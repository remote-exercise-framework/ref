import os
import shutil
import subprocess
import traceback
from threading import Thread
from typing import List
from pathlib import Path

import docker
from flask import Flask, current_app
from sqlalchemy.orm import joinedload, raiseload
from werkzeug.local import LocalProxy

from ref.core import InconsistentStateError, inconsistency_on_error

from .docker import DockerClient
from .exercise import Exercise, ExerciseBuildStatus, ExerciseService

log = LocalProxy(lambda: current_app.logger)

class ImageBuildError(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)

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
        Raises:
            *: If communication with the docker deamon fails.
        """
        #Check entry service docker image
        image_name = self.exercise.entry_service.image_name
        image = self.dc.image(image_name)
        if not image:
            return False

        for service in self.exercise.services:
            if not self.dc.image(service.image_name):
                return False

        return True

    @staticmethod
    def __build_template(app: Flask, files: List[str], build_cmd: List[str], disable_aslr: bool, custom_build_cmd: List[str] = [], default_cmd: List[str] = ['/usr/sbin/sshd', '-D', '-e']) -> str:
        """
        FIXME: Replace this with jinja.
        Generates a Dockerfile in memory and returns it as a string.
        Args:
            app: The Flask app.
            files: Files to COPY into the image.
            build_cmd: Command to executes using RUN {cmd}.
            disabe_aslr: Disabel aslr for the whole container.
            custom_build_cmd: List of arbitrary strings that are injected into the template.
            default_cmd: The default cmd that is executed when the image is started.
        """
        assert isinstance(build_cmd, list)
        assert isinstance(custom_build_cmd, list)
        assert isinstance(default_cmd, list)

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

        for c in custom_build_cmd:
            template += f'{c}\n'

        if disable_aslr:
            template += 'CMD ["/usr/bin/setarch", "x86_64", "-R"'
            for w in default_cmd:
                template += f', "{w}"'
        else:
            template += f'CMD ['
            for w in default_cmd:
                template += f'"{w}", '
            template = template.rstrip(', ')

        template += ']'

        return template

    @staticmethod
    def __build_flag_docker_cmd(exercise_service) -> List[str]:
        """
        Generate a list of docker commands to create a flag.
        """
        es = exercise_service
        cmd = []
        if es.flag_path:
            cmd += [f'RUN echo "{es.flag_value}" > {es.flag_path}']
            cmd += [f'RUN chown {es.flag_user}:{es.flag_group} "{es.flag_path}"']
            cmd += [f'RUN chmod {es.flag_permission} "{es.flag_path}"']

        return cmd

    @staticmethod
    def __docker_build(build_ctx_path: str, tag: str, dockerfile='Dockerfile') -> str:
        """
        Builds a docker image using the dockerfile named 'Dockerfile'
        that is located in the folder 'build_ctx_path' points to.
        Args:
            build_ctx_path: The docker build context.
            tag: The image name.
            dockerfile: Name of the target Dockerfile.
        Raises:
            *: If the image building process fails.
        Return:
            The build log.
        """
        log = ""
        try:
            client = docker.from_env()
            images = client.images
            image, json_log = images.build(path=build_ctx_path, tag=tag, dockerfile=dockerfile)
            json_log = list(json_log)
        except Exception as e:
            dc = DockerClient()
            if dc.image(tag):
                dc.rmi(tag)
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
        Raises:
            *: If the build process fails.
        """
        dc = DockerClient()

        with app.app_context():
            app.logger.info(f'Building entry service of exercise {exercise}')

        build_log = ' --- Building entry service --- \n'
        image_name = exercise.entry_service.image_name

        #Generate cmds to add flag to image
        cmds = ExerciseImageManager.__build_flag_docker_cmd(exercise.entry_service)

        #Copy submission test suit into image (if any)
        if exercise.submission_test_enabled:
            assert os.path.isfile(f'{exercise.template_path}/submission_tests')
            cmds += [
                'COPY submission_tests /usr/local/bin/submission_tests',
                'RUN chown root:root /usr/local/bin/submission_tests && chmod 700 /usr/local/bin/submission_tests'
                ]

        dockerfile = ExerciseImageManager.__build_template(
            app,
            exercise.entry_service.files,
            exercise.entry_service.build_cmd,
            exercise.entry_service.disable_aslr,
            custom_build_cmd=cmds
        )

        build_ctx = exercise.template_path
        try:
            with open(f'{build_ctx}/Dockerfile-entry', 'w') as f:
                f.write(dockerfile)
            build_log += ExerciseImageManager.__docker_build(build_ctx, image_name, dockerfile='Dockerfile-entry')
        except Exception as e:
            raise e

        with app.app_context():
            app.logger.info(f'Build of {exercise} finished. Now copying persisted folder.')

        #Make a copy of the data that needs to be persisted
        if exercise.entry_service.persistance_container_path:
            try:
                build_log += dc.copy_from_image(
                    image_name,
                    exercise.entry_service.persistance_container_path,
                    dc.local_path_to_host(exercise.entry_service.persistance_lower)
                    )
            except Exception as e:
                #Cleanup
                image = dc.image(image_name)
                if image:
                    dc.rmi(image_name)
                raise Exception('Failed to copy data') from e

            ExerciseImageManager.handle_no_randomize_files(exercise, dc, build_log, image_name)


        with app.app_context():
            app.logger.info('Entry service build finished.')

        return build_log

    @staticmethod
    def handle_no_randomize_files(exercise: Exercise, dc, build_log: str, image_name: str):
        if not exercise.entry_service.no_randomize_files:
            return

        for entry in exercise.entry_service.no_randomize_files:
            build_log += f'[+] Disabling ASLR for {entry}\n'
            path = Path(exercise.entry_service.persistance_lower) / entry
            if not path.exists():
                dc.rmi(image_name)
                raise ImageBuildError(f'[!] Failed to find file "{entry}" in "{exercise.entry_service.persistance_container_path}. Make sure to use path relative from home."\n')

            cmd = f'sudo setfattr -n security.no_randomize -v true {path}'
            build_log += f'Running {cmd}\n'
            try:
                subprocess.check_call(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except Exception as e:
                dc.rmi(image_name)
                raise Exception(f'Failed to disable ASLR for {entry}') from e

    @staticmethod
    def __run_build_peripheral_services(app, exercise: Exercise) -> str:
        """
        Builds the peripheral services of an exercise.
        Raises:
            *: If the build process fails.
        Returns:
            The build log on success
        """
        services = []

        #Load objects completely from the database, since we can not lazy load them later
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
                custom_build_cmd=flag_cmds,
                default_cmd=service.cmd
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
    def __purge_entry_service_image(exercise: Exercise, force=False):
        """
        Delete the entry service docker image.
        Can also be called if the images was not build.
        """
        dc = DockerClient()
        name = exercise.entry_service.image_name
        if dc.image(name):
            dc.rmi(name, force=force)

    @staticmethod
    def __purge_peripheral_services_images(exercise: Exercise, force=False):
        """
        Delete the docker images of all peripheral services if any.
        Can also be called if the images was not build.
        """
        dc = DockerClient()
        for service in exercise.services:
            name = service.image_name
            if dc.image(name):
                dc.rmi(name, force=force)

    @staticmethod
    def __run_build(app, exercise: Exercise):
        """
        Builds all docker images that are needed by the passed exercise.
        """
        failed = False
        log_buffer: str = ""
        try:
            #Build entry service
            with app.app_context():
                log_buffer += ExerciseImageManager.__run_build_entry_service(app, exercise)
                log_buffer += ExerciseImageManager.__run_build_peripheral_services(app, exercise)
        except Exception as e:
            with app.app_context():
                if isinstance(e, docker.errors.BuildError):
                    for l in list(e.build_log):
                        if 'stream' in l:
                            log_buffer += l['stream']
                elif isinstance(e, docker.errors.ContainerError):
                    if e.stderr:
                        log_buffer = e.stderr.decode()
                elif isinstance(e, ImageBuildError):
                    log_buffer = f'Error while building image:\n{e}'
                else:
                    app.logger.error(f'{log_buffer}\nUnexpected error during build', exc_info=True)
                log_buffer += traceback.format_exc()
                failed = True

        exercise.build_job_result = log_buffer

        if failed:
            exercise.build_job_status = ExerciseBuildStatus.FAILED
            try:
                with app.app_context():
                    ExerciseImageManager.__purge_entry_service_image(exercise)
                    ExerciseImageManager.__purge_peripheral_services_images(exercise)
            except:
                #No one we can report the error to, so just log it.
                with app.app_context():
                    app.logger.error('Cleanup failed', exc_info=True)
        else:
            with app.app_context():
                exercise.build_job_status = ExerciseBuildStatus.FINISHED

        with app.app_context():
            app.logger.info('Commiting build result to DB')
            app.db.session.add(exercise)
            app.db.session.commit()


    def build(self) -> None:
        """
        Builds all images required for the exercise. This process happens in
        a separate thread that updates the exercise after the build process
        finished. After the build process terminated, the exercises build_job_status
        is ether ExerciseBuildStatus.FAILED or ExerciseBuildStatus.FINISHED.
        """
        self.delete_images()

        # Make sure the exercise does not try to lazy load attributes when detached
        # from the current database session.
        exercise = self.exercise.refresh(eager=True)

        log.info(f'Starting build of exercise {exercise}')
        t = Thread(target=ExerciseImageManager.__run_build, args=(current_app._get_current_object(), exercise))
        t.start()

    def delete_images(self, force=False):
        """
        Delete all images of the exercise. This function can also be called if
        no images have been build so far. This will change the build status of
        the exercise, this `exercise` must be committed to the DB.
        Raises:
            inconsistency_on_error: If deletion fails.
        """
        with inconsistency_on_error(f'Failed to delete images of {self.exercise}'):
            #Delete docker images
            ExerciseImageManager.__purge_entry_service_image(self.exercise, force=force)
            ExerciseImageManager.__purge_peripheral_services_images(self.exercise, force=force)
            self.exercise.build_job_status = ExerciseBuildStatus.NOT_BUILD

    def remove(self):
        """
        Deletes all data associated with the exercise. It is safe to
        call this function multiple times on the same exercise.
        After calling this function, the exercise must be removed from
        the database.
        Raises:
            InconsistentStateError: In case some components of the exercise could not be removed.
        """

        log.info(f'Deleting images of {self.exercise} ')

        with inconsistency_on_error(f'Failed to delete all components of exercise {self.exercise}'):
            #Delete docker images
            self.delete_images()

            #Remove template
            if os.path.isdir(self.exercise.template_path):
                shutil.rmtree(self.exercise.template_path)

            #Remove overlay
            if os.path.isdir(self.exercise.persistence_path):
                subprocess.check_call(f'sudo rm -rf {self.exercise.persistence_path}', shell=True)
