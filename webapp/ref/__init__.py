import datetime
import logging
import os
import time
import subprocess
import urllib
from logging import Formatter, StreamHandler
from types import MethodType

from Crypto.PublicKey import RSA, ECC
from flask import Blueprint, Flask, current_app, g, render_template, request, url_for
from flask.logging import default_handler, wsgi_errors_stream
from flask_limiter import Limiter
from flask_sqlalchemy import SQLAlchemy
import sqlalchemy

from pygments import highlight
from pygments.formatters import HtmlFormatter as pygementsHtmlFormatter
from pygments.lexers import guess_lexer

# Check for standalone testing mode FIRST, before importing config.py
# (config.py accesses env vars at module level which would fail in test mode)
from config_test import is_standalone_testing, env_var_to_bool_or_false

# Import appropriate config based on testing mode
# TestConfig doesn't require env vars, while Debug/ReleaseConfig do
if is_standalone_testing():
    from config_test import TestConfig

    _available_configs = {"TestConfig": TestConfig}
else:
    from config import DebugConfig, ReleaseConfig

    _available_configs = {"DebugConfig": DebugConfig, "ReleaseConfig": ReleaseConfig}

from flask_debugtoolbar import DebugToolbarExtension
from flask_failsafe import failsafe as flask_failsafe
from flask_login import LoginManager, current_user
from flask_migrate import Migrate, upgrade
from flask_moment import Moment
from telegram_handler import TelegramHandler


def limiter_key_function():
    forwarded_ip = request.headers.get("X-Tinyproxy", None)
    ret = forwarded_ip or request.remote_addr or "127.0.0.1"
    return ret


db = SQLAlchemy(
    engine_options={"isolation_level": "READ COMMITTED"},
    session_options={"autoflush": False},
)
refbp = Blueprint("ref", __name__)
limiter = Limiter(key_func=limiter_key_function, default_limits=["32 per second"])


def is_running_under_uwsgi():
    """
    Test whether we are currently executed using uwsgi.
    Returns:
        True if we are running under uwsig, else False.
    """
    try:
        # The uwsgi module is only available if uwsgi is used to run this code.
        import uwsgi  # noqa: F401

        return True
    except ImportError:
        pass
    return False


def db_get(self, model, **kwargs):
    return self.session.query(model).filter_by(**kwargs).first()


db.get = MethodType(db_get, db)

from colorama import Fore  # noqa: E402


class ColorFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": Fore.BLUE,
        "INFO": Fore.GREEN,
        "WARNING": Fore.YELLOW,
        "ERROR": Fore.RED,
        "CRITICAL": Fore.MAGENTA,
    }

    def format(self, record):
        log_color = self.COLORS.get(record.levelname, Fore.WHITE)
        log_message = super().format(record)
        return f"{log_color}{log_message}{Fore.RESET}"


class HostnameFilter(logging.Filter):
    hostname = os.environ.get("REAL_HOSTNAME", "Hostname unset")

    def filter(self, record):
        record.hostname = HostnameFilter.hostname
        return True


log_format = "[%(asctime)s][%(process)d][%(hostname)s][%(levelname)s] %(filename)s:%(lineno)d %(funcName)s(): %(message)s"
colored_log_formatter = ColorFormatter(log_format)
bw_log_formatter = Formatter(log_format)


def setup_loggin(app):
    """
    Setup all loggin related functionality.
    """
    from pathlib import Path
    from logging.handlers import RotatingFileHandler

    # Logs to the WSGI servers stderr
    wsgi_handler = StreamHandler(wsgi_errors_stream)
    wsgi_handler.addFilter(HostnameFilter())
    wsgi_handler.setFormatter(colored_log_formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(wsgi_handler)

    # Also log to file for persistence and debugging
    # This is especially useful for tests where container logs may be lost
    log_dir = Path(app.config.get("LOG_DIR", "/data/logs"))
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "app.log"
        file_handler = RotatingFileHandler(
            str(log_file),
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=3,
        )
        file_handler.addFilter(HostnameFilter())
        file_handler.setFormatter(bw_log_formatter)
        file_handler.setLevel(logging.DEBUG)
        root_logger.addHandler(file_handler)
    except Exception as e:
        # Don't fail if we can't create the log file
        print(f"Warning: Could not setup file logging to {log_dir}: {e}")

    # Logger that can be used to debug database queries that are emitted by the ORM.
    # logging.getLogger('alembic').setLevel(logging.DEBUG)
    # logging.getLogger('sqlalchemy.dialects.postgresql').setLevel(logging.DEBUG)
    # logging.getLogger('sqlalchemy.engine').setLevel(logging.DEBUG)

    # if not app.config.get('DISABLE_TELEGRAM'):
    #     root_logger.addHandler(telegram_handler)

    # We do not need the default handler anymore since we have now our own loggers in place.
    app.logger.removeHandler(default_handler)
    app.logger.info("Logging setup finished")


def setup_telegram_logger(app):
    from ref.model import SystemSettingsManager

    with app.app_context():
        token = SystemSettingsManager.TELEGRAM_LOGGER_TOKEN.value
        channel_id = SystemSettingsManager.TELEGRAM_LOGGER_CHANNEL_ID.value
    if token and channel_id:
        try:
            app.logger.info(
                f"Setting up Telegram log handler with {token=:.8}... and {channel_id=:.4}..."
            )
            root_logger = logging.getLogger()
            telegram_token = token
            telegram_handler = TelegramHandler(telegram_token, channel_id)
            telegram_handler.setLevel(logging.ERROR)
            telegram_handler.addFilter(HostnameFilter())
            telegram_handler.setFormatter(bw_log_formatter)
            root_logger.addHandler(telegram_handler)
        except Exception:
            app.logger.error(
                "Failed to setup telegram logger. Running without it. Check your settings in the webinterface!",
                exc_info=True,
            )
        else:
            app.logger.info("Telegram handler installed!")


def setup_db(app: Flask):
    """
    Setup the database.

    Arguments:
        app -- The flask app.
    Returns:
        True if the database contains other tables besides `alembic_version`.
            I.e., the database contains "data".
        False if there is no, or only the `alembic_version` table, which is considered
            as a uninitialized database.
    """
    # compare_type -> emit ALTER TABLE commands if a type of an column changes
    migrate = Migrate(
        db=db, compare_type=True, directory=app.config["SQLALCHEMY_MIGRATE_REPO"]
    )
    db.init_app(app)
    app.db = db
    migrate.init_app(app, db)
    app.migrate = migrate

    with app.app_context():
        # A DB only containing the table alembic_version is consider uninitialized.
        inspection = sqlalchemy.inspect(app.db.engine)
        tabels = set(inspection.get_table_names()) - set(["alembic_version"])
        if len(tabels) == 0:
            return False

    return True


def setup_db_default_data(app: Flask):
    from ref.model import User
    from ref.model.enums import CourseOfStudies, UserAuthorizationGroups

    with app.app_context():
        admin = User.query.filter(User.mat_num == "0").one_or_none()
        admin_password = app.config["ADMIN_PASSWORD"]

    # Create default admin account
    if not admin:
        admin = User()
        admin.first_name = "Morty"
        admin.surname = "Admin"
        admin.nickname = "Admin"
        admin.set_password(admin_password)
        admin.mat_num = "0"
        admin.registered_date = datetime.datetime.utcnow()
        admin.course_of_studies = CourseOfStudies.OTHER
        admin.auth_groups = [UserAuthorizationGroups.ADMIN]

        if os.environ.get("ADMIN_SSH_KEY", None):
            app.logger.info("Creating admin user with provided pubkey")
            try:
                key = RSA.import_key(os.environ["ADMIN_SSH_KEY"].replace('"', ""))
            except ValueError:
                key = ECC.import_key(os.environ["ADMIN_SSH_KEY"].replace('"', ""))
            admin.pub_key = key.export_key(format="OpenSSH")
            if isinstance(admin.pub_key, bytes):
                # The pycryptodome API returns bytes for RSA.export_key
                # and strings for ECC.export_key >.>
                admin.pub_key = admin.pub_key.decode()
            admin.priv_key = None
        else:
            key = RSA.generate(2048)
            admin.pub_key = key.export_key(format="OpenSSH").decode()
            admin.priv_key = key.export_key().decode()

        with app.app_context():
            app.db.session.add(admin)
            app.db.session.commit()


def setup_installation_id(app: Flask):
    """
    Initialize the installation ID and update Docker resource prefix.
    The installation ID is a unique 6-character identifier for this REF instance,
    used to distinguish Docker resources created by different installations.

    If DOCKER_RESSOURCE_PREFIX is set via environment variable, it takes precedence
    over the installation ID. This allows tests to use custom prefixes for isolation.
    """
    from ref.model import SystemSettingsManager
    from ref.model.settings import generate_installation_id

    with app.app_context():
        install_id = SystemSettingsManager.INSTALLATION_ID.value
        if not install_id:
            install_id = generate_installation_id()
            SystemSettingsManager.INSTALLATION_ID.value = install_id
            app.db.session.commit()
            app.logger.info(f"Generated new installation ID: {install_id}")

        # Respect environment override (for tests) or use installation ID
        env_prefix = os.environ.get("DOCKER_RESSOURCE_PREFIX")
        if env_prefix:
            app.config["DOCKER_RESSOURCE_PREFIX"] = env_prefix
            app.logger.info(f"Docker resource prefix from env: {env_prefix}")
        else:
            app.config["DOCKER_RESSOURCE_PREFIX"] = f"ref-{install_id}-"
            app.logger.info(
                f"Docker resource prefix: {app.config['DOCKER_RESSOURCE_PREFIX']}"
            )


def setup_login(app: Flask):
    """
    Setup authentication for the app.

    Arguments:
        app -- An instance of the flask app.

    Returns:
        None
    """
    login = LoginManager(app)
    login.login_view = "ref.login"
    app.login = login

    from ref.model import User

    @app.login.user_loader
    def load_user(id) -> User:
        """
        This function is called every time a user authenticates to
        the app.

        Arguments:
            id {str} -- The content of the signed authentication token
            provided by the user.

        Returns:
            User -- The user that belongs to the provied id, or None.
        """
        try:
            id = id.split(":")
            user_id = id[0]
            user_token = id[1]
            user = User.query.filter(
                User.id == int(user_id), User.login_token == user_token
            ).one_or_none()
            current_app.logger.info(f"Login with id {id}, user={user}")
            return user
        except Exception as e:
            current_app.logger.info(f"Login failed {e}")
        return None


def setup_instances(app: Flask):
    from ref.model import Instance
    from ref.core import InstanceManager

    with app.app_context():
        instances = Instance.query.all()
        for i in instances:
            mgr = InstanceManager(i)
            # raises
            try:
                mgr.mount()
            except Exception:
                pass


def setup_jinja(app: Flask):
    if app.debug:
        app.jinja_env.auto_reload = True

    # Allow jinja statements to be started by a single '#'
    app.jinja_env.line_statement_prefix = "#"
    app.jinja_env.line_comment_prefix = "##"

    # jinja globals
    from ref.model import SystemSettingsManager

    app.jinja_env.globals["settings"] = SystemSettingsManager

    # jinja filters
    # FIXME: CSS that belongs to this is in the html file itself...
    def ansi2html_filter(s):
        import ansi2html

        ret = ansi2html.Ansi2HTMLConverter().convert(s, full=False)
        return ret

    app.jinja_env.filters["quote_plus"] = lambda u: urllib.parse.quote_plus(u)
    app.jinja_env.filters["any"] = any
    app.jinja_env.filters["all"] = all
    app.jinja_env.filters["not"] = lambda e: [not x for x in e]
    app.jinja_env.filters["ansi2html"] = ansi2html_filter

    def syntax_highlight(val):
        try:
            lexer = guess_lexer(val)
            formatter = pygementsHtmlFormatter(linenos=True)
            result = highlight(val, lexer, formatter)
        except Exception:
            current_app.logger.warning("Failed to highlight text", exc_info=True)
            result = val
        return result

    app.jinja_env.filters["syntax_highlight"] = syntax_highlight

    # @app.context_processor
    # def inject_next():
    #     return {
    #         'next': request.path
    #     }


def setup_momentjs(app: Flask):
    Moment(app)


def check_requirements(app: Flask):
    # Check if the system supports overlay fs
    try:
        subprocess.check_call("cat /proc/filesystems | grep overlay", shell=True)
    except subprocess.CalledProcessError:
        app.logger.error(
            "The systems appares to not support overlay fs!", exc_info=True
        )
        return False
    return True


def get_config(config):
    if config:
        if isinstance(config, type):
            cfg = config()
        else:
            cfg = config
    else:
        if is_standalone_testing():
            cfg = _available_configs["TestConfig"]()
        elif env_var_to_bool_or_false("DEBUG"):
            cfg = _available_configs["DebugConfig"]()
        else:
            cfg = _available_configs["ReleaseConfig"]()
    return cfg


def fix_stuck_exercise_builds(app: Flask):
    """
    Resets any exercises that are stuck in BUILDING status back to NOT_BUILD.
    This can happen if the server was restarted during a build.
    """
    with app.app_context():
        from ref.model import Exercise, ExerciseBuildStatus

        stuck = Exercise.query.filter_by(
            build_job_status=ExerciseBuildStatus.BUILDING
        ).all()
        if stuck:
            for ex in stuck:
                ex.build_job_status = ExerciseBuildStatus.NOT_BUILD
            app.db.session.commit()
            app.logger.warning(
                f"Reset {len(stuck)} exercises from BUILDING to NOT_BUILD on startup."
            )


@flask_failsafe
def create_app(config=None):
    """
    Factory for creating the flask app. This is the entrypoint to our webapplication.
    """
    app = Flask(__name__)

    cfg = get_config(config)

    app.config.from_object(cfg)
    os.makedirs(app.config["DATADIR"], exist_ok=True)

    # Setup error handlers
    from .error import error_handlers

    for error_handler in error_handlers:
        app.register_error_handler(
            error_handler["code_or_exception"], error_handler["func"]
        )

    from ref.core import DockerClient
    import ref.model  # noqa: F401
    import ref.view  # noqa: F401

    setup_loggin(app)

    if not setup_db(app):
        if is_running_under_uwsgi():
            with app.app_context():
                current_app.logger.info("Database is empty, running migrations...")
                upgrade(directory=app.config["SQLALCHEMY_MIGRATE_REPO"])
                current_app.logger.info("Database migrations completed.")
        else:
            # If we are not running under uwsgi, we assume that someone tries to execute a shell cmd
            # e.g., db upgrade. Hence, we return the app before setting-up the database.
            return app

    if os.environ.get("DB_MIGRATE"):
        # We are currently migrating, do not touch the DB (below) and directly
        # return the app, thus the migration can happen.
        return app

    with app.app_context():
        if not check_requirements(app):
            exit(1)

    setup_db_default_data(app)
    setup_installation_id(app)

    # Must happen after we have db access, since the credentails are store inthere.
    setup_telegram_logger(app)
    fix_stuck_exercise_builds(app)

    setup_login(app)
    setup_instances(app)
    setup_jinja(app)
    setup_momentjs(app)

    limiter.init_app(app)

    if app.config["DEBUG_TOOLBAR"]:
        DebugToolbarExtension(app)

    # Get name of SSH reverse proxy container and web container
    with app.app_context():
        try:
            app.config["SSH_REVERSE_PROXY_CONTAINER_NAME"] = (
                DockerClient.container_name_by_hostname("ssh-reverse-proxy")
            )
            app.logger.info(
                f"Found SSH reverse proxy container: {app.config['SSH_REVERSE_PROXY_CONTAINER_NAME']}"
            )
        except Exception:
            from ref.core import failsafe

            app.logger.error(
                "Failed to get container name of SSH reverse proxy.", exc_info=True
            )
            failsafe()

        try:
            app.config["WEB_CONTAINER_NAME"] = DockerClient.container_name_by_hostname(
                "web"
            )
            app.logger.info(f"Found web container: {app.config['WEB_CONTAINER_NAME']}")
        except Exception:
            from ref.core import failsafe

            app.logger.error(
                "Failed to get container name of web container.", exc_info=True
            )
            failsafe()

    # Enable/Disable maintenance mode base on the ctrl.sh '--maintenance' argument.
    with app.app_context():
        from ref.model import SystemSettingsManager

        SystemSettingsManager.MAINTENANCE_ENABLED.value = app.config[
            "MAINTENANCE_ENABLED"
        ]
        app.db.session.commit()

    if app.config["DISABLE_RESPONSE_CACHING"]:
        # Instruct our clients to not cache anything if
        # DISABLE_RESPONSE_CACHING is set.
        def disable_response_chaching(response):
            response.headers["Cache-Control"] = (
                "no-cache, no-store, must-revalidate, public, max-age=0"
            )
            response.headers["Expires"] = 0
            response.headers["Pragma"] = "no-cache"
            return response

        app.after_request(disable_response_chaching)

    # Show maintenance page if user is not admin and tries to access any view, except the login view.
    def show_maintenance_path():
        from ref.model import SystemSettingsManager

        if (
            SystemSettingsManager.MAINTENANCE_ENABLED.value
            and not request.path.startswith(url_for("ref.login"))
            and not request.path.startswith("/api")
        ):
            if not current_user.is_authenticated or not current_user.is_admin:
                current_app.logger.info(
                    f"Rendering view maintenance for request path {request.path}"
                )
                return render_template("maintenance.html")

    app.before_request(show_maintenance_path)

    def request_time():
        # current_app.logger.info(f"before_request")
        g.before_request_ts = time.monotonic()
        g.request_time = lambda: int((time.monotonic() - g.before_request_ts) * 1000)

    app.before_request(request_time)

    # Lock database each time a new DB transaction is started (BEGIN...)
    # This is not really optimal, but we do not have to deal with concurrency issues, so what?
    @db.event.listens_for(db.session, "after_begin")
    def after_begin(session, transaction, connection: sqlalchemy.engine.Connection):
        from ref.core.util import lock_db

        # current_app.logger.info(f"Locking database")
        lock_db(connection)

    """
    Invalidate all DB sessions bound to the current engine.
    This step must be execute after forking from the master process,
    thus the same DB session is not shared between multiple worker processes.
    """

    def _dispose_db_pool():
        with app.app_context():
            db.engine.dispose()

    try:
        from uwsgidecorators import postfork

        postfork(_dispose_db_pool)
    except ImportError:
        app.logger.warning(
            "It appearers that you are not running under UWSGI."
            " Take care that the DB sessions are not shared by multiple workers!"
        )

    app.register_blueprint(refbp)

    return app
