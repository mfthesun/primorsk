"""Course GIS exports from the existing road model; no network requests or canonical writes.
Run with .venv-objectnat/bin/python scripts/analytical_exports.py [today s1 s2].
Pickles retain the calculation CRS EPSG:32635; portable GeoJSON is EPSG:4326.
"""
from __future__ import annotations
import json
import pickle
import sys
from pathlib import Path
import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString
import shapely
from roadgraph import MCRS, scenario_graphs, edges_gdf
from scenarios import SCENARIOS
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/processed/analytical_export'
COVERAGE={'school':15,'kindergarten':7,'polyclinic':15}


def write(g,path):
    path.parent.mkdir(parents=True,exist_ok=True)
    if len(g)==0:
        path.write_text('{"type":"FeatureCollection","features":[]}',encoding='utf-8')
        return
    g=g.to_crs(4326).copy()
    polygonal=g.geom_type.isin(['Polygon','MultiPolygon'])
    if polygonal.any():
        def valid_polygon(geometry):
            fixed=shapely.make_valid(geometry)
            if fixed.geom_type in ('Polygon','MultiPolygon'):return fixed
            def parts(geom):
                if geom.geom_type=='Polygon':return [geom]
                return [p for child in getattr(geom,'geoms',[]) for p in parts(child)]
            return shapely.union_all(parts(fixed))
        g.loc[polygonal,'geometry']=g.loc[polygonal,'geometry'].map(valid_polygon)
    if not g.is_valid.all():raise ValueError(f'Invalid export geometry: {path}')
    g.to_file(path,driver='GeoJSON',engine='pyogrio')


def graph_tables(graph,scenario,mode):
    nodes=gpd.GeoDataFrame([{'node_id':n,'x_m':d['x'],'y_m':d['y']} for n,d in graph.nodes(data=True)],
        geometry=gpd.points_from_xy([d['x'] for _,d in graph.nodes(data=True)], [d['y'] for _,d in graph.nodes(data=True)]),crs=graph.graph['crs'])
    edges=gpd.GeoDataFrame([{'u':u,'v':v,**d} for u,v,d in graph.edges(data=True)],geometry='geometry',crs=graph.graph['crs'])
    for frame in (nodes,edges):
        frame['scenario']=scenario;frame['mode']=mode
    return nodes.to_crs(4326),edges.to_crs(4326)


def export_graph(graph,out,scenario,mode):
    out.mkdir(parents=True,exist_ok=True)
    graph=graph.copy();graph.graph.update(scenario=scenario,mode=mode)
    nodes,edges=graph_tables(graph,scenario,mode)
    with (out/f'graph_{mode}.pkl').open('wb') as stream:pickle.dump(graph,stream,pickle.HIGHEST_PROTOCOL)
    write(nodes,out/f'graph_{mode}.nodes.geojson');write(edges,out/f'graph_{mode}.edges.geojson')
    return {'nodes':len(nodes),'edges':len(edges),'time_min_min':float(edges.time_min.min()),'length_meter_sum':float(edges.length_meter.sum())}


def stable_ids(frame,kind):
    """Namespace source ids; service table without individual ids uses stable source row number."""
    values=frame['id'].astype(str) if 'id' in frame else frame.index.astype(str)
    scenario=frame.get('is_scenario',pd.Series(False,index=frame.index)).fillna(False)
    return pd.Series([f"{kind}:{'scenario' if bool(sc) else 'existing'}:{value}" for value,sc in zip(values,scenario)],index=frame.index)


def allocation_layers(buildings,services,result,scenario,service,threshold):
    """Export exact sparse flow values (the library helper truncates demand to int)."""
    b=buildings.drop(columns=buildings.columns.intersection(result.demand_rows.columns)).join(result.demand_rows)
    s=services.drop(columns=services.columns.intersection(result.capacity_rows.columns)).join(result.capacity_rows)
    coo=result.flow.sparse.to_coo()
    rows=[]
    for i,j,amount in zip(coo.row,coo.col,coo.data):
        bi=result.flow.index[i];sj=result.flow.columns[j]
        cost=float(result.distance_matrix.loc[bi,sj])
        rows.append({'building_id':buildings.loc[bi,'object_id'],'service_object_id':services.loc[sj,'object_id'],
            'allocated':float(amount),'time_min':cost,'within_threshold':cost<=threshold,
            'geometry':LineString([buildings.geometry.loc[bi].representative_point(),services.geometry.loc[sj].representative_point()])})
    links=gpd.GeoDataFrame(rows,geometry='geometry',crs=buildings.crs) if rows else gpd.GeoDataFrame(geometry=[],crs=buildings.crs)
    for frame in (b,s,links):
        frame['scenario']=scenario;frame['service_type']=service;frame['mode']='walk';frame['threshold_min']=threshold
    return b,s,links


def service_frame(service,phase):
    from roadgraph import scenario_layer
    source=gpd.read_file(ROOT/f'data/processed/services/{service}.geojson').to_crs(MCRS)
    source['is_scenario']=False;source['object_id']=stable_ids(source,service)
    extra=scenario_layer(service,phase)
    if extra is not None:
        extra=extra.copy();extra['is_scenario']=True;extra['object_id']=stable_ids(extra,service)
        source=gpd.GeoDataFrame(pd.concat([source,extra],ignore_index=True),geometry='geometry',crs=MCRS)
    source['capacity_status']=np.where(source.capacity<=0,'unknown_not_zero_supply',np.where(source.is_scenario,'design_assumption','source_reported'))
    source.geometry=source.representative_point()
    return source.reset_index(drop=True)


def run(tag):
    from objectnat import get_graph_coverage,get_service_provision,config
    from objectnat_analysis import buildings,urban_graph,PROVISION,TOWN
    config.change_logger_lvl('WARNING');config.set_enable_tqdm(False)
    phase=SCENARIOS[tag]['phase'];graphs,info=scenario_graphs(phase);out=OUT/tag
    metrics={'scenario':tag,'graphs':{mode:export_graph(g,out,tag,mode) for mode,g in graphs.items()},'source_graph_info':info,'coverage':{},'provision':{}}
    ug=urban_graph(graphs['walk'])
    boundary=gpd.read_file(ROOT/'data/processed/boundary.geojson').to_crs(MCRS)
    for service,threshold in COVERAGE.items():
        s=service_frame(service,phase)
        coverage=get_graph_coverage(ug,gdf_destinations=s,weight_type='time_min',weight_value_cutoff=threshold,geometry_type='ways',road_buffer_size=60,zone=boundary)
        if len(coverage):
            coverage=coverage[['geometry']].join(s[['object_id','capacity','capacity_status']])
            coverage['scenario']=tag;coverage['service_type']=service;coverage['mode']='walk';coverage['threshold_min']=threshold
            coverage['method']='objectnat_get_graph_coverage_ways';coverage['road_buffer_m']=60
            coverage['area_ha']=coverage.area/1e4
        write(coverage,out/f'coverage_{service}_walk.geojson')
        metrics['coverage'][service]={'sources':len(s),'zones':len(coverage),'union_area_ha':float(coverage.union_all().area/1e4) if len(coverage) else 0,'threshold_min':threshold}
    b=buildings(phase);b['object_id']=stable_ids(b,'building');b=b[b.population>0].copy().reset_index(drop=True)
    b.geometry=b.representative_point()
    blocks=gpd.read_file(ROOT/f'data/processed/analysis/blocks_{tag}.geojson').to_crs(MCRS)
    joined=gpd.sjoin(b[['geometry']],blocks[['locality','geometry']],how='left',predicate='within')
    town=(joined[~joined.index.duplicated()].locality==TOWN).reindex(b.index,fill_value=False)
    for service,((town_rate,rural_rate),threshold) in PROVISION.items():
        s=service_frame(service,phase)
        # Zero denotes an unknown capacity in this dataset, never an observed closure.
        if (s.capacity<=0).any():raise ValueError(f'{service}: unknown capacity cannot enter allocation')
        b['demand']=(b.population*np.where(town,town_rate,rural_rate)/1000).round(3)
        b['source_demand']=b['demand']
        matrix=ug.od_matrix(gdf_origins=b,gdf_destinations=s,weight='time_min')
        result=get_service_provision(buildings=b,distance_matrix=matrix,services=s,threshold=threshold,seed=0)
        layers=allocation_layers(b,s,result,tag,service,threshold)
        for name,frame in zip(('buildings','services','links'),layers):write(frame,out/f'provision_{service}_{name}.geojson')
        result.flow.to_pickle(out/f'provision_{service}_flow.pkl')
        result.distance_matrix.to_pickle(out/f'provision_{service}_od_time_min.pkl')
        metrics['provision'][service]={'buildings':len(b),'services':len(s),'links':len(layers[2]),'allocated':float(result.flow.sparse.to_coo().data.sum()),'source_demand':float(b.demand.sum()),'library_integer_demand':int(result.demand_rows.demand.sum()),'supplied_within':int(result.demand_rows.supplied_demands_within.sum()),'supplied_outside':int(result.demand_rows.supplied_demands_without.sum()),'unallocated_library_demand':int(result.demand_rows.demand_left.sum()),'source_capacity':float(s.capacity.sum()),'threshold_min':threshold,'seed':0,'demand_columns':list(result.demand_rows),'capacity_columns':list(result.capacity_rows)}
    (out/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(metrics,ensure_ascii=False),flush=True)
    return metrics


def main(tags=None):
    tags=tags or list(SCENARIOS)
    results=[run(tag) for tag in tags]
    report=['# Аналитические экспорты курса','', 'Воспроизведение: `.venv-objectnat/bin/python scripts/analytical_exports.py`.', '', 'Графы — существующая модель roadgraph.scenario_graphs, крупнейшая компонента; walk/drive/transit. Pickle: EPSG:32635; GeoJSON: EPSG:4326. Transit сегодня совпадает с walk; сценарный шаттл — гипотеза с ожиданием половины интервала.', '', 'Зоны — ObjectNat 2.1 get_graph_coverage, multi-source Dijkstra, разделение Voronoi по ближайшему сервису, geometry_type=ways, буфер дорог 60 м, обрезка границей. Самокасания колец после проекции исправляются make_valid, полигональные компоненты сохраняются (без convex hull). Это зоны сетевой доступности без конкуренции за вместимость, не радиус и не convex hull. Привязка к ближайшему узлу не учитывает время подхода от двери.', '', 'Обеспеченность — фактическая разреженная матрица flow из get_service_provision(seed=0), capacity_rows и demand_rows. Links — прямые связи распределения, не маршруты; allocated сохраняет исходную точность; time_min — OD графа. ObjectNat 2.1 отбрасывает дробную часть спроса каждого дома (astype(int)); дома со спросом <1 теряются для распределения. source_demand сохраняет нормативный дробный спрос, demand — целочисленный спрос библиотеки. library_integer_demand, supplied_within и supplied_outside приведены отдельно. Это существенное ограничение метода на уровне малых домов: результаты не заменяют нормативный дефицит BlocksNet и не сравниваются с ним как один показатель. Нормативы детсада 61/40, школы 91/61 места на 1000 (город/село), пороги 7/15 минут. Устойчивые object_id содержат слой, existing/scenario и исходный id (для сервисов без id — порядковый номер исходной записи).', '', 'Нулевая capacity поликлиник означает неизвестную вместимость, не отсутствие обслуживания. Поэтому для них только зоны доступности; модель распределения запускается для школ и детсадов с положительными известными вместимостями. Исходные вместимости из существующих слоёв; актуальность на 2026 год независимо не подтверждена.', '']
    for r in results:report += [f"## {r['scenario']}", '```json',json.dumps(r,ensure_ascii=False,indent=2),'```','']
    (ROOT/'reports/analytical_exports.md').write_text('\n'.join(report),encoding='utf-8')
    return results

if __name__=='__main__':main(sys.argv[1:] or None)
