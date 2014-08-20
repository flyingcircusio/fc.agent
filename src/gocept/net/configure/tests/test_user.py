from __future__ import print_function

from ..users import UserConfig
import gocept.net.utils
import datetime
import os
import pytest


@pytest.fixture
def empty_dbs(tmpdir):
    os.mkdir(str(tmpdir/'etc'))
    os.mkdir(str(tmpdir/'etc/skel'))

    with open(str(tmpdir/'etc/group'), 'wb') as grp:
        grp.write("""\
root::0:root
bin::1:root,bin,daemon
""")
    with open(str(tmpdir/'etc/passwd'), 'wb') as grp:
        grp.write("""\
root:x:0:0:root:/root:/bin/bash
bin:x:1:1:bin:/bin:/bin/false
""")
    with open(str(tmpdir/'etc/shadow'), 'wb') as grp:
        grp.write("""\
root:*:10770:0:::::
halt:*:9797:0:::::
""")

    return tmpdir


def test_create_admin_group(empty_dbs, capsys, monkeypatch, directory):

    def load(self):
        self.users = []
        self.permissions = []
        self.admins_group = {'gid': 2003, 'name': 'admins'}
        self.admins_permission = {}
        self.rg_info = {'gid': 2043}
    monkeypatch.setattr(UserConfig, '_load', load)

    configuration = UserConfig('testrg', prefix=str(empty_dbs))
    configuration.apply()

    out, err = capsys.readouterr()
    assert out == """\
Applying changes for /etc/group:
--- old
+++ new
@@ -1,2 +1,4 @@
 root::0:root
 bin::1:root,bin,daemon
+admins:x:2003:
+testrg:x:2043:

"""
    assert err == ""


def test_create_user_with_unicode_gecos(
        empty_dbs, capsys, monkeypatch, directory):
    users = [{'uid': 'bob',
              'id': 1003,
              'gid': 1000,
              'name': u'B\xc3b',
              'password': 'thehashedpassword',
              'ssh_pubkey': [],
              'permissions': {'testrg': []},
              'login_shell': '/bin/bash',
              'home_directory': '/home/bob'}]

    def load(self):
        self.users = users
        self.permissions = []
        self.admins_group = {'gid': 2003, 'name': 'admins'}
        self.admins_permission = {'name': 'admins'}
        self.rg_info = {'gid': 2043}
    monkeypatch.setattr(UserConfig, '_load', load)

    def chown(file, user, group):
        print('chown', file.replace(str(empty_dbs), ''), user, group)
    monkeypatch.setattr(os, 'chown', chown)

    def now():
        return datetime.datetime(2000, 1, 1, 0, 0)
    monkeypatch.setattr(gocept.net.utils, 'now', now)

    configuration = UserConfig('testrg', prefix=str(empty_dbs))
    configuration.apply()

    out, err = capsys.readouterr()
    # XXX the u'' literal is probably a remainder of the problem
    # that we're implicitly smuggling unicode due to the __future__ imports
    assert out == u"""\
Creating home directory /home/bob for bob
chown /home/bob 1003 1000
(Re-)creating .ssh directory /home/bob/.ssh
chown /home/bob/.ssh 1003 1000
chown /home/bob/.ssh/authorized_keys 1003 1000
Applying changes for /etc/group:
--- old
+++ new
@@ -1,2 +1,4 @@
 root::0:root
 bin::1:root,bin,daemon
+admins:x:2003:
+testrg:x:2043:

Applying changes for /etc/passwd:
--- old
+++ new
@@ -1,2 +1,3 @@
 root:x:0:0:root:/root:/bin/bash
 bin:x:1:1:bin:/bin:/bin/false
+bob:x:1003:1000:B\xc3b:/home/bob:/bin/bash

Applying changes for /etc/shadow:
--- old
+++ new
@@ -1,2 +1,3 @@
 root:*:10770:0:::::
 halt:*:9797:0:::::
+bob:x:10957:0:99999:7:::

"""
    assert err == ""

    users[0]['name'] = 'Bob'
    configuration = UserConfig('testrg', prefix=str(empty_dbs))
    configuration.apply()
    out, err = capsys.readouterr()
    # XXX the u'' literal is probably a remainder of the problem
    # that we're implicitly smuggling unicode due to the __future__ imports
    assert out == u"""\
chown /home/bob/.ssh 1003 1000
Applying changes for /etc/passwd:
--- old
+++ new
@@ -1,3 +1,3 @@
 root:x:0:0:root:/root:/bin/bash
 bin:x:1:1:bin:/bin:/bin/false
-bob:x:1003:1000:B\xc3b:/home/bob:/bin/bash
+bob:x:1003:1000:Bob:/home/bob:/bin/bash

"""
    assert err == ""


def test_passwd_db_ok_with_non_newline_last_line(
        tmpdir, capsys, directory, monkeypatch):
    monkeypatch.setattr(UserConfig, '_load', lambda self: None)
    os.mkdir(str(tmpdir/'etc'))
    with open(str(tmpdir/'etc/group'), 'wb') as grp:
        grp.write("""\
root::0:root
testrg:x:2043:alice,bob\
""")
    with open(str(tmpdir/'etc/passwd'), 'wb') as grp:
        grp.write("""\
root:x:0:0:root:/root:/bin/bash
bin:x:1:1:bin:/bin:/bin/false
bob:x:1322:100:Bob the Bobber:/home/bob:/bin/bash
alice:x:1321:100:Alice di Alicante:/home/alice:/bin/bash\
""")
    with open(str(tmpdir/'etc/shadow'), 'wb') as grp:
        grp.write("""\
root:*:10770:0:::::
halt:*:9797:0:::::
bob:fdsajkfbdsa:9797:0:::::
alice:fdsajkfbdsa:9797:0:::::\
""")
    UserConfig('testrg', prefix=str(tmpdir))
