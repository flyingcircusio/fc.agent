# Copyright (c) 2011 gocept gmbh & co. kg
# See also LICENSE.txt

from gocept.net.configfile import ConfigFile
import cStringIO
import os
import os.path
import tempfile
import unittest


class TestConfigFile(unittest.TestCase):

    def setUp(self):
        self.tf = tempfile.NamedTemporaryFile(suffix='test_configfile',
                                              delete=False)
        self.diffout = cStringIO.StringIO()

    def tearDown(self):
        try:
            os.unlink(self.tf.name)
        except OSError:
            pass

    def test_configfile_behaves_stringio_like(self):
        c = ConfigFile('filename')
        print >>c, 'hello world'
        self.assertEquals(c.getvalue(), 'hello world\n')

    def test_create_file(self):
        os.unlink(self.tf.name)
        c = ConfigFile(self.tf.name, stdout=self.diffout)
        print >>c, 'hello world'
        self.assertRaises(OSError, os.stat, self.tf.name)
        c.commit()
        self.assertEquals(open(self.tf.name).read(), 'hello world\n')

    def test_modify_file(self):
        with open(self.tf.name, 'w') as f:
            print >>f, 'old file contents'
        c = ConfigFile(self.tf.name, stdout=self.diffout)
        print >>c, 'hello world'
        changed = c.commit()
        self.assert_(changed, 'commit() did not set changed flag')
        self.assertEquals(open(self.tf.name).read(), 'hello world\n')

    def test_print_diff(self):
        with open(self.tf.name, 'w') as f:
            print >>f, 'hello world 0\nhello world 1'
        c = ConfigFile(self.tf.name, stdout=self.diffout)
        print >>c, 'hello world 1'
        print >>c, 'hello world 2'
        c.commit()
        self.assertEquals(self.diffout.getvalue(), """\
--- {fn} (old)
+++ {fn} (new)
@@ -1,2 +1,2 @@
-hello world 0
 hello world 1
+hello world 2
""".format(fn=self.tf.name))

    def test_dont_touch_unchanged(self):
        with open(self.tf.name, 'w') as f:
            print >>f, 'hello world'
        before = os.stat(self.tf.name)
        c = ConfigFile(self.tf.name, self.diffout)
        print >>c, 'hello world'
        changed = c.commit()
        self.assertFalse(changed, "commit() set changed flag but shouldn't")
        after = os.stat(self.tf.name)
        self.assertEquals(before, after)
        self.assertEquals('', self.diffout.getvalue())
