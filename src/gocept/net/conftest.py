import pytest
import mock
import gocept.net.directory


@pytest.fixture
def directory(monkeypatch):
    directory = mock.Mock()
    monkeypatch.setattr(gocept.net.directory, 'Directory', directory)
    return directory
