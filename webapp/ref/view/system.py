from flask import redirect, render_template, current_app

from ref import db, refbp
from ref.core import admin_required
from dataclasses import dataclass

from ref.core import DockerClient
from ref.core.util import redirect_to_next

@dataclass
class DangelingNetwork():
    id: str
    name: str

@dataclass
class DangelingContainer():
    id: str
    name: str
    status: str

def _get_dangeling_networks():
    dangeling_networks = []

    d = DockerClient()
    networks = d.networks()

    for network in networks:
        if not network.name.startswith('ref-'):
            continue

        if d.get_connected_container(network):
            #Containers connected, ignore it
            continue

        dn = DangelingNetwork(network.id, network.name)
        dangeling_networks.append(dn)

    return dangeling_networks

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


def _get_dangeling_container():
    dangeling_container = []
    d = DockerClient()
    containers = d.containers(include_stopped=True)

    for container in containers:
        if not container.name.startswith('ref-'):
            continue

        if _is_connected_to_sshserver(container):
            #Check if it is connected to the ssh server
            continue

        dc = DangelingContainer(container.id, container.name, container.status)
        dangeling_container.append(dc)

    return dangeling_container

@refbp.route('/system/gc/delete_dangeling_networks', methods=('GET',))
@admin_required
def sysmtem_gc_delete_dangeling_networks():
    d = DockerClient()
    dangeling_networks = _get_dangeling_networks()
    for network in dangeling_networks:
        network = d.network(network.id)
        if network:
            network.remove()

    return redirect_to_next()

@refbp.route('/system/gc/delete_dangeling_container', methods=('GET',))
@admin_required
def sysmtem_gc_delete_dangeling_container():
    d = DockerClient()
    dangeling_containers = _get_dangeling_container()
    for c in dangeling_containers:
        c = d.container(c.id)
        c.remove(force=True)

    return redirect_to_next()

@refbp.route('/system/gc', methods=('GET', 'POST'))
@admin_required
def system_gc():
    dangeling_networks = _get_dangeling_networks()
    dangeling_container = _get_dangeling_container()

    return render_template('system_gc.html', dangeling_networks=dangeling_networks, dangeling_container=dangeling_container)
