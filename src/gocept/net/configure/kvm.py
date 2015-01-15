from ..configfile import ConfigFile
import glob
import gocept.net.directory
import logging
import os
import os.path
import subprocess
import sys
import yaml


VERBOSE = os.environ.get('VERBOSE', False)
logger = logging.getLogger(__name__)


def call(*cmd):
    if VERBOSE:
        print('calling {}'.format(cmd))
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)


class VM(object):

    root = ''  # support testing
    configfile = '{root}/etc/qemu/vm/{name}.cfg'

    def __init__(self, enc):
        self.name = enc['name']
        self.enc = enc
        for attr in ['configfile']:
            setattr(self, attr,
                    getattr(self, attr).format(root=self.root, **enc))

    def ensure_config(self):
        self.write_config_file()
        self.migrate_old_files()

    def migrate_old_files(self):
        old_config = ['{}/run/kvm.{}.cfg',
                      '{}/run/kvm.{}.cfg.in',
                      '{}/run/kvm.{}.opt',
                      '{}/run/kvm.{}.opt.in',
                      '{}/etc/runlevels/default/kvm.{}',
                      '{}/etc/conf.d/kvm.{}',
                      '{}/etc/kvm/{}.opt',
                      '{}/etc/kvm/{}.cfg',
                      '{}/etc/init.d/kvm.{}']
        for filename in old_config:
            filename = filename.format(self.root, self.name)
            if not os.path.exists(filename):
                continue
            os.unlink(filename)

        # Migrate PID file if it exists.
        pidfile = '{}/run/kvm.{}.pid'.format(self.root, self.name)
        new_pidfile = '{}/run/qemu.{}.pid'.format(self.root, self.name)
        if os.path.exists(pidfile):
            os.rename(pidfile, new_pidfile)

        # Zap init script and remove it
        init = '{}/etc/init.d/kvm.{}'.format(self.root, self.name)
        if os.path.exists(init):
            call(init, 'zap')
            os.unlink(init)

    def write_config_file(self):
        parent = os.path.dirname(self.configfile)
        if not os.path.exists(parent):
            os.makedirs(parent)
        c = ConfigFile(self.configfile)
        c.write(yaml.dump(self.enc))
        c.commit()


def update_configs():
    directory = gocept.net.directory.Directory()
    location = os.environ['PUPPET_LOCATION']

    with gocept.net.directory.exceptions_screened():
        try:
            vms = directory.list_virtual_machines(location)
        except Exception:
            return 1

    exit_code = 0
    for vm_data in vms:
        vm = VM(vm_data)
        try:
            vm.ensure_config()
        except Exception:
            exit_code = 1
    return exit_code


def ensure_vms():
    exit_code = 0
    try:
        exit_code = update_configs()
    except Exception:
        exit_code = 1

    # Allow VMs to be restarted after a crash even if the directory
    # is not around ATM.
    for vm in glob.glob('/etc/qemu/vm/*.cfg'):
        try:
            call('fc-qemu', 'ensure', vm)
        except Exception:
            exit_code = 1

    sys.exit(exit_code)
