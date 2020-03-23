import time
import uuid

#import uwsgidecorators
from flask import current_app
from redis import Redis
from werkzeug.local import LocalProxy

from ref.model import Exercise

rd: Redis = LocalProxy(lambda: current_app.redis)

class RedisSortedIntKeyDict():

    def __init__(self, redis_key):
        self._set_key = f'{redis_key}-set'
        self._cnt_key = f'{redis_key}-cnt'

    def __setitem__(self, key, value):
        if not isinstance(key, int):
            raise AttributeError(f'type of key is {type(key)}, but int is required')
        cnt = rd.incr(self._cnt_key)
        data = {}
        #We are making the key unique by appending a unique integer
        k = f'{value}:{cnt}'
        #key -> score
        data[k] = key
        rd.zadd(self._key, data,  nx=True)

    def __getitem__single(self, key):
        if not isinstance(key, int):
            raise AttributeError(f'type of key is {type(key)}, but int is required')
        #Returns a list of (value, score) tuples
        pairs = rd.zrangebyscore(self._set_key, key, key, withscores=True)
        pairs = { int(e[1]): int(e[0].decode().split(':')[:-1]) for e in pairs }
        return pairs.get(key, None)

    def __getitem__slice(self, key_slice):
        pass

    def __getitem__(self, key):
        if isinstance(key, slice):
            return self.__getitem__slice(key)
        else:
            return self.__getitem__single(key)

    def __len__(self):
        return rd.zcount(self._set_key, '-inf', '+inf')


class ExerciseMetric():
    REDIS_COUNT_KEY_PREFIX = 'ExerciseMetric-Count-'

    def __init__(self, id_):
        self.id_ = id_
        self.instance_count_key = f'{ExerciseMetric.REDIS_COUNT_KEY_PREFIX}-{self.id_}'

    def update(self):
        redis: Redis = current_app.redis

        #Update instance count
        exercise = Exercise.query.filter(Exercise.id == self.id_).one_or_none()
        if exercise:
            kv = {}
            key = f'{len(exercise.instances)}:{uuid.uuid4()}'
            kv[key] = int(time.time())
            redis.zadd(self.instance_count_key, kv,  nx=True)

    def instance_count(self, start_ts=b'-inf', end_ts=f'+inf'):
        """
        Get the number of instances over time.
        Returns an dict that maps timestamps to the number of instances.
        """
        redis: Redis = current_app.redis
        if start_ts:
            start_ts = float(start_ts)

        if end_ts:
            end_ts = float(end_ts)

        pairs = redis.zrangebyscore(self.instance_count_key, start_ts, end_ts, withscores=True)
        pairs = {int(e[1]): int(e[0].decode().split(':')[0]) for e in pairs}
        return pairs

    def instance_count_running(self, start_ts=b'-inf', end_ts=f'+inf'):
        pass


class SystemMetrics():

    def __init__(self):
        pass

class SystemMetricsUpdateService():
    """
    Service used to update system metrics.
    """

    def __init__(self):
        pass

    def update(self):
        current_app.logger.info('Updating system metric')
        exercises = Exercise.query.all()
        for e in exercises:
            m = ExerciseMetric(e.id)
            m.update()
            current_app.logger.info(m.instance_count())
