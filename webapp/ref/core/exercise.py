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

class ExerciseInstanceManager():
    """
    Used to manage a ExerciseInstance.
    """

    def __init__(self, instance: Instance):
        self.dc = DockerClient()
        self.instance = instance

    @staticmethod
    def create_instance(user: User, exercise: Exercise) -> Instance:
        """
        Creates an instance of the given exercise for the given user.
        After creating an instance, .start() must be used to start it.
        If the new instance was successfully created, it is added to the current
        DB transaction.
        """
        instance = Instance()
        instance.exercise = exercise
        instance.user = user
        exercise.instances.append(instance)

        #Create the entry container
        entry_service = InstanceEntryService()
        entry_service.instance = instance

        dirs = [
            Path(instance.persistance_path),
            Path(entry_service.overlay_upper()),
            Path(entry_service.overlay_work()),
            Path(entry_service.overlay_merged())
        ]
        try:
            for d in dirs:
                d.mkdir(parents=True)
        except:
            #If a directory already exists, our system is inconsistent.
            for d in dirs:
                if d.exists():
                    shutil.rmtree(d.as_posix())
            raise

        current_app.db.session.add(entry_service)
        current_app.db.session.add(instance)

        return instance

    def update_instance(self, new_exercise: Exercise) -> Instance:
        """
        Updates the instance to the new exercise version new_exercise.
        The passed exercise must be a newer version of the exercise currently attached
        to the instance.
        Returns a new running instance.
        On error and exception is raised and the current instance might be stopped.
        """
        assert self.instance.exercise.short_name == new_exercise.short_name
        assert self.instance.exercise.version < new_exercise.version

        #Create new instance.
        new_instance = ExerciseInstanceManager.create_instance(self.instance.user, new_exercise)
        new_mgr = ExerciseInstanceManager(new_instance)

        #NOTE: We need to take care of deleteing the new instance if anything down below fails.

        try:
            new_mgr.start()
        except:
            try:
                new_mgr.remove()
            except:
                #No way to resolve this, just log it and hope for the best.
                log.error(f'Failed to remove newly created instance {new_instance} during update of {self.instance}', exc_info=True)
            raise

        try:
            #Make sure the updated instance is not running
            self.stop()
            #Copy old persisted data. If the new exercise version is readonly, the persisted data is discarded.
            if not new_exercise.entry_service.readonly and self.instance.exercise.entry_service.persistance_container_path:
                #We are working directly on the merged directory, since changeing the upper dir itself causes issues:
                #[328100.750176] overlayfs: failed to verify origin (entry-server/lower, ino=31214863, err=-116)
                #[328100.750178] overlayfs: failed to verify upper root origin
                cmd = f'sudo cp -arT {self.instance.entry_service.overlay_upper()} {new_instance.entry_service.overlay_merged()}'
                subprocess.check_call(cmd, shell=True)
        except:
            try:
                #Stop and remove the new instance
                new_mgr.remove()
            except:
                log.error(f'Failed to remove new instance {new_instance} during update of {self.instance}', exc_info=True)
            raise

        try:
            #Remove old instance and all persisted data
            self.remove()
        except:
            #If this fails, we have two instances for one user. How do we deal with this?
            #We need to keep the new instance since it contains the persisted user data and
            #the old instance might be corrupted.
            log.error(f'Failed to remove old instance {self.instance}')
            raise

        return new_instance


    def get_entry_ip(self):
        """
        Returns the IP of entry service that can be used by the SSH server to forward connections.
        """
        network = self.dc.network(self.instance.network_id)
        container = self.dc.container(self.instance.entry_service.container_id)
        log.info(f'Getting IP of container {self.instance.entry_service.container_id} on network {self.instance.network_id}')
        ip = self.dc.container_get_ip(container, network)
        log.info(f'IP is {ip}')
        return ip.split('/')[0]

    def start(self):
        """
        Starts the given instance.
        """
        #Make sure everything is cleaned up
        self.stop()

        exercise: Exercise = self.instance.exercise
        exercise_entry_service = exercise.entry_service
        instance_entry_service = self.instance.entry_service
        #Get the container ID of the ssh container, thus we can connect the new instance
        #to it.
        ssh_container = self.dc.container(current_app.config['SSHSERVER_CONTAINER_NAME'])

        #Create a network. The bridge of an internal network is not connected
        #to the host (i.e., the host has no interface attached to it).
        network_name = f'ref-{self.instance.exercise.short_name}-v{self.instance.exercise.version}-ssh-to-entry-{self.instance.id}'
        network = self.dc.create_network(name=network_name, internal=not self.instance.exercise.allow_internet)

        #Make the ssh server join the network
        log.info(f'connecting {ssh_container.id} to network')
        network.connect(ssh_container)
        self.instance.network_id = network.id

        #Mounts of the entry services
        mounts = None
        if exercise_entry_service.persistance_container_path:
            assert not exercise_entry_service.readonly
            #Create overlay for the container persistance. All changes made by the student are recorded in the upper dir.
            #In case an update of the container is necessary, we can replace the lower dir with a new one and reuse the upper
            #dir. The directory used as mount target (overlay_merged) has shared mount propagation, i.e., mounts done in this
            #directory are propageted to the host. This is needed, since we are mounting this merged directory into a container
            #that is started by the host (see below for further details).
            cmd = [
                'sudo', '/bin/mount', '-t', 'overlay', 'overlay',
                f'-olowerdir={exercise.entry_service.persistance_lower},upperdir={instance_entry_service.overlay_upper()},workdir={instance_entry_service.overlay_work()}',
                f'{instance_entry_service.overlay_merged()}'
            ]
            subprocess.check_call(cmd)

            #FIXME: Fix mountpoint permissions, thus the folder is owned by the container user "user".
            cmd = f'sudo chown 9999:9999 {instance_entry_service.overlay_merged()}'
            subprocess.check_call(cmd, shell=True)

            #Since we are using the hosts docker deamon, the mount source must be a path that is mounted in the hosts tree,
            #hence we need to translate the locale mount path to a host path.
            mounts = {
                self.dc.local_path_to_host(instance_entry_service.overlay_merged()): {'bind': '/home/user', 'mode': 'rw'}
                }
            log.info(f'mounting persistance {mounts}')
        else:
            log.info('Container is readonly')


        image_name = exercise.entry_service.image_name
        #Create container that is initally connected to the 'none' network

        #Allow the usage of ptrace, thus we can use gdb
        capabilities = ['SYS_PTRACE']

        #Apply a custom seccomp profile that allows the personality syscall to disable ASLR
        with open('/app/seccomp.json', 'r') as f:
            seccomp_profile = f.read()

        cpu_period = current_app.config['EXERCISE_CONTAINER_CPU_PERIOD']
        cpu_quota = current_app.config['EXERCISE_CONTAINER_CPU_QUOTA']
        mem_limit = current_app.config['EXERCISE_CONTAINER_MEMORY_LIMIT']

        seccomp_profile = [f'seccomp={seccomp_profile}']
        entry_container_name = f'ref-{self.instance.exercise.short_name}-v{self.instance.exercise.version}-entry-{self.instance.id}'
        container = self.dc.create_container(
            image_name,
            name=entry_container_name,
            network_mode='none',
            volumes=mounts,
            cap_add=capabilities,
            security_opt=seccomp_profile,
            cpu_quota=cpu_quota,
            cpu_period=cpu_period,
            mem_limit=mem_limit,
            read_only=exercise.entry_service.readonly
            )
        instance_entry_service.container_id = container.id

        #Add users public key to authorized_keys
        add_key_cmd = f'bash -c "echo {self.instance.user.pub_key_ssh} >> /home/user/.ssh/authorized_keys"'
        success = container.exec_run(add_key_cmd)
        log.info(f'Add ssh key ret={success}')
        #TODO: Handle errors

        #Store token inside container that can be used to authenticate requests
        #from the container to, e.g., web.
        signer = itsdangerous.Serializer(current_app.config['SECRET_KEY'])
        token = {'instance_id': self.instance.user.id, 'container_id': container.id}
        signature = signer.dumps(token)

        add_token_cmd = f'bash -c "echo {signature} > /etc/auth_token && chmod 400 /etc/auth_token"'
        success = container.exec_run(add_token_cmd)
        log.info(f'Add token ret={success}')

        #Remove created container from 'none' network
        none_network = self.dc.network('none')
        none_network.disconnect(container)

        #Join the network of the ssh server
        network.connect(container)

        current_app.db.session.add(self.instance)


    def _stop_networks(self):
        if self.instance.network_id:
            network = self.dc.network(self.instance.network_id)
            if not network:
                return
            containers = self.dc.get_connected_container(network)
            for c in containers:
                c = self.dc.container(c)
                if c:
                    network.disconnect(c)
                else:
                    log.warning(f'Network of instance {self.instance} contains dead containers')
            network.remove()

    def _stop_containers(self):
        entry_container = self.instance.entry_service.container_id
        if entry_container:
            entry_container = self.dc.container(entry_container)
            if entry_container and entry_container.status == 'running':
                entry_container.kill()

    def _remove_container(self):
        entry_container = self.instance.entry_service.container_id
        if entry_container:
            entry_container = self.dc.container(entry_container)
            if entry_container:
                entry_container.remove()

    def stop(self):
        """
        Stops the given instance. The state is persisted, thus the instance can later be
        started again by calling start(). It is safe to call this function on an already
        stopped instance.
        On success the instance is stopped and the DB is updated to reflect the state
        change.
        """
        #Stop the containers, thus the user gets disconnected
        self._stop_containers()

        try:
            self._stop_networks()
        except Exception as e:
            #FIXME: If a network contains an already removed container, stopping it fails.
            #For now, we just ignore this, since this seems to be a known docker issue.
            e = traceback.format_exc()
            log.error(f'Failed to stop networking', exc_info=True)

        #umount entry service persistance
        if os.path.ismount(self.instance.entry_service.overlay_merged()):
            cmd = ['sudo', '/bin/umount', self.instance.entry_service.overlay_merged()]
            subprocess.check_call(cmd)

        self._remove_container()

        #Sync state back to DB
        self.instance.entry_service.container_id = None
        self.instance.network_id = None
        current_app.db.session.add(self.instance)


    def is_running(self):
        """
        Check whether all components of the instance are running.
        This function only returns True if all components are completely healthy.
        """
        if not self.instance.entry_service.container_id:
            return False
        if not self.instance.network_id:
            return False

        entry_container = self.dc.container(self.instance.entry_service.container_id)
        if not entry_container or entry_container.status != 'running':
            return False

        ssh_to_entry_network = self.dc.network(self.instance.network_id)
        if not ssh_to_entry_network:
            return False

        ssh_container = self.dc.container(current_app.config['SSHSERVER_CONTAINER_NAME'])
        assert ssh_container

        #Check if the ssh container is connected to our network. This might not be the case if the ssh server
        #was removed and restarted with a new id that is not part of our network anymore.
        #i.e., docker-compose down -> docker-compose up
        ssh_to_entry_network.reload()
        containers = ssh_to_entry_network.containers
        if ssh_container not in containers:
            return False

        #Check if the entry container is part of the network
        if entry_container not in containers:
            return False

        return True

    def remove(self):
        """
        Kill the instance and remove all associated persisted data.
        NOTE: After callin this function, the instance must be removed from the DB.
        """
        self.stop()
        try:
            if os.path.exists(self.instance.persistance_path):
                subprocess.check_call(f'sudo rm -rf {self.instance.persistance_path}', shell=True)
        except:
            log.error(f'Error during removal of if instance {self.instance}')
            raise

        current_app.db.session.delete(self.instance.entry_service)
        current_app.db.session.delete(self.instance)


class ExerciseManager():
    """
    Used to manage an Exercise.
    """

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
