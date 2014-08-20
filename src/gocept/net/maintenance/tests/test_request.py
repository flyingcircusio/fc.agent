# Copyright (c) gocept gmbh & co. kg
# See also LICENSE.txt

from __future__ import print_function
from gocept.net.maintenance import Request

import datetime
import gocept.net.utils
import mock
import os
import os.path
import pytz
import shutil
import StringIO
import tempfile
import unittest
import uuid


class RequestTest(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='reqtest')

    def tearDown(self):
        try:
            shutil.rmtree(self.dir)
        except OSError:
            pass

    def test_deserialize(self):
        io = StringIO.StringIO("""\
{
  "comment": "user notice",
  "reqid": 16,
  "estimate": 950,
  "starttime": "2011-07-25T16:09:41+00:00",
  "script": "echo",
  "applicable": "true",
  "_uuid": "2345fa72-7f9f-42c2-aa33-6eaf5d891e29"
}
""")
        self.assertEqual(
            Request.deserialize(io), Request(
                16, 950, 'echo', 'user notice',
                datetime.datetime(2011, 7, 25, 16, 9, 41, tzinfo=pytz.UTC),
                'true',
                _uuid=uuid.UUID('2345fa72-7f9f-42c2-aa33-6eaf5d891e29')))

    def test_serialize(self):
        io = StringIO.StringIO()
        request = Request(
            51, 900, '/bin/true', 'do something',
            datetime.datetime(2011, 7, 25, 3, 5, tzinfo=pytz.UTC),
            'check_something', _uuid='0ae23c8f-46e0-11e3-8000-000000000000')
        request.serialize(io)
        self.assertMultiLineEqual(io.getvalue(), """\
{
  "comment": "do something", 
  "script": "/bin/true", 
  "_uuid": "0ae23c8f-46e0-11e3-8000-000000000000", 
  "applicable": "check_something", 
  "reqid": 51, 
  "starttime": "2011-07-25T03:05:00+00:00", 
  "estimate": 900
}
""")

    def test_save(self):
        path = os.path.join(self.dir, '19')
        r = Request(19, 980, path=path)
        r.save()
        self.assertTrue(os.path.exists(os.path.join(path, 'data')),
                        u'Request.save did not create data file')

    def test_eq(self):
        stub_uuid = uuid.UUID('11afa30a-46de-11e3-8000-000000000000')
        self.assertEqual(Request(11, 39, _uuid=stub_uuid),
                         Request(11, 39, _uuid=stub_uuid))
        self.assertNotEqual(Request(11, 39, _uuid=stub_uuid),
                            Request(12, 39, _uuid=stub_uuid))

    def test_repr_rpc(self):
        request = Request(66, 160, 'script', 'a comment')
        self.assertDictEqual(request.repr_rpc, {
            'estimate': 160, 'comment': 'a comment'})

    def test_state_should_tolerate_empty_exitcode_file(self):
        request = Request(0, 1, path=self.dir)
        request.save()
        with open(os.path.join(self.dir, 'exitcode'), 'w') as f:
            print('', file=f)
        self.assertIsNone(request.exitcode)
        self.assertEqual(request.state, Request.PENDING)

    def test_exitcode_should_read_last_line(self):
        request = Request(0, 1, path=self.dir)
        request.save()
        with open(os.path.join(self.dir, 'exitcode'), 'w') as f:
            print('0\n2', file=f)
        self.assertEqual(request.exitcode, 2)

    @mock.patch('gocept.net.utils.now')
    def test_state_pending(self, now):
        now.return_value = datetime.datetime(2011, 7, 5, 8, 37,
                                             tzinfo=pytz.utc)
        request = Request(
            0, 1, path=self.dir,
            starttime=datetime.datetime(2011, 7, 5, 8, 38, tzinfo=pytz.utc))
        request.save()
        self.assertEqual(request.state, Request.PENDING)

    @mock.patch('gocept.net.utils.now')
    def test_state_due(self, now):
        now.return_value = datetime.datetime(2011, 7, 5, 8, 37,
                                             tzinfo=pytz.utc)
        request = Request(
            0, 1, path=self.dir,
            starttime=datetime.datetime(2011, 7, 5, 8, 37, tzinfo=pytz.utc))
        request.save()
        self.assertEqual(request.state, Request.DUE)

    def test_state_running(self):
        request = Request(0, 1, path=self.dir)
        request.save()
        with open(os.path.join(self.dir, 'started'), 'w') as f:
            print(gocept.net.utils.now(), file=f)
        self.assertEqual(request.state, Request.RUNNING)

    def test_state_success(self):
        request = Request(0, 1, script='exit 0', path=self.dir)
        request.save()
        request.execute()
        self.assertEqual(request.state, Request.SUCCESS)

    def test_state_tempfail(self):
        request = Request(0, 1, script='exit 75', path=self.dir)
        request.save()
        request.execute()
        self.assertEqual(request.state, Request.TEMPFAIL)

    def test_state_retrylimit(self):
        request = Request(0, 1, script='exit 75', path=self.dir)
        request.save()
        with open(os.path.join(request.path, 'attempt'), 'w') as f:
            print(Request.MAX_TRIES, file=f)
        request.execute()
        self.assertEqual(request.state, Request.RETRYLIMIT)

    def test_state_error(self):
        request = Request(0, 1, script='exit 1', path=self.dir)
        request.save()
        request.execute()
        self.assertEqual(request.state, Request.ERROR)

    def test_state_deleted(self):
        request = Request(0, 1, path=self.dir)
        shutil.rmtree(self.dir)
        self.assertEqual(request.state, Request.DELETED)

    def test_estimate_should_be_positive(self):
        self.assertRaises(RuntimeError, Request, 0, 0)

    @mock.patch('gocept.net.utils.now')
    def test_started(self, now):
        now.return_value = datetime.datetime(
            2011, 7, 26, 9, 25, tzinfo=pytz.utc)
        request = Request(0, 1, path=self.dir)
        request.start()
        with open(os.path.join(request.path, 'started'), 'w') as f:
            print('2011-07-26T09:25:00+00:00\n', file=f)
        self.assertEqual(request.started, datetime.datetime(
            2011, 7, 26, 9, 25, tzinfo=pytz.utc))

    @mock.patch('gocept.net.utils.now')
    def test_stopped(self, now):
        now.return_value = datetime.datetime(
            2011, 7, 26, 9, 26, tzinfo=pytz.utc)
        request = Request(0, 1, path=self.dir)
        request.stop()
        with open(os.path.join(request.path, 'stopped'), 'w') as f:
            print('2011-07-26T09:26:00+00:00\n', file=f)
        self.assertEqual(request.stopped, datetime.datetime(
            2011, 7, 26, 9, 26, tzinfo=pytz.utc))

    def test_start_should_not_update_existing_startfile(self):
        with open(os.path.join(self.dir, 'started'), 'w') as f:
            print(u'old', file=f)
        req = Request(0, 1, path=self.dir)
        req.execute()
        self.assertEqual(u'old\n',
                         open(os.path.join(req.path, 'started')).read())

    def test_execution_time_should_return_none_if_not_run(self):
        request = Request(0, 1, path=self.dir)
        self.assertIsNone(request.executiontime)

    def test_execution_time_should_return_executiontime(self):
        request = Request(0, 1, path=self.dir)
        with open(os.path.join(request.path, 'started'), 'w') as f:
            print('2011-07-26T09:27:00+00:00\n', file=f)
        with open(os.path.join(request.path, 'stopped'), 'w') as f:
            print('2011-07-26T10:55:12+00:00\n', file=f)
        self.assertEqual(request.executiontime, 5292)

    @mock.patch('gocept.net.utils.now')
    def test_execute_should_just_record_time_if_no_script(self, now):
        now.return_value = datetime.datetime(
            2011, 7, 27, 7, 35, tzinfo=pytz.utc)
        request = Request(0, 1, path=self.dir)
        request.save()
        request.execute()
        self.assertEqual(request.state, Request.SUCCESS)
        self.assertEqual(request.started, datetime.datetime(
            2011, 7, 27, 7, 35, tzinfo=pytz.utc))
        self.assertEqual(request.stopped, datetime.datetime(
            2011, 7, 27, 7, 35, tzinfo=pytz.utc))

    def test_execute_should_write_exitcode(self):
        request = Request(0, 1, script='exit 70', path=self.dir)
        request.execute()
        self.assertTrue(open(os.path.join(request.path, 'exitcode')).read(),
                        '70\n')

    def test_execute_should_write_applicable(self):
        request = Request(0, 1, script='true', applicable='exit 3',
                          path=self.dir)
        request.execute()
        self.assertTrue(open(os.path.join(request.path, 'applicable')).read(),
                        '3\n')

    def test_execute_should_cd_to_requestpath(self):
        request = Request(0, 1, script='echo foo > localfile', path=self.dir)
        request.execute()
        self.assertTrue(open(os.path.join(request.path, 'localfile')).read(),
                        'foo\n')

    def test_execute_should_skip_execution_if_script_not_applicable(self):
        request = Request(0, 1, script='echo >> did_something', path=self.dir,
                          applicable='/bin/false')
        request.execute()
        self.assertFalse(os.path.exists(
            os.path.join(request.path, 'did_something')),
            "found signs of execution but shouldn't")

    @mock.patch('sys.stderr')
    @mock.patch('sys.stdout')
    def test_execute_should_write_stdout_stderr(self, stdout, stderr):
        request = Request(0, 1, script='echo stdout; echo stderr >&2',
                          path=self.dir)
        request.execute()
        self.assertTrue(open(os.path.join(request.path, 'stdout')).read(),
                        'stdout\n')
        self.assertTrue(open(os.path.join(request.path, 'stderr')).read(),
                        'stderr\n')

    def test_incr_attempt_should_create_counter_if_none(self):
        request = Request(0, 1, path=self.dir)
        request.incr_attempt()
        self.assertEqual(open(os.path.join(request.path, 'attempt')).read(),
                         '1\n')

    def test_attempt_counter(self):
        request = Request(0, 1, path=self.dir)
        with open(os.path.join(request.path, 'attempt'), 'w') as f:
            print(2, file=f)
        request.incr_attempt()
        self.assertEqual(request.attempt, 3)

    def test_estimate_readable(self):
        self.assertEqual(Request(0, 1).estimate_readable, '1s')
        self.assertEqual(Request(0, 61).estimate_readable, '1m 1s')
        self.assertEqual(Request(0, 3600).estimate_readable, '1h')
        self.assertEqual(Request(0, 3661).estimate_readable, '1h 1m 1s')

    def test_update_should_del_starttime_if_none(self):
        r = Request(0, 1, path=self.dir)
        r.starttime = datetime.datetime(2011, 7, 28, 14, 18, tzinfo=pytz.utc)
        r.update(starttime=None)
        self.assertIsNone(r.starttime)

    def test_update_should_accept_datetime(self):
        r = Request(0, 1, path=self.dir)
        r.update(starttime=datetime.datetime(2011, 7, 28, 14, 20,
                                             tzinfo=pytz.utc))
        self.assertEqual(r.starttime, datetime.datetime(
            2011, 7, 28, 14, 20, tzinfo=pytz.utc))

    def test_update_should_accept_str(self):
        r = Request(0, 1, path=self.dir)
        r.update(starttime='2011-07-28T14:22:00+00:00')
        self.assertEqual(r.starttime, datetime.datetime(
            2011, 7, 28, 14, 22, tzinfo=pytz.utc))

    def test_shortid(self):
        r = Request(0, 1, path=self.dir,
                    _uuid='8354bbdc-46e1-11e3-8000-000000000000')
        self.assertEqual('8354bbdc', r.shortid)

    def test_uuid(self):
        r = Request(0, 1, path=self.dir,
                    _uuid='8354bbdc-46e1-11e3-8000-000000000000')
        self.assertEqual('8354bbdc-46e1-11e3-8000-000000000000', r.uuid)
