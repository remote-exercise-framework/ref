import docker
import subprocess
from docker import errors
import random
import string

class DockerClient():

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if not self._client:
            self._client = docker.from_env()
        return self._client

    def path_to_local(self, path):
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

        cmd = ['/bin/bash', '-c', f'cp -avr {container_src_path}/* /ref-copy/']
        log = ""
        log += ' --- Copying data from image ---\n'
        log += self.client.containers.run(image_name, cmd, stderr=True, volumes=mounts, auto_remove=True).decode()

        return log

    def rmi(self, name, force=False) -> None:
        return self.client.images.remove(name, force=force)

    def containers(self, include_stopped=False):
        """
        Get a list of all running containers.
        Raises:
            - docker.errors.APIError
        """
        return self.client.containers.list(all=include_stopped)

    def container(self, name_or_id):
        """
        Get a container by its id or name. In case no container was
        found, None is returned.
        Raises:
            - docker.errors.APIError
        """
        assert name_or_id
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

    def create_container(self, image_name, name=None, auto_remove=True, network_mode='none', volumes=None, cap_add=[], security_opt=[]):
        if not name:
            name = 'ref-' + ''.join(random.choices(string.ascii_uppercase, k=10))
        return self.client.containers.run(image_name, detach=True, privileged=True, name=name, volumes=volumes, cap_add=cap_add, auto_remove=auto_remove, network_mode=network_mode, security_opt=security_opt)

    def create_network(self, name=None, driver='bridge', internal=False):
        """
        Networks do not need a unique name. If name is not set, a random name
        with the prefix 'ref-' is chosen.
        """
        if not name:
            name = 'ref-' + ''.join(random.choices(string.ascii_uppercase, k=10))
        return self.client.networks.create(name, driver=driver, internal=internal)

    def network(self, network_id):
        assert network_id
        try:
            return self.client.networks.get(network_id)
        except errors.NotFound:
            return None