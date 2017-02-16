"""Configure pools on Ceph storage servers according to the directory."""

from __future__ import print_function

from ..ceph import Pools, Cluster
import argparse
import gocept.net.directory


class ResourcegroupPoolEquivalence(object):
    """Ensure that required Ceph pools exist."""

    REQUIRED_POOLS = ['rbd', 'data', 'metadata', 'rbd.hdd']

    def __init__(self, directory, cluster, location):
        self.directory = directory
        self.pools = Pools(cluster)
        self.location = location

    def actual(self):
        return set(p for p in self.pools.names())

    def ensure(self):
        exp = set(self.REQUIRED_POOLS)
        act = self.actual()
        for pool in exp - act:
            print('creating pool {}'.format(pool))
            self.pools.create(pool)


class VolumeDeletions(object):

    def __init__(self, directory, cluster):
        self.directory = directory
        self.pools = Pools(cluster)

    def ensure(self):
        deletions = self.directory.deletions('vm')
        for name, node in deletions.items():
            if 'hard' not in node['stages']:
                continue
            for pool in self.pools:
                try:
                    images = list(pool.images)
                except KeyError:
                    # The pool doesn't exist. Ignore. Nothing to delete anyway.
                    continue

                for image in ['{}.root', '{}.swap', '{}.tmp']:
                    image = image.format(name)
                    base_image = None
                    for rbd_image in images:
                        if rbd_image.image != image:
                            continue
                        if not rbd_image.snapshot:
                            base_image = rbd_image
                            continue
                        # This is a snapshot of the volume itself.
                        print("Purging snapshot {}/{}@{}".format(
                              pool.name, image, rbd_image.snapshot))
                        pool.snap_rm(rbd_image)
                    if base_image is None:
                        continue
                    print("Purging volume {}/{}".format(pool.name, image))
                    pool.image_rm(base_image)


def volumes():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('-n', '--dry-run', help='show what would be done only',
                   default=False, action='store_true')
    p.add_argument('-c', '--conf', default='/etc/ceph/ceph.conf',
                   help='path to ceph.conf (default: %(default)s)')
    p.add_argument('-i', '--id', default='admin', metavar='USER',
                   help='rados user (without the "client." prefix) to '
                   'authenticate as (default: %(default)s)')
    p.add_argument('location', metavar='LOCATION',
                   help='location id (e.g., "dev")')
    args = p.parse_args()
    ceph = Cluster(args.conf, args.id, args.dry_run)
    with gocept.net.directory.exceptions_screened():
        volumes = VolumeDeletions(gocept.net.directory.Directory(), ceph)
        volumes.ensure()
        rpe = ResourcegroupPoolEquivalence(
            gocept.net.directory.Directory(), ceph, args.location)
        rpe.ensure()
