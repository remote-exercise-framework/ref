from dataclasses import dataclass

from flask import current_app, redirect, render_template

from ref import db, refbp
from ref.core import DockerClient, admin_required
from ref.core.util import redirect_to_next
from ref.model import InstanceEntryService, InstanceService, Submission, Instance


@dataclass
class danglingNetwork():
    id: str
    name: str

@dataclass
class danglingContainer():
    id: str
    name: str
    status: str

def _get_dangling_networks():
    dangling_networks = []

    d = DockerClient()
    networks = d.networks()

    ssh_container = d.container(current_app.config['SSHSERVER_CONTAINER_NAME'])

    for network in networks:
        if not network.name.startswith(current_app.config['DOCKER_RESSOURCE_PREFIX']):
            continue

        connected_containers = d.get_connected_container(network)

        if connected_containers and set(connected_containers) != set(ssh_container.id):
            #Containers connected, ignore it
            continue

        dn = danglingNetwork(network.id, network.name)
        dangling_networks.append(dn)

    return dangling_networks

def _is_connected_to_sshserver(container):
    d = DockerClient()
    if isinstance(container, str):
        container = d.container(container)

    if not container:
        return False

    ssh_container = d.container(current_app.config['SSHSERVER_CONTAINER_NAME'])
    if ssh_container == container:
        return True

    containers = d.container_transitive_closure_get_containers(container)

    return ssh_container.id in containers

def _is_in_db(container_id):
    return (
        InstanceService.query.filter(InstanceService.container_id == container_id).one_or_none()
        or InstanceEntryService.query.filter(InstanceEntryService.container_id == container_id).one_or_none()
        )

def _get_dangling_container():
    dangling_container = []
    d = DockerClient()
    containers = d.containers(include_stopped=True)

    for container in containers:
        if not container.name.startswith(current_app.config['DOCKER_RESSOURCE_PREFIX']):
            continue

        if _is_in_db(container.id) and _is_connected_to_sshserver(container.id):
            #Check if it is connected to the ssh server
            continue

        dc = danglingContainer(container.id, container.name, container.status)
        dangling_container.append(dc)

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

@refbp.route('/system/gc/delete_dangling_networks', methods=('GET',))
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

@refbp.route('/system/gc/delete_dangling_container', methods=('GET',))
@admin_required
def system_gc_delete_dangling_container():
    """
    Delete all container that were created by us, but are not connected to the
    SSH entry server anymore.
    """
    d = DockerClient()
    dangling_containers = _get_dangling_container()
    for c in dangling_containers:
        c = d.container(c.id)
        c.remove(force=True)

    return redirect_to_next()

@refbp.route('/system/gc/delete_old_submissions', methods=('GET',))
@admin_required
def system_gc_delete_old_submission():
    """

    """
    # d = DockerClient()
    # dangling_containers = _get_dangling_container()
    # for c in dangling_containers:
    #     c = d.container(c.id)
    #     c.remove(force=True)

    return redirect_to_next()

@refbp.route('/system/gc', methods=('GET', 'POST'))
@admin_required
def system_gc():
    """
    Garbage collection service used to delete container and networks that are dangling.
    """
    dangling_networks = _get_dangling_networks()
    dangling_container = _get_dangling_container()
    old_submissions = _get_old_submissions()
    return render_template('system_gc.html', dangling_networks=dangling_networks, dangling_container=dangling_container, old_submissions=old_submissions)
