"""Localconfig VM management.

Most of this code has been migrated to Consul-triggered fc.qemu stuff.
"""

import glob
import gocept.net.directory
import multiprocessing
import os
import os.path
import subprocess
import sys
import time


VERBOSE = os.environ.get('VERBOSE', False)


class VM(object):
    """Minimal VM abstraction to support config cleanup testing."""

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


def delete_configs():
    """Prune VM configs for deleted VMs."""
    directory = gocept.net.directory.Directory()
    with gocept.net.directory.exceptions_screened():
        deletions = directory.deletions('vm')
    for name, node in deletions.items():
        if 'hard' in node['stages']:
            VM(name).unlink()


def ensure_vm(cfg):
    """Check single VM (presumably in separate process)"""
    cmd = ['fc-qemu', 'ensure', cfg]
    if VERBOSE:
        cmd[1:1] = ['-v']
        print('calling: ' + ' '.join(cmd))
    subprocess.check_call(cmd)


def ensure_vms():
    """Scrub VM status periodically"""
    procs = []
    for vm in glob.glob('/etc/qemu/vm/*.cfg'):
        proc = multiprocessing.Process(target=ensure_vm, name=vm, args=(vm,))
        procs.append(proc)
        proc.start()
        time.sleep(0.1)
    for p in procs:
        p.join(3600)
    exitcodes = [p.exitcode for p in procs] or (0,)

    # Normally VMs should have been shut down already when we delete the config
    # but doing this last also gives a chance this still happening right
    # before.
    delete_configs()
    sys.exit(max(exitcodes))
