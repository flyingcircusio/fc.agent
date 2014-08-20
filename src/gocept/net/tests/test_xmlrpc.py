# Copyright (c) 2009 gocept gmbh & co. kg
# See also LICENSE.txt

import unittest
import gocept.net.xmlrpc


class TestLoginTransport(unittest.TestCase):

    def test_host_info(self):
        transport = gocept.net.xmlrpc.LoginTransport('myuser', 'mypassword')
        host, extra, x509 = transport.get_host_info('asdf.org')
        self.assertEquals('asdf.org', host)
        self.assertEquals({'Authorization': 'Basic bXl1c2VyOm15cGFzc3dvcmQ='},
                          extra)
        self.assertEquals({}, x509)


def test_suite():
    return unittest.makeSuite(TestLoginTransport)
