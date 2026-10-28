"""
Предпроектный анализ «было» (раздел 1 мастер-плана) на BlocksNet 1.0.0a9.

1. Агрегация зданий и сервисов по кварталам: население, площади, FSI/GSI/MXI, Spacematrix.
2. Граф УДС (scripts/roadgraph.py: roads.geojson + дополнение разрывов по data/raw/osm_roads.geojson),
   матрицы доступности кварталов (пешком и на автомобиле), median_accessibility, время до станции и центра.
3. Конкурентная обеспеченность школами и детскими садами (competitive_provision) → таблица
   «норматив / обеспечено / дефицит / избыток», в т. ч. по населённым пунктам.
4. Охват населения прочими социальными сервисами (поликлиника/ФАП, аптека, почта, МФЦ…) по времени.

Окружение — .venv-blocksnet (scripts/setup.sh). Интернет не нужен.
Запуск: .venv-blocksnet/bin/python scripts/analysis.py [--scenario]   (--scenario — «стало», задел на этап 3)

Выход: data/processed/analysis/{blocks_before.geojson, provision_*.geojson, acc_*.pkl, graph_*.geojson},
       reports/analysis_before.md, reports/provision_before.csv, reports/provision_by_locality.csv
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
from roadgraph import MCRS, build_graph, edges_gdf, graph_summary, largest_component, load_network  # noqa: E402

from loguru import logger  # noqa: E402

logger.remove()
logger.add(sys.stderr, level="WARNING")

from blocksnet.analysis.indicators.density import calculate_density_indicators  # noqa: E402
from blocksnet.analysis.morphotypes import get_spacematrix_morphotypes  # noqa: E402
from blocksnet.analysis.network.accessibility import median_accessibility  # noqa: E402
from blocksnet.analysis.provision import competitive_provision  # noqa: E402
from blocksnet.blocks.aggregation import aggregate_objects  # noqa: E402
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
         "train_station": "Ж/д станции"}
STATION = (589964, 6693001)      # ж/д станция Приморск
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
def load_blocks(scenario: bool) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    blocks = read(PROC / "blocks.geojson")[["geometry"]].reset_index(drop=True)
    blocks["site_area"] = blocks.area
    bld = read(PROC / "building.geojson")
    if scenario:
        sb = read(PROC / "scenario" / "building.geojson")
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


# =============================================================================
def graphs() -> tuple[dict, dict]:
    net = load_network()
    out, info = {}, {}
    for mode in ("walk", "drive"):
        G = build_graph(net, mode)
        info[mode] = graph_summary(G)
        G = largest_component(G)
        validate_accessibility_graph(G, "time_min")
        out[mode] = G.to_directed()       # IduEdu ждёт ориентированный граф
        e = edges_gdf(G).to_crs(4326)
        e.to_file(OUT / f"graph_{mode}.geojson", driver="GeoJSON", engine="pyogrio")
    roads_only = build_graph(load_network(include_osm=False), "drive")
    info["roads_only"] = graph_summary(roads_only)
    return out, info


def anchors(blocks: gpd.GeoDataFrame, bld: gpd.GeoDataFrame) -> gpd.GeoSeries:
    """Точка квартала для матрицы: центр застройки (взвешенный по общей площади зданий; ближайшее к нему
    здание, чтобы точка не попала в воду/лес). Кварталы курса крупные (до сотен га с лесом), и
    representative_point() может лежать в километре от домов. Без зданий — representative_point()."""
    pts = gpd.GeoDataFrame({"w": bld["build_floor_area"].clip(lower=1)}, geometry=bld.representative_point(), crs=MCRS)
    j = gpd.sjoin(pts, blocks[["geometry"]], predicate="within")
    out = blocks.representative_point()
    for k, grp in j.groupby("index_right"):
        cx = np.average(grp.geometry.x, weights=grp["w"])
        cy = np.average(grp.geometry.y, weights=grp["w"])
        d = (grp.geometry.x - cx) ** 2 + (grp.geometry.y - cy) ** 2
        out.loc[k] = grp.geometry.loc[d.idxmin()]
    return out


def matrix(G, blocks: gpd.GeoDataFrame) -> pd.DataFrame:
    pts = gpd.GeoDataFrame(geometry=blocks["anchor"], index=blocks.index, crs=MCRS)
    return calculate_accessibility_matrix(pts, G, "time_min", dtype=np.float32)


def block_of(blocks: gpd.GeoDataFrame, xy) -> int:
    p = gpd.GeoDataFrame(geometry=gpd.points_from_xy([xy[0]], [xy[1]]), crs=MCRS)
    return int(gpd.sjoin_nearest(p, blocks[["geometry"]])["index_right"].iloc[0])


# =============================================================================
def services_to_blocks(svc: str, blocks: gpd.GeoDataFrame, scenario: bool) -> gpd.GeoDataFrame:
    s = read(PROC / "services" / f"{svc}.geojson")
    sp = PROC / "scenario" / f"{svc}.geojson"
    if scenario and sp.exists():
        s = pd.concat([s, read(sp)], ignore_index=True)
    s = gpd.GeoDataFrame(s, geometry=s.representative_point(), crs=MCRS)
    j = gpd.sjoin_nearest(s, blocks[["geometry"]], how="left")
    return j[~j.index.duplicated()]


def provision(blocks: gpd.GeoDataFrame, acc: dict, scenario: bool) -> tuple[pd.DataFrame, dict]:
    rows, res = [], {}
    pop_total = int(blocks["population"].sum())
    for svc, acc_min in PROVISION.items():
        demand_k, acc_default = norm(svc)
        s = services_to_blocks(svc, blocks, scenario)
        cap = s.groupby("index_right")["capacity"].sum().reindex(blocks.index, fill_value=0).astype(int)
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


def coverage(blocks: gpd.GeoDataFrame, acc: dict, scenario: bool) -> pd.DataFrame:
    """Время от квартала до ближайшего сервиса — по матрице «квартал → квартал» (сервис — в своём квартале)."""
    rows = []
    pop = blocks["population"]
    for svc, walk_t, drive_t in COVERAGE:
        if not (PROC / "services" / f"{svc}.geojson").exists():
            continue
        s = services_to_blocks(svc, blocks, scenario)
        targets = sorted(s["index_right"].unique())
        r = {"service": svc, "Сервис": NAMES[svc], "Объектов": len(s)}
        for mode, t in (("walk", walk_t), ("drive", drive_t)):
            m = acc[mode][targets].min(axis=1)
            blocks[f"t_{mode}_{svc}"] = m.replace(np.inf, np.nan).round(1)
            if t is None:
                r[f"{mode}_min"], r[f"{mode}_share"] = None, None
                continue
            r[f"{mode}_min"] = t
            r[f"{mode}_share"] = round(float(pop[m <= t].sum() / pop.sum()), 3)
        rows.append(r)
    return pd.DataFrame(rows)


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


def main() -> None:
    scenario = "--scenario" in sys.argv
    tag = "after" if scenario else "before"
    OUT.mkdir(parents=True, exist_ok=True)

    blocks, bld = load_blocks(scenario)
    blocks, agg_info = aggregate(blocks, bld)
    blocks, clusters = density(blocks)
    blocks["locality"] = localities(blocks, bld)
    blocks["anchor"] = anchors(blocks, bld)

    G, ginfo = graphs()
    acc = {mode: matrix(G[mode], blocks) for mode in G}
    for mode, m in acc.items():
        m.to_pickle(OUT / f"acc_{mode}_{tag}.pkl")
        blocks[f"median_acc_{mode}"] = median_accessibility(m)["median_accessibility"].round(1)
        for name, xy in (("station", STATION), ("centre", CENTRE)):
            blocks[f"t_{mode}_{name}"] = m[block_of(blocks, xy)].replace(np.inf, np.nan).round(1)

    prov, res = provision(blocks, acc, scenario)
    for (svc, mode), r in res.items():
        for c in ("demand", "capacity", "demand_within", "demand_without", "demand_left", "capacity_left",
                  "provision_strong", "provision_weak"):
            blocks[f"{svc}_{mode}_{c}"] = r[c]
    cov = coverage(blocks, acc, scenario)

    # по населённым пунктам: школы и детсады (транспортная доступность) + время до станции
    loc = blocks.groupby("locality").agg(population=("population", "sum"))
    for svc in PROVISION:
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

    pop = int(blocks["population"].sum())
    built = blocks[blocks["count_buildings"] > 0]
    lines = [f"# Предпроектный анализ «{'стало' if scenario else 'было'}»: кварталы, доступность, обеспеченность", "",
             "Сгенерировано `scripts/analysis.py` (BlocksNet 1.0.0a9). Таблицы — `reports/*.csv`, слои — "
             "`data/processed/analysis/`.", "",
             "## 1. Кварталы (агрегация BlocksNet)", "",
             f"- кварталов: {len(blocks)}, застроенных: {len(built)}, с жителями: {(blocks.population > 0).sum()};",
             f"- зданий: {agg_info['buildings']}, вне кварталов: {agg_info['outside_blocks']} "
             f"(население {agg_info['pop_outside']} — присоединено к ближайшему кварталу);",
             f"- население в кварталах: {pop} (`boundary.population` "
             f"{int(gpd.read_file(PROC / 'boundary.geojson')['population'].iloc[0])}"
             f"{' + жители зданий сценария' if scenario else ''});",
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
             "участками OSM (`data/raw/osm_roads.geojson`, выгружен 28.10.2026) — интернет при расчёте не нужен.", "",
             "| Граф | Узлов | Рёбер | км | Компонент | Доля крупнейшей | км по источникам |", "|---|---|---|---|---|---|---|"]
    for k, v in ginfo.items():
        lines.append(f"| {'только roads.geojson' if k == 'roads_only' else k} | {v['nodes']} | {v['edges']} | {v['km']} | "
                     f"{v['components']} | {v['largest_share']:.0%} | {v['km_by_source']} |")
    wpop = lambda c: float((blocks[c] * blocks.population).sum() / pop)  # noqa: E731
    lines += ["", "Скорости: пешком 5 км/ч; авто — по категории улицы генплана (региональные 70, улицы в жилой "
              "застройке 20 км/ч, грунт ×0,7) и по `highway` OSM. Время до первого узла — пешком.", "",
              f"- `median_accessibility` (медианное время до остальных кварталов), взвешенное по населению: "
              f"авто {wpop('median_acc_drive'):.0f} мин, пешком {wpop('median_acc_walk'):.0f} мин;",
              f"- среднее время до ж/д станции Приморск: авто {wpop('t_drive_station'):.0f} мин, пешком "
              f"{wpop('t_walk_station'):.0f} мин; до центра Приморска: авто {wpop('t_drive_centre'):.0f} мин;",
              f"- жителей в 20 мин пешком от станции: {blocks.loc[blocks.t_walk_station <= 20, 'population'].sum() / pop:.0%}.",
              "", "## 3. Обеспеченность школами и детскими садами (competitive_provision)", "",
              "Норматив и доступность — `service_types_config` BlocksNet (школа 120 мест/1000 жит., 15 мин; детский "
              "сад 61/1000, 7 мин) — пешком; для сельского поселения добавлен вариант с подвозом (школа 30 мин, "
              "детсад 15 мин на транспорте). Потребность распределена по кварталам пропорционально населению; "
              "вместимость — `capacity` (сайты учреждений). «Обеспечено за пределами» — места, полученные за "
              "пределами нормативной доступности (до 3× норматива).", "",
              md_table(prov.drop(columns=["service"])), "",
              "По населённым пунктам (доля потребности, обеспеченная в нормативной доступности; время до станции на авто):", "",
              md_table(loc.reset_index().rename(columns={
                  "locality": "Населённый пункт", "population": "Население", "school_walk": "Школы пешком",
                  "school_drive": "Школы с подвозом", "kindergarten_walk": "Детсады пешком",
                  "kindergarten_drive": "Детсады транспорт", "t_drive_station": "До станции, мин"})),
              "", "## 4. Охват населения прочими сервисами (доля жителей в пределах времени)", "",
              md_table(cov.drop(columns=["service"]).rename(columns={
                  "walk_min": "пешком, мин", "walk_share": "Доля пешком", "drive_min": "авто, мин",
                  "drive_share": "Доля авто"})), ""]
    (REP / f"analysis_{tag}.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
