import os

def env_var_to_bool_or_false(env_key):
    val = os.environ.get(env_key, False)
    if val is False:
        return val
    return val == '1' or val == 'True' or val == 'true'

class ReleaseConfig(object):
    BASEDIR = '/data'
    DATADIR = os.path.join(BASEDIR, 'data')
    DBDIR = os.path.join(DATADIR, 'db')

    POSTGRES_USER = os.environ['POSTGRES_USER']
    POSTGRES_DB = os.environ['POSTGRES_DB']
    POSTGRES_PASSWORD = os.environ['POSTGRES_PASSWORD']
    SQLALCHEMY_DATABASE_URI = f'postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}@db/{POSTGRES_DB}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    EXERCISES_PATH = '/exercises'
    IMPORTED_EXERCISES_PATH = os.path.join(DATADIR, 'imported_exercises')
    PERSISTANCE_PATH =  os.path.join(DATADIR, 'persistance')
    SQLALCHEMY_MIGRATE_REPO = 'migrations'

    REDIS_KEY = os.environ['REDIS_KEY']
    REDIS_URL = f"redis://:{REDIS_KEY}@redis"
    IMAGE_BUILD_TIMEOUT = 120
    LOGIN_DISABLED = False

    ADMIN_PASSWORD = os.environ['ADMIN_PASSWORD']

    HOSTNAME = os.environ['HOSTNAME']
    SSH_HOST_PORT = os.environ['SSH_HOST_PORT']

    # The container name of the ssh entry server.
    # NOTE: Filled during initialization.
    SSHSERVER_CONTAINER_NAME = None

    SECRET_KEY = os.environ['SECRET_KEY']
    SSH_TO_WEB_KEY = os.environ['SSH_TO_WEB_KEY']

    #Docker image that servers as base for all exercises
    BASE_IMAGE_NAME = 'remote-exercises-framework-exercise-base:latest'

    #Prefix for container and network names created by REF
    DOCKER_RESSOURCE_PREFIX = 'ref-ressource-'

    # This is a hardlimit and determines howmany CPUs an instance
    # can use.
    INSTANCE_CONTAINER_CPUS = 0.5

    # Relative weight for each instance. In case of contention,
    # this value determines how many cycles are assigned to each container.
    INSTANCE_CONTAINER_CPU_SHARES = 1024

    """
    Maximum amount of memory a container is allowed to consume.
    If --memory-swap is unset, the container is allowed to use X*2 swap in adddition
    to the 'real' memory.
    """
    INSTANCE_CONTAINER_MEM_LIMIT = '256m'

    # Number of PIDs an instance is allowed to allocate.
    INSTANCE_CONTAINER_PIDS_LIMIT = 512

    # The capabilities granted by default to instance containers.
    INSTANCE_CAP_WHITELIST = [
        # Capabilities needed to run the per instance SSH-Server inside the container.
        'SYS_CHROOT',
        'SETUID',
        'SETGID',
        'CHOWN',
        'CAP_DAC_OVERRIDE',
        'AUDIT_WRITE', # sshd audit logging
    ]

    # The parent cgroup for REF. This group has two child groups.
    # One for the core services (i.e., webserver, ssh server, db, ...) and
    # a another one for the instance containers. For now we leave the cgroup
    # settings alone, such that both child groups are guranteed 50% CPU time
    # in case of congestion.
    INSTANCES_CGROUP_PARENT = os.environ.get('INSTANCES_CGROUP_PARENT', None)

    #If True, only admin are allowed to use the API.
    MAINTENANCE_ENABLED = env_var_to_bool_or_false('MAINTENANCE_ENABLED')

    # TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
    # TELEGRAM_BOT_CHAT_ID = os.environ.get('TELEGRAM_BOT_CHAT_ID')

    DISABLE_TELEGRAM = env_var_to_bool_or_false('DISABLE_TELEGRAM')

    DEBUG_TOOLBAR = env_var_to_bool_or_false('DEBUG_TOOLBAR')
    DEBUG_TB_ENABLED = DEBUG_TOOLBAR

    DISABLE_RESPONSE_CACHING = env_var_to_bool_or_false('DISABLE_RESPONSE_CACHING')

    # The port we are listinging on for TCP forwarding requests.
    SSH_PROXY_LISTEN_PORT = 8001

    # Maximum allowed number of pending connection requests
    SSH_PROXY_BACKLOG_SIZE = 100

    SSH_PROXY_CONNECTION_TIMEOUT = 120

class DebugConfig(ReleaseConfig):
    debug = True
    DEBUG = True
    DEBUG_TB_INTERCEPT_REDIRECTS = False
    TEMPLATES_AUTO_RELOAD = True

    #SQLALCHEMY_ECHO = True
    #LOGIN_DISABLED = False

class TestConfig(ReleaseConfig):
    TESTING = True
    DEBUG = True
    DEBUG_TB_INTERCEPT_REDIRECTS = False
    PRESERVE_CONTEXT_ON_EXCEPTION = False
    WTF_CSRF_ENABLED = False
    SERVER_NAME = '127.0.0.1:8000'
    DOCKER_RESSOURCE_PREFIX = 'ref-testing-ressource-'
