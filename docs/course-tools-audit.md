# Реестр инструментов курса

Источник требований: [КИГС, 2 курс — инструменты](https://docs.google.com/spreadsheets/d/1SXycGTBji0WK7LlAw7kvEcWchXZUa5Ywq8DXBkvZbFI/edit), прочитано04.11.2026. Всего17 методов (пустые строки исходной таблицы не считаются).

Статус «артефакты есть» подтверждает наличие перечисленных результатов; выполнение и ограничения проверяются по отчётам и журналу верификации. Установка библиотеки результатом не считается.

| № | Метод | Реализация | Результаты | Проверка наличия | Ограничение / способ проверки |
|---|---|---|---|---|---|
| 1 | Визуализация 2D/3D | scripts/webmap.py; scripts/visualization_data.py | `reports/master_plan.html` | артефакты есть | Сценарии, extrusion, вложенные сервисы и браузерная проверка; подложки и CDN требуют сети |
| 2 | Дорожный граф IduEdu | scripts/analytical_exports.py | `data/processed/analytical_export/today/graph_walk.pkl` | артефакты есть | Локальная УДС и OSM; расписание реального ОТ не моделируется |
| 3 | Зоны охвата сервисов | scripts/analytical_exports.py | `data/processed/analytical_export/today/coverage_school_walk.geojson` | артефакты есть | Сетевые зоны; буфер дорог 60 м — параметр визуализации |
| 4 | Изохроны | scripts/objectnat_analysis.py | `data/processed/objectnat/isochrones_today.geojson`<br>`data/processed/objectnat/isochrones_s2.geojson` | артефакты есть | Время по графу, модель шаттла; не наблюдаемые поездки |
| 5 | Обеспеченность по зданиям | scripts/analytical_exports.py | `data/processed/analytical_export/today/provision_kindergarten_buildings.geojson`<br>`data/processed/analytical_export/today/provision_kindergarten_services.geojson`<br>`data/processed/analytical_export/today/provision_kindergarten_links.geojson` | артефакты есть | Реальное распределение ObjectNat; дискретизация спроса библиотекой отделена от BlocksNet |
| 6 | Зоны видимости | scripts/objectnat_analysis.py | `data/processed/objectnat/visibility_today.geojson`<br>`data/processed/objectnat/visibility_s2.geojson` | артефакты есть | Геометрическая модель, препятствия по исходным слоям |
| 7 | Шумовое воздействие | scripts/objectnat_analysis.py | `data/processed/objectnat/noise_today.geojson`<br>`data/processed/objectnat/noise_s2.geojson` | артефакты есть | Расчётное воздействие, без натурных измерений |
| 8 | Генерация кварталов | scripts/blocks_generation.py | `data/processed/blockgen/blocks_generated.geojson`<br>`reports/blocks_generation.json` | артефакты есть | Независимая нарезка; канон526 не заменяется |
| 9 | Агрегация объектов | scripts/analysis.py | `data/processed/analysis/blocks_today.geojson` | артефакты есть | Площади и население; привязка выпавших зданий к ближайшему кварталу отражена в отчёте |
| 10 | Граф города BlocksNet | scripts/roadgraph.py; scripts/analytical_exports.py | `data/processed/analytical_export/s2/graph_transit.pkl` | артефакты есть | Сохранённые графы и GeoJSON; транспортный сценарий условный |
| 11 | Матрица доступности | scripts/analysis.py | `data/processed/analysis/acc_walk_today.pkl`<br>`data/processed/analysis/acc_drive_s2.pkl` | артефакты есть | Индексы OD позиционные0…525, кварталы id1…526 |
| 12 | Транспортная доступность | scripts/analysis.py | `reports/analysis_today.md`<br>`reports/analysis_s2.md` | артефакты есть | median_accessibility и время до опорных точек; не путать с area_accessibility модели стоимости |
| 13 | Конкурентная обеспеченность | scripts/analysis.py | `reports/provision_today.csv`<br>`reports/provision_s2.csv` | артефакты есть | Фактическая вместимость школ/детсадов; норматив и недоступность раздельно |
| 14 | Стоимость земли | scripts/land_value.py | `data/processed/urbanomy/land_today.geojson`<br>`reports/land_model_passport.json` | эксперимент; числовая подготовка обучения полностью не восстановлена | CatBoost курса; независимая проверка точности для Приморска отсутствует |
| 15 | Оптимизация кварталов | scripts/district_optimization.py | `reports/optimization_runs.csv` | частично: фронты марины/детсада; кампус невыполним; школа без геометрии | DistrictProblem+NSGA2; невыполнимость также результат, исследовательские пределы не регламент |
| 16 | Инвестиционная привлекательность | scripts/urbanomy_analysis.py | `reports/urbanomy.md` | артефакты есть | Демо-бенчмарки СПб, кадастровая земля; не банковское ТЭО |
| 17 | Стоимость до/после | scripts/land_value.py | `data/processed/urbanomy/land_s1.geojson`<br>`data/processed/urbanomy/land_s2.geojson`<br>`reports/land_summary.csv` | эксперимент; числовая подготовка обучения полностью не восстановлена | Одинаковая геометрия; обратное log1p, общая стоимость и руб./м² раздельно |

## Критерии завершения

Численная проверка признаков/единиц/населения и ограничений — unit tests и отчёты нового расчётного блока. Полный базовый конвейер и итоговая проверка — reports/completion-verification.md. Карта проверяется в браузере, Figma — чтением текста и снимками изменённых слайдов.

## Исходники учебной визуализации

[3D-блокнот и присвоение сервисов](https://drive.google.com/drive/folders/1jI25H0oHF69Xbmgl4LcVTS2S102O0E8o): адаптированы подход MapLibre5.6 и вложенный список сервисов. Исходные тестовые здания не используются как данные Приморска.

## Организационные зависимости

Официальная форма ТЭП кураторов, персональные зоны ответственности нынешней команды, полевые измерения шума и выборка стоимости для проверки точности не получены. Они не отмечаются выполненными. Содержательный аннотационный отчёт — docs/annotation-report.md; печатное соответствие ГОСТ без проверки макета не заявлено.
