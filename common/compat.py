__all__ = [
    "execfile"
  , "bstr"
  , "charcodes"
  , "characters"
  , "HelpFormatter"
  , "uname"
  , "RecursionError"
]

from .pypath import (
    pythonpath,
)

from argparse import (
    ArgumentDefaultsHelpFormatter,
    _CountAction,
    _StoreConstAction,
)
from os.path import (
    abspath,
    dirname,
)
from platform import (
    uname as platform_uname,
)
from six import (
    PY2,
    PY3,
)
from six.moves import (
    map,
)


def execfile(filename, _globals = None, _locals = None):
    """ Cross Python wrapper for `exec`. Py2's `execfile` analogue.
Preservers file name for the script (`__file__`), a debugger and an exception
traceback. Executes the script as "__main__".

Notes:
 *  Using same `dict` for globals and locals of `execfile` allows a script to
    use self-defined names (global variables, functions...) inside nested name
    spaces (custom functions, classes, ...) _without_ `global` declaration.
    """

    with open(filename, "rb") as f:
        content = f.read()

    if _globals is None:
        _globals = {}

    _globals["__file__"] = filename
    _globals["__name__"] = "__main__"

    file_path = abspath(dirname(filename))

    code = compile(content, filename, "exec")

    with pythonpath(file_path):
        exec(code, _globals, _locals)


if PY3:
    def bstr(v):
        if isinstance(v, str):
            return v.encode("utf-8")
        elif isinstance(v, bytes):
            return v
        else:
            raise ValueError("Incorrect value type %s" % type(v))

    charcodes = lambda _bstr: iter(_bstr)
    characters = lambda _bstr: map(chr, _bstr)
else:
    def bstr(v):
        if isinstance(v, str):
            return v
        elif isinstance(v, unicode):
            return v.encode("utf-8")
        else:
            raise ValueError("Incorrect value type %s" % type(v))

    charcodes = lambda _bstr: map(ord, _bstr)
    characters = lambda _bstr: iter(_bstr)

bstr.__doc__ = "Given a string-like object, returns it as bytes."
" Unicode strings are encoded in UTF-8."
charcodes.__doc__ = "Given bytes, iterates them as integers."
characters.__doc__ = "Given bytes, iterates them as one character strings."


class HelpFormatter(ArgumentDefaultsHelpFormatter):
    """ Like `ArgumentDefaultsHelpFormatter` but it does not print defaults
for flags.
    """

    def _get_help_string(self, action):
        if isinstance(action, (_CountAction, _StoreConstAction)):
            return action.help
        return super(HelpFormatter, self)._get_help_string(action)


def uname():
    return tuple(platform_uname())

if PY2:
    RecursionError = RuntimeError
else:
    # Under Py3 `RecursionError` is builtin.
    # This assignment adds that name to module as declared by `__all__`.
    RecursionError = RecursionError
