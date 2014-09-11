"""Configure iptables input rules based on gocept.directory information."""

from __future__ import print_function, unicode_literals
from gocept.net.configfile import ConfigFile
from gocept.net.directory import Directory, exceptions_screened
import argparse
import netaddr
import os.path
import subprocess
import sys


class Iptables(object):
    """iptables input rules configuration."""

    RULESFILES = {
        4: '/var/lib/iptables/rules.d/filter/INPUT/40resourcegroup',
        6: '/var/lib/ip6tables/rules.d/filter/INPUT/40resourcegroup'}
    PUPPET_LOCKFILE = '/var/lib/puppet/state/agent_catalog_run.lock'

    def __init__(self, location, rg, iface, vlan):
        """Create Iptables configuration for iface with location and vlan."""
        self.iface = iface
        self.location = location
        self.rg = rg
        self.vlan = vlan
        self.config_changed = self.config_has_changed()

    def config_has_changed(self):
        """Check if config files were changed by a service user"""
        for ipt_cmd in ['iptables', 'ip6tables']:
            last_update = os.path.getmtime('/var/lib/{}/rules'.format(ipt_cmd))
            for chain in ['INPUT', 'OUTPUT', 'FORWARD']:
                try:
                    config = '/var/lib/{}/rules.d/filter/{}/local'.format(
                        ipt_cmd, chain)
                    if last_update < os.path.getmtime(config):
                        return True
                except OSError:
                    continue
        return False

    def rg_addresses(self):
        """Query list of addresses in local vlan+location from directory."""
        d = Directory()
        with exceptions_screened():
            for node in d.list_addresses(self.vlan, self.location):
                if node['rg'] == self.rg:
                    yield netaddr.IPNetwork(node['addr']).ip

    def write_rg_input_rules(self):
        """Put one accept rule per IP address into version-specific config."""
        rulesfiles = {}
        for ipversion, filename in self.RULESFILES.items():
            rulesfiles[ipversion] = ConfigFile(filename)
        for addr in self.rg_addresses():
            rule = '-A INPUT -i {0} -s {1} -j ACCEPT'.format(self.iface, addr)
            print(rule, file=rulesfiles[addr.version])
        for f in rulesfiles.values():
            self.config_changed = f.commit() or self.config_changed

    def feature_enabled(self):
        """Return True if iptables feature is switched on."""
        if os.path.exists('/etc/local/stop-firewall'):
            return False
        with open('/proc/net/dev') as dev:
            netdevs = dev.read()
        # No srv net? Probably bootstrapping still in progress
        return ('ethsrv' in netdevs) or ('brsrv' in netdevs)

    @property
    def empty_iptables(self):
        """Detect if no rules have been loaded before."""
        iptables = subprocess.check_output(['iptables', '-LINPUT', '-n'])
        if len(iptables.strip().split('\n')) <= 3:
            return True
        iptables = subprocess.check_output(['ip6tables', '-LINPUT', '-n'])
        if len(iptables.strip().split('\n')) <= 3:
            return True
        return False

    def reload_iptables(self):
        """Trigger reload of changed iptables rules."""
        if self.config_changed or self.empty_iptables:
            subprocess.check_call(['update-iptables'])

    def puppet_catalog_run(self):
        try:
            with open(self.PUPPET_LOCKFILE, 'r') as f:
                pid = int(f.read())
        except (IOError, OSError, ValueError):
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True

    def run(self):
        self.write_rg_input_rules()
        self.reload_iptables()


def inputrules():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('location', metavar='LOCATION',
                   help='short location identifier (e.g., rzob)')
    p.add_argument('rg', metavar='RESOURCE_GROUP',
                   help='resource group this node belongs to')
    p.add_argument('iface', metavar='IFACE',
                   help='interface name')
    p.add_argument('vlan', metavar='VLAN',
                   help='short vlan identifier (e.g., srv)')
    args = p.parse_args()
    iptables = Iptables(args.location, args.rg, args.iface, args.vlan)
    if not iptables.feature_enabled():
        return
    if iptables.puppet_catalog_run():
        print('iptables: puppet agent catalog run in progress, skipping')
        return
    iptables.run()
