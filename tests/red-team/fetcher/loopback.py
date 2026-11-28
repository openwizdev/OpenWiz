"""An audit-hook guard for the red-team copies: localhost only, no new programs.

Importing this module installs the guard for the rest of the process, and it
can't be removed. A name lookup, connect, bind or send to anything but
localhost raises PermissionError, and so does starting another program.
"""
import ipaddress
import sys

LOCAL_NAMES = {'localhost', 'localhost.'}
SPAWN = ('subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn', 'os.spawn', 'os.fork', 'os.forkpty', 'pty.spawn')


def is_local(host):
    if isinstance(host, bytes):
        host = host.decode('ascii', 'replace')
    if host is None or not isinstance(host, str):
        return host is None
    if host.lower() in LOCAL_NAMES:
        return True
    try:
        return ipaddress.ip_address(host.split('%', 1)[0]).is_loopback
    except ValueError:
        return False


def _address_is_local(address):
    return isinstance(address, tuple) and len(address) >= 2 and is_local(address[0])


def _guard(event, args):
    if event == 'socket.getaddrinfo' or event == 'socket.gethostbyname' or event == 'socket.gethostbyname_ex':
        if not is_local(args[0]):
            raise PermissionError('red-team copy: no lookup beyond localhost: %r' % (args[0],))
    elif event in ('socket.connect', 'socket.bind', 'socket.sendto', 'socket.sendmsg'):
        address = args[-1] if event != 'socket.sendmsg' else args[1]
        if address is not None and not _address_is_local(address):
            raise PermissionError('red-team copy: no %s beyond localhost: %r' % (event, address))
    elif event.startswith(SPAWN):
        raise PermissionError('red-team copy: no other programs: ' + event)


sys.addaudithook(_guard)
