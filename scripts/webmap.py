"""
Интерактивная карта «Цифровой мастер-план» (HTML, folium/Leaflet) — reports/master_plan.html.

Структура по мастер-плану:
- «Поселение — существующее положение»: кварталы (население, обеспеченность детсадами и школами, время до
  станции), здания (жилые / нежилые / сезонный фонд), сервисы;
- «Сценарии»: для каждого — сегодня / сценарий 1 / сценарий 2 — объекты сценария, транспортные слои,
  изохроны «пешком + шаттл» 30 мин, шум (ObjectNat); переключаются в панели слоёв.
Подложки Esri (World Light Gray Canvas, World Imagery), не CARTO.

Запуск: python scripts/webmap.py   (после analysis.py и objectnat_analysis.py)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import folium
import geopandas as gpd
from branca.colormap import StepColormap

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scenarios import SCENARIOS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
OUT = ROOT / "reports" / "master_plan.html"
SIMPLIFY = 3.0   # м — упрощение геометрии для размера HTML

# подложки без собственных подписей (все подписи на карте — наши, по-русски); светлая Esri на мелких масштабах
# подписывает объекты латиницей — оставлена последней опцией
ESRI = {
    "Esri — рельеф": "https://server.arcgisonline.com/ArcGIS/rest/services/Elevation/World_Hillshade/MapServer/tile/{z}/{y}/{x}",
    "Esri — снимки": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    "Esri — светлая (подписи не на русском)": "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
}
PHASE = {t: v["phase"] for t, v in SCENARIOS.items()}


def read(p: Path, cols: list[str] | None = None, simplify: bool = True) -> gpd.GeoDataFrame:
    g = gpd.read_file(p)
    if cols:
        g = g[[c for c in cols if c in g.columns] + ["geometry"]]
    if simplify:
        g["geometry"] = g.to_crs(32635).simplify(SIMPLIFY).to_crs(4326)
    return g.to_crs(4326)


def gj(g: gpd.GeoDataFrame, name: str, style, tooltip: list[str] | None = None, aliases: list[str] | None = None,
       show: bool = False) -> folium.FeatureGroup:
    fg = folium.FeatureGroup(name=name, show=show)
    kw = {}
    if tooltip:
        kw["tooltip"] = folium.GeoJsonTooltip(fields=tooltip, aliases=aliases or tooltip, localize=True)
    folium.GeoJson(json.loads(g.to_json()), style_function=style, **kw).add_to(fg)
    return fg


def points(g: gpd.GeoDataFrame, name: str, color: str, label: str, show: bool = False) -> folium.FeatureGroup:
    fg = folium.FeatureGroup(name=name, show=show)
    for _, r in g.iterrows():
        p = r.geometry.representative_point()
        txt = label + (f": {r['name']}" if "name" in r and isinstance(r.get("name"), str) else "")
        if "capacity" in r and r["capacity"]:
            txt += f" — {int(r['capacity'])} мест"
        folium.CircleMarker([p.y, p.x], radius=5, color="white", weight=1.5, fill=True, fill_color=color,
                            fill_opacity=1, tooltip=txt).add_to(fg)
    return fg


def main() -> None:
    m = folium.Map(location=[60.36, 28.75], zoom_start=11, tiles=None, control_scale=True)
    for i, (n, u) in enumerate(ESRI.items()):
        folium.TileLayer(u, name=n, attr="© Esri", overlay=False, control=True, show=(i == 0)).add_to(m)

    # --- поселение: существующее положение ---
    bl = read(PROC / "analysis" / "blocks_today.geojson",
              ["id", "locality", "population", "pop_density", "land_use", "morphotype", "t_drive_station",
               "kindergarten_drive_provision_strong", "school_drive_provision_strong", "median_acc_drive"])
    bl["kg"] = (bl["kindergarten_drive_provision_strong"] * 100).round(0)
    bl["sc"] = (bl["school_drive_provision_strong"] * 100).round(0)
    prov_cm = StepColormap(["#d73027", "#fc8d59", "#fee08b", "#91cf60", "#1a9850"], index=[0, 20, 50, 80, 99.9, 100.1],
                           vmin=0, vmax=100, caption="Обеспеченность, %")
    t_cm = StepColormap(["#1a9850", "#91cf60", "#fee08b", "#fc8d59", "#d73027"], index=[0, 10, 20, 30, 45, 300],
                        vmin=0, vmax=60, caption="Время до станции на авто, мин")
    tip = ["locality", "population", "kg", "sc", "t_drive_station", "morphotype"]
    ali = ["Населённый пункт", "Жителей", "Детсады, %", "Школы, %", "До станции, мин", "Морфотип"]
    pop_bl = bl[bl["population"] > 0]

    def st(col, cm):
        return lambda f: {"fillColor": cm(f["properties"][col]) if f["properties"][col] is not None else "#eee",
                          "color": "white", "weight": 0.3, "fillOpacity": 0.7}
    gj(pop_bl, "Поселение: обеспеченность детсадами (с подвозом)", st("kg", prov_cm), tip, ali, show=True).add_to(m)
    gj(pop_bl, "Поселение: обеспеченность школами (с подвозом)", st("sc", prov_cm), tip, ali).add_to(m)
    gj(pop_bl, "Поселение: время до ж/д станции на авто", st("t_drive_station", t_cm), tip, ali).add_to(m)

    b = read(PROC / "building.geojson", ["is_living", "is_seasonal", "population", "number_of_floors"])
    b["тип"] = b.apply(lambda r: "жилое" if r.is_living else ("сезонное (дача)" if r.is_seasonal else "нежилое"), axis=1)
    col = {"жилое": "#d9480f", "сезонное (дача)": "#f2b880", "нежилое": "#9a9a9a"}
    gj(b, "Поселение: здания (жилые / дачи / нежилые)",
       lambda f: {"fillColor": col[f["properties"]["тип"]], "color": col[f["properties"]["тип"]], "weight": 0.2,
                  "fillOpacity": 0.85},
       ["тип", "population", "number_of_floors"], ["Тип", "Жителей", "Этажей"]).add_to(m)
    for svc, nm, c in (("kindergarten", "Детские сады", "#7b2cbf"), ("school", "Школы", "#1864ab"),
                       ("polyclinic", "Поликлиника / ФАП", "#c2255c"), ("train_station", "Ж/д станции", "#000")):
        points(read(PROC / "services" / f"{svc}.geojson", simplify=False), f"Сервисы: {nm}", c, nm).add_to(m)

    # --- сценарии ---
    sb = read(PROC / "scenario" / "building.geojson", ["id", "build_floor_area", "population", "phase"])
    terr = read(PROC / "scenario" / "boundary.geojson", ["name", "population"])
    for tag, ph in PHASE.items():
        short = SCENARIOS[tag]["short"]
        fg = folium.FeatureGroup(name=f"{short}: объекты и транспорт", show=False)
        if ph:
            folium.GeoJson(json.loads(terr.to_json()), style_function=lambda f: {
                "fillColor": "#ffe8a3", "color": "#d4a017", "weight": 1.5, "fillOpacity": 0.4},
                tooltip=folium.GeoJsonTooltip(["name", "population"], ["Территория", "Жителей"])).add_to(fg)
            s = sb[sb["phase"] <= ph]
            folium.GeoJson(json.loads(s.to_json()), style_function=lambda f: {
                "fillColor": "#e8590c", "color": "#e8590c", "weight": 0.5, "fillOpacity": 0.9},
                tooltip=folium.GeoJsonTooltip(["build_floor_area", "population", "phase"],
                                              ["Площадь, м²", "Жителей", "Очередь"])).add_to(fg)
            for lay, color, dash in (("shuttle_route", "#1864ab", None), ("cycleway", "#2b8a3e", None),
                                     ("footway", "#c2255c", "4 4"), ("pier", "#0b7285", None)):
                g = read(PROC / "scenario" / f"{lay}.geojson")
                g = g[g["phase"] <= ph]
                if len(g):
                    folium.GeoJson(json.loads(g.to_json()), style_function=lambda f, c=color, d=dash: {
                        "color": c, "weight": 4, "dashArray": d}, tooltip=lay).add_to(fg)
        fg.add_to(m)
        on = PROC / "objectnat" / f"isochrones_{tag}.geojson"
        if on.exists():
            iso = read(on)
            iso = iso[(iso["mode"] == "transit") & iso["name"].isin(["станция", "порт"])]
            gj(iso, f"{short}: 30 мин пешком{' + шаттл' if ph else ''} от станции и порта",
               lambda f: {"fillColor": "#2a78d6" if f["properties"]["name"] == "станция" else "#eb6834",
                          "color": "#2a78d6" if f["properties"]["name"] == "станция" else "#eb6834",
                          "weight": 1, "fillOpacity": 0.25},
               ["name", "population", "area_ha"], ["Откуда", "Жителей", "Площадь, га"]).add_to(m)
        nz = PROC / "objectnat" / f"noise_{tag}.geojson"
        if nz.exists():
            n = read(nz)
            ncm = StepColormap(["#fff1a8", "#fdd27a", "#fca95a", "#f67b43", "#e14d35", "#b8262e", "#7f0e24"],
                               index=[50, 55, 60, 65, 70, 75, 80, 200], vmin=50, vmax=85)
            gj(n.sort_values("noise_level"), f"{short}: шум, дБА",
               lambda f: {"fillColor": ncm(f["properties"]["noise_level"]), "color": "none", "fillOpacity": 0.6},
               ["noise_level"], ["дБА"]).add_to(m)

    prov_cm.add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    title = ("<div style='position:fixed;top:10px;left:50px;z-index:9999;background:white;padding:6px 10px;"
             "border-radius:4px;font:14px sans-serif;box-shadow:0 1px 4px rgba(0,0,0,.3)'>"
             "<b>Цифровой мастер-план: Приморское городское поселение</b><br>"
             "<span style='font-size:12px;color:#555'>слои «Поселение» — существующее положение; "
             "«Сегодня / Сценарий 1 / Сценарий 2» — до / после</span></div>")
    m.get_root().html.add_child(folium.Element(title))
    m.save(str(OUT))
    print(OUT, round(OUT.stat().st_size / 1e6, 1), "МБ")


if __name__ == "__main__":
    main()
