from flask import current_app

class CommonDbOpsMixin():

    @classmethod
    def get(cls, id_, lock=False):
        if lock:
            return cls.query.with_for_update().get(id_)
        return cls.query.get(id_)

    @classmethod
    def all(cls, lock=False):
        if lock:
            return cls.query.with_for_update().all()
        return cls.query.all()

    def refresh(self, lock=False):
        return self.__class__.get(self.id, lock=lock)



class ModelToStringMixin():

    def __str__(self):
        to_str_attributes = getattr(self, '__to_str_fields__', None)
        if not to_str_attributes:
            raise RuntimeError('Missing __to_str_fields__ attrbiute!')
        ret = f"<{self.__class__.__name__} "
        for f in to_str_attributes:
            ret += f'{f}={getattr(self, f)}, '
        ret = ret.rstrip(' ,')
        ret += '>'
        return ret