import datetime
import os
import shutil
import tempfile
import typing
from collections import namedtuple
from pathlib import Path

import docker
import redis
import rq
import yaml
from flask import (Blueprint, Flask, abort, current_app, redirect,
                   render_template, request, url_for)
from wtforms import Form, IntegerField, SubmitField, validators

from ref import db, refbp
from ref.core import (ExerciseConfigError,
                      ExerciseImageManager, ExerciseManager, flash, admin_required, DockerClient)
from ref.model import ConfigParsingError, Exercise, User
from ref.model.enums import ExerciseBuildStatus

from flask_login import login_required

lerr = lambda msg: current_app.logger.error(msg)
linfo = lambda msg: current_app.logger.info(msg)
lwarn = lambda msg: current_app.logger.warning(msg)

class Node():

    def __init__(self, id, name, type, size=1, color=None):
        self.id = id
        self.name = name
        self.type = type
        self.size = size
        self.color = color

class Link():

    def __init__(self, name, source, target):
        self.name = name
        self.source = source
        self.target = target


@refbp.route('/graph')
@admin_required
def graph():
    nodes = []
    links = []
    valid_ids = []

    external_node = Node('external', 'external', 'external', 3)
    nodes.append(external_node)

    dc = DockerClient()

    #Create node for each container
    containers = dc.containers()
    for c in containers:
        n = Node(c.id, c.name, 'container')
        valid_ids.append(c.id)
        nodes.append(n)

        #Create nodes and links for processes running in each container
        processes = c.top()['Processes']
        for p in processes:
            #Indices for p ['UID', 'PID', 'PPID', 'C', 'STIME', 'TTY', 'TIME', 'CMD']
            n = Node(c.id + '_' + p[1], p[7] + f' ({p[1]})', 'process', 0.5)
            nodes.append(n)
            l = Link('test', n.id, c.id)
            links.append(l)

    #Create node for each network
    networks = dc.networks()
    for network in networks:
        if network.name in ['host', 'none']:
            continue
        n = Node(network.id, network.name, 'network', 3)
        valid_ids.append(network.id)
        nodes.append(n)

    #Create links between containers and networks.
    for network in networks:
        network.reload()
        for container_id in network.attrs['Containers']:
            if network.id in valid_ids and container_id in valid_ids:
                l = Link('test', network.id, container_id)
                links.append(l)
            elif network.id in valid_ids:
                #Container does not exists anymore
                n = Node(container_id, container_id + ' (dead)', 'container_dead', color='red')
                l = Link('test', container_id, network.id)
                nodes.append(n)
                links.append(l)
        if network.id in valid_ids and not network.attrs['Internal']:
            l = Link('test', network.id, external_node.id)
            links.append(l)

    return render_template('container_graph.html', nodes=nodes, links=links)
