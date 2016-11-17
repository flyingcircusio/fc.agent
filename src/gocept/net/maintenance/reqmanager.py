"""Manage maintenance requests spool directories."""

from __future__ import print_function

import calendar
import fcntl
import glob
import gocept.net.directory
import gocept.net.maintenance
import logging
import os
import StringIO
import subprocess
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
        if self.directory is None:
            self.directory = gocept.net.directory.Directory()
        return func(self, *args, **kwargs)
    return with_directory_connection


def spawn(command):
    """Run shell script in current request's context."""
    LOG.debug('running %s', command)
    p = subprocess.Popen([command], stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)
    p.wait()
    prefix = os.path.basename(command)
    stdout = p.stdout.read()
    for l in stdout.splitlines():
        LOG.info('%s (stdout): %s', prefix, l.strip())
    stderr = p.stderr.read()
    for l in stderr.splitlines():
        LOG.info('%s (stderr): %s', prefix, l.strip())
    LOG.debug('returncode: %s', p.returncode)
    return p.returncode


def run_snippets(snippet_directory):
    """Run all executables in a dir and return the maximum exit code."""
    if not os.path.isdir(snippet_directory):
        raise RuntimeError('Snippet directory {} not found.'.format(dir))
    returncodes = [0]
    for snippet in sorted(
            glob.glob(os.path.join(snippet_directory, '*'))):
        if not os.access(snippet, os.X_OK):
            continue
        # Not short-circuiting this to support convergence
        returncodes.append(spawn(snippet))
    if max(returncodes) != 0:
        raise RuntimeError('Snippets directory {} overall status {}'.format(
            snippet_directory, max(returncodes)))


class ReqManager(object):
    """Container for Requests."""

    DEFAULT_DIR = '/var/spool/maintenance'

    PREPARE_SCRIPTS = '/usr/local/lib/maintenance/prepare'
    FINISH_SCRIPTS = '/usr/local/lib/maintenance/finish'

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
                req.uuid[0:8], starttime, req.estimate_readable, req.state),
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
            f.seek(0)  # On OS X a+ starts at the end of the file.
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
                    applicable=None, uuid=None):
        """Create new request object and save it to disk.

        If a request with exactly the same comment already exists in the
        current list of request (not the archive) then do not create an
        additional request, but update the parameters.

        The Request instance is initialized with the passed arguments and a
        newly allocated reqid. Return the new Request instance.
        """
        reqid = self._allocate_id()
        for request in self.requests().values():
            if comment is None:
                continue
            if request.comment != comment:
                continue
            LOG.info('updating existing maintenance request %s', request.uuid)
            request.estimate = estimate
            request.script = script
            request.applicable = applicable
            break
        else:
            request = gocept.net.maintenance.Request(
                reqid, estimate, script, comment,
                applicable=applicable, path=self._path(reqid), uuid=uuid)
            LOG.info('creating new maintenance request %s', request.uuid)
        request.save()

        if not request.script:
            LOG.warning("(req %s) empty script -- hope that's ok",
                        request.uuid)
        LOG.debug('(req %s) saving to %s', request.uuid, request.path)
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
        for _time, request in sorted(tempfail):
            yield request
        for _time, request in sorted(due):
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
                LOG.debug('(req %s) updating request', req.uuid)
                if req.update(val['time']):
                    LOG.info('(req %s) changing start time to %s',
                             req.uuid, val['time'])
            except KeyError:
                LOG.warning('(req %s) request disappeared, marking as deleted',
                            req.uuid)
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
        requests = list(self.runnable_requests())
        if requests:
            try:
                run_snippets(self.PREPARE_SCRIPTS)
            except RuntimeError as e:
                LOG.warning('prepare scripts returned unsuccessfully, '
                            'not performing maintenance.')
                LOG.debug('exception: %s', e)
                return

        # If we have requests, run the finish scripts. This may be toggled
        # in case we encounter an error.
        for request in requests:
            LOG.debug('next request is %s, starttime: %s',
                      request.uuid, request.starttime)
            request.execute()
            state = request.state
            if state is gocept.net.maintenance.Request.TEMPFAIL:
                LOG.info('(req %s) returned TEMPFAIL, suspending',
                         request.uuid)
                break  # skips 'else' clause
            if state in (gocept.net.maintenance.Request.ERROR,
                         gocept.net.maintenance.Request.RETRYLIMIT):
                LOG.warning('(req %s) returned %s',
                            request.uuid, state.upper())
        else:
            # All requests have been finished successfully.
            try:
                run_snippets(self.FINISH_SCRIPTS)
            except RuntimeError as e:
                LOG.warning('finish scripts returned unsuccessfully.')
                LOG.debug('exception: %s', e)
                return

    @require_lock
    @require_directory
    def postpone_requests(self):
        """Instructs directory to postpone requests.

        Postponed requests get their new scheduled time with the next
        schedule call.
        """
        requests = []
        for req in self.requests().values():
            if req.state is gocept.net.maintenance.Request.POSTPONE:
                requests.append(req)
        if not requests:
            return
        postpone = dict((req.uuid, {'postpone_by': req.estimate})
                        for req in requests)
        LOG.debug('invoking postpone_maintenance(%r)', postpone)
        self.directory.postpone_maintenance(postpone)
        for req in requests:
            req.reset_started_stopped()
            req.update(starttime=None)

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
            LOG.info('(req %s) completed, archiving request', request.uuid)
            os.rename(os.path.join(self.requestsdir, str(reqid)),
                      os.path.join(self.archivedir, str(reqid)))
