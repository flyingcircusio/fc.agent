from gocept.net.configure.kvm import ensure_vms, VM
import mock
import os
import pytest
import unittest


@pytest.fixture(autouse=True)
def prefix_kvm_paths(tmpdir, monkeypatch):
    os.mkdir(str(tmpdir / 'etc'))
    os.mkdir(str(tmpdir / 'etc/kvm'))
    os.mkdir(str(tmpdir / 'etc/conf.d'))
    os.mkdir(str(tmpdir / 'etc/init.d'))
    os.mkdir(str(tmpdir / 'etc/qemu'))
    os.mkdir(str(tmpdir / 'etc/qemu/vm'))
    os.mkdir(str(tmpdir / 'etc/runlevels'))
    os.mkdir(str(tmpdir / 'etc/runlevels/default'))
    os.mkdir(str(tmpdir / 'run'))
    monkeypatch.setattr(VM, 'root', str(tmpdir))


def make_vm(**kw):
    result = {'name': 'test00',
              'parameters': {'id': 1000,
                             'online': False,
                             'memory': 512,
                             'cores': 1,
                             'resource_group': 'test',
                             'disk': 10,
                             'interfaces': {'srv': {'mac': 'foo'}}}}
    result['parameters'].update(kw)
    return result


class KVMConfigTest(unittest.TestCase):

    def setUp(self):
        os.environ['PUPPET_LOCATION'] = 'dev'
        self.p_directory = mock.patch('gocept.net.directory.Directory')
        self.fake_directory = self.p_directory.start()

    def tearDown(self):
        del os.environ['PUPPET_LOCATION']
        self.p_directory.stop()

    def test_node_deletion(self):
        self.fake_directory().list_virtual_machines.return_value = []
        self.fake_directory().deletions.return_value = {
            'node00': {'stages': []},
            'node01': {'stages': ['prepare']},
            'node02': {'stages': ['prepare', 'soft']},
            'node03': {'stages': ['prepare', 'soft', 'hard']}}
        cfgs = {}
        for node in self.fake_directory().deletions.return_value.keys():
            cfgs[node] = VM.configfile.format(root=VM.root, name=node)
            with open(cfgs[node], 'w') as f:
                f.write('test')
        with self.assertRaises(SystemExit) as e:
            ensure_vms()
        assert e.exception.code == 0
        assert os.path.exists(cfgs['node00'])
        assert os.path.exists(cfgs['node01'])
        assert os.path.exists(cfgs['node02'])
        assert not os.path.exists(cfgs['node03'])
        # Running twice must work without exploding
        with self.assertRaises(SystemExit) as e:
            ensure_vms()
        assert e.exception.code == 0
        assert os.path.exists(cfgs['node00'])
        assert os.path.exists(cfgs['node01'])
        assert os.path.exists(cfgs['node02'])
        assert not os.path.exists(cfgs['node03'])
