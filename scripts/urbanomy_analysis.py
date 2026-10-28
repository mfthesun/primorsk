"""
Urbanomy: инвестиционные метрики проектов (кампус, марина) и социально-экономический эффект по сценариям.

Urbanomy (IDUclub/urbanomy) нет на PyPI; scripts/setup.sh кладёт репозиторий на закреплённом коммите в
.venv-blocksnet/src/urbanomy и подключает его src. Используются модули без зависимости от BlocksNet 1.0.0a1:
- InvestmentAttractivenessAnalyzer.calculate_investment_metrics — NPV, IRR, ROI, срок окупаемости,
  потребность в инвестициях по назначению зданий (бенчмарки — data/raw/urbanomy_inputs.json);
- SEREstimator.compute — Δ инвестиций на душу, ВРП на душу, доходов бюджета, средней зарплаты, износа ОФ.
Оценка стоимости земли (LandPriceEstimator) не выполняется: нужна обученная модель CatBoost
(в репозитории её нет) и BlocksNet 1.0.0a1 / Python 3.10 — см. docs/review_comments.md.

Окружение — .venv-blocksnet. Запуск: .venv-blocksnet/bin/python scripts/urbanomy_analysis.py
Выход: reports/metrics/urbanomy_<tag>.json, reports/urbanomy.md
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import geopandas as gpd
import pandas as pd

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from roadgraph import MCRS, scenario_layer  # noqa: E402
from scenarios import BUILDING_USE, DEFAULT_USE, SCENARIOS  # noqa: E402

from urbanomy.methods.investment_potential import InvestmentAttractivenessAnalyzer  # noqa: E402
from urbanomy.methods.socio_economic_indicators.constants import DEFAULT_SER_PARAMETERS  # noqa: E402
from urbanomy.methods.socio_economic_indicators.sei_calculate import SEREstimator  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
REP = ROOT / "reports"
INPUTS = json.loads((ROOT / "data" / "raw" / "urbanomy_inputs.json").read_text(encoding="utf-8"))
PROJECT_OF_TERRITORY = {0: "campus", 1: "marina", 2: "marina"}
PROJECT_NAME = {"campus": "Кампус ИНТЦ", "marina": "Марина"}


def project_input(phase: int) -> gpd.GeoDataFrame:
    """Строки «проект × назначение»: суммарные площади зданий сценария, доля участка по площади зданий."""
    b = scenario_layer("building", phase)
    terr = gpd.read_file(PROC / "scenario" / "boundary.geojson").to_crs(MCRS)
    pts = gpd.GeoDataFrame(b, geometry=b.representative_point(), crs=MCRS)
    j = gpd.sjoin_nearest(pts, terr[["geometry"]], how="left")
    j = j[~j.index.duplicated()]
    b["project"] = j["index_right"].map(PROJECT_OF_TERRITORY)
    b["land_use"] = b["id"].map(BUILDING_USE).fillna(DEFAULT_USE)
    rows = []
    for (proj, lu), g in b.groupby(["project", "land_use"]):
        site = terr.loc[[k for k, v in PROJECT_OF_TERRITORY.items() if v == proj]].area.sum()
        share_gfa = g["build_floor_area"].sum() / b.loc[b.project == proj, "build_floor_area"].sum()
        land_area = float(site * share_gfa)
        price = float(INPUTS["land_price_rub_m2"].get(proj, 0) or 0)
        rows.append({"project": proj, "land_use": lu, "site_area": land_area, "price_pred": price * land_area,
                     "living_area": float(g["living_area"].sum()), "non_living_area": float(g["non_living_area"].sum()),
                     "build_floor_area": float(g["build_floor_area"].sum()), "share": 1.0,
                     "geometry": g.union_all().convex_hull})
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=MCRS)


def run(tag: str) -> dict | None:
    phase = SCENARIOS[tag]["phase"]
    if phase == 0:
        return None
    gdf = project_input(phase)
    bench = {k: v for k, v in INPUTS["benchmarks"].items() if not k.startswith("_")}
    an = InvestmentAttractivenessAnalyzer(benchmarks=bench)
    res = {"tag": tag, "name": SCENARIOS[tag]["name"], "projects": {}}
    for proj, g in gdf.groupby("project"):
        out, summary = an.calculate_investment_metrics(g.drop(columns="project").reset_index(drop=True))
        tot = summary.loc["project_total"].to_dict() if "project_total" in summary.index else {}
        res["projects"][proj] = {"by_use": out.drop(columns="geometry").to_dict(orient="records"),
                                 "total": {k: (float(v) if isinstance(v, (int, float)) else str(v))
                                           for k, v in tot.items()}}
    # социально-экономический эффект (SEREstimator) по всем проектам сценария
    pop = int(gpd.read_file(PROC / "boundary.geojson")["population"].iloc[0])
    allout = []
    for proj, g in gdf.groupby("project"):
        o, _ = an.calculate_investment_metrics(g.drop(columns="project").reset_index(drop=True))
        allout.append(pd.DataFrame(o.drop(columns="geometry")))
    df = pd.concat(allout, ignore_index=True)
    est = SEREstimator({"population": pop, "employment_base": int(pop * INPUTS["ser"]["employment_share"]),
                        "avg_wage_base": INPUTS["ser"]["avg_wage_base"]})
    ser = est.compute(df, pretty=False)
    res["ser"] = ser.to_dict(orient="records")
    jobs_m2 = DEFAULT_SER_PARAMETERS["jobs_per_m2"]
    res["jobs"] = {lu: float(g["built_area"].sum() * jobs_m2.get(lu, jobs_m2["default"]))
                   for lu, g in df.groupby("land_use")}
    res["jobs_total"] = float(sum(res["jobs"].values()))
    res["investment_need_total"] = float(df["investment_need"].sum())
    (REP / "metrics").mkdir(parents=True, exist_ok=True)
    (REP / "metrics" / f"urbanomy_{tag}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str),
                                                         encoding="utf-8")
    print(tag, "инвестиции, млн ₽:", round(res["investment_need_total"] / 1e6, 1), "рабочих мест:",
          round(res["jobs_total"]))
    return res


def report(results: list[dict]) -> None:
    lines = ["# Urbanomy: инвестиции и социально-экономический эффект", "",
             "Сгенерировано `scripts/urbanomy_analysis.py`. Бенчмарки и цена земли — `data/raw/urbanomy_inputs.json` "
             "(демо-значения Urbanomy по СПб; цена земли до получения кадастровой стоимости не учитывается).", ""]
    for r in results:
        lines += [f"## {r['name']}", "", "| Проект | Инвестиции, млн ₽ | NPV, млн ₽ | IRR | Окупаемость, лет |",
                  "|---|---|---|---|---|"]
        for proj, p in r["projects"].items():
            t = p["total"]
            f = lambda k, d=1e6: (f"{float(t[k]) / d:,.1f}".replace(",", " ") if k in t and t[k] not in ("nan", None) else "—")  # noqa: E731
            lines.append(f"| {PROJECT_NAME[proj]} | {f('investment_need')} | {f('NPV')} | {f('IRR', 0.01)} % | "
                         f"{f('PP_years', 1)} |")
        lines += ["", f"Рабочих мест (нормы Urbanomy `jobs_per_m2`): {r['jobs_total']:.0f}", "",
                  "| Показатель (SEREstimator) | Δ за год стройки | Δ за год эксплуатации |", "|---|---|---|"]
        for s in r["ser"]:
            fmt = lambda v: "—" if v is None or v != v else f"{v:,.0f}".replace(",", " ")  # noqa: E731
            lines.append(f"| {s['indicator']} | {fmt(s['delta_build_year'])} | {fmt(s['delta_ops_year'])} |")
        lines.append("")
    (REP / "urbanomy.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


def main() -> None:
    res = [r for r in (run(t) for t in SCENARIOS) if r]
    report(res)


if __name__ == "__main__":
    main()
