import ipaddress
import random
import string
import re
import tarfile
from io import BytesIO
from pathlib import Path
from typing import List, Union, Optional

import docker
from docker import errors
from docker.types import IPAMConfig, IPAMPool
from flask import current_app

from ref.core.logging import get_logger

log = get_logger(__name__)

# Network pool for instance networks. Using /29 subnets (6 usable IPs) to avoid
# exhausting Docker's default address pool. A /16 pool with /29 subnets gives
# us 8192 possible networks.
INSTANCE_NETWORK_POOL = ipaddress.IPv4Network("10.200.0.0/16")
INSTANCE_SUBNET_PREFIX = 29  # 8 IPs, 6 usable (gateway + 5 containers)


class DockerClient:
    def __init__(self):
        self._client = None

    @staticmethod
    def container_name_by_hostname(hostname):
        """
        Finds a container by its hostname using the Docker API.
        Filters by Docker Compose project to handle parallel test instances.
        E.g., ssh-reverse-proxy -> ref_e2e_xxx_ssh-reverse-proxy_1
        """
        client = docker.from_env()

        # Find our own container's compose project label using container ID
        our_project = None
        try:
            my_container_id = DockerClient.get_own_container_id()
            for container in client.containers.list():
                if container.id == my_container_id:
                    labels = container.attrs.get("Config", {}).get("Labels", {})
                    our_project = labels.get("com.docker.compose.project")
                    break
        except Exception:
            pass  # Fall back to non-filtered lookup

        # Find container with matching hostname AND same compose project
        for container in client.containers.list():
            config = container.attrs.get("Config", {})
            if config.get("Hostname") == hostname:
                if our_project:
                    labels = config.get("Labels", {})
                    if labels.get("com.docker.compose.project") == our_project:
                        return container.name
                else:
                    # Fallback if we couldn't determine our project
                    return container.name

        raise Exception(f"No running container found with hostname '{hostname}'")

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
            mounts = Path("/proc/self/mountinfo").read_text()
        except Exception as e:
            raise Exception("Failed to get container ID") from e

        # Grep the ID from the /etc/hostname mount point.
        # 391 382 254:0 /var/lib/docker/containers/19ea1ca788b40ecf52ca33807d465697d730ae5d95994bef869fb9644bcb495b/hostname /etc/hostname rw,relatime - ext4 /dev/mapper/dec_root rw
        container_id = re.findall("/([a-f0-9]{64})/hostname /etc/hostname", mounts)
        if len(container_id) != 1:
            raise Exception(f"Failed to find container ID. lines={mounts}")

        return container_id[0]

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
            Exception
        """
        assert Path(path).is_absolute()

        # The container ID of ourself (raises)
        own_id = DockerClient.get_own_container_id()

        mounts = self.container(own_id, raise_on_not_found=True)
        mounts = mounts.attrs["Mounts"]
        target_mount = None
        for mount in mounts:
            if path.startswith(mount["Destination"]):
                target_mount = mount
                break

        if not target_mount:
            raise Exception(f"Failed to resolve local path {path} to host path.")

        path = path[len(target_mount["Destination"]) :]

        return target_mount["Source"] + path

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
        mounts = {local_dst_path: {"bind": "/ref-copy", "mode": "rw"}}

        cmd = ["/bin/bash", "-c", f"cp -avrT {container_src_path}/ /ref-copy/"]
        log_msgs = ""
        log_msgs += " --- Copying data from image ---\n"
        # ! Do not use auto_remove here, because it is broken in docker==5.0.3.
        # ! See https://github.com/docker/docker-py/pull/2282.
        log_msgs += self.client.containers.run(
            image_name, cmd, stderr=True, volumes=mounts, remove=True
        ).decode()

        return log_msgs

    def rmi(self, name, force=False) -> None:
        """
        Remove the image with the given name.
        Raises:
            docker.errors.APIError
        """
        return self.client.images.remove(name, force=force)

    def containers(
        self, include_stopped=False, sparse=False, filters=None
    ) -> List[docker.models.containers.Container]:
        """
        Get a list of all running containers.
        Args:
            include_stopped: Also return stopped container.
            sparse: Returned Containers are sparse in sense of availabel attributes.
                You might use container.reload() on the returned objects to get all information.
        Raises:
            - docker.errors.APIError
        """
        return self.client.containers.list(
            all=include_stopped, sparse=sparse, filters=filters
        )

    def networks(self, filters=None) -> List[docker.models.networks.Network]:
        """
        Get all networks.
        Raises:
            - docker.errors.APIError
        """
        return self.client.networks.list(greedy=True, filters=filters)

    def get_connected_container(
        self, network: Union[str, docker.models.networks.Network]
    ) -> List[str]:
        """
        Returns a list of ids of all containers connected to the given network.
        If no containers are connected, an empty list is returned.
        Raises:
            - docker.errors.APIError
        """
        network = self.network(network)
        if not network:
            return []

        containers = network.attrs.get("Containers")
        if containers is None:
            return []
        return containers.keys()

    def get_connected_networks(
        self, container: Union[str, docker.models.containers.Container]
    ) -> List[str]:
        """
        Returns a list of ids of all networks that are connected to the given container.
        If the container is not connected to any network, an empty list is returned.
        """
        container = self.container(container, raise_on_not_found=True)

        netwoks = container.attrs["NetworkSettings"]["Networks"].values()
        netwoks = [network["NetworkID"] for network in netwoks]

        return netwoks

    def __container_transitive_closure_get_containers(
        self, container, visited_containers, visited_networks=set()
    ):
        visited_containers.add(container)
        for n in self.get_connected_networks(container):
            for c in self.get_connected_container(n):
                if c not in visited_containers:
                    self.__container_transitive_closure_get_containers(
                        c, visited_containers
                    )

    def container_transitive_closure_get_containers(
        self,
        container: Union[str, docker.models.containers.Container],
        include_self=False,
    ):
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

        self.__container_transitive_closure_get_containers(container.id, containers)

        if not include_self:
            containers.remove(container.id)
        return containers

    def container(
        self, name_or_id: str, raise_on_not_found=False
    ) -> docker.models.containers.Container:
        """
        Get a container by its id or name. In case no container was
        found, None is returned.
        Raises:
            docker.errors.APIError
            docker.errors.NotFound
        """
        if not name_or_id:
            if raise_on_not_found:
                raise Exception("Not found")
            return None

        if isinstance(name_or_id, docker.models.containers.Container):
            return name_or_id

        try:
            return self.client.containers.get(name_or_id)
        except errors.NotFound:
            if raise_on_not_found:
                raise
            return None

    def container_get_ip(
        self,
        container: Union[str, docker.models.containers.Container],
        network: Union[str, docker.models.networks.Network],
    ):
        """
        Returns the IP address of the given container on the given network.
        If the container is not connected to the network, None is returned.
        Raises:
            docker.errors.APIError
        """
        assert container
        assert network
        container = self.container(container, raise_on_not_found=True)
        network = self.network(network, raise_on_not_found=True)

        network.reload()
        containers = network.attrs.get("Containers")
        if containers is None:
            return None
        for k, v in containers.items():
            if k == container.id:
                return v["IPv4Address"]
        return None

    def container_add_file(
        self,
        container: Union[str, docker.models.containers.Container],
        path: str,
        file_bytes: bytes,
        mode=0o700,
    ):
        """
        Add a file into a running container.
        The new file is owned by root.
        Raises:
            docker.errors.APIError
            docker.errors.NetFound
        """
        assert container
        current_app.logger.info(f"Adding file {path} to container {container}")

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

    def create_container(
        self,
        image_name,
        name=None,
        auto_remove=False,
        network_mode="none",
        volumes=None,
        cap_add=[],
        security_opt=[],
        cpu_period=None,
        cpu_quota=None,
        mem_limit=None,
        read_only=False,
        hostname=None,
        **kwargs,
    ):
        if not name:
            name = f"{current_app.config['DOCKER_RESSOURCE_PREFIX']}" + "".join(
                random.choices(string.ascii_uppercase, k=10)
            )

        if hostname:
            kwargs["hostname"] = hostname

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
            **kwargs,
        )

    def stop_container(self, container, timeout=5, remove=False):
        container = self.container(container, raise_on_not_found=True)
        container.stop(timeout=timeout)
        if remove:
            # Make sure it was not started with autremove
            container = self.container(container.id, raise_on_not_found=False)
            if container:
                container.remove(force=True)

    def _get_used_subnets(self) -> set[ipaddress.IPv4Network]:
        """Get all subnets currently in use by Docker networks."""
        used = set()
        for network in self.client.networks.list():
            try:
                ipam_config = network.attrs.get("IPAM", {}).get("Config") or []
                for config in ipam_config:
                    subnet_str = config.get("Subnet")
                    if subnet_str:
                        used.add(ipaddress.IPv4Network(subnet_str))
            except (KeyError, ValueError):
                continue
        return used

    def _allocate_subnet(self) -> Optional[ipaddress.IPv4Network]:
        """
        Allocate an unused /29 subnet from the instance network pool.

        Returns:
            An available IPv4Network, or None if pool is exhausted.
        """
        used_subnets = self._get_used_subnets()

        # Iterate through all possible /29 subnets in our pool
        for subnet in INSTANCE_NETWORK_POOL.subnets(new_prefix=INSTANCE_SUBNET_PREFIX):
            # Check if this subnet overlaps with any used subnet
            overlaps = any(subnet.overlaps(used) for used in used_subnets)
            if not overlaps:
                return subnet

        return None

    def create_network(self, name=None, driver="bridge", internal=False):
        """
        Create a Docker network with a /29 subnet from the instance pool.

        Networks do not need a unique name. If name is not set, a random name
        is chosen. Uses /29 subnets to avoid exhausting Docker's address pool.

        Raises:
            docker.errors.APIError
            RuntimeError: If no subnet is available in the pool.
        """
        if not name:
            name = f"{current_app.config['DOCKER_RESSOURCE_PREFIX']}" + "".join(
                random.choices(string.ascii_uppercase, k=10)
            )

        # Retry loop to handle race conditions when multiple processes
        # try to allocate the same subnet concurrently
        max_retries = 10
        last_error = None

        for attempt in range(max_retries):
            # Allocate a /29 subnet from our pool
            subnet = self._allocate_subnet()
            if subnet is None:
                raise RuntimeError(
                    "No available subnet in instance network pool. "
                    "Consider cleaning up unused networks."
                )

            # First usable host is the gateway
            gateway = str(list(subnet.hosts())[0])

            ipam_pool = IPAMPool(subnet=str(subnet), gateway=gateway)
            ipam_config = IPAMConfig(pool_configs=[ipam_pool])

            log.debug(
                f"Creating network {name} with subnet {subnet} (attempt {attempt + 1})"
            )
            try:
                return self.client.networks.create(
                    name, driver=driver, internal=internal, ipam=ipam_config
                )
            except errors.APIError as e:
                # Check if this is a subnet overlap error (race condition)
                if "Pool overlaps" in str(e):
                    log.warning(
                        f"Subnet {subnet} was allocated by another process, retrying..."
                    )
                    last_error = e
                    continue
                # Re-raise other API errors
                raise

        # All retries exhausted
        raise RuntimeError(
            f"Failed to allocate subnet after {max_retries} attempts. "
            f"Last error: {last_error}"
        )

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
        log.info(f"Removing network {network.id}")

        failed = False
        containers = self.get_connected_container(network)
        for cid in containers:
            c = self.container(cid)
            if c:
                network.disconnect(c)
            else:
                failed = True
                log.warning(
                    f"Network {network.id} contains dead container {cid}, unable to remove network"
                )

        # Removal will only succeed if the network has no attached containers.
        # In case a non-existing container is attached we can not disconnect it, but are
        # also unable to remove the network. This is a known docker bug and can only be
        # solved by restarting docker.
        if not failed:
            network.remove()
