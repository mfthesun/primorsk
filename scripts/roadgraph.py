"""
Дорожный граф по слою УДС (data/processed/roads.geojson) — без загрузки OSM.

Граф совместим с BlocksNet / IduEdu: nx.Graph, graph["crs"] = 32635, у узлов x, y,
у рёбер length_meter, time_min, geometry.

    from roadgraph import load_network, build_graph
    G = build_graph(load_network(), mode="walk")    # пешеходный, 5 км/ч
    G = build_graph(load_network(), mode="drive")   # автомобильный, скорость по категории улицы

Слой УДС взят из генплана и состоит из отдельных отрезков: концы, не совпадающие с другими
отрезками ближе SNAP_TOL, сшиваются с ближайшим узлом в пределах GAP_TOL (разрывы оцифровки).
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import shapely
import shapely.ops
from shapely.geometry import LineString

ROOT = Path(__file__).resolve().parents[1]
MCRS = 32635
SNAP_TOL = 1.0     # м — совпадающие концы
GAP_TOL = 25.0     # м — сшивка висячих концов
WALK_SPEED = 5.0   # км/ч, как в IduEdu
# км/ч по атрибуту function слоя roads (ГП); для «было» — разрешённые скорости с поправкой на покрытие
DRIVE_SPEED = {
    "Автомобильные дороги регионального или межмуниципального значения": 70,
    "Магистральная улица общегородского значения регулируемого движения": 50,
    "Главная улица": 40,
    "Автомобильные дороги местного значения": 50,
    "Улицы и дороги местного значения": 40,
    "Автомобильные дороги иного значения": 30,
    "Улица в жилой застройке": 20,
}
UNPAVED_FACTOR = 0.7   # surface_exist = 2 / 3 (грунт, щебень) — скорость ×0,7
# Дополнение OSM (data/raw/osm_roads.geojson): в слое УДС генплана нет части существующих дорог
# (прибрежная 41А-082 через Приморск, связки между посёлками) — без них граф распадается на ~120 частей.
OSM_SPEED = {"motorway": 90, "trunk": 90, "primary": 70, "secondary": 60, "tertiary": 50, "unclassified": 40,
             "road": 30, "residential": 20, "living_street": 10, "service": 15, "track": 15,
             "motorway_link": 50, "trunk_link": 50, "primary_link": 40, "secondary_link": 40, "tertiary_link": 30}
OSM_WALK_ONLY = {"footway", "path", "pedestrian", "steps", "cycleway"}
OSM_COVER = 15.0   # м — участок OSM ближе к линии генплана считается уже учтённым


def load_roads(path: Path | None = None, include_planned: bool = False) -> gpd.GeoDataFrame:
    """Существующая УДС (event_time ≤ 2022); include_planned — с планируемыми дорогами (2042)."""
    r = gpd.read_file(path or ROOT / "data" / "processed" / "roads.geojson").to_crs(MCRS)
    if not include_planned and "event_time" in r:
        r = r[r["event_time"].fillna(2022) <= 2022]
    r = r.explode(index_parts=False)
    r = r[r.geom_type == "LineString"].reset_index(drop=True)
    return r


def load_network(include_osm: bool = True, include_planned: bool = False) -> gpd.GeoDataFrame:
    """Каркас — УДС генплана; include_osm — достроить разрывы участками OSM, которых нет в генплане."""
    r = load_roads(include_planned=include_planned)
    r["source_layer"] = "roads"
    osm_path = ROOT / "data" / "raw" / "osm_roads.geojson"
    if not include_osm or not osm_path.exists():
        return r
    o = gpd.read_file(osm_path).to_crs(MCRS)
    cover = shapely.union_all(r.buffer(OSM_COVER).values)
    o["geometry"] = o.geometry.difference(cover)
    o = o.explode(index_parts=False)
    o = o[(o.geom_type == "LineString") & (o.length > 2 * OSM_COVER)]
    o = o.rename(columns={"highway": "osm_highway"})
    o["source_layer"] = "osm"
    return gpd.GeoDataFrame(pd.concat([r, o], ignore_index=True), geometry="geometry", crs=MCRS)


def _speed(row, mode: str) -> float:
    hw = row.get("osm_highway")
    if mode == "walk":
        return WALK_SPEED
    if isinstance(hw, str):
        return OSM_SPEED.get(hw, 0.0)          # 0 — только пешеходы
    v = DRIVE_SPEED.get(row.get("function"), 40 if row.get("highway_type_id") == 51 else 30)
    if row.get("surface_exist") in (2, 3) and row.get("highway_type_id") != 51:
        v *= UNPAVED_FACTOR
    return v


def _node_lines(lines: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Нодирование: линии режутся в пересечениях и в точках примыкания висячих концов (≤ GAP_TOL);
    для примыканий с зазором добавляются перемычки kind = "gap"."""
    geoms = list(lines.geometry.values)
    tree = shapely.STRtree(geoms)
    cuts: dict[int, list[float]] = {}
    gaps = []
    for i, g in enumerate(geoms):
        for k in (0, -1):
            p = shapely.Point(g.coords[k])
            cand = [c for c in tree.query(p, predicate="dwithin", distance=GAP_TOL) if c != i]
            if not cand:
                continue
            # конец уже совпадает с концом другой линии — примыкание есть
            if any(min(shapely.Point(geoms[c].coords[0]).distance(p),
                       shapely.Point(geoms[c].coords[-1]).distance(p)) <= SNAP_TOL for c in cand):
                continue
            c = min(cand, key=lambda c: geoms[c].distance(p))
            d = geoms[c].line_locate_point(p)
            if 0 < d < geoms[c].length:
                cuts.setdefault(c, []).append(d)
            q = geoms[c].interpolate(d)
            if p.distance(q) > SNAP_TOL:
                gaps.append(LineString([p, q]))
    rows = []
    attrs = lines.drop(columns="geometry")
    for i, g in enumerate(geoms):
        ds = [0.0] + sorted(set(cuts.get(i, []))) + [g.length]
        for d0, d1 in zip(ds[:-1], ds[1:]):
            if d1 - d0 > 0.01:
                rows.append({**attrs.iloc[i].to_dict(), "geometry": shapely.ops.substring(g, d0, d1)})
    for gl in gaps:
        rows.append({"function": "Улица в жилой застройке", "highway_type_id": 52, "kind": "gap",
                     "source_layer": "gap", "geometry": gl})
    out = gpd.GeoDataFrame(rows, geometry="geometry", crs=MCRS)
    # пересечения «крест-накрест»: делим по точкам пересечения с другими линиями
    union = shapely.union_all(out.geometry.values)
    pieces = list(union.geoms) if hasattr(union, "geoms") else [union]
    segs = gpd.GeoDataFrame(geometry=pieces, crs=MCRS)
    mid = gpd.GeoDataFrame(geometry=segs.geometry.interpolate(0.5, normalized=True), crs=MCRS)
    j = gpd.sjoin_nearest(mid, out, how="left", max_distance=1.0)
    j = j[~j.index.duplicated()]
    return segs.join(j.drop(columns=["geometry", "index_right"]))


def build_graph(roads: gpd.GeoDataFrame, mode: str = "walk", extra_lines: gpd.GeoDataFrame | None = None) -> nx.Graph:
    """Граф из линий. extra_lines — дополнительные линии сценария (велодорожки и т. п.) с тем же набором полей."""
    lines = roads if extra_lines is None else pd.concat([roads, extra_lines.to_crs(MCRS)], ignore_index=True)
    lines = gpd.GeoDataFrame(lines, geometry="geometry", crs=MCRS).reset_index(drop=True)
    lines = lines.explode(index_parts=False)
    lines = lines[lines.geom_type == "LineString"].reset_index(drop=True)
    segs = _node_lines(lines)
    segs = segs[segs.length > 0.01].reset_index(drop=True)

    # узлы: концы отрезков, совпадающие в пределах SNAP_TOL, объединяются (union-find)
    ends = np.array([c for g in segs.geometry for c in (g.coords[0], g.coords[-1])])
    parent = np.arange(len(ends))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    pt_tree = shapely.STRtree(shapely.points(ends))
    for a, b in zip(*pt_tree.query(shapely.points(ends), predicate="dwithin", distance=SNAP_TOL)):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    root = np.array([find(i) for i in range(len(ends))])

    G = nx.Graph(crs=MCRS, mode=mode)
    for k, row in enumerate(segs.itertuples(index=False)):
        a, b = int(root[2 * k]), int(root[2 * k + 1])
        if a == b:
            continue
        geom: LineString = row.geometry
        v = _speed(row._asdict(), mode)
        if v <= 0:
            continue
        # IduEdu хранит вес как целое time_min × 100: ребро короче 0,01 мин обнулилось бы и выпало из матрицы
        t = max(geom.length / (v * 1000 / 60), 0.01)
        if G.has_edge(a, b) and G[a][b]["time_min"] <= t:
            continue
        kind = getattr(row, "kind", None)
        for n in (a, b):
            G.add_node(n, x=float(ends[n][0]), y=float(ends[n][1]))
        src = getattr(row, "source_layer", None)
        G.add_edge(a, b, length_meter=float(geom.length), time_min=float(t), geometry=geom,
                   speed_kmh=float(v), kind=kind if isinstance(kind, str) else "road",
                   source_layer=src if isinstance(src, str) else "roads")
    return nx.convert_node_labels_to_integers(G)


def largest_component(G: nx.Graph) -> nx.Graph:
    cc = max(nx.connected_components(G), key=len)
    # узлы — подряд 0..n-1: IduEdu использует метку узла как номер строки разреженной матрицы
    return nx.convert_node_labels_to_integers(G.subgraph(cc).copy())


def nearest_node(G: nx.Graph, x: float, y: float) -> int:
    xy = np.array([(d["x"], d["y"]) for _, d in G.nodes(data=True)])
    ids = list(G.nodes)
    return ids[int(np.argmin((xy[:, 0] - x) ** 2 + (xy[:, 1] - y) ** 2))]


def path_line(G: nx.Graph, nodes: list[int]) -> LineString:
    """Линия маршрута по последовательности узлов кратчайшего пути."""
    coords: list = []
    for u, v in zip(nodes[:-1], nodes[1:]):
        g = G[u][v]["geometry"]
        c = list(g.coords)
        if np.hypot(c[0][0] - G.nodes[u]["x"], c[0][1] - G.nodes[u]["y"]) > \
                np.hypot(c[-1][0] - G.nodes[u]["x"], c[-1][1] - G.nodes[u]["y"]):
            c = c[::-1]
        coords.extend(c if not coords else c[1:])
    return LineString(coords)


def graph_summary(G: nx.Graph) -> dict:
    cc = sorted((len(c) for c in nx.connected_components(G)), reverse=True)
    km = sum(d["length_meter"] for *_, d in G.edges(data=True)) / 1000
    by_src: dict = {}
    for *_, d in G.edges(data=True):
        by_src[d.get("source_layer")] = by_src.get(d.get("source_layer"), 0) + d["length_meter"] / 1000
    gaps = sum(1 for *_, d in G.edges(data=True) if d.get("kind") == "gap")
    return {"nodes": G.number_of_nodes(), "edges": G.number_of_edges(), "km": round(km, 1),
            "components": len(cc), "largest_share": round(cc[0] / G.number_of_nodes(), 3), "gap_links": gaps,
            "km_by_source": {k: round(v, 1) for k, v in by_src.items()}}


def edges_gdf(G: nx.Graph) -> gpd.GeoDataFrame:
    rows = [{"u": u, "v": v, **{k: d[k] for k in ("length_meter", "time_min", "speed_kmh", "kind", "source_layer")},
             "geometry": d["geometry"]} for u, v, d in G.edges(data=True)]
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=MCRS)


def add_transit(G: nx.Graph, route: LineString, stops: list[tuple[float, float]], speed_kmh: float = 25.0,
                headway_min: float = 15.0, kind: str = "shuttle") -> nx.Graph:
    """Пешеходный граф + маршрут ОТ (шаттл): рёбра между всеми парами остановок, время = путь по маршруту /
    скорость + ожидание (половина интервала). Остановки привязываются к ближайшим узлам графа."""
    G = G.copy()
    pos = sorted((route.line_locate_point(shapely.Point(xy)), xy) for xy in stops)
    nodes = [nearest_node(G, *xy) for _, xy in pos]
    for i in range(len(pos)):
        for j in range(i + 1, len(pos)):
            d = abs(pos[j][0] - pos[i][0])
            t = d / (speed_kmh * 1000 / 60) + headway_min / 2
            a, b = nodes[i], nodes[j]
            if a == b or (G.has_edge(a, b) and G[a][b]["time_min"] <= t):
                continue
            G.add_edge(a, b, length_meter=float(d), time_min=float(t), speed_kmh=speed_kmh, kind=kind,
                       source_layer="scenario", geometry=LineString([pos[i][1], pos[j][1]]))
    return G


TRANSIT = {"speed_kmh": 25.0, "headway_min": 15.0}     # шаттл: скорость с остановками, интервал движения


def scenario_layer(name: str, phase: int) -> gpd.GeoDataFrame | None:
    """Объекты слоя сценария, вводимые к очереди phase (0 — сегодня: объектов нет)."""
    p = ROOT / "data" / "processed" / "scenario" / f"{name}.geojson"
    if phase == 0 or not p.exists():
        return None
    x = gpd.read_file(p).to_crs(MCRS)
    x = x[x["phase"] <= phase]
    return x if len(x) else None


def scenario_graphs(phase: int) -> tuple[dict, dict]:
    """Графы для сценария (неориентированные, крупнейшая компонента, узлы 0..n-1):
    walk (в сценариях — с велодорожкой и пешеходными маршрутами), drive и transit (walk + шаттл; сегодня = walk)."""
    net = load_network()
    out, info = {}, {}
    extra = [x for x in (scenario_layer("cycleway", phase), scenario_layer("footway", phase)) if x is not None]
    for mode in ("walk", "drive"):
        lines = None
        if extra and mode == "walk":
            lines = pd.concat(extra, ignore_index=True)[["geometry"]].assign(source_layer="scenario",
                                                                            kind="scenario_path")
        G = build_graph(net, mode, extra_lines=lines)
        info[mode] = graph_summary(G)
        out[mode] = largest_component(G)
    route, stops = scenario_layer("shuttle_route", phase), scenario_layer("bus_stop", phase)
    if route is not None and stops is not None:
        st = stops[stops.distance(route.geometry.iloc[0]) < 300]
        out["transit"] = add_transit(out["walk"], route.geometry.iloc[0], [(p.x, p.y) for p in st.geometry],
                                     **TRANSIT)
        info["transit"] = {**graph_summary(out["transit"]), "stops": len(st)}
    else:
        out["transit"] = out["walk"]
    return out, info
