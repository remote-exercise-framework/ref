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
from sqlalchemy.orm import joinedload, raiseload
from werkzeug.local import LocalProxy

from ref.model import (Exercise, ExerciseEntryService, ExerciseService,
                       Instance, InstanceEntryService, InstanceService, User, RessourceLimits)
from ref.model.enums import ExerciseBuildStatus

from ref.core.util import datetime_to_naive_utc, datetime_transmute_into_local
from .docker import DockerClient
from .image import ExerciseImageManager
from .instance import InstanceManager

log = LocalProxy(lambda: current_app.logger)

class ExerciseConfigError(Exception):
    pass

class ExerciseManager():
    """
    Used to manage an existing Exercise or to create a new one from a config file.
    """

    def __init__(self, exercise: Exercise):
        self.exercise = exercise

    def image_manager(self) -> ExerciseImageManager:
        return ExerciseImageManager(self.exercise)

    def instance_manager(self) -> InstanceManager:
        return InstanceManager(self.exercise)

    @staticmethod
    def _parse_attr(yaml_dict, attr_name, expected_type, required=True, default=None, validators=None):
        """
        Parse an attribute from an exercise config.
        """
        if required:
            if attr_name not in yaml_dict or yaml_dict[attr_name] == None:
                raise ExerciseConfigError(f'Missing required attribute "{attr_name}"')
        else:
            if attr_name not in yaml_dict or yaml_dict[attr_name] == None:
                if attr_name in yaml_dict:
                    del yaml_dict[attr_name]
                return default

        if expected_type == datetime.time:
            try:
                yaml_dict[attr_name] = datetime.time.fromisoformat(yaml_dict[attr_name])
            except:
                pass

        if not isinstance(yaml_dict[attr_name], expected_type):
            t = type(yaml_dict[attr_name])
            raise ExerciseConfigError(f'Type of attribute "{attr_name}" is {t}, but {expected_type} was expected.')

        ret = yaml_dict[attr_name]
        if validators:
            for (fn, err_msg) in validators:
                if not fn(ret):
                    raise ExerciseConfigError(f'Validation for attribute {attr_name} failed: {err_msg}')


        del yaml_dict[attr_name]
        return ret

    @staticmethod
    def _parse_general_data(exercise: Exercise, cfg, cfg_folder_path):
        """
        General metadata describing of an exercise.
        Args:
            exercise: Object into that the parsed attributes are saved.
            cfg: The YML config as disconary tree.
            cfg_folder_path: Path to the folder that contains the currently parsed config.
        Raises:
            - ExerciseConfigError if the config does not conform to the specification.
        """
        exercise.short_name = ExerciseManager._parse_attr(cfg, 'short-name', str)
        short_name_regex = r'([a-zA-Z0-9._])*'
        if not re.fullmatch(short_name_regex, exercise.short_name):
            raise ExerciseConfigError(f'short-name "{exercise.short_name}" is invalid ({short_name_regex})')

        exercise.category = ExerciseManager._parse_attr(cfg, 'category', str)

        exercise.version = ExerciseManager._parse_attr(cfg, 'version', int)

        deadline = ExerciseManager._parse_attr(cfg, 'deadline', dict, required=False, default=None)
        if deadline:
            start = ExerciseManager._parse_attr(deadline, 'start', dict, required=False, default=None)
            end = ExerciseManager._parse_attr(deadline, 'end', dict, required=False, default=None)
            if not start or not end:
                raise ExerciseConfigError('Missing "start:" or "end:" in deadline entry!')
            start_date = ExerciseManager._parse_attr(start, 'date', datetime.date, required=True, default=None)
            start_time = ExerciseManager._parse_attr(start, 'time', datetime.time, required=True, default=None)
            end_date = ExerciseManager._parse_attr(end, 'date', datetime.date, required=True, default=None)
            end_time = ExerciseManager._parse_attr(end, 'time', datetime.time, required=True, default=None)
            exercise.submission_deadline_start = datetime_transmute_into_local(datetime.datetime.combine(start_date, start_time))
            exercise.submission_deadline_end = datetime_transmute_into_local(datetime.datetime.combine(end_date, end_time))
        else:
            # TODO: Legacy -> Remove
            exercise.submission_deadline_start = ExerciseManager._parse_attr(cfg, 'deadline-start', datetime.datetime, required=False, default=None)
            #Strip timezone from datetime and make it utc
            if exercise.submission_deadline_start:
                exercise.submission_deadline_start = datetime_to_naive_utc(exercise.submission_deadline_start)

            exercise.submission_deadline_end = ExerciseManager._parse_attr(cfg, 'deadline-end', datetime.datetime, required=False, default=None)
            #Strip timezone from datetime and make it utc
            if exercise.submission_deadline_end:
                exercise.submission_deadline_end = datetime_to_naive_utc(exercise.submission_deadline_end)

        exercise.submission_test_enabled = ExerciseManager._parse_attr(cfg, 'submission-test', bool, required=False, default=False)

        if exercise.submission_test_enabled:
            test_script_path = Path(cfg_folder_path) / 'submission_tests'
            if not test_script_path.is_file():
                raise ExerciseConfigError('Missing submission_tests file!')

        exercise.max_grading_points = ExerciseManager._parse_attr(cfg, 'grading-points', int, required=False, default=None)
        if (exercise.max_grading_points is None) != (exercise.submission_deadline_end is None):
            raise ExerciseConfigError('Either both or none of "grading-points" and "submission_deadline_end" must be set')

        if (exercise.submission_deadline_start is None) != (exercise.submission_deadline_end is None):
            raise ExerciseConfigError('Either both or none of deadline-{start,end} must be set!')

        if exercise.submission_deadline_start is not None:
            if exercise.submission_deadline_start >= exercise.submission_deadline_end:
                raise ExerciseConfigError('Deadline start must be smaller then deadline end.')

        #Set defaults
        exercise.is_default = False
        exercise.build_job_status = ExerciseBuildStatus.NOT_BUILD

        #Check for unknown attrs (ignore 'services' and 'entry')
        unparsed_keys = list(set(cfg.keys()) - set(['entry', 'services']))
        if unparsed_keys:
            raise ExerciseConfigError(f'Unknown attribute(s) {" ".join(unparsed_keys)}')

    @staticmethod
    def _parse_entry_service(exercise: Exercise, cfg):
        """
        Parse the config section that describes the entry service.
        Args:
            exercise: Object into that the parsed attributes are saved.
            cfg: The YML config as disconary tree.
        Raises:
            - ExerciseConfigError if the config does not conform to the specification.
        """

        #Check if there is an entry service section
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
        entry.no_randomize_files = ExerciseManager._parse_attr(entry_cfg, 'no-randomize', list, required=False, default=[])
        entry.cmd = ExerciseManager._parse_attr(entry_cfg, 'cmd', list, required=False, default=['/bin/bash'])
        entry.persistance_container_path = ExerciseManager._parse_attr(entry_cfg, 'persistance-path', str, required=False, default=None)
        entry.readonly = ExerciseManager._parse_attr(entry_cfg, 'read-only', bool, required=False, default=False)
        entry.allow_internet = ExerciseManager._parse_attr(entry_cfg, 'allow-internet', bool, required=False, default=False)


        def __check_mem_limit(val, min_mb):
            if not val or val.strip() == '0' or val.lower() == 'none':
                return None

            match = re.search(r"^\ *([1-9][0-9]*).*?(GiB|MiB)", val)
            if not match:
                raise ExerciseConfigError('Invalid memory size value! Please use "GiB" or "MiB" as suffix!')
            val, unit = match.group(1,2)
            val = int(val)
            is_mib = unit == 'MiB'


            if not is_mib:
                # Convert GiB to Mib.
                val = val * 1024

            if val < min_mb:
                raise ExerciseConfigError(f'Memory limits must be greater or equal to {min_mb} MiB.')

            return int(val)

        limits_config = ExerciseManager._parse_attr(entry_cfg, 'limits', dict, required=False, default=None)
        if limits_config:
            entry.ressource_limit = RessourceLimits()

            validators = []
            validators += [(lambda v: v >= 0, "Value must be greater or equal to zero. Zero disables this limit.")]
            validators += [(lambda v: len(str(v).split('.')[1]) < 2, "No more than 2 decimal places are supported.")]
            entry.ressource_limit.cpu_cnt_max = ExerciseManager._parse_attr(limits_config, 'cpu-cnt-max', float, required=False, default=None, validators=validators)

            validators = []
            validators += [(lambda v: v > 0, "Value must be greater than zero")]
            entry.ressource_limit.cpu_shares = ExerciseManager._parse_attr(limits_config, 'cpu-shares', int, required=False, default=None, validators=validators)

            validators = []
            validators += [(lambda v: v >= 64, "Value must be greater or equal than 64")]
            entry.ressource_limit.pids_max = ExerciseManager._parse_attr(limits_config, 'pid-cnt-max', int, required=False, default=None, validators=validators)

            entry.ressource_limit.memory_in_mb = ExerciseManager._parse_attr(limits_config, 'phys-mem', str, required=False, default=None)
            entry.ressource_limit.memory_swap_in_mb = ExerciseManager._parse_attr(limits_config, 'swap-mem', str, required=False, default=None)
            entry.ressource_limit.memory_kernel_in_mb = ExerciseManager._parse_attr(limits_config, 'kernel-mem', str, required=False, default=None)

            entry.ressource_limit.memory_in_mb = __check_mem_limit(entry.ressource_limit.memory_in_mb, 64)
            entry.ressource_limit.memory_swap_in_mb = __check_mem_limit(entry.ressource_limit.memory_swap_in_mb, 0)
            entry.ressource_limit.memory_kernel_in_mb = __check_mem_limit(entry.ressource_limit.memory_kernel_in_mb, 64)

            unparsed_keys = list(limits_config.keys())
            if unparsed_keys:
                raise ExerciseConfigError(f'Unknown attribute(s) in limits configuration {", ".join(unparsed_keys)}')




        flag_config = entry_cfg.get('flag')
        if flag_config:
            entry.flag_path = ExerciseManager._parse_attr(flag_config, 'location', str, required=False, default='/home/user/flag')
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
            raise ExerciseConfigError(f'Unknown attribute(s) in entry service configuration {", ".join(unparsed_keys)}')

    @staticmethod
    def _parse_peripheral_services(exercise: Exercise, cfg):
        """
        Parse the services config section that describes the peripheral services (if any).
        Args:
            exercise: Object into that the parsed attributes are saved.
            cfg: The YML config as disconary tree.
        Raises:
            - ExerciseConfigError if the config does not conform to the specification.
        """

        peripheral_cfg = cfg.get('services')
        if not peripheral_cfg:
            return

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
            if service.files:
                for f in service.files:
                    if not isinstance(f, str):
                        raise ExerciseConfigError(f'Files must be a list of strings {service.files}')

            service.build_cmd = ExerciseManager._parse_attr(service_values, 'build-cmd', list, required=False, default=None)
            if service.build_cmd:
                for line in service.build_cmd:
                    if not isinstance(line, str):
                        raise ExerciseConfigError(f"Command must be a list of strings: {service.build_cmd}")

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

    @staticmethod
    def check_global_constraints(exercise: Exercise):
        """
        Check whether the exercise violates any constraints in combination with already imported
        exercises of the same type.
        Args:
            exercise: The exercises that should be checked for constraint violations.
        """
        predecessors = exercise.predecessors()
        successors = exercise.successors()

        for e in predecessors:
            if e.has_graded_submissions() and e.submission_deadline_end != exercise.submission_deadline_end:
                raise ExerciseConfigError('Changing the deadline of an already graded exercise is not allowed!')

            if e.has_graded_submissions() and e.max_grading_points != exercise.max_grading_points:
                raise ExerciseConfigError('Changing the grading points of an already graded exercise is not allowed!')

            if bool(e.entry_service.readonly) != bool(exercise.entry_service.readonly):
                raise ExerciseConfigError('Changeing the readonly flag between versions is not allowed.')

            if e.entry_service.persistance_container_path != exercise.entry_service.persistance_container_path:
                raise ExerciseConfigError('Persistance path changes are not allowed between versions')



    @staticmethod
    def _from_yaml(cfg_path: str) -> Exercise:
        """
        Parses the YAML config of an exercise.
        Args:
            cfg_path: Path to the config file to parse.
        Raises:
            - ExerciseConfigError if the given config could not be parsed.
            The Exception contains a string describing the problem that occurred.
        Returns:
            A new Exercise that can be passed to ExerciseManager.create()
            to finalize the creation process.
        """

        #The exercise in that the parsed data is stored.
        exercise = Exercise()

        #The folder that contains the .yml file.
        cfg_folder = Path(cfg_path).parent.as_posix()

        try:
            with open(cfg_path, 'r') as f:
                cfg = f.read()
                cfg = yaml.unsafe_load(cfg)
        except Exception as e:
            raise ExerciseConfigError(str(e))

        if cfg is None:
            raise ExerciseConfigError(f'Config {cfg_path} is empty.')

        #Parse general attributes like task name, version,...
        ExerciseManager._parse_general_data(exercise, cfg, cfg_folder)

        #Parse the entry service configuration
        ExerciseManager._parse_entry_service(exercise, cfg)

        #Parse peripheral services configurations (if any)
        ExerciseManager._parse_peripheral_services(exercise, cfg)

        return exercise

    @staticmethod
    def create(exercise: Exercise) -> 'ExerciseManager':
        """
        Copies all data that belong to the passed exercise to a local folder.
        After calling this function, the exercise *must* be added to the DB and can be used
        to create new instances.
        Args:
            exercise: The exercise that should be created. The passed Exercise must be
                created by calling ExerciseManager._from_yaml().
        """
        template_path = Path(current_app.config['IMPORTED_EXERCISES_PATH'])
        template_path = template_path.joinpath(f'{exercise.short_name}-{exercise.version}')
        log.info(f'Creating {template_path}')
        assert not template_path.exists()

        persistence_path = Path(current_app.config['PERSISTANCE_PATH'])
        persistence_path = persistence_path.joinpath(f'{exercise.short_name}-{exercise.version}')
        log.info(f'Creating {persistence_path}')
        assert not persistence_path.exists()

        try:
            persistence_path.mkdir(parents=True)
            #Copy data from import folder into an internal folder
            subprocess.run(['mkdir', '-p', template_path.as_posix()], check=True)
            subprocess.run(
                ['/usr/bin/rsync', '-a', f'{exercise.template_import_path}/', template_path.as_posix()],
                check=True)
        except:
            #Restore state as before create() was called.
            if template_path.exists():
                shutil.rmtree(template_path.as_posix())
            if persistence_path.exists():
                shutil.rmtree(persistence_path.as_posix())
            raise

        exercise.persistence_path = persistence_path.as_posix()
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
