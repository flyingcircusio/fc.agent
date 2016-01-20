import bz2
import hashlib
import logging
import os.path
import rados
import rbd
import requests
import socket
import subprocess
import tempfile

logger = logging.getLogger(__name__)

CEPH_CLIENT = socket.gethostname()


class LockingError(Exception):
    pass


def download_and_uncompress_file(url):
    _, local_filename = tempfile.mkstemp()
    r = requests.get(url, stream=True)
    r.raise_for_status()
    decomp = bz2.BZ2Decompressor()
    sha256 = hashlib.sha256()
    with open(local_filename, 'wb') as f:
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
    return local_filename, sha256.hexdigest()


class BaseImage(object):

    hydra_branch_url = 'https://hydra.flyingcircus.io/channels/branches/{}'
    image_pool = 'rbd'

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
            self.rbd.create(self.ioctx, self.branch, 10)
        self.image = rbd.Image(self.ioctx, self.branch)

        # Ensure we have a lock - stop handling for this image
        # and clean up (exceptions in __enter__ do not automatically
        # cause __exit__ being called).
        try:
            self.image.lock_exclusive('update')
        except (rbd.ImageBusy, rbd.ImageExists):
            # Someone is already updating. Ignore.
            logger.info('Image {} already locked -- update in progress '
                        'elsewhere?'.format(self.branch))
            self.__exit__()
            raise LockingError()

        return self

    def __exit__(self, *args, **kw):
        try:
            self.image.close()
        except Exception:
            pass
        try:

            self.ioctx.close()
        except Exception:
            pass
        self.cluster.shutdown()

    def _snapshot_names(self, image):
        return [x['name'] for x in image.list_snaps()]

    def update(self):
        image_file = ''
        try:
            try:
                # The branch URL is expected to be a redirect to a specific
                # release. This helps us to download atomic updates where Hydra
                # finishing in the middle won't have race conditions with us
                # sending multiple requests.
                release = requests.get(
                    self.hydra_branch_url.format(self.branch),
                    allow_redirects=False)
                assert release.status_code in [301, 302], release.status_code
                release_url = release.headers['Location']
                release = os.path.basename(release_url)
                logger.info("\t Release: {}".format(release_url))
                url = release_url + '/fc-vm-base-image-x86_64-linux.qcow2.bz2'
                checksum = requests.get(url + '.sha256')
                checksum.raise_for_status()
                checksum = checksum.text.strip()
                snapshot_name = 'base-{}'.format(release)
                current_snapshots = self._snapshot_names(self.image)
                logger.info('\t Have releases: \n\t\t{}'.format(
                    '\n\t\t'.join(current_snapshots)))
                if snapshot_name in self._snapshot_names(self.image):
                    # All good. No need to update.
                    return

                logger.info('\tDownloading release {} ...'.format(release))
                # I tried doing this on the fly, but seeking to find the true
                # size of the image is really slow. Also, we can verify the
                # hash faster this way -- no need to write data into Ceph
                # unnecessarily.
                image_file, image_hash = download_and_uncompress_file(url)

                # Verify content
                if image_hash != checksum:
                    raise ValueError(
                        "Image had checksum {} but expected {}. "
                        "Aborting.".format(image_hash, checksum))

                # Store in ceph
                info = subprocess.check_output(
                    ['qemu-img', 'info', image_file])
                for line in info.decode('ascii').splitlines():
                    line = line.strip()
                    if line.startswith('virtual size:'):
                        size = line.split()[3]
                        assert size.startswith('(')
                        size = int(size[1:])
                        break
                self.image.resize(size)

                logger.info('\tStoring release in Ceph RBD volume ...')
                try:
                    target = subprocess.check_output(
                        ['rbd', '--id', CEPH_CLIENT, 'map',
                         '{}/{}'.format(self.image_pool, self.branch)])
                    target = target.strip()
                    # qemu-img can convert directly to rbd, however, this
                    # doesn't work under some circumstances, like the image
                    # already existing, which is why we choose to map and use
                    # the raw converter.
                    subprocess.check_call(
                        ['qemu-img', 'convert', '-n', '-f', 'qcow2',
                         image_file, '-O', 'raw', target])
                finally:
                    subprocess.check_call(
                        ['rbd', '--id', CEPH_CLIENT, 'unmap', target])
                # Create new snapshot and protect it so we can clone from it.
                self.image.create_snap(snapshot_name)
                self.image.protect_snap(snapshot_name)
            finally:
                self.image.unlock('update')
        finally:
            if os.path.exists(image_file):
                os.unlink(image_file)

    def flatten(self):
        for snap in self.image.list_snaps():
            snap = rbd.Image(self.ioctx, self.branch, snap['name'])
            for child_pool, child_image in snap.list_children():
                logger.info('\t Flattening {}/{}'.format(
                    child_pool, child_image))
                try:
                    pool = self.cluster.open_ioctx(child_pool)
                    image = rbd.Image(pool, child_image)
                    image.flatten()
                except:
                    logger.exception("Error trying to flatten {}/{}".format(
                                     child_pool, child_image))
                finally:
                    pool.close()

    def purge(self):
        # Delete old images, but keep the last three.
        #
        # Keeping a few is good because there may be race conditions that
        # images are currently in use even after we called flatten. (This
        # is what unprotect does, but there is no way to run flatten/unprotect
        # in an atomic fashion. However, we expect all clients to always use
        # the newest one. So, the race condition that remains is that we just
        # downloaded a new image and someone else created a VM while we added
        # it and didn't see the new snapshot, but we already were done
        # flattening. Keeping 3 should be more than sufficient.
        #
        # If the ones we want to purge won't work, then we just ignore that
        # for now.
        #
        # The CLI returns snapshots in their ID order (which appears to be
        # guaranteed to increase) but the API isn't documented. Lets order
        # them ourselves to ensure reliability.
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
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    logging.getLogger("requests").setLevel(logging.WARNING)

    for branch in ['fc-15.09-dev', 'fc-15.09-staging', 'fc-15.09-production']:
        logger.info('Updating branch {}'.format(branch))
        try:
            with BaseImage(branch) as image:
                image.update()
                image.flatten()
                image.purge()
        except LockingError:
            # This is expected and should be silent. Someone else is updating
            # this branch at the moment.
            pass
        except Exception:
            logger.exception(
                "An error occured while updating branch `{}`".format(branch))
