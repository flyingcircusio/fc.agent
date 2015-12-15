import argparse
import datetime
import gocept.net.directory
import iso8601
import logging
import nagiosplugin
import os
import socket


log = logging.getLogger('nagiosplugin')


class VMBootstrap(nagiosplugin.Resource):

    MONITORED_PROFILES = (
        'backup',
        'generic',
        'kvm',
        'storage',
        'switch',
        'router',
    )

    def __init__(self, nagios_path, grace_period):
        self.nodes_only_known_to_directory = []
        self.nodes_only_known_to_nagios = []
        self.nagios_path = nagios_path
        self.grace_period = grace_period  # in minutes

    def nodes_directory_knows(self):
        """Returns a list of VMs that should be running in the current location
        according to the Directory (service status: "in service").
        """
        directory = gocept.net.directory.Directory()
        this_node = directory.lookup_node(socket.gethostname())
        nodes = directory.list_nodes(this_node['parameters']['location'])
        reference_date = (datetime.datetime.now(iso8601.iso8601.UTC)
                          - datetime.timedelta(minutes=self.grace_period))
        nodes_directory_knows = [
            node['name'] for node in nodes
            if node['parameters']['servicing']
            if node['parameters'].get('online', True)
            if node['parameters']['profile'] in self.MONITORED_PROFILES
            if (iso8601.parse_date(node['parameters']['creation_date'])
                < reference_date)]

        nodes_directory_knows.sort()
        log.debug('VMs that Directory knows: %s',
                  ' '.join(nodes_directory_knows))
        return nodes_directory_knows

    def nodes_nagios_knows(self):
        """Returns a list of VMs that the Nagios installation on the current
        host knows (directory /etc/nagios/hosts/<vm> exists).
        """
        nodes_nagios_knows = next(os.walk(self.nagios_path))[1]

        log.debug('VMs that Nagios knows: %s',
                  ' '.join(nodes_nagios_knows))

        return nodes_nagios_knows

    def probe(self):
        """Compare VMs lists from Directory and Nagios and return all VMs that
        are present in Directory but not in Nagios.
        """

        nodes_directory_knows = set(self.nodes_directory_knows())
        nodes_nagios_knows = set(self.nodes_nagios_knows())

        self.nodes_only_known_to_directory = sorted(
            nodes_directory_knows - nodes_nagios_knows)
        self. nodes_only_known_to_nagios = sorted(
            nodes_nagios_knows - nodes_directory_knows)

        return [
            nagiosplugin.Metric(
                'nodes_only_known_to_directory',
                len(self.nodes_only_known_to_directory), min=0,
                context='vmbootstrap'),
            nagiosplugin.Metric(
                'nodes_only_known_to_nagios',
                len(self.nodes_only_known_to_nagios), min=0,
                context='vmbootstrap')]


class VMBootstrapSummary(nagiosplugin.Summary):

    def ok(self, results):
        return 'Directory and Nagios are in sync.'

    def problem(self, results):
        resource = results.first_significant.resource
        return ('Directory and Nagios are out of sync: Nagios>{}; Directory>{}'
                .format(
                    ' '.join(resource.nodes_only_known_to_nagios),
                    ' '.join(resource.nodes_only_known_to_directory)))


@nagiosplugin.guarded
def check_nagios_directory_sync():
    """Check that all virtual machines listed in our CMDB (the Directory) are
    present in Nagios. This is done to verify correct VM bootstrap behavior."""

    argp = argparse.ArgumentParser(description=__doc__)
    argp.add_argument('-p', '--nagios-path', default='/etc/nagios/hosts',
                      help='The path to the Nagios hosts directory. '
                      '(default: %(default)s)')
    argp.add_argument('-g', '--grace-period', default='1440',
                      help='The grace period until a VM\'s bootstrap is'
                      ' considered incomplete, in minutes.'
                      ' (default: %(default)s)',
                      type=int)
    argp.add_argument('-w', '--warning', metavar='RANGE', default='0',
                      help='The warning threshold for the number of VMs not '
                      'having been bootstrapped.')
    argp.add_argument('-c', '--critical', metavar='RANGE', default='0',
                      help='The critical threshold for the number of VMs not '
                      'having been bootstrapped.')
    argp.add_argument('-v', '--verbose', action='count', default=0,
                      help='increase output verbosity (use up to 3 times)')
    argp.add_argument('-t', '--timeout', default=30,
                      help='check execution timeout (default: %(default)s)')
    args = argp.parse_args()
    check = nagiosplugin.Check(
        VMBootstrap(args.nagios_path, args.grace_period),
        nagiosplugin.ScalarContext('vmbootstrap', args.warning, args.critical),
        VMBootstrapSummary())
    check.main(verbose=args.verbose, timeout=args.timeout)
