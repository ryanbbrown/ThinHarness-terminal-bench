#!/usr/bin/env bash
set -euo pipefail
readonly STAGE=/opt/thinharness-terminal-bench-subscription
readonly PI_PREFIX=/opt/pi-subscription
readonly NVM_DIR=/root/.nvm
readonly NODE_VERSION=22.23.1

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends ca-certificates curl python3
if [[ ! -s "$NVM_DIR/nvm.sh" ]]; then
  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.2/install.sh | env -u NODE_VERSION bash
fi
. "$NVM_DIR/nvm.sh"
nvm install "$NODE_VERSION" >/dev/null
nvm use "$NODE_VERSION" >/dev/null
rm -rf "$PI_PREFIX"
mkdir -p "$PI_PREFIX"
cp "$STAGE/pi-subscription-package.json" "$PI_PREFIX/package.json"
cp "$STAGE/pi-subscription-package-lock.json" "$PI_PREFIX/package-lock.json"
npm ci --prefix "$PI_PREFIX" --ignore-scripts --no-audit --no-fund >/dev/null
pi_bin="$PI_PREFIX/node_modules/.bin/pi"
node_path="$(command -v node)"
ln -sf "$node_path" /usr/local/bin/node
ln -sf "$(command -v npm)" /usr/local/bin/npm
ln -sf "$pi_bin" /usr/local/bin/pi
test "$($pi_bin --version)" = "0.84.2"
python3 - "$pi_bin" "$node_path" <<'PY'
import hashlib,json,os,platform,subprocess,sys
from pathlib import Path
pi=Path(sys.argv[1]).resolve(); node=Path(sys.argv[2]).resolve()
lock=Path('/opt/pi-subscription/package-lock.json')
value={
 'schema_version':1,'harness':'pi','build_location':'harbor-task-container','pi_version':subprocess.check_output([pi,'--version'],text=True).strip(),
 'package':'@earendil-works/pi-coding-agent','package_version':'0.84.2',
 'package_lock_sha256':hashlib.sha256(lock.read_bytes()).hexdigest(),'node_version':subprocess.check_output([node,'--version'],text=True).strip(),
 'node_executable':str(node),'pi_executable':str(pi),'platform':platform.platform()
}
p=Path('/opt/thinharness-terminal-bench-subscription/install-provenance.json'); t=p.with_suffix('.tmp')
with t.open('w') as f: json.dump(value,f,indent=2,sort_keys=True); f.write('\n'); f.flush(); os.fsync(f.fileno())
os.replace(t,p)
PY
