from ..configfile import ConfigFile
import gocept.net.directory
import logging
import os
import subprocess
import sys
import tempfile
import yaml


VERBOSE = os.environ.get('VERBOSE', False)

# A buffer to receive output from stdout and sterr of subprocesses
out_buf = tempfile.TemporaryFile()

logger = logging.getLogger(__name__)


def call(*cmd):
    out_buf.seek(0)
    out_buf.truncate(0)
    if VERBOSE:
        print('calling {}'.format(cmd))
    try:
        subprocess.check_call(
            cmd, stdout=out_buf, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError, e:
        out_buf.seek(0)
        sys.stdout.write(out_buf.read())
        sys.exit(e.returncode)


class VM(object):

    root = ''  # support testing
    configfile = '{root}/etc/qemu/{name}.yaml'

    def __init__(self, enc):
        self.name = enc['name']
        self.enc = enc
        for attr in ['configfile']:
            setattr(self, attr,
                    getattr(self, attr).format(root=self.root, **enc))

    def ensure(self):
        self.write_config_file()
        self.migrate_old_files()
        call('fc-qemu', 'ensure', self.name)

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
        c = ConfigFile(self.configfile)
        c.write(yaml.dump(self.enc))
        c.commit()


def ensure_vms():
    exitcode = 0
    directory = gocept.net.directory.Directory()
    location = os.environ['PUPPET_LOCATION']

    with gocept.net.directory.exceptions_screened():
        vms = directory.list_virtual_machines(location)

    for vm_data in vms:
        vm = VM(vm_data)
        try:
            vm.ensure()
        except Exception:
            exitcode = 1
    sys.exit(exitcode)
