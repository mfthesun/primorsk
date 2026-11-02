"""
Черновики проектных слоёв сценария (транспортный проект + причалы + детсад).

Геометрия маршрутов строится по существующей и планируемой улично-дорожной сети:
кратчайшие пути по графу дорог (вершины линий + сшивка разрывов до 20 м), а не по
прямым между опорными точками. Целевые длины — из презентации контроля 03.11.2026:
шаттл ≈ 8,6 км, велодорожка ≈ 5,1 км, пешеходные маршруты ≈ 4,7 км суммарно.

Генерирует исходные слои в data/raw/scenario_geojson/ — дальше их правит команда
(в QGIS или руками), process.py подхватывает их оттуда.

Запуск из корня репозитория:  python scripts/scenario_drafts.py
"""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import shapely
from scipy.spatial import cKDTree
from shapely.geometry import LineString, Point

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "scenario_geojson"
CRS = 4326
MCRS = 32635
NODE_TOL = 40.0      # м — сшивка разрывов сети (30–40 м дают связные маршруты без лишних крюков)
CORRIDOR = (28.55, 60.32, 28.80, 60.41)   # окно сети: центр — кампус — порт

# ---- опорные точки (WGS84) --------------------------------------------------
STOP_CENTER = (28.6085, 60.3649)    # центр, у марины (наб. Лебедева)
STOP_STATION = (28.6309, 60.3634)   # станция Приморск (ТПУ)
KINDERGARTEN = (28.6535, 60.3530)   # детсад 160 мест (сценарий 2), Карасёвка — по карте презентации
STOP_KARASYOVKA = (28.6733, 60.3499)  # существующая остановка «Карасёвка» (= «кампус»)
CAMPUS_IN = (28.6852, 60.3478)      # вход в кампус от прибрежной дороги
JCT_PORT = (28.7342, 60.3542)       # примыкание подъезда к порту
STOP_PORT = (28.7355, 60.3500)      # порт
KIRCHE = (28.6057, 60.3642)
GAGARINA_E = (28.6532, 60.3550)     # восточный конец наб. Юрия Гагарина

PIER_PLACES = 40        # концепция: 30–40; презентация: 40
COLLEGE_CAPACITY = 300  # презентация: колледж на 300 мест


def build_road_graph() -> tuple[nx.Graph, dict[int, Point]]:
    """Граф УДС: узлы — вершины линий (сшитые с допуском), рёбра — отрезки линий."""
    roads = gpd.read_file(ROOT / "data" / "processed" / "roads.geojson").cx[CORRIDOR[0]:CORRIDOR[2],
                                                                             CORRIDOR[1]:CORRIDOR[3]]
    planned = gpd.read_file(ROOT / "data" / "processed" / "scenario" / "roads.geojson")
    lines = list(roads.geometry.explode(index_parts=False).geometry) + \
        list(planned.geometry.explode(index_parts=False).geometry)
    lines = [shapely.line_merge(l) if l.geom_type == "MultiLineString" else l for l in lines]

    coords: list[tuple[float, float]] = []   # узлы в метрах (MCRS)
    edges: list[tuple[int, int]] = []
    remap: dict[tuple[float, float], int] = {}
    gs = gpd.GeoSeries(lines, crs=CRS).to_crs(MCRS)
    for line in gs.geometry:
        pts = [tuple(c) for c in line.coords]
        ids = []
        for p in pts:
            key = (round(p[0] / 2) * 2, round(p[1] / 2) * 2)   # сетка 2 м
            if key not in remap:
                remap[key] = len(coords)
                coords.append((p[0], p[1]))
            ids.append(remap[key])
        edges += [(ids[i], ids[i + 1]) for i in range(len(ids) - 1)]

    # сшивка разрывов: узлы ближе NODE_TOL — один узел (union-find)
    arr = np.array(coords)
    tree = cKDTree(arr)
    parent = list(range(len(coords)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j in tree.query_pairs(NODE_TOL):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)

    g = nx.Graph()
    node_pos: dict[int, tuple[float, float]] = {}
    for i, (x, y) in enumerate(coords):
        r = find(i)
        node_pos.setdefault(r, (x, y))
    for i, j in edges:
        a, b = find(i), find(j)
        if a == b:
            continue
        (x1, y1), (x2, y2) = node_pos[a], node_pos[b]
        d = ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5
        if not g.has_edge(a, b) or g[a][b]["weight"] > d:
            g.add_edge(a, b, weight=d)
    print(f"  граф УДС: {g.number_of_nodes()} узлов, {g.number_of_edges()} рёбер, "
          f"{nx.number_connected_components(g)} компонент связности")
    return g, {n: Point(xy) for n, xy in node_pos.items()}


def route(g: nx.Graph, nodes_pos: dict, pts: list[tuple[float, float]],
          name: str) -> LineString:
    """Кратчайший путь по сети через опорные точки (MCRS → CRS)."""
    tree = cKDTree(np.array([list(nodes_pos[n].coords[0]) for n in g.nodes]))
    node_list = list(g.nodes)
    full: list[int] = []
    targets = [min(g.nodes, key=lambda n: nodes_pos[n].distance(
        gpd.GeoSeries([Point(p)], crs=CRS).to_crs(MCRS).iloc[0])) for p in pts]
    for a, b in zip(targets, targets[1:]):
        seg = nx.shortest_path(g, a, b, weight="weight")
        full += seg if not full else seg[1:]
    coords_m = [nodes_pos[n].coords[0] for n in full]
    line_m = LineString(coords_m)
    line = gpd.GeoSeries([line_m], crs=MCRS).to_crs(CRS).iloc[0]
    km = line_m.length / 1000
    print(f"  {name}: {km:.2f} км (по {len(pts)} опорным точкам)")
    return line, km


def write_gj(features: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features},
                               ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  {path.relative_to(ROOT)}: {len(features)} объект(ов)")


def fline(name: str, line: LineString) -> dict:
    return {"type": "Feature", "properties": {"name": name},
            "geometry": line.__geo_interface__}


def main() -> None:
    water = gpd.read_file(ROOT / "data" / "processed" / "water.geojson").union_all()
    bay = gpd.read_file(ROOT / "data" / "processed" / "bay.geojson").union_all()
    aqua = water.union(bay)
    marina = gpd.read_file(ROOT / "data" / "processed" / "scenario" / "boundary.geojson").geometry.iloc[1]
    settl = gpd.read_file(ROOT / "data" / "processed" / "boundary.geojson").union_all()

    print("Черновики проектных слоёв →", OUT.relative_to(ROOT))
    g, nodes = build_road_graph()

    # --- маршруты по улично-дорожной сети ---------------------------------------
    shuttle_line, shuttle_km = route(g, nodes, [STOP_CENTER, STOP_STATION, KINDERGARTEN,
                                                STOP_KARASYOVKA, CAMPUS_IN, JCT_PORT, STOP_PORT],
                                     "Шаттл центр — станция — кампус — порт")
    cyc_line, cyc_km = route(g, nodes, [STOP_CENTER, KINDERGARTEN, STOP_KARASYOVKA, CAMPUS_IN],
                             "Велодорожка центр — кампус")
    ped_center, ped1 = route(g, nodes, [STOP_CENTER, KIRCHE, (28.6063, 60.3661)],
                             "Пешеходный: исторический центр")
    ped_gag, ped2 = route(g, nodes, [(28.6198, 60.3629), GAGARINA_E],
                          "Пешеходный: наб. Юрия Гагарина")
    ped_tpu, ped3 = route(g, nodes, [STOP_STATION, STOP_CENTER],
                          "Пешеходный: ТПУ — центр")
    total_ped = ped1 + ped2 + ped3
    print(f"  пешеходные суммарно: {total_ped:.2f} км (цель ≈ 4,7)")

    write_gj([fline(f"Шаттл: центр — станция — кампус — порт ({shuttle_km:.1f} км)", shuttle_line)],
             OUT / "shuttle.geojson")
    write_gj([fline(f"Велодорожка: центр — кампус ({cyc_km:.1f} км)", cyc_line)], OUT / "cycleway.geojson")
    write_gj([
        fline("Исторический центр: марина — кирха — наб. Лебедева", ped_center),
        fline("Набережная: центр — восточные пляжи (Юрия Гагарина наб.)", ped_gag),
        fline("ТПУ — центр", ped_tpu),
    ], OUT / "pedestrian.geojson")

    # --- остановки шаттла (существующая «Карасёвка» = «кампус» уже в bus_stop) ----
    stops = [{"type": "Feature",
              "properties": {"service_name": "Остановка шаттла", "capacity": 0, "name": nm},
              "geometry": Point(x, y).__geo_interface__}
             for nm, (x, y) in (("Шаттл: центр", STOP_CENTER), ("Шаттл: станция", STOP_STATION),
                                ("Шаттл: порт", STOP_PORT))]
    write_gj(stops, OUT / "bus_stop_shuttle.geojson")

    # --- парковка ТПУ и детсад -----------------------------------------------------
    write_gj([{"type": "Feature",
               "properties": {"service_name": "Парковка ТПУ (100 мест)", "capacity": 0},
               "geometry": Point(*STOP_STATION).__geo_interface__}], OUT / "parking.geojson")
    write_gj([{"type": "Feature",
               "properties": {"service_name": "Детский сад (сценарий 2)", "capacity": 160,
                              "name": "Детский сад, 160 мест (участок в Карасёвке, 0,62 га)"},
               "geometry": Point(*KINDERGARTEN).__geo_interface__}], OUT / "kindergarten.geojson")

    # --- причалы: 2 понтона × 20 мест, перпендикулярно берегу в акваторию ----------
    piers: list[dict] = []
    for p_name, x0 in (("Понтон западный", 28.6080), ("Понтон восточный", 28.6098)):
        ring = marina.geoms[0].exterior if marina.geom_type == "MultiPolygon" else marina.exterior
        edge = min(y for x, y in ring.coords if abs(x - x0) < 0.0004)
        lat = edge
        while not aqua.contains(Point(x0, lat)):
            lat -= 2 / 111_000               # шаг 2 м к воде
        lat0 = lat - 20 / 111_000            # отступ 20 м от уреза воды
        for k in range(PIER_PLACES // 2):    # шаг ~8 м
            lat = lat0 - k * 8 / 111_000
            piers.append({"type": "Feature",
                          "properties": {"service_name": "Причал", "capacity": 0,
                                         "name": f"{p_name}, место {k + 1}"},
                          "geometry": Point(x0, lat).__geo_interface__})
    for f in piers:
        assert aqua.contains(Point(f["geometry"]["coordinates"])), "причал не в акватории"
    write_gj(piers, OUT / "pier.geojson")
    print(f"  причальных мест: {len(piers)}")

    # --- контроль: слои в границе поселения ------------------------------------------
    for nm in ("cycleway", "pedestrian", "shuttle"):
        line = gpd.read_file(OUT / f"{nm}.geojson")
        if int((~line.intersects(settl)).sum()):
            print(f"  !! {nm}: линии выходят за границу поселения")
    print("Готово.")


if __name__ == "__main__":
    main()
