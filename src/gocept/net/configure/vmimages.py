import bz2
import contextlib
import hashlib
import logging
import os
import os.path as p
import rados
import rbd
import requests
import socket
import subprocess
import sys
import tempfile
import time

RELEASES = ['fc-15.09-dev', 'fc-15.09-staging', 'fc-15.09-production']
CEPH_CLIENT = socket.gethostname()
LOCK_COOKIE = '{}.{}'.format(CEPH_CLIENT, os.getpid())

logger = logging.getLogger(__name__)


class LockingError(Exception):
    pass


def download_and_uncompress_file(url):
    logging.debug('\t\tGet %s', url)
    r = requests.get(url, stream=True)
    r.raise_for_status()
    decomp = bz2.BZ2Decompressor()
    sha256 = hashlib.sha256()
    with tempfile.NamedTemporaryFile(mode='wb', suffix='.bz2',
                                     prefix='vm-image.', delete=False) as f:
        for bz2chunk in r.iter_content(chunk_size=64 * 1024):
            if not bz2chunk:
                # filter out keep-alive chunk borders
                continue
            sha256.update(bz2chunk)
            try:
                chunk = decomp.decompress(bz2chunk)
                if chunk:
                    f.write(chunk)
            except EOFError:
                break
        f.flush()
        logging.debug('\t\tSaving to %s', f.name)
        return f.name, sha256.hexdigest()


def delta_update(from_, to):
    """Update changed blocks between image files.

    We assume that one generation of a VM image does not differ
    fundamentatlly from the generation before. We only update
    changed blocks. Additionally, we use a stuttering technique to
    improve fairness.
    """
    blocksize = 64 * 1024
    total = 0
    written = 0
    with open(from_, 'rb') as source:
        with open(to, 'r+b') as dest:
            while True:
                a = source.read(blocksize)
                if not a:
                    break
                total += 1
                b = dest.read(blocksize)
                if a != b:
                    dest.seek(-len(a), os.SEEK_CUR)
                    dest.write(a)
                    written += 1
                time.sleep(1e-4)
    logger.debug('delta_update: %d/%d 64k blocks updated (%d%%)',
        written, total, 100 * written / (max(total, 1)))


class BaseImage(object):

    hydra_branch_url = 'https://hydra.flyingcircus.io/channels/branches/{}'
    image_pool = 'rbd.hdd'
    image_file = None

    def __init__(self, branch):
        self.branch = branch

    # Context manager: maintain ceph connection, ensure existence of
    # image and keep a lock.

    def __enter__(self):
        self.cluster = rados.Rados(conffile='/etc/ceph/ceph.conf',
                                   name='client.{}'.format(CEPH_CLIENT))
        self.cluster.connect()
        self.ioctx = self.cluster.open_ioctx(self.image_pool)
        self.rbd = rbd.RBD()

        # Ensure the image exists.
        if self.branch not in self.rbd.list(self.ioctx):
            logger.info('Creating image for {}'.format(self.branch))
            self.rbd.create(self.ioctx, self.branch, 10 * 2**30)
        self.image = rbd.Image(self.ioctx, self.branch)

        # Ensure we have a lock - stop handling for this image
        # and clean up (exceptions in __enter__ do not automatically
        # cause __exit__ being called).
        logger.debug('Locking image %s', self.image.name)
        try:
            self.image.lock_exclusive(LOCK_COOKIE)
        except rbd.ImageBusy:
            self.force_unlock_if_dead_client()
            try:
                self.image.lock_exclusive(LOCK_COOKIE)
            except Exception:
                logger.error('Could not lock image %s', self.image.name)
                raise LockingError()
        except rbd.ImageExists:
            # _We_ locked the image. Proceed.
            pass

        return self

    def __exit__(self, *args, **kw):
        if self.image_file and p.exists(self.image_file):
            os.unlink(self.image_file)
        try:
            logger.debug('Unlocking image %s', self.branch)
            self.image.unlock(LOCK_COOKIE)
        except Exception:
            logger.exception()
        self.image.close()
        self.ioctx.close()
        self.cluster.shutdown()

    def force_unlock_if_dead_client(self):
        l = self.image.list_lockers()
        if not l:
            return
        logger.debug('Examining lock on image %s (%r)',
                     self.image.name, l)
        client, cookie, _addr = l['lockers'][0]  # excl -> max one lock
        try:
            otherhost, otherpid = cookie.split('.', 1)
            otherpid = int(otherpid)
        except (IndexError, ValueError):
            logger.error('Failed to parse lock cookie %s', cookie)
            raise LockingError()
        if otherhost != CEPH_CLIENT:
            return
        try:
            os.kill(otherpid, 0)
            logger.warn('Lock held by process %d -- still alive', otherpid)
        except OSError:
            # no such process
            logger.debug('Save to break lock')
            self.image.break_lock(client, cookie)

    def _snapshot_names(self, image):
        return [x['name'] for x in image.list_snaps()]

    def current_release(self):
        """Get release identifier and URL to channel downloads."""
        # The branch URL is expected to be a redirect to a specific
        # release. This helps us to download atomic updates where Hydra
        # finishing in the middle won't have race conditions with us
        # sending multiple requests.
        release = requests.get(
            self.hydra_branch_url.format(self.branch),
            allow_redirects=False)
        assert release.status_code in [301, 302], release.status_code
        release_url = release.headers['Location']
        release_id = p.basename(release_url)
        return release_id, release_url

    def download_image(self, release_url):
        image_url = release_url + '/fc-vm-base-image-x86_64-linux.qcow2.bz2'
        self.image_file, image_hash = download_and_uncompress_file(image_url)
        checksum = requests.get(image_url + '.sha256')
        checksum.raise_for_status()
        checksum = checksum.text.strip()
        if image_hash != checksum:
            raise ValueError(
                "Image had checksum {} but expected {}. "
                "Aborting.".format(image_hash, checksum))
        return True

    def image_size(self):
        # Expects self.image_file to have been downloaded and verified.
        info = subprocess.check_output(
            ['qemu-img', 'info', self.image_file])
        for line in info.decode('ascii').splitlines():
            line = line.strip()
            if line.startswith('virtual size:'):
                size = line.split()[3]
                assert size.startswith('(')
                size = int(size[1:])
                break
        assert size > 0
        return size

    @property
    def volume(self):
        return '{}/{}'.format(self.image_pool, self.branch)

    @contextlib.contextmanager
    def mapped(self):
        dev = subprocess.check_output(['rbd', '--id', CEPH_CLIENT, 'map',
                                       self.volume])
        dev = dev.decode().strip()
        try:
            yield dev
        finally:
            subprocess.check_call(['rbd', '--id', CEPH_CLIENT, 'unmap', dev])

    def store_in_ceph(self):
        """Updates image data.

        qemu-img can convert directly to rbd, however, this
        doesn't work under some circumstances, like the image
        already existing etc.
        """
        with tempfile.NamedTemporaryFile(prefix='vm-bounce.') as bounce:
            size = self.image_size()
            self.image.resize(size)
            bounce.truncate(size)
            subprocess.check_call([
                'qemu-img', 'convert', '-n', '-fqcow2', self.image_file,
                '-Oraw', bounce.name])
            os.unlink(self.image_file)
            self.image_file = None
            bounce.seek(0)
            with self.mapped() as blockdev:
                delta_update(bounce.name, blockdev)

    def update(self):
        release, release_url = self.current_release()

        # Check whether the expected snapshot already exists.
        snapshot_name = 'base-{}'.format(release)
        current_snapshots = self._snapshot_names(self.image)

        if snapshot_name in self._snapshot_names(self.image):
            # All good. No need to update.
            return

        logger.info('\tHave releases: \n\t\t{}'.format(
            '\n\t\t'.join(current_snapshots)))
        logger.info('\tDownloading release {}'.format(release))
        try:
            self.download_image(release_url)
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                logger.warn('Ignoring missing image. Hydra was probably lazy.')
                return False

        logger.info('\tStoring in volume {}/{}'.format(
            self.image_pool, self.branch))
        self.store_in_ceph()

        # Create new snapshot and protect it so we can clone from it.
        logger.info('\tCreating snapshot {}'.format(snapshot_name))
        self.image.create_snap(snapshot_name)
        self.image.protect_snap(snapshot_name)
        self.flatten()
        self.purge()

    def flatten(self):
        """Decouple VMs created from their base snapshots."""
        logger.debug('\tFlattening child images')
        for snap in self.image.list_snaps():
            snap = rbd.Image(self.ioctx, self.branch, snap['name'])
            for child_pool, child_image in snap.list_children():
                logger.info('\tFlattening {}/{}'.format(
                    child_pool, child_image))
                try:
                    pool = self.cluster.open_ioctx(child_pool)
                    image = rbd.Image(pool, child_image)
                    image.flatten()
                except:
                    logger.exception("Error trying to flatten {}/{}".format(
                                     child_pool, child_image))
                finally:
                    image.close()
                    pool.close()

    def purge(self):
        """
        Delete old images, but keep the last three.

        Keeping a few is good because there may be race conditions that
        images are currently in use even after we called flatten. (This
        is what unprotect does, but there is no way to run flatten/unprotect
        in an atomic fashion. However, we expect all clients to always use
        the newest one. So, the race condition that remains is that we just
        downloaded a new image and someone else created a VM while we added
        it and didn't see the new snapshot, but we already were done
        flattening. Keeping 3 should be more than sufficient.

        If the ones we want to purge won't work, then we just ignore that
        for now.

        The CLI returns snapshots in their ID order (which appears to be
        guaranteed to increase) but the API isn't documented. Lets order
        them ourselves to ensure reliability.
        """
        snaps = list(self.image.list_snaps())
        snaps.sort(key=lambda x: x['id'])
        for snap in snaps[:-3]:
            logger.info('\tPurging snapshot {}/{}@{}'.format(
                self.image_pool, self.branch, snap['name']))
            try:
                self.image.unprotect_snap(snap['name'])
                self.image.remove_snap(snap['name'])
            except:
                logger.exception('Error trying to purge snapshot:')


def update():
    try:
        if int(os.environ.get('VERBOSE', 0)):
            level = logging.DEBUG
        else:
            level = logging.INFO
    except Exception:
        level = logging.INFO

    logging.basicConfig(level=level, format='%(message)s')
    logging.getLogger("requests").setLevel(logging.WARNING)
    try:
        for branch in RELEASES:
            logger.info('Updating branch {}'.format(branch))
            with BaseImage(branch) as image:
                image.update()
    except LockingError:
        sys.exit(1)
    except Exception:
        logger.exception(
            "An error occured while updating branch `{}`".format(branch))
        sys.exit(1)
