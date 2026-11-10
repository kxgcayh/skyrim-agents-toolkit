"""The session stops before the test temp folders fill the disk (conftest.pytest_runtest_setup)."""
from __future__ import annotations

from collections import namedtuple
from types import SimpleNamespace

import pytest

import conftest

GiB = 2**30
Usage = namedtuple("Usage", "total used free")


def _item(tmp_path):
    return SimpleNamespace(config=SimpleNamespace(option=SimpleNamespace(basetemp=str(tmp_path))))


def test_low_free_space_stops_the_session(tmp_path, monkeypatch):
    monkeypatch.setattr(conftest.shutil, "disk_usage", lambda p: Usage(500 * GiB, 490 * GiB, 10 * GiB))
    with pytest.raises(pytest.exit.Exception, match="GiB free"):
        conftest.pytest_runtest_setup(_item(tmp_path))


def test_enough_free_space_carries_on(tmp_path, monkeypatch):
    monkeypatch.setattr(conftest.shutil, "disk_usage", lambda p: Usage(500 * GiB, 100 * GiB, 400 * GiB))
    conftest.pytest_runtest_setup(_item(tmp_path))


def test_the_floor_is_20_percent_capped_at_20_gib():
    assert conftest._min_free_bytes(50 * GiB) == 10 * GiB
    assert conftest._min_free_bytes(1000 * GiB) == 20 * GiB
