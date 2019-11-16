from flask import redirect, render_template, current_app

from ref import db, refbp
from ref.core import admin_required
from dataclasses import dataclass

from ref.core import DockerClient
from ref.core.util import redirect_to_next

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
        if not network.name.startswith('ref-'):
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


def _get_dangling_container():
    dangling_container = []
    d = DockerClient()
    containers = d.containers(include_stopped=True)

    for container in containers:
        if not container.name.startswith('ref-'):
            continue

        if _is_connected_to_sshserver(container.id):
            #Check if it is connected to the ssh server
            continue

        dc = danglingContainer(container.id, container.name, container.status)
        dangling_container.append(dc)

    return dangling_container

@refbp.route('/system/gc/delete_dangling_networks', methods=('GET',))
@admin_required
def sysmtem_gc_delete_dangling_networks():
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
def sysmtem_gc_delete_dangling_container():
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

@refbp.route('/system/gc', methods=('GET', 'POST'))
@admin_required
def system_gc():
    """
    Garbage collection service used to delete container and networks that are dangling.
    """
    dangling_networks = _get_dangling_networks()
    dangling_container = _get_dangling_container()
    return render_template('system_gc.html', dangling_networks=dangling_networks, dangling_container=dangling_container)
