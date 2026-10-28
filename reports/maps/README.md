# Карты для презентации

Генерируются `scripts/maps.py`. Заголовков на картах нет — подписи к рисункам ниже. Макет единый: кадр 4:3, север — вверху справа, масштабная линейка — внизу слева, условные обозначения — внизу справа; подложка Esri (World Light Gray Canvas — тематические карты, World Imagery — сценарий).

| Файл | Подпись к рисунку | Источник |
|---|---|---|
| `access_median_drive.png` | Транспортная связность кварталов: медианное время на автомобиле до остальных кварталов (median_accessibility) | blocks_today.geojson (BlocksNet median_accessibility) |
| `access_station_drive.png` | Доступность ж/д станции Приморск на автомобиле (от центра застройки квартала) | blocks_today.geojson; граф УДС roads.geojson + OSM (roadgraph.py), матрица BlocksNet |
| `blocks_population_density.png` | Плотность населения по кварталам | blocks_today.geojson — агрегация зданий по кварталам (BlocksNet aggregate_objects) |
| `buildings_floors_settlement.png` | Этажность застройки | building.geojson |
| `buildings_floors_town.png` | Этажность застройки, г. Приморск | building.geojson |
| `buildings_living_settlement.png` | Жилые и нежилые здания | building.geojson (OSM, Реестр домов; корректировка is_living — process.py) |
| `buildings_living_town.png` | Жилые и нежилые здания, г. Приморск | building.geojson (OSM, Реестр домов; корректировка is_living — process.py) |
| `location_region.png` | Приморское городское поселение в Ленинградской области: 132 км до Санкт-Петербурга, 47 км до Выборга | region_context.geojson (границы OSM), boundary.geojson |
| `provision_kindergarten_drive.png` | Обеспеченность детскими садами: с подвозом (транспорт), ≤ 15 мин | blocks_today.geojson (BlocksNet competitive_provision); вместимость — capacity |
| `provision_kindergarten_drive_s2.png` | Обеспеченность детскими садами: с подвозом (транспорт), ≤ 15 мин, сценарий 2 | blocks_s2.geojson (BlocksNet competitive_provision); вместимость — capacity |
| `provision_kindergarten_drive_town.png` | Обеспеченность детскими садами: с подвозом (транспорт), ≤ 15 мин, г. Приморск, сегодня | blocks_today.geojson (BlocksNet competitive_provision); вместимость — capacity |
| `provision_kindergarten_drive_town_s2.png` | Обеспеченность детскими садами: с подвозом (транспорт), ≤ 15 мин, г. Приморск, сценарий 2 | blocks_s2.geojson (BlocksNet competitive_provision); вместимость — capacity |
| `provision_kindergarten_walk.png` | Обеспеченность детскими садами: пешком, ≤ 7 мин | blocks_today.geojson (BlocksNet competitive_provision); вместимость — capacity |
| `provision_kindergarten_walk_s2.png` | Обеспеченность детскими садами: пешком, ≤ 7 мин, сценарий 2 | blocks_s2.geojson (BlocksNet competitive_provision); вместимость — capacity |
| `provision_kindergarten_walk_town.png` | Обеспеченность детскими садами: пешком, ≤ 7 мин, г. Приморск, сегодня | blocks_today.geojson (BlocksNet competitive_provision); вместимость — capacity |
| `provision_kindergarten_walk_town_s2.png` | Обеспеченность детскими садами: пешком, ≤ 7 мин, г. Приморск, сценарий 2 | blocks_s2.geojson (BlocksNet competitive_provision); вместимость — capacity |
| `provision_school_drive.png` | Обеспеченность школами: с подвозом (транспорт), ≤ 30 мин | blocks_today.geojson (BlocksNet competitive_provision); вместимость — capacity |
| `provision_school_walk.png` | Обеспеченность школами: пешком, ≤ 15 мин | blocks_today.geojson (BlocksNet competitive_provision); вместимость — capacity |
| `scenario_projects.png` | Проектные предложения: кампус ИНТЦ, марина, транспортный каркас, детский сад | data/processed/scenario (проектные решения команды) |
| `town_access_transit_s2.png` | Зоны доступности 30 мин без автомобиля (пешком + шаттл) от ж/д станции и порта, сценарий 2 | ObjectNat get_graph_isochrones, isochrones_s2.geojson |
| `town_access_transit_today.png` | Зоны доступности 30 мин без автомобиля (пешком) от ж/д станции и порта, сегодня | ObjectNat get_graph_isochrones, isochrones_today.geojson |
| `town_noise_s2.png` | Шумовое воздействие ж/д, магистральных улиц и порта, сценарий 2 | ObjectNat calculate_simplified_noise_frame, noise_s2.geojson |
| `town_noise_today.png` | Шумовое воздействие ж/д, магистральных улиц и порта, сегодня | ObjectNat calculate_simplified_noise_frame, noise_today.geojson |
| `town_visibility_s2.png` | Зоны видимости с пешеходного маршрута по набережной (до 600 м), сценарий 2 | ObjectNat get_visibility, visibility_s2.geojson |
| `town_visibility_today.png` | Зоны видимости с пешеходного маршрута по набережной (до 600 м), сегодня | ObjectNat get_visibility, visibility_today.geojson |
