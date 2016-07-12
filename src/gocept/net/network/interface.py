from six import u
import collections
import configobj
import ipaddress
import os.path as p
import yaml


DEFAULT_ANNOTATIONS = {
    'mtu': 1500,
    'defaultroute': False,
    'metric': 1000,
    'skip': False,
    'style': 'managed'
}


class HostConfiguration(object):

    RT_TABLES = '/etc/iproute2/rt_tables'

    interfaces = None
    interface_by_mac = None

    def __init__(self, enc_yaml, annotations_dir):
        self.enc = yaml.safe_load(enc_yaml) or {}
        self.enc_interfaces = self.enc.get(
            'parameters', {}).get('interfaces', {})
        self.annotations_dir = annotations_dir
        self.rt_tables = self.parse_rt_tables()

    def parse_interfaces(self):
        self.interfaces = []
        self.interface_by_mac = collections.defaultdict(list)
        for vlan in self.enc_interfaces.keys():
            iface = LeafInterface(
                vlan, self.rt_tables[vlan],
                self.enc['parameters']['interfaces'][vlan],
                p.join(self.annotations_dir, vlan + '.cfg'))
            self.interfaces.append(iface)
            self.interface_by_mac[iface.mac].append(iface)

    def confd(self, basedir):
        res = {}
        for iface in self.interfaces:
            res[p.join(basedir, 'iface.' + iface.vlan)] = iface.confd()
        return res

    def parse_rt_tables(self):
        rt = {}
        with open(self.RT_TABLES) as f:
            for line in f:
                if line == '' or line.startswith('#'):
                    continue
                num, name = line.split(None, 1)
                rt[name.strip()] = int(num)
        return rt


class Interface(object):
    name = None
    mgm = None

# XXX __new__ factory

    def __init__(self, vlan, vlan_id, enc, annotations_cfg=None):
        self.vlan = vlan
        self.vlan_id = vlan_id
        self.enc = enc
        if annotations_cfg and p.exists(annotations_cfg):
            self.ann = configobj.ConfigObj(annotations_cfg)['interface']
        else:
            ann = configobj.ConfigObj()
            ann['interface'] = DEFAULT_ANNOTATIONS
            self.ann = ann['interface']
        if self.ann['style'] == 'managed':
            self.mgm = Static(self)
        self.dependent = {}

    @property
    def name(self):
        return 'eth' + self.vlan

    @property
    def mac(self):
        return self.enc['mac'].upper()

    def interface_addresses(self):
        for net, addrs in sorted(self.enc['networks'].items()):
            n = ipaddress.ip_network(u(net))
            for a in addrs:
                yield ipaddress.ip_interface(u'{}/{}'.format(a, n.prefixlen))

    @property
    def addresses(self):
        for addr in self.interface_addresses():
            yield str(addr)

    @property
    def routes(self):
        for net, addrs in sorted(self.enc['networks'].items()):
            yield '{} table {}'.format(net, self.vlan_id)
            if self.ann.as_bool('defaultroute') and addrs != []:
                gw = self.enc['gateways'].get(net)
                if gw:
                    yield 'default via {} table {}'.format(gw, self.vlan_id)
                    yield 'default via {}'.format(gw)

    def rules(self, af):
        for addr in self.interface_addresses():
            if not addr.version == af:
                continue
            yield 'from {} table {} priority {}'.format(
                addr, self.vlan_id, self.vlan_id * 10)
        for net in sorted(self.enc['networks'].keys()):
            if ipaddress.ip_network(u(net)).version != af:
                continue
            yield 'to {} table {} priority {}'.format(
                net, self.vlan_id, self.vlan_id * 10)

    @property
    def rules4(self):
        return self.rules(4)

    @property
    def rules6(self):
        return self.rules(6)

    @property
    def mtu(self):
        return self.ann.as_int('mtu')

    @property
    def metric(self):
        return self.ann.as_int('metric')

    def confd(self):
        raise NotImplementedError()


class LeafInterface(Interface):

    def confd(self):
        return """\
# Managed by configure-interface. Don't edit.

config_{name}="\\
    {addresses}
"

routes_{name}="\\
    {routes}
"

rules_{name}="\\
    {rules4}
"

rules6_{name}="\\
    {rules6}
"

mtu_{name}={mtu}
metric_{name}={metric}
""".format(addresses='\n    '.join(self.addresses),
           routes='\n    '.join(self.routes),
           rules4='\n    '.join(self.rules4),
           rules6='\n    '.join(self.rules6),
           mtu=self.mtu, metric=self.metric, name=self.name)


class VLANMultiplexer(Interface):
    pass


class BridgedEth(Interface):
    pass


class Bridge(LeafInterface):

    @property
    def name(self):
        return 'br' + self.name


class MgmStrategy(object):

    def __init__(self, iface):
        self.iface = iface


class Static(MgmStrategy):
    pass


class Dynamic(MgmStrategy):
    pass


class Disabled(MgmStrategy):
    pass
