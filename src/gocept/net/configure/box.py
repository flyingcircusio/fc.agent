from __future__ import print_function
from gocept.net.configfile import ConfigFile
from gocept.net.directory import Directory, exceptions_screened
from gocept.net.utils import print
import os
import os.path
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
        # Boxes are not automatically deleted any longer if a user goes away.
        # The 24h delete cycle will remove the contents anyway but
        # we now avoid to immediately delete all user information just in case
        # that the user is not listed any longer. See #13278

    def create_boxes(self):
        for u in self.users:
            box = os.path.join(self.base, u['uid'])
            if not os.path.exists(box):
                print("Creating {}".format(box))
                os.mkdir(box)
            os.chown(box, u['id'], u['gid'])
            os.chmod(box, 0755)


class Mounts(object):

    mount_template = (
        '{server}:/srv/nfs/box/{uid} {home}/box nfs intr,soft,bg,rsize=8192,wsize=8192 0 0\n')

    def __init__(self):
        self.d = Directory()

    def __call__(self):
        self.box_server = os.environ.get('BOX_SERVER')
        if not self.box_server:
            print('No box server. Not configuring.')
            return
        with exceptions_screened():
            self.users = self.d.list_users(os.environ.get('RESOURCE_GROUP'))
        self.users = [u for u in self.users if u['class'] == 'human']
        self.users.sort(key=lambda u: u['uid'])

        self.ensure_mountpoints()
        self.ensure_fstab()
        self.ensure_mounts()

    def ensure_mountpoints(self):
        for user in self.users:
            box = os.path.join(user['home_directory'], 'box')
            try:
                os.lstat(box)
            except OSError, e:
                if e.errno == 2:
                    print("Creating {}".format(box))
                    os.mkdir(box)
                elif e.errno == 116:
                    print("Broken NFS mount. Suspecting a remount will help.")
                    subprocess.check_call(['umount', box])
            os.chown(box, user['id'], user['gid'])

    def ensure_fstab(self):
        fstab = ConfigFile('/etc/fstab.box')
        fstab.write('# Managed by localconfig-box-mounts. '
                    'Manual changes will be overwritten.\n')
        for user in self.users:
            fstab.write(self.mount_template.format(
                server=self.box_server,
                uid=user['uid'],
                home=user['home_directory']))
        fstab.commit()

    def ensure_mounts(self):
        subprocess.check_call(['mount', '-T', '/etc/fstab.box', '-a'])


def mounts():
    m = Mounts()
    m()


def exports():
    e = Exports()
    e()
