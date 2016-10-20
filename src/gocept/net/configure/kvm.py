"""Localconfig VM management.

Most of this code has been migrated to Consul-triggered fc.qemu stuff.
"""

import glob
import gocept.net.directory
import multiprocessing
import os
import os.path
import shutil
import subprocess
import sys
import time


VERBOSE = os.environ.get('VERBOSE', False)


class VM(object):
    """Minimal VM abstraction to support config cleanup testing.

    Calls to fc-qemu are set up in such a way that stdout/stderr goes
    into /var/log/fc-qemu.log
    """

    root = ''  # support testing
    configfile = '{root}/etc/qemu/vm/{name}.cfg'

    def __init__(self, name):
        self.name = name
        self.cfg = self.configfile.format(root=VM.root, name=name)

    def unlink(self):
        """Idempotent config delete action"""
        if os.path.exists(self.cfg):
            if VERBOSE:
                print('cleaning {}'.format(self.cfg))
            os.unlink(self.cfg)

    def ensure(self):
        """Check single VM"""
        cmd = ['fc-qemu', 'ensure', self.name]
        if VERBOSE:
            cmd[1:1] = ['-v']
            print('calling: ' + ' '.join(cmd))
        subprocess.check_call(cmd, close_fds=True)


def delete_configs():
    """Prune VM configs for deleted VMs."""
    directory = gocept.net.directory.Directory()
    with gocept.net.directory.exceptions_screened():
        deletions = directory.deletions('vm')
    for name, node in deletions.items():
        if 'hard' in node['stages']:
            VM(name).unlink()


def ensure_vms():
    """Scrub VM status periodically"""
    procs = []
    for cfg in glob.glob('/etc/qemu/vm/*.cfg'):
        vm = VM(os.path.basename(cfg).rsplit('.', 1)[0])
        proc = multiprocessing.Process(target=vm.ensure, name=vm.name)
        procs.append(proc)
        proc.start()
        time.sleep(0.1)
    for p in procs:
        p.join(4 * 3600)
    exitcodes = [p.exitcode for p in procs] or (0,)

    # Normally VMs should have been shut down already when we delete the config
    # but doing this last also gives a chance this still happening right
    # before.
    delete_configs()
    sys.exit(max(exitcodes))


def ensure_qemu_binary_generation():
    """Manage the "qemu-binary-generation" markers injected by fc.qemu
    into a VM.
    """
    # Update the -booted marker if necessary.
    if os.path.exists('/tmp/fc-data/qemu-binary-generation-booted'):
        shutil.move('/tmp/fc-data/qemu-binary-generation-booted',
                    '/run/qemu-binary-generation-booted')
