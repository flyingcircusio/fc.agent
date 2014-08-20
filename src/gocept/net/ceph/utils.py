# Copyright (c) gocept gmbh & co. kg
# See also LICENSE.txt

"""Command line utilities to easy handling of Ceph images."""

from __future__ import unicode_literals, print_function
from pools import Pools
import argparse
import operator
import socket


def mode_string(img):
    return (('s' if img.snapshot else '-') +
            ('p' if img.protected else '-') +
            (img.lock_type[0] if img.lock_type else '-'))


def short_formatter(pool, img):
    return '{pool}/{name}'.format(pool=pool.name, name=img.name)


def long_formatter(pool, img):
    return '{mode} {fmt} {size:5}  {pool}/{name}'.format(
        mode=mode_string(img), fmt=img.format, size=img.size_gb,
        pool=pool.name, name=img.name)


def list_images():
    argp = argparse.ArgumentParser(
        description='Lists all known RBD images or only those in POOL',
        epilog='Long listing status characters are: s=snapshot, p=protected, '
        'e=exclusive lock')
    argp.add_argument('POOL', nargs='?', default=None,
                      help='confine listing to POOL')
    argp.add_argument('-l', '--long', action='store_true', default=False,
                      help='show additional details: status, image format, '
                      'size (GiB), pool, name')
    argp.add_argument('-i', '--id', default=socket.gethostname(),
                      help='Ceph auth id (defaults to hostname)')
    argp.add_argument('-c', '--conf', default='/etc/ceph/ceph.conf',
                      help='Ceph configuration file (default: %(default)s)')
    args = argp.parse_args()
    if args.long:
        formatter = long_formatter
    else:
        formatter = short_formatter

    pools_collection = Pools(args.id, args.conf)
    if args.POOL:
        pools = [pools_collection.lookup(args.POOL)]
    else:
        pools = pools_collection.all()
    for pool in sorted(pools, key=operator.attrgetter('name')):
        for img in sorted(pool.images, key=operator.attrgetter('name')):
            print(formatter(pool, img))
