# Облачная среда Claude Code для проекта

Чтобы в новых сеансах окружения были готовы сразу, в настройках облачной среды (меню среды в заголовке сеанса →
**Edit**, или новая среда, например «primorsk-adim») в поле **Setup script** вставьте скрипт ниже. Он выполняется при
старте каждого сеанса из папки на уровень выше репозитория.

```bash
#!/bin/bash
# Приморск: окружения .venv, .venv-blocksnet (+ Urbanomy), .venv-objectnat — scripts/setup.sh
set -euo pipefail
cd primorsk
if [ -f scripts/setup.sh ]; then
    bash scripts/setup.sh all
else
    echo "scripts/setup.sh нет в этой ветке — слейте PR mfthesun/primorsk#1 в main" >&2
fi
```

Что ставится (≈ 1–2 мин): `.venv` — `requirements.txt` (geopandas, contextily, folium…); `.venv-blocksnet` — Python
3.12, BlocksNet 1.0.0a9 + iduedu 0.4.1 + CPU-сборка torch, Urbanomy из GitHub на закреплённом коммите;
`.venv-objectnat` — ObjectNat 2.1 + iduedu 2.3.

Сетевой доступ среды должен разрешать: pypi.org / files.pythonhosted.org, download.pytorch.org (CPU torch; без него
torch берётся с PyPI), github.com (Urbanomy, загрузка Python 3.12 через uv, если его нет в образе),
server.arcgisonline.com (подложки Esri для `maps.py` и `webmap.py`). Для повторной выгрузки исходных данных —
maps.mail.ru (Overpass) и archive-api.open-meteo.com; при обычной работе скрипты в интернет не ходят.
