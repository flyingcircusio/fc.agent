"""Resize root filesystem if needed."""

from __future__ import print_function
import os
import re
import subprocess


class Disk(object):
    # 5G disk size granularity -> 2.5G sampling -> 512 byte sectors
    FREE_SECTOR_THRESHOLD = (5 * (1024 * 1024 * 1024) / 2) / 512

    def __init__(self, dev):
        self.dev = dev
        self.sgdisk_out = None

    def check_gpt(self):
        for i in range(0, 3):
            self.sgdisk_out = subprocess.check_output([
                'sgdisk', '-v', self.dev]).decode()
            if not 'Problem: The secondary' in self.sgdisk_out:
	        return
            subprocess.check_call(['sgdisk', '-e', self.dev])
	raise RuntimeError('Unable to fix GPT disk layout')

    r_free = re.compile(r'\s([0-9]+) free sectors')

    def free_sectors(self):
        if not self.sgdisk_out:
            raise RuntimeError('must call check_gpt() first')
        free = self.r_free.search(self.sgdisk_out)
        return(int(free.group(1)))

    def grow_partition(self):
        partx = subprocess.check_output(['partx', '-r', self.dev]).decode()
        first_sector = partx.splitlines()[1].split()[1]
        subprocess.check_call([
            'sgdisk', self.dev, '-d', '1',
            '-n', '1:{}:0'.format(first_sector), '-c', '1:root',
            '-t', '1:8300'])

    def resize_partition(self):
        partx = subprocess.check_output(['partx', '-r', self.dev]).decode()
        partition_size = partx.splitlines()[1].split()[3]   # sectors
        subprocess.check_call(['resizepart', self.dev, '1', partition_size])
        subprocess.check_call(['resize2fs', '{}1'.format(self.dev)])


    def grow(self):
        self.check_gpt()
        free = self.free_sectors()
        if free > self.FREE_SECTOR_THRESHOLD:
            print('{} free sectors on {}, growing'.format(free, self.dev))
            self.grow_partition()
            self.resize_partition()


def check_grow():
    # expects /etc/local/boot.conf to be sourced into the environment
    d = Disk(os.environ['SYSDISK'])
    d.grow()
