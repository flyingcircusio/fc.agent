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

    def __init__(self, nagios_path, grace_period):
        self.vm_bootstraps_failed = []
        self.nagios_path = nagios_path
        self.grace_period = grace_period  # in minutes

    def nodes_directory_knows(self):
        """Returns a list of VMs that should be running in the current location
        according to the Directory (service status: "in service").
        """

        """
        Todo:
            * Retrive nodes from directory that fullfil the following criteria:
                * location: same as VM that this check is running on
                * resource group: *
                * profile: generic
                * environment: *
                * service status: in service
                * creation date: <= "now" minus grace_period (see check args)
        What is listed below is just a test. We actually use Nagios' list and
        add a VM to it to trigger the check.
        """
        directory = gocept.net.directory.Directory()
        this_node = directory.lookup_node(socket.gethostname())
        nodes = directory.list_nodes(this_node['parameters']['location'])
        reference_date = (datetime.datetime.now(iso8601.UTC)
                          - datetime.timedelta(minutes=self.grace_period))
        nodes_directory_knows = [
            node['name'] for node in nodes
            if node['parameters']['servicing']
            if node['parameters'].get('online', True)
            if node['parameters']['profile'] == 'generic'
            if (iso8601.parse_date(node['parameters']['creation_date'])
                < reference_date)]

        nodes_directory_knows.sort()
        # XXX There are nodes which are not managed by puppet. Thus they don't
        # appear in Nagios. But in directory.
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

        nodes_directory_knows = self.nodes_directory_knows()
        nodes_nagios_knows = self.nodes_nagios_knows()

        for vm_probe in nodes_directory_knows:
            if vm_probe not in nodes_nagios_knows:
                log.info('%s failed to bootstrap.', vm_probe)
                self.vm_bootstraps_failed.append(vm_probe)

        self.vm_bootstraps_failed.sort()

        return [nagiosplugin.Metric('vm_bootstraps_failed',
                                    len(self.vm_bootstraps_failed), min=0,
                                    context='vmbootstrap')]


class VMBootstrapSummary(nagiosplugin.Summary):

    def ok(self, results):
        return 'All VMs have been bootstrapped.'

    def problem(self, results):
        resource = results.first_significant.resource
        return 'Failed VM bootstraps: {}'.format(
            ' '.join(resource.vm_bootstraps_failed))


@nagiosplugin.guarded
def check_vm_bootstrap():
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
