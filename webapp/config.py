import os

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

    #NOTE: This name must be adapated if the name of the ssh server is changed
    #or the parent directory of the docker-compose.yml file is renamed.
    SSHSERVER_CONTAINER_NAME = None # 'remote-exercises-framework_sshserver_1'

    SECRET_KEY = os.environ['SECRET_KEY']
    SSH_TO_WEB_KEY = os.environ['SSH_TO_WEB_KEY']

    #Docker image that servers as base for all exercises
    BASE_IMAGE_NAME = 'remote-exercises-framework-exercise-base:latest'

    #Prefix for container and network names created by REF
    DOCKER_RESSOURCE_PREFIX = 'ref-ressource-'

    EXERCISE_CONTAINER_CPU_PERIOD = 100000

    """
    Number of microseconds a container is allowed to consume from the --cpu-period.
    I.e., a value of 50000 allows a container to use 50% of the CPU time of a single cpu at maximum.
    """
    EXERCISE_CONTAINER_CPU_QUOTA = 50000

    """
    Maximum amount of memory a container is allowed to consume.
    If --memory-swap is unset, the container is allowed to use X*2 swap in adddition
    to the 'real' memory.
    """
    EXERCISE_CONTAINER_MEMORY_LIMIT = '256m'

    #If True, only admin are allowed to use the API
    MAINTENANCE_ENABLED = (os.environ.get('MAINTENANCE_ENABLED') and os.environ.get('MAINTENANCE_ENABLED') == '1') or False


class DebugConfig(ReleaseConfig):
    debug = True
    DEBUG = True
    DEBUG_TB_INTERCEPT_REDIRECTS = False

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