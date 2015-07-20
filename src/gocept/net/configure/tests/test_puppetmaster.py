from mock import call
import gocept.net.configure.puppetmaster
import gocept.net.dhcp
import gocept.net.directory
import mock
import os
import shutil
import tempfile
import unittest


class PuppetmasterConfigurationTest(unittest.TestCase):

    def setUp(self):
        self.p_directory = mock.patch('gocept.net.directory.Directory')
        self.fake_directory = self.p_directory.start()

        self.p_call = mock.patch('subprocess.check_output')
        self.fake_call = self.p_call.start()
        self.autosign_conf = tempfile.mktemp()
        gocept.net.configfile.ConfigFile.quiet = True

        self.certdir = tempfile.mkdtemp()

    def tearDown(self):
        self.p_call.stop()
        self.p_directory.stop()
        if os.path.exists(self.autosign_conf):
            os.unlink(self.autosign_conf)
        if os.path.exists(self.certdir):
            shutil.rmtree(self.certdir)

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
        assert master.nodes == ['vm01.example.com', 'vm02.example.com']
        self.assertMultiLineEqual('vm01.example.com\nvm02.example.com\n',
                                  open(self.autosign_conf).read())

    def test_autosign_race_condition_unknown_not_signed(self):
        master = gocept.net.configure.puppetmaster.Puppetmaster(
            'here', 'example.com')
        master.nodes = []
        self.fake_call.return_value = """\
[{"name":"test06.gocept.net","state":"requested"}]"""
        master.sign_race_conditions()
        assert self.fake_call.call_args_list == [
            call(['puppet', 'ca', 'list', '--pending', '--render-as', 'json'])]

    def test_autosign_race_condition_known_gets_signed(self):
        master = gocept.net.configure.puppetmaster.Puppetmaster(
            'here', 'example.com')
        master.nodes = ['test06.gocept.net']
        self.fake_call.return_value = """\
[{"name":"test06.gocept.net","state":"requested"}]"""
        master.sign_race_conditions()
        assert self.fake_call.call_args_list == [
            call(['puppet', 'ca', 'list', '--pending', '--render-as', 'json']),
            call(['puppet', 'ca', 'sign', u'test06.gocept.net'])]

    def test_node_deletion(self):
        self.fake_directory().deletions.return_value = {
            'node00': {'stages': []},
            'node01': {'stages': ['prepare']},
            'node02': {'stages': ['prepare', 'soft']},
            'node03': {'stages': ['prepare', 'soft', 'hard']}}

        def status(*args):
            return '[{{"deactivated": null, "name":"{}"}}]'.format(args[0][-1])
        self.fake_call.side_effect = status
        master = gocept.net.configure.puppetmaster.Puppetmaster(
            'here', 'example.com')
        master.cert_location = self.certdir + '/{}.pem'
        for node in range(4):
            open(master.cert_location.format(
                 'node0{}.example.com'.format(node)), 'w')
        master.delete_nodes()
        assert self.fake_call.call_args_list == [
            call(['puppet', 'node', '--render-as', 'json',
                  'status', 'node02.example.com']),
            call(['puppet', 'node', 'deactivate', 'node02.example.com']),
            call(['puppet', 'node', '--render-as', 'json',
                  'status', 'node03.example.com']),
            call(['puppet', 'node', 'deactivate', 'node03.example.com']),
            call(['puppet', 'node', 'clean', 'node03.example.com'])]

    def test_node_deletion_convergent(self):
        self.fake_directory().deletions.return_value = {
            'node00': {'stages': []},
            'node01': {'stages': ['prepare']},
            'node02': {'stages': ['prepare', 'soft']},
            'node03': {'stages': ['prepare', 'soft', 'hard']}}

        def status(*args):
            return '[{{"deactivated": "2015-01-01", "name":"{}"}}]'.format(args[0][-1])
        self.fake_call.side_effect = status
        master = gocept.net.configure.puppetmaster.Puppetmaster(
            'here', 'example.com')
        master.delete_nodes()
        assert self.fake_call.call_args_list == [
            call(['puppet', 'node', '--render-as', 'json', 'status', 'node02.example.com']),
            call(['puppet', 'node', '--render-as', 'json', 'status', 'node03.example.com'])]

    def test_node_deletion_deactivate_empty_after_clean(self):
        self.fake_directory().deletions.return_value = {
            'node00': {'stages': []},
            'node01': {'stages': ['prepare']},
            'node02': {'stages': ['prepare', 'soft']},
            'node03': {'stages': ['prepare', 'soft', 'hard']}}

        def status(*args):
            # The puppet master returns an empty record with only the name
            # when we cleaned it. This is a regression test to avoid spurious
            # warnings.
            return '[{{"name":"{}"}}]'.format(args[0][-1])
        self.fake_call.side_effect = status
        master = gocept.net.configure.puppetmaster.Puppetmaster(
            'here', 'example.com')
        master.delete_nodes()
        assert self.fake_call.call_args_list == [
            call(['puppet', 'node', '--render-as', 'json', 'status', 'node02.example.com']),
            call(['puppet', 'node', '--render-as', 'json', 'status', 'node03.example.com'])]
