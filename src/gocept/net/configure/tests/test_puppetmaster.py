# Copyright (c) 2011 gocept gmbh & co. kg
# See also LICENSE.txt

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
        self.autosign_conf = tempfile.mktemp()
        gocept.net.configfile.ConfigFile.quiet = True

    def tearDown(self):
        self.p_directory.stop()
        if os.path.exists(self.autosign_conf):
            os.unlink(self.autosign_conf)

    def test_complete_config_acceptance(self):
        """This tests tries to compile most of the nasty cases."""
        self.fake_directory().list_nodes.return_value = [
            {'name':'vm02',
             'parameters': {'location': 'here'}},
            {'name':'vm01',
             'parameters': {'location': 'here'}},
            {'name':'vm03',
             'parameters': {'location': 'there'}}]
        master = gocept.net.configure.puppetmaster.Puppetmaster(
            'here', 'example.com')
        master.autosign_conf = self.autosign_conf
        master.autosign()
        self.assertMultiLineEqual('vm01.example.com\nvm02.example.com\n',
                                  open(self.autosign_conf).read())
