"""Independent BlocksNet cutting experiment; canonical blocks are read for comparison only."""
from pathlib import Path
import hashlib
import json
import geopandas as gpd
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
MCRS=32635


def compare_blocks(generated,canonical,boundary):
    generated=generated.to_crs(MCRS);canonical=canonical.to_crs(MCRS);boundary=boundary.to_crs(MCRS)
    gen=generated[['geometry']].reset_index(drop=True).rename_axis('generated_id').reset_index()
    can=canonical[['geometry']].reset_index(drop=True).rename_axis('canonical_id').reset_index()
    pairs=gpd.overlay(gen,can,how='intersection',keep_geom_type=True)
    pairs['overlap_area_m2']=pairs.area
    pairs=pairs[pairs.overlap_area_m2>1].copy()
    gu=gen.union_all();cu=can.union_all();bu=boundary.union_all();inter=gu.intersection(cu).area
    metrics={'generated_count':len(gen),'canonical_count':len(can),'generated_area_ha':gu.area/1e4,'canonical_area_ha':cu.area/1e4,'boundary_area_ha':bu.area/1e4,'canonical_area_covered_share':inter/cu.area,'generated_area_in_canonical_share':inter/gu.area,'generated_boundary_coverage_share':gu.intersection(bu).area/bu.area,'intersection_over_union':inter/gu.union(cu).area,'generated_internal_overlap_m2':float(gen.area.sum()-gu.area),'canonical_split_count':int((pairs.groupby('canonical_id').generated_id.nunique()>1).sum()),'generated_merge_count':int((pairs.groupby('generated_id').canonical_id.nunique()>1).sum()),'overlap_pairs':len(pairs),'overlap_pair_min_area_m2':1}
    return metrics,pairs


def main():
    from blocksnet.blocks.cutting import cut_urban_blocks
    proc=ROOT/'data/processed';out=proc/'blockgen';out.mkdir(parents=True,exist_ok=True)
    names=['boundary','roads','railways','water','lake','river','blocks']
    inputs={name:gpd.read_file(proc/f'{name}.geojson').to_crs(MCRS) for name in names}
    # Existing roads/rail only; planned 2042 barriers must not masquerade as today's structure.
    for name in ('roads','railways'):
        if 'event_time' in inputs[name]:inputs[name]=inputs[name][inputs[name].event_time.fillna(2022)<=2022]
    lines=gpd.GeoDataFrame(pd.concat([inputs[n][['geometry']] for n in ('roads','railways','river')],ignore_index=True),geometry='geometry',crs=MCRS)
    polygons=gpd.GeoDataFrame(pd.concat([inputs[n][['geometry']] for n in ('water','lake')],ignore_index=True),geometry='geometry',crs=MCRS)
    generated=cut_urban_blocks(inputs['boundary'][['geometry']],lines,polygons)
    generated['generated_id']=range(len(generated));generated['method']='blocksnet_cut_urban_blocks';generated['area_ha']=generated.area/1e4
    metrics,pairs=compare_blocks(generated,inputs['blocks'],inputs['boundary'])
    generated.to_crs(4326).to_file(out/'blocks_generated.geojson',driver='GeoJSON')
    pairs.to_crs(4326).to_file(out/'canonical_overlap.geojson',driver='GeoJSON')
    pairs.drop(columns='geometry').to_csv(out/'canonical_overlap.csv',index=False)
    metrics['inputs']={n:{'sha256':hashlib.sha256((proc/f'{n}.geojson').read_bytes()).hexdigest(),'used_features':len(inputs[n])} for n in names}
    metrics['method']='blocksnet.blocks.cutting.cut_urban_blocks; existing roads+railways+river lines; water+lake polygons; no classifier, no manual edits, no topology snapping, no external downloads'
    (ROOT/'reports/blocks_generation.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf-8')
    report=['# Независимая генерация кварталов BlocksNet','','Воспроизведение: `.venv-blocksnet/bin/python scripts/blocks_generation.py`. Результаты — `data/processed/blockgen/`; исходные 526 кварталов не заменяются.','','Использован реальный API BlocksNet 1.0.0a9 `blocksnet.blocks.cutting.cut_urban_blocks(boundaries_gdf, lines_gdf, polygons_gdf)`. В границе поселения нарезаны существующие дороги и железные дороги (event_time ≤ 2022) и линии рек; водные полигоны water и lake исключены. Применяются метрические геометрии EPSG:32635, экспорт EPSG:4326. Нет classifier и дополнительной ручной/кластерной нарезки.','','По docs/data-sources.md канонические кварталы получены методикой курса с ручной корректировкой; process.py только очищает исходный blocks.geojson. Поэтому совпадение количества 526 не является ожидаемым результатом независимой нарезки. Геометрия линий без дополнительного snapping: разрывы могут оставлять крупные ненарезанные полигоны. Канонические кварталы и независимые полигоны могут различаться охватом леса, суши и детализацией. Разбиения/объединения считаются по пересечениям >1 м². Доля границы включает исходный водный охват; это не доля застроенной территории.','','```json',json.dumps(metrics,ensure_ascii=False,indent=2),'```']
    (ROOT/'reports/blocks_generation.md').write_text('\n'.join(report),encoding='utf-8')
    print(json.dumps(metrics,ensure_ascii=False),flush=True)
    return metrics

if __name__=='__main__':main()
