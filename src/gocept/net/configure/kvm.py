import glob
import gocept.net.directory
import logging
import os
import os.path
import subprocess
import sys


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


def delete_configs():

    directory = gocept.net.directory.Directory()

    with gocept.net.directory.exceptions_screened():
            deletions = directory.deletions('vm')

    for name, node in deletions.items():
        if 'hard' in node['stages']:
            cfg = VM.configfile.format(root=VM.root, name=name)
            if os.path.exists(cfg):
                os.unlink(cfg)


def ensure_vms():
    exit_code = 0

    # Allow VMs to be restarted after a crash even if the directory
    # is not around ATM.
    for vm in glob.glob('/etc/qemu/vm/*.cfg'):
        try:
            call('fc-qemu', 'ensure', vm)
        except Exception:
            exit_code = 1

    # Normally VMs should have been shut down already when we delete the config
    # but doing this last also gives a chance this still happening right
    # before.
    delete_configs()

    sys.exit(exit_code)
