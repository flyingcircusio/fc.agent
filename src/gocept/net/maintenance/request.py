# Copyright (c) gocept gmbh & co. kg
# See also LICENSE.txt

"""Scheduled maintenance requests and actions."""

from __future__ import print_function

import datetime
import gocept.net.utils
import iso8601
import json
import logging
import os
import subprocess
import uuid

LOG = logging.getLogger(__name__)


class Request(object):
    """Represents a single scheduled maintenance request.

    Requests consist mainly of a time estimate, user comment and actions.
    Requests have different states depending on the progress of their
    execution.

    PENDING requests either do not have a scheduled execution date or one in
    the future.
    DUE requests are ready for execution.
    RUNNING requests are currently in execution.
    SUCCESS requests have been successfully executed.
    TEMPFAIL requests have been executed, but need to be executed again on the
    next invokation of the maintenance request runner.
    RETRYLIMIT request have returned TEMPFAIL too often.
    ERROR requests have been executed but failed.
    DELETED requests have been manually deleted.

    Each Requests has an own directory (Request.path) that may contain the
    following files:
        data - JSON dump of request metadata. Modified by the scheduler.
        started - ISO timestamp when Request execution has been started.
        stopped - ISO timestamp when Request execution has been stopped.
        exitcode - script return code. If empty or non-existent, successfull
            script execution is assumed.
        stdout - capture standard output of script execution
        stderr - capture standard error of script execution
        attempt - increasing run number
    """

    MAX_TRIES = 48

    PENDING = 'pending'
    DUE = 'due'
    RUNNING = 'running'
    SUCCESS = 'success'
    TEMPFAIL = 'tempfail'
    RETRYLIMIT = 'too many retries'
    ERROR = 'error'
    DELETED = 'deleted'

    @classmethod
    def deserialize(cls, stream):
        """Construct new Request instance from JSON dump in `stream`."""
        data = json.load(stream)
        if 'starttime' in data:
            data['starttime'] = iso8601.parse_date(data['starttime'])
        return cls(**data)

    def __init__(self, reqid, estimate, script=None, comment=None,
                 starttime=None, applicable=None, path=None, _uuid=None):
        """Create Request.

        `reqid` - numerical request id
        `estimate` - execution time estimate in seconds
        `script` - command that is to be executed via sh
        `comment` - reason for downtime, used to inform users
        `starttime` - scheduled start time
        `applicable` - script to test is the script is applicable
        `path` - path name to request's base directory
        `uuid` - unique ID to identify request with the directory
        """
        if not estimate > 0:
            raise RuntimeError('estimate must be positive', estimate)
        self.reqid = reqid
        self.estimate = estimate
        self.script = script
        self.comment = comment
        self.starttime = starttime
        self.applicable = applicable
        self.path = path
        if _uuid:
            self._uuid = uuid.UUID(str(_uuid))
        else:
            self._uuid = uuid.uuid1()

    def __eq__(self, other):
        if not isinstance(other, Request):
            return False
        return self.__dict__ == other.__dict__

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        """Request data as Python syntax."""
        return '{0}({1})'.format(self.__class__.__name__, ', '.join(
            ['{0}={1!r}'.format(k, v) for k, v in self.__dict__.items()
             if v is not None]))

    def serialize(self, stream):
        """Serialize as JSON data structure into `stream`."""
        data = {
            'reqid': self.reqid,
            'estimate': self.estimate,
            'script': self.script,
            'comment': self.comment,
            'applicable': self.applicable,
            '_uuid': str(self._uuid)
        }
        if self.starttime:
            data['starttime'] = self.starttime.isoformat()
        json.dump(data, stream, indent=2)
        print('', file=stream)

    def save(self):
        if not self.path:
            raise RuntimeError('need path set to save request')
        if not os.path.isdir(self.path):
            os.mkdir(self.path)
        with open(os.path.join(self.path, 'data'), 'w') as f:
            self.serialize(f)
            f.flush()
            os.fsync(f)

    def start(self):
        """Mark Request execution as started."""
        started = os.path.join(self.path, 'started')
        if not os.path.exists(started):
            with open(started, 'w') as f:
                print(gocept.net.utils.now().isoformat(), file=f)

    def stop(self):
        """Mark Request execution as stopped."""
        with open(os.path.join(self.path, 'stopped'), 'w') as f:
            print(gocept.net.utils.now().isoformat(), file=f)

    def spawn(self, command):
        """Run shell script in current request's context."""
        LOG.debug('(req %s) running %r' % (self.shortid, command))
        p = subprocess.Popen([command], shell=True,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             stdin=subprocess.PIPE, cwd=self.path,
                             close_fds=True)
        stdout, stderr = p.communicate()
        with open(os.path.join(self.path, 'stdout'), 'a') as f_stdout:
            f_stdout.write(stdout)
        with open(os.path.join(self.path, 'stderr'), 'a') as f_stderr:
            f_stderr.write(stderr)
            LOG.debug('(req %s) returncode: %s' % (self.shortid, p.returncode))
        return p.returncode

    def is_applicable(self):
        """Test this activity's applicability."""
        if not self.applicable:
            return True
        LOG.debug('(req %s) testing if activity is applicable' % self.shortid)
        exitcode = self.spawn(self.applicable)
        with open(os.path.join(self.path, 'applicable'), 'a') as f:
            print(exitcode, file=f)
        if exitcode != 0:
            LOG.info('(req %s) not applicable, terminating activity',
                     self.shortid)
            return False
        return True

    def execute(self):
        """Run the script in a subshell.

        Run the `applicable` script first if there is one. If it fails,
        consider the maintenance activity as non-applicable and archive
        the script immediately.
        """
        LOG.info('(req %s) starting execution', self.shortid)
        self.start()
        self.incr_attempt()
        if self.script and self.is_applicable():
            exitcode = self.spawn(self.script)
        else:
            exitcode = 0
        with open(os.path.join(self.path, 'exitcode'), 'a') as f:
            print(exitcode, file=f)
        if exitcode != 0:
            LOG.warning('(req %s) script exited with %i', self.shortid,
                        exitcode)
        self.stop()

    def update(self, starttime=None):
        old = self.starttime
        if not starttime:
            self.starttime = None
        elif isinstance(starttime, datetime.datetime):
            self.starttime = starttime
        else:
            self.starttime = iso8601.parse_date(starttime)
        if self.starttime != old:
            self.save()
            return True
        return False

    def incr_attempt(self):
        """Increment execution attempt counter."""
        i = self.attempt or 0
        with open(os.path.join(self.path, 'attempt'), 'w') as f:
            print(i + 1, file=f)

    @property
    def estimate_readable(self):
        out = []
        remainder = self.estimate
        if remainder >= 60 * 60:
            hours = remainder / 60 / 60
            remainder -= hours * 60 * 60
            out.append('{0}h'.format(hours))
        if remainder >= 60:
            minutes = remainder / 60
            remainder -= minutes * 60
            out.append('{0}m'.format(minutes))
        if remainder:
            out.append('{0}s'.format(remainder))
        return ' '.join(out)

    @property
    def state(self):
        """Current processing state determined from the request directory."""
        if (not os.path.exists(self.path) or
                not os.path.exists(os.path.join(self.path, 'data'))):
            return self.DELETED
        if self.started:
            if self.stopped:
                exitcode = self.exitcode
                if not exitcode:
                    return self.SUCCESS
                if exitcode == 75:
                    if self.attempt > self.MAX_TRIES:
                        return self.RETRYLIMIT
                    else:
                        return self.TEMPFAIL
                return self.ERROR
            else:
                # started but not stopped
                return self.RUNNING
        else:
            # neither started nor stopped
            if self.starttime and gocept.net.utils.now() >= self.starttime:
                return self.DUE
            return self.PENDING

    @property
    def started(self):
        """Return start time as datetime, or None if not started."""
        try:
            with open(os.path.join(self.path, 'started')) as f:
                isotimestamp = f.readline().strip()
                if isotimestamp:
                    return iso8601.parse_date(isotimestamp)
        except EnvironmentError:
            pass

    @property
    def stopped(self):
        """Return stop time as datetime, or None if not stopped."""
        try:
            with open(os.path.join(self.path, 'stopped')) as f:
                isotimestamp = f.readline().strip()
                if isotimestamp:
                    return iso8601.parse_date(isotimestamp)
        except EnvironmentError:
            pass

    @property
    def executiontime(self):
        """Return execution time (s) if started and stopped files exist."""
        try:
            timedelta = self.stopped - self.started
        except TypeError:
            return None
        return timedelta.days * 24 * 60 * 60 + timedelta.seconds

    @property
    def exitcode(self):
        """Return script exit code, or None if the file doesn't exist."""
        try:
            with open(os.path.join(self.path, 'exitcode')) as f:
                return int(f.readlines()[-1].strip())
        except (EnvironmentError, ValueError, IndexError):
            pass

    @property
    def attempt(self):
        """Return attempt counter as int, or None."""
        try:
            with open(os.path.join(self.path, 'attempt')) as f:
                return int(f.readline().strip())
        except (EnvironmentError, ValueError):
            pass

    @property
    def repr_rpc(self):
        """Return dict representation suitable for RPC communication."""
        return {'estimate': self.estimate, 'comment': self.comment}

    @property
    def shortid(self):
        """Short version of the UUID for user display."""
        return str(self._uuid).split('-', 1)[0]

    @property
    def uuid(self):
        return str(self._uuid)
