"""Generates /etc/backy.conf from directory data."""

import gocept.net.configfile
import gocept.net.directory
import logging
import os
import os.path
import shutil
import socket
import subprocess

logger = logging.getLogger()

CONFIG_TEMPLATE = """\
# Managed by localconfig, don't edit

global:
    base-dir: /srv/backy
    worker-limit: 3

schedules:
    default:
        daily:
            interval: 1d
            keep: 9
        weekly:
            interval: 7d
            keep: 5
        monthly:
            interval: 30d
            keep: 4

    frequent:
        hourly:
            interval: 1h
            keep: 25
        daily:
            interval: 1d
            keep: 9
        weekly:
            interval: 7d
            keep: 5
        monthly:
            interval: 30d
            keep: 4

jobs:
{jobs}
"""

JOB_TEMPLATE = """\
    {name}:
        source:
            type: flyingcircus
            vm: {name}
            consul_acl_token: {consul_acl_token}
        schedule: {schedule}

"""


class BackyConfig(object):

    prefix = ''

    def __init__(self, location, consul_acl_token):
        self.location = location
        self.consul_acl_token = consul_acl_token
        self.changed = False

    def apply(self):
        self.generate_config()
        self.purge()

        if self.changed:
            subprocess.check_call(['/etc/init.d/backy', 'restart'])

    def generate_config(self):
        with gocept.net.directory.exceptions_screened():
            d = gocept.net.directory.Directory()
            vms = d.list_virtual_machines(self.location)

        jobs = []
        for vm in sorted(vms, key=lambda x: x['name']):
            if vm['parameters'].get('backy_server') != socket.gethostname():
                continue
            jobs.append(JOB_TEMPLATE.format(
                name=vm['name'],
                consul_acl_token=self.consul_acl_token,
                schedule=vm['parameters'].get('backy_schedule', 'default')))

        jobs = '\n'.join(jobs)
        output = gocept.net.configfile.ConfigFile(
            self.prefix + '/etc/backy.conf', mode=0o640)
        output.write(CONFIG_TEMPLATE.format(jobs=jobs))
        self.changed = output.commit()

    def purge(self):
        with gocept.net.directory.exceptions_screened():
            d = gocept.net.directory.Directory()
            deletions = d.deletions('vm')
        for name, node in deletions.items():
            if 'hard' not in node['stages']:
                continue
            node_dir = self.prefix + '/srv/backy/{}'.format(name)
            if os.path.exists(node_dir):
                shutil.rmtree(node_dir)


def configure():
    b = BackyConfig(os.environ['PUPPET_LOCATION'],
                    os.environ['CONSUL_ACL_TOKEN'])
    b.apply()
