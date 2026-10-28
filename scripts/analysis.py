"""
Предпроектный анализ «было» и расчёт «стало» по сценариям (разделы 1 и 4 мастер-плана) на BlocksNet 1.0.0a9.

Для каждого сценария (scripts/scenarios.py: today — сегодня, s1 — первая очередь, s2 — полная реализация):
1. Агрегация зданий (с объектами сценария нужной очереди) по кварталам: население, площади, FSI/GSI/MXI,
   Spacematrix; функциональное зонирование кварталов (assign_objects по ФЗ генплана).
2. Граф (scripts/roadgraph.py) и матрицы доступности: пешком, на автомобиле и «пешком + шаттл» (в s1/s2 —
   с велодорожкой, пешеходными маршрутами и шаттлом), median_accessibility, время до станции и центра.
3. Конкурентная обеспеченность (competitive_provision) школами и детскими садами — таблица
   «норматив / обеспечено / дефицит / избыток»; показатели территории BlocksNet (calculate_social_indicators,
   transport / general / demographic) — обеспеченность всеми сервисами с нормативами BlocksNet.
4. Охват населения прочими сервисами по времени.

Окружение — .venv-blocksnet (scripts/setup.sh). Интернет не нужен.
Запуск: .venv-blocksnet/bin/python scripts/analysis.py [today|s1|s2]   (без аргумента — все три)

Выход: data/processed/analysis/{blocks_<tag>.geojson, acc_<mode>_<tag>.pkl, graph_*.geojson},
       reports/analysis_<tag>.md, reports/provision_<tag>.csv, reports/coverage_<tag>.csv,
       reports/provision_by_locality_<tag>.csv, reports/metrics/blocksnet_<tag>.json
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from roadgraph import (MCRS, TRANSIT, build_graph, edges_gdf, graph_summary, load_network,  # noqa: E402
                       scenario_graphs, scenario_layer)
from scenarios import SCENARIOS  # noqa: E402

from loguru import logger  # noqa: E402

logger.remove()
logger.add(sys.stderr, level="WARNING")

from blocksnet.analysis.indicators.density import calculate_density_indicators  # noqa: E402
from blocksnet.analysis.morphotypes import get_spacematrix_morphotypes  # noqa: E402
from blocksnet.analysis.network.accessibility import median_accessibility  # noqa: E402
from blocksnet.analysis.provision import competitive_provision  # noqa: E402
from blocksnet.blocks.aggregation import aggregate_objects  # noqa: E402
from blocksnet.blocks.assignment import assign_objects  # noqa: E402
from blocksnet.analysis.indicators.socio_economic import (calculate_demographic_indicators,  # noqa: E402
                                                          calculate_general_indicators, calculate_social_indicators,
                                                          calculate_transport_indicators)
import json  # noqa: E402
from blocksnet.config import service_types_config  # noqa: E402
from blocksnet.relations import calculate_accessibility_matrix, validate_accessibility_graph  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
OUT = PROC / "analysis"
REP = ROOT / "reports"

# Нормативы BlocksNet (service_types_config): мест на 1000 жителей и нормативная доступность, мин.
# Для сельского поселения дополнительно — транспортная доступность (подвоз, СП 42.13330.2016 п. 10.4:
# школы — до 30 мин в одну сторону; детские сады — принимаем 15 мин).
PROVISION = {
    "school":       {"walk": 15, "drive": 30},
    "kindergarten": {"walk": 7,  "drive": 15},
    "college":      {"drive": 60},          # норматив BlocksNet: 8 мест/1000, 60 мин (колледж — только в сценариях)
}
# Сервисы слоя → тип сервиса BlocksNet (service_types_config) для показателей территории.
# Реальная вместимость есть у школ, детсадов, колледжа; у прочих — типовая вместимость наименьшего объекта
# BlocksNet (units[].capacity) — оценка, отмечается в отчёте.
BN_TYPES = {"school": "school", "kindergarten": "kindergarten", "college": "college", "polyclinic": "polyclinic",
            "hospital": "hospital", "pharmacy": "pharmacy", "post_office": "post", "mfz": "multifunctional_center",
            "library": "library", "bank": "bank", "cafe": "cafe", "restaurant": "restaurant",
            "convenience": "convenience", "supermarket": "supermarket", "hotel": "hotel", "museum": "museum",
            "police": "police", "fuel": "fuel", "religion": "religion", "pitch": "pitch", "playground": "playground",
            "park": "park", "train_station": "train_station", "bus_stop": "bus_stop", "hairdresser": "hairdresser",
            "marketplace": "market", "pier": "pier", "cemetery": "cemetery"}
REAL_CAPACITY = {"school", "kindergarten", "college"}
# ФЗ генплана → LandUse BlocksNet
LAND_USE = {
    "Зона застройки индивидуальными жилыми домами": "residential",
    "Зона застройки малоэтажными жилыми домами (до 4 этажей, включая мансардный)": "residential",
    "Зона застройки среднеэтажными жилыми домами (от 5 до 8 этажей, включая мансардный)": "residential",
    "Зона застройки многоэтажными жилыми домами (9 этажей и более)": "residential",
    "Зона смешанной и общественно-деловой застройки": "business",
    "Многофункциональная общественно-деловая зона": "business",
    "Зона специализированной общественной застройки": "business",
    "Производственная зона": "industrial", "Коммунально-складская зона": "industrial",
    "Зона транспортной инфраструктуры": "transport",
    "Зона инженерной инфраструктуры": "special", "Зона кладбищ": "special", "Зона режимных территорий": "special",
    "Зона озелененных территорий специального назначения": "special",
    "Зона сельскохозяйственных угодий": "agriculture", "Зоны сельскохозяйственного использования": "agriculture",
    "Производственная зона сельскохозяйственных предприятий": "agriculture",
    "Иные зоны сельскохозяйственного назначения": "agriculture", "Зона садоводства, огородничества": "agriculture",
    "Зона лесов": "recreation", "Зона отдыха": "recreation", "Иные рекреационные зоны": "recreation",
    "Зона озелененных территорий общего пользования (парки, сады, скверы, бульвары, городские леса)": "recreation",
}
# Охват прочими сервисами: (сервис, порог пешком, мин; порог на автомобиле, мин)
COVERAGE = [("polyclinic", 15, 30), ("hospital", 30, 60), ("pharmacy", 15, 30), ("post_office", 15, 30),
            ("mfz", 15, 30), ("library", 15, 30), ("community_centre", 15, 30), ("extra_education", 15, 30),
            ("convenience", 10, 15), ("supermarket", 15, 30), ("bus_stop", 10, None),
            ("train_station", 20, 30)]
NAMES = {"school": "Школы", "kindergarten": "Детские сады", "polyclinic": "Поликлиника / ФАП",
         "hospital": "Больница", "pharmacy": "Аптеки", "post_office": "Почта", "mfz": "МФЦ",
         "library": "Библиотеки", "community_centre": "Дома культуры", "extra_education": "Доп. образование",
         "convenience": "Продукты у дома", "supermarket": "Супермаркеты", "bus_stop": "Остановки ОТ",
         "train_station": "Ж/д станции", "college": "Колледж"}
TYPICAL_CAPACITY: dict[str, int] = {}   # запасные вместимости, если у типа BlocksNet нет units
STATION = (589964, 6693001)      # ж/д станция Приморск
MARINA = (588694, 6693041)       # территория марины
CAMPUS = (593014, 6691007)       # кампус ИНТЦ
PORT = (594950, 6690540)         # въезд в порт (главный работодатель)
TOWN = "Приморск"
CENTRE = (588638, 6693428)       # центр Приморска (рынок)


def read(path: Path) -> gpd.GeoDataFrame:
    return gpd.read_file(path).to_crs(MCRS)


def norm(svc: str) -> tuple[int, int]:
    st = service_types_config[svc]
    return int(st["demand"]), int(st["accessibility"])


def split_int(total: int, weights: pd.Series) -> pd.Series:
    """Целочисленное распределение total пропорционально весам (метод наибольших остатков)."""
    if total <= 0 or weights.sum() <= 0:
        return pd.Series(0, index=weights.index, dtype=int)
    share = weights / weights.sum() * total
    fl = np.floor(share).astype(int)
    rem = int(total - fl.sum())
    fl.iloc[np.argsort(-(share - fl).values)[:rem]] += 1
    return fl


# =============================================================================
def load_blocks(phase: int) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    blocks = read(PROC / "blocks.geojson")[["geometry"]].reset_index(drop=True)
    blocks["site_area"] = blocks.area
    bld = read(PROC / "building.geojson")
    sb = scenario_layer("building", phase)
    if sb is not None:
        bld = pd.concat([bld, sb], ignore_index=True)
    bld = gpd.GeoDataFrame(bld, geometry="geometry", crs=MCRS)
    bld["is_living"] = bld["is_living"].astype(bool)
    return blocks, bld


def aggregate(blocks: gpd.GeoDataFrame, bld: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, dict]:
    cols = ["population", "build_floor_area", "living_area", "non_living_area", "footprint_area"]
    obj = bld[cols + ["geometry"]].copy()
    obj["count_living"] = bld["is_living"].astype(int)
    agg, excess = aggregate_objects(blocks, obj)
    info = {"buildings": len(bld), "outside_blocks": len(excess), "pop_outside": int(excess["population"].sum())}
    # здания вне кварталов (дороги, вода, ошибки нарезки) — к ближайшему кварталу, чтобы не потерять население
    if len(excess):
        ex = excess.copy()
        ex["geometry"] = ex.representative_point()
        j = gpd.sjoin_nearest(ex, blocks[["geometry"]], how="left")
        j = j[~j.index.duplicated()]
        add = j.groupby("index_right")[cols + ["count_living"] + (["count"] if "count" in j else [])].sum()
        for c in add.columns:
            agg.loc[add.index, c] = agg.loc[add.index, c] + add[c]
    agg = agg.rename(columns={"count": "count_buildings"})
    agg["site_area"] = agg.area
    for c in ("population", "count_buildings", "count_living"):
        agg[c] = agg[c].round().astype(int)
    return agg, info


def density(blocks: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    d = calculate_density_indicators(blocks[["site_area", "footprint_area", "build_floor_area", "living_area",
                                             "non_living_area"]].copy())
    for c in ("fsi", "gsi", "mxi", "l", "osr"):
        blocks[c] = d[c].replace([np.inf, -np.inf], np.nan).fillna(0).astype(float)
    blocks["pop_density"] = blocks["population"] / (blocks["site_area"] / 1e4)       # чел./га
    sm, clusters = get_spacematrix_morphotypes(blocks[["l", "fsi", "mxi"]].copy(), n_clusters=8)
    blocks["morphotype"] = sm["morphotype"].fillna("незастроенный")
    return blocks, clusters


def land_use(blocks: gpd.GeoDataFrame, phase: int) -> gpd.GeoDataFrame:
    """land_use квартала — преобладающая ФЗ генплана (существующие зоны, status = 1; в сценариях поверх —
    ФЗ проектных территорий)."""
    lu = read(PROC / "landuse.geojson")
    lu = lu[lu["status"] == 1]
    lu = gpd.GeoDataFrame({"name": lu["name"].map(LAND_USE)}, geometry=lu.geometry, crs=MCRS)
    if phase:
        terr = read(PROC / "scenario" / "boundary.geojson")
        zone = {"Специализированная общественная зона": "business",
                "Многофункциональная общественно-деловая зона": "business"}
        t = gpd.GeoDataFrame({"name": terr["functional_zone"].map(zone)}, geometry=terr.geometry, crs=MCRS)
        lu = pd.concat([gpd.overlay(lu, t[["geometry"]], how="difference"), t], ignore_index=True)
    lu = lu[lu["name"].notna()].explode(index_parts=False)
    lu = lu[lu.geom_type == "Polygon"].reset_index(drop=True)
    a = assign_objects(blocks[["geometry"]].copy(), gpd.GeoDataFrame(lu, geometry="geometry", crs=MCRS))
    blocks["land_use"] = a["name"]
    blocks["share"] = a["share"].fillna(0.0)
    for v in sorted(set(LAND_USE.values())):
        blocks[v] = a[v] if v in a else 0.0
    return blocks


# =============================================================================
def graphs(phase: int) -> tuple[dict, dict]:
    """walk, drive и transit (пешком + шаттл) — roadgraph.scenario_graphs; для IduEdu — ориентированные."""
    out, info = scenario_graphs(phase)
    for mode, G in out.items():
        validate_accessibility_graph(G, "time_min")
        if phase == 0 and mode != "transit":
            edges_gdf(G).to_crs(4326).to_file(OUT / f"graph_{mode}.geojson", driver="GeoJSON", engine="pyogrio")
    info["roads_only"] = graph_summary(build_graph(load_network(include_osm=False), "drive"))
    return {k: v.to_directed() for k, v in out.items()}, info          # IduEdu ждёт ориентированный граф


def anchors(blocks: gpd.GeoDataFrame, bld: gpd.GeoDataFrame) -> gpd.GeoSeries:
    """Точка квартала для матрицы: центр застройки (взвешенный по общей площади зданий; ближайшее к нему
    здание, чтобы точка не попала в воду/лес). Кварталы курса крупные (до сотен га с лесом), и
    representative_point() может лежать в километре от домов. Без зданий — representative_point()."""
    # в квартале с жителями — центр по населению (новые нежилые здания сценария не сдвигают точку)
    pts = gpd.GeoDataFrame({"w": bld["build_floor_area"].clip(lower=1), "p": bld["population"]},
                           geometry=bld.representative_point(), crs=MCRS)
    j = gpd.sjoin(pts, blocks[["geometry"]], predicate="within")
    out = blocks.representative_point()
    for k, grp in j.groupby("index_right"):
        if grp["p"].sum() > 0:
            grp = grp[grp["p"] > 0]
            wts = grp["p"]
        else:
            wts = grp["w"]
        cx = np.average(grp.geometry.x, weights=wts)
        cy = np.average(grp.geometry.y, weights=wts)
        d = (grp.geometry.x - cx) ** 2 + (grp.geometry.y - cy) ** 2
        out.loc[k] = grp.geometry.loc[d.idxmin()]
    return out


def matrix(G, blocks: gpd.GeoDataFrame) -> pd.DataFrame:
    pts = gpd.GeoDataFrame(geometry=blocks["anchor"], index=blocks.index, crs=MCRS)
    return calculate_accessibility_matrix(pts, G, "time_min", dtype=np.float32)


def point_times(G, blocks: gpd.GeoDataFrame, xy) -> pd.Series:
    """Время от центра квартала до точки xy по графу: Дейкстра от узла точки + подход пешком к узлам."""
    import networkx as nx
    from roadgraph import WALK_SPEED
    ids = np.array(list(G.nodes))
    xyn = np.array([(G.nodes[n]["x"], G.nodes[n]["y"]) for n in ids])
    tree = __import__("scipy.spatial", fromlist=["cKDTree"]).cKDTree(xyn)
    d0, i0 = tree.query([xy])
    dist = nx.single_source_dijkstra_path_length(G.reverse(copy=False) if G.is_directed() else G,
                                                 ids[i0[0]], weight="time_min")
    pts = np.array([(p.x, p.y) for p in blocks["anchor"]])
    d1, i1 = tree.query(pts)
    v = WALK_SPEED * 1000 / 60
    t = [dist.get(ids[i], np.nan) + d / v + d0[0] / v for d, i in zip(d1, i1)]
    return pd.Series(t, index=blocks.index)


def block_of(blocks: gpd.GeoDataFrame, xy) -> int:
    p = gpd.GeoDataFrame(geometry=gpd.points_from_xy([xy[0]], [xy[1]]), crs=MCRS)
    return int(gpd.sjoin_nearest(p, blocks[["geometry"]])["index_right"].iloc[0])


# =============================================================================
def services_to_blocks(svc: str, blocks: gpd.GeoDataFrame, phase: int) -> gpd.GeoDataFrame:
    p = PROC / "services" / f"{svc}.geojson"
    s = read(p) if p.exists() else gpd.GeoDataFrame({"capacity": []}, geometry=[], crs=MCRS)
    sc = scenario_layer(svc, phase)
    if sc is not None:
        s = pd.concat([s, sc], ignore_index=True)
    s = gpd.GeoDataFrame(s, geometry=s.representative_point(), crs=MCRS)
    j = gpd.sjoin_nearest(s, blocks[["geometry"]], how="left")
    return j[~j.index.duplicated()]


def provision(blocks: gpd.GeoDataFrame, acc: dict, phase: int) -> tuple[pd.DataFrame, dict]:
    rows, res = [], {}
    pop_total = int(blocks["population"].sum())
    for svc, acc_min in PROVISION.items():
        demand_k, acc_default = norm(svc)
        s = services_to_blocks(svc, blocks, phase)
        cap = s.groupby("index_right")["capacity"].sum().reindex(blocks.index, fill_value=0).astype(int) \
            if len(s) else pd.Series(0, index=blocks.index)
        need = round(pop_total * demand_k / 1000)
        df = pd.DataFrame({"population": blocks["population"],
                           "demand": split_int(need, blocks["population"]).astype(int),
                           "capacity": cap})
        for mode, a in acc_min.items():
            r, links = competitive_provision(df.copy(), acc[mode], accessibility=a, max_depth=3)
            res[(svc, mode)] = r
            within, without = int(r["demand_within"].sum()), int(r["demand_without"].sum())
            rows.append({
                "service": svc, "Сервис": NAMES[svc], "Доступность": f"{'пешком' if mode == 'walk' else 'транспорт'} "
                                                                    f"{a} мин",
                "Норматив, мест/1000": demand_k, "Норматив, мест": need, "Вместимость (факт)": int(cap.sum()),
                "Обеспечено в нормативе": within, "Обеспечено за пределами": without,
                "Дефицит": int(need - within), "Не обеспечено": int(r["demand_left"].sum()),
                "Избыток (свободные места)": int(r["capacity_left"].sum()),
                "provision_strong": round(within / need, 3) if need else None,
                "provision_weak": round((within + without) / need, 3) if need else None,
                "Объектов": len(s)})
    return pd.DataFrame(rows), res


def coverage(blocks: gpd.GeoDataFrame, acc: dict, phase: int) -> pd.DataFrame:
    """Время от квартала до ближайшего сервиса — по матрице «квартал → квартал» (сервис — в своём квартале)."""
    rows = []
    pop = blocks["population"]
    for svc, walk_t, drive_t in COVERAGE:
        if not (PROC / "services" / f"{svc}.geojson").exists():
            continue
        s = services_to_blocks(svc, blocks, phase)
        targets = sorted(s["index_right"].unique())
        r = {"service": svc, "Сервис": NAMES[svc], "Объектов": len(s)}
        for mode, t in (("walk", walk_t), ("transit", walk_t), ("drive", drive_t)):
            m = acc[mode][targets].min(axis=1)
            blocks[f"t_{mode}_{svc}"] = m.replace(np.inf, np.nan).round(1)
            if t is None:
                r[f"{mode}_min"], r[f"{mode}_share"] = None, None
                continue
            r[f"{mode}_min"] = t
            r[f"{mode}_share"] = round(float(pop[m <= t].sum() / pop.sum()), 3)
        rows.append(r)
    return pd.DataFrame(rows)


def territory_indicators(blocks: gpd.GeoDataFrame, acc: dict, G: dict, phase: int) -> dict:
    """Показатели территории BlocksNet (socio_economic) по поселению и населённым пунктам (parent)."""
    df = blocks[["geometry", "population", "site_area", "land_use"]].copy()
    df["population"] = df["population"].astype(int)
    df["parent"] = blocks["locality"]
    est = []
    for svc, bn in BN_TYPES.items():
        s = services_to_blocks(svc, blocks, phase)
        cnt = s.groupby("index_right").size() if len(s) else pd.Series(dtype=int)
        df[f"count_{bn}"] = cnt.reindex(df.index, fill_value=0).astype(int) + \
            (df[f"count_{bn}"] if f"count_{bn}" in df else 0)
        if svc in REAL_CAPACITY:
            cap = s.groupby("index_right")["capacity"].sum() if len(s) else pd.Series(dtype=int)
        else:
            units = service_types_config.units
            caps = units.loc[units["service_type"] == bn, "capacity"]
            unit = int(caps.min()) if len(caps) else TYPICAL_CAPACITY.get(bn, 0)
            cap = cnt * unit
            est.append(bn)
        df[f"capacity_{bn}"] = cap.reindex(df.index, fill_value=0).astype(int) + \
            (df[f"capacity_{bn}"] if f"capacity_{bn}" in df else 0)
    for bn in service_types_config.service_types.index:
        for pre in ("count_", "capacity_"):
            if f"{pre}{bn}" not in df:
                df[f"{pre}{bn}"] = 0
    from blocksnet.config import log_config
    log_config.set_disable_tqdm(True)
    counts, prov = calculate_social_indicators(df, acc["drive"], None)
    luv = df["land_use"].map(lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else v)
    from blocksnet.enums import LandUse
    df_lu = df.assign(land_use=luv.map(lambda v: LandUse(v) if v else None))
    gen = calculate_general_indicators(df_lu)
    dem = calculate_demographic_indicators(df)
    try:
        net = edges_gdf(G["drive"].to_undirected())[["geometry"]]
        tr = calculate_transport_indicators(df_lu, acc["drive"], net)
    except Exception as e:          # noqa: BLE001 — показатели транспорта опциональны
        logger.warning(f"transport indicators: {e}")
        tr = pd.DataFrame()
    return {"counts": counts, "provision": prov, "general": gen, "demographic": dem, "transport": tr,
            "estimated_capacity": est}


def localities(blocks: gpd.GeoDataFrame, bld: gpd.GeoDataFrame) -> pd.Series:
    """Населённый пункт квартала: у зданий — ближайшая точка place из переписи (как в process.py → building),
    у квартала — пункт, где живёт большинство его жителей (без жителей — ближайший к кварталу)."""
    names = set(pd.read_csv(ROOT / "data" / "raw" / "population_census.csv")["name"])
    pl = read(ROOT / "data" / "raw" / "osm_places.geojson")
    pl = pl[pl["name"].isin(names)][["name", "geometry"]]

    def nearest(g):
        pts = gpd.GeoDataFrame(geometry=g.representative_point(), index=g.index, crs=MCRS)
        j = gpd.sjoin_nearest(pts, pl, how="left")
        return j[~j.index.duplicated()]["name"]

    b = bld[bld["population"] > 0]
    b = gpd.GeoDataFrame({"population": b["population"], "loc": nearest(b)},
                         geometry=b.representative_point(), crs=MCRS)
    j = gpd.sjoin(b, blocks[["geometry"]], predicate="within")
    major = j.groupby(["index_right", "loc"])["population"].sum().reset_index() \
        .sort_values("population").drop_duplicates("index_right", keep="last").set_index("index_right")["loc"]
    return major.reindex(blocks.index).fillna(nearest(blocks))


# =============================================================================
def md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        out.append("| " + " | ".join("" if pd.isna(v) else (f"{v:.0%}" if isinstance(v, float) and 0 <= v <= 1
                                                             and c.startswith(("provision", "Доля")) else
                                                             (f"{v:,.0f}".replace(",", " ") if isinstance(v, (int, float, np.integer, np.floating)) and abs(v) >= 1000 else str(v)))
                                     for c, v in zip(cols, r.values)) + " |")
    return "\n".join(out)


def run(tag: str) -> dict:
    phase = SCENARIOS[tag]["phase"]
    OUT.mkdir(parents=True, exist_ok=True)
    (REP / "metrics").mkdir(parents=True, exist_ok=True)

    blocks, bld = load_blocks(phase)
    blocks, agg_info = aggregate(blocks, bld)
    blocks, clusters = density(blocks)
    blocks["locality"] = localities(blocks, bld)
    blocks["anchor"] = anchors(blocks, bld)
    blocks = land_use(blocks, phase)

    G, ginfo = graphs(phase)
    acc = {mode: matrix(G[mode], blocks) for mode in G}
    for mode, m in acc.items():
        m.to_pickle(OUT / f"acc_{mode}_{tag}.pkl")
        blocks[f"median_acc_{mode}"] = median_accessibility(m)["median_accessibility"].round(1)
        for name, xy in (("station", STATION), ("centre", CENTRE), ("marina", MARINA), ("campus", CAMPUS),
                         ("port", PORT)):
            blocks[f"t_{mode}_{name}"] = point_times(G[mode], blocks, xy).round(1)

    prov, res = provision(blocks, acc, phase)
    for (svc, mode), r in res.items():
        for c in ("demand", "capacity", "demand_within", "demand_without", "demand_left", "capacity_left",
                  "provision_strong", "provision_weak"):
            blocks[f"{svc}_{mode}_{c}"] = r[c]
    cov = coverage(blocks, acc, phase)
    ind = territory_indicators(blocks, acc, G, phase)

    # по населённым пунктам: школы и детсады + время до станции
    loc = blocks.groupby("locality").agg(population=("population", "sum"))
    for svc in ("school", "kindergarten"):
        for mode in ("walk", "drive"):
            g = blocks.groupby("locality")[[f"{svc}_{mode}_demand", f"{svc}_{mode}_demand_within"]].sum()
            loc[f"{svc}_{mode}"] = (g.iloc[:, 1] / g.iloc[:, 0].replace(0, np.nan)).round(2)
    w = blocks["population"]
    loc["t_drive_station"] = (blocks["t_drive_station"] * w).groupby(blocks["locality"]).sum() / \
        w.groupby(blocks["locality"]).sum().replace(0, np.nan)
    loc = loc[loc["population"] > 0].sort_values("population", ascending=False).round(1)

    # --- сохранение ---
    out = blocks.drop(columns="anchor")
    out.insert(0, "id", np.arange(1, len(out) + 1, dtype="int32"))
    p = OUT / f"blocks_{tag}.geojson"
    if p.exists():
        p.unlink()
    out.to_crs(4326).to_file(p, driver="GeoJSON", engine="pyogrio")
    prov.to_csv(REP / f"provision_{tag}.csv", index=False, encoding="utf-8-sig")
    cov.to_csv(REP / f"coverage_{tag}.csv", index=False, encoding="utf-8-sig")
    loc.to_csv(REP / f"provision_by_locality_{tag}.csv", encoding="utf-8-sig")
    tot = lambda d: {getattr(k, "name", str(k)).lower(): (None if pd.isna(v) else float(v))  # noqa: E731
                     for k, v in d["total"].items()} if "total" in d else {}
    ind_out = {k: tot(ind[k]) for k in ("counts", "provision", "general", "demographic", "transport")
               if isinstance(ind[k], pd.DataFrame) and len(ind[k])}
    pd.concat({k: ind[k] for k in ("provision", "counts") if len(ind[k])}).to_csv(
        REP / f"territory_indicators_{tag}.csv", encoding="utf-8-sig")

    pop = int(blocks["population"].sum())
    wpop = lambda c: float((blocks[c] * blocks.population).sum() / pop)  # noqa: E731
    share = lambda c, t: float(blocks.loc[blocks[c] <= t, "population"].sum() / pop)  # noqa: E731
    metrics = {
        "tag": tag, "name": SCENARIOS[tag]["name"],
        "population": pop, "buildings": agg_info["buildings"],
        "build_floor_area_m2": float(blocks.build_floor_area.sum()),
        "living_area_m2": float(blocks.living_area.sum()),
        "living_area_per_capita": float(blocks.living_area.sum() / pop),
        "median_acc_drive": wpop("median_acc_drive"), "median_acc_walk": wpop("median_acc_walk"),
        "median_acc_transit": wpop("median_acc_transit"),
        "t_drive_station": wpop("t_drive_station"), "t_transit_station": wpop("t_transit_station"),
        "share_walk_station_20": share("t_walk_station", 20), "share_transit_station_20": share("t_transit_station", 20),
        "share_transit_station_30": share("t_transit_station", 30),
        "share_transit_marina_30": share("t_transit_marina", 30), "share_transit_campus_30": share("t_transit_campus", 30),
        "share_transit_centre_30": share("t_transit_centre", 30),
        "share_transit_port_30": share("t_transit_port", 30),
        # жители г. Приморска (шаттл работает в городе)
        "town_population": int(blocks.loc[blocks.locality == TOWN, "population"].sum()),
        **{f"town_share_{mode}_{dst}_{t}": float(
            blocks.loc[(blocks.locality == TOWN) & (blocks[f"t_{mode}_{dst}"] <= t), "population"].sum()
            / max(blocks.loc[blocks.locality == TOWN, "population"].sum(), 1))
           for mode in ("walk", "transit") for dst in ("station", "campus", "port", "marina") for t in (20, 30)},
        **{f"town_t_{mode}_{dst}": float((blocks.loc[blocks.locality == TOWN, f"t_{mode}_{dst}"]
                                          * blocks.loc[blocks.locality == TOWN, "population"]).sum()
                                         / max(blocks.loc[blocks.locality == TOWN, "population"].sum(), 1))
           for mode in ("walk", "transit", "drive") for dst in ("station", "campus", "port", "marina")},
        "provision": {f"{r.service}_{'walk' if 'пешком' in r['Доступность'] else 'drive'}": {
            "need": r["Норматив, мест"], "capacity": r["Вместимость (факт)"], "within": r["Обеспечено в нормативе"],
            "deficit": r["Дефицит"], "excess": r["Избыток (свободные места)"], "strong": r["provision_strong"],
            "weak": r["provision_weak"]} for _, r in prov.iterrows()},
        "coverage": {r.service: {"walk": r.walk_share, "transit": r.get("transit_share"), "drive": r.drive_share}
                     for _, r in cov.iterrows()},
        "territory": ind_out, "estimated_capacity": ind["estimated_capacity"],
        "graph": ginfo,
    }
    (REP / "metrics" / f"blocksnet_{tag}.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=1,
                                                                      default=float), encoding="utf-8")

    built = blocks[blocks["count_buildings"] > 0]
    lines = [f"# Анализ «{SCENARIOS[tag]['name']}»: кварталы, доступность, обеспеченность", "",
             "Сгенерировано `scripts/analysis.py` (BlocksNet 1.0.0a9). Таблицы — `reports/*.csv`, слои — "
             "`data/processed/analysis/`; сводная таблица по сценариям — `reports/metrics_scenarios.md`.", "",
             "## 1. Кварталы (агрегация BlocksNet)", "",
             f"- кварталов: {len(blocks)}, застроенных: {len(built)}, с жителями: {(blocks.population > 0).sum()};",
             f"- зданий: {agg_info['buildings']}, вне кварталов: {agg_info['outside_blocks']} "
             f"(население {agg_info['pop_outside']} — присоединено к ближайшему кварталу);",
             f"- постоянное население в кварталах: {pop} (`boundary.population` "
             f"{int(gpd.read_file(PROC / 'boundary.geojson')['population'].iloc[0])}"
             f"{' + жители зданий сценария' if phase else ''}; дачи — сезонный фонд, не входят);",
             f"- общая площадь зданий: {blocks.build_floor_area.sum() / 1e3:,.0f} тыс. м², жилая: "
             f"{blocks.living_area.sum() / 1e3:,.0f} тыс. м² ({blocks.living_area.sum() / pop:.1f} м²/чел.);".replace(",", " "),
             f"- медианы по застроенным кварталам: FSI {built.fsi.median():.2f}, GSI {built.gsi.median():.3f}, "
             f"этажность L {built.l.median():.1f}, плотность населения {built[built.population > 0].pop_density.median():.0f} чел./га.",
             "", "Морфотипы Spacematrix (k-means, 8 кластеров по L / FSI / MXI):", "",
             md_table(blocks[blocks.count_buildings > 0].groupby("morphotype").agg(
                 Кварталов=("population", "size"), Население=("population", "sum"),
                 FSI=("fsi", "median"), L=("l", "median"), MXI=("mxi", "median")).round(2)
                      .sort_values("Население", ascending=False).reset_index().rename(columns={"morphotype": "Морфотип"})),
             "", "## 2. Граф и доступность", "",
             "Граф строится по `data/processed/roads.geojson`; в слое УДС генплана нет части существующих дорог "
             "(прибрежная 41А-082 через Приморск, связки между посёлками), поэтому разрывы достраиваются "
             "участками OSM (`data/raw/osm_roads.geojson`, выгружен 28.10.2026) — интернет при расчёте не нужен. "
             f"«Пешком + шаттл» — пешеходный граф с рёбрами шаттла между остановками ({TRANSIT['speed_kmh']:.0f} км/ч, "
             f"интервал {TRANSIT['headway_min']:.0f} мин, ожидание — половина интервала); сегодня совпадает с «пешком».", "",
             "| Граф | Узлов | Рёбер | км | Компонент | Доля крупнейшей | км по источникам |", "|---|---|---|---|---|---|---|"]
    for k, v in ginfo.items():
        lines.append(f"| {'только roads.geojson' if k == 'roads_only' else k} | {v['nodes']} | {v['edges']} | {v['km']} | "
                     f"{v['components']} | {v['largest_share']:.0%} | {v['km_by_source']} |")
    lines += ["", "Скорости: пешком 5 км/ч; авто — по категории улицы генплана (региональные 70, улицы в жилой "
              "застройке 20 км/ч, грунт ×0,7) и по `highway` OSM. Время до первого узла — пешком.", "",
              f"- `median_accessibility`, взвешенное по населению: авто {metrics['median_acc_drive']:.0f} мин, "
              f"пешком {metrics['median_acc_walk']:.0f} мин, пешком + шаттл {metrics['median_acc_transit']:.0f} мин;",
              f"- среднее время до ж/д станции Приморск: авто {metrics['t_drive_station']:.0f} мин, пешком + шаттл "
              f"{metrics['t_transit_station']:.0f} мин;",
              f"- жителей в 20 мин от станции: пешком {metrics['share_walk_station_20']:.0%}, пешком + шаттл "
              f"{metrics['share_transit_station_20']:.0%}.",
              "", "## 3. Обеспеченность (competitive_provision)", "",
              "Норматив и доступность — `service_types_config` BlocksNet (школа 120 мест/1000 жит., 15 мин; детский "
              "сад 61/1000, 7 мин; колледж 8/1000, 60 мин) — пешком; для сельского поселения добавлен вариант с "
              "подвозом (школа 30 мин, детсад 15 мин на транспорте). Потребность распределена по кварталам "
              "пропорционально населению; вместимость — `capacity`. «Обеспечено за пределами» — места за пределами "
              "нормативной доступности (до 3× норматива).", "",
              md_table(prov.drop(columns=["service"])), "",
              "По населённым пунктам (доля потребности, обеспеченная в нормативной доступности; время до станции на авто):", "",
              md_table(loc.reset_index().rename(columns={
                  "locality": "Населённый пункт", "population": "Население", "school_walk": "Школы пешком",
                  "school_drive": "Школы с подвозом", "kindergarten_walk": "Детсады пешком",
                  "kindergarten_drive": "Детсады транспорт", "t_drive_station": "До станции, мин"})),
              "", "## 4. Охват населения прочими сервисами (доля жителей в пределах времени)", "",
              md_table(cov.drop(columns=["service"]).rename(columns={
                  "walk_min": "пешком, мин", "walk_share": "Доля пешком", "transit_min": "пешком+шаттл, мин",
                  "transit_share": "Доля пешком+шаттл", "drive_min": "авто, мин", "drive_share": "Доля авто"})),
              "", "## 5. Показатели территории BlocksNet (socio_economic)", "",
              "Обеспеченность (`provision_strong`, доля потребности в нормативной доступности на автомобиле) по всем "
              "сервисам с нормативами BlocksNet; вместимость, кроме школ, детсадов и колледжа, — типовая вместимость "
              "наименьшего объекта BlocksNet (оценка). Полностью — `reports/territory_indicators_" + tag + ".csv`.", "",
              md_table(pd.DataFrame({"Показатель": list(ind_out.get("provision", {}).keys()),
                                     "Поселение": list(ind_out.get("provision", {}).values())})
                       .dropna().round(2)), ""]
    (REP / f"analysis_{tag}.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"{tag}: население {pop}, median_acc_drive {metrics['median_acc_drive']:.1f}, "
          f"детсады drive {metrics['provision'].get('kindergarten_drive', {}).get('strong')}")
    return metrics


def main() -> None:
    tags = [a for a in sys.argv[1:] if a in SCENARIOS] or list(SCENARIOS)
    for tag in tags:
        run(tag)


if __name__ == "__main__":
    main()
