from setuptools import setup, find_packages

setup(
    name='fc.agent',
    version='1.9.12',
    author='Flying Circus',
    author_email='mail@flyingcircus.io',
    url='http://bitbucket.org/flyingcircus/fc.agent',
    description="""\
Local configuration utilities and helper APIs for flyingcircus.io
system configuration.
""",
    packages=find_packages('src'),
    package_dir={'': 'src'},
    include_package_data=True,
    zip_safe=False,
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Environment :: Console',
        'Programming Language :: Python :: 2.7',
    ],
    license='BSD',
    namespace_packages=['gocept'],
    install_requires=[
        'configobj>=4.7',
        'ipaddress>=1.0',
        'iso8601==0.1.10',
        'nagiosplugin',
        'netaddr>=0.7',
        'pytest',
        'python-ldap',
        'pytz',
        'PyYaml',
        'requests>=2.3',
        'setuptools',
        'six',
        'shortuuid>=0.4',
    ],
    entry_points={
        'console_scripts': [
            'list-maintenance = gocept.net.maintenance.script:list',
            'localconfig-backy = gocept.net.configure.backy:configure',
            'localconfig-bacula-purge = gocept.net.configure.bacula:purge',
            'localconfig-box-exports = gocept.net.configure.box:exports',
            'localconfig-box-mounts = gocept.net.configure.box:mounts',
            'localconfig-ceph-volumes = gocept.net.configure.ceph:volumes',
            'localconfig-dhcpd = gocept.net.configure.dhcpd:main',
            'localconfig-iptables-rules = gocept.net.configure.iptables:rules',
            'localconfig-kibana = gocept.net.configure.kibana:main',
            'localconfig-kvm-init = gocept.net.configure.kvm:ensure_vms',
            'localconfig-nagios-nodes = gocept.net.configure.nagios:nodes',
            'localconfig-nagioscontacts'
            ' = gocept.net.configure.nagios:contacts',
            'localconfig-postfix-master = '
            'gocept.net.configure.postfix:master',
            'localconfig-puppetmaster'
            '= gocept.net.configure.puppetmaster:main',
            'localconfig-resize2fs-vmroot'
            '= gocept.net.configure.resize2fs:check_grow',
            'localconfig-users = gocept.net.configure.users:main',
            'localconfig-vm-images = gocept.net.configure.vmimages:update',
            'localconfig-zones = gocept.net.configure.zones:update',
            'rbd-clean-old-snapshots '
            '= gocept.net.ceph.utils:clean_old_snapshots',
            'rbd-images = gocept.net.ceph.utils:list_images',
            'request-maintenance = gocept.net.maintenance.script:request',
            'run-maintenance = gocept.net.maintenance.script:run',
            'schedule-maintenance = gocept.net.maintenance.script:schedule',
        ],
    },
)
