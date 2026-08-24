"""Create a transient bundle that exposes one exact commit ref."""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

EXACT_BUNDLE_REF = "refs/heads/thinharness-pin"


@dataclass(frozen=True)
class ExactCommitBundle:
    """Identity of one verified transient exact-commit bundle."""

    path: Path
    sha256: str
    source_head: str
    target_commit: str
    advertised_ref: str = EXACT_BUNDLE_REF
    source_head_excluded: bool = False


def _run(*command: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, capture_output=True, text=True)


def _bundle_heads(bundle: Path) -> list[tuple[str, str]]:
    lines = _run("git", "bundle", "list-heads", str(bundle)).stdout.splitlines()
    heads: list[tuple[str, str]] = []
    for line in lines:
        fields = line.split()
        if len(fields) != 2:
            raise RuntimeError("transient source bundle has a malformed advertised head")
        heads.append((fields[0], fields[1]))
    return heads


@contextmanager
def exact_commit_bundle(source: Path, target_commit: str, *, temporary_prefix: str) -> Iterator[ExactCommitBundle]:
    """Bundle only the target ref from a clean checkout whose HEAD may be later."""
    source = source.expanduser().resolve()
    if not source.is_dir():
        raise RuntimeError("local ThinHarness source is not a directory")
    if _run("git", "-C", str(source), "status", "--porcelain").stdout:
        raise RuntimeError("local ThinHarness source must be clean")
    if _run("git", "-C", str(source), "cat-file", "-e", f"{target_commit}^{{commit}}", check=False).returncode:
        raise RuntimeError("local ThinHarness source does not contain the exact pin")
    source_head = _run("git", "-C", str(source), "rev-parse", "HEAD^{commit}").stdout.strip()
    if _run(
        "git", "-C", str(source), "merge-base", "--is-ancestor", target_commit, source_head, check=False
    ).returncode:
        raise RuntimeError("exact pin is not an ancestor of canonical local HEAD")

    with tempfile.TemporaryDirectory(prefix=temporary_prefix) as directory:
        root = Path(directory)
        bare = root / "source.git"
        bundle = root / "thinharness-source.bundle"
        checkout = root / "bundle-check.git"
        _run("git", "clone", "--quiet", "--bare", "--no-local", str(source), str(bare))
        _run("git", "-C", str(bare), "update-ref", EXACT_BUNDLE_REF, target_commit)
        _run("git", "-C", str(bare), "bundle", "create", str(bundle), EXACT_BUNDLE_REF)
        _run("git", "bundle", "verify", str(bundle))
        expected_heads = [(target_commit, EXACT_BUNDLE_REF)]
        if _bundle_heads(bundle) != expected_heads:
            raise RuntimeError("transient source bundle must advertise only the exact pinned ref")

        _run("git", "init", "--quiet", "--bare", str(checkout))
        _run("git", "-C", str(checkout), "fetch", "--quiet", str(bundle), f"{EXACT_BUNDLE_REF}:{EXACT_BUNDLE_REF}")
        staged_commit = _run("git", "-C", str(checkout), "rev-parse", f"{EXACT_BUNDLE_REF}^{{commit}}").stdout.strip()
        if staged_commit != target_commit:
            raise RuntimeError("transient source bundle resolves to a different commit")
        source_head_excluded = source_head == target_commit or _run(
            "git", "-C", str(checkout), "cat-file", "-e", f"{source_head}^{{commit}}", check=False
        ).returncode != 0
        if not source_head_excluded:
            raise RuntimeError("transient source bundle contains later source HEAD commit")

        yield ExactCommitBundle(
            path=bundle,
            sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(),
            source_head=source_head,
            target_commit=target_commit,
            source_head_excluded=source_head_excluded,
        )
