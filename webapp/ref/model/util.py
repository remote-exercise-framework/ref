class CommonDbOpsMixin():

    @classmethod
    def get(cls, id_):
        return cls.query.get(id_)

    @classmethod
    def all(cls):
        return cls.query.all()