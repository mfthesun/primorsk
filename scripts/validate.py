"""
Проверка слоёв data/processed на соответствие требованиям курса (см. docs/requirements.md).
Пишет reports/validation_report.md и завершает работу с кодом 1, если есть ошибки (ERROR).

Запуск: python scripts/validate.py [папка_со_слоями]
"""
from __future__ import annotations

import re
import sys
import warnings
from pathlib import Path

import geopandas as gpd
import pyogrio
import shapely

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
DATA = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "processed"
MCRS = 32635

# поле -> допустимые типы GDAL
INT = {"int32", "int64"}
REAL = {"float64", "float32"}
STR = {"object"}
BOOL = {"bool"}
SCHEMA = {
    "boundary": {"name": STR, "population": INT},
    "building": {"build_floor_area": REAL, "living_area": REAL, "non_living_area": REAL,
                 "footprint_area": REAL, "number_of_floors": INT, "population": INT, "is_living": BOOL},
    "roads": {"highway_type": STR, "highway_type_id": INT},
}
GEOM = {
    "boundary": {"Polygon", "MultiPolygon"}, "building": {"Polygon", "MultiPolygon"},
    "blocks": {"Polygon"}, "landuse": {"Polygon", "MultiPolygon"},
    "water": {"Polygon", "MultiPolygon"}, "bay": {"Polygon", "MultiPolygon"},
    "lake": {"Polygon", "MultiPolygon"}, "river": {"LineString"},
    "railways": {"LineString", "MultiLineString"}, "roads": {"LineString", "MultiLineString"},
}
SERVICE_FIELDS = {"service_id": INT, "service_name": STR, "capacity": INT}
NOT_IN_BUILDING = {"bus_stop", "playground", "pitch", "cell_tower", "pier", "ice_rink"}
LINE_LAYERS = {"roads", "shuttle_route", "cycleway", "footway"}    # линейные слои сценария (highway_type)
# Сервисы, которых нет в таблице сервисов курса: service_id пуст по требованиям (docs/review_comments.md)
NO_SERVICE_ID = {"agricultural_services", "airport", "boilerhouse", "bus_stop", "cell_tower", "cemetery", "fuel",
                 "oopt", "park", "parking", "pitch", "playground", "port", "pumping_station", "train_station",
                 "wastewater_plant", "household", "research_center", "marketplace", "pier", "rental", "ice_rink",
                 "yacht_club"}

issues: list[tuple[str, str, str]] = []   # (level, layer, message)


def add(level, layer, msg):
    issues.append((level, layer, msg))


def fields(path):
    info = pyogrio.read_info(path)
    return dict(zip(info["fields"], info["dtypes"])), info


def common(layer, path, g):
    if g.crs is None or g.crs.to_epsg() != 4326:
        add("ERROR", layer, f"проекция {g.crs} вместо EPSG:4326")
    if not re.fullmatch(r"[a-z0-9_]+\.geojson", path.name):
        add("ERROR", layer, f"имя файла «{path.name}» должно быть латиницей с маленькой буквы")
    empty = (g.geometry.isna() | g.geometry.is_empty).sum()
    if empty:
        add("ERROR", layer, f"пустых геометрий: {empty}")
    inv = (~g.is_valid).sum()
    if inv:
        add("ERROR", layer, f"невалидных геометрий: {inv}")
    for f, t in fields(path)[0].items():
        if f != f.lower():
            add("WARN", layer, f"атрибут «{f}» содержит заглавные буквы")


def check_schema(layer, path, schema, no_id=False):
    flds, _ = fields(path)
    for f, types in schema.items():
        if f not in flds:
            add("ERROR", layer, f"нет обязательного атрибута {f}")
        elif flds[f] not in types:
            g = gpd.read_file(path, columns=[f])
            if g[f].isna().all():
                if no_id and f == "service_id":
                    add("INFO", layer, "service_id пуст: сервиса нет в таблице курса")
                    continue
                add("WARN", layer, f"атрибут {f} пустой у всех объектов (в GeoJSON читается как String)")
                continue
            add("ERROR", layer, f"атрибут {f}: тип {flds[f]}, нужен {'/'.join(sorted(types))}")


def main():
    bnd = gpd.read_file(DATA / "boundary.geojson")
    bnd_geom = bnd.union_all()
    bld = gpd.read_file(DATA / "building.geojson")
    for layer, geoms in GEOM.items():
        path = DATA / f"{layer}.geojson"
        if not path.exists():
            add("ERROR", layer, "файл отсутствует")
            continue
        g = gpd.read_file(path)
        common(layer, path, g)
        bad = set(g.geom_type.unique()) - geoms
        if bad:
            add("ERROR", layer, f"недопустимые типы геометрии: {sorted(bad)}")
        if g.geom_type.nunique() > 1:
            add("WARN", layer, f"смешанные типы геометрии: {g.geom_type.value_counts().to_dict()}")
        if layer in SCHEMA:
            check_schema(layer, path, SCHEMA[layer])

    # логика зданий
    for c in ("build_floor_area", "living_area", "non_living_area", "footprint_area", "population"):
        n = bld[c].isna().sum()
        if n:
            add("ERROR", "building", f"{c}: пустых значений {n}")
    liv = bld["is_living"].astype(bool)
    if (bld.loc[~liv, "population"] > 0).any():
        add("ERROR", "building", "у нежилых зданий есть население")
    if (bld.loc[liv, "population"] <= 0).any():
        add("ERROR", "building", f"жилые здания без населения: {(bld.loc[liv,'population']<=0).sum()}")
    if (bld["living_area"] > bld["build_floor_area"] + 0.01).any():
        add("ERROR", "building", "жилая площадь больше общей")
    if (bld["build_floor_area"] + 0.01 < bld["footprint_area"]).any():
        add("WARN", "building", f"общая площадь меньше пятна застройки: {(bld['build_floor_area']+0.01<bld['footprint_area']).sum()}")
    if abs(bld["population"].sum() - int(bnd["population"].iloc[0])) > 0:
        add("ERROR", "building", f"сумма населения {bld['population'].sum()} ≠ population границы {bnd['population'].iloc[0]}")

    # кварталы — наложения
    bl = gpd.read_file(DATA / "blocks.geojson").to_crs(MCRS)
    s = gpd.sjoin(bl, bl, predicate="overlaps")
    s = s[s.index < s.index_right]
    ov = sum(bl.geometry.iloc[i].intersection(bl.geometry.iloc[j]).area for i, j in zip(s.index, s.index_right))
    if ov > 1:
        add("ERROR", "blocks", f"наложения кварталов: {len(s)} пар, {ov:.0f} м²")

    # сервисы
    bm = bld.to_crs(MCRS)
    tree = shapely.STRtree(bm.geometry.values)
    ids: dict[int, set] = {}
    for folder in ("services", "scenario"):
        d = DATA / folder
        if not d.exists():
            add("ERROR", folder, "папка отсутствует")
            continue
        extra = gpd.read_file(d / "building.geojson").to_crs(MCRS) if (d / "building.geojson").exists() else None
        tree2 = shapely.STRtree(extra.geometry.values) if extra is not None else None
        for path in sorted(d.glob("*.geojson")):
            svc = path.stem
            layer = f"{folder}/{svc}"
            g = gpd.read_file(path)
            common(layer, path, g)
            if folder == "scenario" and svc in {"building", "boundary", "landuse", "blocks"} | LINE_LAYERS:
                if svc == "building":
                    check_schema(layer, path, SCHEMA["building"])
                if svc == "boundary":
                    check_schema(layer, path, {"population": INT})
                if svc in LINE_LAYERS:
                    check_schema(layer, path, SCHEMA["roads"])
                continue
            check_schema(layer, path, SERVICE_FIELDS, no_id=svc in NO_SERVICE_ID)
            if "service_id" in g and g["service_id"].notna().any():
                for sid in g["service_id"].dropna().unique():
                    ids.setdefault(int(sid), set()).add(svc)
            if folder == "services" and (~g.intersects(bnd_geom)).any():
                add("ERROR", layer, f"объекты за границей: {(~g.intersects(bnd_geom)).sum()}")
            if g.geom_type.isin(["MultiPoint"]).any():
                add("ERROR", layer, "MultiPoint — нужна точка (центроид)")
            if svc in ("school", "kindergarten") and (g["capacity"].isna() | (g["capacity"] <= 1)).any():
                add("ERROR", layer, "не заполнена вместимость (capacity)")
            if g.geom_type.eq("Point").all() and svc not in NOT_IN_BUILDING and len(g):
                pts = g.to_crs(MCRS).geometry.values
                on = [len(tree.query(p, predicate="within")) > 0 or
                      (tree2 is not None and len(tree2.query(p, predicate="within")) > 0) for p in pts]
                off = len(on) - sum(on)
                if off:
                    add("WARN", layer, f"точек не на полигоне здания: {off} из {len(on)}")

    for sid, svcs in sorted(ids.items()):
        if len(svcs) > 1:
            add("ERROR", "services", f"service_id {sid} у разных сервисов: {', '.join(sorted(svcs))}")

    # отчёт
    rep = ROOT / "reports" / "validation_report.md"
    rep.parent.mkdir(exist_ok=True)
    n_err = sum(1 for i in issues if i[0] == "ERROR")
    n_warn = sum(1 for i in issues if i[0] == "WARN")
    n_info = sum(1 for i in issues if i[0] == "INFO")
    lines = [f"# Отчёт валидации `{DATA.relative_to(ROOT) if DATA.is_relative_to(ROOT) else DATA}`", "",
             f"Ошибок: **{n_err}**, предупреждений: **{n_warn}**, справочно: {n_info}", "",
             "| Уровень | Слой | Сообщение |", "|---|---|---|"]
    lines += [f"| {lvl} | {lay} | {msg} |" for lvl, lay, msg in issues]
    lines += ["", "## Сводка по зданиям", "",
              f"- зданий: {len(bld)}, жилых: {int(liv.sum())}, нежилых: {int((~liv).sum())}",
              f"- население: {int(bld['population'].sum())} (граница: {int(bnd['population'].iloc[0])})"]
    rep.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    sys.exit(1 if n_err else 0)


if __name__ == "__main__":
    main()
