import configobj
import os.path as p


DEFAULT_ANNOTATIONS = {
    'mtu': 1500,
    'defaultroute': False,
    'metric': 1000,
    'skip': False,
    'style': 'managed'
}


class Annotations(object):

    def __init__(self, dir=None, vlan=None):
        self.cfg = configobj.ConfigObj()
        self.cfg['interface'] = DEFAULT_ANNOTATIONS
        if dir and vlan:
            self.read(dir, vlan)

    def read(self, dir, vlan):
        filename = p.join(dir, vlan + '.cfg')
        if p.exists(filename):
            self.cfg = configobj.ConfigObj(filename)
            return True

    @property
    def defaultroute(self):
        return self.cfg['interface'].as_bool('defaultroute')

    @property
    def skip(self):
        return self.cfg['interface'].as_bool('skip')

    @property
    def metric(self):
        return self.cfg['interface'].as_int('metric')

    @property
    def mtu(self):
        return self.cfg['interface'].as_int('mtu')

    @property
    def style(self):
        return self.cfg['interface']['style']
