from ..nagios import NagiosContacts
import os
import pytest


@pytest.fixture
def empty_config(tmpdir):
    os.mkdir(str(tmpdir/'etc'))
    os.mkdir(str(tmpdir/'etc/nagios/'))
    os.mkdir(str(tmpdir/'etc/nagios/globals/'))
    return tmpdir


def test_create_contacts(empty_config, tmpdir, capsys, monkeypatch, directory):
    directory = directory()
    directory.list_resource_groups.return_value = ['foobar']
    directory.lookup_resourcegroup.return_value = {
        'technical_contacts': ['foo@example.com']}

    contacts = NagiosContacts()
    contacts.prefix = str(tmpdir)
    contacts.contacts_technical()

    target = str(tmpdir/'/etc/nagios/globals/technical_contacts.cfg')
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

def test_ignore_duplicate_contacts(empty_config, tmpdir, capsys, monkeypatch,
                                   directory):
    directory = directory()
    directory.list_resource_groups.return_value = ['foobar']
    directory.lookup_resourcegroup.return_value = {
        'technical_contacts': ['foo@example.com']}

    contacts = NagiosContacts()
    contacts.prefix = str(tmpdir)
    contacts.contacts_seen['foo@example.com'] = set(['foobar'])
    contacts.contacts_technical()

    target = str(tmpdir/'/etc/nagios/globals/technical_contacts.cfg')
    found = open(target, 'r').read()
    assert found == ''
