# Copyright (c) gocept gmbh & co. kg
# See also LICENSE.txt

"""Manage short-lived configuration of the puppet master."""

import gocept.net.directory
import gocept.net.configfile
import os

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


def main():
    """.conf generator main script."""
    master = Puppetmaster(os.environ['PUPPET_LOCATION'], os.environ['SUFFIX'])
    master.autosign()
