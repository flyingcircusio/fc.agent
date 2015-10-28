"""Remove old bacula files like stamps and config snippets."""

import argparse
import functools
import gocept.net.directory
import logging
import os
import os.path as p

_log = logging.getLogger()


def expected_nodes():
    """Returns set of nodes which are expected to have local config present."""
    with gocept.net.directory.exceptions_screened():
        d = gocept.net.directory.Directory()
        nodes = d.class_map('backupclient', 'location')
    return set(nodes.keys())


class BaculaState(object):

    STAMPDIR = '/var/lib/bacula/stamps'
    CLIENTDIR = '/etc/bacula/clients'

    def __init__(self, dry_run=False):
        if dry_run:
            self.unlink = functools.partial(
                _log.debug, 'dry_run: would unlink file %s')
        else:
            self.unlink = os.unlink

    def purge_stamps(self, expected):
        for base, dirs, files in os.walk(self.STAMPDIR):
            for fn in files:
                if not fn.startswith('Backup-'):
                    continue
                candidate = fn.split('-', 1)[1]
                fullname = p.join(base, fn)
                if candidate not in expected:
                    _log.info('deleting stale stamp file %s', fullname)
                    self.unlink(fullname)

    def purge_clients(self, expected):
        for fn in os.listdir(self.CLIENTDIR):
            fullname = p.join(self.CLIENTDIR, fn)
            # unconditionally remove old format configs
            if fn.startswith('job.') and fn.endswith('.conf'):
                _log.info('deleting old-format client config %s', fullname)
                self.unlink(fullname)
            elif fn.endswith('.conf'):
                candidate = fn.rsplit('.', 1)[0]
                if candidate not in expected:
                    _log.info('deleting stale client config %s', fullname)
                    self.unlink(fullname)


def purge():
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument('-n', '--dry-run', default=False, action='store_true',
                   help="don't perform actual deletions")
    args = a.parse_args()
    bacula = BaculaState(args.dry_run)
    expected = expected_nodes()
    bacula.purge_stamps(expected)
    bacula.purge_clients(expected)
