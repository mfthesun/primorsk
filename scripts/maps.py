"""
Карты для презентаций (PNG, reports/maps/) в едином макете для слайдов.

Оформление (одинаково на всех картах):
- без заголовков — заголовки и подписи пишутся в презентации (готовые подписи — reports/maps/README.md);
- кадр 4:3 одного размера; указатель севера — вверху справа, масштабная линейка — внизу слева,
  условные обозначения — внизу справа;
- подложка Esri всегда (contextily; тайлы кэшируются в data/cache/tiles). Без подложки карта не строится:
  при первом запуске нужен доступ к server.arcgisonline.com, дальше хватает кэша.
  Не CARTO — нужен API-ключ.

    python scripts/maps.py              # все карты
    python scripts/maps.py provision    # только карты, в имени которых есть «provision»

Карты «было» требуют data/processed/analysis/blocks_today.geojson (scripts/analysis.py).
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as mpatches  # noqa: E402
import matplotlib.patheffects as pe  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.colors import BoundaryNorm, ListedColormap  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
OUT = ROOT / "reports" / "maps"
CACHE = ROOT / "data" / "cache" / "tiles"
WEB = 3857

# ---- макет ----------------------------------------------------------------------------------------
FIGSIZE = (10, 7.5)          # дюймы, 4:3
DPI = 200
NORTH_XY = (0.955, 0.955)    # доли кадра: указатель севера (верх справа)
SCALE_XY = (0.03, 0.055)     # масштабная линейка (низ слева, над атрибуцией подложки)
LEGEND_LOC = "lower right"   # условные обозначения
# охваты (lon0, lon1, lat0, lat1) — расширяются до 4:3 вокруг центра
# (с запасом справа-снизу под легенду: она всегда в правом нижнем углу)
EXTENT = {"settlement": (28.36, 29.42, 60.14, 60.58), "town": (28.565, 28.725, 60.322, 60.376),
          "region": (26.3, 35.9, 58.35, 61.45)}
# подложки Esri — только без собственных надписей (на них латиница); все подписи на карте — наши, по-русски
GRAY, IMAGERY, RELIEF = "WorldGrayCanvas", "WorldImagery", "WorldShadedRelief"   # RELIEF — без надписей
ATTRIBUTION = "Подложка: © Esri"
# подписи водных объектов (lon, lat, текст)
WATER_LABELS = [(28.50, 60.24, "Финский залив"), (28.54, 60.47, "Выборгский залив"),
                (28.635, 60.352, "Финский залив")]

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "legend.fontsize": 8,
                     "legend.title_fontsize": 9})
HALO = [pe.withStroke(linewidth=2.5, foreground="white")]
CAPTIONS: dict[str, tuple[str, str]] = {}      # имя карты -> (подпись, источник)


def read(path: Path) -> gpd.GeoDataFrame:
    return gpd.read_file(path).to_crs(WEB)


def frame(extent: str):
    fig = plt.figure(figsize=FIGSIZE)
    ax = fig.add_axes([0, 0, 1, 1])
    lon0, lon1, lat0, lat1 = EXTENT[extent]
    bb = gpd.GeoSeries.from_xy([lon0, lon1], [lat0, lat1], crs=4326).to_crs(WEB)
    cx, cy = bb.x.mean(), bb.y.mean()
    w, h = bb.x.max() - bb.x.min(), bb.y.max() - bb.y.min()
    aspect = FIGSIZE[0] / FIGSIZE[1]
    w, h = max(w, h * aspect), max(h, w / aspect)
    ax.set_xlim(cx - w / 2, cx + w / 2)
    ax.set_ylim(cy - h / 2, cy + h / 2)
    ax.set_axis_off()
    return fig, ax


def basemap(ax, style: str = GRAY) -> None:
    import contextily as cx
    CACHE.mkdir(parents=True, exist_ok=True)
    cx.set_cache_dir(str(CACHE))
    try:
        cx.add_basemap(ax, source=getattr(cx.providers.Esri, style), attribution=ATTRIBUTION, attribution_size=6,
                       zorder=0)
    except Exception as e:
        raise SystemExit(f"подложка Esri {style} недоступна ({type(e).__name__}: {e}) — карты без подложки не строим")


def north_arrow(ax) -> None:
    x, y = NORTH_XY
    ax.annotate("", xy=(x, y), xytext=(x, y - 0.075), xycoords="axes fraction",
                arrowprops=dict(facecolor="black", edgecolor="white", width=4, headwidth=13, headlength=12), zorder=20)
    ax.text(x, y - 0.1, "С", transform=ax.transAxes, ha="center", va="center", fontsize=12, fontweight="bold",
            path_effects=HALO, zorder=20)


def scale_bar(ax) -> None:
    """Линейка в истинных метрах: в EPSG:3857 1 м на местности = 1 / cos(φ) единиц карты."""
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    lat = np.degrees(2 * np.arctan(np.exp(((y0 + y1) / 2) / 6378137)) - np.pi / 2)
    k = 1 / np.cos(np.radians(lat))
    ground_w = (x1 - x0) / k
    nice = [100, 200, 250, 500, 1000, 2000, 2500, 5000, 10000, 20000, 25000, 50000, 100000]
    length = max(n for n in nice if n <= ground_w / 5)
    bx = x0 + SCALE_XY[0] * (x1 - x0)
    by = y0 + SCALE_XY[1] * (y1 - y0)
    hgt = 0.012 * (y1 - y0)
    for i in range(4):
        ax.add_patch(mpatches.Rectangle((bx + i * length / 4 * k, by), length / 4 * k, hgt,
                                        facecolor="black" if i % 2 == 0 else "white", edgecolor="black", lw=0.8,
                                        zorder=20))
    fmt = (lambda m: f"{m / 1000:g}".replace(".", ",")) if length >= 1000 else (lambda m: f"{m:g}")
    unit = "км" if length >= 1000 else "м"
    for m in (0, length / 2, length):
        ax.text(bx + m * k, by + hgt * 1.6, fmt(m), ha="center", va="bottom", fontsize=7.5, path_effects=HALO,
                zorder=20)
    ax.text(bx + length * k + 0.01 * (x1 - x0), by + hgt / 2, unit, ha="left", va="center", fontsize=7.5,
            path_effects=HALO, zorder=20)


def legend(ax, handles, title: str) -> None:
    lg = ax.legend(handles=handles, loc=LEGEND_LOC, title=title, frameon=True, framealpha=0.92,
                   edgecolor="#999", borderaxespad=0.8)
    lg.set_zorder(20)


def finish(fig, ax, name: str, handles, legend_title: str, caption: str, source: str, style: str = GRAY,
           water: bool = True) -> None:
    if water:
        water_labels(ax)
    basemap(ax, style)
    legend(ax, handles, legend_title)
    north_arrow(ax)
    scale_bar(ax)
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}.png", dpi=DPI)
    plt.close(fig)
    CAPTIONS[name] = (caption, source)
    print("  ", OUT / f"{name}.png")


def context(ax, roads=True, boundary=True) -> list:
    """Вода, дороги, ж/д, граница; возвращает элементы легенды для них."""
    read(PROC / "water.geojson").plot(ax=ax, color="#cfe3f3", lw=0, zorder=1)
    h = []
    if roads:
        read(PROC / "roads.geojson").plot(ax=ax, color="#8a8a8a", lw=0.4, zorder=4)
        h.append(Line2D([], [], color="#8a8a8a", lw=0.8, label="улично-дорожная сеть"))
    read(PROC / "railways.geojson").plot(ax=ax, color="#333", lw=1.0, ls="--", zorder=4)
    h.append(Line2D([], [], color="#333", lw=1.0, ls="--", label="железная дорога"))
    if boundary:
        read(PROC / "boundary.geojson").boundary.plot(ax=ax, color="#222", lw=0.9, ls="-.", zorder=4)
        h.append(Line2D([], [], color="#222", lw=0.9, ls="-.", label="граница поселения"))
    return h


def water_labels(ax) -> None:
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    w = x1 - x0
    for lon, lat, text in WATER_LABELS:
        p = gpd.GeoSeries.from_xy([lon], [lat], crs=4326).to_crs(WEB).iloc[0]
        # подпись — только если подходит к масштабу кадра (городская — на крупном, общая — на мелком)
        town = lat > 60.33 and lon > 28.6
        if x0 < p.x < x1 and y0 < p.y < y1 and (town == (w < 20000)):
            ax.text(p.x, p.y, text, fontsize=10, fontstyle="italic", color="#3a6f99", ha="center", va="center",
                    zorder=15, path_effects=[pe.withStroke(linewidth=2, foreground="#eaf3fa")])


def places(ax, size=8) -> None:
    pl = read(ROOT / "data" / "raw" / "osm_places.geojson")
    big = pl[pl["place"].isin(["town", "village"])]
    for p, n in zip(big.geometry, big["name"]):
        ax.annotate(n, (p.x, p.y), fontsize=size, ha="center", va="bottom", zorder=15, color="#222",
                    path_effects=HALO)


# =============================================================================
def map_living() -> None:
    b = read(PROC / "building.geojson")
    for ext in ("town", "settlement"):
        fig, ax = frame(ext)
        h = context(ax)
        b[~b.is_living].plot(ax=ax, color="#a9a9a9", lw=0, zorder=5)
        b[b.is_living].plot(ax=ax, color="#d9480f", lw=0, zorder=6)
        if ext == "settlement":
            places(ax)
        h = [mpatches.Patch(color="#d9480f", label=f"жилые ({int(b.is_living.sum())})"),
             mpatches.Patch(color="#a9a9a9", label=f"нежилые ({int((~b.is_living).sum())})")] + h
        finish(fig, ax, f"buildings_living_{ext}", h, "Здания",
               f"Жилые и нежилые здания{', г. Приморск' if ext == 'town' else ''}",
               "building.geojson (OSM, Реестр домов; корректировка is_living — process.py)")


# города и расстояния для карты местоположения (lon, lat, подпись, смещение подписи в pt)
REGION_CITIES = [(30.315, 59.939, "Санкт-Петербург", (8, -14)), (28.733, 60.710, "Выборг", (8, 4)),
                 (28.610, 60.366, "Приморск", (6, -14)), (29.700, 60.196, "Зеленогорск", (8, 4))]


def map_location() -> None:
    """Местоположение поселения относительно Ленинградской области и Санкт-Петербурга."""
    rc = read(ROOT / "data" / "raw" / "region_context.geojson")
    fig, ax = frame("region")
    lo, spb = rc[rc["name"] == "Ленинградская область"], rc[rc["name"] == "Санкт-Петербург"]
    lo.plot(ax=ax, color="#fcd1c6", alpha=0.35, edgecolor="#f87e60", lw=1.4, zorder=2)
    spb.plot(ax=ax, color="#728da0", alpha=0.55, edgecolor="#4f6a7d", lw=1.0, zorder=3)
    bnd = read(PROC / "boundary.geojson")
    bnd.plot(ax=ax, color="#f87e60", edgecolor="#7a2a17", lw=1.0, zorder=5)
    for lon, lat, name, off in REGION_CITIES:
        p = gpd.GeoSeries.from_xy([lon], [lat], crs=4326).to_crs(WEB).iloc[0]
        ax.plot(p.x, p.y, "o", ms=5 if name != "Санкт-Петербург" else 7, color="#111", mec="white", mew=1.2, zorder=6)
        ax.annotate(name, (p.x, p.y), xytext=off, textcoords="offset points", fontsize=11, color="#111", zorder=7,
                    path_effects=HALO, ha="right" if off[0] < 0 else "left")
    c = bnd.geometry.iloc[0].representative_point()
    lab = gpd.GeoSeries.from_xy([27.75], [59.45], crs=4326).to_crs(WEB).iloc[0]
    ax.annotate("Приморское\nгородское поселение", (c.x, c.y), xytext=(lab.x, lab.y), fontsize=12, fontweight="bold",
                color="#7a2a17", ha="center", va="center", zorder=8, path_effects=HALO,
                arrowprops=dict(arrowstyle="-", color="#7a2a17", lw=1.2))
    for lon, lat, text in ((27.05, 60.02, "Финский залив"), (31.6, 60.95, "Ладожское озеро")):
        p = gpd.GeoSeries.from_xy([lon], [lat], crs=4326).to_crs(WEB).iloc[0]
        ax.text(p.x, p.y, text, fontsize=10, fontstyle="italic", color="#3a6f99", ha="center", va="center",
                zorder=7, path_effects=[pe.withStroke(linewidth=2, foreground="#eaf3fa")])
    h = [mpatches.Patch(color="#f87e60", ec="#7a2a17", label="Приморское городское поселение"),
         mpatches.Patch(color="#fcd1c6", ec="#f87e60", label="Ленинградская область"),
         mpatches.Patch(color="#728da0", alpha=0.6, label="Санкт-Петербург"),
         Line2D([], [], marker="o", ls="", color="#111", mec="white", label="города")]
    finish(fig, ax, "location_region", h, "Местоположение",
           "Приморское городское поселение в Ленинградской области: 132 км до Санкт-Петербурга, 47 км до Выборга",
           "region_context.geojson (границы OSM), boundary.geojson", style=RELIEF, water=False)


def map_floors() -> None:
    b = read(PROC / "building.geojson")
    bins = [1, 2, 3, 4, 6, 10, 100]
    labels = ["1", "2", "3", "4–5", "6–9", "10 и более"]
    cmap = ListedColormap(["#fde0c5", "#facba6", "#f59e72", "#e8603e", "#b9302c", "#6b1b2a"])
    norm = BoundaryNorm(bins, cmap.N)
    for ext in ("town", "settlement"):
        fig, ax = frame(ext)
        h = context(ax)
        b.plot(ax=ax, column="number_of_floors", cmap=cmap, norm=norm, lw=0, zorder=5)
        if ext == "settlement":
            places(ax)
        h = [mpatches.Patch(color=cmap(i), label=l) for i, l in enumerate(labels)] + h
        finish(fig, ax, f"buildings_floors_{ext}", h, "Этажность, эт.",
               f"Этажность застройки{', г. Приморск' if ext == 'town' else ''}", "building.geojson")


def blocks_today(tag: str = "today") -> gpd.GeoDataFrame:
    p = PROC / "analysis" / f"blocks_{tag}.geojson"
    if not p.exists():
        raise SystemExit(f"нет blocks_{tag}.geojson — сначала .venv-blocksnet/bin/python scripts/analysis.py")
    return read(p)


def choropleth(name, column, bins, labels, colors, legend_title, caption, source, mask=None, extra=None,
               ext="settlement", tag="today") -> None:
    bl = blocks_today(tag)
    fig, ax = frame(ext)
    cmap = ListedColormap(colors)
    norm = BoundaryNorm(bins, cmap.N)
    sel = bl if mask is None else bl[mask(bl)]
    bl.plot(ax=ax, color="#f4f4f4", edgecolor="#c8c8c8", lw=0.2, zorder=2, alpha=0.8)
    sel.plot(ax=ax, column=column, cmap=cmap, norm=norm, edgecolor="white", lw=0.2, zorder=3, alpha=0.85)
    h = context(ax, roads=True)
    eh = extra(ax) if extra else []
    places(ax)
    h = [mpatches.Patch(color=cmap(i), label=l) for i, l in enumerate(labels)] + \
        [mpatches.Patch(color="#f4f4f4", ec="#c8c8c8", label="кварталы без жителей")] + eh + h
    finish(fig, ax, name, h, legend_title, caption, source)


def map_density() -> None:
    choropleth("blocks_population_density", "pop_density", [0.001, 1, 5, 15, 40, 1e4],
               ["< 1", "1–5", "5–15", "15–40", "> 40"], ["#eff3ff", "#bdd7e7", "#6baed6", "#3182bd", "#08519c"],
               "Плотность населения, чел./га", "Плотность населения по кварталам",
               "blocks_today.geojson — агрегация зданий по кварталам (BlocksNet aggregate_objects)",
               mask=lambda b: b["population"] > 0)


def stations(ax) -> list:
    read(PROC / "services" / "train_station.geojson").plot(ax=ax, color="black", marker="s", markersize=30, zorder=12)
    return [Line2D([], [], marker="s", ls="", color="black", label="ж/д станции")]


def map_accessibility() -> None:
    ramp = ["#1a9850", "#91cf60", "#fee08b", "#fc8d59", "#d73027"]
    choropleth("access_station_drive", "t_drive_station", [0, 10, 20, 30, 45, 1e4],
               ["< 10", "10–20", "20–30", "30–45", "> 45"], ramp, "Время до ст. Приморск, мин",
               "Доступность ж/д станции Приморск на автомобиле (от центра застройки квартала)",
               "blocks_today.geojson; граф УДС roads.geojson + OSM (roadgraph.py), матрица BlocksNet",
               mask=lambda b: b["population"] > 0, extra=stations)
    choropleth("access_median_drive", "median_acc_drive", [0, 30, 40, 50, 60, 1e4],
               ["< 30", "30–40", "40–50", "50–60", "> 60"], ramp, "Медианное время, мин",
               "Транспортная связность кварталов: медианное время на автомобиле до остальных кварталов "
               "(median_accessibility)", "blocks_today.geojson (BlocksNet median_accessibility)",
               mask=lambda b: b["population"] > 0)


def map_provision() -> None:
    acc = {"school": {"walk": 15, "drive": 30}, "kindergarten": {"walk": 7, "drive": 15}}
    ramp = ["#d73027", "#fc8d59", "#fee08b", "#91cf60", "#1a9850"]

    def objects_of(svc: str, legend_name: str, tag: str):
        s = read(PROC / "services" / f"{svc}.geojson")
        layers = [(s, "#08306b", f"{legend_name} (число — мест)")]
        sc = PROC / "scenario" / f"{svc}.geojson"
        if tag != "today" and sc.exists():
            x = read(sc)
            x = x[x["phase"] <= {"s1": 1, "s2": 2}[tag]]
            if len(x):
                layers.append((x, "#c2255c", f"{legend_name} сценария (число — мест)"))

        def objects(ax):
            h = []
            for g, col, lab in layers:
                g.plot(ax=ax, color=col, markersize=np.sqrt(g["capacity"].clip(lower=10)) * 4, edgecolor="white",
                       lw=0.6, zorder=12)
                for p, c in zip(g.geometry, g["capacity"]):
                    ax.annotate(str(c), (p.x, p.y), xytext=(6, -10), textcoords="offset points", fontsize=7.5,
                                color=col, fontweight="bold", zorder=13, path_effects=HALO)
                h.append(Line2D([], [], marker="o", ls="", color=col, label=lab))
            return h
        return objects

    bins, labels = [0, 0.2, 0.5, 0.8, 0.999, 1.01], ["< 20 %", "20–50 %", "50–80 %", "80–99 %", "100 %"]
    for svc, what, legend_name in (("school", "школами", "школы"), ("kindergarten", "детскими садами", "детские сады")):
        for mode, how in (("walk", "пешком"), ("drive", "с подвозом (транспорт)")):
            choropleth(f"provision_{svc}_{mode}", f"{svc}_{mode}_provision_strong", bins, labels, ramp,
                       "Обеспеченность (provision_strong)",
                       f"Обеспеченность {what}: {how}, ≤ {acc[svc][mode]} мин",
                       "blocks_today.geojson (BlocksNet competitive_provision); вместимость — capacity",
                       mask=lambda b, c=f"{svc}_{mode}_demand": b[c] > 0, extra=objects_of(svc, legend_name, "today"))
    # детские сады «сегодня / сценарий 2»: мероприятие — детский сад на 160 мест на востоке Приморска
    for mode, how in (("walk", "пешком"), ("drive", "с подвозом (транспорт)")):
        for tag in ("today", "s2"):
            for ext in ("settlement", "town"):
                if tag == "today" and ext == "settlement":
                    continue                                   # это provision_kindergarten_<mode> выше
                name = f"provision_kindergarten_{mode}" + ("_town" if ext == "town" else "") + \
                    ("_s2" if tag == "s2" else "")
                choropleth(name, f"kindergarten_{mode}_provision_strong", bins, labels, ramp,
                           "Обеспеченность (provision_strong)",
                           f"Обеспеченность детскими садами: {how}, ≤ {acc['kindergarten'][mode]} мин"
                           + (", г. Приморск" if ext == "town" else "") + f", {STATE[tag]}",
                           f"blocks_{tag}.geojson (BlocksNet competitive_provision); вместимость — capacity",
                           mask=lambda b, c=f"kindergarten_{mode}_demand": b[c] > 0,
                           extra=objects_of("kindergarten", "детские сады", tag), ext=ext, tag=tag)


def map_scenario() -> None:
    sc = PROC / "scenario"
    fig, ax = frame("town")
    read(PROC / "building.geojson").plot(ax=ax, color="#e0e0e0", lw=0, zorder=4, alpha=0.7)
    terr = read(sc / "boundary.geojson")
    terr.plot(ax=ax, color="#ffe8a3", edgecolor="#d4a017", lw=1.4, zorder=5, alpha=0.75)
    read(sc / "building.geojson").plot(ax=ax, color="#e8590c", lw=0, zorder=6)
    read(sc / "roads.geojson").plot(ax=ax, color="#b197fc", lw=2, ls="--", zorder=7)
    read(sc / "shuttle_route.geojson").plot(ax=ax, color="#4dabf7", lw=2.8, zorder=8)
    read(sc / "cycleway.geojson").plot(ax=ax, color="#69db7c", lw=2.3, zorder=9)
    read(sc / "footway.geojson").plot(ax=ax, color="#f783ac", lw=2, ls=":", zorder=9)
    read(sc / "parking.geojson").plot(ax=ax, color="#f8f9fa", edgecolor="black", zorder=9)
    read(sc / "pier.geojson").plot(ax=ax, color="#ffd43b", lw=3, zorder=9)
    read(sc / "bus_stop.geojson").plot(ax=ax, color="white", edgecolor="#1864ab", lw=1.5, markersize=40, zorder=10)
    read(sc / "train_station.geojson").plot(ax=ax, color="white", edgecolor="black", marker="s", markersize=50,
                                            zorder=10)
    read(sc / "kindergarten.geojson").plot(ax=ax, color="#c2255c", edgecolor="white", marker="o", markersize=70,
                                           zorder=10)
    for p, n in zip(terr.representative_point(), terr["name"]):
        ax.annotate(n, (p.x, p.y), xytext=(0, 14), textcoords="offset points", fontsize=8, ha="center", zorder=11,
                    path_effects=HALO)
    km = lambda f: f"{gpd.read_file(sc / f).to_crs(32635).length.sum() / 1000:.1f}".replace(".", ",")  # noqa: E731
    h = [mpatches.Patch(color="#ffe8a3", ec="#d4a017", label="проектные территории"),
         mpatches.Patch(color="#e8590c", label="здания сценария (в т. ч. общежитие, 75 чел.)"),
         Line2D([], [], color="#4dabf7", lw=2.8, label=f"шаттл центр – станция – кампус – порт, {km('shuttle_route.geojson')} км"),
         Line2D([], [], color="#69db7c", lw=2.3, label=f"велодорожка, {km('cycleway.geojson')} км"),
         Line2D([], [], color="#f783ac", lw=2, ls=":", label=f"пешеходные маршруты, {km('footway.geojson')} км"),
         Line2D([], [], color="#b197fc", lw=2, ls="--", label="41А-082 (СТП ЛО, 2042)"),
         mpatches.Patch(color="#f8f9fa", ec="black", label="парковка ТПУ, 100 мест"),
         Line2D([], [], color="#ffd43b", lw=3, label="причалы марины, 40 мест"),
         Line2D([], [], marker="o", ls="", mfc="white", mec="#1864ab", label="остановки шаттла"),
         Line2D([], [], marker="s", ls="", mfc="white", mec="black", label="ж/д станция (ТПУ)"),
         Line2D([], [], marker="o", ls="", mfc="#c2255c", mec="white", label="детский сад, 160 мест (сценарий 2)")]
    finish(fig, ax, "scenario_projects", h, "Сценарий",
           "Проектные предложения: кампус ИНТЦ, марина, транспортный каркас, детский сад",
           "data/processed/scenario (проектные решения команды)", style=IMAGERY)


ON = PROC / "objectnat"
STATE = {"today": "сегодня", "s1": "сценарий 1", "s2": "сценарий 2"}


def town_buildings(ax, tag: str) -> list:
    read(PROC / "building.geojson").plot(ax=ax, color="#c8c8c8", lw=0, zorder=5)
    h = [mpatches.Patch(color="#c8c8c8", label="существующие здания")]
    if tag != "today":
        sb = read(PROC / "scenario" / "building.geojson")
        sb = sb[sb["phase"] <= {"s1": 1, "s2": 2}[tag]]
        sb.plot(ax=ax, color="#e8590c", lw=0, zorder=6)
        h.append(mpatches.Patch(color="#e8590c", label="здания сценария"))
    return h


def map_before_after() -> None:
    """Пары карт «сегодня / сценарий 2» для территории г. Приморска (ObjectNat)."""
    for tag in ("today", "s2"):
        # 1. изохроны «пешком + шаттл» 30 мин от станции и порта
        fig, ax = frame("town")
        iso = read(ON / f"isochrones_{tag}.geojson")
        iso = iso[iso["mode"] == "transit"]
        h = []
        for name, col in (("станция", "#2a78d6"), ("порт", "#eb6834")):
            g = iso[iso["name"] == name]
            g.plot(ax=ax, color=col, alpha=0.28, edgecolor=col, lw=1.2, zorder=3)
            pop = int(g["population"].sum())
            h.append(mpatches.Patch(color=col, alpha=0.5, label=f"30 мин от {'станции' if name == 'станция' else 'порта'}: {pop} жит."))
        h += town_buildings(ax, tag)
        if tag != "today":
            read(PROC / "scenario" / "shuttle_route.geojson").plot(ax=ax, color="#104281", lw=2.4, zorder=8)
            read(PROC / "scenario" / "bus_stop.geojson").plot(ax=ax, color="white", edgecolor="#104281", lw=1.4,
                                                            markersize=36, zorder=9)
            h += [Line2D([], [], color="#104281", lw=2.4, label="шаттл"),
                  Line2D([], [], marker="o", ls="", mfc="white", mec="#104281", label="остановки шаттла")]
        h += context(ax, boundary=False)
        finish(fig, ax, f"town_access_transit_{tag}", h, "Пешком + шаттл",
               f"Зоны доступности 30 мин без автомобиля (пешком{' + шаттл' if tag != 'today' else ''}) от ж/д станции и "
               f"порта, {STATE[tag]}", f"ObjectNat get_graph_isochrones, isochrones_{tag}.geojson")
        # 2. шум
        fig, ax = frame("town")
        nz = read(ON / f"noise_{tag}.geojson").sort_values("noise_level")
        levels = [50, 55, 60, 65, 70, 75, 80]
        cmap = ListedColormap(["#fff1a8", "#fdd27a", "#fca95a", "#f67b43", "#e14d35", "#b8262e", "#7f0e24"])
        norm = BoundaryNorm(levels + [200], cmap.N)
        nz.plot(ax=ax, column="noise_level", cmap=cmap, norm=norm, alpha=0.75, lw=0, zorder=3)
        h = [mpatches.Patch(color=cmap(i), label=f"{lv} дБА" + (" и выше" if lv == 80 else "")) for i, lv in enumerate(levels)]
        h += town_buildings(ax, tag) + context(ax, boundary=False)
        finish(fig, ax, f"town_noise_{tag}", h, "Уровень шума",
               f"Шумовое воздействие ж/д, магистральных улиц и порта, {STATE[tag]}",
               f"ObjectNat calculate_simplified_noise_frame, noise_{tag}.geojson")
        # 3. видимость
        fig, ax = frame("town")
        vis = read(ON / f"visibility_{tag}.geojson")
        gpd.GeoSeries([vis.union_all()], crs=WEB).plot(ax=ax, color="#1baf7a", alpha=0.35, lw=0, zorder=3)
        fw = read(PROC / "scenario" / "footway.geojson").iloc[[0]]
        fw.plot(ax=ax, color="#c2255c", lw=2, ls=":", zorder=8)
        h = [mpatches.Patch(color="#1baf7a", alpha=0.5, label="зона видимости с набережной"),
             Line2D([], [], color="#c2255c", lw=2, ls=":", label="маршрут центр – кирха – марина")]
        h += town_buildings(ax, tag) + context(ax, boundary=False)
        finish(fig, ax, f"town_visibility_{tag}", h, "Видовые раскрытия",
               f"Зоны видимости с пешеходного маршрута по набережной (до 600 м), {STATE[tag]}",
               f"ObjectNat get_visibility, visibility_{tag}.geojson")


MAPS = {"location_region": map_location, "buildings_living": map_living, "buildings_floors": map_floors, "blocks_population_density": map_density,
        "access": map_accessibility, "provision": map_provision, "scenario_projects": map_scenario,
        "town_before_after": map_before_after}


def write_captions() -> None:
    p = OUT / "README.md"
    old = {}
    if p.exists():   # при частичной пересборке сохраняем подписи остальных карт
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.startswith("| `"):
                c = [x.strip() for x in line.strip("|").split("|")]
                old[c[0].strip("`").removesuffix(".png")] = (c[1], c[2])
    old.update(CAPTIONS)
    old = {k: v for k, v in old.items() if (OUT / f"{k}.png").exists()}
    lines = ["# Карты для презентации", "",
             "Генерируются `scripts/maps.py`. Заголовков на картах нет — подписи к рисункам ниже. Макет единый: "
             "кадр 4:3, север — вверху справа, масштабная линейка — внизу слева, условные обозначения — внизу "
             "справа; подложка Esri (World Light Gray Canvas — тематические карты, World Imagery — сценарий).", "",
             "| Файл | Подпись к рисунку | Источник |", "|---|---|---|"]
    lines += [f"| `{k}.png` | {c} | {s} |" for k, (c, s) in sorted(old.items())]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    flt = sys.argv[1] if len(sys.argv) > 1 else ""
    for name, fn in MAPS.items():
        if flt in name:
            print(name)
            fn()
    write_captions()


if __name__ == "__main__":
    main()
