from __future__ import print_function
from gocept.net.maintenance import ReqManager, Request

import contextlib
import datetime
import mock
import os
import os.path
import pytest
import pytz
import shutil
import tempfile
import time
import unittest
import uuid


@pytest.yield_fixture
def tz_utc():
    """Decorator to fix $TZ to UTC and restore it afterwards."""
    oldtz = os.environ.get('TZ')
    os.environ['TZ'] = 'UTC'
    time.tzset()
    yield
    if oldtz:
        os.environ['TZ'] = oldtz
    else:
        del os.environ['TZ']
    time.tzset()


@contextlib.contextmanager
def request_population(n, dir):
    """Create a ReqManager with a pregenerated population of N requests.

    The ReqManager and a list of Requests are passed to the calling code.
    """
    with ReqManager(str(dir)) as reqmanager:
        requests = []
        for i in range(n):
            req = reqmanager.add_request(
                1, 'exit 0', _uuid=uuid.UUID('{:032d}'.format(i)))
            requests.append(req)
        yield (reqmanager, requests)

def test_init_should_create_directories(tmpdir):
    spooldir = str(tmpdir/'maintenance')
    ReqManager(spooldir)
    assert os.path.isdir(spooldir)
    assert os.path.isdir(spooldir+'/requests')
    assert os.path.isdir(spooldir+'/archive')


def test_should_open_lockfile(tmpdir):
    with ReqManager(str(tmpdir)) as rm:
        # invoke any method that requires locking
        rm.runnable_requests()
        assert not rm.lockfile.closed, (
            'lock file {0!r} is not open'.format(rm.lockfile))


def test_add_request_should_set_path(tmpdir):
    with ReqManager(str(tmpdir)) as rm:
        request = rm.add_request(30, 'script', 'comment')
    assert request.path == tmpdir / 'requests' / '0'



def test_add_should_init_seq_to_allocate_ids(tmpdir, request_cls):
    seqfile = str(tmpdir/'.SEQ')
    request = request_cls.return_value
    request.reqid = None
    with ReqManager(str(tmpdir)) as rm:
        rm.add(request)
    assert os.path.isfile(seqfile)
    assert '0\n' == open(seqfile).read()
    assert 0 == request.reqid


def test_add_should_increment_seq(tmpdir, request_cls):
    seqfile = str(tmpdir/'.SEQ')
    with open(seqfile, 'w') as f:
        print(7, file=f)
    request = request_cls.return_value
    request.reqid = None
    with ReqManager(str(tmpdir)) as rm:
        rm.add(request)
    assert '8\n' == open(seqfile).read()


def test_schedule_emptylist(tmpdir, dir_fac):
    directory = dir_fac.return_value
    directory.schedule_maintenance = mock.Mock()
    with ReqManager(str(tmpdir)) as rm:
        rm.update_schedule()
    assert 0 == directory.schedule_maintenance.call_count


def test_schedule_should_update_request_time(tmpdir, dir_fac):
    directory = dir_fac.return_value
    directory.schedule_maintenance = mock.Mock()
    directory.schedule_maintenance.return_value = {
        '00000000-0000-0000-0000-000000000000': {
            'time': '2011-07-25T10:55:28.368789+00:00'},
        '00000000-0000-0000-0000-000000000001': {
            'time': None}}
    with request_population(2, tmpdir) as (rm, req):
        rm.update_schedule()
        assert rm.load_request(0).starttime == datetime.datetime(
            2011, 7, 25, 10, 55, 28, 368789, pytz.UTC)
        assert rm.load_request(1).starttime is None
    directory.schedule_maintenance.assert_called_with({
        '00000000-0000-0000-0000-000000000000': {
            'estimate': 1, 'comment': None},
        '00000000-0000-0000-0000-000000000001': {
            'estimate': 1, 'comment': None}})


def test_schedule_mark_off_deleted_requests(tmpdir, dir_fac):
    directory = dir_fac.return_value
    directory.schedule_maintenance = mock.Mock()
    directory.schedule_maintenance.return_value = {
        '00000000-0000-0000-0000-000000000000': {
            'time': '2011-07-25T10:55:28.368789+00:00'},
        '00000000-0000-0000-0000-000000000001': {'time': None}}
    directory.end_maintenance = mock.Mock()
    with request_population(1, tmpdir) as (rm, req):
        rm.update_schedule()
    directory.end_maintenance.assert_called_with({
        '00000000-0000-0000-0000-000000000001': {'result': 'deleted'}})

def test_load_should_return_request(tmpdir):
    with ReqManager(str(tmpdir)) as rm:
        req1 = rm.add_request(300, comment='do something')
        req2 = rm.load_request(req1.reqid)
        assert req1 == req2


def test_current_requests(tmpdir):
    with request_population(2, tmpdir) as (rm, req):
        # directory without data file should be skipped
        os.mkdir(str(tmpdir / '5'))
        # non-directory should be skipped
        open(str(tmpdir / '6'), 'w').close()
        assert {req[0].uuid: req[0],
                req[1].uuid: req[1]} == rm.requests()


def test_runnable_requests(tmpdir, now):
    now.return_value = datetime.datetime(
        2011, 7, 26, 19, 40, tzinfo=pytz.utc)
    # req3 is active and should be returned first. req4 has been partially
    # completed and should be resumed directly after. req0 and req1 are
    # due, but req1's starttime is older so it should precede req0's. req2
    # is still pending and should not be returned.
    with request_population(5, tmpdir) as (rm, req):
        req[0].starttime = now() - datetime.timedelta(30)
        req[0].save()
        req[1].starttime = now() - datetime.timedelta(45)
        req[1].save()
        req[3].start()
        req[4].script = 'exit 75'
        req[4].save()
        req[4].execute()
        assert list(rm.runnable_requests()) == [req[3], req[4], req[1], req[0]]


def test_execute_requests(tmpdir, now):
    # Three requests: the first two are marked as due by the directory
    # scheduler. The first runs to completion, but the second exits with
    # TEMPFILE. The first request should be archived and processing should
    # be suspended after the second request. The third request should not
    # be touched.
    now.return_value = datetime.datetime(
        2011, 7, 27, 7, 12, tzinfo=pytz.utc)
    with request_population(3, tmpdir) as (rm, req):
        req[0].starttime = datetime.datetime(
            2011, 7, 27, 7, 0, tzinfo=pytz.utc)
        req[0].save()
        req[1].script = 'exit 75'
        req[1].starttime = datetime.datetime(
            2011, 7, 27, 7, 10, tzinfo=pytz.utc)
        req[1].save()
        rm.execute_requests()
    assert req[0].state == Request.SUCCESS
    assert req[1].state == Request.TEMPFAIL
    assert req[2].state == Request.PENDING



def test_archive(tmpdir, dir_fac):
    directory = dir_fac.return_value
    directory.end_maintenance = mock.Mock()
    with ReqManager(str(tmpdir)) as rm:
        request = rm.add_request(
            1, script='exit 0',
            _uuid='f02c4745-46e5-11e3-8000-000000000000')
        request.execute()
        rm.archive_requests()
        assert not os.path.exists(rm.requestsdir+'/0'), \
            'request 0 should not exist in requestsdir'
        assert os.path.exists(rm.archivedir+'/0'), \
            'request 0 should exist in archivedir'
    directory.end_maintenance.assert_called_with({
        'f02c4745-46e5-11e3-8000-000000000000': {
            'duration': 0, 'result': 'success'}})


@pytest.yield_fixture
def now():
    with mock.patch('gocept.net.utils.now') as now:
        yield now


@pytest.yield_fixture
def dir_fac():
    with mock.patch('gocept.net.directory.Directory') as dir_fac:
        yield dir_fac

@pytest.yield_fixture
def request_cls():
    with mock.patch('gocept.net.maintenance.Request') as r:
        yield r


def test_str(tmpdir, tz_utc, now):
    now.return_value = datetime.datetime(
        2011, 7, 28, 11, 3, tzinfo=pytz.utc)
    with request_population(3, tmpdir) as (rm, req):
        rm.localtime = pytz.utc
        req[0].execute()
        req[1].starttime = datetime.datetime(
            2011, 7, 28, 11, 1, tzinfo=pytz.utc)
        req[1].save()
        req[2].comment = 'reason'
        req[2].save()
        assert """\
(00000000) scheduled: None, estimate: 1s, state: success

(00000000) scheduled: 2011-07-28 11:01:00 UTC, estimate: 1s, state: due

(00000000) scheduled: None, estimate: 1s, state: pending
reason

""" == str(rm)
