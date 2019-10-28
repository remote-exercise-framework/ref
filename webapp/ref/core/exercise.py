import enum
import os
import random
import shutil
import subprocess
import time
import traceback
import typing
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from threading import Thread

import docker
import yaml
from flask import current_app

from ref.model import (Exercise, ExerciseEntryService, ExerciseInstance,
                       ExerciseInstanceEntryService, ExerciseService, User)
from ref.model.enums import ExerciseBuildStatus

from .docker import DockerClient


class ExerciseConfigError(Exception):
    pass


class ExerciseImageManager():
    """
    This class is used to manage the image that belong to a exercise.
    """

    def __init__(self, exercise: Exercise):
        self._d = DockerClient()
        self.exercise = exercise

    def is_build(self) -> bool:
        """
        Check whether all services images where build.
        """

        #Check the image of the entry service
        image_name = self.exercise.entry_service.image_name
        image = self._d.image(image_name)
        if not image:
            return False

        #TODO: Multiple serviceses not supported
        assert len(self.exercise.services) == 0

        return True

    @staticmethod
    def __build_template(app, files, build_cmd):
        with app.app_context():
            base = app.config['BASE_IMAGE_NAME']
        template = f'FROM {base}\n'

        #Copy files into image
        if files:
            for f in files:
                template += f'COPY {f} /home/user/{f}\n'

        #Run custom commands
        if build_cmd:
            for line in build_cmd:
                template += f'RUN {line}\n'

        return template

    @staticmethod
    def __docker_build(build_ctx_path, tag, dockerfile='Dockerfile'):
        log = ""
        try:
            client = docker.from_env()
            images = client.images
            image, json_log = images.build(path=build_ctx_path, tag=tag, dockerfile=dockerfile)
            json_log = list(json_log)
        except Exception as e:
            raise e
        else:
            for l in json_log:
                if 'stream' in l:
                    log += l['stream']
            return log

    @staticmethod
    def __run_build_entry_service(app, exercise: Exercise):
        """
        Builds the entry service of an exercise.
        """
        log = ' --- Building entry service --- \n'
        image_name = exercise.entry_service.image_name

        dockerfile = ExerciseImageManager.__build_template(
            app,
            exercise.entry_service.files,
            exercise.entry_service.build_cmd
        )
        build_ctx = exercise.template_path
        try:
            with open(f'{build_ctx}/Dockerfile-entry', 'w') as f:
                f.write(dockerfile)
            log += ExerciseImageManager.__docker_build(build_ctx, image_name, dockerfile='Dockerfile-entry')
        except Exception as e:
            raise e

        #Make a copy of the data that needs to be persisted
        if exercise.entry_service.persistance_container_path:
            client = DockerClient()
            log += client.copy_from_image(
                image_name,
                exercise.entry_service.persistance_container_path,
                client.path_to_local(exercise.entry_service.persistance_lower)
                )

        return log


    @staticmethod
    def __run_build(app, exercise: Exercise):
        log = ""
        try:
            #Build entry service
            log += ExerciseImageManager.__run_build_entry_service(app, exercise)

            #TODO: Build other services

        except Exception as e:
            with app.app_context():
                if isinstance(e, docker.errors.ContainerError):
                    if e.stderr:
                        log = e.stderr.decode()
                log += traceback.format_exc()
                #Update instance since is might changed in the meantime
                exercise: Exercise = app.db.get(Exercise, id=exercise.id)
                exercise.build_job_result = log
                exercise.build_job_status = ExerciseBuildStatus.FAILED
        else:
            with app.app_context():
                e = traceback.format_exc()
                #Update instance since is might changed in the meantime
                exercise: Exercise = app.db.get(Exercise, id=exercise.id)
                exercise.build_job_result = log
                exercise.build_job_status = ExerciseBuildStatus.FINISHED

        with app.app_context():
            try:
                app.db.session.add(exercise)
                app.db.session.commit()
            except Exception as e:
                current_app.logger.error(str(e))

    def build(self):
        """
        Builds an image from the given exercise. This process happens in
        a separate thread that updates the exercise after the build process
        finished. After the build process terminated, the exercises build_job_status
        is ExerciseBuildStatus.FAILED or ExerciseBuildStatus.FINISHED.
        """
        assert not self.is_build()

        t = Thread(target=ExerciseImageManager.__run_build, args=(current_app._get_current_object(), self.exercise))
        t.start()

    def remove(self):
        """
        Deletes the image associated to exercise.
        """

        #Delete docker image of entry service
        image_name = self.exercise.entry_service.image_name
        if self._d.image(image_name):
            img = self._d.rmi(image_name)

        #Remove template
        if os.path.isdir(self.exercise.template_path):
            shutil.rmtree(self.exercise.template_path)

        #Remove overlay
        if os.path.isdir(self.exercise.persistence_path):
            subprocess.check_call(f'sudo rm -rf {self.exercise.persistence_path}', shell=True)


#What is about admins and containers?
#Student -> User with is_admin flag?

class ExerciseInstanceManager():
    """
    Used to manage ExerciseInstance's.
    """

    def __init__(self, instance: ExerciseInstance):
        self._d = DockerClient()
        self.instance = instance

    @staticmethod
    def create_instance(user: User, exercise: Exercise) -> ExerciseInstance:
        """
        Creates an instance of the given exercise for the given user.
        """
        instance = ExerciseInstance()
        instance.exercise = exercise
        instance.user = user

        persistance = Path(instance.persistance_path())
        assert not persistance.exists()
        persistance.mkdir(parents=True)

        #Get the container ID of the ssh container, thus we can connect the new instance
        #to it.
        dc = DockerClient()
        ssh_container = dc.container(current_app.config['SSHSERVER_CONTAINER_NAME'])

        #Create a network. The bridge of an internal network is not connected
        #to the host (i.e., the host has no interface attached to it).
        network = dc.create_network(internal=True)

        #Make the ssh server join the network
        current_app.logger.info(f'connecting {ssh_container.id} to network')
        network.connect(ssh_container)
        instance.network_id = network.id

        #Create the entry container
        entry_service = ExerciseInstanceEntryService()
        entry_service.instance = instance
        #instance.entry_service = entry_service

        persistance = Path(entry_service.overlay_upper())
        assert not persistance.exists()
        persistance.mkdir(parents=True)

        persistance = Path(entry_service.overlay_work())
        assert not persistance.exists()
        persistance.mkdir(parents=True)

        persistance = Path(entry_service.overlay_merged())
        assert not persistance.exists()
        persistance.mkdir(parents=True)

        image_name = exercise.entry_service.image_name
        #Create container that is initally connected to the 'none' network
        capas = ['CAP_SYS_PTRACE']
        container = dc.create_container(image_name, network_mode='none', volumes=mounts, cap_add=capas)

        #Remove created container from 'none' network
        none_network = dc.network('none')
        none_network.disconnect(container)

        network.connect(container)

        entry_service.container_id = container.id

        current_app.db.session.add(entry_service)
        current_app.db.session.add(instance)

        return instance

    def get_entry_ip(self):
        """
        Returns the IP of entry service that can be used by the SSH server to forward connections.
        """
        dc = DockerClient()
        network = dc.network(self.instance.network_id)
        container = dc.container(self.instance.entry_service.container_id)
        current_app.logger.info(f'Getting IP of container {self.instance.entry_service.container_id} on network {self.instance.network_id}')
        ip = dc.container_get_ip(container, network)
        current_app.logger.info(f'IP is {ip}')
        return ip.split('/')[0]

    def start(self):
        """
        Starts the given instance.
        """
        ssh_container = self._d.container(current_app.config['SSHSERVER_CONTAINER_NAME'])

        #Create a network
        network = self._d.create_network(internal=False)

        #Make the ssh server join the network
        current_app.logger.info(f'connecting {ssh_container.id} to network')
        network.connect(ssh_container)
        self.instance.network_id = network.id

        image_name = self.instance.exercise.entry_service.image_name
        container = self._d.create_container(image_name)
        network.connect(container)

        self.instance.entry_service.container_id = container.id
        current_app.db.session.add(self.instance)
        current_app.db.session.commit()


    def _stop_networks(self):
        network = self._d.network(self.instance.network_id)
        if not network:
            return
        network.reload()
        for c in network.containers:
            network.disconnect(c)
        network.remove()

    def _stop_containers(self):
        entry_container = self.instance.entry_service.container_id
        if not entry_container:
            return
        entry_container = self._d.container(entry_container)
        if entry_container:
            entry_container.kill()

    def stop(self):
        """
        Stops the given instance. The state is persisted, thus the instance can later be
        started again by calling start().
        """
        try:
            self._stop_networks()
        except Exception as e:
            #FIXME: If a network contains an already removed container, stopping it fails.
            #For now, we just ignore this, since this seems to be a known docker issue.
            current_app.logger.info(f'Failed to stop networking: {e}')

        self._stop_containers()

        #Sync state back to DB
        self.instance.entry_service.container_id = None
        self.instance.network_id = None
        current_app.db.session.add(self.instance)
        current_app.db.session.commit()


    def is_running(self):
        """
        Check whether all components of the instance are running.
        """
        if not self.instance.entry_service.container_id:
            return False
        if not self.instance.network_id:
            return False

        container = self._d.container(self.instance.entry_service.container_id)
        if not container or container.status != 'running':
            return False
        network = self._d.network(self.instance.network_id)
        if not network:
            return False
        return True

    def get_container(self, instance: ExerciseInstance):
        """
        Returns an instance of DockerContainer. In case the
        instance is currently stopped, it is started again.
        """

    def remove(self):
        """
        Kill the instance and remove all associated persisted data.
        After calling this function, the given instance is deleted from the DB.
        """
        self.stop()
        if os.path.exists(self.instance.persistance_path()):
            shutil.rmtree(self.instance.persistance_path())
        current_app.db.session.delete(self.instance.entry_service)
        current_app.db.session.delete(self.instance)
        current_app.db.session.commit()

    def update(self, instance: ExerciseInstance, exercise: Exercise) -> ExerciseInstance:
        pass

    def get_instance(self, exercise: Exercise, user: User) -> ExerciseInstance:
        """
        Returns a ExerciseInstance of the given exercise bound to the given user.
        """


class ExerciseManager():

    def __init__(self, exercise: Exercise):
        self.exercise = exercise

    def image_manager(self) -> ExerciseImageManager:
        return ExerciseImageManager(self.exercise)

    def instance_manager(self) -> ExerciseInstanceManager:
        return ExerciseInstanceManager(self.exercise)

    @staticmethod
    def _parse_attr(yaml_dict, attr_name, expected_type, required=True, default=None):
        if required:
            if attr_name not in yaml_dict or yaml_dict[attr_name] == None:
                raise ExerciseConfigError(f'Missing required attribute {attr_name}')
        else:
            if attr_name not in yaml_dict or yaml_dict[attr_name] == None:
                if attr_name in yaml_dict:
                    del yaml_dict[attr_name]
                return default

        if not isinstance(yaml_dict[attr_name], expected_type):
            t = type(yaml_dict[attr_name])
            raise ExerciseConfigError(f'Type of attribute {attr_name} is {t}, but {expected_type} was expected.')

        ret = yaml_dict[attr_name]
        del yaml_dict[attr_name]
        return ret

    @staticmethod
    def _from_yaml(path) -> Exercise:
        """
        Parses the given yaml config of an exercise.
        Raises:
            - ExerciseConfigError if the given config could not be parsed.
        """
        exercise = Exercise()

        try:
            with open(path, 'r') as f:
                cfg = f.read()
            cfg = yaml.load(cfg)
        except Exception as e:
            raise ExerciseConfigError(str(e))

        #General metadata describing the exercise
        exercise.short_name = ExerciseManager._parse_attr(cfg, 'short-name', str)
        exercise.description = ExerciseManager._parse_attr(cfg, 'description', str)
        exercise.version = ExerciseManager._parse_attr(cfg, 'version', int)
        exercise.is_default = False
        exercise.build_job_status = ExerciseBuildStatus.NOT_BUILD

        #Check if there is an entry service
        if 'entry' not in cfg:
            raise ExerciseConfigError('An exercise must have exactly one "entry" section')

        #We got an entry section, parse it
        entry = ExerciseEntryService()
        exercise.entry_service = entry
        entry.exercise = exercise
        entry_cfg = cfg['entry']

        entry.files = ExerciseManager._parse_attr(entry_cfg, 'files', list, required=False, default=None)
        if entry.files:
            for f in entry.files:
                if not isinstance(f, str):
                    raise ExerciseConfigError(f'Files must be a list of strings {entry.files}')

        cmd = ExerciseManager._parse_attr(entry_cfg, 'build-cmd', list, required=False, default=None)
        entry.build_cmd = None
        if cmd:
            entry.build_cmd = []
            for line in cmd:
                if not isinstance(line, str):
                    raise ExerciseConfigError(f"Command must be a list of strings: {cmd}")
                entry.build_cmd += [f"{line}"]

        entry.disable_aslr = ExerciseManager._parse_attr(entry_cfg, 'disable-aslr', bool, required=False, default=False)
        entry.cmd = ExerciseManager._parse_attr(entry_cfg, 'cmd', list, required=False, default='/bin/bash')

        entry.persistance_container_path = ExerciseManager._parse_attr(entry_cfg, 'persistance-path', str, required=False, default=None)

        return exercise

    @staticmethod
    def create(exercise: Exercise):
        template_path = Path(current_app.config['IMPORTED_EXERCISES_PATH'])
        template_path = template_path.joinpath(f'{exercise.short_name}-{exercise.version}')
        assert not template_path.exists()

        persistence_path = Path(current_app.config['PERSISTANCE_PATH'])
        persistence_path = persistence_path.joinpath(f'{exercise.short_name}-{exercise.version}')
        assert not persistence_path.exists()
        persistence_path.mkdir(parents=True)
        exercise.persistence_path = persistence_path.as_posix()


        template_path = template_path.as_posix()
        #Copy data from import folder into an internal folder
        shutil.copytree(exercise.template_import_path, template_path)
        exercise.template_path = template_path
        return ExerciseManager(exercise)

    @staticmethod
    def from_template(path: str) -> Exercise:
        """
        Parses the template in the given folder. This only returns a Exercise
        without copying its data to the local storage. Before commiting it to the DB,
        ExerciseManager.create(exercise) must be called.
        Raises:
            - ExerciseConfigError if the template could not be parsed.
        """
        if hasattr(path, 'as_posix'):
            path = path.as_posix()
        cfg = os.path.join(path, 'settings.yml')
        exercise = ExerciseManager._from_yaml(cfg)
        exercise.template_import_path = path

        return exercise

    def get_instances(self) -> typing.List[ExerciseInstance]:
        """
        Returns all instances of the given exercise.
        """
        instances = ExerciseInstance.query.filter(ExerciseInstance.exercise == self.exercise).all()
        return instances

    def remove(self, exercise: Exercise):
        """
        Removes all data associated to the given exercise. After calling this function,
        the given exercise should be removed from the DB.
        """
