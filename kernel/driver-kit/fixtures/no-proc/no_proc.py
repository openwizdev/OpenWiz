import builtins, ctypes, io, os, runpy, signal, sys

HERE = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
while args and args[0] in ('-I', '-u', '-B', '-E', '-s'):
    args.pop(0)


def hidden(path):
    try:
        path = os.fsdecode(path)
    except TypeError:
        return False
    return path.rstrip('/') == '/proc' or path.startswith('/proc/')


def gone(path):
    return FileNotFoundError(2, 'No such file or directory', path)


def hide(module, name):
    real = getattr(module, name)

    def fake(path, *a, **k):
        if not isinstance(path, int) and hidden(path):
            raise gone(path)
        return real(path, *a, **k)
    setattr(module, name, fake)


for name in ('open', 'listdir', 'scandir', 'stat', 'lstat'):
    hide(os, name)
hide(io, 'open')
builtins.open = io.open
if hasattr(os, 'pidfd_open'):
    del os.pidfd_open
if hasattr(signal, 'pidfd_send_signal'):
    del signal.pidfd_send_signal


class CDLL(ctypes.CDLL):
    def __getattr__(self, name):
        if name == 'prctl':
            raise AttributeError(name)
        return super().__getattr__(name)


ctypes.CDLL = CDLL
sys.platform = 'darwin'
sys.executable = os.path.join(HERE, 'python3')
if args[:1] == ['-c']:
    sys.argv = ['-c'] + args[2:]
    exec(compile(args[1], '<string>', 'exec'), {'__name__': '__main__'})
else:
    sys.argv = args
    runpy.run_path(args[0], run_name='__main__')
