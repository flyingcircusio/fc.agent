"""Configure iptables input rules based on gocept.directory information."""

from __future__ import print_function, unicode_literals
from gocept.net.configfile import ConfigFile
from gocept.net.directory import Directory, exceptions_screened
import argparse
import netaddr
import os.path
import subprocess


class Iptables(object):
    """iptables input rules configuration."""

    INPUT = {
        4: '/var/lib/iptables/rules.d/filter/INPUT/40resourcegroup',
        6: '/var/lib/ip6tables/rules.d/filter/INPUT/40resourcegroup'}

    OUTPUT = {
        4: '/var/lib/iptables/rules.d/filter/OUTPUT/40resourcegroup',
        6: '/var/lib/ip6tables/rules.d/filter/OUTPUT/40resourcegroup'}

    def __init__(self, location, rg, iface, vlan):
        """Create Iptables configuration for iface with location and vlan."""
        self.iface = iface
        self.location = location
        self.rg = rg
        self.vlan = vlan

    def rg_addresses(self):
        """Query list of addresses in local vlan+location from directory."""
        d = Directory()
        with exceptions_screened():
            for node in d.list_addresses(self.vlan, self.location):
                if node['rg'] == self.rg:
                    yield netaddr.IPNetwork(node['addr']).ip

    def write_rg_input_rules(self, addrs):
        """Put one accept rule per IP address into version-specific config."""
        rulesfiles = {}
        for ipversion, filename in self.INPUT.items():
            rulesfiles[ipversion] = ConfigFile(filename)
        for addr in addrs:
            rule = '-A INPUT -i {0} -s {1} -j ACCEPT'.format(self.iface, addr)
            print(rule, file=rulesfiles[addr.version])
        for f in rulesfiles.values():
            f.commit()

    def write_rg_output_rules(self, addrs):
        """Put one accept rule per IP address into version-specific config."""
        rulesfiles = {}
        for ipversion, filename in self.OUTPUT.items():
            rulesfiles[ipversion] = ConfigFile(filename)
        for addr in addrs:
            rule = '-A OUTPUT -o {0} -d {1} -j ACCEPT'.format(self.iface, addr)
            print(rule, file=rulesfiles[addr.version])
        for f in rulesfiles.values():
            f.commit()

    def feature_enabled(self):
        """Return True if iptables feature is switched on."""
        if os.path.exists('/etc/local/stop-firewall'):
            return False
        with open('/proc/net/dev') as dev:
            netdevs = dev.read()
        # No srv net? Probably bootstrapping still in progress
        return ('ethsrv' in netdevs) or ('brsrv' in netdevs)

    def reload_iptables(self):
        """Trigger reload of changed iptables rules."""
        subprocess.check_call(['/usr/local/sbin/update-iptables'])

    def run(self):
        addrs = list(self.rg_addresses())
        self.write_rg_input_rules(addrs)
        self.write_rg_output_rules(addrs)
        self.reload_iptables()


def rules():
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
    iptables.run()
