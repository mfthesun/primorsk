# CLAUDE.md

Командный проект ИДУ ИТМО: **Приморское городское поселение** (Выборгский р-н, Ленобласть).
Язык общения, документации и коммитов — русский.

Сейчас проект продолжается в дисциплине «Анализ данных и моделирование в урбанистике»: итоговый продукт —
«Цифровой мастер-план» (`docs/course-adim.md`). Контроль презентаций 03.11.2026, защита 24.12.2026.

## Контекст проекта (читать перед работой)

1. `docs/concept.md` — концепция 1-го семестра: 3 проекта (транспорт, кампус ИНТЦ, марина) с цифрами и гипотезами.
2. `docs/digital-model.md` — цифровая модель 2-го семестра (защита 14.05.2026, 85 баллов).
3. `docs/scenario.md` — как слои сценария соответствуют проектам концепции и чего не хватает.
4. `docs/course-adim.md` — требования дисциплины, KPI, график, инструменты; `docs/roadmap.md` — план работ по разделам мастер-плана.
5. `docs/requirements.md` — требования курса к слоям (критерии оценки); `docs/review_comments.md` — замечания и TODO.

Исходные презентации — `presentations/*.pdf` (тяжёлые, читать постранично).

## Правила работы с данными

- `data/raw/` — исходники, **не редактировать**. Все правки — в `scripts/process.py`, результат — `data/processed/`.
- После любых изменений: `python scripts/process.py && python scripts/validate.py` → 0 ошибок;
  `reports/` коммитить вместе с данными.
- Ручные правки по 2ГИС для зданий — `data/raw/is_living_overrides.csv` (`id,is_living[,comment]`), применяются
  поверх правил в `building()`.
- Новые исходные слои — в `data/raw/` + запись об источнике и дате в `docs/data-sources.md`.

## Соглашения

- Хранение — EPSG:4326, GeoJSON; метрические расчёты — EPSG:32635 (UTM 35N).
- Имена файлов и атрибутов — латиница, нижний регистр, snake_case; сервисы — по таблице сервисов курса.
- `building`: `build_floor_area, living_area, non_living_area, footprint_area` (real), `number_of_floors, population`
  (int), `is_living` (bool). Нет `None` в площадях; у нежилых `population = 0`; сумма = `boundary.population`.
- Сервисы: `service_id` (int, пусто если сервиса нет в таблице), `service_name` (str), `capacity` (int; реальная — у
  школ, детсадов, колледжей, допобразования; у прочих 0). Точки — на полигонах `building`
  (кроме `bus_stop, playground, pitch, cell_tower`); в сценарии — на зданиях сценария.
- GeoJSON не хранит типы: столбец целиком из null читается как String.
- Карты: подложки Esri/OSM, **не CARTO** (нужен API-ключ).

## Окружение

```bash
bash scripts/setup.sh                      # .venv, .venv-blocksnet (+ Urbanomy), .venv-objectnat — Python 3.12, uv
                                           # (в облачной среде — автоматически, см. docs/cloud-environment.md)
.venv/bin/python scripts/process.py && .venv/bin/python scripts/validate.py
.venv-blocksnet/bin/python scripts/analysis.py            # BlocksNet: today / s1 / s2
.venv-objectnat/bin/python scripts/objectnat_analysis.py  # ObjectNat: изохроны, обеспеченность по зданиям, шум, видимость
.venv-blocksnet/bin/python scripts/urbanomy_analysis.py   # Urbanomy: инвестиции, SER
.venv/bin/python scripts/climate.py && .venv/bin/python scripts/metrics.py   # климат; сводная таблица
.venv/bin/python scripts/maps.py && .venv/bin/python scripts/webmap.py       # карты PNG; HTML «Цифровой мастер-план»
```

Сценарии — `scripts/scenarios.py` (today / s1 — первая очередь до 2029 / s2 — полная реализация до 2031), у объектов
сценария атрибут `phase`. Дачи — сезонный фонд (`is_seasonal`), в постоянное население не входят.

BlocksNet 1.0.0a9 требует iduedu 0.4.1 и extra `[torch]` (Python 3.10–3.12; setup.sh ставит CPU-сборку torch);
ObjectNat 2.1 требует iduedu ≥ 2.2 — `.venv-objectnat`; `UrbanGraph.from_nx_graph` в iduedu 2.3 падает — собирать
`UrbanGraph(nodes, edges, ...)` из таблиц. Urbanomy — только из GitHub (IDUclub/urbanomy, коммит в setup.sh), без
модели CatBoost стоимость земли не считается. Опыт — github.com/mfthesun/pskov-blocksnet.

Граф — `scripts/roadgraph.py` по `roads.geojson` + достройка разрывов `data/raw/osm_roads.geojson` (без интернета).
Подводные камни IduEdu 0.4.1: граф должен быть ориентированным, узлы — подряд 0..n-1 (метка = номер строки
матрицы), вес ребра ≥ 0,01 мин (хранится как целое ×100). Точка квартала — центр его застройки, не
`representative_point()` (кварталы до сотен га).

Карты: без заголовков (они в презентации; подписи — `reports/maps/README.md`), кадр 4:3, север — вверху справа,
масштабная линейка — внизу слева, легенда — внизу справа, подложка Esri без надписей, все подписи по-русски.

Внешние данные (OSM/Overpass, 2ГИС, Росстат) скрипты не скачивают.

## Ближайшие задачи

1. Запустить `urbanomy_analysis.py` (нужно разрешение на код из GitHub) и вписать кадастровую стоимость земли
   в `data/raw/urbanomy_inputs.json`; получить модель CatBoost курса для стоимости земли до / после.
2. Демография из БД ПМО Росстата; программа / стратегия развития поселения → целевые показатели в `metrics.py`.
3. Дефицит детских садов (363 места) сценарии не закрывают — кандидат в мероприятия МП.
4. Таблица ТЭП по форме кураторов; таблицы мероприятий (очерёдность) и рисков.
