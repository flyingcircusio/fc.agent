import gocept.net.configure.bacula
import glob
import os
import pytest


@pytest.fixture
def empty_config(tmpdir):
    os.mkdir(str(tmpdir / 'etc'))
    os.mkdir(str(tmpdir / 'etc/bacula/'))
    os.mkdir(str(tmpdir / 'etc/bacula/clients/'))
    os.mkdir(str(tmpdir / 'var'))
    os.mkdir(str(tmpdir / 'var/lib'))
    os.mkdir(str(tmpdir / 'var/lib/bacula'))
    os.mkdir(str(tmpdir / 'var/lib/bacula/stamps'))
    os.mkdir(str(tmpdir / 'var/lib/bacula/stamps/Full'))

    gocept.net.configure.bacula.ROOT = str(tmpdir)
    return tmpdir


def test_delete_nodes(empty_config, tmpdir, capsys, monkeypatch, directory):
    directory = directory()
    directory.deletions.return_value = {
        'node00': {'stages': []},
        'node01': {'stages': ['prepare']},
        'node02': {'stages': ['prepare', 'soft']},
        'node03': {'stages': ['prepare', 'soft', 'hard']},
        'node04': {'stages': ['prepare', 'soft', 'hard', 'purge']}}

    # Create config files for all nodes.
    for node in directory.deletions():
        for file in ['{}.conf', 'job.{}.conf']:
            file = file.format(node)
            with open(str(tmpdir / 'etc/bacula/clients' / file), 'w'):
                pass
        with open(str(tmpdir /
                  'var/lib/bacula/stamps/Full/Backup-{}'.format(node)), 'w'):
            pass

    gocept.net.configure.bacula.purge_stamps()

    remaining = glob.glob(str(tmpdir / 'etc/bacula/clients/*'))
    remaining.extend(glob.glob(str(tmpdir /
                                   'var/lib/bacula/stamps/*/Backup-*')))
    remaining.sort()
    remaining = [x.replace(str(tmpdir), '') for x in remaining]
    assert ['/etc/bacula/clients/job.node00.conf',
            '/etc/bacula/clients/job.node01.conf',
            '/etc/bacula/clients/job.node02.conf',
            '/etc/bacula/clients/node00.conf',
            '/etc/bacula/clients/node01.conf',
            '/etc/bacula/clients/node02.conf',
            '/var/lib/bacula/stamps/Full/Backup-node00',
            '/var/lib/bacula/stamps/Full/Backup-node01'] == remaining
