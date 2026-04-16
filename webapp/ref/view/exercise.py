import json
import subprocess
import urllib
from collections import defaultdict
from pathlib import Path

from flask import abort, current_app, redirect, render_template, request, url_for
from wtforms import (
    BooleanField,
    Form,
    IntegerField,
    StringField,
    SubmitField,
    TextAreaField,
    validators,
)

from ref import db, refbp
from ref.core import (
    ExerciseConfigError,
    ExerciseImageManager,
    ExerciseManager,
    admin_required,
    extract_task_names_from_submission_tests,
    flash,
    InstanceManager,
    validate_scoring_policy,
)
from ref.core.logging import get_logger
from ref.core.security import sanitize_path_is_subdir
from ref.core.util import datetime_transmute_into_local, redirect_to_next
from ref.model import Exercise, ExerciseConfig
from ref.model.enums import ExerciseBuildStatus

from ref.core import InconsistentStateError

log = get_logger(__name__)


class ExerciseConfigForm(Form):
    short_name = StringField("Short Name", validators=[validators.DataRequired()])
    category = StringField("Category", validators=[validators.DataRequired()])
    submission_deadline_start = StringField("Deadline Start")
    submission_deadline_end = StringField("Deadline End")
    submission_test_enabled = BooleanField("Submission Tests Enabled")
    max_grading_points = IntegerField(
        "Max Grading Points", validators=[validators.Optional()]
    )
    per_task_scoring_policies_json = TextAreaField(
        "Per-task scoring policies", validators=[validators.Optional()]
    )

    submit = SubmitField("Save")


def _discover_tasks_for_config(config: ExerciseConfig) -> list[str]:
    """Return the task names declared in the current default version's
    submission_tests file, or [] when the file is missing or unparseable.

    ExerciseConfig is shared across all versions of an exercise, so
    discovery targets the version currently marked as default.
    """
    exercise = Exercise.query.filter(
        Exercise.short_name == config.short_name,
        Exercise.is_default.is_(True),
    ).one_or_none()
    if exercise is None or not exercise.template_path:
        return []
    return extract_task_names_from_submission_tests(
        Path(exercise.template_path) / "submission_tests"
    )


def _per_task_policies_from_form(
    form: "ExerciseConfigForm",
    discovered_tasks: list[str],
) -> tuple[dict[str, dict] | None, list[str]]:
    """Parse and validate the per-task policies JSON blob.

    Returns `(policies_dict | None, errors)`. An empty blob yields
    `(None, [])` — the column is set to NULL and every task scores as
    pass-through. Each policy is validated with `validate_scoring_policy`;
    entries for tasks not in `discovered_tasks` are rejected as a safety
    check against stale rows when a task was renamed or removed.
    """
    raw = (form.per_task_scoring_policies_json.data or "").strip()
    if not raw:
        return None, []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, [f"per-task policies JSON is invalid: {exc.msg}"]
    if not isinstance(parsed, dict):
        return None, ["per-task policies must be a JSON object keyed by task name."]

    errors: list[str] = []
    discovered_set = set(discovered_tasks)
    cleaned: dict[str, dict] = {}
    for task_name, policy in parsed.items():
        if not isinstance(task_name, str):
            errors.append(f"task name {task_name!r} must be a string.")
            continue
        if discovered_set and task_name not in discovered_set:
            errors.append(
                f"unknown task {task_name!r} — not present in submission_tests."
            )
            continue
        if policy is None or policy == {}:
            # Empty policy means "pass through" — don't store it.
            continue
        if not isinstance(policy, dict):
            errors.append(f"policy for task {task_name!r} must be an object.")
            continue
        policy_errors = validate_scoring_policy(policy)
        if policy_errors:
            for err in policy_errors:
                errors.append(f"task {task_name!r}: {err}")
            continue
        cleaned[task_name] = policy

    if errors:
        return None, errors
    return (cleaned or None), []


@refbp.route("/admin/exercise/build/<int:exercise_id>")
@admin_required
def exercise_build(exercise_id):
    """
    Request to build exercise with ID exercise_id.
    """
    exercise: Exercise = db.get(Exercise, id=exercise_id)
    if not exercise:
        log.info(f"Unknown exercise ID {exercise_id}")
        flash.warning(f"Unknown exercise ID {exercise_id}")
        abort(400)

    if exercise.build_job_status in [
        ExerciseBuildStatus.BUILDING,
        ExerciseBuildStatus.FINISHED,
    ]:
        log.warning(
            f"Unable to start build for exercise {exercise} in state {exercise.build_job_status}"
        )
        flash.error("Already build!")
        abort(400)

    mgr = ExerciseImageManager(exercise)
    if mgr.is_build():
        log.info(f"Build for already build exercise {exercise} was requested.")
        flash.success("Container already build")
        return redirect_to_next()
    else:
        # Start new build. build() handles setting BUILDING status,
        # deleting old images, and committing before spawning the thread.
        current_app.logger.info(f"Starting build for exercise {exercise}.")
        flash.info("Build started...")
        mgr.build()
        return redirect_to_next()


@refbp.route("/admin/exercise/diff")
@admin_required
def exercise_diff():
    """
    Returns a modal that shows a diff of the exercise configs provided
    via query args path_a, path_b. If path_b is not set, the path_a config
    is compared with the most recent version of the same exercise.
    """
    path_a = request.args.get("path_a")
    path_b = request.args.get("path_b")

    if not path_a:
        flash.error("path_a is required")
        abort(400)

    exercises_path = current_app.config["EXERCISES_PATH"]
    if not sanitize_path_is_subdir(exercises_path, path_a):
        flash.error("path_a is invalid")
        log.info(f"Failed to sanitize path {path_a}")
        abort(400)

    exercise_a = ExerciseManager.from_template(path_a)
    exercise_b = None

    # If path_b is not provided, we compare exercise path_a with the most recent version
    # of the same exercise.
    if not path_b:
        # We can trust the paths retrived from DB
        exercise_b = exercise_a.predecessor()
    else:
        if not sanitize_path_is_subdir(exercises_path, path_b):
            flash.error("path_b is invalid")
            log.info(f"Failed to sanitize path {path_b}")
            abort(400)

    if not exercise_b:
        log.info("Unable find any exercise to compare with")
        flash.error("Nothing to compare with")
        abort(400)

    log.info(f"Comparing {exercise_a} with{exercise_b}")

    # template_path is only set if the exercise was already imported
    if exercise_a.template_path:
        path_a = exercise_a.template_path
    else:
        path_a = exercise_a.template_import_path

    if exercise_b.template_path:
        path_b = exercise_b.template_path
    else:
        path_b = exercise_b.template_import_path

    # Check how many files are there to compare.
    # Safety: Both pathes do not contain any user provided data.
    a_file_cnt = int(
        subprocess.check_output(f'find "{path_a}" -type f | wc -l', shell=True)
    )
    b_file_cnt = int(
        subprocess.check_output(f'find "{path_b}" -type f | wc -l', shell=True)
    )
    if a_file_cnt > 16 or b_file_cnt > 16:
        log.warning(
            f"To many files to diff: a_file_cnt={a_file_cnt}, b_file_cnt={b_file_cnt}"
        )
        flash.error("To many files to diff")
        return render_template("500.html"), 500

    # Dockerfile-entry is generated during build, thus we ignore it
    cmd = f"diff -N -r -u --exclude=Dockerfile-entry -U 5 {path_b} {path_a}"
    log.info(f"Running cmd: {cmd}")
    p = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode == 2:
        log.error(f"Failed to run. {p.stderr.decode()}")
        return render_template("500.html"), 500
    diff = p.stdout.decode()

    title = f"{exercise_a.short_name} - v{exercise_b.version} vs. v{exercise_a.version}"
    return render_template("exercise_config_diff.html", title=title, diff=diff)


@refbp.route("/admin/exercise/import/<string:cfg_path>")
@admin_required
def exercise_do_import(cfg_path):
    def render():
        return redirect_to_next()

    try:
        cfg_path = urllib.parse.unquote_plus(cfg_path)
    except Exception:
        log.info("Import failed: invalid config path encoding")
        flash.error("Invalid config path")
        return render()

    if not sanitize_path_is_subdir(current_app.config["EXERCISES_PATH"], cfg_path):
        log.info(f"Import failed: path not in exercises dir: {cfg_path}")
        flash.error("Invalid cfg path")
        return render()

    log.info(f"Importing {cfg_path}")

    try:
        exercise = ExerciseManager.from_template(cfg_path)
    except ExerciseConfigError as err:
        log.info(f"Import failed: template at {cfg_path} contains errors: {err}")
        flash.error(f"Template at {cfg_path} contains errors: {err}")
        return render()

    if exercise.exists():
        log.info(f"Import failed: exercise version already imported: {cfg_path}")
        flash.warning("The given exercise version was already imported")
        return render()

    # Check if this is really a new version or a new task
    successor = exercise.successor()
    if successor:
        log.info(f"Import failed: older version of existing exercise: {cfg_path}")
        flash.warning("Unable to import older version of already existing exercise")
        return render()

    ExerciseManager.create(exercise)

    # Make sure if the REF DB was reset but the docker images where not purged,
    # that leftovers are deleted on import.
    image_manager = ExerciseImageManager(exercise)
    image_manager.delete_images(force=True)

    # Persist the exercise and its config. For new exercises, the config is
    # new and will be inserted. For reimports, the config already exists in
    # the DB (attached by _from_yaml).
    to_add = [exercise.entry_service, exercise]
    if exercise.config.id is None:
        to_add.append(exercise.config)
    db.session.add_all(to_add)
    db.session.commit()

    return render()


@refbp.route("/admin/exercise/view")
@admin_required
def exercise_view_all():
    # Exercises already added to the DB
    exercises = []
    categories = {}
    # Exercises that might be imported by a user. These Exercise instances are not committed to the DB.
    importable = []

    def render():
        return render_template(
            "exercise_view_all.html",
            exercises=exercises,
            categories=categories,
            importable=importable,
        )

    # Parse all available configs
    import_candidates = []
    for path in Path(current_app.config["EXERCISES_PATH"]).glob("*"):
        if not path.is_dir() or not path.joinpath("settings.yml").exists():
            continue
        try:
            exercise = ExerciseManager.from_template(path)
        except ExerciseConfigError as err:
            path = path.joinpath("settings.yml")
            flash.error(f"Template at {path} contains an error: {err}")
        else:
            import_candidates.append(exercise)

    # Filter import_candidates and put result into importable
    for exercise in import_candidates:
        successors = exercise.successors()
        same_version = exercise.get_exercise(exercise.short_name, exercise.version)

        if successors or same_version:
            # Do not import exercises of same type with version <= the already imported versions.
            continue

        try:
            # Global constraints only need be be valid if we the exercise has a newer version
            # than the currently imported once.
            ExerciseManager.check_global_constraints(exercise)
        except ExerciseConfigError as err:
            flash.error(f"Template at {path} contains an error: {err}")
        else:
            importable.append(exercise)

    # Check whether our DB and the local docker repo are in sync.
    # This basically fixes situations where changes have been made to docker
    # without involvement of REF.
    exercises = Exercise.query.all()
    exercises = sorted(exercises, key=lambda e: e.category)

    for exercise in exercises:
        is_build = ExerciseImageManager(exercise).is_build()
        if exercise.build_job_status != ExerciseBuildStatus.FINISHED and is_build:
            # Already build
            exercise.build_job_status = ExerciseBuildStatus.FINISHED
            db.session.add(exercise)
        elif exercise.build_job_status == ExerciseBuildStatus.FINISHED and not is_build:
            # Image got deleted
            exercise.is_default = False
            exercise.build_job_status = ExerciseBuildStatus.NOT_BUILD
            db.session.add(exercise)

    db.session.commit()

    categories = defaultdict(lambda: defaultdict(list))
    for e in sorted(exercises, key=lambda e: (e.category, e.short_name, e.version)):
        categories[e.category][e.short_name] += [e]

    return render()


@refbp.route("/admin/exercise/<int:exercise_id>/delete")
@admin_required
def exercise_delete(exercise_id):
    exercise = Exercise.query.filter(Exercise.id == exercise_id).first()
    if not exercise:
        # Exercise already deleted. This can happen when a concurrent request was blocked
        # on the global DB advisory lock while the first request performed slow Docker
        # operations (container/image removal) and then deleted the exercise.
        return redirect_to_next()

    # TODO: The slow Docker operations (instance removal, image deletion) hold the global
    # DB lock for the entire duration, blocking all other requests. Moving them to a
    # background thread would help, but introduces challenges keeping DB and Docker state
    # in sync.

    instances = exercise.instances
    if instances:
        if all([i.user.is_admin for i in instances]):
            for i in instances:
                mgr = InstanceManager(i)
                mgr.remove()
                # FIXME: What happens if we fails after n-1 instances?
        else:
            flash.error(
                "Exercise has associated instances or submissions owned by non admin users, unable to delete!"
            )
            return redirect_to_next()

    if exercise.build_job_status == ExerciseBuildStatus.BUILDING:
        flash.error("Unable to delete exercise during building")
        return redirect_to_next()

    mgr = ExerciseImageManager(exercise)

    try:
        mgr.remove()
    except InconsistentStateError:
        raise

    for service in exercise.services:
        db.session.delete(service)

    # FIXME: Move this DB related stuff into the core!
    db.session.delete(exercise.entry_service)
    db.session.delete(exercise)
    db.session.commit()

    return redirect_to_next()


@refbp.route("/admin/exercise/default/toggle/<int:exercise_id>")
@admin_required
def exercise_toggle_default(exercise_id):
    exercise = Exercise.query.filter(Exercise.id == exercise_id).one_or_none()
    if not exercise:
        log.info(f"Tried to toggle unknown exercise id={exercise_id}")
        flash.error(f"Unknown exercises id={exercise_id}")
        abort(400)
    if exercise.build_job_status != ExerciseBuildStatus.FINISHED:
        log.info(f"Tried to toggle default for exercise {exercise} that is not build")
        flash.error("Unable to mark exercise that was not build as default")
        abort(400)

    exercises_same_version = Exercise.get_exercises(exercise.short_name)
    exercises_same_version.remove(exercise)

    # Make sure there are not multiple default exercises of the same version
    for e in exercises_same_version:
        e.is_default = False

    # Toggle the state
    exercise.is_default = not exercise.is_default

    db.session.add(exercise)
    db.session.commit()

    return redirect_to_next()


@refbp.route("/admin/exercise/view/<int:exercise_id>")
@admin_required
def exercise_view(exercise_id):
    exercise = Exercise.query.filter(Exercise.id == exercise_id).one_or_none()
    if not exercise:
        flash.error(f"Unknown exercise ID {exercise_id}")
        abort(400)

    return render_template("exercise_view_single.html", exercise=exercise)


@refbp.route("/admin/exercise/<int:exercise_id>/browse", methods=["GET"])
@admin_required
def exercise_browse(exercise_id):
    exercise: Exercise = Exercise.query.filter(Exercise.id == exercise_id).one_or_none()
    if exercise is None:
        abort(400)

    return render_template("exercise_file_browser.html", exercise=exercise)


@refbp.route("/admin/exercise/config/<string:short_name>/edit", methods=("GET", "POST"))
@admin_required
def exercise_edit_config(short_name):
    """
    Edit the shared administrative configuration for an exercise.
    """
    import datetime as dt

    config = ExerciseConfig.query.filter(
        ExerciseConfig.short_name == short_name
    ).one_or_none()
    if not config:
        flash.error(f"No configuration found for exercise '{short_name}'")
        return redirect_to_next()

    form = ExerciseConfigForm(request.form)
    discovered_tasks = _discover_tasks_for_config(config)

    def render():
        return render_template(
            "exercise_config_edit.html",
            form=form,
            short_name=short_name,
            discovered_tasks=discovered_tasks,
        )

    if request.method == "GET":
        form.short_name.data = config.short_name
        form.category.data = config.category
        form.submission_deadline_start.data = (
            config.submission_deadline_start.strftime("%Y-%m-%dT%H:%M")
            if config.submission_deadline_start
            else ""
        )
        form.submission_deadline_end.data = (
            config.submission_deadline_end.strftime("%Y-%m-%dT%H:%M")
            if config.submission_deadline_end
            else ""
        )
        form.submission_test_enabled.data = config.submission_test_enabled
        form.max_grading_points.data = config.max_grading_points
        form.per_task_scoring_policies_json.data = json.dumps(
            config.per_task_scoring_policies or {}, indent=2
        )

    if request.method == "POST" and form.validate():
        import re

        new_short_name = form.short_name.data.strip()
        short_name_regex = r"([a-zA-Z0-9._])*"
        if not re.fullmatch(short_name_regex, new_short_name):
            flash.error(
                f'Invalid short name "{new_short_name}" (must match {short_name_regex})'
            )
            return render()

        # Handle rename
        if new_short_name != config.short_name:
            existing = ExerciseConfig.query.filter(
                ExerciseConfig.short_name == new_short_name
            ).one_or_none()
            if existing:
                flash.error(f'Short name "{new_short_name}" is already in use.')
                return render()

            # Update all Exercise rows that share this short_name
            exercises = Exercise.query.filter(
                Exercise.short_name == config.short_name
            ).all()
            for ex in exercises:
                ex.short_name = new_short_name
                db.session.add(ex)

            config.short_name = new_short_name

        config.category = form.category.data

        # Parse deadline fields
        deadline_start = None
        deadline_end = None
        start_str = form.submission_deadline_start.data.strip()
        end_str = form.submission_deadline_end.data.strip()

        if start_str and end_str:
            try:
                deadline_start = datetime_transmute_into_local(
                    dt.datetime.strptime(start_str, "%Y-%m-%dT%H:%M")
                )
                deadline_end = datetime_transmute_into_local(
                    dt.datetime.strptime(end_str, "%Y-%m-%dT%H:%M")
                )
            except ValueError:
                flash.error("Invalid date format.")
                return render()

            if deadline_start >= deadline_end:
                flash.error("Deadline start must be before deadline end.")
                return render()
        elif start_str or end_str:
            flash.error("Either set both deadline start and end, or leave both empty.")
            return render()

        config.submission_deadline_start = deadline_start
        config.submission_deadline_end = deadline_end
        config.submission_test_enabled = form.submission_test_enabled.data
        config.max_grading_points = form.max_grading_points.data

        per_task_policies, scoring_errors = _per_task_policies_from_form(
            form, discovered_tasks
        )
        if scoring_errors:
            for err in scoring_errors:
                flash.error(err)
            return render()
        config.per_task_scoring_policies = per_task_policies

        # Validate consistency
        has_deadline = config.submission_deadline_end is not None
        has_points = config.max_grading_points is not None
        if has_deadline != has_points:
            flash.error(
                "Either set both deadline and grading points, or leave both empty."
            )
            return render()

        db.session.add(config)
        db.session.commit()
        flash.success(f"Configuration for '{config.short_name}' updated.")
        return redirect(url_for("ref.exercise_view_all"))

    return render()


@refbp.route("/admin", methods=("GET", "POST"))
@admin_required
def admin_default_routes():
    """
    List all students currently registered.
    """
    return redirect(url_for("ref.exercise_view_all"))
