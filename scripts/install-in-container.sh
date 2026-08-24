#!/usr/bin/env bash
set -euo pipefail

readonly STAGE=/opt/thinharness-terminal-bench
readonly SOURCE=/opt/thinharness-source
readonly VENV=/opt/thinharness-venv
readonly WHEELS=/opt/thinharness-wheels
readonly SOURCE_BUNDLE="$STAGE/thinharness-source.bundle"
readonly COMMIT=84105f07bb9c1ad366fc8fe4fef49e700f5e88ef
readonly REPOSITORY=https://github.com/ryanbbrown/thinharness.git

if ! command -v python3 >/dev/null || ! command -v git >/dev/null; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates git python3 python3-pip python3-venv
fi

rm -rf "$SOURCE" "$VENV" "$WHEELS"
python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --disable-pip-version-check --no-input \
  pip==25.2 setuptools==80.9.0 wheel==0.45.1

source_mode=canonical-github
source_bundle_sha256=
if [[ -f "$SOURCE_BUNDLE" ]]; then
  source_mode=local-git-bundle-override
  source_bundle_sha256="$(sha256sum "$SOURCE_BUNDLE" | cut -d ' ' -f 1)"
  git clone --quiet --no-checkout "$SOURCE_BUNDLE" "$SOURCE"
  git -C "$SOURCE" checkout --quiet --detach "$COMMIT"
else
  git clone --quiet --filter=blob:none --no-checkout "$REPOSITORY" "$SOURCE"
  git -C "$SOURCE" fetch --quiet --depth=1 origin "$COMMIT"
  git -C "$SOURCE" checkout --quiet --detach "$COMMIT"
fi
actual_commit="$(git -C "$SOURCE" rev-parse HEAD)"
test "$actual_commit" = "$COMMIT"

mkdir -p "$WHEELS"
"$VENV/bin/python" -m pip wheel --disable-pip-version-check --no-input --no-deps --no-build-isolation --wheel-dir "$WHEELS" "$SOURCE"
wheel_path="$(find "$WHEELS" -maxdepth 1 -type f -name 'thinharness-*.whl' -print -quit)"
test -n "$wheel_path"
"$VENV/bin/python" -m pip install --disable-pip-version-check --no-input --no-deps \
  -r "$STAGE/container-runtime-requirements.txt"
"$VENV/bin/python" -m pip install --disable-pip-version-check --no-input --no-deps "$wheel_path"

"$VENV/bin/python" - "$wheel_path" "$actual_commit" "$REPOSITORY" "$STAGE/install-provenance.json" "$source_mode" "$source_bundle_sha256" <<'PY'
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
from pathlib import Path

wheel = Path(sys.argv[1]).resolve()
value = {
    "schema_version": 2,
    "build_location": "harbor-task-container",
    "repository": sys.argv[3],
    "canonical_commit": sys.argv[2],
    "source_mode": sys.argv[5],
    "source_bundle_sha256": sys.argv[6] or None,
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

# The installed wheel and provenance are sufficient. Do not retain source or the override bundle.
rm -rf "$SOURCE"
rm -f "$SOURCE_BUNDLE"

readonly SENTINEL='controlled-preflight-sentinel-not-a-secret'
exec 8<<<"$SENTINEL"
exec env -u OPENAI_API_KEY -u TB_CREDENTIAL_SENTINEL \
  "$VENV/bin/python" "$STAGE/container_runner.py" preflight \
  --prompt "$STAGE/system-prompt.md" \
  --install-provenance "$STAGE/install-provenance.json" \
  --receipt /logs/agent/container-preflight.json \
  --sentinel-fd 8
