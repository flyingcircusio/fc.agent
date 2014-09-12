from gocept.net.configure.kvm import ensure_vms, VM
import mock
import os
import pytest
import shutil
import tempfile
import unittest


@pytest.fixture(autouse=True)
def prefix_kvm_paths(tmpdir, monkeypatch):
    os.mkdir(str(tmpdir/'etc'))
    os.mkdir(str(tmpdir/'etc/kvm'))
    os.mkdir(str(tmpdir/'etc/conf.d'))
    os.mkdir(str(tmpdir/'etc/init.d'))
    os.mkdir(str(tmpdir/'etc/qemu'))
    os.mkdir(str(tmpdir/'etc/qemu/vm'))
    os.mkdir(str(tmpdir/'etc/runlevels'))
    os.mkdir(str(tmpdir/'etc/runlevels/default'))
    os.mkdir(str(tmpdir/'run'))
    monkeypatch.setattr(VM, 'root',  str(tmpdir))


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

    @mock.patch('gocept.net.configure.kvm.VM.ensure')
    def test_no_actions_on_empty_list(self, ensure):
        with self.assertRaises(SystemExit) as e:
            ensure_vms()
        assert e.exception.code == 0
        self.assertEquals(ensure.call_count, 0)

    @mock.patch('gocept.net.configure.kvm.VM.ensure')
    def test_listed_vms_get_ensure_called(self, ensure):
        self.fake_directory().list_virtual_machines.return_value = [
            make_vm()]
        with self.assertRaises(SystemExit) as e:
            ensure_vms()
        assert e.exception.code == 0
        self.assertEquals(ensure.call_count, 1)


class VMTest(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.p_call = mock.patch('gocept.net.configure.kvm.call')
        self.call = self.p_call.start()

        self.p_subpcall = mock.patch('subprocess.check_call')
        self.subpcall = self.p_subpcall.start()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)
        self.p_call.stop()
        self.p_subpcall.stop()

    def test_vm_config_generated_and_ensure_called(self):
        vm = VM(make_vm(online=True, kvm_host='foo'))
        vm.ensure()
        assert """\
name: test00
parameters:
  cores: 1
  disk: 10
  id: 1000
  interfaces:
    srv: {mac: foo}
  kvm_host: foo
  memory: 512
  online: true
  resource_group: test
""" == open(vm.configfile, 'r').read()

    def test_vm_old_files_migrated(self):
        vm = VM(make_vm(online=True, kvm_host='foo'))
        files = [vm.root+'/run/kvm.test00.pid',
                 vm.root+'/run/kvm.test00.cfg',
                 vm.root+'/run/kvm.test00.cfg.in',
                 vm.root+'/run/kvm.test00.opt',
                 vm.root+'/run/kvm.test00.opt.in',
                 vm.root+'/etc/runlevels/default/kvm.test00',
                 vm.root+'/etc/conf.d/kvm.test00',
                 vm.root+'/etc/kvm/test00.opt',
                 vm.root+'/etc/kvm/test00.cfg',
                 vm.root+'/etc/init.d/kvm.test00']
        for f in files:
            open(f, 'w')
        vm.ensure()
        assert os.path.exists(vm.root+'/run/qemu.test00.pid')
        for f in files:
            assert not os.path.exists(f)
