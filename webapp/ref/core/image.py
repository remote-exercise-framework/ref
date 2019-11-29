import os
import shutil
import subprocess
from threading import Thread

import docker
from flask import current_app
from werkzeug.local import LocalProxy

from .docker import DockerClient
from .exercise import Exercise, ExerciseBuildStatus

log = LocalProxy(lambda: current_app.logger)

class ExerciseImageManager():
    """
    This class is used to manage an image that belong to an exercise.
    """

    def __init__(self, exercise: Exercise):
        self.dc = DockerClient()
        self.exercise = exercise

    def is_build(self) -> bool:
        """
        Check whether all docker images that belong to the exercise where build.
        """

        log.info(f'Checking if image of exercise {self.exercise} was build')

        #Check entry service docker image
        image_name = self.exercise.entry_service.image_name
        image = self.dc.image(image_name)
        if not image:
            log.info(f'Entry service {image_name} was not build')
            return False

        for service in self.exercise.services:
            if not self.dc.image(service.image_name):
                log.info(f'Service image {service.image_name} was not build')
                return False

        log.info(f'All images have been build')
        return True

    @staticmethod
    def __build_template(app, files, build_cmd, disable_aslr, injected_cmds=[], cmd=['/usr/sbin/sshd', '-D']):
        """
        Returns a dynamically build docker file as string.
        """
        with app.app_context():
            base = app.config['BASE_IMAGE_NAME']
        template = f'FROM {base}\n'

        #Copy files into image
        if files:
            for f in files:
                template += f'COPY {f} /home/user/{f}\n'

        #Run custom commands
        if build_cmd:
            for line in build_cmd:
                template += f'RUN {line}\n'

        for c in injected_cmds:
            template += f'{c}\n'

        if disable_aslr:
            template += 'CMD ["/usr/bin/setarch", "x86_64", "-R"'
            for w in cmd:
                template += f', "{w}"'
        else:
            template += f'CMD ['
            for w in cmd:
                template += f'"{w}", '
            template.rstrip(' ,')

        template += ']'

        return template

    @staticmethod
    def __build_flag_docker_cmd(exercise_service):
        es = exercise_service
        cmd = []
        if es.flag_path:
            cmd += [f'RUN echo "{es.flag_value}" > {es.flag_path}']
            cmd += [f'RUN chown {es.flag_user}:{es.flag_group} "{es.flag_path}"']
            cmd += [f'RUN chmod {es.flag_permission} "{es.flag_path}"']

        return cmd

    @staticmethod
    def __docker_build(build_ctx_path, tag, dockerfile='Dockerfile'):
        """
        Builds a docker image using the dockerfile named 'dockerfile'
        that is located at path 'build_ctx_path'.
        """
        log = ""
        try:
            client = docker.from_env()
            images = client.images
            image, json_log = images.build(path=build_ctx_path, tag=tag, dockerfile=dockerfile)
            json_log = list(json_log)
        except Exception as e:
            raise e
        else:
            for l in json_log:
                if 'stream' in l:
                    log += l['stream']
            return log

    @staticmethod
    def __run_build_entry_service(app, exercise: Exercise):
        """
        Builds the entry service of an exercise.
        """
        log = ' --- Building entry service --- \n'
        image_name = exercise.entry_service.image_name

        flag_cmds = ExerciseImageManager.__build_flag_docker_cmd(exercise.entry_service)

        dockerfile = ExerciseImageManager.__build_template(
            app,
            exercise.entry_service.files,
            exercise.entry_service.build_cmd,
            exercise.entry_service.disable_aslr,
            injected_cmds=flag_cmds
        )

        build_ctx = exercise.template_path
        try:
            with open(f'{build_ctx}/Dockerfile-entry', 'w') as f:
                f.write(dockerfile)
            log += ExerciseImageManager.__docker_build(build_ctx, image_name, dockerfile='Dockerfile-entry')
        except Exception as e:
            raise e

        #Make a copy of the data that needs to be persisted
        if exercise.entry_service.persistance_container_path:
            client = DockerClient()
            log += client.copy_from_image(
                image_name,
                exercise.entry_service.persistance_container_path,
                client.local_path_to_host(exercise.entry_service.persistance_lower)
                )

        return log

    @staticmethod
    def __run_build_peripheral_services(app, exercise: Exercise):
        """
        Builds the peripheral services of an exercise.
        """
        services = []
        #Load objects completely from the database, since we can not lazy load them later
        with app.app_context():
            #joinedload causes eager loading of all attributes of the exercise
            #raiseload raises an exception if there are still lazy attributes
            exercise = Exercise.query.filter(Exercise.id == exercise.id).options(joinedload('*')).first()
            for service in exercise.services:
                services.append(ExerciseService.query.filter(ExerciseService.id == service.id).options(joinedload('*')).first())

        if not services:
            return "No peripheral services to build"

        for service in services:
            log = f' --- Building peripheral service {service.name} --- \n'
            image_name = service.image_name

            flag_cmds = ExerciseImageManager.__build_flag_docker_cmd(service)

            dockerfile = ExerciseImageManager.__build_template(
                app,
                service.files,
                service.build_cmd,
                service.disable_aslr,
                injected_cmds=flag_cmds,
                cmd=service.cmd
            )
            build_ctx = exercise.template_path
            try:
                dockerfile_name = f'Dockerfile-{service.name}'
                with open(f'{build_ctx}/{dockerfile_name}', 'w') as f:
                    f.write(dockerfile)
                log += ExerciseImageManager.__docker_build(build_ctx, image_name, dockerfile=dockerfile_name)
            except Exception as e:
                raise e

        return log


    @staticmethod
    def __run_build(app, exercise: Exercise):
        """
        Builds all docker images that are needed by the passed exercise.
        """
        log = ""
        try:
            #Build entry service
            log += ExerciseImageManager.__run_build_entry_service(app, exercise)
            log += ExerciseImageManager.__run_build_peripheral_services(app, exercise)
        except Exception as e:
            with app.app_context():
                if isinstance(e, docker.errors.BuildError):
                    for l in list(e.build_log):
                        if 'stream' in l:
                            log += l['stream']
                elif isinstance(e, docker.errors.ContainerError):
                    if e.stderr:
                        log = e.stderr.decode()
                log += traceback.format_exc()
                exercise: Exercise = app.db.get(Exercise, id=exercise.id)
                exercise.build_job_result = log
                exercise.build_job_status = ExerciseBuildStatus.FAILED
        else:
            with app.app_context():
                exercise: Exercise = app.db.get(Exercise, id=exercise.id)
                exercise.build_job_result = log
                exercise.build_job_status = ExerciseBuildStatus.FINISHED

        with app.app_context():
            app.db.session.add(exercise)
            app.db.session.commit()

    def build(self):
        """
        Builds all images required for the exercise. This process happens in
        a separate thread that updates the exercise after the build process
        finished. After the build process terminated, the exercises build_job_status
        is ExerciseBuildStatus.FAILED or ExerciseBuildStatus.FINISHED.
        """
        assert not self.is_build()

        log.info(f'Starting build of exercise {self.exercise}')
        t = Thread(target=ExerciseImageManager.__run_build, args=(current_app._get_current_object(), self.exercise))
        t.start()

    def remove(self):
        """
        Deletes all images associated to the exercise.
        """

        log.info(f'Deleting images of {self.exercise} ')

        #Delete docker image of entry service
        image_name = self.exercise.entry_service.image_name
        if self.dc.image(image_name):
            img = self.dc.rmi(image_name)

        for service in self.exercise.services:
            if self.dc.image(service.image_name):
                self.dc.rmi(service.image_name)

        #Remove template
        if os.path.isdir(self.exercise.template_path):
            shutil.rmtree(self.exercise.template_path)

        #Remove overlay
        if os.path.isdir(self.exercise.persistence_path):
            subprocess.check_call(f'sudo rm -rf {self.exercise.persistence_path}', shell=True)
