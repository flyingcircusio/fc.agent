from gocept.net.configure.backy import configure, BackyConfig
import mock
import os
import os.path as p
import pytest
import subprocess


@pytest.fixture
def enc(directory):
    d = directory()
    d.list_virtual_machines.return_value = [
        {'name': 'test01',
         'parameters': {
             'backy_server': 'thishost',
             'backy_schedule': 'asdf',
             'rbd_pool': 'rbd.hdd',
             'resource_group': 'test',
         }},
        {'name': 'test02',
         'parameters': {
             'backy_server': 'anotherhost',
             'backy_schedule': 'asdf',
             'rbd_pool': 'rbd.ssd',
             'resource_group': 'test',
         }}]
    d.deletions.return_value = {
        'node00': {'stages': []},
        'node01': {'stages': ['prepare']},
        'node02': {'stages': ['prepare', 'soft']},
        'node03': {'stages': ['prepare', 'soft', 'hard']},
        'node04': {'stages': ['prepare', 'soft', 'hard', 'purge']}}
    return d


@pytest.fixture
def backyenv(tmpdir, monkeypatch):
    check_call = mock.Mock()
    monkeypatch.setattr(subprocess, 'check_call', check_call)
    monkeypatch.setenv('PUPPET_LOCATION', 'test')
    monkeypatch.setenv('CONSUL_ACL_TOKEN', '123')
    prefix = BackyConfig.prefix = str(tmpdir)
    BackyConfig.hostname = 'thishost'
    os.makedirs(prefix + '/etc')
    return (check_call, tmpdir)


def test_backy_config(backyenv, enc):
    configure()

    call, prefix = backyenv
    assert call.call_args_list == [
        mock.call(['/etc/init.d/backy', 'restart'])]
    with open(str(prefix / 'etc/backy.conf')) as c:
        assert c.read() == """\
# Managed by localconfig, don't edit

global: {base-dir: /srv/backy, worker-limit: 3}
jobs:
  test01:
    schedule: asdf
    source: {consul_acl_token: '123', image: test01.root, pool: rbd.hdd, \
type: flyingcircus,
      vm: test01}
schedules:
  default:
    daily: {interval: 1d, keep: 10}
    monthly: {interval: 30d, keep: 4}
    weekly: {interval: 7d, keep: 4}
  frequent:
    daily: {interval: 1d, keep: 10}
    hourly: {interval: 1h, keep: 25}
    monthly: {interval: 30d, keep: 4}
    weekly: {interval: 7d, keep: 4}
"""


def test_backy_remove_deleted_nodes(backyenv, enc):
    _call, prefix = backyenv
    os.makedirs(str(prefix / 'srv/backy/node00'))
    os.makedirs(str(prefix / 'srv/backy/node01'))
    os.makedirs(str(prefix / 'srv/backy/node02'))
    os.makedirs(str(prefix / 'srv/backy/node03'))
    os.makedirs(str(prefix / 'srv/backy/node04'))

    configure()

    assert p.exists(str(prefix / 'srv/backy/node00'))
    assert p.exists(str(prefix / 'srv/backy/node01'))
    assert p.exists(str(prefix / 'srv/backy/node02'))
    assert p.exists(str(prefix / 'srv/backy/node03'))
    assert not p.exists(str(prefix / 'srv/backy/node04'))


def vm_params(vms):
    return [{
        'name': vm, 'parameters': {
            'backy_server': 'thishost', 'backy_schedule': 'default',
            'rbd_pool': 'rbd.hdd', 'resource_group': 'node',
        }} for vm in vms]


def test_backy_dont_configure_deleted_nodes(backyenv, enc):
    enc.list_virtual_machines.return_value = vm_params([
        'node00', 'node01', 'node02', 'node03', 'node04'])
    b = BackyConfig('location', 'consul_acl_token')
    assert set(b.job_config().keys()) == set(['node00', 'node01', 'node02'])
