# Manage nagios contacts: Nagios contacts for a specific contact group are all
# users with the "stats" permission. Users with the keyword "nonagios" in their
# description field are excluded from mails but still able to log in.

import gocept.net.directory
import StringIO
import gocept.net.ldaptools
import hashlib
import ldap
import os
import os.path
import re


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
        # XXX use configfile pattern!
        if os.path.exists(filename):
            old = open(filename, 'r').read()
            if content == old:
                return

        f = open(filename, 'w')
        f.write(content)
        f.close()
        self.needs_restart = True

    def contact_groups(self):
        self._init_ldap()
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
            for grant in self.search(
                    'cn=%s,ou=Group' % group_id,
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

        for user in self.search(
                'ou=People', '(&(cn=*)(objectClass=organizationalPerson))'):
            additional_options = []
            grp = []
            if user['uid'][0] in admins:
                grp.append('admins')
            grp.extend(stats_permission.get(user['uid'][0], []))
            self.contacts_seen.setdefault(user['mail'][0], set()).update(grp)
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
        """List all technical contacts as Nagios contacts."""
        result = StringIO.StringIO()

        contacts = dict()
        for group in self.directory.list_resource_groups():
            # XXX directory load. a comprehensive API would be nice.
            group_details = self.directory.lookup_resourcegroup(group)
            technical_contacts = group_details.get('technical_contacts', [])
            for contact in technical_contacts:
                contacts.setdefault(contact, []).append(group)

        for contact, groups in contacts.items():
            groups = set(groups)
            groups.difference_update(self.contacts_seen.get(contact, set()))
            if not groups:
                continue
            groups = list(groups)
            groups.sort()
            contact_hash = hashlib.sha256(contact)
            contact_hash = contact_hash.hexdigest()[:5]

            contact_safe = re.sub(r'[^a-zA-Z0-9]', '_', contact)
            contact_name = "technical_contact_{}_{}".format(
                contact_safe, contact_hash)

            additional_options = '    contact_groups      ' + ','.join(groups)
            result.write(CONTACT_TEMPLATE.format(
                name=contact_name,
                alias='Technical contact {} ({})'.format(
                    contact_safe, contact_hash),
                mail=contact,
                additional_options=additional_options))

        target = self.prefix + '/etc/nagios/globals/technical_contacts.cfg'
        self._flush(target, result.getvalue())


def contacts():
    with gocept.net.directory.exceptions_screened():
        configuration = NagiosContacts()
        configuration.contact_groups()
        configuration.contacts()
        configuration.contacts_technical()
        configuration.finish()
