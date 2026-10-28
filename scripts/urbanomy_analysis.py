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
# цена земли проекта, руб./м²: средневзвешенная кадастровая стоимость участков НСПД (data/raw/cadastral_parcels.csv);
# если участков проекта нет — значение из urbanomy_inputs.json
_cad = pd.read_csv(ROOT / "data" / "raw" / "cadastral_parcels.csv").groupby("project")[["area_m2", "cadastral_value_rub"]].sum()
LAND_PRICE = {**{k: float(v or 0) for k, v in INPUTS["land_price_rub_m2"].items() if not k.startswith("_")},
              **(_cad["cadastral_value_rub"] / _cad["area_m2"]).to_dict()}
PROJECT_NAME = {"campus": "Кампус ИНТЦ", "marina": "Марина", "kindergarten": "Детский сад"}
# здания сценария вне территорий проектов: id → (проект, участок из data/raw/scenario_design)
OWN_SITE = {29: ("kindergarten", "kindergarten_site")}


def project_input(phase: int) -> gpd.GeoDataFrame:
    """Строки «проект × назначение»: суммарные площади зданий сценария, доля участка по площади зданий."""
    b = scenario_layer("building", phase)
    terr = gpd.read_file(PROC / "scenario" / "boundary.geojson").to_crs(MCRS)
    pts = gpd.GeoDataFrame(b, geometry=b.representative_point(), crs=MCRS)
    j = gpd.sjoin_nearest(pts, terr[["geometry"]], how="left")
    j = j[~j.index.duplicated()]
    b["project"] = j["index_right"].map(PROJECT_OF_TERRITORY)
    sites = {}
    for bid, (proj, site_layer) in OWN_SITE.items():
        b.loc[b["id"] == bid, "project"] = proj
        sites[proj] = float(gpd.read_file(ROOT / "data" / "raw" / "scenario_design" / f"{site_layer}.geojson")
                            .to_crs(MCRS).area.sum())
    b["land_use"] = b["id"].map(BUILDING_USE).fillna(DEFAULT_USE)
    rows = []
    for (proj, lu), g in b.groupby(["project", "land_use"]):
        site = sites.get(proj) or terr.loc[[k for k, v in PROJECT_OF_TERRITORY.items() if v == proj]].area.sum()
        share_gfa = g["build_floor_area"].sum() / b.loc[b["project"] == proj, "build_floor_area"].sum()
        land_area = float(site * share_gfa)
        price = LAND_PRICE.get(proj, 0.0)
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
        allout.append(pd.DataFrame(o.drop(columns="geometry")).assign(project=proj))
    df = pd.concat(allout, ignore_index=True)
    emp = INPUTS["ser"].get("employment_base") or int(pop * INPUTS["ser"]["employment_share"])
    est = SEREstimator({"population": pop, "employment_base": int(emp),
                        "avg_wage_base": INPUTS["ser"]["avg_wage_base"]})
    ser = est.compute(df, pretty=False)
    res["ser"] = ser.to_dict(orient="records")
    jobs_m2 = DEFAULT_SER_PARAMETERS["jobs_per_m2"]
    df["jobs"] = df["built_area"] * df["land_use"].map(lambda lu: jobs_m2.get(lu, jobs_m2["default"]))
    res["jobs"] = {lu: float(v) for lu, v in df.groupby("land_use")["jobs"].sum().items()}
    res["jobs_by_project"] = {p: float(v) for p, v in df.groupby("project")["jobs"].sum().items()}
    res["investment_by_project"] = {p: float(v) for p, v in df.groupby("project")["investment_need"].sum().items()}
    res["jobs_total"] = float(df["jobs"].sum())
    res["investment_need_total"] = float(df["investment_need"].sum())
    (REP / "metrics").mkdir(parents=True, exist_ok=True)
    (REP / "metrics" / f"urbanomy_{tag}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str),
                                                         encoding="utf-8")
    print(tag, "инвестиции, млн ₽:", round(res["investment_need_total"] / 1e6, 1), "рабочих мест:",
          round(res["jobs_total"]))
    return res


def report(results: list[dict]) -> None:
    lines = ["# Urbanomy: инвестиции и социально-экономический эффект", "",
             "Сгенерировано `scripts/urbanomy_analysis.py`. Бенчмарки — `data/raw/urbanomy_inputs.json` "
             "(демо-значения Urbanomy по СПб); цена земли — кадастровая стоимость участков НСПД "
             "(`data/raw/cadastral_parcels.csv`): " + ", ".join(f"{PROJECT_NAME[k]} {v:,.0f} ₽/м²".replace(",", " ")
                                                              for k, v in LAND_PRICE.items() if k in PROJECT_NAME) + ".", ""]
    for r in results:
        lines += [f"## {r['name']}", "", "| Проект | Инвестиции, млн ₽ | NPV, млн ₽ | IRR | Окупаемость, лет |",
                  "|---|---|---|---|---|"]
        for proj, p in r["projects"].items():
            t = p["total"]
            f = lambda k, d=1e6: (f"{float(t[k]) / d:,.1f}".replace(",", " ") if k in t and pd.notna(t[k]) and t[k] != "nan" else "—")  # noqa: E731
            lines.append(f"| {PROJECT_NAME[proj]} | {f('investment_need')} | {f('NPV')} | {f('IRR', 0.01)} % | "
                         f"{f('PP_years', 1)} |")
        jp = r["jobs_by_project"]
        lines += ["", f"Рабочих мест (нормы Urbanomy `jobs_per_m2`): {r['jobs_total']:.0f} — кампус "
                  f"{jp.get('campus', 0):.0f}, марина {jp.get('marina', 0):.0f} (для RECREATION норма 0)"
                  + (f", детский сад {jp['kindergarten']:.0f}" if "kindergarten" in jp else ""), "",
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
