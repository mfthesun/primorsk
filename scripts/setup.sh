#!/usr/bin/env bash
# Установка окружений проекта.
#
#   bash scripts/setup.sh            # базовое окружение + BlocksNet
#   bash scripts/setup.sh base       # только пайплайн данных и карты (requirements.txt)
#   bash scripts/setup.sh blocksnet  # только окружение моделирования (BlocksNet + Urbanomy)
#   bash scripts/setup.sh objectnat  # только окружение ObjectNat
#   bash scripts/setup.sh link       # только ссылки .venv* в репозитории на окружения из PRIMORSK_VENVS
#
# PRIMORSK_VENVS — где лежат окружения (по умолчанию — корень репозитория). В облачной среде Claude Code
# окружения ставятся в /opt/primorsk (переживает свежий клон репозитория), а в репозитории создаются ссылки
# .venv → /opt/primorsk/.venv и т. д. (docs/cloud-environment.md).
#
# Окружения:
#   .venv            — пайплайн данных (process.py, validate.py, maps.py): requirements.txt, любой Python ≥ 3.10;
#   .venv-blocksnet  — моделирование (analysis.py, urbanomy_analysis.py): Python 3.12, BlocksNet 1.0.0a9 [torch]
#                      + iduedu 0.4.1; Urbanomy — из GitHub (IDUclub/urbanomy, на PyPI нет) на закреплённом коммите;
#   .venv-objectnat  — objectnat_analysis.py: Python 3.12, ObjectNat 2.1 + iduedu 2.3 (несовместим с BlocksNet).
#
# Интернет может быть ограничен: скрипт ставит пакеты только из PyPI (и CPU-сборку torch с download.pytorch.org,
# если она доступна — иначе torch берётся с PyPI). Данные OSM/Overpass не нужны: граф строится в analysis.py
# по data/processed/roads.geojson. Если PyPI недоступен совсем, задайте зеркало: UV_INDEX_URL=... bash scripts/setup.sh
#
# Если uv не найден, он ставится через pip (pip install --user uv).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
WHAT="${1:-all}"
# окружения: PRIMORSK_VENVS, иначе /opt/primorsk (облачная среда), если там уже установлено, иначе — репозиторий
if [ -n "${PRIMORSK_VENVS:-}" ]; then VENVS="$PRIMORSK_VENVS"
elif [ -d /opt/primorsk/.venv ]; then VENVS=/opt/primorsk
else VENVS="$ROOT"; fi
mkdir -p "$VENVS"
V="$VENVS/.venv"; VB="$VENVS/.venv-blocksnet"; VO="$VENVS/.venv-objectnat"

BLOCKSNET_VERSION="1.0.0a9"
IDUEDU_VERSION="0.4.1"        # BlocksNet 1.0.0a9 несовместим с iduedu ≥ 1.0
TORCH_INDEX="https://download.pytorch.org/whl/cpu"
OBJECTNAT_VERSION="2.1.0"
URBANOMY_REPO="https://github.com/IDUclub/urbanomy.git"
URBANOMY_COMMIT="0666d6b7e128fd9a081b56f30be8893690a6fd40"   # 2025-10-09

log() { printf '\n== %s\n' "$*"; }

ensure_uv() {
    if command -v uv >/dev/null 2>&1; then return; fi
    log "uv не найден — ставлю через pip"
    python3 -m pip install --user -q uv
    export PATH="$HOME/.local/bin:$PATH"
    command -v uv >/dev/null 2>&1 || { echo "не удалось установить uv"; exit 1; }
}

reachable() {  # reachable URL — доступен ли хост (код ответа < 500)
    local code
    code=$(curl -sS -m 15 -o /dev/null -w '%{http_code}' "$1" 2>/dev/null || true)
    [[ "$code" =~ ^[1-4][0-9][0-9]$ ]]
}

setup_base() {
    log "Базовое окружение .venv (requirements.txt)"
    [ -d "$V" ] || uv venv -q "$V"
    VIRTUAL_ENV="$V" uv pip install -q -r requirements.txt
    "$V/bin/python" -c "import geopandas, pyogrio, shapely, matplotlib; print('geopandas', geopandas.__version__)"
}

setup_blocksnet() {
    log "Окружение моделирования .venv-blocksnet (Python 3.12, BlocksNet $BLOCKSNET_VERSION)"
    # uv сам скачает Python 3.12, если его нет в системе (нужен доступ к github.com);
    # при ограниченном интернете поставьте python3.12 из пакетов ОС заранее.
    [ -d "$VB" ] || uv venv -q -p 3.12 "$VB"
    local extra=()
    if reachable "$TORCH_INDEX/torch/"; then
        # CPU-сборка torch: ~200 МБ вместо ~2 ГБ с CUDA
        extra=(--extra-index-url "$TORCH_INDEX" --index-strategy unsafe-best-match)
    else
        echo "download.pytorch.org недоступен — torch будет взят с PyPI (сборка с CUDA, тяжелее)"
    fi
    VIRTUAL_ENV="$VB" uv pip install -q "${extra[@]}" \
        "blocksnet[torch]==$BLOCKSNET_VERSION" "iduedu==$IDUEDU_VERSION" \
        -r requirements.txt
    "$VB/bin/python" - <<'PY'
import blocksnet, iduedu, torch, pulp
print("blocksnet", blocksnet.__version__, "| iduedu", iduedu.__version__, "| torch", torch.__version__)
from blocksnet.analysis.provision import competitive_provision  # noqa: F401
print("CBC:", pulp.PULP_CBC_CMD().available())
PY
}

setup_urbanomy() {
    # Urbanomy: pyproject требует Python 3.10 и BlocksNet 1.0.0a1 (ради land_value_modeling); используемые
    # модули (investment_potential, socio_economic_indicators) от BlocksNet не зависят — подключаем src в .venv-blocksnet
    log "Urbanomy ($URBANOMY_COMMIT) → .venv-blocksnet"
    local dst="$VB/src/urbanomy"
    if [ ! -d "$dst/.git" ]; then
        git clone -q "$URBANOMY_REPO" "$dst"
    fi
    git -C "$dst" fetch -q --depth 1 origin "$URBANOMY_COMMIT" 2>/dev/null || true
    git -C "$dst" checkout -q "$URBANOMY_COMMIT"
    local site
    site=$("$VB/bin/python" -c "import sysconfig; print(sysconfig.get_paths()['purelib'])")
    echo "$dst/src" > "$site/urbanomy_src.pth"
    VIRTUAL_ENV="$VB" uv pip install -q catboost libpysal
    "$VB/bin/python" -c "from urbanomy.methods.socio_economic_indicators.sei_calculate import SEREstimator; print('urbanomy OK')"
}

setup_objectnat() {
    log "Окружение ObjectNat .venv-objectnat (Python 3.12, ObjectNat $OBJECTNAT_VERSION)"
    [ -d "$VO" ] || uv venv -q -p 3.12 "$VO"
    VIRTUAL_ENV="$VO" uv pip install -q "objectnat==$OBJECTNAT_VERSION" -r requirements.txt
    "$VO/bin/python" -c "import objectnat, iduedu; print('objectnat', '$OBJECTNAT_VERSION', '| iduedu', iduedu.__version__)"
}

link_venvs() {
    # окружения вне репозитория → ссылки .venv* в корне репозитория (команды в документации не меняются)
    [ "$VENVS" = "$ROOT" ] && return
    for n in .venv .venv-blocksnet .venv-objectnat; do
        if [ -d "$VENVS/$n" ] && [ ! -e "$ROOT/$n" -o -L "$ROOT/$n" ]; then
            ln -sfn "$VENVS/$n" "$ROOT/$n"
        fi
    done
}

if [ "$WHAT" = "link" ]; then link_venvs; exit 0; fi
ensure_uv
case "$WHAT" in
    base) setup_base ;;
    blocksnet) setup_blocksnet; setup_urbanomy ;;
    objectnat) setup_objectnat ;;
    all) setup_base; setup_blocksnet; setup_urbanomy; setup_objectnat ;;
    *) echo "использование: bash scripts/setup.sh [all|base|blocksnet|objectnat|link]"; exit 2 ;;
esac
link_venvs

log "Готово"
cat <<'TXT'
  .venv/bin/python scripts/process.py && .venv/bin/python scripts/validate.py
  .venv-blocksnet/bin/python scripts/analysis.py            # BlocksNet: today, s1, s2
  .venv-objectnat/bin/python scripts/objectnat_analysis.py  # ObjectNat
  .venv-blocksnet/bin/python scripts/urbanomy_analysis.py   # Urbanomy
  .venv/bin/python scripts/climate.py && .venv/bin/python scripts/metrics.py
  .venv/bin/python scripts/maps.py
TXT
