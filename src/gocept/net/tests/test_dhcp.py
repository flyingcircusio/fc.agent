# Copyright (c) 2011 gocept gmbh & co. kg
# See also LICENSE.txt

import netaddr
import unittest

from gocept.net.dhcp import Hosts, HostAddr, SharedNetwork


class HostsTest(unittest.TestCase):

    # save typing :)
    mac1 = netaddr.EUI('00:11:43:d7:8a:70', dialect=netaddr.mac_unix)
    mac2 = netaddr.EUI('00:11:43:d7:8a:72', dialect=netaddr.mac_unix)
    mac3 = netaddr.EUI('00:11:43:d7:8a:74', dialect=netaddr.mac_unix)
    ip1 = netaddr.IPNetwork('10.0.1.1/24')
    ip2 = netaddr.IPNetwork('10.0.1.2/24')
    ip3 = netaddr.IPNetwork('10.0.2.1/24')

    def test_add_same_ip_should_fail(self):
        hosts = Hosts()
        hosts.add(HostAddr('h1', 'n1', self.mac1, self.ip1))
        self.assertRaises(
            RuntimeError, hosts.add,
            HostAddr('h2', 'n1', self.mac2, self.ip1))

    def test_add_network_address_should_fail(self):
        with self.assertRaises(RuntimeError):
            Hosts().add(HostAddr(
                'h', 'n', self.mac1, netaddr.IPNetwork('10.0.1.0/24')))

    def test_add_broadcast_address_should_fail(self):
        with self.assertRaises(RuntimeError):
            Hosts().add(HostAddr(
                'h', 'n', self.mac1, netaddr.IPNetwork('10.0.1.127/25')))

    def test_iter_should_group_hosts(self):
        h1a = HostAddr('h1', 'n1', self.mac1, self.ip1)
        h1b = HostAddr('h1', 'n2', self.mac3, self.ip3)
        h2 = HostAddr('h2', 'n1', self.mac2, self.ip2)
        hosts = Hosts().add(h1a).add(h2).add(h1b)
        self.assertListEqual(list(hosts), [[h1a, h1b], [h2]])

    def test_iter_unique_mac_should_filter_repeated_macs_in_same_vlan(self):
        h1a = HostAddr('h1', 'n1', self.mac1, self.ip1)
        h1b = HostAddr('h1', 'n2', self.mac1, self.ip3)
        h2 = HostAddr('h2', 'n1', self.mac1, self.ip2)
        hosts = Hosts().add(h1a).add(h1b).add(h2)
        self.assertListEqual(list(hosts.iter_unique_mac()), [[h1a], []])


class SharedNetworkTest(unittest.TestCase):

    def test_register_should_create_different_subnets(self):
        shnet = SharedNetwork()
        shnet.register(netaddr.IPNetwork('2001:db8:1::1/64'))
        shnet.register(netaddr.IPNetwork('2001:db8:2::1/64'))
        self.assertListEqual(list(shnet), [
            netaddr.IPNetwork('2001:db8:1::/64'),
            netaddr.IPNetwork('2001:db8:2::/64')])

    def test_register_should_not_create_different_subnets(self):
        shnet = SharedNetwork()
        shnet.register(netaddr.IPNetwork('2001:db8:1::1/64'))
        shnet.register(netaddr.IPNetwork('2001:db8:1::2/64'))
        self.assertListEqual(list(shnet), [
            netaddr.IPNetwork('2001:db8:1::/64')])
