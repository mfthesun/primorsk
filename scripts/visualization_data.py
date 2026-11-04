"""Производные данные веб-карты; канонические GeoJSON не изменяются.

Адаптация учебных тетрадей КИГС 2026: 3D / присоединение сервисов.
Сервис присоединяется только при пересечении; неоднозначность разрешается
минимальной площадью здания, затем стабильным ID. Высота: этажи × 3 м.
"""
from __future__ import annotations
import json
from pathlib import Path
import geopandas as gpd
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTDOOR = {'bus_stop','playground','pitch','cell_tower'}

def clean(value):
    if isinstance(value, dict): return {str(k):clean(v) for k,v in value.items()}
    if isinstance(value,(list,tuple,np.ndarray)): return [clean(v) for v in value]
    if isinstance(value,np.generic): value=value.item()
    if value is None or (not isinstance(value,(str,dict,list)) and pd.isna(value)): return None
    return value

def feature_collection(frame):
    """GeoJSON сохраняет вложенные атрибуты, null и стабильные строковые ID."""
    frame=frame.to_crs(4326)
    features=[]
    for index,row in frame.iterrows():
        props=clean(row.drop(labels=frame.geometry.name).to_dict())
        features.append({'type':'Feature','id':props.get('stable_id',str(index)), 'properties':props,
                         'geometry':clean(row.geometry.__geo_interface__)})
    return {'type':'FeatureCollection','features':features}

def assign_services(buildings, services):
    """Возвращает копию зданий и аудит каждого сервиса; ближайшие не назначаются."""
    result=buildings.copy()
    result['services']=[[] for _ in range(len(result))]
    b=result.to_crs(32635); s=services.to_crs(32635)
    areas=b.geometry.area
    report={'assigned':0,'unmatched':0,'outdoor':0,'ambiguous':0,'records':[]}
    for i,row in s.iterrows():
        kind=row.get('service_type','unknown')
        record={'service_index':str(i),'service_type':kind,'source':clean(row.get('source')),'name':clean(row.get('name')) or clean(row.get('service_name')),'capacity':clean(row.get('capacity'))}
        if kind in OUTDOOR:
            report['outdoor']+=1;record['status']='outdoor'
        else:
            hits=list(b.sindex.query(row.geometry,predicate='intersects'))
            if hits:
                chosen=min(hits,key=lambda j:(areas.iloc[j],str(b.iloc[j].stable_id)))
                sid=clean(row.get('service_id'))
                item={'service':sid,'name':clean(row.get('name')) or clean(row.get('service_name')) or kind,
                      'capacity':clean(row.get('capacity')), 'type':kind,'phase':clean(row.get('phase',0)) or 0}
                result.iloc[chosen,result.columns.get_loc('services')].append(item)
                record.update(status='assigned',building_id=str(b.iloc[chosen].stable_id),candidates=len(hits))
                report['assigned']+=1
                if len(hits)>1:report['ambiguous']+=1
            else:
                report['unmatched']+=1;record['status']='unmatched'
        report['records'].append(record)
    return result,report

def read(path):
    return gpd.read_file(path).to_crs(4326)

def prepare_buildings(root=ROOT):
    proc=root/'data/processed'
    today=read(proc/'building.geojson');today['stable_id']='today_'+today.id.astype(str);today['phase']=0
    scenario=read(proc/'scenario/building.geojson');scenario['stable_id']='scenario_'+scenario.id.astype(str)
    buildings=gpd.GeoDataFrame(pd.concat([today,scenario],ignore_index=True),crs=4326)
    buildings['height_m']=buildings.number_of_floors.fillna(1).clip(lower=1)*3
    buildings['provision']=[{} for _ in range(len(buildings))]
    zones=read(proc/'landuse.geojson').to_crs(32635)
    metric=buildings.to_crs(32635)
    zone_names=[]
    for geom in metric.geometry:
        candidates=list(zones.sindex.query(geom,predicate='intersects'))
        zone_names.append(str(zones.iloc[max(candidates,key=lambda j:geom.intersection(zones.geometry.iloc[j]).area)]['name']) if candidates else None)
    buildings['zone_name']=zone_names
    services=[]
    for directory in [proc/'services',proc/'scenario']:
        for path in sorted(directory.glob('*.geojson')):
            frame=read(path)
            if 'service_id' not in frame and 'service_name' not in frame:continue
            frame['service_type']=path.stem;frame['source']=str(path.relative_to(root));frame['phase']=frame.get('phase',0)
            services.append(frame)
    svc=gpd.GeoDataFrame(pd.concat(services,ignore_index=True),crs=4326)
    # Существующие сервисы не могут попасть в ещё не построенное сценарное здание.
    pieces=[]; audits={}
    for label,subset,ss in [('today',buildings[buildings.phase==0],svc[svc.source.str.contains('/services/')]),
                             ('scenario',buildings[buildings.phase>0],svc[~svc.source.str.contains('/services/')])]:
        assigned,report=assign_services(subset,ss);pieces.append(assigned);audits[label]=report
    buildings=gpd.GeoDataFrame(pd.concat(pieces,ignore_index=True),crs=4326)
    # Предпочтительно явный source ID из воспроизводимого analytical_export.
    stable_index={str(row.stable_id):i for i,row in buildings.iterrows()}
    for tag in ['today','s1','s2']:
        for service in ['kindergarten','school']:
            exported=proc/'analytical_export'/tag/f'provision_{service}_buildings.geojson'
            path=exported if exported.exists() else proc/'objectnat'/f'provision_{service}_{tag}.geojson'
            if not path.exists():continue
            frame=read(path)
            for _,row in frame.iterrows():
                if exported.exists():
                    key=('scenario_' if row.get('is_scenario',False) else 'today_')+str(int(row['id']))
                    idx=stable_index.get(key);value=row.get('provision_value')
                else:
                    hits=list(buildings.sindex.query(row.geometry,predicate='intersects'))
                    idx=min(hits,key=lambda j:(metric.geometry.iloc[j].area,str(buildings.iloc[j].stable_id))) if hits else None
                    value=row.get(service+'_provision_value')
                if idx is not None:buildings.iloc[idx]['provision'][f'{tag}_{service}']=clean(value)
    buildings['has_services']=buildings.services.map(bool)
    return buildings,svc,audits
