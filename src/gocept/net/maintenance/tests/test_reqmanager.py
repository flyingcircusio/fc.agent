from __future__ import print_function
from gocept.net.maintenance import ReqManager, Request
from gocept.net.maintenance.reqmanager import run_snippets
from gocept.net.utils import now

import contextlib
import datetime
import freezegun
import gocept.net.maintenance.reqmanager
import mock
import os
import pytest
import pytz
import time
import uuid as pyuuid


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


@pytest.yield_fixture
def dir_fac():
    with mock.patch('gocept.net.directory.Directory') as dir_fac:
        yield dir_fac


@pytest.yield_fixture
def request_cls():
    with mock.patch('gocept.net.maintenance.Request') as r:
        yield r


@contextlib.contextmanager
def request_population(n, dir):
    """Create a ReqManager with a pregenerated population of N requests.

    The ReqManager and a list of Requests are passed to the calling code.
    """
    with ReqManager(str(dir)) as reqmanager:
        reqmanager.PREPARE_SCRIPTS = str(dir / 'scripts/prepare')
        os.makedirs(reqmanager.PREPARE_SCRIPTS)
        reqmanager.FINISH_SCRIPTS = str(dir / 'scripts/finish')
        os.makedirs(reqmanager.FINISH_SCRIPTS)
        requests = []
        for i in range(n):
            req = reqmanager.add_request(
                1, 'exit 0', uuid=pyuuid.UUID('{:032d}'.format(i + 2 ** 32)))
            requests.append(req)
        yield (reqmanager, requests)


def test_init_should_create_directories(tmpdir):
    spooldir = str(tmpdir / 'maintenance')
    ReqManager(spooldir)
    assert os.path.isdir(spooldir)
    assert os.path.isdir(spooldir + '/requests')
    assert os.path.isdir(spooldir + '/archive')


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
    seqfile = str(tmpdir / '.SEQ')
    request = request_cls.return_value
    request.reqid = None
    with ReqManager(str(tmpdir)) as rm:
        rm.add(request)
    assert os.path.isfile(seqfile)
    assert '0\n' == open(seqfile).read()
    assert 0 == request.reqid


def test_add_should_increment_seq(tmpdir, request_cls):
    seqfile = str(tmpdir / '.SEQ')
    with open(seqfile, 'w') as f:
        print(7, file=f)
    request = request_cls.return_value
    request.reqid = None
    with ReqManager(str(tmpdir)) as rm:
        rm.add(request)
    assert '8\n' == open(seqfile).read()


def test_add_updates_existing_with_same_comment(tmpdir):
    with ReqManager(str(tmpdir)) as rm:
        first = rm.add_request(30, 'script', 'comment')
        rm.add_request(60, 'script2', 'comment')

        requests = rm.requests()
        assert len(requests) == 1
        assert requests[first.uuid].estimate == 60
        assert requests[first.uuid].script == 'script2'


def test_add_does_not_fold_when_comment_is_none(tmpdir):
    with ReqManager(str(tmpdir)) as rm:
        rm.add_request(30, 'script')
        rm.add_request(60, 'script2')
        assert len(rm.requests()) == 2


def test_add_does_not_fold_when_comment_differs(tmpdir):
    with ReqManager(str(tmpdir)) as rm:
        rm.add_request(30, 'script', 'comment1')
        rm.add_request(60, 'script2', 'comment2')
        assert len(rm.requests()) == 2


def test_schedule_emptylist(tmpdir, dir_fac):
    directory = dir_fac.return_value
    directory.schedule_maintenance = mock.Mock()
    with ReqManager(str(tmpdir)) as rm:
        rm.update_schedule()
    assert 0 == directory.schedule_maintenance.call_count


def test_schedule_should_update_request_time(tmpdir, dir_fac):
    with request_population(2, tmpdir) as (rm, req):
        directory = dir_fac.return_value
        directory.schedule_maintenance = mock.Mock()
        directory.schedule_maintenance.return_value = {
            req[0].uuid: {'time': '2011-07-25T10:55:28.368789+00:00'},
            req[1].uuid: {'time': None}}
        rm.update_schedule()
        assert rm.load_request(0).starttime == datetime.datetime(
            2011, 7, 25, 10, 55, 28, 368789, pytz.UTC)
        assert rm.load_request(1).starttime is None
        directory.schedule_maintenance.assert_called_with({
            req[0].uuid: {'estimate': 1, 'comment': None},
            req[1].uuid: {'estimate': 1, 'comment': None}})


def test_schedule_mark_off_deleted_requests(tmpdir, dir_fac):
    with request_population(1, tmpdir) as (rm, req):
        directory = dir_fac.return_value
        directory.schedule_maintenance = mock.Mock()
        directory.schedule_maintenance.return_value = {
            req[0].uuid: {'time': '2011-07-25T10:55:28.368789+00:00'},
            'jsHgdSNWx3nVMVLAMaY3tf': {'time': None}}
        directory.end_maintenance = mock.Mock()
        rm.update_schedule()
        directory.end_maintenance.assert_called_with({
            'jsHgdSNWx3nVMVLAMaY3tf': {'result': 'deleted'}})


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


def test_runnable_requests(tmpdir):
    with freezegun.freeze_time('2011-07-26 19:40:00', tz_offset=0):
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
            assert list(rm.runnable_requests()) == [
                req[3], req[4], req[1], req[0]]


def test_execute_requests(tmpdir):
    # Three requests: the first two are marked as due by the directory
    # scheduler. The first runs to completion, but the second exits with
    # TEMPFILE. The first request should be archived and processing should
    # be suspended after the second request. The third request should not
    # be touched.
    with freezegun.freeze_time('2011-07-27 07:12:00', tz_offset=0):
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


def test_postpone(tmpdir, dir_fac):
    directory = dir_fac.return_value
    directory.postpone_maintenance = mock.Mock()
    with freezegun.freeze_time('2011-07-27 07:12:00', tz_offset=0):
        with ReqManager(str(tmpdir)) as rm:
            rm.PREPARE_SCRIPTS = str(tmpdir / 'scripts/prepare')
            os.makedirs(rm.PREPARE_SCRIPTS)
            rm.FINISH_SCRIPTS = str(tmpdir / 'scripts/finish')
            os.makedirs(rm.FINISH_SCRIPTS)
            req = rm.add_request(300, script='exit 69')
            req.starttime = now()
            req.save()
            assert req.state == Request.DUE
            rm.execute_requests()
            rm.postpone_requests()
            req = rm.load_request(req.reqid)
            assert req.state == Request.PENDING
            assert req.starttime is None
            directory.postpone_maintenance.assert_called_with({
                req.uuid: {'postpone_by': 300}})


def test_archive(tmpdir, dir_fac):
    directory = dir_fac.return_value
    directory.end_maintenance = mock.Mock()
    with ReqManager(str(tmpdir)) as rm:
        request = rm.add_request(
            1, script='exit 0',
            uuid='f02c4745-46e5-11e3-8000-000000000000')
        request.execute()
        rm.archive_requests()
        assert not os.path.exists(rm.requestsdir + '/0'), \
            'request 0 should not exist in requestsdir'
        assert os.path.exists(rm.archivedir + '/0'), \
            'request 0 should exist in archivedir'
        directory.end_maintenance.assert_called_with({
            request.uuid: {'duration': 0, 'result': 'success'}})


def test_str(tmpdir, tz_utc):
    with freezegun.freeze_time('2011-07-28 11:03:00', tz_offset=0):
        with request_population(3, tmpdir) as (rm, req):
            rm.localtime = pytz.utc
            req[0].execute()
            req[1].starttime = datetime.datetime(
                2011, 7, 28, 11, 1, tzinfo=pytz.utc)
            req[1].save()
            req[2].comment = 'reason'
            req[2].save()
            assert """\
({0}) scheduled: None, estimate: 1s, state: success

({1}) scheduled: 2011-07-28 11:01:00 UTC, estimate: 1s, state: due

({2}) scheduled: None, estimate: 1s, state: pending
reason

""".format(req[0].uuid[0:8], req[1].uuid[0:8], req[2].uuid[0:8]) == str(rm)


def generate_snippets(tmp, *exitcodes):
    tmp = str(tmp)
    if not os.path.exists(tmp):
        os.makedirs(tmp)
    for i, exitcode in enumerate(exitcodes):
        with open(tmp + '/' + str(i), 'w') as f:
            f.write("""\
#!/bin/sh
exit {}
""".format(exitcode))
            os.fchmod(f.fileno(), 0o755)
    return tmp


def test_snippet_directory(tmpdir):
    generate_snippets(tmpdir, 0, 69)
    with pytest.raises(RuntimeError) as e:
        run_snippets(str(tmpdir))
    assert 'overall status 69' in str(e.value)


def test_snippet_dir_highest_nonzero_wins(tmpdir):
    generate_snippets(tmpdir, 1, 75, 69)
    with pytest.raises(RuntimeError) as e:
        run_snippets(str(tmpdir))
    assert 'overall status 75' in str(e.value)


def test_snippet_dir_should_skip_nonexecutable_files(tmpdir):
    generate_snippets(tmpdir, 1, 0)
    os.chmod(str(tmpdir) + '/0', 0o644)
    run_snippets(str(tmpdir))


@pytest.fixture
def log_run_snippets(monkeypatch):
    run_snippets = []
    original = gocept.net.maintenance.reqmanager.run_snippets

    def logged_run_snippets(dir):
        run_snippets.append(dir.split('/')[-1])
        return original(dir)
    monkeypatch.setattr(
        'gocept.net.maintenance.reqmanager.run_snippets', logged_run_snippets)
    return run_snippets


def test_execute_requests_stopped_by_prepare_scripts(tmpdir, log_run_snippets):
    # Three requests: the first two are marked as due by the directory
    # scheduler. The first runs to completion, but the second exits with
    # TEMPFILE. The first request should be archived and processing should
    # be suspended after the second request. The third request should not
    # be touched.

    with freezegun.freeze_time('2011-07-27 07:12:00', tz_offset=0):
        with request_population(3, tmpdir) as (rm, req):
            rm.PREPARE_SCRIPTS = generate_snippets(str(tmpdir / 'prepare'), 5)
            rm.FINISH_SCRIPTS = generate_snippets(str(tmpdir / 'finish'))
            req[0].starttime = datetime.datetime(
                2011, 7, 27, 7, 0, tzinfo=pytz.utc)
            req[0].save()
            req[1].script = 'exit 75'
            req[1].starttime = datetime.datetime(
                2011, 7, 27, 7, 10, tzinfo=pytz.utc)
            req[1].save()
            rm.execute_requests()
        assert log_run_snippets == ['prepare']
        assert req[0].state == Request.DUE
        assert req[1].state == Request.DUE
        assert req[2].state == Request.PENDING


def test_execute_requests_run_finish_scripts(tmpdir, log_run_snippets):
    # Three requests: the first two are marked as due by the directory
    # scheduler. The first runs to completion, but the second exits with
    # TEMPFILE. The first request should be archived and processing should
    # be suspended after the second request. The third request should not
    # be touched.

    with freezegun.freeze_time('2011-07-27 07:12:00', tz_offset=0):
        with request_population(3, tmpdir) as (rm, req):
            rm.PREPARE_SCRIPTS = generate_snippets(str(tmpdir / 'prepare'), 0)
            rm.FINISH_SCRIPTS = generate_snippets(str(tmpdir / 'finish'))
            req[0].starttime = datetime.datetime(
                2011, 7, 27, 7, 0, tzinfo=pytz.utc)
            req[0].save()
            rm.execute_requests()
        assert req[0].state == Request.SUCCESS
        assert req[2].state == Request.PENDING
    assert log_run_snippets == ['prepare', 'finish']


def test_execute_requests_does_not_run_finish_scripts_on_fail(
        tmpdir, log_run_snippets):
    # Three requests: the first two are marked as due by the directory
    # scheduler. The first runs to completion, but the second exits with
    # TEMPFILE. The first request should be archived and processing should
    # be suspended after the second request. The third request should not
    # be touched.
    with freezegun.freeze_time('2011-07-27 07:12:00', tz_offset=0):
        with request_population(3, tmpdir) as (rm, req):
            rm.PREPARE_SCRIPTS = generate_snippets(str(tmpdir / 'prepare'), 0)
            rm.FINISH_SCRIPTS = generate_snippets(str(tmpdir / 'finish'), 0)
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
    assert log_run_snippets == ['prepare']
