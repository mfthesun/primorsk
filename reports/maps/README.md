# Карты для презентации

Генерируются `scripts/maps.py`. Заголовков на картах нет — подписи к рисункам ниже. Макет единый: кадр 4:3, север — вверху справа, масштабная линейка — внизу слева, условные обозначения — внизу справа; подложка Esri (World Light Gray Canvas — тематические карты, World Imagery — сценарий).

| Файл | Подпись к рисунку | Источник |
|---|---|---|
| `access_median_drive.png` | Транспортная связность кварталов: медианное время на автомобиле до остальных кварталов (median_accessibility) | blocks_before.geojson (BlocksNet median_accessibility) |
| `access_station_drive.png` | Доступность ж/д станции Приморск на автомобиле (от центра застройки квартала) | blocks_before.geojson; граф УДС roads.geojson + OSM (roadgraph.py), матрица BlocksNet |
| `blocks_population_density.png` | Плотность населения по кварталам | blocks_before.geojson — агрегация зданий по кварталам (BlocksNet aggregate_objects) |
| `buildings_floors_settlement.png` | Этажность застройки | building.geojson |
| `buildings_floors_town.png` | Этажность застройки, г. Приморск | building.geojson |
| `buildings_living_settlement.png` | Жилые и нежилые здания | building.geojson (OSM, Реестр домов; корректировка is_living — process.py) |
| `buildings_living_town.png` | Жилые и нежилые здания, г. Приморск | building.geojson (OSM, Реестр домов; корректировка is_living — process.py) |
| `provision_kindergarten_drive.png` | Обеспеченность детскими садами: с подвозом (транспорт), ≤ 15 мин | blocks_before.geojson (BlocksNet competitive_provision); вместимость — capacity |
| `provision_kindergarten_walk.png` | Обеспеченность детскими садами: пешком, ≤ 7 мин | blocks_before.geojson (BlocksNet competitive_provision); вместимость — capacity |
| `provision_school_drive.png` | Обеспеченность школами: с подвозом (транспорт), ≤ 30 мин | blocks_before.geojson (BlocksNet competitive_provision); вместимость — capacity |
| `provision_school_walk.png` | Обеспеченность школами: пешком, ≤ 15 мин | blocks_before.geojson (BlocksNet competitive_provision); вместимость — capacity |
| `scenario_projects.png` | Проектные предложения: кампус ИНТЦ, марина, транспортный каркас | data/processed/scenario (проектные решения команды) |
