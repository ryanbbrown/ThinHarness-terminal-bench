#!/usr/bin/env bash
set -euo pipefail
readonly STAGE=/opt/thinharness-terminal-bench-direct
readonly SOURCE=/opt/thinharness-direct-source
readonly VENV=/opt/thinharness-direct-venv
readonly WHEELS=/opt/thinharness-direct-wheels
readonly SOURCE_BUNDLE="$STAGE/thinharness-source.bundle"
readonly UV_BOOTSTRAP=/opt/thinharness-direct-uv-bootstrap
readonly PYTHON_VERSION=3.12.11
readonly UV_VERSION=0.8.13
readonly COMMIT=84105f07bb9c1ad366fc8fe4fef49e700f5e88ef

test -f "$SOURCE_BUNDLE"
probe="$(mktemp -d)"
if ! command -v python3 >/dev/null || ! command -v git >/dev/null || ! python3 -m venv "$probe/venv" >/dev/null 2>&1; then
  rm -rf "$probe"
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates git python3 python3-pip python3-venv
else
  rm -rf "$probe"
fi
rm -rf "$SOURCE" "$VENV" "$WHEELS" "$UV_BOOTSTRAP"
python3 -m venv "$UV_BOOTSTRAP"
"$UV_BOOTSTRAP/bin/python" -m pip install --disable-pip-version-check --no-input "uv==$UV_VERSION"
"$UV_BOOTSTRAP/bin/uv" python install "$PYTHON_VERSION"
"$UV_BOOTSTRAP/bin/uv" venv --seed --python "$PYTHON_VERSION" "$VENV"
"$VENV/bin/python" -m pip install --disable-pip-version-check --no-input pip==25.2 setuptools==80.9.0 wheel==0.45.1
bundle_sha256="$(sha256sum "$SOURCE_BUNDLE" | cut -d ' ' -f 1)"
git clone --quiet --no-checkout "$SOURCE_BUNDLE" "$SOURCE"
git -C "$SOURCE" checkout --quiet --detach "$COMMIT"
test "$(git -C "$SOURCE" rev-parse HEAD)" = "$COMMIT"
mkdir -p "$WHEELS"
"$VENV/bin/python" -m pip wheel --disable-pip-version-check --no-input --no-deps --no-build-isolation --wheel-dir "$WHEELS" "$SOURCE"
wheel_path="$(find "$WHEELS" -maxdepth 1 -type f -name 'thinharness-*.whl' -print -quit)"
test -n "$wheel_path"
"$VENV/bin/python" -m pip install --disable-pip-version-check --no-input --no-deps -r "$STAGE/container-runtime-requirements.txt"
"$VENV/bin/python" -m pip install --disable-pip-version-check --no-input --no-deps "$wheel_path"
"$VENV/bin/python" - "$wheel_path" "$bundle_sha256" <<'PY'
import hashlib, importlib.metadata, json, os, platform, sys
from pathlib import Path
wheel=Path(sys.argv[1]).resolve()
value={
 "schema_version":1,"harness":"thinharness","build_location":"harbor-task-container",
 "canonical_commit":"84105f07bb9c1ad366fc8fe4fef49e700f5e88ef","source_mode":"transient-local-git-bundle",
 "source_bundle_sha256":sys.argv[2],"wheel_path":str(wheel),"wheel_sha256":hashlib.sha256(wheel.read_bytes()).hexdigest(),
 "installed_version":importlib.metadata.version("thinharness"),"python":sys.version,"platform":platform.platform()
}
p=Path("/opt/thinharness-terminal-bench-direct/install-provenance.json"); t=p.with_suffix('.tmp')
with t.open('w') as f: json.dump(value,f,indent=2,sort_keys=True); f.write('\n'); f.flush(); os.fsync(f.fileno())
os.replace(t,p)
PY
rm -rf "$SOURCE" "$UV_BOOTSTRAP"
rm -f "$SOURCE_BUNDLE"
