from gocept.net.network.interface import HostConfiguration, LeafInterface
from gocept.net.network.annotations import Annotations
from ipaddress import IPv4Interface, IPv6Interface, IPv4Network, IPv6Network
import pkg_resources
import pytest
import StringIO


HostConfiguration.RT_TABLES = pkg_resources.resource_filename(
    __name__, 'fixture/rt_tables')


def test_no_interfaces():
    hc = HostConfiguration(StringIO.StringIO(), '')
    hc.create_all_interfaces()
    assert len(hc.interfaces) == 0


def test_rt_tables():
    hc = HostConfiguration(StringIO.StringIO(), '')
    assert hc.parse_rt_tables() == dict(
        unspec=0, mgm=1, fe=2, srv=3, sto=4, stb=8, dhp=19, default=253,
        main=254, local=255)


def test_addrs():
    i = LeafInterface('srv', 3, {'networks': {
        '172.22.48.0/20': ['172.22.48.127'],
        '195.62.126.128/25': [],
        '2a02:248:101:63::/64':
        ['2a02:248:101:63::10d6', '2a02:248:101:63::10da'],
    }}, Annotations())
    assert i.addrs == {
        IPv4Network(u'172.22.48.0/20'): [IPv4Interface(u'172.22.48.127/20')],
        IPv4Network(u'195.62.126.128/25'): [],
        IPv6Network(u'2a02:248:101:63::/64'): [
            IPv6Interface(u'2a02:248:101:63::10d6/64'),
            IPv6Interface(u'2a02:248:101:63::10da/64'),
        ]
    }


def test_all_addrs():
    i = LeafInterface('srv', 3, {'networks': {
        '172.22.48.0/20': ['172.22.48.127'],
        '2a02:248:101:63::/64':
        ['2a02:248:101:63::10d6', '2a02:248:101:63::10da'],
    }}, Annotations())
    assert set(i.all_addrs) == set([
        IPv4Interface(u'172.22.48.127/20'),
        IPv6Interface(u'2a02:248:101:63::10d6/64'),
        IPv6Interface(u'2a02:248:101:63::10da/64'),
    ])

# XXX split into test_all_interfaces and individual add_interface tests


def test_fc00_confd():
    hc = HostConfiguration(
        pkg_resources.resource_stream(__name__, 'fixture/fc00/enc.yaml'),
        pkg_resources.resource_filename(__name__, 'fixture/fc00/ann'))
    hc.create_all_interfaces()
    confd = hc.confd('net.d')
    assert len(confd.keys()) == 2
    for vlan in ['fe', 'srv']:
        assert confd['net.d/iface.{}'.format(vlan)] == str(
            pkg_resources.resource_string(
                __name__, 'result/fc00/conf.d/iface.{}'.format(vlan)))


def test_lenny_confd():
    hc = HostConfiguration(
        pkg_resources.resource_stream(__name__, 'fixture/lenny/enc.yaml'),
        pkg_resources.resource_filename(__name__, 'fixture/lenny/ann'))
    hc.create_all_interfaces()
    confd = hc.confd('net.d')
    assert len(confd.keys()) == 5  # XXX should be 4 (w/o dhp)
    for vlan in ['fe', 'srv', 'sto', 'mgm']:
        assert confd['net.d/iface.{}'.format(vlan)] == str(
            pkg_resources.resource_string(
                __name__, 'result/lenny/conf.d/iface.{}'.format(vlan)))
