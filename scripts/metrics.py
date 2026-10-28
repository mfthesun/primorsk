"""
Сводная таблица показателей «сегодня / сценарий 1 / сценарий 2» для обоснования сценариев (раздел 4 МП, KPI 3–4).

Собирает результаты: analysis.py (BlocksNet), objectnat_analysis.py (ObjectNat), urbanomy_analysis.py (Urbanomy),
climate.py (ERA5), а также базовые показатели по слоям (население, жильё, сезонный фонд, объекты сценария).
Каждый показатель привязан к цели: цели концепции (Т — транспортная связность, К — научно-образовательный
кластер / удержание молодёжи, М — морская столица / круглогодичный туризм) и национальные цели
(Указ Президента РФ от 07.05.2024 № 309). Отдельно — показатели, которые посчитать не удалось.

Запуск: python scripts/metrics.py → reports/metrics_scenarios.md, reports/metrics_scenarios.csv,
        reports/charts/metrics_key.png
"""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

import sys  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from scenarios import SCENARIOS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
MET = ROOT / "reports" / "metrics"
REP = ROOT / "reports"
TAGS = list(SCENARIOS)
MCRS = 32635
SEASONAL_HOUSEHOLD = 2.5
# ступени одного тона: сценарии упорядочены (сегодня → 1 → 2)
COLORS = {"today": "#86b6ef", "s1": "#2a78d6", "s2": "#104281"}


def load(name: str, tag: str) -> dict | None:
    p = MET / f"{name}_{tag}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def layer(name: str, phase: int):
    p = PROC / "scenario" / f"{name}.geojson"
    if phase == 0 or not p.exists():
        return None
    x = gpd.read_file(p).to_crs(MCRS)
    x = x[x["phase"] <= phase]
    return x if len(x) else None


def base(tag: str) -> dict:
    ph = SCENARIOS[tag]["phase"]
    b = gpd.read_file(PROC / "building.geojson")
    sb = layer("building", ph)
    liv = b[b.is_living]
    pop = int(b.population.sum()) + (int(sb.population.sum()) if sb is not None else 0)
    total_housing = float(liv.build_floor_area.sum()) + (float(sb[sb.is_living].build_floor_area.sum()) if sb is not None else 0)
    km = lambda n: float(layer(n, ph).length.sum() / 1000) if layer(n, ph) is not None else 0.0  # noqa: E731
    cnt = lambda n: int(len(layer(n, ph))) if layer(n, ph) is not None else 0  # noqa: E731
    piers = layer("pier", ph)
    park = layer("parking", ph)
    college = layer("college", ph)
    sail = layer("extra_education", ph)
    return {
        "population": pop, "seasonal_houses": int(b.is_seasonal.sum()),
        "seasonal_population": round(int(b.is_seasonal.sum()) * SEASONAL_HOUSEHOLD),
        "housing_total_m2_per_capita": total_housing / pop,
        "new_floor_area_m2": float(sb.build_floor_area.sum()) if sb is not None else 0.0,
        "cycleway_km": km("cycleway"), "footway_km": km("footway"), "shuttle_km": km("shuttle_route"),
        "berths": int(piers["berths"].sum()) if piers is not None else 0,
        "parking_places": int(park["places"].sum()) if park is not None else 0,
        "college_places": int(college["capacity"].sum()) if college is not None else 0,
        "sailing_school_places": int(sail["capacity"].sum()) if sail is not None else 0,
        "public_spaces": cnt("footway") + (1 if piers is not None else 0),
        "tourism_objects": cnt("hotel") + cnt("yacht_club") + cnt("rental") + cnt("ice_rink") + cnt("marketplace"),
    }


def iso(on: dict, origin: str, mode: str) -> float | None:
    for r in on["isochrones"]:
        if r["origin"] == origin and r["mode"] == mode:
            return r["population"]
    return None


def rows() -> list[dict]:
    B = {t: base(t) for t in TAGS}
    N = {t: load("blocksnet", t) for t in TAGS}
    O = {t: load("objectnat", t) for t in TAGS}
    U = {t: load("urbanomy", t) for t in TAGS}
    C = json.loads((MET / "climate.json").read_text(encoding="utf-8")) if (MET / "climate.json").exists() else {}
    R: list[dict] = []

    def add(group, name, unit, f, tool, goal, src=None, fmt="{:,.0f}"):
        vals = {}
        for t in TAGS:
            try:
                vals[t] = f(t)
            except (KeyError, TypeError, IndexError):
                vals[t] = None
        R.append({"group": group, "indicator": name, "unit": unit, **vals, "tool": tool, "goal": goal,
                  "fmt": fmt, "src": src})

    pv = lambda t, k, f="strong": N[t]["provision"][k][f]  # noqa: E731
    tp = lambda t, k: N[t]["territory"]["provision"][k]  # noqa: E731

    g = "1. Население и жильё"
    add(g, "Постоянное население", "чел.", lambda t: B[t]["population"], "слои + перепись", "Нацель «Сохранение населения»")
    add(g, "Сезонное население (дачи, оценка 2,5 чел./дом)", "чел.", lambda t: B[t]["seasonal_population"],
        "process.py (сезонный фонд)", "контекст нагрузки на сервисы летом")
    add(g, "Общая площадь жилья на человека", "м²/чел.", lambda t: B[t]["housing_total_m2_per_capita"], "слои building",
        "Указ № 309 (4б): ≥ 33 м²/чел. к 2030", fmt="{:.1f}")
    add(g, "Новое строительство (здания сценария)", "тыс. м²", lambda t: B[t]["new_floor_area_m2"] / 1000, "сценарий",
        "Концепция: +240 тыс. м² фонда", fmt="{:.1f}")
    add(g, "Места в колледже", "мест", lambda t: B[t]["college_places"], "сценарий", "К: 250–300 студентов/год")

    g = "2. Социальная инфраструктура (обеспеченность)"
    add(g, "Детские сады, в нормативе пешком (7 мин)", "%", lambda t: pv(t, "kindergarten_walk") * 100,
        "BlocksNet competitive_provision", "Нацель «Сохранение населения», поддержка семьи")
    add(g, "Детские сады, с подвозом (15 мин)", "%", lambda t: pv(t, "kindergarten_drive") * 100,
        "BlocksNet competitive_provision", "то же")
    add(g, "Дефицит мест в детских садах", "мест", lambda t: pv(t, "kindergarten_drive", "deficit"),
        "BlocksNet competitive_provision", "главный дефицит «было»")
    add(g, "Школы, в нормативе пешком (15 мин)", "%", lambda t: pv(t, "school_walk") * 100, "BlocksNet", "то же")
    add(g, "Школы, с подвозом (30 мин)", "%", lambda t: pv(t, "school_drive") * 100, "BlocksNet", "то же")
    add(g, "Колледж (8 мест/1000, 60 мин)", "%", lambda t: pv(t, "college_drive") * 100, "BlocksNet", "К: удержание молодёжи")
    add(g, "Детсады по зданиям, пешком", "%", lambda t: O[t]["provision"]["kindergarten"]["share_within"] * 100,
        "ObjectNat get_service_provision", "проверка BlocksNet вторым методом")
    for key, nm in (("polyclinic", "Поликлиника / ФАП"), ("pharmacy", "Аптеки"), ("library", "Библиотеки"),
                    ("pitch", "Спортивные площадки"), ("catering", "Общепит"), ("hotel", "Гостиницы")):
        add(g, f"{nm} (норматив BlocksNet, авто)", "%", lambda t, k=key: tp(t, k) * 100,
            "BlocksNet calculate_social_indicators", "М (гостиницы, общепит)" if key in ("hotel", "catering") else "соц. сфера")

    g = "3. Транспорт и доступность"
    add(g, "Медианная доступность кварталов на авто (median_accessibility)", "мин",
        lambda t: N[t]["median_acc_drive"], "BlocksNet", "Т: связность поселения", fmt="{:.1f}")
    add(g, "Время до ж/д станции без машины (жители Приморска)", "мин", lambda t: N[t]["town_t_transit_station"],
        "BlocksNet, граф пешком + шаттл", "Т: ТПУ, −25–30 % времени в пути до СПб", fmt="{:.1f}")
    add(g, "Время до порта без машины (жители Приморска)", "мин", lambda t: N[t]["town_t_transit_port"],
        "BlocksNet, граф пешком + шаттл", "Т: доступ к главному работодателю", fmt="{:.1f}")
    add(g, "Время до кампуса без машины (жители Приморска)", "мин", lambda t: N[t]["town_t_transit_campus"],
        "BlocksNet, граф пешком + шаттл", "К: доступность кампуса", fmt="{:.1f}")
    add(g, "Жители Приморска в 30 мин от станции без машины", "%",
        lambda t: N[t]["town_share_transit_station_30"] * 100, "BlocksNet", "Т")
    add(g, "Жители в 30 мин от порта (пешком + шаттл)", "чел.", lambda t: iso(O[t], "порт", "transit"),
        "ObjectNat get_graph_isochrones", "Т: занятость без автомобиля")
    add(g, "Жители в 30 мин от станции (пешком + шаттл)", "чел.", lambda t: iso(O[t], "станция", "transit"),
        "ObjectNat get_graph_isochrones", "Т: пассажиропоток +150–200 %")
    add(g, "Жители в 15 мин пешком от марины", "чел.", lambda t: iso(O[t], "марина", "walk"),
        "ObjectNat get_graph_isochrones", "М: набережная для жителей")
    add(g, "Связность населённых пунктов (BlocksNet)", "—", lambda t: N[t]["territory"]["transport"]["settlements_connectivity"],
        "BlocksNet calculate_transport_indicators", "Т", fmt="{:.2f}")
    add(g, "Плотность УДС", "км/км²", lambda t: N[t]["territory"]["transport"]["road_network_density"],
        "BlocksNet calculate_transport_indicators", "Т", fmt="{:.2f}")
    add(g, "Велодорожки", "км", lambda t: B[t]["cycleway_km"], "сценарий", "Т: 4,5–5 км", fmt="{:.1f}")
    add(g, "Пешеходные маршруты", "км", lambda t: B[t]["footway_km"], "сценарий", "Т; Указ № 309 (4е)", fmt="{:.1f}")
    add(g, "Маршрут шаттла", "км", lambda t: B[t]["shuttle_km"], "сценарий", "Т: 10 км", fmt="{:.1f}")
    add(g, "Парковка ТПУ", "мест", lambda t: B[t]["parking_places"], "сценарий", "Т: 100 мест")

    g = "4. Среда и экология"
    add(g, "Жители г. Приморска в зоне шума ≥ 55 дБА", "чел.", lambda t: O[t]["noise"]["population_ge55"],
        "ObjectNat calculate_simplified_noise_frame", "Нацель «Комфортная среда»")
    add(g, "Объекты сценария в зоне шума ≥ 55 дБА", "зданий", lambda t: O[t]["noise"].get("scenario_buildings_ge55"),
        "ObjectNat", "общежитие и детский сад — 53 дБА (ниже нормы 55); здания марины у улицы — до 72 дБА")
    add(g, "Видимая с набережной акватория (среднее с точки)", "га", lambda t: O[t]["visibility"]["mean_sea_view_ha"],
        "ObjectNat get_visibility", "М: видовые раскрытия на залив", fmt="{:.1f}")
    add(g, "Благоустроенные общественные пространства (маршруты, марина)", "ед.", lambda t: B[t]["public_spaces"],
        "сценарий", "Указ № 309 (4е): благоустройство общественных территорий")

    g = "5. Экономика и туризм"
    add(g, "Причальные места", "мест", lambda t: B[t]["berths"], "сценарий", "М: 30–40 мест")
    add(g, "Места в парусной школе", "мест/год", lambda t: B[t]["sailing_school_places"], "сценарий", "М: 50–60")
    add(g, "Туристские объекты (гостиница, клуб, прокат, каток, рынок)", "ед.", lambda t: B[t]["tourism_objects"],
        "сценарий", "Указ № 309 (6н): доля туризма в ВВП 5 %")
    z = lambda t, f: f(U[t]) if U[t] else (0 if t == "today" else None)  # noqa: E731
    ser = lambda u, ind, k="delta_ops_year": next(r[k] for r in u["ser"] if r["indicator"] == ind)  # noqa: E731
    add(g, "Инвестиции в проекты, всего", "млн ₽", lambda t: z(t, lambda u: u["investment_need_total"] / 1e6),
        "Urbanomy InvestmentAttractivenessAnalyzer", "бенчмарки СПб, без стоимости земли")
    add(g, "Инвестиции: марина", "млн ₽", lambda t: z(t, lambda u: u["investment_by_project"]["marina"] / 1e6),
        "Urbanomy InvestmentAttractivenessAnalyzer", "М: 150–200 млн ₽")
    add(g, "Инвестиции: кампус", "млн ₽", lambda t: z(t, lambda u: u["investment_by_project"]["campus"] / 1e6),
        "Urbanomy InvestmentAttractivenessAnalyzer", "К: в концепции не оценены")
    add(g, "Инвестиции: детский сад (240 мест)", "млн ₽",
        lambda t: z(t, lambda u: u["investment_by_project"].get("kindergarten", 0) / 1e6),
        "Urbanomy InvestmentAttractivenessAnalyzer", "мероприятие МП: дефицит детсадов")
    add(g, "Новые рабочие места: кампус", "мест", lambda t: z(t, lambda u: u["jobs_by_project"]["campus"]),
        "Urbanomy (jobs_per_m2)", "К: +250–300")
    add(g, "Новые рабочие места: марина", "мест", lambda t: z(t, lambda u: u["jobs_by_project"]["marina"]),
        "Urbanomy (jobs_per_m2; для RECREATION норма 0)", "М: +40–50 (марина) и +200 (комплекс)")
    add(g, "Δ доходов бюджета территории (год эксплуатации)", "млн ₽/год",
        lambda t: z(t, lambda u: ser(u, "Доходы бюджета территории") / 1e6), "Urbanomy SEREstimator",
        "бюджет 2024 — 281,4 млн ₽; концепция: +96–134 млн ₽/год (Т 30–45, М 6–9 и 60–80)", fmt="{:.1f}")
    add(g, "Δ доходов бюджета территории (год стройки)", "млн ₽/год",
        lambda t: z(t, lambda u: ser(u, "Доходы бюджета территории", "delta_build_year") / 1e6),
        "Urbanomy SEREstimator", "то же", fmt="{:.1f}")
    add(g, "Δ ВРП на душу (год эксплуатации)", "тыс. ₽/чел.",
        lambda t: z(t, lambda u: ser(u, "Валовый региональный продукт на душу населения") / 1000),
        "Urbanomy SEREstimator", "концепция: ВГП ×2,0–2,1", fmt="{:.1f}")

    g = "6. Климат (дополнительные метрики)"
    add(g, "Дни, пригодные для парусных занятий (май–сентябрь)", "дн.", lambda t: C["sail_days_mean"], "ERA5 / Open-Meteo",
        "М: загрузка парусной школы")
    add(g, "Дни со среднесуточной t < −5 °C", "дн.", lambda t: C["frost_days_mean"], "ERA5", "М: буеры, каток — круглогодичность")
    add(g, "Доля дневных часов с ветром > 5 м/с", "%", lambda t: C["windy_daytime_share"] * 100, "ERA5",
        "ветровой комфорт набережной")
    add(g, "Максимальный порыв за 10 лет", "м/с", lambda t: C["gust_max_ms"], "ERA5", "ветровая нагрузка на причалы",
        fmt="{:.1f}")
    return R


NOT_COUNTED = [
    ("Возрастная структура поселения, очередь в детсады, СКР", "Росстат публикует возраст только по районам (взята "
     "доля детей Выборгского р-на); данных об очереди нет", "проверка норматива; Нацель «Сохранение населения» "
     "(СКР 1,6 к 2030)"),
    ("Стоимость земли «до / после»", "нет обученной модели CatBoost для Urbanomy LandPriceEstimator",
     "KPI ТЭП «было / стало»; нужны модель курса или кадастровые цены"),
    ("ВГП / ВРП «стало» в абсолютных значениях", "нет базового ВРП поселения; SEREstimator даёт только приросты",
     "концепция: ВГП ×2,0–2,1"),
    ("Турпоток", "нет статистики размещения / посещений", "концепция: 75 тыс. чел./год, +400–700 %"),
    ("Пассажиропоток ж/д", "нет данных РЖД / СЗППК по ст. Приморск", "концепция: +150–200 %"),
    ("Отток молодёжи", "нет миграционной статистики по возрастам", "концепция: −35–45 %"),
    ("Дороги в нормативном состоянии", "нет данных диагностики покрытия", "Указ № 309 (4л): ≥ 60 % региональных"),
    ("Индекс качества городской среды", "методика Минстроя для опорных НП, нет исходных данных", "Указ № 309 (4а)"),
]


SER_CSV = ROOT / "data" / "raw" / "ser_forecast_2030.csv"
AGE_CSV = ROOT / "data" / "raw" / "rosstat_age_vyborg_2024.csv"   # возрастной состав Выборгского р-на


def ser_section(R: list[dict]) -> list[str]:
    """Сверка с официальным прогнозом СЭР поселения до 2030 (инерционный вариант, без проектов концепции)."""
    if not SER_CSV.exists():
        return []
    f = pd.read_csv(SER_CSV).set_index("indicator")
    v = lambda k, y: f.loc[k, f"y{y}"]  # noqa: E731
    val = lambda name: next((r["s2"] for r in R if r["indicator"] == name), None)  # noqa: E731
    jobs = sum(x or 0 for x in (val("Новые рабочие места: кампус"), val("Новые рабочие места: марина")))
    inv = val("Инвестиции в проекты, всего")
    births = (v("births", 2023) + v("births", 2024)) / 2
    age = pd.read_csv(AGE_CSV).set_index("area")
    share = age["age_1_6"] / age["population"]
    town_pop = json.loads((MET / "blocksnet_today.json").read_text(encoding="utf-8"))["town_population"]
    kids_town = town_pop * share["urban"]
    kids = kids_town + (next(r["today"] for r in R if r["indicator"] == "Постоянное население") - town_pop) * share["rural"]
    pt = pd.read_csv(REP / "provision_today.csv")
    kg = pt[pt["service"] == "kindergarten"].iloc[0]
    kg_need, kg_cap = kg["Норматив, мест"], kg["Вместимость (факт)"]
    n = lambda x, d=0: "—" if x is None or x != x else f"{x:,.{d}f}".replace(",", " ").replace(".", ",")  # noqa: E731
    rows_ = [
        ("Численность населения на 1 января", "чел.", n(v("population_jan1", 2024)), n(v("population_jan1", 2030)),
         n(val("Постоянное население")), "сценарий: +75 жителей общежития; прогноз СЭР: +61 к 2030 за счёт миграции"),
        ("Рождаемость / смертность", "чел./год", f"{n(v('births', 2024))} / {n(v('deaths', 2024))}",
         f"{n(v('births', 2030))} / {n(v('deaths', 2030))}", "—", "естественная убыль сохраняется (−27 в 2030)"),
        ("Миграционный прирост", "чел./год", n(v("migration_increase", 2024)), n(v("migration_increase", 2030)), "—",
         "сценарии миграцию не моделируют"),
        ("Дети 1–6 лет (оценка по структуре Выборгского р-на, Росстат 01.01.2024)", "чел.", n(kids), "—", "—",
         f"город {kids_town:.0f} (4,4 % жителей) + сёла {kids - kids_town:.0f} (3,8 %); по рождаемости 2023–2024 — "
         f"≈ {6 * births:.0f}; мест в детсадах {kg_cap:.0f}, норматив МНГП ЛО (зона Б) — {kg_need:.0f}"),
        ("Инвестиции в основной капитал", "млн ₽/год", n(v("investment_fixed_capital", 2024), 1),
         n(v("investment_fixed_capital", 2030), 1), n(None if inv is None else inv / 5, 1),
         "сценарий 2: проекты за 2027–2031, в среднем за год (Urbanomy)"),
        ("Доходы бюджета поселения", "млн ₽", n(v("budget_revenue", 2024), 1), n(v("budget_revenue", 2030), 1),
         "+" + n(val("Δ доходов бюджета территории (год эксплуатации)"), 1),
         "Δ SEREstimator — все уровни бюджета; бюджет поселения получает лишь часть НДФЛ и имущественных налогов"),
        ("Занятые в экономике", "чел.", n(v("employed_economy", 2024)), n(v("employed_economy", 2030)),
         "+" + n(jobs), "сценарий 2: рабочие места кампуса и марины (Urbanomy), прогноз СЭР — без роста"),
        ("Среднемесячная зарплата", "₽", n(v("avg_wage_month", 2024)), n(v("avg_wage_month", 2030)), "—",
         "база SEREstimator — 2024"),
    ]
    out = ["## 7. Сверка с прогнозом СЭР поселения до 2030", "",
           "Прогноз — постановление администрации МО «Приморское городское поселение» № 996 от 06.12.2024, "
           "прил. 1 (`data/raw/ser_forecast_2030.csv`): инерционный вариант без проектов концепции.", "",
           "| Показатель | Ед. | 2024 (оценка) | 2030 (прогноз СЭР) | Сценарий 2 (расчёт) | Комментарий |",
           "|---|---|---|---|---|---|"]
    out += [f"| {a} | {b} | {c} | {d} | {e} | {g} |" for a, b, c, d, e, g in rows_]
    return out + [""]


def fmt(v, f):
    if v is None or v != v:
        return "—"
    return f.format(v).replace(",", " ").replace(".", ",")


def main() -> None:
    R = rows()
    df = pd.DataFrame(R)
    df.drop(columns=["fmt", "src"]).to_csv(REP / "metrics_scenarios.csv", index=False, encoding="utf-8-sig")
    lines = ["# Показатели состояния поселения: сегодня — сценарий 1 — сценарий 2", "",
             "Сгенерировано `scripts/metrics.py`. Сценарии — `scripts/scenarios.py`: "
             + "; ".join(f"**{v['short']}** — {v['name']}" for v in SCENARIOS.values()) + ".",
             "Цели концепции: **Т** — транспортная связность, **К** — научно-образовательный кластер (удержание "
             "молодёжи), **М** — морская столица (круглогодичный туризм). Нацели — Указ Президента РФ "
             "от 07.05.2024 № 309.", ""]
    for gname, gdf in df.groupby("group", sort=False):
        lines += [f"## {gname}", "", "| Показатель | Ед. | Сегодня | Сценарий 1 | Сценарий 2 | Δ к сегодня (сц. 2) | "
                  "Инструмент | Цель / гипотеза |", "|---|---|---|---|---|---|---|---|"]
        for _, r in gdf.iterrows():
            a, c = r["today"], r["s2"]
            d = (c - a) if isinstance(a, (int, float)) and isinstance(c, (int, float)) and a == a and c == c else None
            ad = None if d is None else fmt(abs(d), r["fmt"])
            ds = "—" if d is None else ("0" if ad.strip("0,") == "" else ("+" if d > 0 else "−") + ad)
            lines.append(f"| {r['indicator']} | {r['unit']} | {fmt(a, r['fmt'])} | {fmt(r['s1'], r['fmt'])} | "
                         f"{fmt(c, r['fmt'])} | {ds} | {r['tool']} | {r['goal']} |")
        lines.append("")
    lines += ser_section(R)
    lines += ["## Важные показатели, которые посчитать не удалось", "",
              "| Показатель | Почему | Зачем нужен |", "|---|---|---|"]
    lines += [f"| {a} | {b} | {c} |" for a, b, c in NOT_COUNTED]
    lines.append("")
    (REP / "metrics_scenarios.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    chart(df)


KEY = [("Детские сады, с подвозом (15 мин)", "Детсады с подвозом, %"),
       ("Колледж (8 мест/1000, 60 мин)", "Колледж, % нормы"),
       ("Время до ж/д станции без машины (жители Приморска)", "До станции без машины, мин"),
       ("Время до порта без машины (жители Приморска)", "До порта без машины, мин"),
       ("Жители в 30 мин от порта (пешком + шаттл)", "Жителей в 30 мин от порта"),
       ("Видимая с набережной акватория (среднее с точки)", "Видимая акватория, га"),
       ("Причальные места", "Причальные места"),
       ("Новые рабочие места: кампус", "Рабочие места в кампусе")]


def chart(df: pd.DataFrame) -> None:
    """Малые множества: по панели на показатель (одна ось на панель), три ступени одного тона."""
    have = lambda k: df[df.indicator == k][["s1", "s2"]].notna().any(axis=None)  # noqa: E731
    keys = [(k, lab) for k, lab in KEY if k in set(df.indicator) and have(k)]
    n = len(keys)
    cols = 4
    rows_ = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows_, cols, figsize=(13, 3.1 * rows_))
    plt.rcParams.update({"font.family": "DejaVu Sans"})
    for ax, (k, lab) in zip(axes.flat, keys):
        r = df[df.indicator == k].iloc[0]
        vals = [r[t] if r[t] is not None else 0 for t in TAGS]
        bars = ax.bar(range(3), vals, color=[COLORS[t] for t in TAGS], width=0.62, edgecolor="white", linewidth=2)
        for b, v, t in zip(bars, vals, TAGS):
            txt = "—" if r[t] is None else fmt(v, r["fmt"])
            ax.text(b.get_x() + b.get_width() / 2, b.get_height(), txt, ha="center", va="bottom", fontsize=9,
                    color="#222")
        ax.set_title(lab, fontsize=10, loc="left", color="#222")
        ax.set_xticks(range(3))
        ax.set_xticklabels([SCENARIOS[t]["short"] for t in TAGS], fontsize=8, color="#555")
        ax.set_yticks([])
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.spines["bottom"].set_color("#bbb")
        ax.set_ylim(0, max(vals) * 1.25 if max(vals) > 0 else 1)
    for ax in list(axes.flat)[n:]:
        ax.set_visible(False)
    fig.tight_layout()
    (REP / "charts").mkdir(parents=True, exist_ok=True)
    fig.savefig(REP / "charts" / "metrics_key.png", dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    main()
