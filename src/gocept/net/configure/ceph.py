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

    def __init__(self, directory, cluster):
        self.directory = directory
        self.pools = Pools(cluster)

    def expected(self):
        rgs = self.directory.list_resource_groups()
        if len(rgs) < 1:
            raise RuntimeError('no RGs returned -- directory ok?')
        return set(rgs)

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
            print('should be deleting pool {} (disabled)'.format(pool))


def pools():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('-n', '--dry-run', help='show what would be done only',
                   default=False, action='store_true')
    p.add_argument('-c', '--conf', default='/etc/ceph/ceph.conf',
                   help='path to ceph.conf (default: %(default)s)')
    p.add_argument('-i', '--id', default='admin', metavar='USER',
                   help='rados user (without the "client." prefix) to '
                   'authenticate as (default: %(default)s)')
    args = p.parse_args()
    ceph = Cluster(args.conf, args.id, args.dry_run)
    with gocept.net.directory.exceptions_screened():
        rpe = ResourcegroupPoolEquivalence(
            gocept.net.directory.Directory(), ceph)
        rpe.ensure()


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

    def ensure(self):
        """Go through pool in random order and fix pg levelling.

        We pick a subset of all pools and stop if we change something.
        This one-at-a-time approach avoids cluster overload from too
        many concurrent backfills.
        """
        pools = Pools(self.ceph)
        poolnames = list(pools.names())
        random.shuffle(poolnames)
        for poolname in poolnames[0:50]:
            pool = pools[poolname]
            ratio = float(pool.size_total_gb) / float(pool.pg_num)
            if pool.pg_num < self.ceph.default_pg_num():
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
                   default=4.0, help='Adjust pg_num so that there are at most '
                   'RATIO GiB data per PG (default: %(default)s)')
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
        self.cluster = cluster
        self.pools = Pools(self.cluster)

    def ensure(self):
        deletions = self.directory.deletions('vm')
        for name, node in deletions.items():
            # This really depends on the VM names adhering to our policy of
            # <rg>[0-9]{2}
            pool = self.pools[name[:-2]]
            if 'purge' in node['stages']:
                for image in ['{}.root', '{}.swap', '{}.tmp']:
                    image = image.format(name)
                    try:
                        image = pool[image]
                    except KeyError:
                        # Already deleted
                        pass
                    else:
                        pool.image_rm(image)


def purge_volumes():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('-n', '--dry-run', help='show what would be done only',
                   default=False, action='store_true')
    p.add_argument('-c', '--conf', default='/etc/ceph/ceph.conf',
                   help='path to ceph.conf (default: %(default)s)')
    p.add_argument('-i', '--id', default='admin', metavar='USER',
                   help='rados user (without the "client." prefix) to '
                   'authenticate as (default: %(default)s)')
    args = p.parse_args()
    ceph = Cluster(args.conf, args.id, args.dry_run)
    with gocept.net.directory.exceptions_screened():
        volumes = VolumeDeletions(gocept.net.directory.Directory(), ceph)
        volumes.ensure()
