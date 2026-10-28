"""
Климатические метрики для обоснования проектов марины, парусной школы, катка и набережной
(дополнительные показатели к библиотекам ИДУ).

Данные: реанализ ERA5 через Open-Meteo (data/raw/climate_openmeteo_*.csv, 2015–2024, ячейка у берега Приморска;
выгружены один раз, скрипт в интернет не ходит).

Метрики:
- парусный сезон (май–сентябрь): дни, когда средний дневной ветер (10–19 ч) 3–10 м/с и порывы < 15 м/с —
  пригодно для учебных занятий парусной школы (швертботы, яхты класса «Кадет»/«Оптимист» — до 8–10 м/с);
- ледовый сезон: дни со среднесуточной температурой < −5 °C и длина непрерывного морозного периода —
  потенциал буеров, снегоходов и естественного катка (концепция: «прокат буеров/снегоходов, каток»);
- ветровая нагрузка: максимальный за 10 лет порыв и скоростной напор q = ρv²/2 — сопоставление с нормативным
  давлением ветра w0 по СП 20.13330.2016 (II ветровой район, w0 = 0,30 кПа, как для Санкт-Петербурга — уточнить по карте СП 20.13330, прил. Е) для причалов и
  лёгких конструкций марины;
- ветровой комфорт набережной: доля дневных часов с ветром > 5 м/с (критерий Лоусона для прогулок).

Запуск: python scripts/climate.py → reports/metrics/climate.json, reports/climate.md, reports/charts/wind_rose.png
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
REP = ROOT / "reports"
RHO = 1.25            # кг/м³
W0_KPA = 0.30         # СП 20.13330.2016, II ветровой район
SAIL = (3.0, 10.0)    # м/с, учебные занятия
GUST_MAX = 15.0
COMFORT = 5.0         # м/с


def main() -> dict:
    h = pd.read_csv(RAW / "climate_openmeteo_hourly.csv.gz", parse_dates=["time"])
    d = pd.read_csv(RAW / "climate_openmeteo_daily.csv", parse_dates=["time"])
    h["date"] = h["time"].dt.date
    h["year"] = h["time"].dt.year
    day = h[h["time"].dt.hour.between(10, 19)]
    daily = day.groupby("date").agg(wind=("wind_speed_10m", "mean"), gust=("wind_gusts_10m", "max"))
    daily.index = pd.to_datetime(daily.index)
    season = daily[daily.index.month.isin([5, 6, 7, 8, 9])]
    ok = season[(season.wind.between(*SAIL)) & (season.gust < GUST_MAX)]
    years = sorted(h["year"].unique())
    sail_days = ok.groupby(ok.index.year).size().reindex(years, fill_value=0)

    tmean = h.groupby("date")["temperature_2m"].mean()
    tmean.index = pd.to_datetime(tmean.index)
    frost = tmean < -5
    # зима = ноябрь–март; год зимы — по январю
    wy = tmean.index.year + (tmean.index.month >= 11)
    frost_days = frost.groupby(wy).sum()
    frost_days = frost_days[(frost_days.index > years[0]) & (frost_days.index <= years[-1])]
    below0 = (tmean < 0).groupby(wy).sum()
    below0 = below0[below0.index.isin(frost_days.index)]

    def longest(s):
        best = cur = 0
        for v in s:
            cur = cur + 1 if v else 0
            best = max(best, cur)
        return best
    run_len = (tmean < 0).groupby(wy).apply(longest)
    run_len = run_len[run_len.index.isin(frost_days.index)]

    gmax = float(h["wind_gusts_10m"].max())
    q = RHO * gmax ** 2 / 2 / 1000
    vmax = float(h["wind_speed_10m"].max())          # максимальная средняя (часовая) скорость
    q_mean = RHO * vmax ** 2 / 2 / 1000
    comfort = float((day["wind_speed_10m"] > COMFORT).mean())
    dirs = h["wind_direction_10m"]
    sector = ((dirs + 22.5) // 45 % 8).astype(int)
    names = ["С", "СВ", "В", "ЮВ", "Ю", "ЮЗ", "З", "СЗ"]
    rose = sector.value_counts(normalize=True).sort_index()
    rose.index = [names[i] for i in rose.index]

    m = {
        "period": f"{years[0]}–{years[-1]}",
        "sail_days_mean": float(sail_days.mean()), "sail_days_min": int(sail_days.min()),
        "sail_days_max": int(sail_days.max()), "sail_season_days": 153,
        "frost_days_mean": float(frost_days.mean()), "frost_days_min": int(frost_days.min()),
        "below0_days_mean": float(below0.mean()), "longest_frost_run_mean": float(run_len.mean()),
        "gust_max_ms": gmax, "q_gust_kpa": q, "w0_kpa": W0_KPA, "wind_mean_max_ms": vmax, "q_mean_kpa": q_mean,
        "windy_daytime_share": comfort, "wind_mean_ms": float(h["wind_speed_10m"].mean()),
        "prevailing": rose.idxmax(), "rose": rose.round(3).to_dict(),
        "sunshine_hours_summer": float(d[d.time.dt.month.isin([6, 7, 8])].groupby(d.time.dt.year)[
            "sunshine_duration"].sum().mean() / 3600),
    }
    (REP / "metrics").mkdir(parents=True, exist_ok=True)
    (REP / "metrics" / "climate.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")

    # роза ветров
    (REP / "charts").mkdir(parents=True, exist_ok=True)
    fig = plt.figure(figsize=(5, 5))
    ax = fig.add_subplot(projection="polar")
    ang = np.deg2rad(np.arange(0, 360, 45))
    ax.bar(ang, [rose.get(n, 0) * 100 for n in names], width=np.deg2rad(40), color="#4c78a8", edgecolor="white")
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_xticks(ang)
    ax.set_xticklabels(names)
    ax.set_yticklabels([])
    for a, n in zip(ang, names):
        ax.text(a, rose.get(n, 0) * 100 + 1.2, f"{rose.get(n, 0) * 100:.0f} %", ha="center", fontsize=8)
    fig.savefig(REP / "charts" / "wind_rose.png", dpi=200, bbox_inches="tight")
    plt.close(fig)

    lines = ["# Климатические метрики (ERA5 / Open-Meteo, " + m["period"] + ")", "",
             "| Метрика | Значение | Для чего |", "|---|---|---|",
             f"| Дни, пригодные для парусных занятий (май–сентябрь, ветер {SAIL[0]:g}–{SAIL[1]:g} м/с днём, порывы < "
             f"{GUST_MAX:g} м/с) | {m['sail_days_mean']:.0f} из 153 (от {m['sail_days_min']} до {m['sail_days_max']}) | "
             "парусная школа, прокат: загрузка сезона |",
             f"| Дни со среднесуточной температурой < −5 °C (зима) | {m['frost_days_mean']:.0f} | буеры, снегоходы |",
             f"| Дни с температурой < 0 °C / самый длинный морозный период | {m['below0_days_mean']:.0f} / "
             f"{m['longest_frost_run_mean']:.0f} дн. | естественный каток, круглогодичность марины |",
             f"| Максимальная средняя скорость ветра за 10 лет / скоростной напор | {m['wind_mean_max_ms']:.1f} м/с / "
             f"{m['q_mean_kpa']:.2f} кПа (норматив w0 = {W0_KPA} кПа — по средней скорости, повторяемость раз в 50 лет) "
             "| ветровая нагрузка на причалы и лёгкие павильоны |",
             f"| Максимальный порыв за 10 лет | {m['gust_max_ms']:.1f} м/с ({m['q_gust_kpa']:.2f} кПа) | крепление понтонов, "
             "штормовые ограничения проката |",
             f"| Доля дневных часов с ветром > {COMFORT:g} м/с | {m['windy_daytime_share']:.0%} | ветровой комфорт "
             "набережной, защита пешеходных маршрутов |",
             f"| Преобладающее направление ветра | {m['prevailing']} | ориентация причалов, ветрозащита |",
             f"| Солнечных часов за лето (июнь–август) | {m['sunshine_hours_summer']:.0f} | пляжный и водный туризм |",
             "", "Роза ветров — `reports/charts/wind_rose.png`. Ячейка ERA5 ≈ 60,42° N, 28,59° E (акватория у Приморска).", ""]
    (REP / "climate.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return m


if __name__ == "__main__":
    main()
