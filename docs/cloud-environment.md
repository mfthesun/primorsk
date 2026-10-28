# Облачная среда Claude Code для проекта

Среда, в которой новые сеансы стартуют с готовыми окружениями (`.venv`, `.venv-blocksnet` с Urbanomy,
`.venv-objectnat`). Создаётся в claude.ai/code: меню облачной среды в заголовке сеанса → **Add environment**
(или **Edit** у существующей) → **Add environment** / **Save changes**.

## Параметры

| Поле | Значение |
|---|---|
| **Name** | `primorsk-adim` |
| **Network access** | **Full** (или **Custom** со списком ниже и галочкой **Also include default list of common package managers**) |
| **Environment variables** | см. ниже |
| **Setup script** | см. ниже |

### Allowed domains (только для уровня Custom)

```
download.pytorch.org
server.arcgisonline.com
*.arcgisonline.com
archive-api.open-meteo.com
maps.mail.ru
```

PyPI и github.com входят в список по умолчанию. download.pytorch.org — CPU-сборка torch (без него torch с CUDA
≈ 2 ГБ, установка может не уложиться в 5 минут); arcgisonline — подложки Esri для `maps.py` и `webmap.py`;
open-meteo и maps.mail.ru (Overpass) — только для повторной выгрузки исходных данных.

### Environment variables

```
PRIMORSK_VENVS=/opt/primorsk
MPLBACKEND=Agg
BASH_DEFAULT_TIMEOUT_MS=600000
BASH_MAX_TIMEOUT_MS=1800000
```

Таймауты — для долгих расчётов (ObjectNat по трём сценариям идёт ~10 мин).

### Setup script

```bash
#!/bin/bash
# Приморск: окружения в /opt/primorsk (попадают в кэш среды), ссылки .venv* в репозитории
export PRIMORSK_VENVS=/opt/primorsk
cd primorsk || exit 0
if [ -f scripts/setup.sh ]; then
    bash scripts/setup.sh all || echo "scripts/setup.sh завершился с ошибкой — см. лог выше" >&2
else
    echo "scripts/setup.sh нет в ветке по умолчанию — слейте PR mfthesun/primorsk#1 в main" >&2
fi
exit 0
```

## Как это работает

- Скрипт выполняется при первом сеансе (≈ 1–2 мин), затем среда кэшируется снимком файловой системы на ~7 дней:
  следующие сеансы стартуют с установленными окружениями в `/opt/primorsk`. Кэш пересобирается при изменении
  скрипта или списка доменов.
- Репозиторий в сеансе клонируется заново, поэтому окружения лежат вне него, а в репозитории — ссылки
  `.venv → /opt/primorsk/.venv` и т. д. Если ссылок нет, Claude выполняет `bash scripts/setup.sh link`
  (`CLAUDE.md`); `setup.sh` сам находит `/opt/primorsk`.
- Скрипт всегда завершается с кодом 0, чтобы сбой установки не мешал запуску сеанса.
