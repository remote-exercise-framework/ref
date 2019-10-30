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

    def __init__(self, id, name, type, size=1):
        self.id = id
        self.name = name
        self.type = type
        self.size = size

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
    containers = dc.containers()
    for c in containers:
        n = Node(c.id, c.name, 'container')
        valid_ids.append(c.id)
        nodes.append(n)
    nodes.append(n)

    networks = dc.networks()
    for e in networks:
        if e.name in ['host', 'none']:
            continue
        n = Node(e.id, e.name, 'network', 3)
        valid_ids.append(e.id)
        nodes.append(n)

    for e in networks:
        e.reload()
        for k, v in e.attrs['Containers'].items():
            if e.id in valid_ids and k in valid_ids:
                l = Link('test', e.id, k)
                links.append(l)
        if e.id in valid_ids and not e.attrs['Internal']:
            l = Link('test', e.id, external_node.id)
            links.append(l)

    return render_template('container_graph.html', nodes=nodes, links=links)
