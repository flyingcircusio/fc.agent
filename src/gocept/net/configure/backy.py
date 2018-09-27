"""Generates /etc/backy.conf from directory data."""

import gocept.net.configfile
import gocept.net.directory
import copy
import os
import os.path as p
import shutil
import socket
import logging
import logging.handlers
import subprocess
import syslog
import yaml

_log = logging.getLogger(__name__)
BASEDIR = '/srv/backy'
DEFAULT_CONFIG = {
    'global': {
        'base-dir': BASEDIR,
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
    """Represents a complete backy configuration."""

    prefix = ''
    hostname = socket.gethostname()

    def __init__(self, location, consul_acl_token):
        self.location = location
        self.consul_acl_token = consul_acl_token
        self.changed = False
        self._deletions = None

    def apply(self):
        """Updates configuration file and reloads daemon if necessary."""
        self.generate_config()
        self.purge()
        if self.changed:
            _log.info('config changed, restarting backy')
            subprocess.check_call(['/etc/init.d/backy', 'restart'])

    @property
    def deletions(self):
        """Cached copy of nodes marked in directory for deletion."""
        if not self._deletions:
            with gocept.net.directory.exceptions_screened():
                d = gocept.net.directory.Directory()
                self._deletions = d.deletions('vm')
        return self._deletions

    def job_config(self):
        """Returns data structure for "jobs" config file section.

        Goes over all nodes in the current location and selects those
        that are assigned to the current backup server and are not
        marked for deletion.

        Schedules may have variants which are separated by a hyphen,
        e.g. "default-full".
        """
        with gocept.net.directory.exceptions_screened():
            d = gocept.net.directory.Directory()
            vms = d.list_virtual_machines(self.location)
        jobs = {}
        for vm in vms:
            name = vm['name']
            if vm['parameters'].get('backy_server') != self.hostname:
                continue
            if 'hard' in self.deletions.get(name, {'stages': []})['stages']:
                continue
            schedule = vm['parameters'].get('backy_schedule', 'default')
            variant = None
            if '-' in schedule:
                schedule, variant = schedule.split('-', 1)
            jobs[name] = {
                'source': {
                    'type': 'flyingcircus',
                    'consul_acl_token': self.consul_acl_token,
                    'image': vm['name'] + '.root',
                    'pool': vm['parameters']['rbd_pool'],
                    'vm': name,
                    'full-always': (variant == 'full'),
                },
                'schedule': schedule,
            }
        return jobs

    def generate_config(self):
        """Writes main backy configuration file.

        Returns True if file has been changed.
        """
        global_conf = self.prefix + '/etc/backy.global.conf'
        if p.exists(global_conf):
            with open(global_conf) as f:
                config = yaml.safe_load(f)
        else:
            config = copy.copy(DEFAULT_CONFIG)
        config['jobs'] = self.job_config()
        output = gocept.net.configfile.ConfigFile(
            self.prefix + '/etc/backy.conf', mode=0o640)
        output.write("# Managed by localconfig, don't edit\n\n")
        yaml.safe_dump(config, output)
        self.changed = output.commit()

    def purge(self):
        """Removes job directories for nodes that are marked for deletion."""
        for name, node in self.deletions.items():
            if 'purge' not in node['stages']:
                continue
            node_dir = self.prefix + p.join(BASEDIR, name)
            if p.exists(node_dir):
                _log.info('purging backups for deleted node %s', name)
                shutil.rmtree(node_dir, ignore_errors=True)


def configure():
    h = logging.handlers.SysLogHandler(facility=syslog.LOG_LOCAL4)
    logging.basicConfig(level=logging.DEBUG, handler=h)
    b = BackyConfig(os.environ['PUPPET_LOCATION'],
                    os.environ['CONSUL_ACL_TOKEN'])
    b.apply()
