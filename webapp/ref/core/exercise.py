import enum
import os
import random
import re
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
import itsdangerous
import yaml
from flask import current_app
from werkzeug.local import LocalProxy

from ref.model import (Exercise, ExerciseEntryService, Instance,
                       InstanceEntryService, ExerciseService, User, ExerciseService)

from ref.model.enums import ExerciseBuildStatus

from .docker import DockerClient

log = LocalProxy(lambda: current_app.logger)

class ExerciseConfigError(Exception):
    pass


class ExerciseImageManager():
    """
    This class is used to manage an image that belong to an exercise.
    """

    def __init__(self, exercise: Exercise):
        self.dc = DockerClient()
        self.exercise = exercise

    def is_build(self) -> bool:
        """
        Check whether all docker images that belong to the exercise where build.
        """

        #Check entry service docker image
        image_name = self.exercise.entry_service.image_name
        image = self.dc.image(image_name)
        if not image:
            return False

        return True

    @staticmethod
    def __build_template(app, files, build_cmd, disable_aslr):
        """
        Returns a dynamically build docker file as string.
        """
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

        if disable_aslr:
            template += 'CMD ["/usr/bin/setarch", "x86_64", "-R", "/usr/sbin/sshd", "-D"]\n'
        else:
            template += 'CMD ["/usr/sbin/sshd", "-D"]\n'


        return template

    @staticmethod
    def __docker_build(build_ctx_path, tag, dockerfile='Dockerfile'):
        """
        Builds a docker image using the dockerfile named 'dockerfile'
        that is located at path 'build_ctx_path'.
        """
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
            exercise.entry_service.build_cmd,
            exercise.entry_service.disable_aslr
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
                client.local_path_to_host(exercise.entry_service.persistance_lower)
                )

        return log


    @staticmethod
    def __run_build(app, exercise: Exercise):
        """
        Builds all docker images that are needed by the passed exercise.
        """
        log = ""
        try:
            #Build entry service
            log += ExerciseImageManager.__run_build_entry_service(app, exercise)

            #TODO: Build other services

        except Exception as e:
            with app.app_context():
                if isinstance(e, docker.errors.BuildError):
                    for l in list(e.build_log):
                        if 'stream' in l:
                            log += l['stream']
                elif isinstance(e, docker.errors.ContainerError):
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
                log.error(str(e))

    def build(self):
        """
        Builds all images required for the exercise. This process happens in
        a separate thread that updates the exercise after the build process
        finished. After the build process terminated, the exercises build_job_status
        is ExerciseBuildStatus.FAILED or ExerciseBuildStatus.FINISHED.
        """
        assert not self.is_build()

        t = Thread(target=ExerciseImageManager.__run_build, args=(current_app._get_current_object(), self.exercise))
        t.start()

    def remove(self):
        """
        Deletes all images associated to the exercise.
        """

        #Delete docker image of entry service
        image_name = self.exercise.entry_service.image_name
        if self.dc.image(image_name):
            img = self.dc.rmi(image_name)

        #Remove template
        if os.path.isdir(self.exercise.template_path):
            shutil.rmtree(self.exercise.template_path)

        #Remove overlay
        if os.path.isdir(self.exercise.persistence_path):
            subprocess.check_call(f'sudo rm -rf {self.exercise.persistence_path}', shell=True)

class ExerciseManager():
    """
    Used to manage an Exercise.
    """

    def __init__(self, exercise: Exercise):
        self.exercise = exercise

    def image_manager(self) -> ExerciseImageManager:
        return ExerciseImageManager(self.exercise)

    def instance_manager(self) -> InstanceManager:
        return InstanceManager(self.exercise)

    @staticmethod
    def _parse_attr(yaml_dict, attr_name, expected_type, required=True, default=None):
        if required:
            if attr_name not in yaml_dict or yaml_dict[attr_name] == None:
                raise ExerciseConfigError(f'Missing required attribute "{attr_name}"')
        else:
            if attr_name not in yaml_dict or yaml_dict[attr_name] == None:
                if attr_name in yaml_dict:
                    del yaml_dict[attr_name]
                return default

        if not isinstance(yaml_dict[attr_name], expected_type):
            t = type(yaml_dict[attr_name])
            raise ExerciseConfigError(f'Type of attribute "{attr_name}" is {t}, but {expected_type} was expected.')

        ret = yaml_dict[attr_name]
        del yaml_dict[attr_name]
        return ret

    @staticmethod
    def _from_yaml(path) -> Exercise:
        """
        Parses the given yaml config of an exercise and returns an Exercise on success.
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
        short_name_regex = r'([a-zA-Z0-9._])*'
        if not re.fullmatch(short_name_regex, exercise.short_name):
            raise ExerciseConfigError(f'short-name "{exercise.short_name}" is invalid ({short_name_regex})')

        exercise.category = ExerciseManager._parse_attr(cfg, 'category', str)

        exercise.description = ExerciseManager._parse_attr(cfg, 'description', str, required=False, default="")

        exercise.version = ExerciseManager._parse_attr(cfg, 'version', int)
        exercise.allow_internet = ExerciseManager._parse_attr(cfg, 'allow-internet', bool, required=False, default=False)
        exercise.is_default = False
        exercise.build_job_status = ExerciseBuildStatus.NOT_BUILD

        #Check for unknown attrs (ignore 'services' and 'entry')
        unparsed_keys = list(set(cfg.keys()) - set(['entry', 'services']))
        if unparsed_keys:
            raise ExerciseConfigError(f'Unknown key(s) {unparsed_keys}')

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
        entry.readonly = ExerciseManager._parse_attr(entry_cfg, 'read-only', bool, required=False, default=False)
        entry.bind_executable = ExerciseManager._parse_attr(entry_cfg, 'bind-executable', str, required=False, default=None)

        if entry.readonly and entry.persistance_container_path:
            raise ExerciseConfigError('persistance-path and readonly are mutually exclusive')

        #Check for unknown attrs
        unparsed_keys = list(entry_cfg.keys())
        if unparsed_keys:
            raise ExerciseConfigError(f'Unknown key(s) in entry service configuration {unparsed_keys}')

        #Parse peripheral services
        peripheral_cfg = cfg.get('services')
        if not peripheral_cfg:
            return exercise

        services = []
        for service_name, service_values in peripheral_cfg.items():
            service = ExerciseService()
            service_name_regex = r'([a-zA-Z0-9_-])*'
            if not re.fullmatch(service_name_regex, service_name):
                raise ExerciseConfigError(f'Service name "{service_name}"" is invalid ({service_name_regex})')
            service.name = service_name

            service.disable_aslr = ExerciseManager._parse_attr(service_values, 'disable-aslr', bool, required=False, default=False)

            service.files = ExerciseManager._parse_attr(service_values, 'files', list, required=False, default=None)
            if entry.files:
                for f in service.files:
                    if not isinstance(f, str):
                        raise ExerciseConfigError(f'Files must be a list of strings {service.files}')

            service.build_cmd = ExerciseManager._parse_attr(service_values, 'build-cmd', list, required=False, default=None)
            if service.build_cmd:
                for line in service.build_cmd:
                    if not isinstance(line, str):
                        raise ExerciseConfigError(f"Command must be a list of strings: {cmd}")

            service.cmd = ExerciseManager._parse_attr(service_values, 'cmd', str)
            services.append(service)

        return exercise

    @staticmethod
    def create(exercise: Exercise):
        """
        Copies all data that belong to the passed exercise to a local folder.
        After calling this function, the exercise *must* be added to the DB and can be used
        to create new instances.
        """
        template_path = Path(current_app.config['IMPORTED_EXERCISES_PATH'])
        template_path = template_path.joinpath(f'{exercise.short_name}-{exercise.version}')
        log.info(f'Creating {template_path}')
        assert not template_path.exists()

        persistence_path = Path(current_app.config['PERSISTANCE_PATH'])
        persistence_path = persistence_path.joinpath(f'{exercise.short_name}-{exercise.version}')
        log.info(f'Creating {persistence_path}')
        assert not persistence_path.exists()

        persistence_path.mkdir(parents=True)
        exercise.persistence_path = persistence_path.as_posix()

        try:
            #Copy data from import folder into an internal folder
            shutil.copytree(exercise.template_import_path, template_path.as_posix())
        except:
            #Restore state as before create() was called.
            if template_path.exists():
                shutil.rmtree(template_path.as_posix())
            shutil.rmtree(persistence_path.as_posix())

        exercise.template_path = template_path.as_posix()
        return ExerciseManager(exercise)

    @staticmethod
    def from_template(path: str) -> Exercise:
        """
        Parses the template in the given folder. This only returns a Exercise
        without copying its data to the local storage nor adding it to the current transaction.
        Before commiting it to the DB, ExerciseManager.create(exercise) must be called.
        Raises:
            - ExerciseConfigError if the template could not be parsed.
        """
        if hasattr(path, 'as_posix'):
            path = path.as_posix()
        cfg = os.path.join(path, 'settings.yml')
        exercise = ExerciseManager._from_yaml(cfg)
        exercise.template_import_path = path

        return exercise

    def get_instances(self) -> typing.List[Instance]:
        """
        Returns all instances of the given exercise.
        """
        instances = Instance.query.filter(Instance.exercise == self.exercise).all()
        return instances
