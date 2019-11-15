class CommonDbOpsMixin():

    @classmethod
    def get(cls, id_):
        return cls.query.get(id_)

    @classmethod
    def all(cls):
        return cls.query.all()

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