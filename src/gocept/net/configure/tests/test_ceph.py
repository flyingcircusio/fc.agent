from mock import call
import gocept.net.configfile
import gocept.net.configure.ceph
from gocept.net.ceph.rbdimage import RBDImage
import mock
import unittest


class CephConfigurationTest(unittest.TestCase):

    def setUp(self):
        self.p_directory = mock.patch('gocept.net.directory.Directory')
        self.fake_directory = self.p_directory.start()

        self.p_call = mock.patch(
            'gocept.net.ceph.cluster.Cluster.generic_ceph_cmd')
        self.fake_call = self.p_call.start()

        self.p_load_pool = mock.patch('gocept.net.ceph.pools.Pool.load')
        self.fake_load_pool = self.p_load_pool.start()

        gocept.net.configfile.ConfigFile.quiet = True

    def tearDown(self):
        self.p_call.stop()
        self.p_directory.stop()
        self.p_load_pool.stop()

    def test_node_deletion(self):
        self.fake_directory().deletions.return_value = {
            'node00': {'stages': []},
            'node01': {'stages': ['prepare']},
            'node02': {'stages': ['prepare', 'soft']},
            'node03': {'stages': ['prepare', 'soft', 'hard']},
            'node04': {'stages': ['prepare', 'soft', 'hard', 'purge']}}
        import sys
        sys.argv = ['']

        images = {}
        for node in range(5):
            name = 'node0{}'.format(node)
            images['{}.root'.format(name)] = RBDImage(
                '{}.root'.format(name), 100)
            images['{}.root@snap1'.format(name)] = RBDImage(
                '{}.root'.format(name), 100, snapshot='snap1')
            images['{}.swap'.format(name)] = RBDImage(
                '{}.swap'.format(name), 100)
            images['{}.tmp'.format(name)] = RBDImage(
                '{}.tmp'.format(name), 100)

        self.fake_load_pool.return_value = images

        gocept.net.configure.ceph.purge_volumes()

        assert self.fake_call.call_args_list == [
            call(['rbd', '--id', 'admin', '-c', '/etc/ceph/ceph.conf'],
                 ['snap', 'rm', 'node/node04.root@snap1'], False, False),
            call(['rbd', '--id', 'admin', '-c', '/etc/ceph/ceph.conf'],
                 ['rm', 'node/node04.root'], False, False),
            call(['rbd', '--id', 'admin', '-c', '/etc/ceph/ceph.conf'],
                 ['rm', 'node/node04.swap'], False, False),
            call(['rbd', '--id', 'admin', '-c', '/etc/ceph/ceph.conf'],
                 ['rm', 'node/node04.tmp'], False, False)]

    def test_node_deletion_missing_pool(self):
        self.fake_directory().deletions.return_value = {
            'node00': {'stages': []},
            'node01': {'stages': ['prepare']},
            'node02': {'stages': ['prepare', 'soft']},
            'node03': {'stages': ['prepare', 'soft', 'hard']},
            'node04': {'stages': ['prepare', 'soft', 'hard', 'purge']}}
        import sys
        sys.argv = ['']

        self.fake_load_pool.side_effect = KeyError()

        gocept.net.configure.ceph.purge_volumes()
