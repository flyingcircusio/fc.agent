"""Commonly used utility functions."""

from __future__ import unicode_literals, print_function
import datetime
import fcntl
import logging
import os
import pytz
import subprocess


VERBOSE = os.environ.get('VERBOSE', False)

logger = logging.getLogger(__name__)


def print(*args, **kw):
    if not VERBOSE:
        return
    __builtins__['print'](*args, **kw)


def log_call(*args):
    try:
        return subprocess.check_output(*args)
    except Exception, e:
        logger.exception(e)


# XXX obsolete -- use freezegun instead
def now(tzinfo=pytz.utc):
    return datetime.datetime.now(tzinfo)


class Lock(object):
    """Lockfiles to interlock various parts of the r-u-p machinery.

    The lockfiles created by this class are compatible with
    acquire_lock/release_lock from goceptnet-functions.sh.
    """

    def __init__(self, service):
        self.lockfile = '/run/lock/{}'.format(service)
        self.lockfd = None

    def acquire(self):
        self.lockfd = open(self.lockfile, 'a')
        fcntl.flock(self.lockfd, fcntl.LOCK_EX)
        self.lockfd.seek(0)
        self.lockfd.truncate()
        print(os.getpid(), file=self.lockfd)
        self.lockfd.flush()
        return self

    def release(self):
        if self.lockfd:
            self.lockfd.truncate(0)
            self.lockfd.close()
            self.lockfd = None
