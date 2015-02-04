"""Manage short-lived configuration of the puppet master."""
import gocept.net.configfile
import gocept.net.directory
import logging
import os
import subprocess

logger = logging.getLogger(__name__)


def log_call(*args):
    try:
        subprocess.check_call(*args)
    except Exception:
        logger.exception()


class Puppetmaster(object):
    """puppetmaster config generator."""

    autosign_conf = '/etc/puppet/autosign.conf'

    def __init__(self, location, suffix):
        self.location = location
        self.directory = gocept.net.directory.Directory()
        self.suffix = suffix

    def autosign(self):
        with gocept.net.directory.exceptions_screened():
            nodes = ['{0}.{1}\n'.format(node['name'], self.suffix)
                     for node in self.directory.list_nodes()
                     if node['parameters']['location'] == self.location]
        nodes.sort()
        conffile = gocept.net.configfile.ConfigFile(self.autosign_conf)
        conffile.write(''.join(nodes))
        conffile.commit()

    def delete_nodes(self):
        with gocept.net.directory.exceptions_screened():
            deletions = self.directory.deletions('vm')
        for name, node in deletions.items():
            if 'soft' in node['stages']:
                log_call(['puppet', 'node', 'deactivate', name])
            if 'hard' in node['stages']:
                log_call(['puppet', 'node', 'clean', name])


def main():
    """.conf generator main script."""
    master = Puppetmaster(os.environ['PUPPET_LOCATION'], os.environ['SUFFIX'])
    master.autosign()
    master.delete_nodes()
