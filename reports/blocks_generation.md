# Независимая генерация кварталов BlocksNet

Воспроизведение: `.venv-blocksnet/bin/python scripts/blocks_generation.py`. Результаты — `data/processed/blockgen/`; исходные 526 кварталов не заменяются.

Использован реальный API BlocksNet 1.0.0a9 `blocksnet.blocks.cutting.cut_urban_blocks(boundaries_gdf, lines_gdf, polygons_gdf)`. В границе поселения нарезаны существующие дороги и железные дороги (event_time ≤ 2022) и линии рек; водные полигоны water и lake исключены. Применяются метрические геометрии EPSG:32635, экспорт EPSG:4326. Нет classifier и дополнительной ручной/кластерной нарезки.

По docs/data-sources.md канонические кварталы получены методикой курса с ручной корректировкой; process.py только очищает исходный blocks.geojson. Поэтому совпадение количества 526 не является ожидаемым результатом независимой нарезки. Геометрия линий без дополнительного snapping: разрывы могут оставлять крупные ненарезанные полигоны. Канонические кварталы и независимые полигоны могут различаться охватом леса, суши и детализацией. Разбиения/объединения считаются по пересечениям >1 м². Доля границы включает исходный водный охват; это не доля застроенной территории.

```json
{
  "generated_count": 361,
  "canonical_count": 526,
  "generated_area_ha": 66481.39838275117,
  "canonical_area_ha": 64959.25653051348,
  "boundary_area_ha": 335997.2041361205,
  "canonical_area_covered_share": 0.999974325670004,
  "generated_area_in_canonical_share": 0.9770791578592681,
  "generated_boundary_coverage_share": 0.19786295113282787,
  "intersection_over_union": 0.9770546469775591,
  "generated_internal_overlap_m2": 4.410743713378906e-06,
  "canonical_split_count": 15,
  "generated_merge_count": 36,
  "overlap_pairs": 548,
  "overlap_pair_min_area_m2": 1,
  "inputs": {
    "boundary": {
      "sha256": "d5800a10312d026e2e23b38b9c8f1d4d67b31bba9765cf351f52500982b7d784",
      "used_features": 1
    },
    "roads": {
      "sha256": "f8f3120adb122b708eff2736d25f00b3cab4f2239f18f9fa6ad9646d71c856c6",
      "used_features": 956
    },
    "railways": {
      "sha256": "5247a83338ae34c5d42ead78087a9c96b8682fb065513d0aeb66dcf87097e30f",
      "used_features": 8
    },
    "water": {
      "sha256": "783a22d9c5f86a570c602763276f14c0c48a573c77ae1dc5af797b714cf5f9e9",
      "used_features": 1
    },
    "lake": {
      "sha256": "704fcbe887e3afaedbc4af08a50b16bb063bf56f20066d45a050a006254cc3ed",
      "used_features": 70
    },
    "river": {
      "sha256": "584bbb1dee8e4248e4d7c6b863bc6a66a6b6f1ca63b1fe35ccbfd192232223c1",
      "used_features": 230
    },
    "blocks": {
      "sha256": "28f85ec51dd5d514014f713a5cdf33cd16940249c73292e25d15fcd871945f1d",
      "used_features": 526
    }
  },
  "method": "blocksnet.blocks.cutting.cut_urban_blocks; existing roads+railways+river lines; water+lake polygons; no classifier, no manual edits, no topology snapping, no external downloads"
}
```