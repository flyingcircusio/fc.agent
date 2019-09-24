from gocept.net.configure.vmimages import _parse_qemu_image_size


def test_parse_qemu_image_size_qemu_4_1():
    output = """\
image: /tmp/vm-image.GAb8k_.qcow2
file format: qcow2
virtual size: 10 GiB (10737418240 bytes)
disk size: 2.8 GiB
cluster_size: 65536
Format specific information:
    compat: 1.1
    lazy refcounts: true
    refcount bits: 16
    corrupt: false
"""
    assert 10737418240 == _parse_qemu_image_size(output)
