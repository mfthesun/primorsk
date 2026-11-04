# Аналитические экспорты курса

Воспроизведение: `.venv-objectnat/bin/python scripts/analytical_exports.py`.

Графы — существующая модель roadgraph.scenario_graphs, крупнейшая компонента; walk/drive/transit. Pickle: EPSG:32635; GeoJSON: EPSG:4326. Transit сегодня совпадает с walk; сценарный шаттл — гипотеза с ожиданием половины интервала.

Зоны — ObjectNat 2.1 get_graph_coverage, multi-source Dijkstra, разделение Voronoi по ближайшему сервису, geometry_type=ways, буфер дорог 60 м, обрезка границей. Самокасания колец после проекции исправляются make_valid, полигональные компоненты сохраняются (без convex hull). Это зоны сетевой доступности без конкуренции за вместимость, не радиус и не convex hull. Привязка к ближайшему узлу не учитывает время подхода от двери.

Обеспеченность — фактическая разреженная матрица flow из get_service_provision(seed=0), capacity_rows и demand_rows. Links — прямые связи распределения, не маршруты; allocated сохраняет исходную точность; time_min — OD графа. ObjectNat 2.1 отбрасывает дробную часть спроса каждого дома (astype(int)); дома со спросом <1 теряются для распределения. source_demand сохраняет нормативный дробный спрос, demand — целочисленный спрос библиотеки. library_integer_demand, supplied_within и supplied_outside приведены отдельно. Это существенное ограничение метода на уровне малых домов: результаты не заменяют нормативный дефицит BlocksNet и не сравниваются с ним как один показатель. Нормативы детсада 61/40, школы 91/61 места на 1000 (город/село), пороги 7/15 минут. Устойчивые object_id содержат слой, existing/scenario и исходный id (для сервисов без id — порядковый номер исходной записи).

Нулевая capacity поликлиник означает неизвестную вместимость, не отсутствие обслуживания. Поэтому для них только зоны доступности; модель распределения запускается для школ и детсадов с положительными известными вместимостями. Исходные вместимости из существующих слоёв; актуальность на 2026 год независимо не подтверждена.

## today
```json
{
  "scenario": "today",
  "graphs": {
    "walk": {
      "nodes": 8596,
      "edges": 10172,
      "time_min_min": 0.012046472491766307,
      "length_meter_sum": 1410116.7371591409
    },
    "drive": {
      "nodes": 7974,
      "edges": 9086,
      "time_min_min": 0.01,
      "length_meter_sum": 1223661.1466935275
    },
    "transit": {
      "nodes": 8596,
      "edges": 10172,
      "time_min_min": 0.012046472491766307,
      "length_meter_sum": 1410116.7371591409
    }
  },
  "source_graph_info": {
    "walk": {
      "nodes": 9032,
      "edges": 10587,
      "km": 1481.4,
      "components": 67,
      "largest_share": 0.952,
      "gap_links": 2066,
      "km_by_source": {
        "roads": 387.9,
        "gap": 29.1,
        "osm": 1064.4
      }
    },
    "drive": {
      "nodes": 8527,
      "edges": 9561,
      "km": 1303.9,
      "components": 117,
      "largest_share": 0.935,
      "gap_links": 2050,
      "km_by_source": {
        "roads": 388.0,
        "gap": 29.0,
        "osm": 886.9
      }
    }
  },
  "coverage": {
    "school": {
      "sources": 6,
      "zones": 6,
      "union_area_ha": 807.6518507496496,
      "threshold_min": 15
    },
    "kindergarten": {
      "sources": 4,
      "zones": 4,
      "union_area_ha": 150.38544663540125,
      "threshold_min": 7
    },
    "polyclinic": {
      "sources": 5,
      "zones": 5,
      "union_area_ha": 764.5012533957171,
      "threshold_min": 15
    }
  },
  "provision": {
    "kindergarten": {
      "buildings": 2832,
      "services": 4,
      "links": 71,
      "allocated": 230.0,
      "source_demand": 680.6759999999999,
      "library_integer_demand": 256,
      "supplied_within": 202,
      "supplied_outside": 28,
      "unallocated_library_demand": 26,
      "source_capacity": 470.0,
      "threshold_min": 7,
      "seed": 0,
      "demand_columns": [
        "demand",
        "demand_left",
        "supplied_demands_within",
        "supplied_demands_without",
        "min_dist",
        "avg_dist",
        "provision_value"
      ],
      "capacity_columns": [
        "capacity",
        "capacity_left",
        "carried_capacity_within",
        "carried_capacity_without",
        "service_load"
      ]
    },
    "school": {
      "buildings": 2832,
      "services": 6,
      "links": 107,
      "allocated": 409.0,
      "source_demand": 1025.079,
      "library_integer_demand": 429,
      "supplied_within": 384,
      "supplied_outside": 25,
      "unallocated_library_demand": 20,
      "source_capacity": 1847.0,
      "threshold_min": 15,
      "seed": 0,
      "demand_columns": [
        "demand",
        "demand_left",
        "supplied_demands_within",
        "supplied_demands_without",
        "min_dist",
        "avg_dist",
        "provision_value"
      ],
      "capacity_columns": [
        "capacity",
        "capacity_left",
        "carried_capacity_within",
        "carried_capacity_without",
        "service_load"
      ]
    }
  }
}
```

## s1
```json
{
  "scenario": "s1",
  "graphs": {
    "walk": {
      "nodes": 8881,
      "edges": 10456,
      "time_min_min": 0.012046472491766307,
      "length_meter_sum": 1410104.082973308
    },
    "drive": {
      "nodes": 7974,
      "edges": 9086,
      "time_min_min": 0.01,
      "length_meter_sum": 1223661.1466935275
    },
    "transit": {
      "nodes": 8881,
      "edges": 10462,
      "time_min_min": 0.012046472491766307,
      "length_meter_sum": 1439418.096739101
    }
  },
  "source_graph_info": {
    "walk": {
      "nodes": 9317,
      "edges": 10871,
      "km": 1481.4,
      "components": 67,
      "largest_share": 0.953,
      "gap_links": 2036,
      "km_by_source": {
        "roads": 386.9,
        "gap": 28.6,
        "scenario": 3.0,
        "osm": 1062.8
      }
    },
    "drive": {
      "nodes": 8527,
      "edges": 9561,
      "km": 1303.9,
      "components": 117,
      "largest_share": 0.935,
      "gap_links": 2050,
      "km_by_source": {
        "roads": 388.0,
        "gap": 29.0,
        "osm": 886.9
      }
    },
    "transit": {
      "nodes": 8881,
      "edges": 10462,
      "km": 1439.4,
      "components": 1,
      "largest_share": 1.0,
      "gap_links": 1959,
      "km_by_source": {
        "roads": 377.8,
        "gap": 27.6,
        "scenario": 32.3,
        "osm": 1001.6
      },
      "stops": 4
    }
  },
  "coverage": {
    "school": {
      "sources": 6,
      "zones": 6,
      "union_area_ha": 808.240785972198,
      "threshold_min": 15
    },
    "kindergarten": {
      "sources": 4,
      "zones": 4,
      "union_area_ha": 150.70030893093107,
      "threshold_min": 7
    },
    "polyclinic": {
      "sources": 5,
      "zones": 5,
      "union_area_ha": 765.5078399391194,
      "threshold_min": 15
    }
  },
  "provision": {
    "kindergarten": {
      "buildings": 2833,
      "services": 4,
      "links": 72,
      "allocated": 230.0,
      "source_demand": 685.251,
      "library_integer_demand": 260,
      "supplied_within": 202,
      "supplied_outside": 28,
      "unallocated_library_demand": 30,
      "source_capacity": 470.0,
      "threshold_min": 7,
      "seed": 0,
      "demand_columns": [
        "demand",
        "demand_left",
        "supplied_demands_within",
        "supplied_demands_without",
        "min_dist",
        "avg_dist",
        "provision_value"
      ],
      "capacity_columns": [
        "capacity",
        "capacity_left",
        "carried_capacity_within",
        "carried_capacity_without",
        "service_load"
      ]
    },
    "school": {
      "buildings": 2833,
      "services": 6,
      "links": 107,
      "allocated": 409.0,
      "source_demand": 1031.904,
      "library_integer_demand": 435,
      "supplied_within": 384,
      "supplied_outside": 25,
      "unallocated_library_demand": 26,
      "source_capacity": 1847.0,
      "threshold_min": 15,
      "seed": 0,
      "demand_columns": [
        "demand",
        "demand_left",
        "supplied_demands_within",
        "supplied_demands_without",
        "min_dist",
        "avg_dist",
        "provision_value"
      ],
      "capacity_columns": [
        "capacity",
        "capacity_left",
        "carried_capacity_within",
        "carried_capacity_without",
        "service_load"
      ]
    }
  }
}
```

## s2
```json
{
  "scenario": "s2",
  "graphs": {
    "walk": {
      "nodes": 8881,
      "edges": 10456,
      "time_min_min": 0.012046472491766307,
      "length_meter_sum": 1410104.082973308
    },
    "drive": {
      "nodes": 7974,
      "edges": 9086,
      "time_min_min": 0.01,
      "length_meter_sum": 1223661.1466935275
    },
    "transit": {
      "nodes": 8881,
      "edges": 10462,
      "time_min_min": 0.012046472491766307,
      "length_meter_sum": 1439418.096739101
    }
  },
  "source_graph_info": {
    "walk": {
      "nodes": 9317,
      "edges": 10871,
      "km": 1481.4,
      "components": 67,
      "largest_share": 0.953,
      "gap_links": 2036,
      "km_by_source": {
        "roads": 386.9,
        "gap": 28.6,
        "scenario": 3.0,
        "osm": 1062.8
      }
    },
    "drive": {
      "nodes": 8527,
      "edges": 9561,
      "km": 1303.9,
      "components": 117,
      "largest_share": 0.935,
      "gap_links": 2050,
      "km_by_source": {
        "roads": 388.0,
        "gap": 29.0,
        "osm": 886.9
      }
    },
    "transit": {
      "nodes": 8881,
      "edges": 10462,
      "km": 1439.4,
      "components": 1,
      "largest_share": 1.0,
      "gap_links": 1959,
      "km_by_source": {
        "roads": 377.8,
        "gap": 27.6,
        "scenario": 32.3,
        "osm": 1001.6
      },
      "stops": 4
    }
  },
  "coverage": {
    "school": {
      "sources": 6,
      "zones": 6,
      "union_area_ha": 808.240785972198,
      "threshold_min": 15
    },
    "kindergarten": {
      "sources": 5,
      "zones": 5,
      "union_area_ha": 162.56480412168992,
      "threshold_min": 7
    },
    "polyclinic": {
      "sources": 5,
      "zones": 5,
      "union_area_ha": 765.5078399391194,
      "threshold_min": 15
    }
  },
  "provision": {
    "kindergarten": {
      "buildings": 2833,
      "services": 5,
      "links": 73,
      "allocated": 231.0,
      "source_demand": 685.251,
      "library_integer_demand": 260,
      "supplied_within": 202,
      "supplied_outside": 29,
      "unallocated_library_demand": 29,
      "source_capacity": 630.0,
      "threshold_min": 7,
      "seed": 0,
      "demand_columns": [
        "demand",
        "demand_left",
        "supplied_demands_within",
        "supplied_demands_without",
        "min_dist",
        "avg_dist",
        "provision_value"
      ],
      "capacity_columns": [
        "capacity",
        "capacity_left",
        "carried_capacity_within",
        "carried_capacity_without",
        "service_load"
      ]
    },
    "school": {
      "buildings": 2833,
      "services": 6,
      "links": 107,
      "allocated": 409.0,
      "source_demand": 1031.904,
      "library_integer_demand": 435,
      "supplied_within": 384,
      "supplied_outside": 25,
      "unallocated_library_demand": 26,
      "source_capacity": 1847.0,
      "threshold_min": 15,
      "seed": 0,
      "demand_columns": [
        "demand",
        "demand_left",
        "supplied_demands_within",
        "supplied_demands_without",
        "min_dist",
        "avg_dist",
        "provision_value"
      ],
      "capacity_columns": [
        "capacity",
        "capacity_left",
        "carried_capacity_within",
        "carried_capacity_without",
        "service_load"
      ]
    }
  }
}
```
