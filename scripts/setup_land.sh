#!/usr/bin/env bash
# Изолированная учебная модель земли: старые .venv* и Projects/Urbanomy не меняются.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
V="$ROOT/.venv-land"
COMMIT=1f3ec003890524e557f56d7778d2393410dadd2e
export NUMBA_CACHE_DIR="${NUMBA_CACHE_DIR:-/tmp/primorsk-numba}"
export MPLCONFIGDIR="${MPLCONFIGDIR:-/tmp/primorsk-mpl}"
command -v uv >/dev/null
[ -x "$V/bin/python" ] || uv venv -p 3.12 "$V"
uv pip install --python "$V/bin/python" -r scripts/requirements-land.lock.txt
mkdir -p "$V/src"
[ -d "$V/src/urbanomy/.git" ] || git clone https://github.com/IDUclub/Urbanomy.git "$V/src/urbanomy"
git -C "$V/src/urbanomy" fetch --depth 1 origin "$COMMIT"
git -C "$V/src/urbanomy" checkout --detach "$COMMIT"
"$V/bin/python" - <<'PY'
import sysconfig
from pathlib import Path
Path(sysconfig.get_paths()['purelib'],'urbanomy_src.pth').write_text(str(Path('.venv-land/src/urbanomy/src').resolve())+'\n')
PY
"$V/bin/python" -c "from urbanomy.methods.land_value_modeling.ga_mc_optimizer import DistrictProblem; print('DistrictProblem / pinned Urbanomy OK')"
