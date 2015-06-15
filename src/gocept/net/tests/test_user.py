import cStringIO
import datetime
import gocept.net.configure.users
import mock
import os
import pytest
import pytz
import shutil
import tempfile
import unittest


sanitize = gocept.net.configure.users.sanitize_password


class TestPasswordSanitization(unittest.TestCase):

    def test_no_crypt(self):
        self.assertEquals('x', sanitize('asdfdsafdsa'))
        self.assertEquals('x', sanitize('{MD5}asdfdsafdsa'))
        self.assertEquals('x', sanitize('{SHA}asdfdsafdsa'))

    def test_crypt_no_algo_no_salt(self):
        self.assertEquals('x', sanitize('{CRYPT}asdfdsafdsa'))

    def test_crypt_no_algo(self):
        self.assertEquals('x', sanitize('{CRYPT}asdf$dsafdsa'))

    def test_crypt_wrong_algo(self):
        self.assertEquals('x', sanitize('{CRYPT}$asdf$dsafdsa'))
        self.assertEquals('x', sanitize('{CRYPT}$0$dsafdsa'))

    def test_crypt_leading_garbage(self):
        self.assertEquals('x', sanitize('{CRYPT}asdf$1$dsa$fdsa'))

    def test_empty(self):
        self.assertEquals('x', sanitize(''))

    def test_none(self):
        self.assertEquals('x', sanitize(None))

    def test_crypt(self):
        self.assertEquals('$1$dsa$fdsa', sanitize('{CRYPT}$1$dsa$fdsa'))


class TestUserConfig(unittest.TestCase):

    def setUp(self):
        gocept.net.configure.users.OUT = cStringIO.StringIO()
        self.p_directory = mock.patch('gocept.net.configure.users.Directory')
        self.fake_directory = self.p_directory.start()
        resource_groups = {'admins': {'gid': 1, 'name': 'admins'},
                           'test': {'gid': 2, 'name': 'test'}}
        self.fake_directory().lookup_resourcegroup = (
            resource_groups.__getitem__)

        self.p_chown = mock.patch('os.chown')
        self.chown = self.p_chown.start()

        self.tmpdir = tempfile.mkdtemp()
        os.mkdir(self.tmpdir + '/etc')
        os.mkdir(self.tmpdir + '/etc/skel')
        open(self.tmpdir + '/etc/skel/foo', 'w').write('foobar')
        os.mkdir(self.tmpdir + '/home')
        open(self.tmpdir + '/etc/group', 'w')
        open(self.tmpdir + '/etc/shadow', 'w')
        open(self.tmpdir + '/etc/passwd', 'w')

    def tearDown(self):
        shutil.rmtree(self.tmpdir)
        self.p_directory.stop()

    @mock.patch('gocept.net.utils.now')
    def test_workflow(self, _now):
        # fix notion of time to get stable "lastchange" value in shadow
        _now.return_value = datetime.datetime(2014, 4, 1, tzinfo=pytz.utc)

        self.fake_directory().list_permissions.return_value = [
            {'name': 'login', 'id': 3}]
        self.fake_directory().list_users.return_value = [
            {'uid': 'bob', 'id': 10, 'gid': 100, 'name': 'Bob the builder',
             'login_shell': '/bin/bash', 'home_directory': '/home/bob',
             'password': '{crypt}$6$fdas$gt798ewa',
             'ssh_pubkey': ['ssh-rsa fdhsaukhfdsa foo@localhost'],
             'permissions': {'test': ['login']}}]

        configuration = gocept.net.configure.users.UserConfig(
            'test', prefix=self.tmpdir)
        configuration.ensure_permission_groups()
        configuration.ensure_rg_unix_group()
        configuration.ensure_users()
        configuration.finish()

        group = open(self.tmpdir + '/etc/group', 'r').read()
        self.assertEqual(group, """\
login:x:3:bob
admins:x:1:
test:x:2:
""")

        passwd = open(self.tmpdir + '/etc/passwd', 'r').read()
        self.assertEqual(passwd, """\
bob:x:10:100:Bob the builder:/home/bob:/bin/bash
""")

        shadow = open(self.tmpdir + '/etc/shadow', 'r').read()
        self.assertEqual(shadow, """\
bob:$6$fdas$gt798ewa:16161:0:99999:7:::
""")

    def test_admin_is_present_in_admins_group(self):
        # fix notion of time to get stable "lastchange" value in shadow
        self.fake_directory().list_permissions.return_value = [
            {'name': 'login', 'id': 3}]
        self.fake_directory().list_users.return_value = [
            {'uid': 'tom', 'id': 11, 'gid': 100, 'name': 'Tom the Admin',
             'login_shell': '/bin/bash', 'home_directory': '/home/tom',
             'password': '{crypt}$6$psSt0ipIJ7oe.', 'ssh_pubkey': [],
             'permissions': {'test': ['login', 'admins']}}]

        configuration = gocept.net.configure.users.UserConfig(
            'test', prefix=self.tmpdir)
        configuration.ensure_permission_groups()
        configuration.ensure_users()
        configuration.finish()

        group = open(self.tmpdir + '/etc/group', 'r').read()
        self.assertEqual(group, """\
login:x:3:tom
admins:x:1:tom
""")

    @mock.patch('gocept.net.utils.now')
    def test_local_users_with_different_uid_not_hijackable(self, _now):
        # fix notion of time to get stable "lastchange" value in shadow
        _now.return_value = datetime.datetime(2014, 4, 1, tzinfo=pytz.utc)

        with open(self.tmpdir + '/etc/passwd', 'w') as f:
            f.write('root:x:0:0:The Root User:/root:/bin/bash')

        self.fake_directory().list_permissions.return_value = [
            {'name': 'login', 'id': 3}]
        self.fake_directory().list_users.return_value = [
            {'uid': 'root', 'id': 10, 'gid': 100, 'name': 'Bob the builder',
             'login_shell': '/bin/bash', 'home_directory': '/home/bob',
             'password': '{crypt}$6$fdas$gt798ewa',
             'ssh_pubkey': ['ssh-rsa fdhsaukhfdsa foo@localhost'],
             'permissions': {'test': ['login']}}]

        configuration = gocept.net.configure.users.UserConfig(
            'test', prefix=self.tmpdir)
        configuration.ensure_permission_groups()
        configuration.ensure_rg_unix_group()
        with pytest.raises(ValueError):
            configuration.ensure_users()
