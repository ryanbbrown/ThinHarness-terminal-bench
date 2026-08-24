from __future__ import annotations

import os

import pytest

from tbench.container_security import harden_linux_model_loop_parent, read_handoff_fd


def test_anonymous_descriptor_handoff_reads_then_closes() -> None:
    read_fd, write_fd = os.pipe()
    os.write(write_fd, b"sentinel-value\n")
    os.close(write_fd)

    assert read_handoff_fd(read_fd, label="test") == "sentinel-value"
    with pytest.raises(OSError):
        os.read(read_fd, 1)


def test_credential_isolation_fails_closed_off_linux(monkeypatch) -> None:
    monkeypatch.setattr("sys.platform", "darwin")

    with pytest.raises(RuntimeError, match="requires Linux procfs"):
        harden_linux_model_loop_parent()
