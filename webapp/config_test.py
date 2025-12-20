"""
Test configuration for standalone unit testing outside the container environment.

This module is separate from config.py to avoid triggering environment variable
lookups when imported in test mode.
"""

import os


def env_var_to_bool_or_false(env_key):
    val = os.environ.get(env_key, False)
    if val is False:
        return val
    assert isinstance(val, str)
    return val == "1" or val.lower() == "true"


def is_standalone_testing():
    """Check if we're running in standalone test mode."""
    return env_var_to_bool_or_false("REF_STANDALONE_TESTING")


class Config:
    """
    A configuration that can be loaded via the .from_object() method provided by the Flask
    config object.
    """


class _TestConfigNotAvailable:
    """Descriptor that raises an error when the config value is accessed in test mode."""

    def __init__(self, name: str):
        self.name = name

    def __get__(self, obj, objtype=None):
        raise RuntimeError(
            f"Config value '{self.name}' is not available in standalone test mode. "
            f"This code path requires infrastructure (database, containers, etc.) "
            f"that is not available during unit testing."
        )


class TestConfig(Config):
    """
    Configuration for standalone unit testing outside the container environment.

    Properties that require infrastructure (DB, Docker, etc.) raise RuntimeError
    when accessed, helping identify code paths that won't work in unit tests.

    Enable by setting REF_STANDALONE_TESTING=1 environment variable.
    """

    # Properties that MUST raise errors (require real infrastructure)
    POSTGRES_USER = _TestConfigNotAvailable("POSTGRES_USER")
    POSTGRES_DB = _TestConfigNotAvailable("POSTGRES_DB")
    POSTGRES_PASSWORD = _TestConfigNotAvailable("POSTGRES_PASSWORD")
    SQLALCHEMY_DATABASE_URI = _TestConfigNotAvailable("SQLALCHEMY_DATABASE_URI")
    ADMIN_PASSWORD = _TestConfigNotAvailable("ADMIN_PASSWORD")
    SSH_HOST_PORT = _TestConfigNotAvailable("SSH_HOST_PORT")
    SSHSERVER_CONTAINER_NAME = _TestConfigNotAvailable("SSHSERVER_CONTAINER_NAME")

    # Properties that can be safely mocked
    BASEDIR = "/tmp/ref-test"
    DATADIR = "/tmp/ref-test/data"
    DBDIR = "/tmp/ref-test/data/db"
    LOG_DIR = "/tmp/ref-test/logs"

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    EXERCISES_PATH = "/tmp/ref-test/exercises"
    IMPORTED_EXERCISES_PATH = "/tmp/ref-test/data/imported_exercises"
    PERSISTANCE_PATH = "/tmp/ref-test/data/persistance"
    SQLALCHEMY_MIGRATE_REPO = "migrations"

    LOGIN_DISABLED = True  # Disable login checks in tests

    SECRET_KEY = "test-secret-key-not-for-production"
    SSH_TO_WEB_KEY = "test-ssh-to-web-key-not-for-production"

    # Docker image settings (tests shouldn't actually use Docker)
    BASE_IMAGE_NAME = "test-base-image:latest"
    DOCKER_RESSOURCE_PREFIX = "ref-test-"

    # Container limits (dummy values for tests)
    INSTANCE_CONTAINER_CPUS = 0.5
    INSTANCE_CONTAINER_CPU_SHARES = 1024
    INSTANCE_CONTAINER_MEM_LIMIT = "256m"
    INSTANCE_CONTAINER_MEM_PLUS_SWAP_LIMIT = "256m"
    INSTANCE_CONTAINER_MEM_KERNEL_LIMIT = "256m"
    INSTANCE_CONTAINER_PIDS_LIMIT = 512

    INSTANCE_CAP_WHITELIST = [
        "SYS_CHROOT",
        "SETUID",
        "SETGID",
        "CHOWN",
        "CAP_DAC_OVERRIDE",
        "AUDIT_WRITE",
    ]

    INSTANCES_CGROUP_PARENT = None

    # Feature flags for tests
    MAINTENANCE_ENABLED = False
    DISABLE_TELEGRAM = True
    DEBUG_TOOLBAR = False
    DEBUG_TB_ENABLED = False
    DISABLE_RESPONSE_CACHING = True

    # SSH Proxy settings
    SSH_PROXY_LISTEN_PORT = 18001
    SSH_PROXY_BACKLOG_SIZE = 10
    SSH_PROXY_CONNECTION_TIMEOUT = 30

    # Database lock timeout (lower for tests)
    DB_LOCK_TIMEOUT_SECONDS = 30
    DB_LOCK_SLOW_THRESHOLD_SECONDS = 2

    # Rate limiting disabled for unit tests
    RATELIMIT_ENABLED = False

    # Debug settings
    debug = False
    DEBUG = False
