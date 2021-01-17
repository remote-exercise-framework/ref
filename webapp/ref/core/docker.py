import random
import string
import subprocess
import tarfile
from io import BytesIO, StringIO
from pathlib import Path
from typing import List, Optional, Union

import docker
from docker import errors
from flask import current_app
from werkzeug.local import LocalProxy

log = LocalProxy(lambda: current_app.logger)


class DockerClient():

    def __init__(self):
        self._client = None

    @staticmethod
    def container_name_by_hostname(hostname):
        """
        Resolves the hostname of an container to its full name.
        E.g., ssh -> ref_sshserver_1
        """
        log.debug(f'Getting FQN of host {hostname}')
        cmd = f'dig +short {hostname}'
        ip = None
        try:
            ip = subprocess.check_output(cmd, shell=True)
        except subprocess.CalledProcessError as e:
            log.error(f'Failed to get IP of host "{hostname}"', exc_info=True)
            raise

        ip = ip.decode().rstrip()
        log.debug(f'IP is {ip}')

        cmd = f'nslookup {ip} | grep -o "name = .*$" | cut -d "=" -f 2 | xargs | cut -d "." -f 1'
        full_hostname = None
        try:
            full_hostname = subprocess.check_output(cmd, shell=True)
        except subprocess.CalledProcessError as e:
            log.error(
                f'Failed to get hostname for IP {ip} of host {hostname}', exc_info=True)
            raise

        full_hostname = full_hostname.decode().rstrip()
        log.debug(f'Full hostname is {full_hostname}')

        return full_hostname

    @property
    def client(self) -> docker.DockerClient:
        if not self._client:
            self._client = docker.from_env()
        return self._client

    def close(self):
        if self._client:
            self._client.close()

    @staticmethod
    def get_own_container_id() -> str:
        """
        Returns the container ID of the executing container.
        For example 7bb6c606c363fc63210e70afaa1cc93288c7318d54674c99be81312b0989ae39
        """
        try:
            own_id = subprocess.check_output(
                'cat /proc/self/cgroup | head -n 1 | cut -d "/" -f3', shell=True)
            own_id = own_id.decode()
            own_id = own_id.rstrip()
        except Exception as e:
            raise Exception(
                'Failed to get ID. Are we running inside a container?') from e

        if len(own_id) != 64:
            raise Exception(f'This does not look like a container ID {own_id}')

        return own_id

    def local_path_to_host(self, path: str) -> str:
        """
        Converts the given absolute local path (path inside this container) into an absolute host path.
        This only works if the given path points to a file/folder that is mounted from the host.
        For example:
            Host (/home/user/app) -> Container (/app)
            local_path_to_host(/app/downloads) -> /home/user/app/downloads
        Raises:
            docker.errors.APIError
            docker.errors.NotFound
        """
        assert Path(path).is_absolute()

        # The container ID of ourself (raises)
        own_id = DockerClient.get_own_container_id()

        mounts = self.container(own_id, raise_on_not_found=True)
        mounts = mounts.attrs['Mounts']
        target_mount = None
        for mount in mounts:
            if path.startswith(mount['Destination']):
                target_mount = mount
                break

        if not target_mount:
            raise Exception(
                f'Failed to resolve local path {path} to host path.')

        path = path[len(target_mount['Destination']):]

        return target_mount['Source'] + path

    def images(self) -> List[docker.models.images.Image]:
        """
        Get a list of all images.
        Raises:
            - docker.errors.APIError
        """
        return self.client.images.list()

    def image(self, name) -> docker.models.images.Image:
        """
        Get an image by its name. In case no image was found, None
        is returned.
        Raises:
            - docker.errors.APIError
        """
        try:
            return self.client.images.get(name)
        except errors.NotFound:
            return None

    def copy_from_image(self, image_name, container_src_path, local_dst_path) -> str:
        """
        Copies path container_src_path from inside a container of type image_name
        to the local path local_dst_path.
        Raises:
            docker.errors.ContainerError: If the container exits with a non-zero exit code.
            docker.errors.ImageNotFound: If the specified image does not exist.
            docker.errors.APIError: If the server returns an error.
        Returns:
            On success, stdout captured during the copy process.
        """
        mounts = {
            local_dst_path: {'bind': '/ref-copy', 'mode': 'rw'}
        }

        cmd = ['/bin/bash', '-c', f'cp -avrT {container_src_path}/ /ref-copy/']
        log_msgs = ""
        log_msgs += ' --- Copying data from image ---\n'
        log_msgs += self.client.containers.run(
            image_name, cmd, stderr=True, volumes=mounts, auto_remove=True).decode()

        return log_msgs

    def rmi(self, name, force=False) -> None:
        """
        Remove the image with the given name.
        Raises:
            docker.errors.APIError
        """
        return self.client.images.remove(name, force=force)

    def containers(self, include_stopped=False, sparse=False, filters=None) -> List[docker.models.containers.Container]:
        """
        Get a list of all running containers.
        Args:
            include_stopped: Also return stopped container.
            sparse: Returned Containers are sparse in sense of availabel attributes.
                You might use container.reload() on the returned objects to get all information.
        Raises:
            - docker.errors.APIError
        """
        return self.client.containers.list(all=include_stopped, sparse=sparse, filters=filters)

    def networks(self, filters=None) -> List[docker.models.networks.Network]:
        """
        Get all networks.
        Raises:
            - docker.errors.APIError
        """
        return self.client.networks.list(greedy=True, filters=filters)

    def get_connected_container(self, network: Union[str, docker.models.networks.Network]) -> List[str]:
        """
        Returns a list of ids of all containers connected to the given network.
        If no containers are connected, an empty list is returned.
        Raises:
            - docker.errors.APIError
        """
        network = self.network(network)
        if not network:
            return []

        return network.attrs['Containers'].keys()

    def get_connected_networks(self, container: Union[str, docker.models.containers.Container]) -> List[str]:
        """
        Returns a list of ids of all networks that are connected to the given container.
        If the container is not connected to any network, an empty list is returned.
        """
        container = self.container(container, raise_on_not_found=True)

        netwoks = container.attrs['NetworkSettings']['Networks'].values()
        netwoks = [network['NetworkID'] for network in netwoks]

        return netwoks

    def __container_transitive_closure_get_containers(self, container, visited_containers, visited_networks=set()):
        visited_containers.add(container)
        for n in self.get_connected_networks(container):
            for c in self.get_connected_container(n):
                if c not in visited_containers:
                    self.__container_transitive_closure_get_containers(
                        c, visited_containers)

    def container_transitive_closure_get_containers(self, container: Union[str, docker.models.containers.Container], include_self=False):
        """
        Returns a set containing all containers ids of containers connected over any network
        to the given container. This also includes containers that are connected over in intermediate
        container.
        Raises:
            docker.errors.APIError
            docker.errors.NotFound
        """
        container = self.container(container, raise_on_not_found=True)
        containers = set()
        containers.add(container.id)

        self.__container_transitive_closure_get_containers(
            container.id, containers)

        if not include_self:
            containers.remove(container.id)
        return containers

    def container(self, name_or_id: str, raise_on_not_found=False) -> docker.models.containers.Container:
        """
        Get a container by its id or name. In case no container was
        found, None is returned.
        Raises:
            docker.errors.APIError
            docker.errors.NotFound
        """
        if not name_or_id:
            return None

        if isinstance(name_or_id, docker.models.containers.Container):
            return name_or_id

        try:
            return self.client.containers.get(name_or_id)
        except errors.NotFound:
            if raise_on_not_found:
                raise
            return None

    def container_get_ip(self, container: Union[str, docker.models.containers.Container], network: Union[str, docker.models.networks.Network]):
        """
        Returns the IP address of the given container on the given network.
        If the container is net connected to the network, None is returned.
        Raises:
            docker.errors.APIError
        """
        assert container
        assert network
        container = self.container(container, raise_on_not_found=True)
        network = self.network(network, raise_on_not_found=True)

        network.reload()
        for k, v in network.attrs['Containers'].items():
            if k == container.id:
                return v['IPv4Address']
        return None

    def container_add_file(self, container: Union[str, docker.models.containers.Container], path: str, file_bytes: bytes, mode=0o700):
        """
        Add a file into a running container.
        The new file is owned by root.
        Raises:
            docker.errors.APIError
            docker.errors.NetFound
        """
        assert container
        current_app.logger.info(f'Adding file {path} to container {container}')

        container = self.container(container, raise_on_not_found=True)

        if isinstance(path, str):
            path = Path(path)

        tar_bytes = BytesIO()
        tar = tarfile.open(mode="w", fileobj=tar_bytes)
        data = BytesIO(file_bytes)

        info = tarfile.TarInfo(name=path.parts[-1])
        info.size = len(data.getvalue())
        info.mode = mode

        tar.addfile(tarinfo=info, fileobj=data)
        tar.close()

        container.put_archive(path.parent.as_posix(), tar_bytes.getvalue())

    def create_container(self,
                         image_name,
                         name=None,
                         auto_remove=False,
                         network_mode='none',
                         volumes=None,
                         cap_add=[],
                         security_opt=[],
                         cpu_period=None,
                         cpu_quota=None,
                         mem_limit=None,
                         read_only=False,
                         hostname=None,
                         **kwargs):
        if not name:
            name = f'{current_app.config["DOCKER_RESSOURCE_PREFIX"]}' + \
                ''.join(random.choices(string.ascii_uppercase, k=10))

        if hostname:
            kwargs['hostname'] = hostname

        return self.client.containers.run(
            image_name,
            detach=True,
            privileged=False,
            name=name,
            volumes=volumes,
            cap_add=cap_add,
            auto_remove=auto_remove,
            network_mode=network_mode,
            security_opt=security_opt,
            cpu_period=cpu_period,
            cpu_quota=cpu_quota,
            mem_limit=mem_limit,
            read_only=read_only,
            stdin_open=True,
            **kwargs
        )

    def stop_container(self, container, timeout=5, remove=False):
        container = self.container(container, raise_on_not_found=True)
        container.stop(timeout=timeout)
        if remove:
            #Make sure it was not started with autremove
            container = self.container(container.id, raise_on_not_found=False)
            if container:
                container.remove(force=True)


    def create_network(self, name=None, driver='bridge', internal=False):
        """
        Networks do not need a unique name. If name is not set, a random name
        is chosen.
        Raises:
            docker.errors.APIError
        """
        if not name:
            name = f'{current_app.config["DOCKER_RESSOURCE_PREFIX"]}' + \
                ''.join(random.choices(string.ascii_uppercase, k=10))
        return self.client.networks.create(name, driver=driver, internal=internal)

    def network(self, network_id, raise_on_not_found=False):
        if not network_id:
            return None

        if isinstance(network_id, docker.models.networks.Network):
            return network_id

        try:
            return self.client.networks.get(network_id)
        except errors.NotFound:
            if raise_on_not_found:
                raise
            return None

    def remove_network(self, network: Union[str, docker.models.networks.Network]):
        """
        Remove the given network.
        Raises:
            docker.errors.APIError
        """
        network = self.network(network)
        if not network:
            return
        log.info(f'Removing network {network.id}')

        failed = False
        containers = self.get_connected_container(network)
        for cid in containers:
            c = self.container(cid)
            if c:
                network.disconnect(c)
            else:
                failed = True
                log.warning(
                    f'Network {network.id} contains dead container {cid}, unable to remove network')

        # Removal will only succeed if the network has no attached containers.
        # In case a non-existing container is attached we can not disconnect it, but are
        # also unable to remove the network. This is a known docker bug and can only be
        # solved by restarting docker.
        if not failed:
            network.remove()
