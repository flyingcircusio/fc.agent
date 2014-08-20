# Copyright (c) 2009 gocept gmbh & co. kg
# See also LICENSE.txt

import ldap


def load_ldapconf(filename):
    data = {}
    for line in open(filename):
        if line.startswith('#'):
            continue
        line = line.strip()
        if not line:
            continue
        key, value = line.split(' ', 1)
        data[key] = value
    return data


def search(server, base, filter):
    id = server.search(base, ldap.SCOPE_ONELEVEL, filter, None)
    while True:
        type, data = server.result(id, 0)
        if data == []:
            return
        if type == ldap.RES_SEARCH_ENTRY:
            yield data[0][1]


