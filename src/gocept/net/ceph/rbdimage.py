"""Value object to represent an individual RBD image"""

import collections
import datetime
import re


class RBDImage(collections.namedtuple('RBDImage', [
        'image', 'size', 'format', 'lock_type', 'snapshot', 'protected'])):
    """Represents a single RBD image from the pool listing."""

    def __new__(_cls, image, size, format=1, lock_type=None, snapshot=None,
                protected=None):
        protected = protected in ['true', 'True']
        return super(RBDImage, _cls).__new__(
            _cls, image, size, format, lock_type, snapshot, protected)

    @classmethod
    def from_dict(cls, params):
        """Construct from dict as returned by `rbd ls --format=json`."""
        return cls(params['image'], params['size'], params.get('format', 1),
                   params.get('lock_type', None), params.get('snapshot', None),
                   params.get('protected', None))

    @property
    def name(self):
        """Display name (depends on whether this is a snapshot)."""
        if self.snapshot:
            return self.image + '@' + self.snapshot
        return self.image

    @property
    def size_gb(self):
        return int(round(self.size / 2**30))

    r_snapshot_keep_until = re.compile(r'-keep-until-(\d{8})$')

    @property
    def is_outdated_snapshot(self):
        """Returns True if this snapshot shouldn't be kept anymore."""
        if not self.snapshot or self.lock_type or self.protected:
            return False
        match = self.r_snapshot_keep_until.search(self.snapshot)
        if match:
            d = datetime.datetime.strptime(match.group(1), '%Y%m%d')
            date = datetime.date(d.year, d.month, d.day)
            return date < datetime.date.today()
