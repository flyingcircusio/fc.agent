"""Generates /etc/backy.conf from directory data."""

import gocept.net.configfile
import gocept.net.directory
import copy
import os
import os.path
import shutil
import socket
import logging
import logging.handlers
import subprocess
import syslog
import yaml

_log = logging.getLogger(__name__)
MAIN_CONFIG = {
    'global': {
        'base-dir': '/srv/backy',
        'worker-limit': 3,
    },
    'schedules': {
        'default': {
            'daily': {
                'interval': '1d',
                'keep': 10,
            },
            'weekly': {
                'interval': '7d',
                'keep': 4,
            },
            'monthly': {
                'interval': '30d',
                'keep': 4,
            }},
        'frequent': {
            'hourly': {
                'interval': '1h',
                'keep': 25,
            },
            'daily': {
                'interval': '1d',
                'keep': 10,
            },
            'weekly': {
                'interval': '7d',
                'keep': 4,
            },
            'monthly': {
                'interval': '30d',
                'keep': 4,
            }}},
}


class BackyConfig(object):

    prefix = ''
    hostname = socket.gethostname()

    def __init__(self, location, consul_acl_token):
        self.location = location
        self.consul_acl_token = consul_acl_token
        self.changed = False

    def apply(self):
        self.generate_config()
        self.purge()
        if self.changed:
            _log.info('config changed, restarting backy')
            subprocess.check_call(['/etc/init.d/backy', 'restart'])

    def job_config(self, vms):
        jobs = {}
        for vm in vms:
            if vm['parameters'].get('backy_server') != self.hostname:
                continue
            jobs[vm['name']] = {
                'source': {
                    'type': 'flyingcircus',
                    'vm': vm['name'],
                    'consul_acl_token': self.consul_acl_token,
                },
                'schedule': vm['parameters'].get('backy_schedule', 'default'),
            }
        return jobs

    def generate_config(self):
        with gocept.net.directory.exceptions_screened():
            d = gocept.net.directory.Directory()
            vms = d.list_virtual_machines(self.location)
        config = copy.copy(MAIN_CONFIG)
        config['jobs'] = self.job_config(vms)
        output = gocept.net.configfile.ConfigFile(
            self.prefix + '/etc/backy.conf', mode=0o640)
        output.write("# Managed by localconfig, don't edit\n")
        yaml.safe_dump(config, output)
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
                _log.info('purging backups for deleted node %s', name)
                shutil.rmtree(node_dir)


def configure():
    h = logging.handlers.SysLogHandler(facility=syslog.LOG_LOCAL4)
    logging.basicConfig(level=logging.DEBUG, handler=h)
    b = BackyConfig(os.environ['PUPPET_LOCATION'],
                    os.environ['CONSUL_ACL_TOKEN'])
    b.apply()
