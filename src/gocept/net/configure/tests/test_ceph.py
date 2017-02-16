from ..ceph import VolumeDeletions
from gocept.net.ceph.rbdimage import RBDImage
import collections
import gocept.net.ceph.cluster
import gocept.net.configfile
import gocept.net.configure.ceph
import gocept.net.directory
import mock
import pytest


# class CephConfigurationTest(unittest.TestCase):

#     def setUp(self):
#         self.p_directory = mock.patch('gocept.net.directory.Directory')
#         self.fake_directory = self.p_directory.start()

#         self.p_call = mock.patch(
#             'gocept.net.ceph.cluster.Cluster.generic_ceph_cmd')
#         self.fake_call = self.p_call.start()

#         self.p_load_pool = mock.patch('gocept.net.ceph.pools.Pool.load')
#         self.fake_load_pool = self.p_load_pool.start()

#         gocept.net.configfile.ConfigFile.quiet = True

#     def tearDown(self):
#         self.p_call.stop()
#         self.p_directory.stop()
#         self.p_load_pool.stop()


@pytest.fixture
def fake_directory():
    d = mock.MagicMock(spec=['deletions'])
    d.deletions.return_value = collections.OrderedDict([
        ('node00', {'stages': []}),
        ('node01', {'stages': ['prepare']}),
        ('node02', {'stages': ['prepare', 'soft']}),
        ('node03', {'stages': ['prepare', 'soft', 'hard']}),
        ('node04', {'stages': ['prepare', 'soft', 'hard', 'purge']}),
    ])
    return d


@pytest.fixture
def cluster(monkeypatch):
    monkeypatch.setattr(
        gocept.net.ceph.cluster.Cluster, 'rbd',
        mock.MagicMock(spec=gocept.net.ceph.cluster.Cluster.rbd))
    return gocept.net.ceph.cluster.Cluster(ceph_id='admin')


@pytest.fixture
def pools(cluster, monkeypatch):
    monkeypatch.setattr(gocept.net.ceph.pools.Pools, 'names',
                        lambda self: set(['rbd.hdd', 'rbd.ssd']))
    images_hdd = {}
    images_ssd = {}
    for node in range(5):
        images = images_hdd if node % 2 else images_ssd
        name = 'node0{}'.format(node)
        images['{}.root'.format(name)] = RBDImage(
            '{}.root'.format(name), 100)
        images['{}.root@snap1'.format(name)] = RBDImage(
            '{}.root'.format(name), 100, snapshot='snap1')
        images['{}.swap'.format(name)] = RBDImage(
            '{}.swap'.format(name), 100)
        images['{}.tmp'.format(name)] = RBDImage(
            '{}.tmp'.format(name), 100)
    monkeypatch.setattr(
        gocept.net.ceph.pools.Pool, 'load',
        lambda self: images_hdd if self.name == 'rbd.hdd' else images_ssd)
    return gocept.net.ceph.pools.Pools(cluster)


def test_node_deletion(fake_directory, cluster, pools):
    v = VolumeDeletions(fake_directory, cluster)
    v.ensure()

    assert cluster.rbd.call_args_list == [
        # hard
        mock.call(['snap', 'rm', 'rbd.hdd/node03.root@snap1']),
        mock.call(['rm', 'rbd.hdd/node03.root']),
        mock.call(['rm', 'rbd.hdd/node03.swap']),
        mock.call(['rm', 'rbd.hdd/node03.tmp']),
        # purge
        mock.call(['snap', 'rm', 'rbd.ssd/node04.root@snap1']),
        mock.call(['rm', 'rbd.ssd/node04.root']),
        mock.call(['rm', 'rbd.ssd/node04.swap']),
        mock.call(['rm', 'rbd.ssd/node04.tmp']),
    ]
