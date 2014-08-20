import datetime
import gocept.net.passwd
import mock
import os
import pytz
import shutil
import tempfile
import unittest


class TestPasswd(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.pwd_file = os.path.join(self.directory, 'passwd')
        self.grp_file = os.path.join(self.directory, 'grp')
        open(self.pwd_file, 'w').close()
        open(os.path.join(self.directory, 'passwd2'), 'w').close()
        grp = open(self.grp_file, 'w')
        grp.write("""\
root:x:0:
adm:x:3:ctheune,root,zagy
""")
        grp.close()
        self.grp = gocept.net.passwd.Group(self.grp_file)

    def tearDown(self):
        self.grp.close()
        shutil.rmtree(self.directory)

    def test_lock(self):
        pwd = gocept.net.passwd.Passwd(self.pwd_file)
        self.assertRaises(RuntimeError,
            gocept.net.passwd.Passwd, self.pwd_file)
        pwd2 = gocept.net.passwd.Passwd(
            self.pwd_file + '2')
        pwd.close()
        pwd = gocept.net.passwd.Passwd(self.pwd_file)
        pwd.close()

    def test_parse_passwd_mismatch(self):
        f = open(self.pwd_file, 'w')
        f.write("""\
root:x:0:0:root:/root:/bin/bash:asdf
""")
        f.close()
        self.assertRaises(RuntimeError,
                          gocept.net.passwd.Passwd, self.pwd_file)

    def test_parse_passwd(self):
        f = open(self.pwd_file, 'w')
        f.write("""\
root:x:0:0:root:/root:/bin/bash
daemon:x:1:1:daemon:/usr/sbin:/bin/sh
bin:x:2:2:bin:/bin:/bin/sh
sys:x:3:3:sys:/dev:/bin/sh
""")
        f.close()
        pwd = gocept.net.passwd.Passwd(self.pwd_file)
        self.assertEquals(4, len(pwd.records))
        self.assertEquals('root', pwd.records[0].login_name)
        self.assertEquals('x', pwd.records[0].password)
        self.assertEquals('0', pwd.records[0].uid)
        self.assertEquals('0', pwd.records[0].gid)
        self.assertEquals('root', pwd.records[0].gecos)
        self.assertEquals('/root', pwd.records[0].home)
        self.assertEquals('/bin/bash', pwd.records[0].shell)

    def test_save_passwd(self):
        pwd = gocept.net.passwd.Passwd(self.pwd_file)
        self.assertEquals(0, len(pwd.records))
        entry = gocept.net.passwd.PasswdEntry('root')
        entry.password = 'x'
        entry.uid = '0'
        entry.gid = '0'
        entry.gecos = 'root'
        entry.home = '/root'
        entry.shell = '/bin/bash'
        pwd.records.append(entry)
        pwd.save()
        pwd.close()
        self.assertEquals('root:x:0:0:root:/root:/bin/bash\n',
                          open(self.pwd_file).read())

    def test_parse_group(self):
        f = open(self.pwd_file, 'w')
        f.write("""\
root:x:0:
adm:x:3:ctheune,root,zagy
""")
        f.close()
        pwd = gocept.net.passwd.Group(self.pwd_file)
        self.assertEquals(2, len(pwd.records))
        self.assertEquals('adm', pwd.records[1].group)
        self.assertEquals('x', pwd.records[1].password)
        self.assertEquals('3', pwd.records[1].gid)
        self.assertEquals('ctheune,root,zagy', pwd.records[1].members)

    def test_save_group(self):
        pwd = gocept.net.passwd.Passwd(self.pwd_file)
        self.assertEquals(0, len(pwd.records))
        entry = gocept.net.passwd.PasswdEntry('root')
        entry.password = 'x'
        entry.uid = '0'
        entry.gid = '0'
        entry.gecos = 'root'
        entry.home = '/root'
        entry.shell = '/bin/bash'
        pwd.records.append(entry)
        pwd.save()
        pwd.close()
        self.assertEquals('root:x:0:0:root:/root:/bin/bash\n',
                          open(self.pwd_file).read())

    def test_get_group_by_name(self):
        adm = self.grp.get('adm')
        self.assertEquals('adm', adm.group)
        self.assertEquals('3', adm.gid)
        self.assertRaises(KeyError, self.grp.get, 'asdf')

    def test_group_update_members(self):
        adm = self.grp.get('adm')
        self.assertEquals('ctheune,root,zagy', adm.members)
        adm.add_members('ctheune', 'alf', 'moppi')
        self.assertEquals('alf,ctheune,moppi,root,zagy', adm.members)

    def test_get_passwd_by_login(self):
        open(self.pwd_file, 'w').write('root:x:0:0:root:/root:/bin/bash\n')
        pwd = gocept.net.passwd.Passwd(self.pwd_file)
        self.assertEquals(1, len(pwd.records))
        entry = pwd.get('root')
        self.assertEquals(entry.login_name, 'root')
        self.assertEquals(entry.password, 'x')
        self.assertEquals(entry.uid, '0')
        self.assertEquals(entry.gid, '0')
        self.assertEquals(entry.gecos, 'root')
        self.assertEquals(entry.home, '/root')
        self.assertEquals(entry.shell, '/bin/bash')


class ShadowTest(unittest.TestCase):

    @mock.patch('gocept.net.utils.now')
    def test_lastchange_should_be_set_to_current_date(self, _now):
        # 2014-04-04 is 16164 days after the epoch
        _now.return_value = datetime.datetime(2014, 4, 4, tzinfo=pytz.utc)
        with tempfile.NamedTemporaryFile(prefix='shadow.') as tf:
            shadow = gocept.net.passwd.Shadow(tf.name)
            u = shadow.get('user', create=True)
            self.assertEqual(u.lastchange, '16164')
