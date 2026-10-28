"""
ObjectNat 2.1 (IduEdu 2.3): изохроны, обеспеченность по зданиям, шум и зоны видимости — «было» и «стало».

Для каждого сценария (scripts/scenarios.py) на графе roadgraph.scenario_graphs (тот же, что в analysis.py):
1. Изохроны (get_graph_isochrones) от ж/д станции, центра, марины, кампуса и порта: пешком 15 мин и
   «пешком + шаттл» 30 мин → площадь, число жителей внутри.
2. Обеспеченность детскими садами и школами по зданиям (get_service_provision, гравитационная модель):
   пешком, нормативы как в BlocksNet (61 и 120 мест на 1000 жителей; 7 и 15 мин).
3. Шум (calculate_simplified_noise_frame) от ж/д, региональных дорог и порта в г. Приморске → жители в зоне
   ≥ 55 дБА (СанПиН 1.2.3685-21, день, территории жилой застройки), объекты сценария в зоне шума.
4. Зоны видимости (get_visibility) с пешеходного маршрута по набережной: видимая площадь акватории
   (видовые раскрытия на залив) — как меняется после застройки марины.

Окружение — .venv-objectnat (scripts/setup.sh). Запуск: .venv-objectnat/bin/python scripts/objectnat_analysis.py
Выход: data/processed/objectnat/*.geojson, reports/metrics/objectnat_<tag>.json, reports/objectnat.md
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from roadgraph import MCRS, edges_gdf, scenario_graphs, scenario_layer  # noqa: E402
from scenarios import SCENARIOS  # noqa: E402

from objectnat import config as on_config  # noqa: E402

on_config.change_logger_lvl("WARNING")
on_config.set_enable_tqdm(False)
from iduedu.graph.urban_graph import UrbanGraph  # noqa: E402
from objectnat import (calculate_simplified_noise_frame, get_graph_isochrones, get_service_provision,  # noqa: E402
                       get_visibility)

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
OUT = PROC / "objectnat"
REP = ROOT / "reports"

ORIGINS = {"станция": (589964, 6693001), "центр": (588638, 6693428), "марина": (588694, 6693041),
           "кампус": (593014, 6691007), "порт": (594950, 6690540)}
ISO = [("walk", 15), ("transit", 30)]
# мест на 1000 жит. по МНГП ЛО для зоны Б (г. Приморск, сельские НП) — как в analysis.py; мин пешком
PROVISION = {"kindergarten": ((61, 40), 7), "school": ((91, 61), 15)}
TOWN = "Приморск"
# источники шума: эквивалентный уровень Lэкв на 7,5 м (дБА; типовые значения для ж/д, магистральных и
# местных улиц, границы порта) → уровень на 1 м от источника, как ждёт ObjectNat: +20·lg(7,5) ≈ +17,5 дБ
L75 = {"railway": 80, "regional_road": 75, "main_street": 70, "port": 68}
FREQ = {"railway": 1000, "regional_road": 2000, "main_street": 2000, "port": 1000}
NOISE = {k: (round(v + 17.5), FREQ[k]) for k, v in L75.items()}
OSM_MAIN = {"primary": "regional_road", "secondary": "regional_road", "tertiary": "main_street"}
NOISE_LIMIT = 55
TOWN_BOX = (586500, 6689000, 597000, 6696500)                  # охват расчёта шума и видимости, UTM 35N
VIEW_STEP, VIEW_DIST = 150, 600                                 # точки обзора на маршруте, м


def read(p: Path) -> gpd.GeoDataFrame:
    return gpd.read_file(p).to_crs(MCRS)


def urban_graph(G) -> UrbanGraph:
    """UrbanGraph из таблиц узлов и рёбер (UrbanGraph.from_nx_graph в IduEdu 2.3 падает на read-only массиве)."""
    nodes = gpd.GeoDataFrame(index=list(G.nodes), geometry=gpd.points_from_xy(
        [G.nodes[n]["x"] for n in G.nodes], [G.nodes[n]["y"] for n in G.nodes]), crs=MCRS)
    e = edges_gdf(G)
    e = gpd.GeoDataFrame(e[["u", "v", "length_meter", "time_min", "geometry"]], geometry="geometry", crs=MCRS)
    return UrbanGraph(nodes, e, is_multigraph=False, is_directed=False, crs=MCRS, graph_type="walk")


def buildings(phase: int) -> gpd.GeoDataFrame:
    b = read(PROC / "building.geojson")
    sb = scenario_layer("building", phase)
    if sb is not None:
        sb = sb.assign(is_scenario=True)
        b = pd.concat([b.assign(is_scenario=False), sb], ignore_index=True)
    else:
        b["is_scenario"] = False
    b = gpd.GeoDataFrame(b, geometry="geometry", crs=MCRS)
    b["is_living"] = b["is_living"].astype(bool)
    return b


def services(svc: str, phase: int) -> gpd.GeoDataFrame:
    s = read(PROC / "services" / f"{svc}.geojson")
    sc = scenario_layer(svc, phase)
    if sc is not None:
        s = pd.concat([s, sc], ignore_index=True)
    s = gpd.GeoDataFrame(s, geometry=s.representative_point(), crs=MCRS).reset_index(drop=True)
    return s


def pop_inside(polys: gpd.GeoDataFrame, b: gpd.GeoDataFrame) -> list[int]:
    pts = gpd.GeoDataFrame({"population": b["population"]}, geometry=b.representative_point(), crs=MCRS)
    j = gpd.sjoin(pts[pts.population > 0], polys[["geometry"]], predicate="within")
    s = j.groupby("index_right")["population"].sum()
    return [int(s.get(i, 0)) for i in polys.index]


# =============================================================================
def isochrones(G: dict, b: gpd.GeoDataFrame, tag: str) -> list[dict]:
    rows, layers = [], []
    for mode, t in ISO:
        ug = urban_graph(G[mode])
        o = gpd.GeoDataFrame({"name": list(ORIGINS)}, geometry=gpd.points_from_xy(*zip(*ORIGINS.values())), crs=MCRS)
        iso = get_graph_isochrones(ug, weight_value_cutoff=t, gdf_origins=o, weight_type="time_min",
                                   geometry_type="ways", road_buffer_size=60)
        iso = iso.to_crs(MCRS).reset_index(drop=True)
        iso["name"] = list(ORIGINS)[:len(iso)] if "name" not in iso else iso["name"]
        iso["mode"], iso["minutes"] = mode, t
        iso["population"] = pop_inside(iso, b)
        iso["area_ha"] = (iso.area / 1e4).round(1)
        layers.append(iso[["name", "mode", "minutes", "population", "area_ha", "geometry"]])
        for _, r in iso.iterrows():
            rows.append({"origin": r["name"], "mode": mode, "minutes": t, "population": int(r["population"]),
                         "area_ha": float(r["area_ha"])})
    write(pd.concat(layers, ignore_index=True), OUT / f"isochrones_{tag}.geojson")
    return rows


def provision(G: dict, b: gpd.GeoDataFrame, phase: int, tag: str) -> dict:
    res = {}
    liv = b[b["population"] > 0].copy()
    liv["geometry"] = liv.representative_point()
    liv = liv.reset_index(drop=True)
    bl = read(PROC / "analysis" / f"blocks_{tag}.geojson")[["locality", "geometry"]]
    j = gpd.sjoin(liv[["geometry"]], bl, how="left", predicate="within")
    town = (j[~j.index.duplicated()]["locality"] == TOWN).reindex(liv.index, fill_value=False)
    ug = urban_graph(G["walk"])
    for svc, ((k_town, k_rural), t) in PROVISION.items():
        s = services(svc, phase)
        liv["demand"] = (liv["population"] * np.where(town, k_town, k_rural) / 1000).round(3)
        mx = ug.od_matrix(gdf_origins=liv, gdf_destinations=s, weight="time_min")
        pr = get_service_provision(buildings=liv, distance_matrix=mx, services=s, threshold=t)
        d = pr.demand_rows
        within = [c for c in d.columns if "within" in c.lower() or "inside" in c.lower()]
        supplied_in = float(d[within[0]].sum()) if within else float("nan")
        total = float(liv["demand"].sum())
        res[svc] = {"demand": round(total, 1), "supplied_within": round(supplied_in, 1),
                    "share_within": round(supplied_in / total, 3) if total else None,
                    "columns": list(d.columns)}
        out = liv[["population", "geometry"]].join(d.reset_index(drop=True).add_prefix(f"{svc}_"))
        write(out, OUT / f"provision_{svc}_{tag}.geojson")
    return res


def noise(b: gpd.GeoDataFrame, phase: int, tag: str) -> dict:
    from shapely.geometry import box
    area = box(*TOWN_BOX)
    rw = read(PROC / "railways.geojson").clip(area)
    roads = read(PROC / "roads.geojson")
    rr = roads[roads["highway_type_id"] == 51].clip(area)
    port = read(PROC / "services" / "port.geojson").clip(area)
    # прибрежной 41А-082 через город нет в УДС генплана — магистральные улицы берём из OSM
    osm = read(ROOT / "data" / "raw" / "osm_roads.geojson")
    osm = osm[osm["highway"].isin(OSM_MAIN)].clip(area)
    osm = osm.assign(kind=osm["highway"].map(OSM_MAIN))
    src = pd.concat([rw.assign(kind="railway"), rr.assign(kind="regional_road"), osm, port.assign(kind="port")],
                    ignore_index=True)[["kind", "geometry"]]
    src = gpd.GeoDataFrame(src, geometry="geometry", crs=MCRS).explode(index_parts=False).reset_index(drop=True)
    src = src[~src.geometry.is_empty]
    src["source_noise_db"] = src["kind"].map(lambda k: NOISE[k][0])
    src["geometric_mean_freq_hz"] = src["kind"].map(lambda k: NOISE[k][1])
    obst = b[b.intersects(area)][["geometry"]].reset_index(drop=True)
    frame = calculate_simplified_noise_frame(src, obst, air_temperature=10, target_noise_db=45, db_sim_step=5,
                                             linestring_point_radius=30, polygon_point_radius=40,
                                             visibility_parallel=True, visibility_max_workers=4)
    frame = frame.to_crs(MCRS)
    write(frame, OUT / f"noise_{tag}.geojson")
    loud = frame[frame["noise_level"] >= NOISE_LIMIT].union_all() if "noise_level" in frame else frame.union_all()
    bb = b[b.intersects(area)]
    # здания — препятствия, зона шума обходит их контуры: дом в зоне, если её касается фасад (буфер 3 м)
    in_loud = bb.geometry.buffer(3).intersects(loud)
    town_pop = int(bb["population"].sum())
    res = {"population_ge55": int(bb.loc[in_loud, "population"].sum()), "town_population": town_pop,
           "share_ge55": round(float(bb.loc[in_loud, "population"].sum() / max(town_pop, 1)), 3)}
    if phase:
        sc = bb[bb["is_scenario"]]
        res["scenario_buildings_ge55"] = int(in_loud[sc.index].sum())
        res["scenario_buildings"] = int(len(sc))
        res["scenario_population_ge55"] = int(sc.loc[in_loud[sc.index], "population"].sum())
    return res


def visibility(b: gpd.GeoDataFrame, tag: str) -> dict:
    """Точки обзора — пешеходный маршрут «набережная» (footway сценария) каждые VIEW_STEP м."""
    fw = read(PROC / "scenario" / "footway.geojson")
    route = fw.geometry.iloc[0]
    pts = [route.interpolate(d) for d in np.arange(0, route.length, VIEW_STEP)]
    pf = gpd.GeoDataFrame(geometry=pts, crs=MCRS)
    obst = b[b.intersects(route.buffer(VIEW_DIST + 50))][["geometry"]].reset_index(drop=True)
    vis = get_visibility(pf, obst, view_distance=VIEW_DIST, method="accurate").to_crs(MCRS)
    water = read(PROC / "water.geojson")
    sea = water[water.intersects(route.buffer(VIEW_DIST))].union_all()
    vis["sea_ha"] = vis.intersection(sea).area / 1e4
    vis["area_ha"] = vis.area / 1e4
    write(vis, OUT / f"visibility_{tag}.geojson")
    union = vis.union_all()
    return {"points": len(pf), "mean_view_ha": round(float(vis["area_ha"].mean()), 2),
            "mean_sea_view_ha": round(float(vis["sea_ha"].mean()), 2),
            "union_sea_view_ha": round(float(union.intersection(sea).area / 1e4), 1)}


def write(g: gpd.GeoDataFrame, p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        p.unlink()
    g = g[[c for c in g.columns if g[c].dtype != object or c == "geometry" or isinstance(g[c].iloc[0], str)]]
    gpd.GeoDataFrame(g, geometry="geometry", crs=MCRS).to_crs(4326).to_file(p, driver="GeoJSON", engine="pyogrio")


def run(tag: str) -> dict:
    phase = SCENARIOS[tag]["phase"]
    G, _ = scenario_graphs(phase)
    b = buildings(phase)
    m = {"tag": tag, "name": SCENARIOS[tag]["name"]}
    m["isochrones"] = isochrones(G, b, tag)
    print(tag, "изохроны готовы")
    m["provision"] = provision(G, b, phase, tag)
    print(tag, "обеспеченность по зданиям:", {k: v["share_within"] for k, v in m["provision"].items()})
    m["noise"] = noise(b, phase, tag)
    print(tag, "шум:", m["noise"])
    m["visibility"] = visibility(b, tag)
    print(tag, "видимость:", m["visibility"])
    (REP / "metrics").mkdir(parents=True, exist_ok=True)
    (REP / "metrics" / f"objectnat_{tag}.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    return m


def main() -> None:
    tags = [a for a in sys.argv[1:] if a in SCENARIOS] or list(SCENARIOS)
    res = [run(t) for t in tags]
    if len(res) == len(SCENARIOS):
        report(res)


def report(res: list[dict]) -> None:
    lines = ["# ObjectNat: изохроны, обеспеченность по зданиям, шум, видимость", "",
             "Сгенерировано `scripts/objectnat_analysis.py` (ObjectNat 2.1, IduEdu 2.3). Слои — "
             "`data/processed/objectnat/`.", "", "## Изохроны: жители в зоне доступности", "",
             "| Откуда | Режим | " + " | ".join(r["name"] for r in res) + " |", "|---|---|" + "---|" * len(res)]
    for i, row in enumerate(res[0]["isochrones"]):
        mode = "пешком" if row["mode"] == "walk" else "пешком + шаттл"
        vals = [f"{r['isochrones'][i]['population']} чел. / {r['isochrones'][i]['area_ha']:.0f} га" for r in res]
        lines.append(f"| {row['origin']} | {mode}, {row['minutes']} мин | " + " | ".join(vals) + " |")
    lines += ["", "## Обеспеченность по зданиям (get_service_provision, пешком)", "",
              "| Сервис | " + " | ".join(r["name"] for r in res) + " |", "|---|" + "---|" * len(res)]
    for svc in PROVISION:
        lines.append(f"| {svc} | " + " | ".join(f"{r['provision'][svc]['share_within']:.0%}" for r in res) + " |")
    lines += ["", f"## Шум (г. Приморск): жители в зоне ≥ {NOISE_LIMIT} дБА", "",
              "Источники (Lэкв на 7,5 м, пересчёт к 1 м +17,5 дБ): ж/д 80 дБА, региональные дороги и 41А-082 75 дБА, "
              "улицы `tertiary` OSM 70 дБА, граница порта 68 дБА — типовые оценки, не замеры; препятствия — здания.", "",
              "| " + " | ".join(r["name"] for r in res) + " |", "|" + "---|" * len(res),
              "| " + " | ".join(f"{r['noise']['population_ge55']} ({r['noise']['share_ge55']:.0%})"
                                 + (f"; объектов сценария в зоне: {r['noise'].get('scenario_buildings_ge55')} из "
                                    f"{r['noise'].get('scenario_buildings')}" if 'scenario_buildings' in r['noise'] else "")
                                 for r in res) + " |",
              "", "## Видовые раскрытия на залив с набережной (get_visibility)", "",
              "| Показатель | " + " | ".join(r["name"] for r in res) + " |", "|---|" + "---|" * len(res),
              "| Средняя видимая акватория с точки, га | " + " | ".join(str(r["visibility"]["mean_sea_view_ha"]) for r in res) + " |",
              "| Суммарная видимая акватория, га | " + " | ".join(str(r["visibility"]["union_sea_view_ha"]) for r in res) + " |", ""]
    (REP / "objectnat.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
