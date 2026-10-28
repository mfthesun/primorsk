"""
Черновая трассировка проектных слоёв сценария (транспортный проект и причалы марины) по концепции.

Маршруты прокладываются по существующему графу (scripts/roadgraph.py) кратчайшим путём между опорными
точками; парковка ТПУ и причалы — простая геометрия у станции и у берега территории марины.
Результат — data/raw/scenario_design/*.geojson: это исходник «проектное решение», его можно
поправить руками в QGIS; process.py забирает его в data/processed/scenario/.

Запуск (один раз или после смены опорных точек): python scripts/scenario_design.py
"""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import shapely
from shapely.geometry import LineString, Point, box

from roadgraph import MCRS, build_graph, largest_component, load_network, nearest_node, path_line

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "scenario_design"
PROC = ROOT / "data" / "processed"

# опорные точки, EPSG:32635 (см. docs/scenario.md)
PTS = {
    "центр": (588638, 6693428),       # остановка «Приморск, рынок»
    "станция": (589964, 6693001),     # ж/д станция Приморск (реконструкция, ТПУ)
    "кампус": (592338, 6691557),      # остановка «Карасёвка» у кампуса
    "порт": (594950, 6690540),        # въезд в порт (парковка у КПП)
    "кирха": (588551, 6693082),       # кирха св. Марии Магдалины
    "марина": (588694, 6693041),      # территория #1
    "парусная школа": (589442, 6692493),  # территория #2
}
SHUTTLE = ["центр", "станция", "кампус", "порт"]            # концепция: остановки «центр», «кампус», «порт»
CYCLE = [["марина", "станция", "кампус"]]                    # 4,5–5 км
FOOT = [["центр", "кирха", "марина", "парусная школа"],      # набережная
        ["станция", "парусная школа"]]                       # станция — берег
PARKING_PLACES = 100
PARKING_M2_PER_PLACE = 25.0
PIERS, PIER_LEN, BERTHS_PER_PIER = 4, 60.0, 10               # 40 причальных мест
PIER_GAP = 25.0                                              # м между причалами


def route(G: nx.Graph, names: list[str]) -> LineString:
    nodes: list[int] = []
    ids = [nearest_node(G, *PTS[n]) for n in names]
    for a, b in zip(ids[:-1], ids[1:]):
        p = nx.shortest_path(G, a, b, weight="length_meter")
        nodes.extend(p if not nodes else p[1:])
    return path_line(G, nodes)


def lines_gdf(items: list[tuple[str, LineString]], kind: str) -> gpd.GeoDataFrame:
    g = gpd.GeoDataFrame({"name": [n for n, _ in items], "kind": kind,
                          "highway_type": "местная", "highway_type_id": 52},
                         geometry=[l for _, l in items], crs=MCRS)
    g["length_m"] = g.length.round(0)
    return g


def parking_lot() -> gpd.GeoDataFrame:
    """Квадрат площадью 100 мест × 25 м², ближайший к станции, не задевающий здания, ж/д, дороги и воду."""
    side = float(np.sqrt(PARKING_PLACES * PARKING_M2_PER_PLACE))
    sx, sy = PTS["станция"]
    obstacles = [gpd.read_file(PROC / f"{n}.geojson").to_crs(MCRS) for n in ("building", "water", "railways")]
    roads = gpd.read_file(PROC / "roads.geojson").to_crs(MCRS)
    win = box(sx - 400, sy - 400, sx + 400, sy + 400)
    obst = shapely.union_all([o[o.intersects(win)].buffer(5 if i < 2 else 15).union_all()
                              for i, o in enumerate(obstacles)] + [roads[roads.intersects(win)].buffer(4).union_all()])
    best = None
    for r in np.arange(40, 400, 10):
        for a in np.linspace(0, 2 * np.pi, 36, endpoint=False):
            cx, cy = sx + r * np.cos(a), sy + r * np.sin(a)
            sq = box(cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2)
            if not sq.intersects(obst):
                best = sq
                break
        if best is not None:
            break
    return gpd.GeoDataFrame({"name": ["Парковка ТПУ «Приморск»"], "places": [PARKING_PLACES]},
                            geometry=[best], crs=MCRS)


def piers() -> gpd.GeoDataFrame:
    terr = gpd.read_file(PROC / "scenario" / "boundary.geojson").to_crs(MCRS).geometry.iloc[1]   # марина
    water = gpd.read_file(PROC / "water.geojson").to_crs(MCRS)
    sea = water[water.intersects(terr.buffer(50))].union_all()
    shore = sea.boundary.intersection(terr.buffer(20))       # береговая линия в пределах участка
    shore = shapely.line_merge(shore) if shore.geom_type == "MultiLineString" else shore
    if shore.geom_type == "MultiLineString":
        shore = max(shore.geoms, key=lambda x: x.length)
    # кандидаты через 5 м вдоль берега; берём причалы, целиком лежащие в воде, не ближе PIER_GAP друг к другу
    cands = []
    for d in np.arange(2, shore.length - 2, 5.0):
        p, q = shore.interpolate(d - 1), shore.interpolate(d + 1)
        nx_, ny_ = -(q.y - p.y), q.x - p.x                       # нормаль к берегу
        norm = np.hypot(nx_, ny_)
        nx_, ny_ = nx_ / norm, ny_ / norm
        o = shore.interpolate(d)
        if not sea.contains(Point(o.x + 10 * nx_, o.y + 10 * ny_)):   # нормаль — в сторону воды
            nx_, ny_ = -nx_, -ny_
        line = LineString([(o.x, o.y), (o.x + PIER_LEN * nx_, o.y + PIER_LEN * ny_)])
        cands.append((line.intersection(sea).length, d, line))
    chosen: list = []
    for wet, d, line in sorted(cands, key=lambda c: -c[0]):
        if wet >= 0.95 * PIER_LEN and all(abs(d - c[0]) >= PIER_GAP for c in chosen) and \
                all(line.distance(c[1]) >= PIER_GAP / 2 for c in chosen):
            chosen.append((d, line))
        if len(chosen) == PIERS:
            break
    rows = [{"name": f"Понтонный причал {k + 1}", "berths": BERTHS_PER_PIER, "geometry": line}
            for k, (_, line) in enumerate(sorted(chosen, key=lambda c: c[0]))]
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=MCRS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    net = load_network()
    drive = largest_component(build_graph(net, "drive"))
    walk = largest_component(build_graph(net, "walk"))

    shuttle = lines_gdf([("Шаттл: " + " – ".join(SHUTTLE), route(drive, SHUTTLE))], "shuttle")
    cycle = lines_gdf([("Велодорожка: " + " – ".join(c), route(walk, c)) for c in CYCLE], "cycleway")
    foot = lines_gdf([("Пешеходный маршрут: " + " – ".join(f), route(walk, f)) for f in FOOT], "footway")
    stops = gpd.GeoDataFrame({"name": [f"Шаттл: {n}" for n in SHUTTLE]},
                             geometry=[Point(PTS[n]) for n in SHUTTLE], crs=MCRS)
    out = {"shuttle_route": shuttle, "cycleway": cycle, "footway": foot, "shuttle_stop": stops,
           "parking": parking_lot(), "pier": piers()}
    for name, g in out.items():
        p = OUT / f"{name}.geojson"
        if p.exists():
            p.unlink()
        g.to_crs(4326).to_file(p, driver="GeoJSON", engine="pyogrio")
    for name in ("shuttle_route", "cycleway", "footway"):
        print(name, out[name][["name", "length_m"]].to_string(index=False, header=False))
    print("parking", round(out["parking"].area.iloc[0]), "м²;", "pier", int(out["pier"]["berths"].sum()), "мест")


if __name__ == "__main__":
    main()
