"""
Пешеходный граф УДС Приморска из слоёв репозитория — без внешних запросов.

Строится из `data/processed/roads.geojson` (+ планируемая 41А-082 из scenario/roads):
unary_union нодит пересечения, узлы сшиваются с допуском, вес ребра — время пешком
(5 км/ч). Для сценария «после» маршрут шаттла добавляется рёбрами на скорости
автобуса 25 км/ч с пешеходными подходами к остановкам.

Используется тетрадями notebooks/ (см. notebooks/01, 02).
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
import shapely
from scipy.spatial import cKDTree
from shapely.geometry import LineString, Point

CRS, MCRS = 4326, 32635
SPEED_WALK = 5000 / 60       # м/мин — 5 км/ч
SPEED_BUS = 25000 / 60       # м/мин — 25 км/ч (шаттл по маршруту)
STITCH_DEG = 0.0004          # ~40 м — допуск сшивки узлов

ROOT = Path(__file__).resolve().parents[1]


def _merge_nodes(coords: list, pairs: list) -> tuple[np.ndarray, np.ndarray]:
    """Сшивка узлов ближе STITCH_DEG (union-find)."""
    tree = cKDTree(np.array(coords))
    parent = list(range(len(coords)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j in tree.query_pairs(STITCH_DEG):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)
    return parent, find


def build_walk_graph(data_dir: Path | None = None, include_planned: bool = True):
    """Граф пешеходной сети: (G, pos_m, names). pos_m — узел → Point в EPSG:32635."""
    data_dir = data_dir or ROOT / "data" / "processed"
    bnd = gpd.read_file(data_dir / "boundary.geojson")
    roads = gpd.read_file(data_dir / "roads.geojson")
    minx, miny, maxx, maxy = bnd.total_bounds
    parts = [roads.cx[minx:maxx, miny:maxy]]
    if include_planned and (data_dir / "scenario" / "roads.geojson").exists():
        parts.append(gpd.read_file(data_dir / "scenario" / "roads.geojson"))
    r = pd.concat(parts, ignore_index=True)

    noded = shapely.ops.unary_union(list(r.geometry.explode(index_parts=False).geometry))
    lines = list(noded.geoms) if noded.geom_type == "MultiLineString" else [noded]

    coords, remap, edges = [], {}, []
    for line in lines:
        ids = []
        for x, y in line.coords:
            key = (round(x * 111320), round(y * 111320))   # сетка ~1 м
            if key not in remap:
                remap[key] = len(coords)
                coords.append((x, y))
            ids.append(remap[key])
        edges += list(zip(ids, ids[1:]))

    parent, find = _merge_nodes(coords, edges)
    pos_wgs = {}
    for i, c in enumerate(coords):
        pos_wgs.setdefault(find(i), c)
    pts_m = gpd.GeoSeries([Point(c) for c in pos_wgs.values()], crs=CRS).to_crs(MCRS)
    pos_m = dict(zip(pos_wgs.keys(), pts_m))

    g = nx.Graph()
    for i, j in edges:
        a, b = find(i), find(j)
        if a == b:
            continue
        t = pos_m[a].distance(pos_m[b]) / SPEED_WALK
        if not g.has_edge(a, b) or g[a][b]["weight"] > t:
            g.add_edge(a, b, weight=t)
    return g, pos_m, list(pos_m)


def nearest_node(pos_m: dict, pt_m) -> int:
    """Ближайший узел графа к точке (EPSG:32635)."""
    arr = np.array([[p.x, p.y] for p in pos_m.values()])
    names = list(pos_m)
    k = cKDTree(arr).query([pt_m.x, pt_m.y])[1]
    return names[int(k)]


def graph_with_shuttle(g: nx.Graph, pos_m: dict, data_dir: Path | None = None,
                       speed_bus: float = SPEED_BUS):
    """Граф «после»: маршрут шаттла рёбрами на скорости автобуса + подходы к остановкам пешком."""
    data_dir = data_dir or ROOT / "data" / "processed"
    route = gpd.read_file(data_dir / "scenario" / "shuttle_route.geojson").union_all()
    route = shapely.line_merge(route)
    route = gpd.GeoSeries([route], crs=CRS).to_crs(MCRS).iloc[0]   # метры, не градусы
    if route.geom_type == "MultiLineString":          # склейка частей в одну полилинию
        coords = []
        for part in route.geoms:
            coords.extend(part.coords)
        route = LineString(coords)
    stops = gpd.read_file(data_dir / "scenario" / "bus_stop.geojson")
    stops = stops[stops["name"].astype(str).str.contains("Шаттл|Карасёвка", case=False, na=False)]
    stop_pts = stops.to_crs(MCRS).geometry.centroid.tolist()

    g2 = g.copy()
    names = list(pos_m)
    # узлы остановок + подходы пешком к сети
    stop_nodes = []
    for p in stop_pts:
        nid = f"stop_{len(stop_nodes)}"
        g2.add_node(nid)
        pos_m = {**pos_m, nid: p}
        base = nearest_node({n: pos_m[n] for n in names}, p)
        g2.add_edge(nid, base, weight=p.distance(pos_m[base]) / SPEED_WALK)
        stop_nodes.append(nid)

    # сегменты маршрута между остановками (порядок — вдоль маршрута)
    proj = sorted(range(len(stop_pts)), key=lambda i: route.project(stop_pts[i]))
    for a, b in zip(proj, proj[1:]):
        s = route.project(stop_pts[a])
        e = route.project(stop_pts[b])
        seg = shapely.ops.substring(route, s, e)
        t = seg.length / speed_bus
        if not g2.has_edge(stop_nodes[a], stop_nodes[b]) or g2[stop_nodes[a]][stop_nodes[b]]["weight"] > t:
            g2.add_edge(stop_nodes[a], stop_nodes[b], weight=t)
    return g2, pos_m, stop_nodes
