import datetime
import enum
import os
import random
import re
import shutil
import subprocess
import time
import traceback
import typing
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from threading import Thread

import docker
import itsdangerous
import yaml
from flask import current_app
from werkzeug.local import LocalProxy

from ref.model import (Exercise, ExerciseEntryService, ExerciseService,
                       Instance, InstanceEntryService, InstanceService, User)
from ref.model.enums import ExerciseBuildStatus
from sqlalchemy.orm import joinedload, raiseload

from .docker import DockerClient
from .image import ExerciseImageManager
from .instance import InstanceManager

log = LocalProxy(lambda: current_app.logger)

class ExerciseConfigError(Exception):
    pass

class ExerciseManager():
    """
    Used to manage an Exercise.
    """

    def __init__(self, exercise: Exercise):
        self.exercise = exercise

    def image_manager(self) -> ExerciseImageManager:
        return ExerciseImageManager(self.exercise)

    def instance_manager(self) -> InstanceManager:
        return InstanceManager(self.exercise)

    @staticmethod
    def _parse_attr(yaml_dict, attr_name, expected_type, required=True, default=None):
        if required:
            if attr_name not in yaml_dict or yaml_dict[attr_name] == None:
                raise ExerciseConfigError(f'Missing required attribute "{attr_name}"')
        else:
            if attr_name not in yaml_dict or yaml_dict[attr_name] == None:
                if attr_name in yaml_dict:
                    del yaml_dict[attr_name]
                return default

        if not isinstance(yaml_dict[attr_name], expected_type):
            t = type(yaml_dict[attr_name])
            raise ExerciseConfigError(f'Type of attribute "{attr_name}" is {t}, but {expected_type} was expected.')

        ret = yaml_dict[attr_name]
        del yaml_dict[attr_name]
        return ret

    @staticmethod
    def _from_yaml(path) -> Exercise:
        """
        Parses the given yaml config of an exercise and returns an Exercise on success.
        Raises:
            - ExerciseConfigError if the given config could not be parsed.
        """
        exercise = Exercise()

        try:
            with open(path, 'r') as f:
                cfg = f.read()
            cfg = yaml.unsafe_load(cfg)
        except Exception as e:
            raise ExerciseConfigError(str(e))

        #General metadata describing the exercise
        exercise.short_name = ExerciseManager._parse_attr(cfg, 'short-name', str)
        short_name_regex = r'([a-zA-Z0-9._])*'
        if not re.fullmatch(short_name_regex, exercise.short_name):
            raise ExerciseConfigError(f'short-name "{exercise.short_name}" is invalid ({short_name_regex})')

        exercise.category = ExerciseManager._parse_attr(cfg, 'category', str)

        exercise.description = ExerciseManager._parse_attr(cfg, 'description', str, required=False, default=None)

        exercise.version = ExerciseManager._parse_attr(cfg, 'version', int)

        exercise.submission_deadline_start = ExerciseManager._parse_attr(cfg, 'deadline-start', datetime.datetime, required=False, default=None)

        exercise.submission_deadline_end = ExerciseManager._parse_attr(cfg, 'deadline-end', datetime.datetime, required=False, default=None)

        if (exercise.submission_deadline_start is None) != (exercise.submission_deadline_end is None):
            raise ExerciseConfigError('Either both or none of deadline-{start,end} must be set!')

        #Set defaults
        exercise.is_default = False
        exercise.build_job_status = ExerciseBuildStatus.NOT_BUILD

        #Check for unknown attrs (ignore 'services' and 'entry')
        unparsed_keys = list(set(cfg.keys()) - set(['entry', 'services']))
        if unparsed_keys:
            raise ExerciseConfigError(f'Unknown key(s) {unparsed_keys}')

        #Check if there is an entry service
        if 'entry' not in cfg:
            raise ExerciseConfigError('An exercise must have exactly one "entry" section')

        #We got an entry section, parse it
        entry = ExerciseEntryService()
        exercise.entry_service = entry
        entry.exercise = exercise
        entry_cfg = cfg['entry']

        entry.files = ExerciseManager._parse_attr(entry_cfg, 'files', list, required=False, default=None)
        if entry.files:
            for f in entry.files:
                if not isinstance(f, str):
                    raise ExerciseConfigError(f'Files must be a list of strings {entry.files}')

        cmd = ExerciseManager._parse_attr(entry_cfg, 'build-cmd', list, required=False, default=None)
        entry.build_cmd = None
        if cmd:
            entry.build_cmd = []
            for line in cmd:
                if not isinstance(line, str):
                    raise ExerciseConfigError(f"Command must be a list of strings: {cmd}")
                entry.build_cmd += [f"{line}"]

        entry.disable_aslr = ExerciseManager._parse_attr(entry_cfg, 'disable-aslr', bool, required=False, default=False)
        entry.cmd = ExerciseManager._parse_attr(entry_cfg, 'cmd', list, required=False, default=['/bin/bash'])
        entry.persistance_container_path = ExerciseManager._parse_attr(entry_cfg, 'persistance-path', str, required=False, default=None)
        entry.readonly = ExerciseManager._parse_attr(entry_cfg, 'read-only', bool, required=False, default=False)
        entry.allow_internet = ExerciseManager._parse_attr(entry_cfg, 'allow-internet', bool, required=False, default=False)

        flag_config = entry_cfg.get('flag')
        if flag_config:
            entry.flag_path = ExerciseManager._parse_attr(flag_config, 'location', str, required=True)
            entry.flag_value = ExerciseManager._parse_attr(flag_config, 'value', str, required=True)
            entry.flag_user = ExerciseManager._parse_attr(flag_config, 'user', str, required=False, default='admin')
            entry.flag_group = ExerciseManager._parse_attr(flag_config, 'group', str, required=False, default='admin')
            entry.flag_permission = ExerciseManager._parse_attr(flag_config, 'permission', int, required=False, default='400')
            del entry_cfg['flag']

        if entry.readonly and entry.persistance_container_path:
            raise ExerciseConfigError('persistance-path and readonly are mutually exclusive')

        #Check for unknown attrs
        unparsed_keys = list(entry_cfg.keys())
        if unparsed_keys:
            raise ExerciseConfigError(f'Unknown key(s) in entry service configuration {unparsed_keys}')

        #Parse peripheral services
        peripheral_cfg = cfg.get('services')
        if not peripheral_cfg:
            return exercise

        services_names = set()
        for service_name, service_values in peripheral_cfg.items():
            service = ExerciseService()
            service_name_regex = r'([a-zA-Z0-9_-])*'
            if not re.fullmatch(service_name_regex, service_name):
                raise ExerciseConfigError(f'Service name "{service_name}"" is invalid ({service_name_regex})')
            service.name = service_name

            if service_name in services_names:
                raise ExerciseConfigError(f'There is already a service with name {service_name}.')
            services_names.add(service_name)

            service.disable_aslr = ExerciseManager._parse_attr(service_values, 'disable-aslr', bool, required=False, default=False)

            service.files = ExerciseManager._parse_attr(service_values, 'files', list, required=False, default=None)
            if entry.files:
                for f in service.files:
                    if not isinstance(f, str):
                        raise ExerciseConfigError(f'Files must be a list of strings {service.files}')

            service.build_cmd = ExerciseManager._parse_attr(service_values, 'build-cmd', list, required=False, default=None)
            if service.build_cmd:
                for line in service.build_cmd:
                    if not isinstance(line, str):
                        raise ExerciseConfigError(f"Command must be a list of strings: {cmd}")

            service.cmd = ExerciseManager._parse_attr(service_values, 'cmd', list)

            service.readonly =  ExerciseManager._parse_attr(service_values, 'read-only', bool, required=False, default=False)

            service.allow_internet = ExerciseManager._parse_attr(service_values, 'allow-internet', bool, required=False, default=False)

            flag_config = service_values.get('flag')
            if flag_config:
                service.flag_path = ExerciseManager._parse_attr(flag_config, 'location', str, required=True)
                service.flag_value = ExerciseManager._parse_attr(flag_config, 'value', str, required=True)
                service.flag_user = ExerciseManager._parse_attr(flag_config, 'user', str, required=False, default='admin')
                service.flag_group = ExerciseManager._parse_attr(flag_config, 'group', str, required=False, default='admin')
                service.flag_permission = ExerciseManager._parse_attr(flag_config, 'permission', int, required=False, default='400')
                del service_values['flag']

            exercise.services.append(service)

        return exercise

    @staticmethod
    def create(exercise: Exercise):
        """
        Copies all data that belong to the passed exercise to a local folder.
        After calling this function, the exercise *must* be added to the DB and can be used
        to create new instances.
        """
        template_path = Path(current_app.config['IMPORTED_EXERCISES_PATH'])
        template_path = template_path.joinpath(f'{exercise.short_name}-{exercise.version}')
        log.info(f'Creating {template_path}')
        assert not template_path.exists()

        persistence_path = Path(current_app.config['PERSISTANCE_PATH'])
        persistence_path = persistence_path.joinpath(f'{exercise.short_name}-{exercise.version}')
        log.info(f'Creating {persistence_path}')
        assert not persistence_path.exists()

        persistence_path.mkdir(parents=True)
        exercise.persistence_path = persistence_path.as_posix()

        try:
            #Copy data from import folder into an internal folder
            shutil.copytree(exercise.template_import_path, template_path.as_posix())
        except:
            #Restore state as before create() was called.
            if template_path.exists():
                shutil.rmtree(template_path.as_posix())
            shutil.rmtree(persistence_path.as_posix())

        exercise.template_path = template_path.as_posix()
        return ExerciseManager(exercise)

    @staticmethod
    def from_template(path: str) -> Exercise:
        """
        Parses the template in the given folder. This only returns a Exercise
        without copying its data to the local storage nor adding it to the current transaction.
        Before commiting it to the DB, ExerciseManager.create(exercise) must be called.
        Raises:
            - ExerciseConfigError if the template could not be parsed.
        """
        if hasattr(path, 'as_posix'):
            path = path.as_posix()
        cfg = os.path.join(path, 'settings.yml')
        exercise = ExerciseManager._from_yaml(cfg)
        exercise.template_import_path = path

        return exercise

    def get_instances(self) -> typing.List[Instance]:
        """
        Returns all instances of the given exercise.
        """
        instances = Instance.query.filter(Instance.exercise == self.exercise).all()
        return instances
