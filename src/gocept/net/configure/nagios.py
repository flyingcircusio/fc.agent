# Manage nagios contacts: Nagios contacts for a specific contact group are all
# users with the "stats" permission. Users with the keyword "nonagios" in their
# description field are excluded from mails but still able to log in.

import gocept.net.directory
import gocept.net.ldaptools
import hashlib
import ldap
import logging
import os
import os.path
import re
import shutil
import StringIO

logger = logging.getLogger(__name__)

CONTACT_TEMPLATE = """
define contact {{
    use                 generic-contact
    contact_name        {name}
    alias               {alias}
    email               {mail}
{additional_options}
}}
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

    prefix = ''

    def __init__(self):
        self.directory = gocept.net.directory.Directory()
        self.needs_restart = False
        self.contacts_seen = {}

    def _init_ldap(self):
        self.ldapconf = gocept.net.ldaptools.load_ldapconf('/etc/ldap.conf')
        self.server = ldap.initialize('ldap://%s/' % self.ldapconf['host'])
        self.server.protocol_version = ldap.VERSION3
        self.server.simple_bind_s(
            self.ldapconf['binddn'], self.ldapconf['bindpw'])
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
        filename = self.prefix + filename
        # XXX use configfile pattern!
        if os.path.exists(filename):
            old = open(filename, 'r').read()
            if content == old:
                return

        f = open(filename, 'w')
        f.write(content)
        f.close()
        self.needs_restart = True

    def _purge(self, filename):
        filename = self.prefix + filename
        if not os.path.exists(filename):
            return
        os.remove(filename)
        self.needs_restart = True

    def contact_groups(self):
        self._init_ldap()
        result = StringIO.StringIO()
        for group in self.groups:
            result.write(CONTACT_GROUP_TEMPLATE % dict(
                name=group['cn'][0],
                description=group.get('description', group['cn'])[0]))
            result.write(CONTACT_GROUP_TEMPLATE % dict(
                name='%s-system' % group['cn'][0],
                description="System notifications for RG %s" % group['cn'][0]))
        self._flush('/etc/nagios/globals/contactgroups.cfg', result.getvalue())

    def admins(self):
        """List of all super-admins"""
        admins = [group for group in self.groups
                  if group['cn'] == ['admins']][0]
        return admins['memberUid']

    def _permission_map(self, permission):
        permission_map = {}
        for group in self.groups:
            group_id = group['cn'][0]
            for grant in self.search(
                    'cn=%s,ou=Group' % group_id,
                    '(&(permission=%s)(objectClass=permissionGrant))' %
                    permission):
                for user in grant['uid']:
                    permission_map.setdefault(user, set())
                    permission_map[user].add(group_id)
        return permission_map

    def stats_permission(self):
        """Dict that lists groups for which each user has stats permissions"""
        return self._permission_map('stats')

    def wheel_permission(self):
        """Dict that lists groups for which each user has wheel permissions"""
        return self._permission_map('wheel')

    def users(self):
        return self.search(
            'ou=People', '(&(cn=*)(objectClass=organizationalPerson))')

    def contacts(self):
        """List all users as contacts"""
        result = StringIO.StringIO()
        admins = self.admins()
        stats_permission = self.stats_permission()
        wheel_permission = self.wheel_permission()

        for user in self.users():
            additional_options = []
            grp = []
            if user['uid'][0] in admins:
                grp.append('admins')
            grp.extend(stats_permission.get(user['uid'][0], []))
            grp.extend(
                '%s-system' % group
                for group in wheel_permission.get(user['uid'][0], []))
            if 'mail' in user:
                self.contacts_seen.setdefault(user['mail'][0], set()).update(
                    grp)
            if grp:
                additional_options.append(
                    '    contact_groups      ' + ','.join(grp))
            if 'nonagios' in '\n'.join(user.get('description', [])):
                additional_options.append(NO_NOTIFICATIONS_TEMPLATE)
            try:
                result.write(CONTACT_TEMPLATE.format(
                    name=user['uid'][0],
                    alias=user['cn'][0],
                    mail=user['mail'][0],
                    additional_options='\n'.join(additional_options)))
            except KeyError:
                pass

        self._flush('/etc/nagios/globals/contacts.cfg', result.getvalue())

    def contacts_technical(self):
        """Do not explicitly alert technical contacts for now, see also #14900"""
        self._purge('/etc/nagios/globals/technical_contacts.cfg')


def contacts():
        configuration = NagiosContacts()
        configuration.contact_groups()
        configuration.contacts()
        configuration.contacts_technical()
        configuration.finish()


def nodes():
    with gocept.net.directory.exceptions_screened():
        d = gocept.net.directory.Directory()
        deletions = d.deletions('vm')
    reload_nagios = False
    for name, node in deletions.items():
        if 'soft' in node['stages']:
            try:
                hostdir = (NagiosContacts.prefix +
                           '/etc/nagios/hosts/{}'.format(name))
                if os.path.exists(hostdir):
                    reload_nagios = True
                    shutil.rmtree(hostdir)
                hostcfg = (NagiosContacts.prefix +
                           '/etc/nagios/hosts/{}.cfg'.format(name))
                if os.path.exists(hostcfg):
                    reload_nagios = True
                    os.unlink(hostcfg)
            except Exception, e:
                logger.exception(e)
        if 'purge' in node['stages']:
            try:
                perfdata = (NagiosContacts.prefix +
                            '/var/nagios/perfdata/{}'.format(name))
                if os.path.exists(perfdata):
                    shutil.rmtree(perfdata)
            except Exception, e:
                logger.exception(e)
    if reload_nagios:
        os.system('/etc/init.d/nagios reload > /dev/null')
