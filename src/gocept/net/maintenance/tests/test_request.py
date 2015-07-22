from __future__ import print_function
from gocept.net.maintenance import Request

import datetime
import freezegun
import gocept.net.utils
import os
import os.path as p
import pytest
import pytz
import shutil
import StringIO
import uuid as pyuuid


def test_deserialize():
    io = StringIO.StringIO("""\
{
  "comment": "user notice",
  "reqid": 16,
  "estimate": 950,
  "starttime": "2011-07-25T16:09:41+00:00",
  "script": "echo",
  "applicable": "true",
  "uuid": "2345fa72-7f9f-42c2-aa33-6eaf5d891e29"
}
""")
    assert Request.deserialize(io) == Request(
        16, 950, 'echo', 'user notice',
        datetime.datetime(2011, 7, 25, 16, 9, 41, tzinfo=pytz.UTC), 'true',
        uuid=pyuuid.UUID('2345fa72-7f9f-42c2-aa33-6eaf5d891e29'))


def test_serialize():
    io = StringIO.StringIO()
    request = Request(
        51, 900, '/bin/true', 'do something',
        datetime.datetime(2011, 7, 25, 3, 5, tzinfo=pytz.UTC),
        'check_something', uuid='0ae23c8f-46e0-11e3-8000-001fd0a3d7a6')
    request.serialize(io)
    assert """\
{
  "comment": "do something",\x20
  "uuid": "iSDJhfaauzAEMRtAaNXPw3",\x20
  "script": "/bin/true",\x20
  "applicable": "check_something",\x20
  "reqid": 51,\x20
  "starttime": "2011-07-25T03:05:00+00:00",\x20
  "estimate": 900
}
""" == io.getvalue()


def test_save(tmpdir):
    r = Request(19, 980, path=str(tmpdir/'19'))
    r.save()
    assert os.path.exists(str(tmpdir/'19/data')) is True


def test_eq():
    stub_uuid = pyuuid.UUID('11afa30a-46de-11e3-8000-000000000000')
    assert Request(11, 39, uuid=stub_uuid) == Request(11, 39, uuid=stub_uuid)
    assert Request(11, 39, uuid=stub_uuid) != Request(12, 39, uuid=stub_uuid)


def test_repr_rpc():
    request = Request(66, 160, 'script', 'a comment')
    assert request.repr_rpc == {'estimate': 160, 'comment': 'a comment'}


def test_state_should_tolerate_empty_exitcode_file(tmpdir):
    request = Request(0, 1, path=str(tmpdir))
    request.save()
    with open(str(tmpdir/'exitcode'), 'w') as f:
        print('', file=f)
    assert request.exitcode is None
    assert request.state == Request.PENDING


def test_exitcode_should_read_last_line(tmpdir):
    request = Request(0, 1, path=str(tmpdir))
    request.save()
    with open(str(tmpdir/'exitcode'), 'w') as f:
        print('0\n2', file=f)
    assert request.exitcode == 2


def test_state_pending(tmpdir):
    with freezegun.freeze_time('2011-07-05 08:37:00', tz_offset=0):
        request = Request(
            0, 1, path=str(tmpdir),
            starttime=datetime.datetime(2011, 7, 5, 8, 38, tzinfo=pytz.utc))
        request.save()
        assert request.state == Request.PENDING


def test_state_due(tmpdir):
    with freezegun.freeze_time('2011-07-05 08:37:00', tz_offset=0):
        request = Request(
            0, 1, path=str(tmpdir),
            starttime=datetime.datetime(2011, 7, 5, 8, 37, tzinfo=pytz.utc))
        request.save()
        assert request.state == Request.DUE


def test_state_running(tmpdir):
    request = Request(0, 1, path=str(tmpdir))
    request.save()
    with open(str(tmpdir/'started'), 'w') as f:
        print(gocept.net.utils.now(), file=f)
    assert request.state == Request.RUNNING


def test_state_success(tmpdir):
    request = Request(0, 1, script='exit 0', path=str(tmpdir))
    request.save()
    request.execute()
    assert request.state == Request.SUCCESS


def test_state_tempfail(tmpdir):
    request = Request(0, 1, script='exit 75', path=str(tmpdir))
    request.save()
    request.execute()
    assert request.state == Request.TEMPFAIL


def test_state_postpone(tmpdir):
    request = Request(0, 1, script='exit 69', path=str(tmpdir))
    request.save()
    request.execute()
    assert request.state == Request.POSTPONE


def test_state_retrylimit(tmpdir):
    request = Request(0, 1, script='exit 75', path=str(tmpdir))
    request.save()
    with open(os.path.join(request.path, 'attempt'), 'w') as f:
        print(Request.MAX_TRIES, file=f)
    request.execute()
    assert request.state == Request.RETRYLIMIT


def test_state_error(tmpdir):
    request = Request(0, 1, script='exit 1', path=str(tmpdir))
    request.save()
    request.execute()
    assert request.state == Request.ERROR


def test_state_deleted(tmpdir):
    request = Request(0, 1, path=str(tmpdir))
    shutil.rmtree(str(tmpdir))
    assert request.state == Request.DELETED


def test_estimate_should_be_positive():
    with pytest.raises(RuntimeError):
        Request(0, 0)


def test_started(tmpdir):
    with freezegun.freeze_time('2011-07-26 09:25:00', tz_offset=0):
        request = Request(0, 1, path=str(tmpdir))
        request.start()
        with open(os.path.join(request.path, 'started'), 'w') as f:
            print('2011-07-26T09:25:00+00:00\n', file=f)
        assert request.started == datetime.datetime(
            2011, 7, 26, 9, 25, tzinfo=pytz.utc)


def test_stopped(tmpdir):
    with freezegun.freeze_time('2011-07-26 09:26:00', tz_offset=0):
        request = Request(0, 1, path=str(tmpdir))
        request.stop()
        with open(os.path.join(request.path, 'stopped'), 'w') as f:
            print('2011-07-26T09:26:00+00:00\n', file=f)
        assert request.stopped == datetime.datetime(
            2011, 7, 26, 9, 26, tzinfo=pytz.utc)


def test_start_should_not_update_existing_startfile(tmpdir):
    with open(str(tmpdir/'started'), 'w') as f:
        print(u'old', file=f)
    req = Request(0, 1, path=str(tmpdir))
    req.execute()
    with open(os.path.join(req.path, 'started')) as f:
        assert u'old\n' == f.read()


def test_reset_started_stopped(tmpdir):
    request = Request(0, 1, path=str(tmpdir))
    request.start()
    assert p.exists(p.join(request.path, 'started')) is True
    request.stop()
    assert p.exists(p.join(request.path, 'stopped')) is True
    request.reset_started_stopped()
    assert p.exists(p.join(request.path, 'started')) is False
    assert p.exists(p.join(request.path, 'stopped')) is False


def test_execution_time_should_return_none_if_not_run(tmpdir):
    request = Request(0, 1, path=str(tmpdir))
    assert request.executiontime is None


def test_execution_time_should_return_executiontime(tmpdir):
    request = Request(0, 1, path=str(tmpdir))
    with open(os.path.join(request.path, 'started'), 'w') as f:
        print('2011-07-26T09:27:00+00:00\n', file=f)
    with open(os.path.join(request.path, 'stopped'), 'w') as f:
        print('2011-07-26T10:55:12+00:00\n', file=f)
    assert request.executiontime == 5292


def test_execute_should_just_record_time_if_no_script(tmpdir):
    with freezegun.freeze_time('2011-07-27 07:35:00', tz_offset=0):
        request = Request(0, 1, path=str(tmpdir))
        request.save()
        request.execute()
        assert request.state == Request.SUCCESS
        assert request.started == datetime.datetime(
            2011, 7, 27, 7, 35, tzinfo=pytz.utc)
        assert request.stopped == datetime.datetime(
            2011, 7, 27, 7, 35, tzinfo=pytz.utc)


def test_execute_should_write_exitcode(tmpdir):
    request = Request(0, 1, script='exit 70', path=str(tmpdir))
    request.execute()
    with open(os.path.join(request.path, 'exitcode')) as f:
        assert f.read() == '70\n'


def test_not_applicable_but_success(tmpdir):
    request = Request(0, 1, script='true', applicable='exit 1',
                      path=str(tmpdir))
    request.save()
    request.execute()
    assert request.state == Request.SUCCESS
    assert request.exitcode == 0


def test_applicable_error(tmpdir):
    request = Request(0, 1, script='true', applicable='exit 2',
                      path=str(tmpdir))
    request.save()
    request.execute()
    assert request.state == Request.ERROR
    assert request.exitcode == 2


def test_applicable_postpone(tmpdir):
    request = Request(0, 1, script='true', applicable='exit 69',
                      path=str(tmpdir))
    request.save()
    request.execute()
    assert request.state == Request.POSTPONE


def test_execute_should_cd_to_requestpath(tmpdir):
    request = Request(0, 1, script='echo foo > localfile', path=str(tmpdir))
    request.execute()
    with open(os.path.join(request.path, 'localfile')) as f:
        assert f.read() == 'foo\n'


def test_execute_should_skip_execution_if_script_not_applicable(tmpdir):
    request = Request(0, 1, script='echo >> did_something', path=str(tmpdir),
                      applicable='/bin/false')
    request.execute()
    assert os.path.exists(
        os.path.join(request.path, 'did_something')) is False


def test_execute_should_write_stdout_stderr(tmpdir):
    request = Request(0, 1, script='echo stdout; echo stderr >&2',
                      path=str(tmpdir))
    request.execute()
    with open(os.path.join(request.path, 'stdout')) as f:
        assert f.read() == 'stdout\n'
    with open(os.path.join(request.path, 'stderr')) as f:
        assert f.read() == 'stderr\n'


def test_incr_attempt_should_create_counter_if_none(tmpdir):
    request = Request(0, 1, path=str(tmpdir))
    request.incr_attempt()
    with open(os.path.join(request.path, 'attempt')) as f:
        assert f.read() == '1\n'


def test_attempt_counter(tmpdir):
    request = Request(0, 1, path=str(tmpdir))
    with open(os.path.join(request.path, 'attempt'), 'w') as f:
        print(2, file=f)
    request.incr_attempt()
    assert request.attempt == 3


def test_estimate_readable():
    assert Request(0, 1).estimate_readable == '1s'
    assert Request(0, 61).estimate_readable == '1m 1s'
    assert Request(0, 3600).estimate_readable == '1h'
    assert Request(0, 3661).estimate_readable == '1h 1m 1s'


def test_update_should_del_starttime_if_none(tmpdir):
    r = Request(0, 1, path=str(tmpdir))
    r.starttime = datetime.datetime(2011, 7, 28, 14, 18, tzinfo=pytz.utc)
    r.update(starttime=None)
    assert r.starttime is None


def test_update_should_accept_datetime(tmpdir):
    r = Request(0, 1, path=str(tmpdir))
    r.update(starttime=datetime.datetime(2011, 7, 28, 14, 20,
                                         tzinfo=pytz.utc))
    assert r.starttime == datetime.datetime(
        2011, 7, 28, 14, 20, tzinfo=pytz.utc)


def test_update_should_accept_str(tmpdir):
    r = Request(0, 1, path=str(tmpdir))
    r.update(starttime='2011-07-28T14:22:00+00:00')
    assert r.starttime == datetime.datetime(
        2011, 7, 28, 14, 22, tzinfo=pytz.utc)


def test_uuid_encode(tmpdir):
    r = Request(0, 1, path=str(tmpdir),
                uuid=pyuuid.UUID('f198be2e-b826-11e4-a65e-001fd0a3d7a6'))
    assert 'hQiTKzANzaJ33zRjoSkAzk' == r.uuid


def test_uuid_decode_short(tmpdir):
    r = Request(0, 1, path=str(tmpdir),
                uuid='hQiTKzANzaJ33zRjoSkAzk')
    assert 'hQiTKzANzaJ33zRjoSkAzk' == r.uuid


def test_uuid_decode_long(tmpdir):
    r = Request(0, 1, path=str(tmpdir),
                uuid='f198be2e-b826-11e4-a65e-001fd0a3d7a6')
    assert 'hQiTKzANzaJ33zRjoSkAzk' == r.uuid
