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
    cert_location = '/var/lib/puppet/ssl-master/ca/signed/{}.pem'

    def __init__(self, location, suffix):
        self.location = location
        self.directory = gocept.net.directory.Directory()
        self.suffix = suffix
        self.nodes = []

    def autosign(self):
        with gocept.net.directory.exceptions_screened():
            self.nodes = ['{0}.{1}'.format(node['name'], self.suffix)
                          for node in self.directory.list_nodes()
                          if node['parameters']['location'] == self.location]
        self.nodes.sort()
        conffile = gocept.net.configfile.ConfigFile(self.autosign_conf)
        conffile.write('\n'.join(self.nodes))
        conffile.write('\n')
        conffile.commit()

    def delete_nodes(self):
        with gocept.net.directory.exceptions_screened():
            deletions = self.directory.deletions('vm')
        for name, node in deletions.items():
            name = '{0}.{1}'.format(name, self.suffix)
            if 'soft' in node['stages']:
                out = log_call(
                    ['puppet', 'node', '--render-as', 'json', 'status', name])
                status = json.loads(out)
                if not status:
                    continue
                status = status[0]
                assert status['name'] == name
                # The dict will not contain the 'deactivated' field when the
                # VM is completely purged. We return 'deleted' as a True
                # marker for this case. Otherwise 'deactivated' contains the
                # date when the node was deactivated, or null if it is active.
                if not status.get('deactivated', 'deleted'):
                    print('Deactivating {}'.format(name))
                    log_call(['puppet', 'node', 'deactivate', name])
            if 'hard' in node['stages']:
                cert = self.cert_location.format(name)
                if os.path.exists(cert):
                    print('Cleaning {}'.format(name))
                    log_call(['puppet', 'node', 'clean', name])

    def sign_race_conditions(self):
        # Those VMs were to fast and didn't appear in autosign when we needed
        # them. Sign them manually anyway.
        c = log_call(['puppet', 'ca', 'list', '--pending', '--render-as',
                     'json'])
        requests = json.loads(c)
        for request in requests:
                if request['state'] != 'requested':
                    continue
                if request['name'] not in self.nodes:
                    continue
                log_call(['puppet', 'ca', 'sign', request['name']])


def main():
    """.conf generator main script."""
    master = Puppetmaster(os.environ['PUPPET_LOCATION'], os.environ['SUFFIX'])
    master.autosign()
    master.delete_nodes()
    master.sign_race_conditions()
