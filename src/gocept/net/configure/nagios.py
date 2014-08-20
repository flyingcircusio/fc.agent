# Copyright (c) 2011 gocept gmbh & co. kg
# See also LICENSE.txt
#
# Manage nagios contacts: Nagios contacts for a specific contact group are all
# users with the "stats" permission. Users with the keyword "nonagios" in their
# description field are excluded from mails but still able to log in.

import StringIO
import gocept.net.ldaptools
import ldap
import os
import os.path


CONTACT_TEMPLATE = """
define contact {
    use                 generic-contact
    contact_name        %(uid)s%(groups)s
    alias               %(cn)s
    email               %(mail)s
%(notifications)s}
"""

NO_NOTIFICATIONS_TEMPLATE = """\
    service_notification_options n
    host_notification_options n
"""

CONTACT_GROUP_TEMPLATE = """
define contactgroup {
    contactgroup_name   %(name)s
    alias               %(description)s
}
"""


class NagiosContacts(object):

    def __init__(self):
        self.ldapconf = gocept.net.ldaptools.load_ldapconf('/etc/ldap.conf')
        self.server = ldap.initialize('ldap://%s/' % self.ldapconf['host'])
        self.server.protocol_version = ldap.VERSION3
        self.server.simple_bind_s(
            self.ldapconf['binddn'], self.ldapconf['bindpw'])
        self.needs_restart = False
        self.groups = list(self.search(
            'ou=Group', '(objectClass=posixGroup)'))
        if len(self.groups) <= 1:
            raise RuntimeError(
                'safety check: not enough data returned by LDAP query: %r' %
                self.groups)

    def search(self, base, *args, **kw):
        base = '%s,%s' % (base, self.ldapconf['base'])
        return gocept.net.ldaptools.search(self.server, base, *args, **kw)

    def finish(self):
        self.server.unbind()
        if self.needs_restart:
            os.system('/etc/init.d/nagios reload > /dev/null')

    def _flush(self, filename, content):
        if os.path.exists(filename):
            old = open(filename, 'r').read()
            if content == old:
                return

        f = open(filename, 'w')
        f.write(content)
        f.close()
        self.needs_restart = True

    def contact_groups(self):
        result = StringIO.StringIO()
        for group in self.groups:
            result.write(CONTACT_GROUP_TEMPLATE % dict(
                name=group['cn'][0],
                description=group.get('description', group['cn'])[0]))
        self._flush('/etc/nagios/globals/contactgroups.cfg', result.getvalue())

    def admins(self):
        """List of all super-admins"""
        admins = [group for group in self.groups
                  if group['cn'] == ['admins']][0]
        return admins['memberUid']

    def stats_permission(self):
        """Dict that lists groups for which each user has stats permissions"""
        stats_permission = {}
        for group in self.groups:
            group_id = group['cn'][0]
            for grant in self.search('cn=%s,ou=Group' % group_id,
                        '(&(permission=stats)(objectClass=permissionGrant))'):
                for user in grant['uid']:
                    stats_permission.setdefault(user, set())
                    stats_permission[user].add(group_id)
        return stats_permission

    def contacts(self):
        """List all users as contacts"""
        result = StringIO.StringIO()
        admins = self.admins()
        stats_permission = self.stats_permission()

        for user in self.search('ou=People',
                '(&(cn=*)(objectClass=organizationalPerson))'):
            groups = ''
            grp = []
            if user['uid'][0] in admins:
                grp.append('admins')
            grp.extend(stats_permission.get(user['uid'][0], []))
            if grp:
                groups = '\n    contact_groups      ' + ','.join(grp)
            if 'nonagios' in '\n'.join(user.get('description', [])):
                notifications = NO_NOTIFICATIONS_TEMPLATE
            else:
                notifications = ''
            try:
                result.write(CONTACT_TEMPLATE % dict(
                    uid=user['uid'][0],
                    groups=groups,
                    cn=user['cn'][0],
                    mail=user['mail'][0],
                    notifications=notifications))
            except KeyError:
                pass

        self._flush('/etc/nagios/globals/contacts.cfg', result.getvalue())


def contacts():
    configuration = NagiosContacts()
    configuration.contact_groups()
    configuration.contacts()
    configuration.finish()
