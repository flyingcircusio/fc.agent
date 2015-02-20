import os
import re
import socket
import urlparse
import xmlrpclib


def directory_server():
    try:
        return os.environ['DIRECTORY_SERVER']
    except KeyError:
        pass
    for line in open('/etc/local/configure/defaults'):
        if not line.startswith('DIRECTORY_SERVER='):
            continue
        url = line.split('=')[1]
        return url.strip(' \n"')
    raise RuntimeError('cannot find DIRECTORY_SERVER in localconfig defaults')


def Directory():
    user = socket.gethostname()
    password = open('/etc/directory.secret').read().strip()
    url = directory_server()
    parts = urlparse.urlsplit(url)
    if not socket.getdefaulttimeout():
        socket.setdefaulttimeout(300)
    return xmlrpclib.ServerProxy('%s://%s:%s@%s%s' % (
        parts.scheme, user, password, parts.netloc, parts.path))


def exceptions_screened():
    """Run the associated 'with' block but screen raised exceptions."""
    return ExceptionScreener()


class ExceptionScreener(object):
    """Context manager to modify exceptions raised by the associated block.

    When an xmlrpclib exception is raised, the url field in the exception is
    screened for passwords. Passwords are replaced with a non-sensitive value.
    """

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is xmlrpclib.ProtocolError:
            exc_val.url = re.sub(r':(\S+)@', ':PASSWORD@', exc_val.url)
        return False
