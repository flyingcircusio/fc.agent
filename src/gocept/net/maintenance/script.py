"""Console scripts for maintenance handling."""

import gocept.net.maintenance
import logging
import logging.handlers
import optparse
import sys


def parse_estimate(estimate):
    """Converts suffixed time string into seconds."""
    if estimate.endswith('s'):
        return int(estimate[:-1])
    elif estimate.endswith('m'):
        return int(estimate[:-1]) * 60
    elif estimate.endswith('h'):
        return int(estimate[:-1]) * 60 * 60
    else:
        return int(float(estimate))


def request():
    """Post a new maintenance request to spooldir."""
    o = optparse.OptionParser(
        usage=u'[OPTIONS] ESTIMATE',
        description=u'Post new scheduled maintenance request for ESTIMATE in '
        u'spool directory. ESTIMATE may have the suffixes s, m, or h.',
        epilog=u"""\
The activity may exit with status 75 (TEMPFAIL) to indicate that the execution
of the maintenance script should be suspended. If the activity exits with
status 69 (UNAVAILABLE), it will be postponed by its duration estimate and then
tried again. Other exit codes except 0 indicate hard failure.

Likewise, the applicable script(s) may return with status codes with the same
meaning to signal that the machine is currently not ready to run the
maintenance action.
        """)
    default_options(o)
    o.add_option('-c', '--comment', default='',
                 help=u'notify users with COMMENT about upcoming maintenance')
    o.add_option('-s', '--script', default='',
                 help=u'execute SCRIPT during maintenance period')
    o.add_option('-i', '--stdin', default=False, action='store_true',
                 help=u'read SCRIPT from stdin (mutually exclusive with -s)')
    o.add_option('-a', '--applicable', default='', metavar='SCRIPT/DIR',
                 help=u'decide if maintenance activity is still applicable '
                      u'by running SCRIPT or all executable snippets in DIR')
    opts, args = o.parse_args()
    if len(args) != 1:
        o.error('need ESTIMATE (invoke with "--help" to get help)')
    if opts.script and opts.stdin:
        o.error('--script and --stdin are mutually exclusive')
    estimate = parse_estimate(args[0])
    if not estimate > 0:
        o.error('estimate must be positive')
    setup_logging(opts.verbose)
    if opts.stdin:
        script = sys.stdin.read()
    else:
        script = opts.script
    with gocept.net.maintenance.ReqManager(opts.spooldir) as sd:
        sd.add_request(estimate, script, opts.comment, opts.applicable)


def schedule():
    """Schedule maintenance requests and execute them when due."""
    o = optparse.OptionParser(
        usage=u'[OPTIONS]',
        description=u"""\
Execute scheduled maintenance. Each pending maintenance request is scheduled
and executed if due. Finished requests are archived.""")
    default_options(o)
    opts, args = o.parse_args()
    if len(args):
        o.error('superfluous arguments (invoke with "--help" to get help)')
    setup_logging(opts.verbose)
    with gocept.net.maintenance.ReqManager(opts.spooldir) as rm:
        with gocept.net.directory.exceptions_screened():
            rm.update_schedule()


def run():
    """Schedule maintenance requests and execute them when due."""
    o = optparse.OptionParser(
        usage=u'[OPTIONS]',
        description=u"""\
Execute scheduled maintenance. Each pending maintenance request is scheduled
and executed if due. Finished requests are archived.""")
    default_options(o)
    opts, args = o.parse_args()
    if len(args):
        o.error('superfluous arguments (invoke with "--help" to get help)')
    setup_logging(opts.verbose)
    with gocept.net.maintenance.ReqManager(opts.spooldir) as rm:
        rm.execute_requests()
        with gocept.net.directory.exceptions_screened():
            rm.postpone_requests()
            rm.archive_requests()


def list():
    """Print human-readable listing of active maintenance requests."""
    o = optparse.OptionParser(
        usage=u'[OPTIONS]',
        description=u"""\
Print all current maintenance activities.
""")
    default_options(o)
    o.add_option('-q', '--quiet', action='store_true', default=False,
                 help=u'no output; signal pending requests with exit code 1')
    opts, args = o.parse_args()
    setup_logging(opts.verbose)
    if len(args):
        o.error('superfluous arguments (invoke with "--help" to get help)')
    with gocept.net.maintenance.ReqManager(opts.spooldir) as rm:
        if opts.quiet:
            if len(rm.requests()):
                sys.exit(1)
        else:
            sys.stdout.write(str(rm))


def setup_logging(verbosity=0):
    """Configure logging to log to both stdout and syslog.

    `verbosity` controls the level of detail on the stdout logger. All messages
    are forwarded to syslog nevertheless.
    """
    stderr = logging.StreamHandler(sys.stderr)
    if verbosity > 1:
        stderr.setLevel(logging.DEBUG)
    elif verbosity > 0:
        stderr.setLevel(logging.INFO)
    else:
        stderr.setLevel(logging.WARNING)
    stderr.setFormatter(logging.Formatter(
        '%(name)s: %(message)s',
        gocept.net.maintenance.ReqManager.TIMEFMT))
    syslog = logging.handlers.SysLogHandler(
        facility=logging.handlers.SysLogHandler.LOG_LOCAL4)
    syslog.setLevel(logging.DEBUG)
    processname = sys.argv[0].rsplit('/', 1)[-1]
    syslog.setFormatter(logging.Formatter(
        '{0}[%(process)d]: %(message)s'.format(processname)))
    root = logging.getLogger('.'.join(__name__.split('.')[0:2]))
    root.setLevel(logging.DEBUG)
    root.addHandler(stderr)
    root.addHandler(syslog)


def default_options(parser):
    """Configure commonly used command line options."""
    parser.add_option('-v', '--verbose', dest='verbose', default=0,
                      action='count',
                      help=u'provide more verbose output (repeat for debug '
                      u'output)')
    parser.add_option('-d', '--directory', dest='spooldir',
                      default=gocept.net.maintenance.ReqManager.DEFAULT_DIR,
                      help=u'use alternative spool directory (default: '
                      u'%default)')
