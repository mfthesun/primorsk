"""
Исправление замечаний и приведение слоёв Приморского ГП к требованиям курса
«Цифровое моделирование урбанизированных территорий».

Вход:  data/raw/            — слои в том виде, в каком они были сданы (geojson + gpkg)
Выход: data/processed/      — исправленные слои в GeoJSON, EPSG:4326
       reports/*.csv        — журналы изменений для ручной проверки в QGIS

Запуск из корня репозитория:  python scripts/process.py
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import MultiPoint, Point

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"
REP = ROOT / "reports"
CRS = 4326          # требуемая проекция
MCRS = 32635        # метрическая проекция для площадей/расстояний (UTM 35N)

TERRITORY_NAME = "Приморское городское поселение"
# Численность населения (как в сданном boundary). Перед сдачей сверить с Росстатом
# (оценка на 01.01.2024/2025) и при необходимости поменять здесь.
TERRITORY_POPULATION = 13659

# ---- параметры корректировки is_living -------------------------------------
RES_ZONES = {
    "Зона застройки индивидуальными жилыми домами",
    "Зона застройки малоэтажными жилыми домами (до 4 этажей, включая мансардный)",
    "Зона застройки среднеэтажными жилыми домами (от 5 до 8 этажей, включая мансардный)",
    "Зона застройки многоэтажными жилыми домами (9 этажей и более)",
    "Зона смешанной и общественно-деловой застройки",
}
GARDEN_ZONE = "Зона садоводства, огородничества"
UNSPECIFIED_ZONES = {"Иные зоны", "нет зоны"}
MIN_HOUSE = 40.0      # м², меньше — хозпостройки (бани, сараи, гаражи)
MAX_HOUSE = 400.0     # м², больше — без данных реестра считаем нежилым
MAX_HOUSE_UNSPEC = 300.0
NEIGHBOUR_RADIUS = 150.0   # м, «Иные зоны»: жилой, если рядом есть жилые дома из реестра
NEIGHBOUR_MIN = 2
AUX_MAX = 70.0        # м², постройка до этой площади рядом с более крупным домом = хозпостройка
AUX_RADIUS = 12.0     # м
LIVING_COEF = 0.7     # доля жилой площади в общей площади для домов без данных реестра

# Сервисы, которые по смыслу должны стоять на здании (точка на полигоне building)
NOT_IN_BUILDING = {"bus_stop", "playground", "pitch", "cell_tower"}
SNAP_DIST = 60.0      # м — максимальное расстояние переноса точки на здание
LOG_COLS = ["service", "row", "action", "distance_m"]
CAPACITY_SERVICES = {"school", "kindergarten", "extra_education", "fuel", "college"}


def write(gdf: gpd.GeoDataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    gdf = gdf.to_crs(CRS)
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
    gdf.to_file(path, driver="GeoJSON", engine="pyogrio")


def read(path: Path, layer: str | None = None) -> gpd.GeoDataFrame:
    g = gpd.read_file(path, layer=layer) if layer else gpd.read_file(path)
    if g.crs is None:
        g = g.set_crs(CRS)
    return g.to_crs(CRS)


def fix_geom(g: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    g = g[g.geometry.notna() & ~g.geometry.is_empty].copy()
    bad = ~g.is_valid
    if bad.any():
        g.loc[bad, "geometry"] = g.loc[bad].make_valid()
    return g[~g.geometry.is_empty].copy()


def lower_cols(g: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Названия атрибутов — с маленькой буквы (замечание преподавателя)."""
    ren, seen = {}, set(c for c in g.columns if c == c.lower())
    for c in g.columns:
        if c == "geometry" or c == c.lower():
            continue
        n = c.lower()
        if n in seen:
            n = n + "_src"
        ren[c] = n
        seen.add(n)
    return g.rename(columns=ren)


def only_polygons(geom):
    if geom is None:
        return None
    if geom.geom_type in ("Polygon", "MultiPolygon"):
        return geom
    if geom.geom_type == "GeometryCollection":
        polys = [p for p in geom.geoms if p.geom_type in ("Polygon", "MultiPolygon")]
        return shapely.union_all(polys) if polys else None
    return None


# =============================================================================
def boundary() -> gpd.GeoDataFrame:
    b = fix_geom(read(RAW / "boundary.geojson"))
    geom = shapely.union_all(b.geometry.values)
    if geom.geom_type == "MultiPolygon" and len(geom.geoms) == 1:
        geom = geom.geoms[0]
    out = gpd.GeoDataFrame(
        {"name": [TERRITORY_NAME], "population": pd.array([TERRITORY_POPULATION], dtype="int32")},
        geometry=[geom], crs=CRS)
    write(out, OUT / "boundary.geojson")
    return out


# =============================================================================
def building(bnd: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    g = fix_geom(read(RAW / "building.geojson"))
    g = g.reset_index(drop=True)
    g["id"] = np.arange(1, len(g) + 1, dtype="int32")
    gm = g.to_crs(MCRS)
    g["footprint_area"] = gm.area.round(2)
    g["number_of_floors"] = g["number_of_floors"].fillna(1).clip(lower=1).round().astype("int32")
    registry = g["living_area"].fillna(0) > 0        # дом сопоставлен с Реестром
    old = g["is_living"].astype(bool)

    # зона ФЗ по точке внутри здания
    lu = fix_geom(read(RAW / "landuse.geojson"))[["name", "geometry"]].to_crs(MCRS)
    pts = gpd.GeoDataFrame(geometry=gm.representative_point(), crs=MCRS)
    j = gpd.sjoin(pts, lu, how="left", predicate="within")
    j = j[~j.index.duplicated(keep="first")]
    g["zone"] = j["name"].fillna("нет зоны").values

    fa = g["footprint_area"]
    floors = g["number_of_floors"]
    rule = pd.Series("нежилое по умолчанию", index=g.index)
    new = pd.Series(False, index=g.index)

    # 1. дома из реестра — жилые
    new[registry] = True
    rule[registry] = "реестр"
    # 2. садоводства — нежилые (кроме многоквартирных: >2 этажей или >400 м²)
    garden = (g["zone"] == GARDEN_ZONE) & (floors <= 2) & (fa <= MAX_HOUSE)
    new[garden] = False
    rule[garden] = "садоводство -> нежилое"
    # 3. жилые зоны: дома 40–400 м² без данных реестра
    res = (~registry) & g["zone"].isin(RES_ZONES) & fa.between(MIN_HOUSE, MAX_HOUSE) & (floors <= 3)
    new[res] = True
    rule[res] = "жилая зона ФЗ, 40–400 м²"
    # 4. «Иные зоны»/без зоны (деревни без детального ФЗ): рядом есть жилые дома из реестра
    reg_pts = gm[registry].representative_point()
    tree = shapely.STRtree(reg_pts.values)
    cand = (~registry) & g["zone"].isin(UNSPECIFIED_ZONES) & fa.between(MIN_HOUSE, MAX_HOUSE_UNSPEC) & (floors <= 3)
    cpts = gm.loc[cand].representative_point()
    if len(cpts):
        pairs = tree.query(cpts.values, predicate="dwithin", distance=NEIGHBOUR_RADIUS)
        cnt = np.bincount(pairs[0], minlength=len(cpts))
        ok = cpts.index[cnt >= NEIGHBOUR_MIN]
        new[ok] = True
        rule[ok] = f"иная зона, ≥{NEIGHBOUR_MIN} жилых дома реестра в {int(NEIGHBOUR_RADIUS)} м"
    # 5. хозпостройки: маленькое здание рядом с более крупным жилым домом
    small = new & (~registry) & (fa < AUX_MAX)
    if small.any():
        big_idx = g.index[new]
        btree = shapely.STRtree(gm.geometry.loc[big_idx].values)
        sp = gm.geometry.loc[small]
        pr = btree.query(sp.values, predicate="dwithin", distance=AUX_RADIUS)
        for si, bi in zip(*pr):
            s_id, b_id = sp.index[si], big_idx[bi]
            if s_id != b_id and fa[b_id] >= 1.5 * fa[s_id]:
                new[s_id] = False
                rule[s_id] = "хозпостройка у жилого дома"

    # 6. ручные исправления по 2ГИС: data/raw/is_living_overrides.csv (id,is_living[,comment])
    ov_path = RAW / "is_living_overrides.csv"
    if ov_path.exists():
        ov = pd.read_csv(ov_path)
        m = g["id"].map(dict(zip(ov["id"], ov["is_living"].astype(int).astype(bool))))
        hit = m.notna()
        new[hit] = m[hit].astype(bool)
        rule[hit] = "ручная правка (2ГИС)"

    g["is_living"] = new.astype(bool)

    # --- площади ---
    bfa_geom = (fa * floors).round(2)
    living = g["is_living"]
    # нежилые: вся площадь нежилая
    g.loc[~living, "build_floor_area"] = bfa_geom[~living]
    g.loc[~living, "living_area"] = 0.0
    g.loc[~living, "non_living_area"] = bfa_geom[~living]
    # жилые без реестра: оценка
    est = living & ~registry
    g.loc[est, "build_floor_area"] = bfa_geom[est]
    g.loc[est, "living_area"] = (bfa_geom[est] * LIVING_COEF).round(2)
    g.loc[est, "non_living_area"] = (bfa_geom[est] - g.loc[est, "living_area"]).round(2)
    # жилые из реестра: общая площадь не меньше пятна застройки
    reg_l = living & registry
    small_bfa = reg_l & (g["build_floor_area"].fillna(0) < fa)
    g.loc[small_bfa, "build_floor_area"] = bfa_geom[small_bfa]
    g.loc[reg_l, "living_area"] = np.minimum(g.loc[reg_l, "living_area"], g.loc[reg_l, "build_floor_area"])
    g.loc[reg_l, "non_living_area"] = (g.loc[reg_l, "build_floor_area"] - g.loc[reg_l, "living_area"]).round(2)
    for c in ("build_floor_area", "living_area", "non_living_area", "footprint_area"):
        g[c] = g[c].astype(float).fillna(0.0).round(2)

    # --- восполнение населения: пропорционально жилой площади, сумма = население границы ---
    pop = np.zeros(len(g), dtype=np.int64)
    w = g["living_area"].where(living, 0.0).values
    idx = np.where(living.values)[0]
    target = TERRITORY_POPULATION
    base = np.ones(len(idx), dtype=np.int64)            # минимум 1 житель на жилой дом
    rest = target - base.sum()
    if rest < 0:
        raise ValueError("жилых домов больше, чем жителей — проверить is_living")
    share = w[idx] / w[idx].sum() * rest
    fl = np.floor(share).astype(np.int64)
    rem = rest - fl.sum()
    order = np.argsort(-(share - fl))[:rem]
    fl[order] += 1
    pop[idx] = base + fl
    g["population"] = pop.astype("int32")

    log = pd.DataFrame({"id": g["id"], "zone": g["zone"], "footprint_area": fa,
                        "registry": registry, "is_living_old": old, "is_living_new": g["is_living"],
                        "rule": rule})
    log["changed"] = log.is_living_old != log.is_living_new
    REP.mkdir(exist_ok=True)
    log.to_csv(REP / "is_living_changes.csv", index=False, encoding="utf-8-sig")

    cols = ["id", "build_floor_area", "living_area", "non_living_area", "footprint_area",
            "number_of_floors", "population", "is_living", "geometry"]
    out = g[cols].copy()
    write(out, OUT / "building.geojson")
    return out


# =============================================================================
def blocks(bnd: gpd.GeoDataFrame, min_area: float = 100.0, min_hole: float = 10.0) -> gpd.GeoDataFrame:
    b = fix_geom(read(RAW / "blocks.geojson")).to_crs(MCRS)
    b["geometry"] = b.geometry.apply(only_polygons)
    b = b[b.geometry.notna()].explode(index_parts=False)
    b = b[b.area >= min_area].copy()
    b["a"] = b.area
    b = b.sort_values("a", ascending=False).reset_index(drop=True)
    # убираем наложения: каждый квартал минус уже принятые (большие приоритетнее)
    kept: list = []
    tree_geoms: list = []
    for geom in b.geometry:
        if tree_geoms:
            t = shapely.STRtree(tree_geoms)
            hits = t.query(geom, predicate="intersects")
            if len(hits):
                geom = geom.difference(shapely.union_all([tree_geoms[i] for i in hits]))
        geom = only_polygons(shapely.make_valid(geom)) if geom is not None else None
        if geom is None or geom.is_empty:
            continue
        parts = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
        for p in parts:
            # убираем только микро-«дырки» (щели оцифровки < 10 м²) — в них не может лежать квартал
            holes = [h for h in p.interiors if shapely.Polygon(h).area >= min_hole]
            p = shapely.Polygon(p.exterior, holes)
            if p.area >= min_area:
                kept.append(p)
                tree_geoms.append(p)
    out = gpd.GeoDataFrame({"id": np.arange(1, len(kept) + 1, dtype="int32")}, geometry=kept, crs=MCRS)
    out = out.clip(bnd.to_crs(MCRS))
    out = out[out.geom_type.isin(["Polygon", "MultiPolygon"])].explode(index_parts=False)
    out = out[out.area >= min_area].to_crs(CRS)
    out["geometry"] = out.make_valid().apply(only_polygons)
    out = out[out.geometry.notna()].explode(index_parts=False)
    out = out[out.to_crs(MCRS).area >= min_area]
    out["id"] = np.arange(1, len(out) + 1, dtype="int32")
    write(out[["id", "geometry"]], OUT / "blocks.geojson")
    return out


# =============================================================================
def water_layers(bnd: gpd.GeoDataFrame) -> None:
    # river: единый тип геометрии — LineString (замечание «реки в разных типах геометрии»)
    r = fix_geom(read(RAW / "river.geojson"))
    r = r.clip(bnd)
    r = r[r.geom_type.isin(["LineString", "MultiLineString"])]
    r["geometry"] = r.geometry.apply(lambda x: shapely.line_merge(x) if x.geom_type == "MultiLineString" else x)
    r = r.explode(index_parts=False)
    r = r[r.geom_type == "LineString"]
    r = r[r.to_crs(MCRS).length > 1]
    r = gpd.GeoDataFrame({"id": np.arange(1, len(r) + 1, dtype="int32")}, geometry=r.geometry.values, crs=CRS)
    write(r, OUT / "river.geojson")

    for name in ("water", "bay", "lake"):
        x = fix_geom(read(RAW / f"{name}.geojson"))
        x["geometry"] = x.geometry.apply(only_polygons)
        x = x[x.geometry.notna()]
        x = gpd.GeoDataFrame({"id": np.arange(1, len(x) + 1, dtype="int32")}, geometry=x.geometry.values, crs=CRS)
        write(x, OUT / f"{name}.geojson")


def passthrough() -> None:
    for name in ("landuse", "roads", "railways", "forest"):
        x = lower_cols(fix_geom(read(RAW / f"{name}.geojson")))
        if name == "roads":
            x["highway_type_id"] = x["highway_type_id"].astype("int32")
        write(x, OUT / f"{name}.geojson")


# =============================================================================
NAME_COLS = ["name", "NAME", "name:ru"]
ADDR_COLS = ["ADDRESS", "ADRESS", "address"]


def to_point(geom):
    if geom is None or geom.is_empty:
        return None
    if isinstance(geom, MultiPoint):
        return geom.geoms[0] if len(geom.geoms) == 1 else geom.centroid
    return geom


def normalize_service(g: gpd.GeoDataFrame, svc: str) -> gpd.GeoDataFrame:
    g = fix_geom(g).reset_index(drop=True)
    out = gpd.GeoDataFrame(geometry=g.geometry.values, crs=CRS)
    sid = pd.to_numeric(g.get("service_id"), errors="coerce") if "service_id" in g else pd.Series([np.nan] * len(g))
    out["service_id"] = pd.array(sid.round(), dtype="Int32")
    sn = g["service_name"].astype(str).str.strip() if "service_name" in g else pd.Series([None] * len(g))
    out["service_name"] = sn.replace({"None": None, "nan": None})
    cap = pd.to_numeric(g.get("capacity"), errors="coerce") if "capacity" in g else pd.Series([np.nan] * len(g))
    if svc not in CAPACITY_SERVICES:
        # вместимость не требуется — пишем 0, чтобы поле оставалось INTEGER
        # (столбец из одних null в GeoJSON читается как String)
        cap = cap.fillna(0)
    out["capacity"] = pd.array(cap.round(), dtype="Int32")
    for c in NAME_COLS:
        if c in g and g[c].notna().any():
            out["name"] = g[c].astype("string")
            break
    for c in ADDR_COLS:
        if c in g and g[c].notna().any():
            out["address"] = g[c].astype("string")
            break
    if out.geom_type.isin(["Point", "MultiPoint"]).all():
        out["geometry"] = out.geometry.apply(to_point)
    return out


def snap_to_buildings(s: gpd.GeoDataFrame, bld: gpd.GeoDataFrame, svc: str, log: list) -> gpd.GeoDataFrame:
    if svc in NOT_IN_BUILDING or not s.geom_type.eq("Point").all() or s.empty:
        return s
    sm, bm = s.to_crs(MCRS), bld.to_crs(MCRS)
    tree = shapely.STRtree(bm.geometry.values)
    new_geoms = []
    for i, p in enumerate(sm.geometry):
        if len(tree.query(p, predicate="within")):
            new_geoms.append(p)
            continue
        k = tree.nearest(p)
        d = p.distance(bm.geometry.iloc[k])
        if d <= SNAP_DIST:
            q = bm.geometry.iloc[k].representative_point()
            log.append({"service": svc, "row": i, "action": "перенесена на здание", "distance_m": round(d, 1)})
            new_geoms.append(q)
        else:
            log.append({"service": svc, "row": i, "action": "НЕ на здании (далеко)", "distance_m": round(d, 1)})
            new_geoms.append(p)
    sm = sm.copy()
    sm["geometry"] = new_geoms
    return sm.to_crs(CRS)


def services(bld: gpd.GeoDataFrame, bnd: gpd.GeoDataFrame) -> None:
    log: list = []
    for f in sorted((RAW / "services_gpkg").glob("*.gpkg")):
        svc = f.stem.lower()
        g = read(f)
        s = normalize_service(g, svc)
        s = s[s.intersects(bnd.union_all())]
        s = snap_to_buildings(s, bld, svc, log)
        write(s, OUT / "services" / f"{svc}.geojson")
    pd.DataFrame(log, columns=LOG_COLS).to_csv(REP / "services_snap.csv", index=False, encoding="utf-8-sig")


def scenario(bld: gpd.GeoDataFrame) -> None:
    src, dst = RAW / "scenario_gpkg", OUT / "scenario"
    log: list = []
    # здания сценария
    sb = fix_geom(read(src / "building.gpkg"))
    sb = sb.rename(columns={"Is_living": "is_living"})
    sb["footprint_area"] = sb.to_crs(MCRS).area.round(2)
    sb["is_living"] = sb["is_living"].astype(bool)
    for c in ("number_of_floors", "population", "id"):
        sb[c] = sb[c].fillna(0).astype("int32")
    for c in ("build_floor_area", "living_area", "non_living_area"):
        sb[c] = sb[c].astype(float).fillna(0.0).round(2)
    sb = sb[["id", "build_floor_area", "living_area", "non_living_area", "footprint_area",
             "number_of_floors", "population", "is_living", "geometry"]]
    write(sb, dst / "building.geojson")
    all_bld = pd.concat([bld[["geometry"]], sb[["geometry"]]], ignore_index=True)
    all_bld = gpd.GeoDataFrame(all_bld, geometry="geometry", crs=CRS)

    for name in ("boundary", "landuse"):
        x = fix_geom(read(src / f"{name}.gpkg"))
        x = x.rename(columns=lambda c: c.strip().lower().replace(" ", "_") if c != "geometry" else c)
        write(x, dst / f"{name}.geojson")
    r = lower_cols(fix_geom(read(src / "roads.gpkg")))
    r["highway_type_id"] = r["highway_type_id"].astype("int32")
    write(r, dst / "roads.geojson")

    skip = {"building", "boundary", "landuse", "roads"}
    for f in sorted(src.glob("*.gpkg")):
        if f.stem in skip:
            continue
        svc = f.stem.lower()
        s = normalize_service(read(f), svc)
        s = snap_to_buildings(s, all_bld, svc, log)
        write(s, dst / f"{svc}.geojson")
    pd.DataFrame(log, columns=LOG_COLS).to_csv(REP / "scenario_snap.csv", index=False, encoding="utf-8-sig")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    bnd = boundary()
    bld = building(bnd)
    blocks(bnd)
    water_layers(bnd)
    passthrough()
    services(bld, bnd)
    scenario(bld)
    print("Готово:", OUT)


if __name__ == "__main__":
    main()
