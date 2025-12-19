from concurrent.futures import ThreadPoolExecutor

from flask import render_template

from ref import refbp
from ref.core import DockerClient, admin_required


class Node:
    def __init__(self, id, name, type, size=1, color=None):
        self.id = id
        self.name = name
        self.type = type
        self.size = size
        self.color = color


class Link:
    def __init__(self, name, source, target):
        self.name = name
        self.source = source
        self.target = target


def _container_top(container):
    # Create nodes and links for processes running in each container
    processes = container.top()["Processes"]
    nodes = []
    links = []
    for p in processes:
        # Indices for p ['UID', 'PID', 'PPID', 'C', 'STIME', 'TTY', 'TIME', 'CMD']
        node = Node(container.id + "_" + p[1], p[7] + f" ({p[1]})", "process", 0.5)
        link = Link(None, node.id, container.id)
        nodes.append(node)
        links.append(link)

    return nodes, links


@refbp.route("/admin/graph")
@admin_required
def graph():
    nodes = []
    links = []
    valid_ids = set()

    external_node = Node("external", "external", "external", 3)
    nodes.append(external_node)

    dc = DockerClient()

    # Create node for each container
    containers = dc.containers()

    executor = ThreadPoolExecutor(max_workers=16)
    top_futures = []

    for c in containers:
        node = Node(c.id, c.name, "container")
        valid_ids.add(c.id)
        nodes.append(node)

        # Create links and nodes for all processes running in the container
        top_futures.append(executor.submit(_container_top, c))

    # Create node for each network
    networks = dc.networks()
    for network in networks:
        if network.name in ["host", "none"]:
            continue
        node = Node(network.id, network.name, "network", 3)
        valid_ids.add(network.id)
        nodes.append(node)

    # Create links between containers and networks.
    for network in networks:
        for container_id in network.attrs["Containers"]:
            if network.id in valid_ids and container_id in valid_ids:
                link = Link(None, network.id, container_id)
                links.append(link)
            elif network.id in valid_ids:
                # Container does not exists anymore
                node = Node(
                    container_id,
                    container_id + " (dead)",
                    "container_dead",
                    color="red",
                )
                link = Link(None, container_id, network.id)
                nodes.append(node)
                links.append(link)
        if network.id in valid_ids and not network.attrs["Internal"]:
            link = Link(None, network.id, external_node.id)
            links.append(link)

    # Add the nodes for the running processes
    for future in top_futures:
        proc_nodes, proc_links = future.result()
        nodes += proc_nodes
        links += proc_links

    executor.shutdown()

    return render_template("container_graph.html", nodes=nodes, links=links)
