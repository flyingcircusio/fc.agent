"""Helpers for accessing and manipulating local passwd files."""

import cStringIO
import datetime
import difflib
import gocept.net.utils
import locale
import os
import time


def check_link_count(file):
    # Copied from check_link_count in commonio.c from shadow library
    try:
        sb = os.stat(file)
    except Exception:
        return 0
    if sb.st_nlink != 2:
        return 0
    return 1


class Database(object):

    def __init__(self, path):
        self.path = path
        self.open()

    def open(self):
        self.lock()
        self.records = []
        for line in open(self.path):
            line = line.rstrip()
            self.records.append(self.factory.fromString(line))

    def close(self):
        self.unlock()
        del self.records

    def _dump(self):
        output = cStringIO.StringIO()
        for record in self.records:
            output.write(record.toString() + '\n')
        output.seek(0)
        return output

    def diff(self):
        new = self._dump()
        old = open(self.path, 'r')
        delta = difflib.unified_diff(
            old.readlines(), new.readlines(), "old", "new")
        old.close()
        return list(delta)

    def save(self):
        # We need to assemble the contents of the file first, otherwise
        # opening it for writing and then failing will cause it to become
        # empty.
        if self.diff():
            f = open(self.path, 'w')
            f.write(self._dump().getvalue())
            f.close()

    def unlock(self):
        os.unlink(self.path + '.lock')

    def get(self, key, create=False):
        for item in self.records:
            if getattr(item, self.factory.key) == key:
                return item
        if create:
            item = self.factory(key)
            self.records.append(item)
            return item
        raise KeyError(key)

    def lock(self):
        # This locking is re-implemented emulating the locking of
        # shadow library's `commonio.c`.
        file = "%s.%lu" % (self.path, os.getpid())
        lock = "%s.lock" % self.path

        # fd = open (file, O_CREAT | O_EXCL | O_WRONLY, 0600);
        # if (-1 == fd) {
        #         return 0;
        # }
        fd = os.open(file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0600)

        # pid = getpid ();
        # snprintf (buf, sizeof buf, "%lu", (unsigned long) pid);
        # len = (ssize_t) strlen (buf) + 1;
        pid = os.getpid()
        buf = str(pid)

        # if (write (fd, buf, (size_t) len) != len) {
        #         (void) close (fd);
        #         unlink (file);
        #         return 0;
        # }
        # close (fd);
        try:
            failure = (os.write(fd, buf) != len(buf))
        except Exception:
            failure = True
        if failure:
            os.close(fd)
            os.unlink(file)
            raise RuntimeError()

        # if (link (file, lock) == 0) {
        #         retval = check_link_count (file);
        #         unlink (file);
        #         return retval;
        # }
        try:
            os.link(file, lock)
        except Exception:
            pass
        else:
            success = check_link_count(file)
            os.unlink(file)
            if not success:
                raise RuntimeError()
            return

        # fd = open (lock, O_RDWR);
        # if (-1 == fd) {
        #         unlink (file);
        #         errno = EINVAL;
        #         return 0;
        # }
        try:
            fd = os.open(lock, os.O_RDWR)
        except Exception:
            os.unlink(file)
            raise

        # len = read (fd, buf, sizeof (buf) - 1);
        # close (fd);
        # if (len <= 0) {
        #         unlink (file);
        #         errno = EINVAL;
        #         return 0;
        # }
        # buf[len] = '\0';
        buf = os.read(fd, 31)
        os.close(fd)
        if not buf:
            os.unlink(file)
            raise RuntimeError()

        # if (get_pid (buf, &pid) == 0) {
        #         unlink (file);
        #         errno = EINVAL;
        #         return 0;
        # }
        try:
            pid = int(buf)
        except:
            os.unlink(file)
            raise RuntimeError('EINVAL')

        # if (kill (pid, 0) == 0) {
        #         unlink (file);
        #         errno = EEXIST;
        #         return 0;
        # }
        try:
            os.kill(pid, 0)
        except:
            pass
        else:
            os.unlink(file)
            raise RuntimeError('EEXISTS')

        # if (unlink (lock) != 0) {
        #         unlink (file);
        #         return 0;
        # }
        try:
            os.unlink(lock)
        except:
            os.unlink(file)
            raise

        # retval = 0;
        # if ((link (file, lock) == 0) && (check_link_count (file) != 0)) {
        #         retval = 1;
        # }
        #
        # unlink (file);
        # return retval;
        try:
            os.link(file, lock)
        except:
            os.unlink(file)
            raise
        if not check_link_count(file):
            os.unlink(file)
            raise RuntimeError()
        os.unlink(file)


class DatabaseEntry(object):

    fields = ()

    @classmethod
    def fromString(cls, data):
        data = data.split(':')
        if len(data) != len(cls.fields):
            raise RuntimeError('mismatching record length', data, cls.fields)
        data = dict(zip(cls.fields, data))
        entry = cls(data.pop(cls.key))
        for key, value in data.items():
            setattr(entry, key, value)
        return entry

    def toString(self):
        return ':'.join(getattr(self, field) for field in self.fields)


class PasswdEntry(DatabaseEntry):

    fields = ['login_name',
              'password',
              'uid',
              'gid',
              'gecos',
              'home',
              'shell']

    key = 'login_name'

    def __init__(self, login_name):
        self.login_name = login_name
        self.password = 'x'
        self.gecos = ''
        self.shell = '/bin/bash'


class Passwd(Database):

    factory = PasswdEntry


class GroupEntry(DatabaseEntry):

    fields = ['group',
              'password',
              'gid',
              'members']

    key = 'group'

    def __init__(self, group):
        self.group = group
        self.password = 'x'
        self.members = ''

    def add_members(self, *new_members):
        members = set(self.members.split(','))
        members.update(new_members)
        members = members - set([''])
        self.members = ','.join(sorted(members))


class Group(Database):

    factory = GroupEntry


class ShadowEntry(DatabaseEntry):

    fields = ['login',
              'password',
              'lastchange',
              'nextchange_min',
              'nextchange_max',
              'expire_warn',
              'until_inactive',
              'until_expire',
              'reserved']

    key = 'login'
    epoch = datetime.date(1970, 1, 1).toordinal()

    def __init__(self, login):
        self.login = login
        self.lastchange = str(gocept.net.utils.now().toordinal() - self.epoch)
        self.nextchange_min = '0'
        self.nextchange_max = '99999'
        self.expire_warn = '7'
        self.until_inactive = ''
        self.until_expire = ''
        self.reserved = ''


class Shadow(Database):

    factory = ShadowEntry
