import logging
import os
import shutil
import subprocess
import sys
import traceback
from threading import Thread
from typing import List
from pathlib import Path

import docker
from flask import Flask, current_app
from sqlalchemy.orm import joinedload

from ref.core import inconsistency_on_error
from ref.core.logging import get_logger

from .docker import DockerClient
from .exercise import Exercise, ExerciseBuildStatus

log = get_logger(__name__)

# Create a dedicated file logger for build operations that persists even on crash
_build_file_logger: logging.Logger | None = None


def _get_build_logger() -> logging.Logger:
    """Get or create a file logger for build operations.

    This logger writes directly to a file to ensure build logs are captured
    even if the process crashes or the database commit fails.
    """
    global _build_file_logger
    if _build_file_logger is not None:
        return _build_file_logger

    _build_file_logger = logging.getLogger("ref.build")
    _build_file_logger.setLevel(logging.DEBUG)

    # Avoid duplicate handlers
    if not _build_file_logger.handlers:
        # Try to get log directory from Flask app config, fallback to /data/logs
        # Use /data/logs because it's mounted from host and persists after container exit
        log_dir = "/data/logs"
        try:
            from flask import current_app

            if current_app and current_app.config.get("LOG_DIR"):
                log_dir = current_app.config["LOG_DIR"]
        except RuntimeError:
            pass

        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        log_file = log_path / "build.log"
        try:
            handler = logging.FileHandler(str(log_file))
            handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
            )
            handler.setFormatter(formatter)
            _build_file_logger.addHandler(handler)
        except Exception:
            # Fall back to stderr if file logging fails
            handler = logging.StreamHandler(sys.stderr)
            handler.setLevel(logging.DEBUG)
            _build_file_logger.addHandler(handler)

    return _build_file_logger


def _log_build(msg: str, level: int = logging.INFO) -> None:
    """Log a build message to both the standard logger and the build file logger.

    Also prints to stderr with flush to ensure immediate visibility, even if the
    process is killed before completion.
    """
    log.log(level, msg)
    # Print directly to stderr with flush for immediate visibility
    print(msg, file=sys.stderr, flush=True)
    try:
        _get_build_logger().log(level, msg)
    except Exception:
        pass  # Don't let logging failures break the build


class ImageBuildError(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class ExerciseImageManager:
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
        # Check entry service docker image
        image_name = self.exercise.entry_service.image_name
        image = self.dc.image(image_name)
        if not image:
            return False

        for service in self.exercise.services:
            if not self.dc.image(service.image_name):
                return False

        return True

    @staticmethod
    def __build_template(
        app: Flask,
        files: List[str],
        build_cmd: List[str],
        disable_aslr: bool,
        custom_build_cmd: List[str] = [],
        default_cmd: List[str] = ["/usr/sbin/sshd", "-D", "-e"],
    ) -> str:
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
            base = app.config["BASE_IMAGE_NAME"]
        template = f"FROM {base}\n"

        # Copy files into image
        if files:
            for f in files:
                template += f"COPY {f} /home/user/{f}\n"

        # Run custom commands
        if build_cmd:
            for line in build_cmd:
                template += f"RUN {line}\n"

        for c in custom_build_cmd:
            template += f"{c}\n"

        if disable_aslr:
            template += 'CMD ["/usr/bin/setarch", "x86_64", "-R"'
            for w in default_cmd:
                template += f', "{w}"'
        else:
            template += "CMD ["
            for w in default_cmd:
                template += f'"{w}", '
            template = template.rstrip(", ")

        template += "]"

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
    def __docker_build(build_ctx_path: str, tag: str, dockerfile="Dockerfile") -> str:
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
        build_log = ""
        _log_build(
            f"[BUILD] Starting docker build: tag={tag}, "
            f"dockerfile={dockerfile}, context={build_ctx_path}"
        )
        try:
            _log_build("[BUILD] Connecting to Docker daemon...")
            client = docker.from_env()
            images = client.images
            _log_build(
                "[BUILD] Connected. Starting image build (this may take a while)..."
            )
            image, json_log = images.build(
                path=build_ctx_path, tag=tag, dockerfile=dockerfile
            )
            _log_build("[BUILD] Docker build command completed, processing log...")
            json_log = list(json_log)
        except Exception as e:
            _log_build(
                f"[BUILD] Docker build failed with exception: {e}\n"
                f"Traceback:\n{traceback.format_exc()}",
                level=logging.ERROR,
            )
            dc = DockerClient()
            if dc.image(tag):
                dc.rmi(tag)
            raise e
        else:
            for entry in json_log:
                if "stream" in entry:
                    build_log += entry["stream"]
            _log_build(f"[BUILD] Docker build succeeded for {tag}")
            return build_log

    @staticmethod
    def __run_build_entry_service(app, exercise: Exercise) -> str:
        """
        Builds the entry service of an exercise.
        Raises:
            *: If the build process fails.
        """
        dc = DockerClient()

        _log_build(
            f"[BUILD] __run_build_entry_service starting for {exercise.short_name}"
        )

        build_log = " --- Building entry service --- \n"
        image_name = exercise.entry_service.image_name
        _log_build(f"[BUILD] Entry service image name: {image_name}")

        try:
            # Generate cmds to add flag to image
            cmds = ExerciseImageManager.__build_flag_docker_cmd(exercise.entry_service)
            _log_build(f"[BUILD] Flag commands generated: {len(cmds)} commands")

            # Copy submission test suit into image (if any)
            if exercise.submission_test_enabled:
                _log_build("[BUILD] Submission tests enabled, adding to image")
                assert os.path.isfile(f"{exercise.template_path}/submission_tests")
                cmds += [
                    "COPY submission_tests /usr/local/bin/submission_tests",
                    "RUN chown root:root /usr/local/bin/submission_tests && chmod 700 /usr/local/bin/submission_tests",
                ]

            _log_build("[BUILD] Generating Dockerfile template...")
            dockerfile = ExerciseImageManager.__build_template(
                app,
                exercise.entry_service.files,
                exercise.entry_service.build_cmd,
                exercise.entry_service.disable_aslr,
                custom_build_cmd=cmds,
            )

            build_ctx = exercise.template_path
            _log_build(f"[BUILD] Writing Dockerfile-entry to {build_ctx}")
            with open(f"{build_ctx}/Dockerfile-entry", "w") as f:
                f.write(dockerfile)
            _log_build("[BUILD] Dockerfile-entry written, starting docker build...")
            build_log += ExerciseImageManager.__docker_build(
                build_ctx, image_name, dockerfile="Dockerfile-entry"
            )

            _log_build("[BUILD] Entry service docker build completed successfully")

            # Make a copy of the data that needs to be persisted
            if exercise.entry_service.persistance_container_path:
                _log_build(
                    f"[BUILD] Copying persisted data from "
                    f"{exercise.entry_service.persistance_container_path}"
                )
                build_log += dc.copy_from_image(
                    image_name,
                    exercise.entry_service.persistance_container_path,
                    dc.local_path_to_host(exercise.entry_service.persistance_lower),
                )

                _log_build("[BUILD] Handling no_randomize_files...")
                build_log += ExerciseImageManager.handle_no_randomize_files(
                    exercise, dc, build_log, image_name
                )

            _log_build("[BUILD] Entry service build finished successfully")

            return build_log
        except Exception as e:
            _log_build(
                f"[BUILD] Entry service build failed: {e}\n"
                f"Traceback:\n{traceback.format_exc()}",
                level=logging.ERROR,
            )
            # Cleanup on failure
            try:
                if dc.image(image_name):
                    dc.rmi(image_name)
            except Exception:
                pass
            raise

    @staticmethod
    def handle_no_randomize_files(
        exercise: Exercise, dc, build_log: str, image_name: str
    ) -> str:
        build_log = ""
        if not exercise.entry_service.no_randomize_files:
            return build_log

        for entry in exercise.entry_service.no_randomize_files:
            build_log += f"[+] Disabling ASLR for {entry}\n"
            path = Path(exercise.entry_service.persistance_lower) / entry
            if not path.exists():
                dc.rmi(image_name)
                raise ImageBuildError(
                    f'[!] Failed to find file "{entry}" in "{exercise.entry_service.persistance_container_path}. Make sure to use path relative from home."\n'
                )

            cmd = f"sudo setfattr -n security.no_randomize -v true {path}"
            build_log += f"Running {cmd}\n"
            try:
                subprocess.check_call(
                    cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
            except Exception as e:
                dc.rmi(image_name)
                raise Exception(f"Failed to disable ASLR for {entry}") from e
        return build_log

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
        build_log_output: str = ""

        _log_build(
            f"[BUILD] __run_build_peripheral_services starting for {exercise.short_name}"
        )

        try:
            # Note: exercise.services should already be eager-loaded by __run_build_by_id
            # which uses joinedload(Exercise.services). No need to re-query.
            services = list(exercise.services)
            _log_build(f"[BUILD] Found {len(services)} services")

            if not services:
                _log_build("[BUILD] No peripheral services to build")
                return "No peripheral services to build"

            _log_build(f"[BUILD] Building {len(services)} peripheral services")
            for service in services:
                _log_build(f"[BUILD] Building peripheral service: {service.name}")
                build_log_output = (
                    f" --- Building peripheral service {service.name} --- \n"
                )
                image_name = service.image_name

                flag_cmds = ExerciseImageManager.__build_flag_docker_cmd(service)

                dockerfile = ExerciseImageManager.__build_template(
                    app,
                    service.files,
                    service.build_cmd,
                    service.disable_aslr,
                    custom_build_cmd=flag_cmds,
                    default_cmd=service.cmd,
                )
                build_ctx = exercise.template_path
                dockerfile_name = f"Dockerfile-{service.name}"
                _log_build(f"[BUILD] Writing {dockerfile_name} to {build_ctx}")
                with open(f"{build_ctx}/{dockerfile_name}", "w") as f:
                    f.write(dockerfile)
                build_log_output += ExerciseImageManager.__docker_build(
                    build_ctx, image_name, dockerfile=dockerfile_name
                )
                _log_build(f"[BUILD] Peripheral service {service.name} build complete")

            _log_build("[BUILD] All peripheral services built successfully")
            return build_log_output
        except Exception as e:
            _log_build(
                f"[BUILD] Peripheral services build failed: {e}\n"
                f"Traceback:\n{traceback.format_exc()}",
                level=logging.ERROR,
            )
            raise

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
    def __run_build_by_id(app, exercise_id: int):
        """
        Wrapper that loads the exercise fresh inside the thread context
        to avoid SQLAlchemy detached instance issues. The entire build
        runs within the app context to keep the session alive.
        """
        _log_build(f"[BUILD] Build thread started for exercise_id={exercise_id}")
        try:
            with app.app_context():
                _log_build(f"[BUILD] Loading exercise {exercise_id} from database...")
                exercise = Exercise.query.options(
                    joinedload(Exercise.entry_service),
                    joinedload(Exercise.services),
                ).get(exercise_id)
                if exercise is None:
                    _log_build(
                        f"[BUILD] Exercise {exercise_id} not found for build",
                        level=logging.ERROR,
                    )
                    app.logger.error(f"Exercise {exercise_id} not found for build")
                    return
                _log_build(
                    f"[BUILD] Exercise loaded: {exercise.short_name}, "
                    f"template_path={exercise.template_path}"
                )
                # Expunge the exercise and all related objects so they become
                # fully detached Python objects. This prevents any attribute
                # access during the long-running Docker build from triggering
                # a lazy load, which would open a new transaction and hold
                # the database advisory lock for the entire build duration.
                #
                # We also manually wire up back-references since joinedload
                # only populates forward relationships, not reverse ones.
                entry_service = exercise.entry_service
                services = list(exercise.services)
                app.db.session.expunge(exercise)
                if entry_service:
                    app.db.session.expunge(entry_service)
                    entry_service.exercise = exercise
                for svc in services:
                    app.db.session.expunge(svc)
                    svc.exercise = exercise
                app.db.session.commit()
                ExerciseImageManager.__run_build(app, exercise)
            _log_build(f"[BUILD] Build thread finished for exercise_id={exercise_id}")
        except Exception as e:
            _log_build(
                f"[BUILD] FATAL: Build thread crashed for exercise_id={exercise_id}: {e}\n"
                f"Traceback:\n{traceback.format_exc()}",
                level=logging.ERROR,
            )

    @staticmethod
    def __run_build(app, exercise: Exercise):
        """
        Builds all docker images that are needed by the passed exercise.
        Note: This function must be called from within an app_context() - do not
        create nested app contexts here as it causes session/lock issues.
        """
        _log_build(f"[BUILD] Starting __run_build for exercise {exercise.short_name}")
        failed = False
        log_buffer: str = ""
        try:
            # Build entry service
            _log_build("[BUILD] Building entry service...")
            log_buffer += ExerciseImageManager.__run_build_entry_service(app, exercise)
            _log_build(
                "[BUILD] Entry service build complete. Building peripheral services..."
            )
            log_buffer += ExerciseImageManager.__run_build_peripheral_services(
                app, exercise
            )
            _log_build("[BUILD] Peripheral services build complete.")
        except Exception as e:
            _log_build(
                f"[BUILD] Exception caught in __run_build: {type(e).__name__}: {e}",
                level=logging.ERROR,
            )
            if isinstance(e, docker.errors.BuildError):
                for entry in list(e.build_log):
                    if "stream" in entry:
                        log_buffer += entry["stream"]
            elif isinstance(e, docker.errors.ContainerError):
                if e.stderr:
                    log_buffer = e.stderr.decode()
            elif isinstance(e, ImageBuildError):
                log_buffer = f"Error while building image:\n{e}"
            else:
                _log_build(
                    f"[BUILD] Unexpected error during build: {e}\n"
                    f"Traceback:\n{traceback.format_exc()}",
                    level=logging.ERROR,
                )
            log_buffer += traceback.format_exc()
            failed = True

        exercise.build_job_result = log_buffer

        if failed:
            _log_build(
                f"[BUILD] Build FAILED for {exercise.short_name}", level=logging.ERROR
            )
            exercise.build_job_status = ExerciseBuildStatus.FAILED
            try:
                ExerciseImageManager.__purge_entry_service_image(exercise)
                ExerciseImageManager.__purge_peripheral_services_images(exercise)
            except Exception as cleanup_e:
                _log_build(
                    f"[BUILD] Cleanup failed: {cleanup_e}\n"
                    f"Traceback:\n{traceback.format_exc()}",
                    level=logging.ERROR,
                )
        else:
            _log_build(f"[BUILD] Build SUCCEEDED for {exercise.short_name}")
            exercise.build_job_status = ExerciseBuildStatus.FINISHED

        _log_build("[BUILD] Committing build result to DB...")
        exercise = app.db.session.merge(exercise)
        app.db.session.commit()
        _log_build("[BUILD] Build result committed to DB")

    def build(self, wait: bool = False) -> None:
        """
        Builds all images required for the exercise. This process happens in
        a separate thread that updates the exercise after the build process
        finished. After the build process terminated, the exercises build_job_status
        is ether ExerciseBuildStatus.FAILED or ExerciseBuildStatus.FINISHED.

        Args:
            wait: If True, block until the build completes. Useful for testing.
        """
        _log_build(f"[BUILD] build() called for exercise {self.exercise}, wait={wait}")
        self.delete_images()

        # Store the exercise ID to pass to the thread - the thread will
        # reload the exercise with a fresh session to avoid detached
        # instance issues.
        exercise_id = self.exercise.id

        # Set BUILDING status after delete_images (which sets NOT_BUILD),
        # then commit to release the database advisory lock before starting
        # the build thread. The thread needs to acquire this lock to access
        # the database, so we must release it first or the thread will block
        # until the caller's transaction completes.
        from ref import db

        self.exercise.build_job_status = ExerciseBuildStatus.BUILDING
        self.exercise.build_job_result = None
        db.session.commit()

        _log_build(f"[BUILD] Starting build thread for exercise_id={exercise_id}")
        t = Thread(
            target=ExerciseImageManager.__run_build_by_id,
            args=(current_app._get_current_object(), exercise_id),
        )
        t.start()

        if wait:
            _log_build("[BUILD] Waiting for build thread to complete...")
            t.join()
            _log_build("[BUILD] Build thread completed")

    def delete_images(self, force=False):
        """
        Delete all images of the exercise. This function can also be called if
        no images have been build so far. This will change the build status of
        the exercise, this `exercise` must be committed to the DB.
        Raises:
            inconsistency_on_error: If deletion fails.
        """
        with inconsistency_on_error(f"Failed to delete images of {self.exercise}"):
            # Delete docker images
            ExerciseImageManager.__purge_entry_service_image(self.exercise, force=force)
            ExerciseImageManager.__purge_peripheral_services_images(
                self.exercise, force=force
            )
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

        log.info(f"Deleting images of {self.exercise} ")

        with inconsistency_on_error(
            f"Failed to delete all components of exercise {self.exercise}"
        ):
            # Delete docker images
            self.delete_images()

            # Remove template
            if os.path.isdir(self.exercise.template_path):
                shutil.rmtree(self.exercise.template_path)

            # Remove overlay
            if os.path.isdir(self.exercise.persistence_path):
                subprocess.check_call(
                    f"sudo rm -rf {self.exercise.persistence_path}", shell=True
                )
