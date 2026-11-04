"""
Карты цифровой модели и сценария Приморска в стиле презентации мастер-плана
(контроль 03.11.2026): шрифты Inter / Dela Gothic One, палитра презентации,
врезка-локатор «местоположение в Ленинградской области» (Natural Earth).

Выход: maps/*.png. Для scenario.png нужна сеть (тайлы Esri World Imagery),
остальные карты строятся в лёгком векторном стиле без подложки.

Запуск из корня репозитория:  python scripts/maps.py
"""
from __future__ import annotations

import math
from pathlib import Path

import geopandas as gpd
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from shapely.geometry import box

matplotlib.use("Agg")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed"
NE = ROOT / "data" / "raw" / "natural_earth"
OUT = ROOT / "maps"
WEB = 3857
MCRS = 32635
LAT = 60.36          # широта Приморска (масштабные линейки)
REGION_VIEW = (26.9, 58.7, 32.5, 61.9)   # охват врезки

# ---- шрифты презентации -------------------------------------------------------
for f in sorted((ROOT / "assets" / "fonts").glob("*.ttf")):
    font_manager.fontManager.addfont(str(f))
plt.rcParams.update({
    "font.family": "Inter Regular",
    "svg.fonttype": "none",
})
TITLE_FONT = "Dela Gothic One"

# ---- палитра презентации ------------------------------------------------------
C_WATER = "#dbe7ef"      # вода
C_LAND = "#f4f1ec"       # суша (врезка)
C_OBLAST = "#fde2da"     # Ленинградская область
C_SPB = "#9fb3c2"        # Санкт-Петербург
C_SETTLE = "#f87e60"     # Приморское городское поселение
C_TEXT = "#7a2a17"       # подписи на врезке
C_INK = "#343a40"        # основной текст
C_ROAD = "#d3cfc8"       # улично-дорожная сеть (контекст)
C_RAIL = "#adb5bd"       # железная дорога
# сценарий (легенда карты презентации)
C_TERR = "#ffe8a3"       # проектные территории
C_TERR_EDGE = "#f59f00"
C_BLD = "#e8590c"        # здания сценария
C_SHUTTLE = "#4dabf7"    # шаттл
C_CYCLE = "#40c057"      # велодорожка
C_PED = "#f783ac"        # пешеходные маршруты
C_41A = "#b7a0fa"        # 41А-082 (СТП ЛО, 2042)
C_STOP = "#1864ab"       # остановки шаттла (обводка)
C_PIER = "#ffd43b"       # причалы
C_PIER_EDGE = "#f08c00"
C_KG = "#c2255c"         # детский сад
C_PARK_EDGE = "#495057"  # парковка/станция (обводка)


def km_to_web(km: float) -> float:
    """Длина км вдоль параллели в метрах EPSG:3857 на широте Приморска."""
    return km * 1000 / math.cos(math.radians(LAT))


def add_scalebar(ax, tb, km_total: float, segments: int, label_fmt: str) -> None:
    """Чёрно-белая сегментная линейка с подписями на светлой подложке, слева снизу."""
    x0, y0 = tb[0], tb[1]
    y = y0 + (tb[3] - tb[1]) * 0.04
    bar = km_to_web(km_total)
    h = bar * 0.045
    x = x0 + (tb[2] - tb[0]) * 0.03
    # светлая плашка, чтобы линейка читалась на тёмной подложке
    ax.add_patch(plt.Rectangle((x - bar * 0.06, y - h * 1.2), bar * 1.30, h * 5.6,
                               facecolor="white", edgecolor="#dee2e6", lw=0.6,
                               alpha=0.9, zorder=6.5))
    for i in range(segments):
        fill = "#212529" if i % 2 == 0 else "white"
        ax.add_patch(plt.Rectangle((x + i * bar / segments, y), bar / segments, h,
                                   facecolor=fill, edgecolor="#212529", lw=0.8, zorder=7))
    for i in range(segments + 1):
        xx = x + i * bar / segments
        ax.plot([xx, xx], [y + h, y + h * 1.9], color="#212529", lw=0.8, zorder=7)
        lbl = f"{i * km_total / segments:g}".replace(".", ",")
        ax.text(xx, y + h * 2.3, lbl, ha="center", va="bottom", fontsize=8, color="#212529", zorder=7)
    ax.text(x + bar * 1.10, y + h * 1.4, label_fmt, ha="left", va="center",
            fontsize=8, color="#212529", zorder=7)


def add_north(ax) -> None:
    """Стрелка севера внутри Axes (в врезке-локаторе, как на карте презентации)."""
    ax.annotate("", xy=(0.935, 0.945), xytext=(0.935, 0.83), xycoords="axes fraction",
                arrowprops=dict(arrowstyle="-|>,head_width=0.35,head_length=0.8",
                                color="#212529", lw=1.8), zorder=7)
    ax.text(0.935, 0.80, "С", transform=ax.transAxes, ha="center", va="top",
            fontsize=10, color="#212529", zorder=7)


def add_inset(fig, rect: list[float]) -> None:
    """Врезка «Местоположение в Ленинградской области» (Natural Earth, стиль презентации)."""
    ax = fig.add_axes(rect)
    ax.set_facecolor(C_WATER)
    countries = gpd.read_file(NE / "countries.geojson")
    regions = gpd.read_file(NE / "regions.geojson")
    lakes = gpd.read_file(NE / "lakes.geojson")
    settle = gpd.read_file(DATA / "boundary.geojson")
    minx, miny, maxx, maxy = REGION_VIEW
    countries.plot(ax=ax, color=C_LAND, edgecolor="white", linewidth=0.4)
    for _, r in regions.iterrows():
        face = C_SPB if "Peterburg" in str(r.get("name")) else C_OBLAST
        gpd.GeoSeries([r.geometry], crs=4326).plot(ax=ax, color=face, edgecolor="white",
                                                   linewidth=0.5)
    lakes.plot(ax=ax, color=C_WATER, edgecolor="none")
    settle.plot(ax=ax, color=C_SETTLE, edgecolor="white", linewidth=0.6)
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)
    ax.set_aspect(1 / math.cos(math.radians(60.1)))
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_xlabel(""); ax.set_ylabel("")
    for s in ax.spines.values():
        s.set_edgecolor("#c8c2b8"); s.set_linewidth(0.8)

    from matplotlib import patheffects
    halo = [patheffects.withStroke(linewidth=2, foreground="white")]
    cities = {"Выборг": (28.753, 60.710), "Зеленогорск": (29.670, 60.398),
              "Санкт-Петербург": (30.360, 59.939), "Приморск": (28.612, 60.365)}
    for nm, (x, y) in cities.items():
        ax.plot(x, y, "o", ms=3.5 if nm != "Приморск" else 4.5,
                color="#212529" if nm != "Приморск" else "#a61e4d", zorder=6)
        ax.annotate(nm, (x, y), xytext=(4, 3), textcoords="offset points",
                    fontsize=6.5, color=C_TEXT if nm != "Приморск" else "#a61e4d",
                    path_effects=halo, zorder=6)
    ax.annotate("Приморское городское\nпоселение", (28.66, 60.33), xytext=(27.35, 59.98),
                textcoords="data", fontsize=6.3, color="#a61e4d", ha="center",
                arrowprops=dict(arrowstyle="-", color="#a61e4d", lw=0.6),
                path_effects=halo, zorder=6)
    ax.text(0.07, 0.56, "Финский\nзалив", transform=ax.transAxes, fontsize=6,
            color="#5f7d99", style="italic", ha="center")
    ax.text(0.72, 0.70, "Ладожское\nозеро", transform=ax.transAxes, fontsize=6,
            color="#5f7d99", style="italic", ha="center")
    ax.text(0.02, 0.955, "Финляндия", transform=ax.transAxes, fontsize=6, color=C_TEXT, va="top")
    ax.text(0.04, 0.05, "Эстония", transform=ax.transAxes, fontsize=6, color=C_TEXT)
    ax.text(0.74, 0.05, "Новгородская обл.", transform=ax.transAxes, fontsize=6, color=C_TEXT)
    # линейка 50 км внутри врезки (градусы долготы на 60° с.ш.)
    deg = 50 / (111.32 * math.cos(math.radians(60.1)))
    x0, y0 = minx + 0.04 * (maxx - minx), miny + 0.10 * (maxy - miny)
    for i in range(2):
        ax.add_patch(plt.Rectangle((x0 + i * deg / 2, y0), deg / 2, deg * 0.045,
                                   facecolor="#212529" if i % 2 == 0 else "white",
                                   edgecolor="#212529", lw=0.6, zorder=6))
    for i, lbl in ((0, "0"), (1, "25"), (2, "50")):
        ax.text(x0 + i * deg / 2, y0 + deg * 0.075, lbl, ha="center", fontsize=5.5,
                color="#212529", zorder=6)
    ax.text(x0 + deg * 1.08, y0 + deg * 0.02, "км", fontsize=5.5, color="#212529", zorder=6)


def finalize(fig, ax, outfile: str, attribution: str, dark_bg: bool = False) -> None:
    ax.set_xlabel(""); ax.set_ylabel("")
    ax.set_axis_off()
    ax.text(0.005, 0.005, attribution, transform=ax.transAxes, ha="left", va="bottom",
            fontsize=6.5, color="#e9ecef" if dark_bg else "#868e96", zorder=7)
    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / outfile, facecolor="white")
    plt.close(fig)
    print(f"  maps/{outfile}")


def km_len(gdf: gpd.GeoDataFrame) -> float:
    return float(gdf.to_crs(MCRS).geometry.length.sum() / 1000)


# ---- график NSGA-II для слайда оптимизации (стиль презентации) ------------------
PARETO_STYLE = {
    "campus": dict(label="Кампус", color="#e8590c", marker="o"),
    "kindergarten": dict(label="Детский сад", color="#9474ac", marker="^"),
    "marina": dict(label="Марина", color="#4dabf7", marker="s"),
}


def pareto() -> None:
    """Допустимые фронты NSGA-II (reports/optimization_front_*.csv) и выбранные варианты
    (optimization_selected.csv) — Inter, палитра презентации, млрд/млн ₽ без смещения осей.
    Канонический график расчёта остаётся reports/optimization_pareto.png."""
    fig, ax = plt.subplots(figsize=(10.13, 7.6), dpi=150)
    fig.subplots_adjust(left=0.11, right=0.97, top=0.95, bottom=0.11)
    for name, st in PARETO_STYLE.items():
        front = pd.read_csv(ROOT / "reports" / f"optimization_front_{name}.csv")
        sel = pd.read_csv(ROOT / "reports" / "optimization_selected.csv")
        sel = sel[sel["project"] == name]
        ax.scatter(front["land_value_total_rub"] / 1e9, front["investor_npv_rub"] / 1e6,
                   s=30, alpha=0.4, linewidths=0, color=st["color"], marker=st["marker"])
        ax.scatter(sel["land_value_total_rub"] / 1e9, sel["investor_npv_rub"] / 1e6,
                   s=150, color=st["color"], marker=st["marker"], edgecolor="white",
                   linewidth=1.8, zorder=3, label=st["label"])
    ax.set_xlim(215.23, 215.275)
    ax.set_xticks(np.arange(215.23, 215.2801, 0.01))
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.2f}"))
    ax.set_ylim(-5, 125)
    ax.set_yticks(np.arange(0, 121, 20))
    ax.grid(axis="y", color="#dee5e2", linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#adb5bd")
    ax.tick_params(labelsize=12.5, colors="#343a40")
    ax.set_xlabel("Полная стоимость земли поселения, млрд ₽", fontsize=14, color="#343a40")
    ax.set_ylabel("NPV проекта, млн ₽", fontsize=14, color="#343a40")
    ax.legend(loc="upper right", frameon=False, fontsize=13.5, handletextpad=0.4,
              scatterpoints=1, markerscale=1.1)
    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / "optimization_pareto.png", facecolor="white")
    plt.close(fig)
    print("  maps/optimization_pareto.png")


def main() -> None:
    print("Карты →", OUT)
    bnd = gpd.read_file(DATA / "boundary.geojson")
    bld = gpd.read_file(DATA / "building.geojson")
    water = pd.concat([gpd.read_file(DATA / f"{n}.geojson") for n in ("water", "lake")],
                      ignore_index=True)
    roads = gpd.read_file(DATA / "roads.geojson").cx[27.0:29.3, 60.28:60.55]
    rails = gpd.read_file(DATA / "railways.geojson").cx[27.0:29.3, 60.28:60.55]

    minx, miny, maxx, maxy = bnd.total_bounds
    inset_rect = [0.67, 0.68, 0.31, 0.25]
    # основная карта — заселённая полоса; бухта с островами остаётся во врезке-локаторе
    bminx, bminy, bmaxx, bmaxy = bld.total_bounds
    bounds = (bminx - 0.03, bminy - 0.02, bmaxx + 0.03, bmaxy + 0.02)

    def base_layers() -> list:
        return [(water, dict(color=C_WATER, linewidth=0, zorder=1)),
                (roads, dict(color=C_ROAD, linewidth=0.35, zorder=2)),
                (rails, dict(color=C_RAIL, linewidth=0.5, linestyle=(0, (4, 2)), zorder=2))]

    # --- жилые / нежилые ---------------------------------------------------------
    lw, nl = bld[bld["is_living"]], bld[~bld["is_living"]]
    handles = [
        Patch(facecolor="#e03131", edgecolor="#862e2e", linewidth=0.2, label=f"Жилые ({len(lw)})"),
        Patch(facecolor="#adb5bd", edgecolor="#495057", linewidth=0.2, label=f"Нежилые ({len(nl)})"),
    ]
    layers = base_layers() + [
        (nl, dict(color="#adb5bd", edgecolor="#495057", linewidth=0.12, zorder=3)),
        (lw, dict(color="#e03131", edgecolor="#862e2e", linewidth=0.12, zorder=3)),
        (bnd, dict(facecolor="none", edgecolor="#495057", linewidth=1.0, zorder=4)),
    ]
    fig, ax, tb = draw(layers, "Здания: жилые и нежилые", bounds)
    ax.legend(handles=handles, loc="lower right", fontsize=9, framealpha=0.95, borderpad=0.9)
    add_scalebar(ax, tb, 5, 5, "км")
    add_inset(fig, inset_rect)
    finalize(fig, ax, "living.png", "Данные: OSM, Реестр домов, ГП/СТП ЛО")

    # --- этажность ----------------------------------------------------------------
    bins = np.digitize(bld["number_of_floors"].clip(lower=1), [1, 2, 3, 5, 100], right=True)
    bld2 = bld.assign(bin_code=bins.clip(0, 4))
    palette = ["#ffe066", "#ffc078", "#ff922b", "#f76707", "#c92a2a"]
    labels = ["1", "2", "3", "4–5", "6+"]
    counts = bld2["bin_code"].value_counts().sort_index()
    handles = [Patch(facecolor=palette[i], edgecolor="#495057", linewidth=0.15,
                     label=f"{labels[i]} эт. ({int(counts.get(i, 0))})") for i in range(5)]
    from matplotlib.colors import ListedColormap
    layers = base_layers() + [
        (bld2, dict(column="bin_code", cmap=ListedColormap(palette), edgecolor="#495057",
                    linewidth=0.12, vmin=0, vmax=4, zorder=3)),
        (bnd, dict(facecolor="none", edgecolor="#495057", linewidth=1.0, zorder=4)),
    ]
    fig, ax, tb = draw(layers, "Здания: этажность", bounds)
    ax.legend(handles=handles, loc="lower right", fontsize=9, framealpha=0.95, borderpad=0.9)
    add_scalebar(ax, tb, 5, 5, "км")
    add_inset(fig, inset_rect)
    finalize(fig, ax, "floors.png", "Данные: OSM, Реестр домов, ГП/СТП ЛО")

    # --- сценарий (стиль карты презентации, подложка Esri Imagery) -----------------
    import contextily as cx
    sc = DATA / "scenario"
    sb = gpd.read_file(sc / "boundary.geojson")
    sbld = gpd.read_file(sc / "building.geojson")
    shuttle = gpd.read_file(sc / "shuttle_route.geojson")
    cyc = gpd.read_file(sc / "cycleway.geojson")
    ped = gpd.read_file(sc / "footway.geojson")
    stops = gpd.read_file(sc / "bus_stop.geojson")
    pier = gpd.read_file(sc / "pier.geojson")
    parking = gpd.read_file(sc / "parking.geojson")
    kg = gpd.read_file(sc / "kindergarten.geojson")
    station = gpd.read_file(sc / "train_station.geojson")
    sc_box = (28.585, 60.330, 28.755, 60.405)
    road41 = gpd.read_file(sc / "roads.geojson")   # планируемая 41А-082 (СТП ЛО, 2042)

    sc_tb = gpd.GeoSeries([box(*sc_box)], crs=4326).to_crs(WEB).total_bounds
    handles = [
        Patch(facecolor=C_TERR, edgecolor=C_TERR_EDGE, linewidth=0.8, label="проектные территории"),
        Patch(facecolor=C_BLD, edgecolor="#b53a07", linewidth=0.4,
              label="здания сценария (в т. ч. общежитие, 75 чел.)"),
        Line2D([0], [0], color=C_SHUTTLE, lw=3.5,
               label=f"шаттл центр – станция – кампус – порт, {km_len(shuttle):.1f} км".replace(".", ",")),
        Line2D([0], [0], color=C_CYCLE, lw=2.5,
               label=f"велодорожка, {km_len(cyc):.1f} км".replace(".", ",")),
        Line2D([0], [0], color=C_PED, lw=2.5, linestyle=(0, (2, 1.5)),
               label=f"пешеходные маршруты, {km_len(ped):.1f} км".replace(".", ",")),
        Line2D([0], [0], color=C_41A, lw=2, linestyle=(0, (5, 3)), label="41А-082 (СТП ЛО, 2042)"),
        Line2D([0], [0], marker="s", color="none", markerfacecolor="white",
               markeredgecolor=C_PARK_EDGE, markersize=9, label="парковка ТПУ, 100 мест"),
        Line2D([0], [0], color=C_PIER, lw=4, label="причалы марины, 40 мест"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor="white",
               markeredgecolor=C_STOP, markersize=8, label="остановка шаттла"),
        Line2D([0], [0], marker="P", color="none", markerfacecolor="white",
               markeredgecolor=C_PARK_EDGE, markersize=9, label="ж/д станция (ТПУ)"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor=C_KG, markersize=8,
               label="детский сад, 160 мест (сценарий 2)"),
    ]
    layers = [
        (road41, dict(color=C_41A, linewidth=1.8, linestyle=(0, (5, 3)), zorder=2)),
        (sb, dict(facecolor=C_TERR, alpha=0.9, edgecolor=C_TERR_EDGE, linewidth=1.2, zorder=3)),
        (sbld, dict(color=C_BLD, edgecolor="#b53a07", linewidth=0.3, zorder=4)),
        (shuttle, dict(color=C_SHUTTLE, linewidth=3.5, zorder=5)),
        (cyc, dict(color=C_CYCLE, linewidth=2.5, zorder=5)),
        (ped, dict(color=C_PED, linewidth=2.2, linestyle=(0, (2, 1.5)), zorder=5)),
        (stops, dict(facecolor="white", edgecolor=C_STOP, linewidth=1.2, markersize=26,
                     marker="o", zorder=6)),
        (parking, dict(facecolor="white", edgecolor=C_PARK_EDGE, linewidth=1.2, markersize=44,
                       marker="s", zorder=6)),
        (station, dict(facecolor="white", edgecolor=C_PARK_EDGE, linewidth=1.2, markersize=44,
                       marker="P", zorder=6)),
        (pier, dict(color=C_PIER, linewidth=4, zorder=6)),
        (kg, dict(facecolor=C_KG, edgecolor="white", linewidth=0.8, markersize=60,
                  marker="o", zorder=6)),
    ]
    fig, ax, sc_tb = draw(layers, "Сценарий: кампус ИНТЦ, марина и транспортный проект", sc_box)
    try:
        cx.add_basemap(ax, crs=WEB, source=cx.providers.Esri.WorldImagery, attribution=False, zoom=15)
    except Exception as e:
        print(f"  !! подложка недоступна ({e}); белая подложка")
    ax.legend(handles=handles, loc="lower right", fontsize=8, framealpha=0.95,
              borderpad=0.8, labelspacing=0.55)
    add_scalebar(ax, sc_tb, 2, 2, "км")
    add_inset(fig, inset_rect)
    finalize(fig, ax, "scenario.png", "Подложка: © Esri · Данные: OSM, ГП/СТП ЛО", dark_bg=True)


def draw(layers: list[tuple[gpd.GeoDataFrame, dict]], title: str,
         bounds_4326: tuple[float, float, float, float]):
    """Слои (EPSG:4326) → фигура 11×11 с осями под пропорцию данных (EPSG:3857, aspect equal)."""
    fig = plt.figure(figsize=(11, 11), dpi=200)
    minx, miny, maxx, maxy = bounds_4326
    tb = gpd.GeoSeries([box(minx, miny, maxx, maxy)], crs=4326).to_crs(WEB).total_bounds
    dx, dy = tb[2] - tb[0], tb[3] - tb[1]
    w = 0.94
    h = w * dy / dx
    if h > 0.90:                       # слишком высоко для холста — ужимаем по высоте
        h = 0.90
        w = h * dx / dy
    rect = [0.5 - w / 2, 0.46 - h / 2, w, h]   # центр чуть ниже заголовка
    ax = fig.add_axes(rect)
    ax.set_facecolor(C_LAND)
    for gdf, kw in layers:
        gdf.to_crs(WEB).plot(ax=ax, **kw)
    ax.set_xlim(tb[0], tb[2])
    ax.set_ylim(tb[1], tb[3])
    ax.set_aspect("equal")
    fig.text(0.5, 0.955, title, ha="center", va="top", fontfamily=TITLE_FONT,
             fontsize=17, color=C_INK)
    return fig, ax, tb


if __name__ == "__main__":
    main()
