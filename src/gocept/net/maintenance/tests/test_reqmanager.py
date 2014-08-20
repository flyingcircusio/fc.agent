# Copyright (c) 2011 gocept gmbh & co. kg
# See also LICENSE.txt

from __future__ import print_function
from gocept.net.maintenance import ReqManager, Request

import contextlib
import datetime
import mock
import os
import os.path
import pytz
import shutil
import tempfile
import time
import unittest
import uuid


def tz_utc(func):
    """Decorator to fix $TZ to UTC and restore it afterwards."""
    def fix_tz(*args, **kwargs):
        oldtz = os.environ.get('TZ')
        os.environ['TZ'] = 'UTC'
        time.tzset()
        retval = func(*args, **kwargs)
        if oldtz:
            os.environ['TZ'] = oldtz
        else:
            del os.environ['TZ']
        time.tzset()
        return retval
    return fix_tz


class ReqManagerTest(unittest.TestCase):

    def assertIsDirectory(self, directory):
        self.assert_(os.path.isdir(directory),
                     u"directory '%s' is not present" % directory)

    @contextlib.contextmanager
    def request_population(self, n):
        """Create a ReqManager with a pregenerated population of N requests.

        The ReqManager and a list of Requests are passed to the calling code.
        """
        with ReqManager(self.dir) as reqmanager:
            requests = []
            for i in range(n):
                req = reqmanager.add_request(
                    1, 'exit 0', _uuid=uuid.UUID('{:032d}'.format(i)))
                requests.append(req)
            yield (reqmanager, requests)

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='spooldirtest')

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_init_should_create_directories(self):
        spooldir = os.path.join(self.dir, 'maintenance')
        ReqManager(spooldir)
        self.assertIsDirectory(spooldir),
        self.assertIsDirectory(os.path.join(spooldir, 'requests'))
        self.assertIsDirectory(os.path.join(spooldir, 'archive'))

    def test_should_open_lockfile(self):
        with ReqManager(self.dir) as rm:
            # invoke any method that requires locking
            rm.runnable_requests()
            self.assertFalse(rm.lockfile.closed,
                             'lock file {0!r} is not open'.format(rm.lockfile))

    def test_add_request_should_set_path(self):
        with ReqManager(self.dir) as rm:
            request = rm.add_request(30, 'script', 'comment')
        self.assertEqual(request.path,
                         os.path.join(self.dir, 'requests', '0'))

    @mock.patch('gocept.net.maintenance.Request')
    def test_add_should_init_seq_to_allocate_ids(self, request_cls):
        seqfile = os.path.join(self.dir, '.SEQ')
        request = request_cls.return_value
        request.reqid = None
        with ReqManager(self.dir) as rm:
            rm.add(request)
        self.assertTrue(os.path.isfile(seqfile))
        self.assertEqual('0\n', open(seqfile).read())
        self.assertEqual(0, request.reqid)

    @mock.patch('gocept.net.maintenance.Request')
    def test_add_should_increment_seq(self, request_cls):
        seqfile = os.path.join(self.dir, '.SEQ')
        with open(seqfile, 'w') as f:
            print(7, file=f)
        request = request_cls.return_value
        request.reqid = None
        with ReqManager(self.dir) as rm:
            rm.add(request)
        self.assertEqual('8\n', open(seqfile).read())

    @mock.patch('gocept.net.directory.Directory')
    def test_schedule_emptylist(self, dir_fac):
        directory = dir_fac.return_value
        directory.schedule_maintenance = mock.Mock()
        with ReqManager(self.dir) as rm:
            rm.update_schedule()
        self.assertEqual(directory.schedule_maintenance.call_count, 0)

    @mock.patch('gocept.net.directory.Directory')
    def test_schedule_should_update_request_time(self, dir_fac):
        directory = dir_fac.return_value
        directory.schedule_maintenance = mock.Mock()
        directory.schedule_maintenance.return_value = {
            '00000000-0000-0000-0000-000000000000': {
                'time': '2011-07-25T10:55:28.368789+00:00'},
            '00000000-0000-0000-0000-000000000001': {
                'time': None}}
        with self.request_population(2) as (rm, req):
            rm.update_schedule()
            self.assertEqual(
                rm.load_request(0).starttime,
                datetime.datetime(2011, 7, 25, 10, 55, 28, 368789, pytz.UTC))
            self.assertEqual(rm.load_request(1).starttime, None)
        directory.schedule_maintenance.assert_called_with({
            '00000000-0000-0000-0000-000000000000': {
                'estimate': 1, 'comment': None},
            '00000000-0000-0000-0000-000000000001': {
                'estimate': 1, 'comment': None}})

    @mock.patch('gocept.net.directory.Directory')
    def test_schedule_mark_off_deleted_requests(self, dir_fac):
        directory = dir_fac.return_value
        directory.schedule_maintenance = mock.Mock()
        directory.schedule_maintenance.return_value = {
            '00000000-0000-0000-0000-000000000000': {
                'time': '2011-07-25T10:55:28.368789+00:00'},
            '00000000-0000-0000-0000-000000000001': {'time': None}}
        directory.end_maintenance = mock.Mock()
        with self.request_population(1) as (rm, req):
            rm.update_schedule()
        directory.end_maintenance.assert_called_with({
            '00000000-0000-0000-0000-000000000001': {'result': 'deleted'}})

    def test_load_should_return_request(self):
        with ReqManager(self.dir) as rm:
            req1 = rm.add_request(300, comment='do something')
            req2 = rm.load_request(req1.reqid)
            self.assertEqual(req1, req2)

    def test_current_requests(self):
        self.maxDiff = 2000
        with self.request_population(2) as (rm, req):
            # directory without data file should be skipped
            os.mkdir(os.path.join(self.dir, '5'))
            # non-directory should be skipped
            open(os.path.join(self.dir, '6'), 'w').close()
            self.assertDictEqual(rm.requests(),
                                 {req[0].uuid: req[0], req[1].uuid: req[1]})

    @mock.patch('gocept.net.utils.now')
    def test_runnable_requests(self, now):
        now.return_value = datetime.datetime(
            2011, 7, 26, 19, 40, tzinfo=pytz.utc)
        # req3 is active and should be returned first. req4 has been partially
        # completed and should be resumed directly after. req0 and req1 are
        # due, but req1's starttime is older so it should precede req0's. req2
        # is still pending and should not be returned.
        with self.request_population(5) as (rm, req):
            req[0].starttime = now() - datetime.timedelta(30)
            req[0].save()
            req[1].starttime = now() - datetime.timedelta(45)
            req[1].save()
            req[3].start()
            req[4].script = 'exit 75'
            req[4].save()
            req[4].execute()
            self.assertListEqual(
                list(rm.runnable_requests()), [req[3], req[4], req[1], req[0]])

    @mock.patch('gocept.net.utils.now')
    def test_execute_requests(self, now):
        # Three requests: the first two are marked as due by the directory
        # scheduler. The first runs to completion, but the second exits with
        # TEMPFILE. The first request should be archived and processing should
        # be suspended after the second request. The third request should not
        # be touched.
        now.return_value = datetime.datetime(
            2011, 7, 27, 7, 12, tzinfo=pytz.utc)
        with self.request_population(3) as (rm, req):
            req[0].starttime = datetime.datetime(
                2011, 7, 27, 7, 0, tzinfo=pytz.utc)
            req[0].save()
            req[1].script = 'exit 75'
            req[1].starttime = datetime.datetime(
                2011, 7, 27, 7, 10, tzinfo=pytz.utc)
            req[1].save()
            rm.execute_requests()
        self.assertEqual(req[0].state, Request.SUCCESS)
        self.assertEqual(req[1].state, Request.TEMPFAIL)
        self.assertEqual(req[2].state, Request.PENDING)

    @mock.patch('gocept.net.directory.Directory')
    def test_archive(self, dir_fac):
        directory = dir_fac.return_value
        directory.end_maintenance = mock.Mock()
        with ReqManager(self.dir) as rm:
            request = rm.add_request(
                1, script='exit 0',
                _uuid='f02c4745-46e5-11e3-8000-000000000000')
            request.execute()
            rm.archive_requests()
            self.assertFalse(os.path.exists(os.path.join(rm.requestsdir, '0')),
                             'request 0 should not exist in requestsdir')
            self.assertTrue(os.path.exists(os.path.join(rm.archivedir, '0')),
                            'request 0 should exist in archivedir')
        directory.end_maintenance.assert_called_with({
            'f02c4745-46e5-11e3-8000-000000000000': {
                'duration': 0, 'result': 'success'}})

    @mock.patch('gocept.net.utils.now')
    @tz_utc
    def test_str(self, now):
        now.return_value = datetime.datetime(
            2011, 7, 28, 11, 3, tzinfo=pytz.utc)
        with self.request_population(3) as (rm, req):
            rm.localtime = pytz.utc
            req[0].execute()
            req[1].starttime = datetime.datetime(
                2011, 7, 28, 11, 1, tzinfo=pytz.utc)
            req[1].save()
            req[2].comment = 'reason'
            req[2].save()
            self.assertMultiLineEqual(str(rm), """\
(00000000) scheduled: None, estimate: 1s, state: success

(00000000) scheduled: 2011-07-28 11:01:00 UTC, estimate: 1s, state: due

(00000000) scheduled: None, estimate: 1s, state: pending
reason

""")
