"""Регресс-тесты диагностики ТЭП сценарных зданий (scripts/validate.py → scenario_tep_issues)."""
from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from validate import scenario_tep_issues


def _gdf(rows):
    return gpd.GeoDataFrame(rows, geometry=[Point(0, 0)] * len(rows), crs=4326)


def test_kindergarten_reference_passes():
    # эталон — детсад сценария 2 (id 29): GFA честно собран как пятно × этажность
    rows = [{"id": 29, "footprint_area": 1440.0, "number_of_floors": 2, "build_floor_area": 2880.0}]
    assert scenario_tep_issues(_gdf(rows)) == []


def test_dorm_contradiction_detected():
    # известное противоречие общежития id 16 в исходнике: GFA-атрибут = «пятно источника» × этажность,
    # что в 2,448 раза больше нарисованного пята — диагностика обязана это поймать
    rows = [{"id": 16, "footprint_area": 749.41, "number_of_floors": 5, "build_floor_area": 9172.70}]
    issues = scenario_tep_issues(_gdf(rows))
    assert len(issues) == 1 and "id 16" in issues[0] and "2.448" in issues[0]


def test_zero_parameters_flagged():
    rows = [{"id": 9, "footprint_area": 0.0, "number_of_floors": 2, "build_floor_area": 100.0}]
    assert scenario_tep_issues(_gdf(rows)) == ["id 9: нулевые пятно/этажность/общая площадь"]
