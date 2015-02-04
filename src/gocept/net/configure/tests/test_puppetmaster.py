from mock import call
import gocept.net.configure.puppetmaster
import gocept.net.dhcp
import gocept.net.directory
import mock
import os
import tempfile
import unittest


class PuppetmasterConfigurationTest(unittest.TestCase):

    def setUp(self):
        self.p_directory = mock.patch('gocept.net.directory.Directory')
        self.fake_directory = self.p_directory.start()

        self.p_call = mock.patch('subprocess.check_call')
        self.fake_call = self.p_call.start()
        self.autosign_conf = tempfile.mktemp()
        gocept.net.configfile.ConfigFile.quiet = True

    def tearDown(self):
        self.p_call.stop()
        self.p_directory.stop()
        if os.path.exists(self.autosign_conf):
            os.unlink(self.autosign_conf)

    def test_complete_config_acceptance(self):
        """This tests tries to compile most of the nasty cases."""
        self.fake_directory().list_nodes.return_value = [
            {'name': 'vm02', 'parameters': {'location': 'here'}},
            {'name': 'vm01', 'parameters': {'location': 'here'}},
            {'name': 'vm03', 'parameters': {'location': 'there'}}]
        master = gocept.net.configure.puppetmaster.Puppetmaster(
            'here', 'example.com')
        master.autosign_conf = self.autosign_conf
        master.autosign()
        self.assertMultiLineEqual('vm01.example.com\nvm02.example.com\n',
                                  open(self.autosign_conf).read())

    def test_node_deletion(self):
        self.fake_directory().deletions.return_value = {
            'node00': {'stages': []},
            'node01': {'stages': ['prepare']},
            'node02': {'stages': ['prepare', 'soft']},
            'node03': {'stages': ['prepare', 'soft', 'hard']}}
        master = gocept.net.configure.puppetmaster.Puppetmaster(
            'here', 'example.com')
        master.delete_nodes()
        assert self.fake_call.call_args_list == [
            call(['puppet', 'node', 'deactivate', 'node02']),
            call(['puppet', 'node', 'deactivate', 'node03']),
            call(['puppet', 'node', 'clean', 'node03'])]
