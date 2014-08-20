# Copyright (c) gocept gmbh & co. kg
# See also LICENSE.txt

"""Manage maintenance requests spool directories."""

from __future__ import print_function

import calendar
import fcntl
import gocept.net.directory
import gocept.net.maintenance
import logging
import os
import os.path
import StringIO
import time

LOG = logging.getLogger(__name__)


def require_lock(func):
    """Decorator that asserts an open lockfile prior execution."""
    def guarded(self, *args, **kwargs):
        if not self.lockfile or self.lockfile.closed:
            self.lockfile = open(os.path.join(self.spooldir, '.lock'), 'a')
            fcntl.flock(self.lockfile.fileno(), fcntl.LOCK_EX)
            self.lockfile.seek(0)
            self.lockfile.truncate()
            print(os.getpid(), file=self.lockfile)
        return func(self, *args, **kwargs)
    return guarded


def require_directory(func):
    """Decorator that ensures a directory connection is present."""
    def with_directory_connection(self, *args, **kwargs):
        if not self.directory:
            self.directory = gocept.net.directory.Directory()
        return func(self, *args, **kwargs)
    return with_directory_connection


class ReqManager(object):
    DEFAULT_DIR = '/var/spool/maintenance'
    TIMEFMT = '%Y-%m-%d %H:%M:%S %Z'

    def __init__(self, spooldir=DEFAULT_DIR):
        """Initialize ReqManager and create directories if necessary."""
        self.spooldir = spooldir
        self.requestsdir = os.path.join(self.spooldir, 'requests')
        self.archivedir = os.path.join(self.spooldir, 'archive')
        for d in (self.spooldir, self.requestsdir, self.archivedir):
            if not os.path.exists(d):
                os.mkdir(d)
        self.lockfile = None
        self.directory = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        if self.lockfile and not self.lockfile.closed:
            self.lockfile.close()
        self.lockfile = None

    def __str__(self):
        """Human-readable listing of active maintenance requests."""
        out = StringIO.StringIO()
        for req in self.requests().values():
            try:
                starttime = time.strftime(self.TIMEFMT, time.localtime(
                    calendar.timegm(req.starttime.timetuple())))
            except AttributeError:
                starttime = req.starttime
            print('({0}) scheduled: {1}, estimate: {2}, state: {3}'.format(
                req.shortid, starttime, req.estimate_readable, req.state),
                file=out)
            if req.comment:
                print(req.comment, file=out)
            print(file=out)
        return out.getvalue()

    def _path(self, reqid):
        """Return file system path for request identified by `reqid`."""
        return os.path.realpath(os.path.join(self.requestsdir, str(reqid)))

    def _allocate_id(self):
        """Get a new unique request id using a SEQ file."""
        with open(os.path.join(self.spooldir, '.SEQ'), 'a+') as f:
            fcntl.lockf(f.fileno(), fcntl.LOCK_EX)
            oldseq = f.readline()
            if not oldseq:
                new_id = 0
            else:
                new_id = int(oldseq) + 1
            f.seek(0)
            f.truncate()
            print(new_id, file=f)
        return new_id

    @require_lock
    def add(self, request):
        """Add request to this spooldir and save it to disk."""
        if request.reqid is None:
            request.reqid = self._allocate_id()
        if request.path is None:
            request.path = self._path(request.reqid)
        request.save()

    @require_lock
    def add_request(self, estimate, script=None, comment=None,
                    applicable=None, _uuid=None):
        """Create new request object and save it to disk.

        The Request instance is initialized with the passed arguments and a
        newly allocated reqid. Return the new Request instance.
        """
        reqid = self._allocate_id()
        request = gocept.net.maintenance.Request(
            reqid, estimate, script, comment,
            applicable=applicable, path=self._path(reqid), _uuid=_uuid)
        request.save()
        LOG.info('creating new maintenance request %s', request.uuid)
        if not request.script:
            LOG.warning("(req %s) empty script -- hope that's ok",
                        request.shortid)
        LOG.debug('(req %s) saving to %s', request.shortid, request.path)
        return request

    def load_request(self, reqid):
        with open(os.path.join(self._path(reqid), 'data')) as f:
            request = gocept.net.maintenance.Request.deserialize(f)
            request.path = self._path(reqid)
            return request

    def requests(self):
        """Return dict of all requests in requestsdir."""
        requests = {}
        for candidate in os.listdir(self.requestsdir):
            try:
                reqid = int(candidate)
            except ValueError:
                continue
            try:
                request = self.load_request(reqid)
            except EnvironmentError:
                continue
            requests[request.uuid] = request
        return requests

    @require_lock
    def runnable_requests(self):
        """Generate due Requests in running order."""
        tempfail = []
        due = []
        for request in self.requests().itervalues():
            if request.state is gocept.net.maintenance.Request.RUNNING:
                yield request
            elif request.state is gocept.net.maintenance.Request.TEMPFAIL:
                tempfail.append((request.starttime, request))
            elif request.state is gocept.net.maintenance.Request.DUE:
                due.append((request.starttime, request))
        for time, request in sorted(tempfail):
            yield request
        for time, request in sorted(due):
            yield request

    @require_lock
    @require_directory
    def update_schedule(self):
        """Trigger request scheduling on server."""
        requests = self.requests()
        if not requests:
            return
        activities = self.directory.schedule_maintenance(dict(
            [(req.uuid, req.repr_rpc) for req in requests.values()]))
        deleted_requests = set()
        for key, val in activities.items():
            try:
                req = requests[key]
                LOG.debug('(req %s) updating request', req.shortid)
                if req.update(val['time']):
                    LOG.info('(req %s) changing start time to %s',
                             req.shortid, val['time'])
            except KeyError:
                LOG.warning('(req %s) request disappeared, marking as deleted',
                            req.shortid)
                deleted_requests.add(key)
        if deleted_requests:
            self.directory.end_maintenance(dict(
                (key,
                 {'result': gocept.net.maintenance.Request.DELETED})
                for key in deleted_requests))

    @require_lock
    def execute_requests(self):
        """Process maintenance requests.

        If there is an already active request, run to termination first.
        After that, select the oldest due request as next active request.
        """
        for request in self.runnable_requests():
            LOG.debug('next request is %s, starttime: %s',
                      request.shortid, request.starttime)
            request.execute()
            state = request.state
            if state is gocept.net.maintenance.Request.TEMPFAIL:
                LOG.info('(req %s) returned TEMPFAIL, suspending',
                         request.shortid)
                break
            if state in (gocept.net.maintenance.Request.ERROR,
                         gocept.net.maintenance.Request.RETRYLIMIT):
                LOG.warning('(req %s) returned %s',
                            request.shortid, state.upper())

    @require_lock
    @require_directory
    def archive_requests(self):
        """Move all completed requests to archivedir."""
        archive = {}
        for request in self.requests().values():
            if request.state in (gocept.net.maintenance.Request.SUCCESS,
                                 gocept.net.maintenance.Request.ERROR,
                                 gocept.net.maintenance.Request.RETRYLIMIT,
                                 gocept.net.maintenance.Request.DELETED):
                archive[request.reqid] = request
        if not archive:
            return
        finished = dict((req.uuid, {
            'duration': req.executiontime,
            'result': req.state})
            for req in archive.values())
        LOG.debug('invoking end_maintenance(%r)', finished)
        self.directory.end_maintenance(finished)
        for reqid, request in archive.iteritems():
            LOG.info('(req %s) completed, archiving request', request.shortid)
            os.rename(os.path.join(self.requestsdir, str(reqid)),
                      os.path.join(self.archivedir, str(reqid)))
