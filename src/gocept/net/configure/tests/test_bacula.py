from gocept.net.configure.bacula import BaculaState, expected_nodes
import os
import pytest


@pytest.fixture
def bacula_dir(tmpdir):
    os.mkdir(str(tmpdir / 'stamps'))
    os.mkdir(str(tmpdir / 'stamps/Full'))
    os.mkdir(str(tmpdir / 'clients'))
    BaculaState.STAMPDIR = str(tmpdir / 'stamps')
    BaculaState.CLIENTDIR = str(tmpdir / 'clients')
    return tmpdir


def touch(tmpdir, fn):
    open(str(tmpdir / fn), 'a').close()


def test_expected_nodes(directory):
    d = directory()
    d.class_map.return_value = {'node00': {}, 'node01': {}}
    assert (set(['node00', 'node01']) == expected_nodes())


def test_purge_stamps(bacula_dir):
    touch(bacula_dir, 'stamps/Full/Backup-node01')  # keep
    touch(bacula_dir, 'stamps/Full/Backup-node02')  # delete
    touch(bacula_dir, 'stamps/Full/somethingelse')  # don't touch

    BaculaState().purge_stamps(set(['node00', 'node01']))
    assert set(['Backup-node01', 'somethingelse']) == set(os.listdir(str(
        bacula_dir / 'stamps/Full')))
