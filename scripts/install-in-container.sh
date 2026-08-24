#!/usr/bin/env bash
set -euo pipefail

readonly STAGE=/opt/thinharness-terminal-bench
readonly SOURCE=/opt/thinharness-source
readonly VENV=/opt/thinharness-venv
readonly WHEELS=/opt/thinharness-wheels
readonly COMMIT=758fcf305e468138b03723760d477444592b1916
readonly REPOSITORY=https://github.com/ryanbbrown/thinharness.git

if ! command -v python3 >/dev/null || ! command -v git >/dev/null; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates git python3 python3-pip python3-venv
fi

rm -rf "$SOURCE" "$VENV" "$WHEELS"
python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --disable-pip-version-check --no-input \
  pip==25.2 setuptools==80.9.0 wheel==0.45.1

git clone --quiet --filter=blob:none --no-checkout "$REPOSITORY" "$SOURCE"
git -C "$SOURCE" fetch --quiet --depth=1 origin "$COMMIT"
git -C "$SOURCE" checkout --quiet --detach "$COMMIT"
actual_commit="$(git -C "$SOURCE" rev-parse HEAD)"
test "$actual_commit" = "$COMMIT"

mkdir -p "$WHEELS"
"$VENV/bin/python" -m pip wheel --disable-pip-version-check --no-input --no-deps --no-build-isolation --wheel-dir "$WHEELS" "$SOURCE"
wheel_path="$(find "$WHEELS" -maxdepth 1 -type f -name 'thinharness-*.whl' -print -quit)"
test -n "$wheel_path"
"$VENV/bin/python" -m pip install --disable-pip-version-check --no-input --no-deps \
  -r "$STAGE/container-runtime-requirements.txt"
"$VENV/bin/python" -m pip install --disable-pip-version-check --no-input --no-deps "$wheel_path"

"$VENV/bin/python" - "$wheel_path" "$actual_commit" "$REPOSITORY" "$STAGE/install-provenance.json" <<'PY'
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
from pathlib import Path

wheel = Path(sys.argv[1]).resolve()
value = {
    "schema_version": 1,
    "build_location": "harbor-task-container",
    "repository": sys.argv[3],
    "canonical_commit": sys.argv[2],
    "wheel_path": str(wheel),
    "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
    "installed_version": importlib.metadata.version("thinharness"),
    "python": sys.version,
    "platform": platform.platform(),
    "installed_distributions": sorted(
        f"{distribution.metadata['Name']}=={distribution.version}"
        for distribution in importlib.metadata.distributions()
        if distribution.metadata.get("Name")
    ),
}
path = Path(sys.argv[4])
temporary = path.with_suffix(".tmp")
with temporary.open("w", encoding="utf-8") as stream:
    json.dump(value, stream, indent=2, sort_keys=True)
    stream.write("\n")
    stream.flush()
    os.fsync(stream.fileno())
os.replace(temporary, path)
PY

"$VENV/bin/python" "$STAGE/container_runner.py" preflight \
  --prompt "$STAGE/system-prompt.md" \
  --install-provenance "$STAGE/install-provenance.json" \
  --receipt /logs/agent/container-preflight.json
