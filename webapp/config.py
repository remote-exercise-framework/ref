import os
BASEDIR = os.environ.get('BASEDIR') or '/tmp/basedir'

class ReleaseConfig(object):
    BASEDIR = BASEDIR
    DATADIR = os.path.join(BASEDIR, 'data')
    DBDIR = os.path.join(DATADIR, 'db')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(DBDIR, 'app.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    REDIS_URL = os.environ.get('REDIS_URL') or 'redis://'
    EXERCISES_PATH = '/exercises'
    IMPORTED_EXERCISES_PATH = os.path.join(DATADIR, 'imported_exercises')
    PERSISTANCE_PATH =  os.path.join(DATADIR, 'persistance')
    SQLALCHEMY_MIGRATE_REPO = 'migrations' #os.path.join(BASEDIR, 'migrations')
    IMAGE_BUILD_TIMEOUT = 120
    LOGIN_DISABLED = False

    #Docker image that servers as base for all exercises
    BASE_IMAGE_NAME = 'remote-exercises-framework-exercise-base:latest'

    #NOTE: This name must be adapated if the name of the ssh server is changed
    #or the parent directory of the docker-compose.yml file is renamed.
    SSHSERVER_CONTAINER_NAME = 'remote-exercises-framework_sshserver_1'

    #Network the instances are connected to. The SSH server must be part of this
    #network, thus it can forward incoming connections to a specific instance.
    INSTANCES_NETWORK_NAME = os.environ.get('INSTANCES_NETWORK_NAME') or 'ref-instances'
    SECRET_KEY = 'cowhSpWKs26DQA7KloZ5SJmPP2BMdY'

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


class DebugConfig(ReleaseConfig):
    debug = True
    DEBUG_TB_INTERCEPT_REDIRECTS = False
    #LOGIN_DISABLED = False