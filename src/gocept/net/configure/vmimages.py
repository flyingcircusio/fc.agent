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


def download_and_uncompress_file(url):
    _, local_filename = tempfile.mkstemp()
    r = requests.get(url, stream=True)
    r.raise_for_status()
    decomp = bz2.BZ2Decompressor()
    sha256 = hashlib.sha256()
    with open(local_filename, 'wb') as f:
        for bz2chunk in r.iter_content(chunk_size=64*1024): 
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

    def __init__(self, branch):
        self.branch = branch

    def __enter__(self):
        self.cluster = rados.Rados(conffile='/etc/ceph/ceph.conf', name='client.{}'.format(CEPH_CLIENT))
        self.cluster.connect()
        self.ioctx = self.cluster.open_ioctx('services')
        self.rbd = rbd.RBD()
        return self

    def __exit__(self, *args, **kw):
        try:
            self.ioctx.close()
        except Exception:
            pass
        self.cluster.shutdown()

    def _snapshot_names(self, image):
        return [x['name'] for x in image.list_snaps()]

    def flatten(self, snapshot):
        # nightly
        pass

    def purge(self):
        # delete all but keep last three
        # need to flatten them first.
        pass

    def update(self):
        if not self.branch in self.rbd.list(self.ioctx):
            logger.info('Creating image for {}'.format(branch))
            self.rbd.create(self.ioctx, self.branch, 10)
        image = rbd.Image(self.ioctx, self.branch)
        image_file = ''
        try:
            try:
                image.lock_exclusive('update')
            except (rbd.ImageBusy, rbd.ImageExists):
                # Someone is already updating. Ignore.
                logger.info('Image {} already locked -- update in progress elsewhere?'.format(self.branch))
                return
            try:
                logger.info('Checking for current release ...')
		# The branch URL is expected to be a redirect to a specific release. This helps us to download atomic
		# updates where Hydra finishing in the middle won't have race conditions with us sending multiple requests.
		release = requests.get('https://hydra.flyingcircus.io/channels/branches/{}'.format(self.branch), allow_redirects=False)
		assert release.status_code in [301, 302], release.status_code
		release_url = release.headers['Location']
		print "Release:", release_url
                url = release_url + '/fc-vm-base-image-x86_64-linux.qcow2.bz2'
                checksum = requests.get(url+'.sha256')
                checksum.raise_for_status()
                checksum = checksum.text.strip()
                snapshot_name = 'base-{}'.format(checksum)
                if snapshot_name in self._snapshot_names(image):
                    logger.info('Snapshot is current. Nothing to do.')
                    # All good. No need to update.
                    return

                logger.info('Snapshot is not current. Updating.')
                # I tried doing this on the fly, but seeking to find the true size
                # of the image is really slow. Also, we can verify the hash
                # faster this way -- no need to write data into Ceph unnecessarily.
                logger.info('Downloading, uncompressing, and verifying integrity ...')
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
                image.resize(size)

                logger.info('Storing into ceph ...')
                try:
                    target = subprocess.check_output(
                        ['rbd', '--id', CEPH_CLIENT, 'map', 'services/{}'.format(self.branch)])
                    target = target.strip()
                    #subprocess.check_call(
                    #    ['qemu-img', 'convert', '-n', '-f', 'qcow2', image_file,
                    #     'rbd:services/{}:id=CEPH_CLIENT'.format(self.branch)])
                    subprocess.check_call(
                        ['qemu-img', 'convert', '-n', '-f', 'qcow2', image_file,
                         '-O', 'raw', target])
                finally:
                    subprocess.check_call(['rbd', '--id', CEPH_CLIENT, 'unmap', target])
                # Create new snapshot and protect it so we can clone from it.
                logger.info('Creating and protecting snapshot ...')
                image.create_snap(snapshot_name)
                image.protect_snap(snapshot_name)
            finally:
                image.unlock('update')
        finally:
            if os.path.exists(image_file):
                os.unlink(image_file)
            image.close()


logging.basicConfig(level=logging.INFO)
for branch in ['fc-15.09-dev', 'fc-15.09-staging', 'fc-15.09-production']:
    try:
        with BaseImage(branch) as image:
            image.update()
            image.purge()
    except Exception:
        logger.exception("An error occured while updating for branch `{}`".format(branch))
