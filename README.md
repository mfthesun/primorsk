# Приморск — сценарий комплексного развития и цифровая модель городской среды

Командный проект ИДУ ИТМО (программа «Цифровая урбанистика») по **Приморскому городскому поселению**
Выборгского района Ленинградской области.

Команда: Яковлев Денис, Ренгач Владислав, Комарова Арина, Непомнящая Мария, Яцуба Александра,
Саркисова Наталия, Цыганов Виктор.

**Презентация «Цифровой мастер-план» (контроль 03.11.2026), Figma Slides:**
https://www.figma.com/slides/KSYAlweFOrSx2AfOUjUJlO — структура и подписи к слайдам — `docs/slides-0311.md`.

## Этапы

| Этап | Что | Статус | Документы |
|---|---|---|---|
| 1. Концепция (1-й семестр) | Комплексные исследования, SWOT, 3 сценария: реновация пешеходно-транспортной сети, кампус ИНТЦ «Приморская долина», марина и парусная школа | защищено | `docs/concept.md`, `presentations/2025_concept_primorsk.pdf` |
| 2. Цифровая модель (2-й семестр) | Слои территории, сервисы, кварталы, сценарий | защищено 14.05.2026 (85 баллов), замечания исправлены | `docs/digital-model.md`, `docs/review_comments.md`, `presentations/2026-05-14_digital_model_primorsk.pdf` |
| 3. Цифровой мастер-план (осень 2026, дисциплина «Анализ данных и моделирование в урбанистике») | BlocksNet / ObjectNat / Urbanomy: анализ, сценарии, ТЭП и обеспеченность «до / после», очерёдность, риски | в работе: контроль 03.11, защита 24.12 | `docs/course-adim.md`, `docs/roadmap.md`, `docs/scenario.md`, [презентация в Figma](https://www.figma.com/slides/KSYAlweFOrSx2AfOUjUJlO) |

## Структура

```
presentations/        защищённые презентации (PDF)
docs/
  concept.md          выжимка концепции с цифрами
  digital-model.md    что было на защите 14.05, карты → слои
  scenario.md         слои сценария ↔ проекты концепции, расхождения
  course-adim.md      требования, KPI и график дисциплины АДиМ, инструменты курса
  roadmap.md          план цифрового мастер-плана
  requirements.md     требования курса к слоям
  review_comments.md  замечания преподавателя и статус
  data-sources.md     источники слоёв
data/
  raw/                слои в сданном виде (не редактировать)
  processed/          итоговые GeoJSON, EPSG:4326: территория, services/, scenario/
scripts/
  setup.sh            окружения: .venv и .venv-blocksnet (Python 3.12, uv)
  process.py          raw → processed (все исправления)
  validate.py         проверка на соответствие требованиям
  roadgraph.py        дорожный граф по roads.geojson (+ разрывы из OSM), формат BlocksNet/IduEdu
  scenario_design.py  трассировка транспортных слоёв сценария и причалов → data/raw/scenario_design
  scenarios.py        состав сценариев (today / s1 / s2) и очереди объектов
  analysis.py         BlocksNet: кварталы, доступность, обеспеченность, показатели территории по сценариям
  objectnat_analysis.py  ObjectNat: изохроны, обеспеченность по зданиям, шум, видимость
  urbanomy_analysis.py   Urbanomy: инвестиции и социально-экономический эффект
  climate.py          климатические метрики (ERA5): парусный сезон, лёд, ветер
  metrics.py          сводная таблица «сегодня / сценарий 1 / сценарий 2» → reports/metrics_scenarios.md
  maps.py             карты для презентации → reports/maps/
  webmap.py           интерактивный «Цифровой мастер-план» → reports/master_plan.html
reports/              отчёт валидации и журналы изменений
CLAUDE.md             инструкции для Claude Code
```

## Быстрый старт

```bash
bash scripts/setup.sh                              # окружения .venv и .venv-blocksnet
.venv/bin/python scripts/process.py                # пересобрать data/processed из data/raw
.venv/bin/python scripts/validate.py               # проверить; код выхода 1 при ошибках
.venv-blocksnet/bin/python scripts/analysis.py     # BlocksNet по сценариям
.venv-objectnat/bin/python scripts/objectnat_analysis.py
.venv/bin/python scripts/climate.py && .venv/bin/python scripts/metrics.py
.venv/bin/python scripts/maps.py && .venv/bin/python scripts/webmap.py
```

## Ключевые цифры

| Показатель | Значение |
|---|---|
| Население города / поселения | 6 271 / 13 593 (Росстат на 01.01.2025, презентации); в слое `boundary` — 13 659 (на 01.01.2024) |
| Здания | 9 156: жилых 2 832, сезонный фонд (дачи) 2 314 ≈ 5 800 чел. летом |
| Кварталы | 526 |
| Сервисы | 45 слоёв |
| Сценарий | 3 проектные территории, 24 здания (59 тыс. м²), общежитие 75 чел., сервисы + транспортные слои и причалы |
| Обеспеченность «было» | школы 97 % с подвозом (57 % пешком); детсады — дефицит 363 места |
| Сценарии | `reports/metrics_scenarios.md` — показатели «сегодня / сценарий 1 / сценарий 2» |

## Данные

Слои основаны на OpenStreetMap (© участники OpenStreetMap, ODbL), материалах генерального плана и СТП
Ленинградской области, Реестре домов и Росстате — см. `docs/data-sources.md`.
