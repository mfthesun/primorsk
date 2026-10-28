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

# Независимая проверка is_living по тегам building=* OpenStreetMap (data/raw/osm_building_tags.geojson) —
# замена ручной сверки по 2ГИС для зданий, где OSM даёт однозначный тип.
OSM_NON_LIVING = {"garage", "garages", "shed", "industrial", "greenhouse", "service", "storage_tank", "ruins",
                  "hangar", "warehouse", "kiosk", "school", "kindergarten", "church", "hospital", "roof",
                  "bunker", "pavilion", "collapsed", "construction"}
OSM_LIVING = {"house", "detached", "apartments", "residential", "semidetached_house", "terrace", "dormitory"}

# Сервисы, которые по смыслу должны стоять на здании (точка на полигоне building)
NOT_IN_BUILDING = {"bus_stop", "playground", "pitch", "cell_tower", "pier", "ice_rink"}
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
CENSUS = RAW / "population_census.csv"      # численность по населённым пунктам (ВПН-2020, Росстат)
PLACES = RAW / "osm_places.geojson"         # точки населённых пунктов OSM (place=*)


def distribute(w: pd.Series, total: int) -> np.ndarray:
    """total жителей по домам: минимум 1 на дом, остальное — пропорционально весу (наибольшие остатки)."""
    n = len(w)
    rest = total - n
    if rest < 0:
        raise ValueError("жилых домов больше, чем жителей — проверить is_living")
    share = w.values / w.values.sum() * rest if w.values.sum() > 0 else np.full(n, rest / max(n, 1))
    fl = np.floor(share).astype(np.int64)
    fl[np.argsort(-(share - fl))[:rest - fl.sum()]] += 1
    return 1 + fl


def locality_of(gm: gpd.GeoDataFrame) -> pd.Series:
    """Населённый пункт здания — ближайшая точка place из переписи (диаграмма Вороного по точкам OSM)."""
    names = set(pd.read_csv(CENSUS)["name"])
    pl = read(PLACES).to_crs(MCRS)
    pl = pl[pl["name"].isin(names)][["name", "geometry"]]
    pts = gpd.GeoDataFrame(geometry=gm.representative_point(), index=gm.index, crs=MCRS)
    j = gpd.sjoin_nearest(pts, pl, how="left")
    return j[~j.index.duplicated()]["name"]


def census_targets(loc: pd.Series, total: int) -> pd.Series:
    """Численность пунктов по переписи, приведённая к total; пункт не меньше числа своих жилых домов
    (лишние дома — дачи, учтённые жилыми; им по 1 жителю), излишек снимается с остальных пропорционально."""
    c = pd.read_csv(CENSUS).set_index("name")["population"].astype(float)
    houses = loc.value_counts().reindex(c.index, fill_value=0)
    c = c[houses > 0]
    houses = houses[c.index]
    fixed = pd.Series(False, index=c.index)
    for _ in range(len(c)):
        t = c.where(~fixed, 0) / c.where(~fixed, 0).sum() * (total - houses[fixed].sum())
        t[fixed] = houses[fixed]
        low = (~fixed) & (t < houses)
        if not low.any():
            break
        fixed |= low
    fl = np.floor(t).astype(int)
    fl.iloc[np.argsort(-(t - fl).values)[:total - fl.sum()]] += 1
    return fl


def building(bnd: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    g = fix_geom(read(RAW / "building.geojson"))
    # здания, которых нет в исходном слое, но есть в OSM (база отдыха в Прибылово) — нежилые
    extra = fix_geom(read(RAW / "osm_extra_buildings.geojson"))
    extra = extra[~extra.intersects(g.union_all())]
    extra = gpd.GeoDataFrame({"number_of_floors": 1, "is_living": False}, index=range(len(extra)),
                             geometry=[shapely.MultiPolygon([p]) if p.geom_type == "Polygon" else p
                                       for p in extra.geometry], crs=CRS)
    g = pd.concat([g, extra], ignore_index=True)
    g = gpd.GeoDataFrame(g, geometry="geometry", crs=CRS)
    g["is_living"] = g["is_living"].fillna(False)
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

    # 6. теги OSM: однозначно нежилой тип (гаражи, сараи, промышленные…) — нежилое, даже если сопоставлен
    #    с реестром (ошибка сопоставления по адресу); дом по OSM вне садоводства — жилой
    osm = fix_geom(read(RAW / "osm_building_tags.geojson"))[["building", "geometry"]].to_crs(MCRS)
    jo = gpd.sjoin(pts, osm, how="left", predicate="within")
    jo = jo[~jo.index.duplicated(keep="first")]
    g["osm_building"] = jo["building"].values
    osm_non = g["osm_building"].isin(OSM_NON_LIVING) & new
    new[osm_non] = False
    rule[osm_non] = "OSM: нежилой тип building=*"
    osm_liv = g["osm_building"].isin(OSM_LIVING) & ~new & (g["zone"] != GARDEN_ZONE) & (fa >= MIN_HOUSE)
    new[osm_liv] = True
    rule[osm_liv] = "OSM: жилой тип building=*"
    registry = registry & ~osm_non       # площади реестра у таких зданий не используем

    # 7. ручные исправления по 2ГИС: data/raw/is_living_overrides.csv (id,is_living[,comment])
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

    # --- восполнение населения: сумма = население границы; внутри населённого пункта — пропорционально
    #     жилой площади (минимум 1 житель на дом), между пунктами — по переписи (data/raw/population_census.csv) ---
    idx = np.where(living.values)[0]
    w = pd.Series(g["living_area"].values[idx], index=idx)
    pop = np.zeros(len(g), dtype=np.int64)
    if CENSUS.exists():
        loc = locality_of(gm.iloc[idx])
        g["locality"] = None
        g.loc[idx, "locality"] = loc.values
        targets = census_targets(loc, TERRITORY_POPULATION)
        for name, t in targets.items():
            sel = loc.index[loc.values == name]
            pop[sel] = distribute(w.loc[sel], int(t))
        pd.DataFrame({"census": pd.read_csv(CENSUS).set_index("name")["population"],
                      "houses": loc.value_counts(),
                      "proportional": pd.Series(distribute(w, TERRITORY_POPULATION), index=idx).groupby(loc).sum(),
                      "population": pd.Series(pop[idx], index=idx).groupby(loc).sum()}) \
            .fillna(0).astype(int).rename_axis("locality").sort_values("census", ascending=False) \
            .to_csv(REP / "population_by_locality.csv", encoding="utf-8-sig")
    else:
        pop[idx] = distribute(w, TERRITORY_POPULATION)
    g["population"] = pop.astype("int32")

    log = pd.DataFrame({"id": g["id"], "zone": g["zone"], "osm_building": g["osm_building"], "footprint_area": fa,
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


# Дополнение сервисов точками OSM (data/raw/osm_pois.geojson, kind = amenity/tourism):
# добавляются объекты, у которых в слое нет точки ближе OSM_DEDUP_DIST
OSM_SUPPLEMENT = {"post_office": "post_office"}
OSM_DEDUP_DIST = 300.0   # м


def osm_supplement(s: gpd.GeoDataFrame, svc: str, log: list) -> gpd.GeoDataFrame:
    if svc not in OSM_SUPPLEMENT:
        return s
    o = read(RAW / "osm_pois.geojson")
    o = o[o["kind"] == OSM_SUPPLEMENT[svc]]
    sm, om = s.to_crs(MCRS), o.to_crs(MCRS)
    far = [sm.distance(p).min() > OSM_DEDUP_DIST if len(sm) else True for p in om.geometry]
    add = o[far]
    if add.empty:
        return s
    new = gpd.GeoDataFrame({"service_id": pd.array([s["service_id"].dropna().iloc[0]] * len(add), dtype="Int32"),
                            "service_name": s["service_name"].iloc[0],
                            "capacity": pd.array([0] * len(add), dtype="Int32"),
                            "name": add["name"].astype("string").values},
                           geometry=add.geometry.values, crs=CRS)
    for i, n in enumerate(add["name"]):
        log.append({"service": svc, "row": len(s) + i, "action": f"добавлена из OSM ({n})", "distance_m": None})
    return pd.concat([s, new], ignore_index=True)


def services(bld: gpd.GeoDataFrame, bnd: gpd.GeoDataFrame) -> None:
    log: list = []
    for f in sorted((RAW / "services_gpkg").glob("*.gpkg")):
        svc = f.stem.lower()
        g = read(f)
        s = normalize_service(g, svc)
        s = osm_supplement(s, svc, log)
        s = s[s.intersects(bnd.union_all())]
        s = snap_to_buildings(s, bld, svc, log)
        write(s, OUT / "services" / f"{svc}.geojson")
    pd.DataFrame(log, columns=LOG_COLS).to_csv(REP / "services_snap.csv", index=False, encoding="utf-8-sig")


# ---- параметры сценария по концепции (docs/concept.md, docs/scenario.md) -------------------------
DORM_BUILDING_ID = 16        # корпус кампуса без сервисов: в нём общежитие (2 500 м², 70–80 мест)
DORM_AREA = 2500.0
DORM_POPULATION = 75
SCENARIO_CAPACITY = {"college": 300, "extra_education": 60}   # студентов/год: колледж 250–300, парусная школа 50–60
# service_id, которых нет в таблице курса или которые заняты другим сервисом (99 — «Пункт выдачи», outpost)
SCENARIO_NO_ID = {"marketplace"}
# новые сервисы марины: (слой, service_id, service_name, name, id здания сценария | None — точка у парусной школы)
MARINA_SERVICES = [
    ("hotel", 110, "Гостиница", "Гостинично-досуговый комплекс (ф. 2 марины)", 7),
    ("yacht_club", None, "Яхт-клуб", "Клубный дом марины", 6),
    ("rental", None, "Прокат", "Прокат буеров, снегоходов, сапов", None),
    ("ice_rink", None, "Каток", "Сезонный каток", None),
]
DESIGN = RAW / "scenario_design"     # трассировка транспортных слоёв и причалов (scripts/scenario_design.py)


def scenario_design(dst: Path, sb: gpd.GeoDataFrame) -> None:
    """Слои транспортного проекта и причалы — из data/raw/scenario_design."""
    for name in ("shuttle_route", "cycleway", "footway"):
        x = read(DESIGN / f"{name}.geojson")
        x["highway_type_id"] = x["highway_type_id"].astype("int32")
        x["length_m"] = x["length_m"].round().astype("int32")
        write(x, dst / f"{name}.geojson")
    pk = read(DESIGN / "parking.geojson")
    pk = gpd.GeoDataFrame({"service_id": pd.array([None], dtype="Int32"), "service_name": "Парковка",
                           "capacity": pd.array([0], dtype="Int32"), "name": pk["name"].values,
                           "places": pk["places"].astype("int32").values}, geometry=pk.geometry.values, crs=CRS)
    write(pk, dst / "parking.geojson")
    pr = read(DESIGN / "pier.geojson")
    pr = gpd.GeoDataFrame({"service_id": pd.array([None] * len(pr), dtype="Int32"), "service_name": "Причал",
                           "capacity": pd.array([0] * len(pr), dtype="Int32"), "name": pr["name"].values,
                           "berths": pr["berths"].astype("int32").values}, geometry=pr.geometry.values, crs=CRS)
    write(pr, dst / "pier.geojson")


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
    # в исходнике два здания с id = 23 — второму даём следующий свободный номер
    dup = sb["id"].duplicated()
    sb.loc[dup, "id"] = np.arange(sb["id"].max() + 1, sb["id"].max() + 1 + dup.sum(), dtype="int32")
    # общежитие кампуса: часть корпуса DORM_BUILDING_ID
    d = sb["id"] == DORM_BUILDING_ID
    sb.loc[d, "is_living"] = True
    sb.loc[d, "living_area"] = round(DORM_AREA * LIVING_COEF, 2)
    sb.loc[d, "non_living_area"] = (sb.loc[d, "build_floor_area"] - sb.loc[d, "living_area"]).round(2)
    sb.loc[d, "population"] = DORM_POPULATION
    sb = sb[["id", "build_floor_area", "living_area", "non_living_area", "footprint_area",
             "number_of_floors", "population", "is_living", "geometry"]]
    write(sb, dst / "building.geojson")
    all_bld = pd.concat([bld[["geometry"]], sb[["geometry"]]], ignore_index=True)
    all_bld = gpd.GeoDataFrame(all_bld, geometry="geometry", crs=CRS)

    for name in ("boundary", "landuse"):
        x = fix_geom(read(src / f"{name}.gpkg"))
        x = x.rename(columns=lambda c: c.strip().lower().replace(" ", "_") if c != "geometry" else c)
        if name == "boundary":
            # предполагаемое население территории = жители зданий сценария внутри неё
            xm = x.to_crs(MCRS)
            sbp = sb.to_crs(MCRS).representative_point()
            x["population"] = pd.array([int(sb.loc[sbp.within(t.buffer(1)), "population"].sum())
                                        for t in xm.geometry], dtype="int32")
            x["name"] = ["Кампус ИНТЦ «Приморская долина»", "Марина, рыбный рынок, клубный дом",
                         "Парусная школа, прокат"]
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
        if svc in SCENARIO_CAPACITY:
            n = len(s)
            cap = SCENARIO_CAPACITY[svc]
            s["capacity"] = pd.array([cap // n + (1 if i < cap % n else 0) for i in range(n)], dtype="Int32")
        if svc in SCENARIO_NO_ID:
            s["service_id"] = pd.array([None] * len(s), dtype="Int32")
        if svc == "bus_stop":
            st = read(DESIGN / "shuttle_stop.geojson")
            st = st[st.to_crs(MCRS).geometry.apply(lambda p: s.to_crs(MCRS).distance(p).min() > 30)]
            s = pd.concat([s, gpd.GeoDataFrame({"service_id": pd.array([None] * len(st), dtype="Int32"),
                                                "service_name": s["service_name"].iloc[0],
                                                "capacity": pd.array([0] * len(st), dtype="Int32"),
                                                "name": st["name"].values}, geometry=st.geometry.values, crs=CRS)],
                          ignore_index=True)
        s = snap_to_buildings(s, all_bld, svc, log)
        write(s, dst / f"{svc}.geojson")
        if svc == "extra_education":
            sail = s.geometry.iloc[0]

    # новые сервисы марины
    sbm = sb.set_index("id")
    for svc, sid, sname, name, bid in MARINA_SERVICES:
        if bid is not None:
            geom = sbm.loc[[bid]].to_crs(MCRS).representative_point().to_crs(CRS).iloc[0]
        else:
            # рядом с парусной школой: прокат — в том же здании, каток — на берегу в 40 м
            geom = sail if svc != "ice_rink" else \
                gpd.GeoSeries([sail], crs=CRS).to_crs(MCRS).translate(0, -40).to_crs(CRS).iloc[0]
        x = gpd.GeoDataFrame({"service_id": pd.array([sid], dtype="Int32"), "service_name": [sname],
                              "capacity": pd.array([0], dtype="Int32"), "name": [name]}, geometry=[geom], crs=CRS)
        write(x, dst / f"{svc}.geojson")
    scenario_design(dst, sb)
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
