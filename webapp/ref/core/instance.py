import base64
import binascii
import datetime
import hashlib
import os
import re
import shutil
import subprocess
from sys import exc_info
import tarfile
import traceback
from io import BytesIO, StringIO
from pathlib import Path
from typing import List

import itsdangerous
from flask import current_app
from werkzeug.local import LocalProxy

from ref.core import InconsistentStateError, inconsistency_on_error
from ref.model import (Instance, InstanceEntryService, InstanceService,
                       Submission, User, RessourceLimits)
from ref.model import SubmissionTestResult

from .docker import DockerClient
from .exercise import Exercise, ExerciseService

log = LocalProxy(lambda: current_app.logger)

class InstanceManager():
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

        Args:
            user: The user the instance is created for.
            exercise: The exercise of that an instance is created.
        Raises:
            *: If the instance creation failed.
            InconsistentStateError: If the instance creation failed and left the system
                in an inconsistent state.
        Returns:
            The created instance.
        """
        instance = Instance()
        instance.creation_ts = datetime.datetime.utcnow()
        instance.exercise = exercise
        instance.user = user
        exercise.instances.append(instance)

        #Create the entry service
        entry_service = InstanceEntryService()
        instance.entry_service = entry_service

        #Create the peripheral services
        for service in exercise.services:
            peripheral_service = InstanceService()
            instance.peripheral_services.append(peripheral_service)
            peripheral_service.exercise_service = service

        dirs = [
            Path(instance.persistance_path),
            Path(entry_service.overlay_upper),
            Path(entry_service.overlay_work),
            Path(entry_service.overlay_merged),
            Path(entry_service.overlay_submitted),
            Path(entry_service.shared_folder)
        ]

        def delete_dirs():
            for d in dirs:
                if d.exists():
                    shutil.rmtree(d.as_posix())

        try:
            for d in dirs:
                d.mkdir(parents=True)
            mgr = InstanceManager(instance)
            mgr.mount()
        except:
            #Revert changes
            with inconsistency_on_error(f'Error while aborting instance creation {instance}'):
                delete_dirs()
            raise

        current_app.db.session.add(instance)

        return instance

    def create_submission(self, test_results: List[SubmissionTestResult]) -> Instance:
        """
        Args:
            test_ret: The return value of the submission test (user controlled!)
            test_out: The output of the submission test (user controlled!)
        Creates a new instance that represents a snapshot of the current instance state.
          - This will not check whether associated deadline is passed.
        Raises:
            *: If the instance submission failed.
            InconsistentStateError: If the instance submission failed and left the system
                in an inconsistent state.
        """
        assert not self.instance.submission, f'Can not submit instance {self.instance}, cause it is already part of a submission'

        user = self.instance.user
        exercise = self.instance.exercise

        new_instance = InstanceManager.create_instance(user, exercise)
        new_mgr = InstanceManager(new_instance)

        #Copy user data from the original instance as second lower dir to new instance.
        # XXX: We are working here with mounted overlayfs directories.
        src = self.instance.entry_service.overlay_upper
        dst = new_instance.entry_service.overlay_submitted
        # -a is mandatory, since the upper dir might contain files with extended file attrbiutes (used by overlayfs).
        cmd = f'sudo rsync -arXv {src}/ {dst}/'

        try:
            container = self.dc.container(self.instance.entry_service.container_id)
        except:
            log.error('Error while getting instance container', exc_info=True)
            with inconsistency_on_error():
                new_mgr.remove()
            raise

        try:
            # Make sure no running process is interfering with our copy operation,
            # since, e.g., files disappiring during `cp`` execution cause non zero
            # exit statuses.
            container.pause()
            subprocess.check_call(cmd, shell=True)
            container.unpause()
        except subprocess.CalledProcessError:
            log.error('Error while coping submitted data into new instance.', exc_info=True)
            with inconsistency_on_error():
                new_mgr.remove()
                container.unpause()
            raise

        submission = Submission()
        submission.submission_test_results = test_results
        submission.submission_ts = datetime.datetime.now()
        submission.origin_instance = self.instance
        submission.submitted_instance = new_instance

        try:
            current_app.db.session.add(submission) # type: ignore
            current_app.db.session.add(self.instance) # type: ignore
        except:
            log.error('Error while adding objects to DB', exc_info=True)
            with inconsistency_on_error():
                new_mgr.remove()
            raise

        return new_instance

    def update_instance(self, new_exercise: Exercise) -> Instance:
        """
        Updates the instance to the new exercise version new_exercise.
        The passed exercise must be a newer version of the exercise currently attached
        to the instance.
        Args:
            new_exercise: The exercise the instance should be updated to.
        Raises:
            *: If the instance update failed.
            InconsistentStateError: If an error occurred that caus the system to be left in an
                inconsistent state.
        Returns:
            The new instance that was created.
            NOTE: The caller is responsible to delete the old instance, after an successfull upgrade.
        """
        assert self.instance.exercise.short_name == new_exercise.short_name
        assert self.instance.exercise.version < new_exercise.version
        assert not self.instance.submission, 'Submissions can not be upgraded'

        #Create new instance.
        new_instance = InstanceManager.create_instance(self.instance.user, new_exercise)
        new_mgr = InstanceManager(new_instance)

        try:
            new_mgr.start()
        except:
            log.error('Failed to start new instance.', exc_info=True)
            with inconsistency_on_error():
                new_mgr.remove()

        try:
            #Make sure the updated instance is not running
            self.stop()
            #Copy old persisted data. If the new exercise version is readonly, the persisted data is discarded.
            if not new_exercise.entry_service.readonly and self.instance.exercise.entry_service.persistance_container_path:
                # We are working directly on the merged directory, since changeing the upper dir itself causes issues:
                # [328100.750176] overlayfs: failed to verify origin (entry-server/lower, ino=31214863, err=-116)
                # [328100.750178] overlayfs: failed to verify upper root origin
                # rsync ignores whiteouts created by overlayfs without the --devices argument. Thus, this command will
                # cause whiteouts to be discarded and will only copy user created data into the new distance.
                # So, if the user deleted a file from the lower dir, it will become visible again after an upgrade.
                # FIXME: Transfer whiteouts to new instances during upgrade. Just using --devices causes mount to fail
                # FIXME: with an `stale file error`.
                cmd = f'sudo rsync -arXv {self.instance.entry_service.overlay_upper}/ {new_instance.entry_service.overlay_upper}/'
                subprocess.check_call(cmd, shell=True)
        except:
            log.info('whops', exc_info=True)
            with inconsistency_on_error():
                new_mgr.remove()

        return new_instance


    def get_entry_ip(self):
        """
        Returns the IP of entry service that can be used by the SSH server to forward connections.
        Raises:
            *: If the IP could not be determined.
        """
        network = self.dc.network(self.instance.network_id)
        container = self.dc.container(self.instance.entry_service.container_id)
        log.info(f'Getting IP of container {self.instance.entry_service.container_id} on network {self.instance.network_id}')
        ip = self.dc.container_get_ip(container, network)
        if ip is None:
            raise Exception('Failed to get container IP.')
        log.info(f'IP is {ip}')
        #Split the CIDR suffix
        return ip.split('/')[0]

    def __get_container_config_defaults(self):
        config = {}

        #Apply a custom seccomp:
        # - Allow the personality syscall to disable ASLR
        # - Allow the ptrace syscall by default without requiring SYS_PTRACE.
        #   Thus, gdb can be used but we do not have to grand additional capabilities.
        #   XXX: SYS_PTRACE normally grants additional syscalls. Maybe we need to add them (see seccomp profile).
        with open('/app/seccomp.json', 'r') as f:
            seccomp_profile = f.read()
        config['security_opt'] = [f'seccomp={seccomp_profile}']

        # Drop all capabilities
        config['cap_drop'] = ['ALL']
        # Whitelist
        config['cap_add'] = current_app.config['INSTANCE_CAP_WHITELIST']

        config['cgroup_parent'] = current_app.config['INSTANCES_CGROUP_PARENT']

        return config

    def __get_container_limits_config(self, limits: RessourceLimits):
        config = {}
        log.info(f'limits={limits}')

        cpus = current_app.config['INSTANCE_CONTAINER_CPUS']

        # docker lib does not support `cups`, so we need to calculate it on our own.
        config['cpu_period'] = 100000
        config['cpu_quota'] = int(100000 * cpus)
        config['cpu_shares'] = current_app.config['INSTANCE_CONTAINER_CPU_SHARES']

        config['mem_limit'] = current_app.config['INSTANCE_CONTAINER_MEM_LIMIT']
        config['memswap_limit'] = current_app.config['INSTANCE_CONTAINER_MEM_PLUS_SWAP_LIMIT']
        config['kernel_memory'] = current_app.config['INSTANCE_CONTAINER_MEM_KERNEL_LIMIT']

        # Max number of allocatable PIDs per instance.
        config['pids_limit'] = current_app.config['INSTANCE_CONTAINER_PIDS_LIMIT']

        if not limits:
            # No instance specific limits, return the default.
            return config

        if limits.cpu_cnt_max:
            config['cpu_period'] = 100000
            config['cpu_quota'] = int(100000 * limits.cpu_cnt_max)
        elif limits.cpu_cnt_max == 0:
            # No limit
            del config['cpu_period']
            del config['cpu_quota']

        if limits.cpu_shares:
            config['cpu_shares'] = limits.cpu_shares

        total_mem = 0
        if limits.memory_in_mb:
            config['mem_limit'] = str(limits.memory_in_mb) + 'm'
            total_mem += limits.memory_in_mb

        if limits.memory_swap_in_mb:
            total_mem += limits.memory_swap_in_mb

        if total_mem:
            config['memswap_limit'] = str(total_mem) + 'm'

        if limits.memory_kernel_in_mb:
            config['kernel_memory'] = str(limits.memory_kernel_in_mb) + 'm'

        # All limits are optional!
        if limits.pids_max:
            config['pids_limit'] = limits.pids_max

        log.info(f'Limits config: {config}')
        return config


    def mount(self):
        """
        Mount the persistance of the Instance.
        """
        log.info(f'Mounting persistance of {self.instance}')
        exercise: Exercise = self.instance.exercise
        exercise_entry_service = exercise.entry_service
        instance_entry_service = self.instance.entry_service

        #Mounts of the entry services
        mounts = None
        if exercise_entry_service.persistance_container_path:
            if os.path.ismount(self.instance.entry_service.overlay_merged):
                log.info('Already mounted.')
                return
            assert not exercise_entry_service.readonly

            #Create overlay for the container persistance. All changes made by the student are recorded in the upper dir.
            #In case an update of the container is necessary, we can replace the lower dir with a new one and reuse the upper
            #dir. The directory used as mount target (overlay_merged) has shared mount propagation, i.e., mounts done in this
            #directory are propageted to the host. This is needed, since we are mounting this merged directory into a container
            #that is started by the host (see below for further details).
            cmd = [
                'sudo', '/bin/mount', '-t', 'overlay', 'overlay',
                f'-olowerdir={instance_entry_service.overlay_submitted}:{exercise.entry_service.persistance_lower},upperdir={instance_entry_service.overlay_upper},workdir={instance_entry_service.overlay_work}',
                f'{instance_entry_service.overlay_merged}'
            ]
            subprocess.check_call(cmd)

            #FIXME: Fix mountpoint permissions, thus the folder is owned by the container user "user".
            cmd = f'sudo chown 9999:9999 {instance_entry_service.overlay_merged}'
            subprocess.check_call(cmd, shell=True)

            #Since we are using the hosts docker deamon, the mount source must be a path that is mounted in the hosts tree,
            #hence we need to translate the locale mount path to a host path.
            mounts = {
                self.dc.local_path_to_host(instance_entry_service.overlay_merged): {'bind': '/home/user', 'mode': 'rw'}
                }
            log.info(f'mounting persistance {mounts}')
        else:
            log.info('Container is readonly')

    def umount(self):
        """
        Unmount the persistance of the Instance.
        After calling this function the instance must be mounted again
        or be removed. 
        """
        log.info(f'Unmounting persistance of {self.instance}')
        if os.path.ismount(self.instance.entry_service.overlay_merged):
            cmd = ['sudo', '/bin/umount', self.instance.entry_service.overlay_merged]
            subprocess.check_call(cmd)

    def is_mounted(self):
        return os.path.ismount(self.instance.entry_service.overlay_merged)

    def __start_peripheral_services(self, exercise: Exercise, entry_container):
        """
        Start the peripheral services and the associated networks. Peripheral service
        normally proved a service to the entry service like an application that must be
        exploited over the network.
        """
        services = self.instance.peripheral_services
        if not services:
            return

        #List of services that are allowed to connect to the internet
        internet_services = [service for service in services if service.exercise_service.allow_internet]

        DOCKER_RESSOURCE_PREFIX = f'{current_app.config["DOCKER_RESSOURCE_PREFIX"]}'

        internet_network = None
        if internet_services:
            network_name = f'{DOCKER_RESSOURCE_PREFIX}'
            network_name += f'{self.instance.exercise.short_name}'
            network_name += f'-v{self.instance.exercise.version}-peripheral-internet-{self.instance.id}'
            internet_network = self.dc.create_network(name=network_name, internal=False)
            self.instance.peripheral_services_internet_network_id = internet_network.id

        network_name = f'{DOCKER_RESSOURCE_PREFIX}'
        network_name += f'{self.instance.exercise.short_name}'
        network_name += f'-v{self.instance.exercise.version}-peripheral-to-entry-{self.instance.id}'
        to_entry_network = self.dc.create_network(name=network_name, internal=True)
        self.instance.peripheral_services_network_id = to_entry_network.id

        to_entry_network.connect(entry_container)

        default_config = self.__get_container_config_defaults()
        # Use default settings for peripheral services.
        ressource_limit_config = self.__get_container_limits_config(None)

        config = default_config | ressource_limit_config
        assert (len(default_config) + len(ressource_limit_config)) == len(config)

        #Create container for all services
        for service in services:
            container_name = f'{DOCKER_RESSOURCE_PREFIX}{self.instance.exercise.short_name}'
            container_name += f'-v{self.instance.exercise.version}-{service.exercise_service.name}-{self.instance.id}'
            log.info(f'Creating peripheral container {container_name}')

            container = self.dc.create_container(
                service.exercise_service.image_name,
                name=container_name,
                network_mode='none',
                read_only=service.exercise_service.readonly,
                hostname=service.exercise_service.name,
                **config
            )
            log.info(f'Success, id is {container.id}')

            service.container_id = container.id
            none_network = self.dc.network('none')
            none_network.disconnect(container)

            to_entry_network.connect(container, aliases=[service.exercise_service.name])

            if service.exercise_service.allow_internet:
                internet_network.connect(container)

            current_app.db.session.add(service)

    def start(self):
        """
        Starts the instance. Before calling this function, .stop() should be called.
        Raises:
            *: If starting the instance failed.
            InconsistentStateError: If the starting operation failed, and left the system in an inconsistent state.
        """
        assert self.is_mounted(), 'Instances should always be mounted, except just before they are removed'

        #FIXME: Remove this? It feels wrong to call this each time as a safeguard.
        #Make sure everything is cleaned up (this function can be called regardless of whether the instance is running)
        self.stop()

        exercise: Exercise = self.instance.exercise

        #Class if the EntryService
        exercise_entry_service = exercise.entry_service

        #Object/Instance of the EntryService
        instance_entry_service = self.instance.entry_service

        #Get the container ID of the ssh container, thus we can connect the new instance to it.
        ssh_container = self.dc.container(current_app.config['SSHSERVER_CONTAINER_NAME'])

        #Create a network that connects the entry service with the ssh service.
        entry_to_ssh_network_name = f'{current_app.config["DOCKER_RESSOURCE_PREFIX"]}{self.instance.exercise.short_name}-v{self.instance.exercise.version}-ssh-to-entry-{self.instance.id}'

        #If it is internal, the host does not attach an interface to the bridge, and therefore there is no way
        #of routing data to other endpoints then the two connected containers.
        entry_to_ssh_network = self.dc.create_network(name=entry_to_ssh_network_name, internal=not self.instance.exercise.entry_service.allow_internet)
        self.instance.network_id = entry_to_ssh_network.id

        #Make the ssh server join the network
        log.info(f'Connecting ssh server to network {self.instance.network_id}')

        #aliases makes the ssh_container available to other container through the hostname sshserver
        try:
            entry_to_ssh_network.connect(ssh_container, aliases=['sshserver'])
        except:
            #This will reraise automatically
            with inconsistency_on_error():
                self.dc.remove_network(entry_to_ssh_network)

        image_name = exercise.entry_service.image_name
        #Create container that is initally connected to the 'none' network

        #Apply a custom seccomp profile that allows the personality syscall to disable ASLR
        with open('/app/seccomp.json', 'r') as f:
            seccomp_profile = f.read()

        #Get host path that we are going to mount into the container
        mounts = {}
        if exercise_entry_service.persistance_container_path:
            assert not exercise_entry_service.readonly
            try:
                mounts[self.dc.local_path_to_host(instance_entry_service.overlay_merged)] = {'bind': '/home/user', 'mode': 'rw'}
            except:
                #This will reraise automatically
                with inconsistency_on_error():
                    entry_to_ssh_network.disconnect(ssh_container)
                    self.dc.remove_network(entry_to_ssh_network)

        # A folder that can be used to share data with an instance
        shared_folder_path = '/shared'
        local_shared_folder_path = Path(instance_entry_service.shared_folder)

        # If this is no virgin instance, remove stale shared content.
        if local_shared_folder_path.exists():
            try:
                shutil.rmtree(local_shared_folder_path)
            except:
                with inconsistency_on_error():
                    entry_to_ssh_network.disconnect(ssh_container)
                    self.dc.remove_network(entry_to_ssh_network)

        mounts[self.dc.local_path_to_host(local_shared_folder_path.as_posix())] = {'bind': shared_folder_path, 'mode': 'rw'}


        # Default setting shared by the entry service and the peripheral services.
        default_config = self.__get_container_config_defaults()
        ressource_limit_config = self.__get_container_limits_config(exercise.entry_service.ressource_limit)

        config = default_config | ressource_limit_config
        assert (len(default_config) + len(ressource_limit_config)) == len(config)

        entry_container_name = f'{current_app.config["DOCKER_RESSOURCE_PREFIX"]}'
        entry_container_name += f'{self.instance.exercise.short_name}-v{self.instance.exercise.version}-entry-{self.instance.id}'

        log.info(f'Creating docker container {entry_container_name}')
        try:
            container = self.dc.create_container(
                image_name,
                name=entry_container_name,
                network_mode='none',
                volumes=mounts,
                read_only=exercise.entry_service.readonly,
                hostname=self.instance.exercise.short_name,
                **config
            )
        except:
            #This will reraise automatically
            with inconsistency_on_error():
                entry_to_ssh_network.disconnect(ssh_container)
                self.dc.remove_network(entry_to_ssh_network)

        instance_entry_service.container_id = container.id

        #Scrip that is initially executed to setup the environment.
        # 1. Add the SSH key of the user that owns the container to authorized_keys.
        # FIXME: This key is not actually used for anything right now, since the ssh entry server
        # uses the master key (docker base image authorized_keys) for authentication for all containers.
        # 2. Store the instance ID as string in a file /etc/instance_id.
        container_setup_script = (
            '#!/bin/bash\n'
            'set -e\n'
            f'if ! grep -q "{self.instance.user.pub_key}" /home/user/.ssh/authorized_keys; then\n'
                f'bash -c "echo {self.instance.user.pub_key} >> /home/user/.ssh/authorized_keys"\n'
            'fi\n'
            f'echo -n {self.instance.id} > /etc/instance_id && chmod 400 /etc/instance_id\n'
        )
        if exercise.entry_service.disable_aslr:
            container_setup_script += 'touch /etc/aslr_disabled && chmod 400 /etc/aslr_disabled\n'

        if self.instance.submission:
            container_setup_script += 'touch /etc/is_submission\n'

        self.dc.container_add_file(container, '/tmp/setup.sh', container_setup_script.encode('utf-8'))
        ret = container.exec_run(f'bash -c "/tmp/setup.sh"')
        if ret.exit_code != 0:
            log.info(f'Container setup script failed. ret={ret}')
            with inconsistency_on_error():
                self.dc.stop_container(container, remove=True)
                entry_to_ssh_network.disconnect(ssh_container)
                self.dc.remove_network(entry_to_ssh_network)
            raise Exception('Failed to start instance')

        #Store the instance specific key that is used to sign requests from the container to web.
        instance_key = self.instance.get_key()
        self.dc.container_add_file(container, '/etc/key', instance_key)

        try:
            #Remove created container from 'none' network
            none_network = self.dc.network('none')
            none_network.disconnect(container)

            #Join the network of the ssh server
            entry_to_ssh_network.connect(container)
        except:
            with inconsistency_on_error():
                self.dc.stop_container(container, remove=True)
                entry_to_ssh_network.disconnect(ssh_container)
                self.dc.remove_network(entry_to_ssh_network)
            raise Exception('Failed to establish the instances network connection')

        try:
            self.__start_peripheral_services(exercise, container)
        except Exception as e:
            with inconsistency_on_error():
                entry_to_ssh_network.disconnect(container)
                self.dc.stop_container(container, remove=True)

                entry_to_ssh_network.disconnect(ssh_container)
                self.dc.remove_network(entry_to_ssh_network)
            raise Exception('Failed to start peripheral services') from e

        # Setup SOCKS proxy for SSH port forwarding support.

        # Create a unix domain socket that the SSH entry server will send
        # proxy requests to.
        # We listen on `unix_socket_path` and forward each incoming connection to
        # 127.0.0.1 on port 37777 (where our SOCKS proxy is going to listen on).
        unix_socket_path = f'{shared_folder_path}/socks_proxy'
        unix_to_proxy_cmd = f'socat -d -d -d -lf {shared_folder_path}/proxy-socat.log UNIX-LISTEN:{unix_socket_path},reuseaddr,fork,su=socks TCP:127.0.0.1:37777'
        proxy_cmd = f'/usr/local/bin/microsocks -i 127.0.0.1 -p 37777'
        try:
            log.info(f'Running {unix_to_proxy_cmd}')
            container.exec_run(unix_to_proxy_cmd, detach=True)
            log.info(f'Running {proxy_cmd}')
            ret = container.exec_run(proxy_cmd, user='socks', detach=True)
            log.info(ret)
        except Exception as e:
            with inconsistency_on_error():
                entry_to_ssh_network.disconnect(container)
                self.dc.stop_container(container, remove=True)

                entry_to_ssh_network.disconnect(ssh_container)
                self.dc.remove_network(entry_to_ssh_network)
            raise Exception('Failed start SOCKS proxy') from e


        current_app.db.session.add(self.instance)
        current_app.db.session.add(self.instance.entry_service)

    def _stop_networks(self):
        if self.instance.network_id:
            self.dc.remove_network(self.instance.network_id)
        if self.instance.peripheral_services_internet_network_id:
            self.dc.remove_network(self.instance.peripheral_services_internet_network_id)
        if self.instance.peripheral_services_network_id:
            self.dc.remove_network(self.instance.peripheral_services_network_id)


    def _stop_containers(self):
        entry_container = self.instance.entry_service.container_id
        if entry_container:
            entry_container = self.dc.container(entry_container)
            if entry_container and entry_container.status == 'running':
                entry_container.kill()

        for service in self.instance.peripheral_services:
            if service.container_id:
                container = self.dc.container(service.container_id)
                if container and container.status == 'running':
                    container.kill()

    def _remove_container(self):
        entry_container = self.instance.entry_service.container_id
        if entry_container:
            entry_container = self.dc.container(entry_container)
            if entry_container:
                entry_container.remove()

        for service in self.instance.peripheral_services:
            if service.container_id:
                container = self.dc.container(service.container_id)
                if container:
                    container.remove()

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
        except Exception:
            #FIXME: If a network contains an already removed container, stopping it fails.
            #For now we just ignore this, since this seems to be a known docker issue.
            log.error(f'Failed to stop networking', exc_info=True)

        self._remove_container()

        #Sync state back to DB
        self.instance.entry_service.container_id = None
        self.instance.network_id = None
        self.instance.peripheral_services_network_id = None
        self.instance.peripheral_services_internet_network_id = None
        current_app.db.session.add(self.instance)
        current_app.db.session.add(self.instance.entry_service)

        for service in self.instance.peripheral_services:
            current_app.db.session.add(service)


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

        #Check if all peripheral services are running
        for service in self.instance.peripheral_services:
            c = self.dc.container(service.container_id)
            if not c or c.status != 'running':
                return False

        #If we have peripheral services, check if the network connecting them with
        #the entry service is up.
        if self.instance.peripheral_services:
            if not self.dc.network(self.instance.peripheral_services_network_id):
                return False

        #Check if the internet network for the peripheral services is running (if we have networked container)
        if any(map(lambda e: e.exercise_service.allow_internet, self.instance.peripheral_services)):
            if not self.dc.network(self.instance.peripheral_services_internet_network_id):
                return False

        return True

    def run_tests(self):
        container = self.dc.container(self.instance.entry_service.container_id)
        if not container:
            return 1, 'Failed to access container!'

        run_test_cmd = f'/usr/local/bin/submission_tests'
        ret, output = container.exec_run(run_test_cmd)
        log.info(f'Test output for instance {self.instance} is ret={ret}, out={output}')

        return ret, output

    def bequeath_submissions_to(self, instance: Instance):
        instance.submissions = self.instance.submissions
        self.instance.submissions = []

    def remove(self, bequeath_submissions_to=None):
        """
        Kill the instance and remove all associated persisted data.
        NOTE: After callin this function, the instance must be removed from the DB.
        """
        log.info(f'Deleting instance {self.instance}')
        self.stop()
        self.umount()
        try:
            if os.path.exists(self.instance.persistance_path):
                subprocess.check_call(f'sudo rm -rf {self.instance.persistance_path}', shell=True)
        except:
            log.error(f'Error during removal of instance {self.instance}')
            raise

        for service in self.instance.peripheral_services:
            current_app.db.session.delete(service)

        #Check if the submissions of this instance should be bequeathed by another Instance.
        for submission in self.instance.submissions:
            mgr = InstanceManager(submission.submitted_instance)
            mgr.remove()
            current_app.db.session.delete(submission)

        #If this instance is part of a submission, delete the associated submission object.
        submission = self.instance.submission
        if submission:
            current_app.db.session.delete(submission)
            #Delete the grading object
            if submission.grading:
                current_app.db.session.delete(submission.grading)

        current_app.db.session.delete(self.instance.entry_service)
        current_app.db.session.delete(self.instance)

    def reset(self):
        """
        Purges all persisted data from the instance.
        """
        self.stop()
        self.umount()
        try:
            path = Path(self.instance.entry_service.overlay_upper)
            if path.is_dir():
                for path in path.glob('*'):
                    if path.parts[-1] in ['.ssh']:
                        #Do not purge the .ssh file since it contains the SSH keys
                        #that are allowed to connect to the instance.
                        continue
                    subprocess.check_call(['/usr/bin/sudo', '/bin/rm', '-rf', '--', path.as_posix()], shell=False)
        except:
            log.error(f'Error during purgeing of persisted data {self.instance}', exc_info=True)
            raise
        finally:
            self.mount()

    def init_pid(self) -> int:
        if self.is_running():
            c = self.dc.container(self.instance.entry_service.container_id)
            return int(c.attrs['State']['Pid'])
        return None