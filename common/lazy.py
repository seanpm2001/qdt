__all__ = [
    "lazy"
      , "cached"
  , "reset_cache"
]

# See: https://habr.com/post/122082/

class lazy(object):

    def __init__(self, getter):
        self.getter = getter
        doc = getter.__doc__ or ""

        self.__doc__ = doc + "\nlazy: evaluated on demand."

    def __get__(self, obj, cls):
        getter = self.getter
        val = getter(obj)
        # add evaluated value to `__dict__` of `obj` to prevent consequent call
        # to `__get__` of this descriptor.
        obj.__dict__[getter.__name__] = val
        return val


class cached(lazy):
    """ Variant of `lazy` attribute decorator that saves names of evaluated
lazy attributes to list with name `__lazy__`. An instance with `cached`
attributes must provide such an attribute (by `__init__`, for example).
    """

    def __get__(self, obj, cls):
        getter = self.getter
        val = getter(obj)
        name = getter.__name__
        obj.__dict__[name] = val
        obj.__lazy__.append(name)
        return val

def reset_cache(obj):
    "Resets lazily evaluated `cached` attributes of `obj`."

    l = obj.__lazy__
    d = obj.__dict__
    for name in l:
        del d[name]
    del l[:]
