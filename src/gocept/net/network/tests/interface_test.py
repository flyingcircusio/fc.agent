from gocept.net.network.interface import HostConfiguration, LeafInterface
import ipaddress
import pkg_resources
import pytest
import StringIO


HostConfiguration.RT_TABLES = pkg_resources.resource_filename(
    __name__, 'fixture/rt_tables')


def test_no_interfaces():
    hc = HostConfiguration(StringIO.StringIO(), '')
    hc.parse_interfaces()
    assert len(hc.interfaces) == 0


def test_fc00_confd():
    hc = HostConfiguration(
        pkg_resources.resource_stream(__name__, 'fixture/fc00/enc.yaml'),
        pkg_resources.resource_filename(__name__, 'fixture/fc00/ann'))
    hc.parse_interfaces()
    confd = hc.confd('net.d')
    assert len(confd.keys()) == 2
    assert confd['net.d/iface.fe'] == str(pkg_resources.resource_string(
        __name__, 'result/fc00/conf.d/iface.fe'))
    assert confd['net.d/iface.srv'] == str(pkg_resources.resource_string(
        __name__, 'result/fc00/conf.d/iface.srv'))


def test_interface_addresses():
    i = LeafInterface('srv', 3, {'networks': {
        '172.22.48.0/20': ['172.22.48.127'],
        '2a02:248:101:63::/64':
        ['2a02:248:101:63::10d6', '2a02:248:101:63::10da'],
    }})
    assert set(i.interface_addresses()) == set([
        ipaddress.IPv4Interface(u'172.22.48.127/20'),
        ipaddress.IPv6Interface(u'2a02:248:101:63::10d6/64'),
        ipaddress.IPv6Interface(u'2a02:248:101:63::10da/64'),
    ])


def test_rt_tables():
    hc = HostConfiguration(StringIO.StringIO(), '')
    assert hc.parse_rt_tables() == dict(
        unspec=0, mgm=1, fe=2, srv=3, sto=4, stb=8, dhp=19, default=253,
        main=254, local=255)
