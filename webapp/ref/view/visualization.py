import datetime
import os
import shutil
import tempfile
import typing
from collections import namedtuple, defaultdict
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Set

import docker
import redis
import rq
import yaml
from flask import (Blueprint, Flask, abort, current_app, redirect,
                   render_template, request, url_for)

from flask_login import login_required
from ref.core.util import utc_datetime_to_local_tz
from ref import db, refbp
from ref.core import (DockerClient, ExerciseConfigError, ExerciseImageManager,
                      ExerciseManager, admin_required, flash)
from ref.model import ConfigParsingError, Exercise, User, Submission
from ref.model.enums import ExerciseBuildStatus
from wtforms import Form, IntegerField, SubmitField, validators
from gviz_api import DataTable

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

def _container_top(container):
    #Create nodes and links for processes running in each container
    processes = container.top()['Processes']
    nodes = []
    links = []
    for p in processes:
        #Indices for p ['UID', 'PID', 'PPID', 'C', 'STIME', 'TTY', 'TIME', 'CMD']
        n = Node(container.id + '_' + p[1], p[7] + f' ({p[1]})', 'process', 0.5)
        l = Link(None, n.id, container.id)
        nodes.append(n)
        links.append(l)

    return nodes, links

@refbp.route('/admin/visualization/containers_and_networks_graph')
@admin_required
def visualization_containers_and_networks_graph():
    nodes = []
    links = []
    valid_ids = set()

    external_node = Node('external', 'external', 'external', 3)
    nodes.append(external_node)

    dc = DockerClient()

    #Create node for each container
    containers = dc.containers()

    executor = ThreadPoolExecutor(max_workers=16)
    top_futures = []

    for c in containers:
        n = Node(c.id, c.name, 'container')
        valid_ids.add(c.id)
        nodes.append(n)

        #Create links and nodes for all processes running in the container
        top_futures.append(executor.submit(_container_top, c))

    #Create node for each network
    networks = dc.networks()
    for network in networks:
        if network.name in ['host', 'none']:
            continue
        n = Node(network.id, network.name, 'network', 3)
        valid_ids.add(network.id)
        nodes.append(n)

    #Create links between containers and networks.
    for network in networks:
        for container_id in network.attrs['Containers']:
            if network.id in valid_ids and container_id in valid_ids:
                l = Link(None, network.id, container_id)
                links.append(l)
            elif network.id in valid_ids:
                #Container does not exists anymore
                n = Node(container_id, container_id + ' (dead)', 'container_dead', color='red')
                l = Link(None, container_id, network.id)
                nodes.append(n)
                links.append(l)
        if network.id in valid_ids and not network.attrs['Internal']:
            l = Link(None, network.id, external_node.id)
            links.append(l)

    #Add the nodes for the running processes
    for future in top_futures:
        n, l = future.result()
        nodes += n
        links += l

    executor.shutdown()

    return render_template('visualization_containers_and_networks_graph.html', nodes=nodes, links=links)

def _min_max_mean_per_assignment():
    assignment_to_exercises_names: Dict[str, Set(str)]  = defaultdict(set)

    exercises = Exercise.all()
    for e in exercises:
        if e.has_deadline():
            assignment_to_exercises_names[e.category].add(e.short_name)

    exercise_name_to_submissions_cnt: Dict[str, int] = defaultdict(int)
    for e in exercises:
        if e.has_deadline():
            exercise_name_to_submissions_cnt[e.short_name] += len(e.submission_heads_global())

    Row = namedtuple('Row', ['assignment', 'min', 'start', 'end', 'max', 'tooltip'])
    data = []

    for assignment_name, exercises_names in sorted(assignment_to_exercises_names.items(), key=lambda e: e[0]):
        min_submissions_cnt = None
        max_submissions_cnt = None
        #List of the total number of submissions for each exercise of the current assignment_name
        submissions_per_exercise: List[int] = []
        tooltip = "#Submissions\n"

        for e in exercises_names:
            exercise_submission_cnt = exercise_name_to_submissions_cnt[e]
            tooltip += f'{e}: {exercise_submission_cnt}\n'
            submissions_per_exercise += [exercise_name_to_submissions_cnt[e]]
            if min_submissions_cnt is None or exercise_submission_cnt < min_submissions_cnt:
                min_submissions_cnt = exercise_submission_cnt
            if max_submissions_cnt is None or exercise_submission_cnt > max_submissions_cnt:
                max_submissions_cnt = exercise_submission_cnt

        avg = sum(submissions_per_exercise) / len(submissions_per_exercise)
        tooltip += '\n'
        tooltip += f'Avg: {avg:.02f}\n'
        tooltip += f'Min: {min_submissions_cnt}\n'
        tooltip += f'Max: {max_submissions_cnt}'

        r = Row(assignment_name, min_submissions_cnt, avg, avg, max_submissions_cnt, tooltip)
        data.append(r)

    min_max_mean_per_assignment = DataTable([
        ('Assignment', 'string'), #Assignment name
        ('min', 'number'), #Lowest number of submission of all exercises that belong to the submission
        ('start', 'number'), #avg
        ('end', 'number'), #avg
        ('max', 'number'), #Highest number of submissions
        ('tooltip', 'string', 'tooltip', {'role': 'tooltip'}), #Tooltip displayed on hover
        ], data)
    return min_max_mean_per_assignment


    # for s in submissions:
    #     ts: datetime.datetime = utc_datetime_to_local_tz(s.submission_ts)
    #     assignment = s.origin_instance.exercise.category
    #     assignment_to_hour_to_submissions[assignment][ts.hour].add(s)

    # for assignment, hours_to_submissions in assignment_to_hour_to_submissions.items():
    #     for hour in range(0, 24):
    #         if hour not in hours_to_submissions:
    #             hours_to_submissions[hour] = set()

    # data = []
    # for assignment, hours_to_submissions in assignment_to_hour_to_submissions.items():
    #     for hour, submissions in hours_to_submissions.items():
    #         data.append([assignment, hour, len(submissions)])

    # for curr_hour in range(0, 24):
    #     row = [curr_hour]
    #     for assignment, hours_to_submissions in assignment_to_hour_to_submissions.items():
    #         for hour, submissions in hours_to_submissions.items():
    #             if hour == curr_hour:


def _submission_per_day_hour():
    submissions = Submission.all()
    assignment_to_hour_to_submissions = defaultdict(lambda: defaultdict(set))

    for s in submissions:
        ts: datetime.datetime = utc_datetime_to_local_tz(s.submission_ts)
        assignment = s.origin_instance.exercise.category

        skip = False
        for submission in assignment_to_hour_to_submissions[assignment][ts.hour]:
            #Ignore multiple submissions of the same exercise and same user for a single hour
            if submission.origin_instance.user == s.origin_instance.user and submission.origin_instance.exercise == s.origin_instance.exercise:
                skip = True
                break

        if not skip:
            assignment_to_hour_to_submissions[assignment][ts.hour].add(s)

    data = []
    for curr_hour in range(0, 24):
        row = [curr_hour]
        for assignment, hours_to_submissions in sorted(assignment_to_hour_to_submissions.items(), key=lambda e: e[0]):
            found = False
            for hour, submissions in hours_to_submissions.items():
                if hour == curr_hour:
                    row += [len(submissions)]
                    found = True
                    break
            if not found:
                row += [0]
        data += [row]

    """
    hour, assignment 1, ...,  assignment n
    0, 1, ..., 26
    1, 77, ..., 11
    """
    day_hour_to_submission_cnt = DataTable([
        ('Hour', 'number'), # The hour of the day (0-23) column
        *[(e, 'number') for e in sorted(assignment_to_hour_to_submissions)] # Per assignment column
    ], data)

    return day_hour_to_submission_cnt


def _submission_per_day_of_week():
    submissions = Submission.all()
    assignment_to_hour_to_submissions = defaultdict(lambda: defaultdict(set))

    for s in submissions:
        ts: datetime.datetime = utc_datetime_to_local_tz(s.submission_ts)
        assignment = s.origin_instance.exercise.category

        skip = False
        for submission in assignment_to_hour_to_submissions[assignment][ts.weekday()]:
            #Ignore multiple submissions of the same exercise and same user for a single hour
            if submission.origin_instance.user == s.origin_instance.user and submission.origin_instance.exercise == s.origin_instance.exercise:
                skip = True
                break

        if not skip:
            assignment_to_hour_to_submissions[assignment][ts.weekday()].add(s)

    data = []
    for curr_hour in range(0, 7):
        row = [curr_hour]
        for assignment, hours_to_submissions in sorted(assignment_to_hour_to_submissions.items(), key=lambda e: e[0]):
            found = False
            for hour, submissions in hours_to_submissions.items():
                if hour == curr_hour:
                    row += [len(submissions)]
                    found = True
                    break
            if not found:
                row += [0]
        data += [row]

    """
    hour, assignment 1, ...,  assignment n
    0, 1, ..., 26
    1, 77, ..., 11
    """
    day_hour_to_submission_cnt = DataTable([
        ('Day of the Week', 'number'), # The hour of the day (0-23) column
        *[(e, 'number') for e in sorted(assignment_to_hour_to_submissions)] # Per assignment column
    ], data)

    return day_hour_to_submission_cnt


@refbp.route('/admin/visualization/graphs')
@admin_required
def visualization_graphs():
    min_max_mean_per_assignment = _min_max_mean_per_assignment()
    day_hour_to_submission_cnt = _submission_per_day_hour()

    return render_template('visualization_graphs.html',
        min_max_mean_per_assignment=min_max_mean_per_assignment.ToJSon(),
        day_hour_to_submission_cnt=day_hour_to_submission_cnt.ToJSon(),
        week_data=_submission_per_day_of_week().ToJSon()
        )