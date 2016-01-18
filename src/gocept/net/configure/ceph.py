"""Configure pools on Ceph storage servers according to the directory."""

from __future__ import print_function

from ..ceph import Pools, Cluster
import argparse
import gocept.net.directory
import math
import random


class ResourcegroupPoolEquivalence(object):
    """Ensure that Ceph's pools match existing resource groups."""

    PROTECTED_POOLS = ['rbd', 'data', 'metadata']

    def __init__(self, directory, cluster, location):
        self.directory = directory
        self.pools = Pools(cluster)
        self.location = location

    def expected(self):
        vms = self.directory.list_virtual_machines(self.location)
        rgs = set(vm['parameters']['resource_group'] for vm in vms)
        if not len(rgs):
            raise RuntimeError('no RGs returned -- directory ok?')
        return rgs

    def actual(self):
        return set(p for p in self.pools.names()
                   if p not in self.PROTECTED_POOLS)

    def ensure(self):
        exp = self.expected()
        act = self.actual()
        for pool in exp - act:
            print('creating pool {}'.format(pool))
            self.pools.create(pool)
        for pool in act - exp:
            print('deleting pool {}'.format(pool))
            self.pools[pool].delete()
            return


class PgNumPolicy(object):
    """The number of PGs per pool must scale with the amount of data.

    If the total size of all images contained in a pool exceed the
    defined ratio per PG, the number of PGs will be doubled. Also ensure
    minimum pgs and pool flags whose defaults may have changed over
    time.
    """

    def __init__(self, gb_per_pg, ceph):
        self.gb_per_pg = gb_per_pg
        self.ceph = ceph

    def ensure_minimum_pgs(self, pool):
        min_pgs = self.ceph.default_pg_num()
        print('Pool {}: pg_num={} is below min_pgs={}, adding PGs'.format(
            pool.name, pool.pg_num, min_pgs))
        pool.pg_num = min_pgs
        pool.fix_options()

    def ensure_ratio(self, pool):
        print('Pool {}: size={} / pg_num={} ratio is above {}, adding PGs'.
              format(pool.name, pool.size_total_gb, pool.pg_num,
                     self.gb_per_pg))
        # round up to the nearest power of two
        pool.pg_num = 2 ** math.frexp(pool.pg_num + 1)[1]
        pool.fix_options()

    def ensure_pgp_count(self, pool):
        """Align pgp_num with pg_num.

        This should normally not be necessary, but it is possible that
        ensure_ratio hits a timeout before all PG have been created. In
        this case, pgp_num is left less than pg_num and needs to be
        fixed in a future run.
        """
        print('Pool {}: pgp_num={} < pg_num={}, fixing'.format(
            pool.name, pool.pgp_num, pool.pg_num))
        pool.pgp_num = pool.pg_num

    def ensure(self):
        """Go through pool in random order and fix pg levelling.

        We pick a subset of all pools and stop if we change something.
        This one-at-a-time approach avoids cluster overload from too
        many concurrent backfills.
        """
        pools = Pools(self.ceph)
        poolnames = list(pools.names())
        random.shuffle(poolnames)
        for poolname in poolnames[0:25]:
            pool = pools[poolname]
            ratio = float(pool.size_total_gb) / float(pool.pg_num)
            if pool.pgp_num < pool.pg_num:
                self.ensure_pgp_count(pool)
                return
            elif pool.pg_num < self.ceph.default_pg_num():
                self.ensure_minimum_pgs(pool)
                return
            elif ratio > self.gb_per_pg:
                self.ensure_ratio(pool)
                return


def pg_num():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('-n', '--dry-run', help='show what would be done only',
                   default=False, action='store_true')
    p.add_argument('-r', '--gb-per-pg', metavar='RATIO', type=float,
                   default=16.0, help='Adjust pg_num so that there are at most'
                   ' RATIO GiB data per PG (default: %(default)s)')
    p.add_argument('-c', '--conf', default='/etc/ceph/ceph.conf',
                   help='path to ceph.conf (default: %(default)s)')
    p.add_argument('-i', '--id', default='admin', metavar='USER',
                   help='rados user (without the "client." prefix) to '
                   'authenticate as (default: %(default)s)')
    args = p.parse_args()
    ceph = Cluster(args.conf, args.id, args.dry_run)
    pgnp = PgNumPolicy(args.gb_per_pg, ceph)
    pgnp.ensure()


class VolumeDeletions(object):

    def __init__(self, directory, cluster):
        self.directory = directory
        self.pools = Pools(cluster)

    def ensure(self):
        deletions = self.directory.deletions('vm')
        for name, node in deletions.items():
            # This really depends on the VM names adhering to our policy of
            # <rg>[0-9]{2}
            pool = self.pools[name[:-2]]
            try:
                images = list(pool.images)
            except KeyError:
                # The pool doesn't exist. Ignore. Nothing to delete anyway.
                continue
            if 'hard' in node['stages']:
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
                        print("Purging snapshot {}".format(image))
                        pool.snap_rm(rbd_image)
                    if base_image is None:
                        continue
                    print("Purging volume {}".format(image))
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
