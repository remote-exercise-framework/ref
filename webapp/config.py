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

    #Docker image that servers as base for all exercises
    BASE_IMAGE_NAME = 'remote-exercises-framework-exercise-base:latest'

    #NOTE: This name must be adapated if the name of the ssh server is changed
    #or the parent directory of the docker-compose.yml file is renamed.
    SSHSERVER_CONTAINER_NAME = 'remote-exercises-framework_sshserver_1'

    #Network the instances are connected to. The SSH server must be part of this
    #network, thus it can forward incoming connections to a specific instance.
    INSTANCES_NETWORK_NAME = os.environ.get('INSTANCES_NETWORK_NAME') or 'ref-instances'

class DebugConfig(ReleaseConfig):
    debug = True
    SECRET_KEY = b'123'