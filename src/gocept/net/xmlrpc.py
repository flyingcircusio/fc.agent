# Copyright (c) 2012 gocept gmbh & co. kg
# See also LICENSE.txt

import xmlrpclib


class LoginTransport(xmlrpclib.Transport):

    user = None
    password = None

    def __init__(self, user, password):
        self.user = user
        self.password = password
        xmlrpclib.Transport.__init__(self, use_datetime=0)

    def get_host_info(self, host):
        host, extra_headers, x509 = xmlrpclib.Transport.get_host_info(
            self, host)
        if self.user:
            if extra_headers is None:
                extra_headers = {}
            auth = '%s:%s' % (self.user, self.password)
            auth = auth.encode('base64').strip()
            extra_headers['Authorization'] = 'Basic %s' % auth
        return host, extra_headers, x509
