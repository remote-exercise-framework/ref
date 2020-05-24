from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from flask import current_app, redirect, render_template
from functools import partial
from ref import db, refbp
from ref.core import DockerClient, admin_required
from ref.core.util import redirect_to_next
from ref.model import InstanceEntryService, InstanceService, Submission, Instance


@dataclass
class danglingNetwork():
    id: str
    name: str

@dataclass
class DanglingContainer():
    id: str
    name: str
    status: str

def _get_dangling_networks():
    dangling_networks = []

    d = DockerClient()
    networks = d.networks(filters={'name': current_app.config['DOCKER_RESSOURCE_PREFIX']})

    ssh_container = d.container(current_app.config['SSHSERVER_CONTAINER_NAME'])

    for network in networks:
        connected_containers = d.get_connected_container(network)

        if connected_containers and set(connected_containers) != set([ssh_container.id]):
            #Containers connected (besides the SSH container), ignore it
            continue

        dn = danglingNetwork(network.id, network.name)
        dangling_networks.append(dn)

    return dangling_networks

def _is_in_db(container_id):
    """
    Check if the given container ID is contained in any DB record.
    Returns:
        True, if the container ID is found in the DB.
        Else, False.
    """
    return (
        InstanceService.query.filter(InstanceService.container_id == container_id).one_or_none()
        or InstanceEntryService.query.filter(InstanceEntryService.container_id == container_id).one_or_none()
        )

def _is_connected_to_sshserver(dc, ssh_container, container):
    """
    Check whether the container is connected to the SSH server.
    Returns:
        True, if the container is connected to the SSH server
        Else, False.
    """
    if ssh_container == container:
        return container, True

    containers = dc.container_transitive_closure_get_containers(container)

    return container, ssh_container.id in containers

def _get_dangling_container():
    dangling_container = []
    dc = DockerClient()
    #Get all container that have a name that contains the provided prefix
    containers = dc.containers(include_stopped=True, sparse=True, filters={'name': current_app.config['DOCKER_RESSOURCE_PREFIX']})
    ssh_container = dc.container(current_app.config['SSHSERVER_CONTAINER_NAME'])

    executor = ThreadPoolExecutor(max_workers=16)
    is_connected_to_ssh = {}
    is_connected_to_ssh_futures = set()

    is_connected_to_sshserver = partial(_is_connected_to_sshserver, dc, ssh_container)

    for container in containers:
        if not _is_in_db(container.id):
            container.reload()
            dangling_container.append(DanglingContainer(container.id, container.name, container.status))
        is_connected_to_ssh_futures.add(executor.submit(is_connected_to_sshserver, container))

    for future in is_connected_to_ssh_futures:
        c, is_connected = future.result()
        if not is_connected:
            dangling_container.append(DanglingContainer(container.id, container.name, container.status))

    executor.shutdown()

    return dangling_container

def _get_old_submissions():
    """
    Returns all submissions that have an successor (i.e., the same instance has a more recent submission).
    """
    ret = set()

    instances = Instance.all()
    for instance in instances:
        if len(instance.submissions) > 1:
            submissions = sorted(instance.submissions, key=lambda e: e.submission_ts)
            ret |= set(submissions[0:-1])

    return list(sorted(list(ret), key=lambda e: e.id))

@refbp.route('/system/gc/delete_dangling_networks')
@admin_required
def system_gc_delete_dangling_networks():
    """
    Delete all networks that were created by us, but do not have any container attached.
    """
    d = DockerClient()
    dangling_networks = _get_dangling_networks()
    for network in dangling_networks:
        network = d.network(network.id)
        if network:
            network.remove()

    return redirect_to_next()

@refbp.route('/system/gc/delete_dangling_container')
@admin_required
def system_gc_delete_dangling_container():
    """
    Delete all container that belong to REF, but are not connected to the
    SSH entry server anymore.
    """
    d = DockerClient()
    dangling_containers = _get_dangling_container()
    for c in dangling_containers:
        c = d.container(c.id)
        c.remove(force=True)

    return redirect_to_next()

@refbp.route('/system/gc/delete_old_submissions')
@admin_required
def system_gc_delete_old_submission():
    #TODO: Implement
    return redirect_to_next()

@refbp.route('/system/gc')
@admin_required
def system_gc():
    """
    Garbage collection service used to delete container and networks that are dangling.
    """
    dangling_networks = _get_dangling_networks()
    dangling_container = _get_dangling_container()
    old_submissions = _get_old_submissions()
    return render_template('system_gc.html', dangling_networks=dangling_networks, dangling_container=dangling_container, old_submissions=old_submissions)
