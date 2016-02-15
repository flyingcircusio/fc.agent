"""Manage users, home directories and store public SSH keys."""

from __future__ import unicode_literals, print_function
from gocept.net.directory import Directory, exceptions_screened
import gocept.net.configfile
import gocept.net.passwd
import os
import os.path
import shutil
import sys


def sanitize_password(hash=''):
    try:
        if not hash.lower().startswith('{crypt}'):
            return 'x'
        hash = hash[len('{crypt}'):]
        front, algorithm, salt, _ = hash.split('$', 3)
        if front:
            return 'x'
        algorithm = int(algorithm)
        if not algorithm >= 1:
            return 'x'
        return hash
    except (ValueError, AttributeError):
        return 'x'


class UserConfig(object):

    def __init__(self, resource_group, prefix=''):
        self.prefix = prefix  # test support
        self.resource_group = resource_group

        self.etcgrp = gocept.net.passwd.Group(self._map('/etc/group'))
        self.etcpasswd = gocept.net.passwd.Passwd(self._map('/etc/passwd'))
        self.etcshadow = gocept.net.passwd.Shadow(self._map('/etc/shadow'))

        self._load()

    def _load(self):
        directory = Directory()
        with exceptions_screened():
            self.users = directory.list_users(self.resource_group)
            self.permissions = directory.list_permissions()
            self.admins_group = directory.lookup_resourcegroup('admins')
            self.admins_permission = {'description': 'Administrators',
                                      'id': self.admins_group['gid'],
                                      'name': self.admins_group['name']}
            self.rg_info = directory.lookup_resourcegroup(self.resource_group)

    def _map(self, path):
        return self.prefix + path

    def finish(self):
        for db in [self.etcgrp, self.etcpasswd, self.etcshadow]:
            diff = db.diff()
            if diff:
                print('Applying changes for %s:' %
                      db.path.replace(self.prefix, ''), file=sys.stdout)
                print(b''.join(diff), file=sys.stdout)
            db.save()
            db.close()

    def ensure_permission_groups(self):
        """
        Ensure that for every directory permission we have a correct
        local unix group.
        """
        for permission in self.permissions:
            permission_group = self.etcgrp.get(permission['name'], create=True)
            permission_group.gid = str(permission['id'])
        admins_grp = self.etcgrp.get(self.admins_group['name'], create=True)
        admins_grp.gid = str(self.admins_group['gid'])

    def ensure_rg_unix_group(self):
        rg_grp = self.etcgrp.get(self.resource_group, create=True)
        rg_grp.gid = str(self.rg_info['gid'])

    def ensure_users(self):
        for user in self.users:
            self.ensure_user(user)
            self.ensure_homedir(user)
            self.ensure_ssh(user)
            self.ensure_permissions(user)
        # Delete unknown users in directory range.
        known_uids = [
            user['uid']
            for user in self.users]
        for user in self.etcpasswd.records[:]:
            if 1000 <= int(user.uid) <= 64999:
                if user.login_name not in known_uids:
                    self.etcpasswd.records.remove(user)
                    user_shadow = self.etcshadow.get(user.login_name)
                    self.etcshadow.records.remove(user_shadow)
                    self.ensure_permissions_for_user_name(user.login_name, [])

    def ensure_user(self, user):
        # XXX re-implement user deletion based on deletion timestamp
        # a) remove user and permissions immediately
        # b) remove home directory after grace period

        # Step 1: Home directory creation

        # Update passwd and shadow records
        user_pwd = self.etcpasswd.get(user['uid'], create=True)
        if not hasattr(user_pwd, 'uid'):
            # Initial creation: set ID
            user_pwd.uid = str(user['id'])
        elif user_pwd.uid != str(user['id']):
            raise ValueError(
                'Local numeric UID conflict for {}: {} != {}'.format(
                    user['uid'], user['id'], user_pwd.uid))
        user_pwd.uid = str(user['id'])
        user_pwd.gid = str(user['gid'])
        user_pwd.gecos = user['name'].encode('utf-8')
        user_pwd.shell = user['login_shell']
        user_pwd.home = user['home_directory']

        user_shadow = self.etcshadow.get(user_pwd.login_name, create=True)
        user_shadow.password = sanitize_password(user['password'])

    def ensure_homedir(self, user):
        """Manage home directory contents."""
        homedir = self._map(user['home_directory'])
        if os.path.exists(homedir):
            return
        print('Creating home directory {0[home_directory]} for {0[uid]}'.
              format(user), file=sys.stdout)
        shutil.copytree(self._map('/etc/skel'), homedir, symlinks=True)
        for root, dirs, files in os.walk(homedir, followlinks=False):
            os.chown(root, user['id'], user['gid'])
            for file in files:
                os.chown(os.path.join(root, file), user['id'], user['gid'])

    def ensure_ssh(self, user):
        ssh = self._map(os.path.join(user['home_directory'], '.ssh'))
        if not os.path.exists(ssh):
            print('(Re-)creating .ssh directory {}'.
                  format(ssh.replace(self.prefix, '')), file=sys.stdout)
            # Don't rely on skel for creating the .ssh directory
            os.mkdir(ssh)
        os.chmod(ssh, 0o711)
        os.chown(ssh, user['id'], user['gid'])
        authorized_keys = os.path.join(ssh, 'authorized_keys')
        output = gocept.net.configfile.ConfigFile(authorized_keys)
        print("# Managed by localconfig-users: do not edit this file "
              "directly. It will be overwritten!", file=output)
        for key in user['ssh_pubkey']:
            print(key, file=output)
        changed = output.commit()
        if changed:
            os.chown(authorized_keys, user['id'], user['gid'])
            os.chmod(authorized_keys, 0o640)

    def ensure_permissions(self, user):
        granted_permissions = user['permissions'][self.resource_group]
        self.ensure_permissions_for_user_name(user['uid'], granted_permissions)

    def ensure_permissions_for_user_name(self, user_name, granted_permissions):
        for permission in self.permissions + [self.admins_permission]:
            group = self.etcgrp.get(permission['name'])
            members = set(group.members.split(','))
            if (permission['name'] in granted_permissions and
                    user_name not in members):
                members.add(user_name)
            if (permission['name'] not in granted_permissions and
                    user_name in members):
                members.remove(user_name)
            group.members = ''
            group.add_members(*members)

    def apply(self):
        self.ensure_permission_groups()
        self.ensure_rg_unix_group()
        self.ensure_users()
        self.finish()


def main():
    if not sys.argv[1:]:
        print('Usage: %s RESOURCE_GROUP' % sys.argv[0])
        sys.exit(1)
    configuration = UserConfig(sys.argv[1])
    configuration.apply()
