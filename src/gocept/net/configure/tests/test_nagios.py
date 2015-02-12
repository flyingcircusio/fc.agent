from ..nagios import NagiosContacts, nodes
import os
import pytest


@pytest.fixture
def empty_config(tmpdir):
    os.mkdir(str(tmpdir / 'etc'))
    os.mkdir(str(tmpdir / 'etc/nagios/'))
    os.mkdir(str(tmpdir / 'etc/nagios/globals/'))
    return tmpdir


def test_create_technical_contacts(empty_config, tmpdir, capsys, directory):
    directory = directory()
    directory.list_resource_groups.return_value = ['foobar']
    directory.lookup_resourcegroup.return_value = {
        'technical_contacts': ['foo@example.com']}

    contacts = NagiosContacts()
    contacts.prefix = str(tmpdir)
    contacts.contacts_technical()

    target = str(tmpdir / '/etc/nagios/globals/technical_contacts.cfg')
    found = open(target, 'r').read()
    assert found == '''\

define contact {
    use                 generic-contact
    contact_name        technical_contact_foo_example_com_321ba
    alias               Technical contact foo_example_com (321ba)
    email               foo@example.com
    contact_groups      foobar
}
'''


def test_ignore_duplicate_contacts(empty_config, tmpdir, capsys, directory):
    directory = directory()
    directory.list_resource_groups.return_value = ['foobar']
    directory.lookup_resourcegroup.return_value = {
        'technical_contacts': ['foo@example.com']}

    contacts = NagiosContacts()
    contacts.prefix = str(tmpdir)
    contacts.contacts_seen['foo@example.com'] = set(['foobar'])
    contacts.contacts_technical()

    target = str(tmpdir / '/etc/nagios/globals/technical_contacts.cfg')
    found = open(target, 'r').read()
    assert found == ''


def test_create_contacts(empty_config, tmpdir, capsys, monkeypatch, directory):
    directory = directory()
    directory.list_resource_groups.return_value = ['foobar']

    contacts = NagiosContacts()
    contacts.prefix = str(tmpdir)
    contacts._init_ldap = lambda: None
    contacts.admins = lambda: []
    contacts.stats_permission = lambda: {'bob': set('foobar'),
                                         'alice': set('foobar')}
    contacts.users = lambda: [
        {'uid': ['bob']},
        {'uid': ['alice'], 'mail': ['alice@example.com']},
        {'uid': ['caesar'], 'mail': ['caesar@example.com'], 'cn': ['Caesar']}]
    contacts.groups = [{'cn': ['foobar']}]
    contacts.contact_groups()
    contacts.contacts()

    target = str(tmpdir / '/etc/nagios/globals/contacts.cfg')
    found = open(target, 'r').read()
    assert found == """\

define contact {
    use                 generic-contact
    contact_name        caesar
    alias               Caesar
    email               caesar@example.com

}
"""


def test_delete_nodes(empty_config, tmpdir, capsys, monkeypatch, directory):
    directory = directory()
    directory.deletions.return_value = {
        'node00': {'stages': []},
        'node01': {'stages': ['prepare']},
        'node02': {'stages': ['prepare', 'soft']},
        'node03': {'stages': ['prepare', 'soft', 'hard']},
        'node04': {'stages': ['prepare', 'soft', 'hard', 'purge']}}

    NagiosContacts.prefix = str(tmpdir)

    md = os.makedirs
    for node in directory.deletions().keys():
        md(str(tmpdir / '/etc/nagios/hosts/{}/asdf'.format(node)))
        md(str(tmpdir / '/var/nagios/perfdata/{}'.format(node)))
        open(str(tmpdir / '/etc/nagios/hosts/{}.cfg'.format(node)), 'w')

    for i in range(5):
        assert os.path.isdir(
            str(tmpdir / '/etc/nagios/hosts/node0{}').format(i))
        assert os.path.exists(
            str(tmpdir / '/etc/nagios/hosts/node0{}/asdf').format(i))
        assert os.path.exists(
            str(tmpdir / '/etc/nagios/hosts/node0{}.cfg').format(i))
        assert os.path.isdir(
            str(tmpdir / '/var/nagios/perfdata/node0{}').format(i))

    nodes()

    # nothing
    assert os.path.exists(str(tmpdir / '/etc/nagios/hosts/node00'))
    assert os.path.exists(str(tmpdir / '/etc/nagios/hosts/node00/asdf'))
    assert os.path.exists(str(tmpdir / '/etc/nagios/hosts/node00.cfg'))
    assert os.path.exists(str(tmpdir / '/var/nagios/perfdata/node00'))

    # prepare
    assert os.path.exists(str(tmpdir / '/etc/nagios/hosts/node01'))
    assert os.path.exists(str(tmpdir / '/etc/nagios/hosts/node01/asdf'))
    assert os.path.exists(str(tmpdir / '/etc/nagios/hosts/node01.cfg'))
    assert os.path.exists(str(tmpdir / '/var/nagios/perfdata/node01'))

    # soft
    assert not os.path.exists(str(tmpdir / '/etc/nagios/hosts/node02'))
    assert not os.path.exists(str(tmpdir / '/etc/nagios/hosts/node02/asdf'))
    assert not os.path.exists(str(tmpdir / '/etc/nagios/hosts/node02.cfg'))
    assert os.path.exists(str(tmpdir / '/var/nagios/perfdata/node02'))

    # hard
    assert not os.path.exists(str(tmpdir / '/etc/nagios/hosts/node03'))
    assert not os.path.exists(str(tmpdir / '/etc/nagios/hosts/node03/asdf'))
    assert not os.path.exists(str(tmpdir / '/etc/nagios/hosts/node03.cfg'))
    assert os.path.exists(str(tmpdir / '/var/nagios/perfdata/node03'))

    # purge
    assert not os.path.exists(str(tmpdir / '/etc/nagios/hosts/node04'))
    assert not os.path.exists(str(tmpdir / '/etc/nagios/hosts/node04/asdf'))
    assert not os.path.exists(str(tmpdir / '/etc/nagios/hosts/node04.cfg'))
    assert not os.path.exists(str(tmpdir / '/var/nagios/perfdata/node04'))
