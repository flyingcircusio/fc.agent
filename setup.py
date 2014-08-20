from setuptools import setup, find_packages
import os

setup(
    name='fc.agent',
    version='1.3.4dev0',
    author='gocept',
    author_email='mail@gocept.com',
    url='http://bitbucket.org/flyingcircus/fc.agent/',
    description="""\
Local configuration utilities and helper APIs for flyingcircus.io system configuration.
""",
    packages=find_packages('src'),
    package_dir={'': 'src'},
    include_package_data=True,
    zip_safe=False,
    license='BSD',
    namespace_packages=['gocept'],
    install_requires=[
        'setuptools',
        'python-ldap',
        'mock>=0.8',
        'pytz',
        'iso8601>=0.1.4',
        'configobj>=4.7',
        'netaddr>=0.7'],
    entry_points={
        'console_scripts': [
            'list-maintenance = gocept.net.maintenance.script:list',
            'localconfig-box-exports = gocept.net.configure.box:exports',
            'localconfig-box-mounts = gocept.net.configure.box:mounts',
            'localconfig-ceph-pg_num = gocept.net.configure.ceph:pg_num',
            'localconfig-ceph-pools = gocept.net.configure.ceph:pools',
            'localconfig-dhcpd = gocept.net.configure.dhcpd:main',
            'localconfig-iptables-inputrules = gocept.net.configure.iptables:inputrules',
            'localconfig-kvm-disks = gocept.net.configure.kvm:resize_disks',
            'localconfig-kvm-init = gocept.net.configure.kvm:ensure_vms',
            'localconfig-nagioscontacts = gocept.net.configure.nagios:contacts',
            'localconfig-postfix-master = gocept.net.configure.postfix:master',
            'localconfig-puppetmaster = gocept.net.configure.puppetmaster:main',
            'localconfig-resize2fs-vmroot = gocept.net.configure.resize2fs:check_grow',
            'localconfig-users = gocept.net.configure.users:main',
            'localconfig-zones = gocept.net.configure.zones:update',
            'rbd-images = gocept.net.ceph.utils:list_images',
            'redundancy-groups = gocept.net.directory:redundancy_groups',
            'request-maintenance = gocept.net.maintenance.script:request',
            'run-maintenance = gocept.net.maintenance.script:run',
            'schedule-maintenance = gocept.net.maintenance.script:schedule',
        ],
    },
)
