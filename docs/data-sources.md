# Источники данных

Определено по составу атрибутов исходных слоёв (`data/raw/`). Даты выгрузок в исходниках не сохранились —
при обновлении слоя дописывайте дату и способ получения.

| Слой | Источник | Признак |
|---|---|---|
| `boundary` | OpenStreetMap; население — Росстат | — |
| `building` | OpenStreetMap (геометрия) + Реестр домов (площади, этажность жилых) | `living_area` > 0 у сопоставленных с реестром |
| `landuse` | Генеральный план МО «Приморское городское поселение» (векторные слои ФЗ, формат ФГИС ТП) | `gml_id`, `globalid`, `classid`; `status` 1 — существующее (2022), 2 — планируемое (2042–2043) |
| `roads` | Слои ГП / СТП (ФГИС ТП); поле `source`: «ингео», «топооснова», «предложения генерального плана», «СТП ЛО», «СТП Выборгского района» | `highway_type` — по `reg_rdtype` (региональные 41А/41К) |
| `railways` | ГП (ФГИС ТП) | — |
| `water`, `bay`, `lake`, `river`, `forest` | OpenStreetMap | — |
| `blocks` | генерация по методике курса (BlocksNet, ноутбук курса) + ручная корректировка | — |
| сервисы ФГИС ТП / ГП | boilerhouse, camp, cell_tower, emergency, extra_education, fire_station, fuel, historic (приказы комитета по культуре ЛО 2018–2019), hospital, kindergarten, pharmacy, polyclinic, post_office, public_bath, pumping_station, religion, school, train_station | `GLOBALID`, `CLASSID` |
| сервисы OSM | airport, bank, beauty, bus_stop, cafe, cemetery, clothes, community_centre, convenience, dentist, hairdresser, hotel, library, mfz, museum, oopt, park, parking, pitch, playground, port, restaurant, supermarket | `osm_id` |
| сервисы, отрисованные вручную | agricultural_services, outpost, police, wastewater_plant | только `service_*` |
| сценарий | границы и ВРИ — кадастр (НСПД): з/у 47:01:0401004:19; остальное — проектные решения команды | `cad_num` |

Вместимости школ и детских садов заполнены вручную (с сайтов учреждений).

Аптеки, почта и другие сервисы из ГП отражают учтённые в генплане объекты и могут быть неполными —
для них стоит сверка с OSM / 2ГИС (см. `docs/review_comments.md`).
