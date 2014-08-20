import pytest
import mock
import gocept.net.directory


@pytest.fixture
def directory(monkeypatch):
    monkeypatch.setattr(gocept.net.directory, 'Directory', mock.Mock())
