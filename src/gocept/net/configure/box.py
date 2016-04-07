from __future__ import print_function
from gocept.net.utils import print
from gocept.net.configfile import ConfigFile
from gocept.net.directory import Directory, exceptions_screened
import os
import os.path as p
import subprocess


class Exports(object):

    base = '/srv/nfs/box'

    def __init__(self):
        self.d = Directory()

    def __call__(self):
        with exceptions_screened():
            self.users = self.d.list_users()
        self.users = [u for u in self.users if u['class'] == 'human']
        self.create_boxes()

    def create_boxes(self):
        for u in self.users:
            box = p.join(self.base, u['uid'])
            if not p.exists(box):
                print("Creating {}".format(box))
                os.mkdir(box)
            os.chown(box, u['id'], u['gid'])
            os.chmod(box, 0o755)


class Mounts(object):

    def __init__(self, box_server, resource_group):
        self.box_server = box_server
        self.resource_group = resource_group
        self.d = Directory()

    def __call__(self):
        if not self.box_server:
            print('No box server. Not configuring.')
            return
        with exceptions_screened():
            self.users = self.d.list_users(os.environ.get('RESOURCE_GROUP'))
        self.users = [u for u in self.users if u['class'] == 'human']
        self.users.sort(key=lambda u: u['uid'])

        self.ensure_symlinks()
        changed = self.ensure_automap()
        if changed:
            subprocess.check_call(['/etc/init.d/autofs', 'restart'])

    def ensure_symlink(self, user, box):
        target = p.join('/mnt/autofs/box', user['uid'])
        if p.islink(box) and os.readlink(box) == target:
            return
        if p.ismount(box):
            print('Box {} is still mounted, unmounting'.format(box))
            subprocess.check_call(['umount', box])
        if p.isdir(box):
            os.rmdir(box)
        else:
            try:
                os.unlink(box)
            except Exception:
                pass
        if not p.exists(box):
            print('Symlinking {}'.format(box))
            os.symlink(target, box)

    def ensure_symlinks(self):
        for user in self.users:
            box = p.join(user['home_directory'], 'box')
            self.ensure_symlink(user, box)

    autofs_template = (
        '{uid} -intr,soft,rsize=8192,wsize=8192 {server}:/srv/nfs/box/{uid}\n')

    def ensure_automap(self):
        fstab = ConfigFile('/etc/autofs/auto.box')
        fstab.write('# Managed by localconfig-box-mounts. '
                    'Manual changes will be overwritten.\n')
        for user in self.users:
            fstab.write(self.autofs_template.format(
                server=self.box_server,
                uid=user['uid']))
        return fstab.commit()


def mounts():
    m = Mounts(os.environ.get('BOX_SERVER'), os.environ.get('RESOURCE_GROUP'))
    m()


def exports():
    e = Exports()
    e()
