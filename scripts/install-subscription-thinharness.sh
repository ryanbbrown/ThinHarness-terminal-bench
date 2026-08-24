#!/usr/bin/env bash
set -euo pipefail
readonly STAGE=/opt/thinharness-terminal-bench-subscription
readonly SOURCE=/opt/thinharness-subscription-source
readonly VENV=/opt/thinharness-subscription-venv
readonly WHEELS=/opt/thinharness-subscription-wheels
readonly SOURCE_BUNDLE="$STAGE/thinharness-source.bundle"
readonly COMMIT=84105f07bb9c1ad366fc8fe4fef49e700f5e88ef

test -f "$SOURCE_BUNDLE"
if ! command -v python3 >/dev/null || ! command -v git >/dev/null; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates git python3 python3-pip python3-venv
fi
rm -rf "$SOURCE" "$VENV" "$WHEELS"
python3 -m venv "$VENV"
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
p=Path("/opt/thinharness-terminal-bench-subscription/install-provenance.json"); t=p.with_suffix('.tmp')
with t.open('w') as f: json.dump(value,f,indent=2,sort_keys=True); f.write('\n'); f.flush(); os.fsync(f.fileno())
os.replace(t,p)
PY
rm -rf "$SOURCE"
rm -f "$SOURCE_BUNDLE"
