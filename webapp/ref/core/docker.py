import random
import string
import subprocess
import tarfile
from io import BytesIO, StringIO
from pathlib import Path

import docker
from docker import errors
from flask import current_app
from werkzeug.local import LocalProxy

log = LocalProxy(lambda: current_app.logger)

class DockerClient():

    def __init__(self):
        self._client = None

    @staticmethod
    def container_name_by_hostname(hostname, raise_exc=False):
        log.debug(f'Getting FQN of host {hostname}')
        cmd = f'dig +short {hostname}'
        ip = None
        try:
            ip = subprocess.check_output(cmd, shell=True)
        except subprocess.CalledProcessError as e:
            log.error(f'Failed to get IP of host "{hostname}"', exc_info=True)
            if raise_exc:
                raise e
            return None

        ip = ip.decode().rstrip()
        log.debug(f'IP is {ip}')

        cmd = f'nslookup {ip} | grep -o "name = .*$" | cut -d "=" -f 2 | xargs | cut -d "." -f 1'
        full_hostname = None
        try:
            full_hostname = subprocess.check_output(cmd, shell=True)
        except subprocess.CalledProcessError as e:
            log.error(f'Failed to get hostname for IP {ip} of host {full_hostname}', exc_info=True)
            if raise_exc:
                raise e
            return None

        full_hostname = full_hostname.decode().rstrip()
        log.debug(f'Full hostname is {full_hostname}')

        return full_hostname


    @property
    def client(self):
        if not self._client:
            self._client = docker.from_env()
        return self._client

    def close(self):
        if self._client:
            self._client.close()

    def local_path_to_host(self, path):
        """
        Converts the given full qualified local path (path inside this container) into a host path.
        This only works if the given path points to a file/folder that is mounted
        from the host.
        """
        assert path[0] == '/'
        own_id = subprocess.check_output('cat /proc/self/cgroup | head -n 1 | cut -d "/" -f3', shell=True)
        own_id = own_id.decode()
        own_id = own_id.rstrip()
        mounts = self.client.containers.get(own_id)
        mounts = mounts.attrs['Mounts']
        target_mount = None
        for mount in mounts:
            if path.startswith(mount['Destination']):
                target_mount = mount
                break
        path = path[len(target_mount['Destination']):]
        return target_mount['Source'] + path

    def images(self):
        """
        Get a list of all images.
        Raises:
            - docker.errors.APIError
        """
        return self.client.images.list()

    def image(self, name):
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

    def copy_from_image(self, image_name, container_src_path, local_dst_path):
        """
        Copies path container_src_path from inside a container of type image_name
        to the local path local_dst_path.
        Raises:
        docker.errors.ContainerError – If the container exits with a non-zero exit code and detach is False.
        docker.errors.ImageNotFound – If the specified image does not exist.
        docker.errors.APIError – If the server returns an error.
        """
        mounts = {
            local_dst_path: {'bind': '/ref-copy', 'mode': 'rw'}
            }

        cmd = ['/bin/bash', '-c', f'cp -avrT {container_src_path}/ /ref-copy/']
        log = ""
        log += ' --- Copying data from image ---\n'
        log += self.client.containers.run(image_name, cmd, stderr=True, volumes=mounts, auto_remove=True).decode()

        return log

    def rmi(self, name, force=False) -> None:
        return self.client.images.remove(name, force=force)

    def containers(self, include_stopped=False, sparse=False):
        """
        Get a list of all running containers.
        Raises:
            - docker.errors.APIError
        """
        return self.client.containers.list(all=include_stopped, sparse=sparse)

    def networks(self):
        return self.client.networks.list(greedy=True)

    def get_connected_container(self, network):
        """
        Returns a list of ids of all connected containers. If no containers are connected,
        an empty list is returned.
        """
        if isinstance(network, str):
            network = self.network(network)
        if not network:
            return []

        return network.attrs['Containers'].keys()

    def get_connected_networks(self, container):
        """
        Returns a list of ids of all networks that are connected to the given container.
        If the container is not connected to any network, an empty list is returned.
        """
        if isinstance(container, str):
            container = self.container(container)
        if not container:
            return []

        netwoks = container.attrs['NetworkSettings']['Networks'].values()
        netwoks = [network['NetworkID'] for network in netwoks]

        return netwoks

    def __container_transitive_closure_get_containers(self, container, visited_containers, visited_networks=set()):
        visited_containers.add(container)
        for n in self.get_connected_networks(container):
            for c in self.get_connected_container(n):
                if c not in visited_containers:
                    self.__container_transitive_closure_get_containers(c, visited_containers)

    def container_transitive_closure_get_containers(self, container, include_self=False):
        """
        Returns a set containing all ids of containers connected over a network
        to the given container.
        """
        if isinstance(container, str):
            container = self.container(container)
        containers = set()
        containers.add(container.id)

        self.__container_transitive_closure_get_containers(container.id, containers)

        if not include_self:
            containers.remove(container.id)
        return containers


    def container(self, name_or_id):
        """
        Get a container by its id or name. In case no container was
        found, None is returned.
        Raises:
            - docker.errors.APIError
        """
        if not name_or_id:
            return None

        try:
            return self.client.containers.get(name_or_id)
        except errors.NotFound:
            return None

    def container_get_ip(self, container, network):
        assert container
        assert network
        network.reload()
        for k, v in network.attrs['Containers'].items():
            if k == container.id:
                return v['IPv4Address']
        return None

    def container_add_file(self, container, path, file_bytes, mode=0o700):
        current_app.logger.info(f'Adding file {path} to container {container}')
        
        if isinstance(path, str):
            path = Path(path)

        if isinstance(container, str):
            container_obj = self.container(container)
            if not container_obj:
                raise docker.errors.NotFound(f'Failed to find container {container}')
            container = container_obj

        tar_bytes = BytesIO()
        tar = tarfile.open(mode = "w", fileobj = tar_bytes)
        data = BytesIO(file_bytes)

        info = tarfile.TarInfo(name=path.parts[-1])
        info.size = len(data.getvalue())
        info.mode = mode
    
        tar.addfile(tarinfo=info, fileobj=data)
        tar.close()

        container.put_archive(path.parent.as_posix(), tar_bytes.getvalue())

    def create_container(self, image_name, name=None, auto_remove=False, network_mode='none', volumes=None, cap_add=[], security_opt=[], cpu_period=None, cpu_quota=None, mem_limit=None, read_only=False, hostname=None):
        if not name:
            name = f'{current_app.config["DOCKER_RESSOURCE_PREFIX"]}' + ''.join(random.choices(string.ascii_uppercase, k=10))

        kwargs = {}
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

    def create_network(self, name=None, driver='bridge', internal=False):
        """
        Networks do not need a unique name. If name is not set, a random name
        with the prefix 'ref-' is chosen.
        """
        if not name:
            name = f'{current_app.config["DOCKER_RESSOURCE_PREFIX"]}' + ''.join(random.choices(string.ascii_uppercase, k=10))
        return self.client.networks.create(name, driver=driver, internal=internal)

    def network(self, network_id):
        if not network_id:
            return None
        try:
            return self.client.networks.get(network_id)
        except errors.NotFound:
            return None

    def remove_network(self, network):
        if isinstance(network, str):
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
                log.warning(f'Network {network.id} contains dead container {cid}, unable to remove network')

        #Removal will only succeed if the network has no attached containers.
        #In case a non-existing container is attached we can not disconnect it, but are
        #also unable to remove the network. This is a known docker bug and can only be
        #solved by restarting docker.
        if not failed:
            network.remove()
