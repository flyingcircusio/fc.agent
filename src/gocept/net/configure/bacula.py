import glob
import gocept.net.directory
import logging
import os
import os.path

logger = logging.getLogger()

ROOT = ''


def purge_stamps():
    with gocept.net.directory.exceptions_screened():
        d = gocept.net.directory.Directory()
        deletions = d.deletions('vm')
    files = []
    for name, node in deletions.items():
        if 'soft' in node['stages']:
            files.append('/var/lib/bacula/stamps/*/Backup-{}'.format(name))
        if 'hard' in node['stages']:
            files.append('/etc/bacula/clients/{}.conf'.format(name))
            files.append('/etc/bacula/clients/job.{}.conf'.format(name))

    for candidate in files:
        candidate = ROOT + candidate
        for file in glob.glob(candidate):
            try:
                os.unlink(file)
            except Exception, e:
                logger.exception(e)
