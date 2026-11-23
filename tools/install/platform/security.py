import os
import stat
import sys


def require(value):
    if not value:
        raise ValueError('refused')


def private(fd, directory):
    meta = os.fstat(fd)
    require(meta.st_uid == os.geteuid() and not meta.st_mode & 0o077)
    require(stat.S_ISDIR(meta.st_mode) if directory else
            stat.S_ISREG(meta.st_mode) and meta.st_nlink == 1 and 0 < meta.st_size <= 16384)


def outside_repository(fd):
    for name in ('.git',):
        try:
            os.stat(name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ValueError('refused')
    try:
        os.stat('HEAD', dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    for name in ('objects', 'config'):
        try:
            os.stat(name, dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ValueError('refused')


def open_key(root):
    require(root.startswith('/') and all(p not in ('', '.', '..') for p in root[1:].split('/')))
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    directory = flags | os.O_DIRECTORY
    fd = os.open('/', directory)
    try:
        for name in root[1:].split('/'):
            outside_repository(fd)
            child = os.open(name, directory, dir_fd=fd)
            os.close(fd)
            fd = child
        outside_repository(fd)
        private(fd, True)
        for name in ('service', 'app'):
            child = os.open(name, directory, dir_fd=fd)
            os.close(fd)
            fd = child
            private(fd, True)
            outside_repository(fd)
        key = os.open('private-key.pem', flags, dir_fd=fd)
        try:
            private(key, False)
        except BaseException:
            os.close(key)
            raise
        return key
    finally:
        os.close(fd)


def main():
    require(len(sys.argv) == 3 and sys.argv[1] in ('inspect', 'sign'))
    key = open_key(sys.argv[2])
    try:
        if sys.argv[1] == 'sign':
            os.set_inheritable(key, True)
            os.execve('/usr/bin/openssl', ['/usr/bin/openssl','dgst','-sha256','-sign',
                                         '/dev/fd/'+str(key)], {})
    finally:
        os.close(key)

if __name__ == '__main__':
    try:
        main()
    except BaseException:
        # SECURITY: credentials, tool output and local paths never become diagnostics.
        sys.exit(1)
