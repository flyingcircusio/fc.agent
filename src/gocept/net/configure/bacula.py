import glob
import gocept.net.directory
import logging
import os
import os.path

logger = logging.getLogger()


def purge_stamps():
    with gocept.net.directory.exceptions_screened():
        d = gocept.net.directory.Directory()
        deletions = d.deletions('vm')
    for name, node in deletions.items():
        if 'soft' in node['stages']:
            try:
                stamps = '/var/lib/bacula/stamps/*/Backup-{}'.format(name)
                for stamp in glob.glob(stamps):
                    os.unlink(stamp)
            except Exception, e:
                logger.exception(e)
