#!/usr/bin/env bash
# Установка окружений проекта.
#
#   bash scripts/setup.sh            # базовое окружение + BlocksNet
#   bash scripts/setup.sh base       # только пайплайн данных и карты (requirements.txt)
#   bash scripts/setup.sh blocksnet  # только окружение моделирования
#
# Окружения:
#   .venv            — пайплайн данных (process.py, validate.py, maps.py): requirements.txt, любой Python ≥ 3.10;
#   .venv-blocksnet  — моделирование (analysis.py): Python 3.12, BlocksNet 1.0.0a9 [torch] + iduedu 0.4.1.
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

BLOCKSNET_VERSION="1.0.0a9"
IDUEDU_VERSION="0.4.1"        # BlocksNet 1.0.0a9 несовместим с iduedu ≥ 1.0
TORCH_INDEX="https://download.pytorch.org/whl/cpu"

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
    [ -d .venv ] || uv venv -q .venv
    VIRTUAL_ENV="$ROOT/.venv" uv pip install -q -r requirements.txt
    .venv/bin/python -c "import geopandas, pyogrio, shapely, matplotlib; print('geopandas', geopandas.__version__)"
}

setup_blocksnet() {
    log "Окружение моделирования .venv-blocksnet (Python 3.12, BlocksNet $BLOCKSNET_VERSION)"
    # uv сам скачает Python 3.12, если его нет в системе (нужен доступ к github.com);
    # при ограниченном интернете поставьте python3.12 из пакетов ОС заранее.
    [ -d .venv-blocksnet ] || uv venv -q -p 3.12 .venv-blocksnet
    local extra=()
    if reachable "$TORCH_INDEX/torch/"; then
        # CPU-сборка torch: ~200 МБ вместо ~2 ГБ с CUDA
        extra=(--extra-index-url "$TORCH_INDEX" --index-strategy unsafe-best-match)
    else
        echo "download.pytorch.org недоступен — torch будет взят с PyPI (сборка с CUDA, тяжелее)"
    fi
    VIRTUAL_ENV="$ROOT/.venv-blocksnet" uv pip install -q "${extra[@]}" \
        "blocksnet[torch]==$BLOCKSNET_VERSION" "iduedu==$IDUEDU_VERSION" \
        -r requirements.txt
    .venv-blocksnet/bin/python - <<'PY'
import blocksnet, iduedu, torch, pulp
print("blocksnet", blocksnet.__version__, "| iduedu", iduedu.__version__, "| torch", torch.__version__)
from blocksnet.analysis.provision import competitive_provision  # noqa: F401
print("CBC:", pulp.PULP_CBC_CMD().available())
PY
}

ensure_uv
case "$WHAT" in
    base) setup_base ;;
    blocksnet) setup_blocksnet ;;
    all) setup_base; setup_blocksnet ;;
    *) echo "использование: bash scripts/setup.sh [all|base|blocksnet]"; exit 2 ;;
esac

log "Готово"
cat <<'TXT'
  .venv/bin/python scripts/process.py && .venv/bin/python scripts/validate.py
  .venv-blocksnet/bin/python scripts/analysis.py
  .venv/bin/python scripts/maps.py
TXT
