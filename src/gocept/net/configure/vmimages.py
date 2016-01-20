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
                # filter out keep-alive new chunks
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
                logger.info('Checking for current release ...')
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
                print "Release:", release_url
                url = release_url + '/fc-vm-base-image-x86_64-linux.qcow2.bz2'
                checksum = requests.get(url + '.sha256')
                checksum.raise_for_status()
                checksum = checksum.text.strip()
                snapshot_name = 'base-{}'.format(release)
                current_snapshots = self._snapshot_names(self.image)
                logger.info('Existing snapshots :{}'.format(current_snapshots))
                logger.info('Expecting snapshot: {}'.format(snapshot_name))
                if snapshot_name in self._snapshot_names(self.image):
                    logger.info('Found snapshot. Nothing to do.')
                    # All good. No need to update.
                    return

                logger.info('Did not find snapshot. Updating.')
                # I tried doing this on the fly, but seeking to find the true
                # size of the image is really slow. Also, we can verify the
                # hash faster this way -- no need to write data into Ceph
                # unnecessarily.
                logger.info(
                    'Downloading, uncompressing, and verifying integrity ...')
                image_file, image_hash = download_and_uncompress_file(url)

                # Verify content
                if image_hash != checksum:
                    raise ValueError(
                        "Image had checksum {} but expected {}. "
                        "Aborting.".format(image_hash, checksum))

                # Store in ceph
                logger.info('Resizing ceph base image ...')
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

                logger.info('Storing into ceph ...')
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
                logger.info('Creating and protecting snapshot ...')
                self.image.create_snap(snapshot_name)
                self.image.protect_snap(snapshot_name)
            finally:
                self.image.unlock('update')
        finally:
            if os.path.exists(image_file):
                os.unlink(image_file)

    def flatten(self):
        logger.info('Flattening ...')
        for snap in self.image.list_snaps():
            snap = rbd.Image(self.ioctx, self.branch, snap['name'])
            for child_pool, child_image in snap.list_children():
                logger.info('Flattening {}/{}'.format(child_pool, child_image))
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
        logger.info('Purging ...')
        # Delete old images, but keep the last three.
        #
        # Keeping a few is good because there may be race conditions that
        # images are currently in use even after we called flatten. We expect
        # all clients to always use the newest one, so if we do not purge all
        # but keep a few then older ones should be reliably flattened by now.
        #
        # Note: images may not be flattened yet, even when we tried earlier
        # and we then just give up (for now).
        snaps = list(self.image.list_snaps())
        snaps.sort(key=lambda x: x['id'])
        for snap in snaps[:-1]:
            logger.info('Purging old snapshot {}/{}@{}'.format(
                self.image_pool, self.branch, snap['name']))
            try:
                self.image.unprotect_snap(snap['name'])
                self.image.remove_snap(snap['name'])
            except:
                logger.exception('Error trying to purge snapshot:')


FORMAT = '%(asctime)-15s %(message)s'


def main():
    logging.basicConfig(level=logging.INFO, format=FORMAT)
    logging.getLogger("requests").setLevel(logging.WARNING)

    for branch in ['fc-15.09-dev', 'fc-15.09-staging', 'fc-15.09-production']:
        logger.info('Updating branch {}'.format(branch))
        try:
            with BaseImage(branch) as image:
                image.update()
                image.flatten()
                image.purge()
        except LockingError:
            # This is expected and should be silent.
            pass
        except Exception:
            logger.exception(
                "An error occured while updating branch `{}`".format(branch))


if __name__ == '__main__':
    main()
