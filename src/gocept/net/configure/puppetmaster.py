"""Manage short-lived configuration of the puppet master."""
from gocept.net.utils import log_call
import gocept.net.configfile
import gocept.net.directory
import json
import logging
import os


logger = logging.getLogger(__name__)


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
            name = '{0}.{1}'.format(name, self.suffix)
            if 'soft' in node['stages']:
                status = log_call(
                    ['puppet', 'node', '--render-as', 'json', 'status', name])
                status = json.loads(status)[0]
                assert status['name'] == name
                if not status['deactivated']:
                    log_call(['puppet', 'node', 'deactivate', name])
            if 'hard' in node['stages']:
                log_call(['puppet', 'node', 'clean', name])


def main():
    """.conf generator main script."""
    master = Puppetmaster(os.environ['PUPPET_LOCATION'], os.environ['SUFFIX'])
    master.autosign()
    master.delete_nodes()
