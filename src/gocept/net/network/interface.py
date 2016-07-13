from six import u
from .annotations import Annotations
import collections
import itertools
import configobj
import ipaddress
import os.path as p
import yaml


class HostConfiguration(object):

    RT_TABLES = '/etc/iproute2/rt_tables'

    interfaces = None
    interface_by_mac = None
    conf_header = "# Managed by configure-interface. Don't edit.\n\n"

    def __init__(self, enc_yaml, annotations_dir):
        self.enc = yaml.safe_load(enc_yaml) or {}
        self.enc_interfaces = self.enc.get('interfaces', {})
        self.annotations_dir = annotations_dir
        self.rt_tables = self.parse_rt_tables()

    def create_all_interfaces(self):
        self.interfaces = []
        self.interface_by_mac = collections.defaultdict(list)
        for vlan in self.enc_interfaces.keys():
            for iface in self.create_interfaces(vlan):
                self.interfaces.append(iface)
                self.interface_by_mac[iface.mac].append(iface)

    def create_interfaces(self, vlan):
        annotations = Annotations(self.annotations_dir, vlan)
        if annotations.skip:
            return []
        vlan_id = self.rt_tables[vlan]
        params = self.enc_interfaces[vlan]
        if params['bridged'] is True or params['bridged'] == 'true':
            eth = BridgedEth(vlan, vlan_id, params, annotations)
            br = Bridge(vlan, vlan_id, params, annotations)
            eth.add_child(br)
            return [eth, br]
        else:
            return [LeafInterface(vlan, vlan_id, params, annotations)]

    def confd(self, basedir):
        res = collections.defaultdict(list)
        for iface in self.interfaces:
            c = iface.confd()
            if c:
                res[p.join(basedir, 'iface.' + iface.vlan)].append(c)
        conffiles = {}
        for path, snippets in res.items():
            conffiles[path] = self.conf_header + '\n'.join(snippets)
        return conffiles

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
    parent = None

    def __init__(self, vlan, vlan_id, enc, annotations):
        self.vlan = vlan
        self.vlan_id = vlan_id
        self.enc = enc
        self.ann = annotations
        if self.ann.style == 'managed':
            self.mgm = Static(self)
        self.addrs = {}
        for net, addrs in sorted(self.enc['networks'].items()):
            n = ipaddress.ip_network(u(net))
            if n not in self.addrs:
                self.addrs[n] = []
            for a in addrs:
                self.addrs[n].append(
                    ipaddress.ip_interface(u'{}/{}'.format(a, n.prefixlen)))

    @property
    def name(self):
        return 'eth' + self.vlan

    @property
    def mac(self):
        return self.enc['mac'].upper()

    @property
    def all_addrs(self):
        return itertools.chain.from_iterable(self.addrs.values())

    @property
    def config(self):
        for addr in self.all_addrs:
            yield str(addr)

    @property
    def routes(self):
        for net in sorted(self.addrs.keys(), key=str):
            if not any(a for a in self.all_addrs
                       if a.version == net.version):
                continue
            yield '{} table {}'.format(net, self.vlan_id)
            if self.ann.defaultroute and self.addrs[net]:
                gw = self.enc['gateways'].get(str(net))
                if gw:
                    yield 'default via {} table {}'.format(gw, self.vlan_id)
                    yield 'default via {}'.format(gw)

    def add_child(self, child):
        child.parent = self
        self.children.append(child)

    def rules(self, af):
        for addr in self.all_addrs:
            if not addr.version == af:
                continue
            yield 'from {} table {} priority {}'.format(
                addr, self.vlan_id, self.vlan_id * 10)
        for net in sorted(self.addrs.keys(), key=str):
            if net.version == af:
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
        return self.ann.mtu

    @property
    def metric(self):
        return self.ann.metric

    def confd(self):
        raise NotImplementedError()


class LeafInterface(Interface):

    def confd(self):
        return self.mgm.confd()


class BridgedEth(Interface):

    def __init__(self, vlan, vlan_id, enc, annotations_cfg=None):
        super(BridgedEth, self).__init__(vlan, vlan_id, enc, annotations_cfg)
        self.children = []

    def confd(self):
        return """\
config_{name}="null"
mtu_{name}={mtu}
""".format(name=self.name, mtu=self.mtu)


class Bridge(LeafInterface):

    @property
    def name(self):
        return 'br' + self.vlan

    def confd(self):
        return ("""\
bridge_{name}="{eth}"
rc_net_{name}_need="net.{eth}"
""".format(name=self.name, eth=self.parent.name) + '\n' +
            self.mgm.confd())


class MgmStrategy(object):

    def __init__(self, iface):
        self.iface = iface


class Static(MgmStrategy):

    def confd(self):
        return """\
config_{name}="\\
    {config}
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
""".format(config='\n    '.join(self.iface.config),
           routes='\n    '.join(self.iface.routes),
           rules4='\n    '.join(self.iface.rules4),
           rules6='\n    '.join(self.iface.rules6),
           mtu=self.iface.mtu, metric=self.iface.metric, name=self.iface.name)


class DHCP(MgmStrategy):
    pass


class Disabled(MgmStrategy):
    pass
