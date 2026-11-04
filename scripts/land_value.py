"""Учебная CatBoost-модель полной стоимости квартала; внешняя модель не включена в Git."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
os.environ.setdefault('NUMBA_CACHE_DIR', '/tmp/primorsk-numba')
os.environ.setdefault('MPLCONFIGDIR', '/tmp/primorsk-mpl')
import geopandas as gpd
import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from blocksnet.analysis.morphotypes import get_strelka_morphotypes
from blocksnet.analysis.network.accessibility import area_accessibility
from urbanomy.methods.land_value_modeling.land_price_estimation import LandPriceEstimator
from urbanomy.methods.land_value_modeling.scenario_modification import ScenarioTEPModifier
from urbanomy.methods.land_value_modeling.constants import ORIGINAL_FEATURES, CATEGORICAL_FEATURES, RADIUS_LIST
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/processed/urbanomy'
REPORT=ROOT/'reports'
SOURCE=Path('/home/mfthesun/Workspace/ИИ, анализ данных и моделирование в урбанистике/Данные')
MODEL=Path(os.environ.get('LAND_MODEL_PATH',os.environ.get('PRIMORSK_LAND_MODEL',SOURCE/'catboost_land_value_no_services.cbm')))
TRAIN=Path(os.environ.get('PRIMORSK_LAND_TRAIN',SOURCE/'blocks_agg_with_indicators.geojson'))
MCRS=32635

def inverse_prices(log_total, site_area):
    total=np.expm1(np.asarray(log_total,dtype=float))
    return total, np.divide(total,site_area,out=np.full_like(total,np.nan),where=np.asarray(site_area)>0)

def restore_actual_tep(modified, actual):
    result=modified.copy()
    result['population']=actual.population.astype(int)
    result['living_area']=actual.living_area.astype(float)
    result['non_living_area']=result.build_floor_area-result.living_area
    result['mxi']=np.divide(result.living_area,result.build_floor_area,out=np.zeros(len(result)),where=result.build_floor_area.to_numpy()>0)
    return result

def load_model():
    model=CatBoostRegressor(thread_count=1)
    model.load_model(str(MODEL))
    if len(model.feature_names_)!=101 or model.get_cat_feature_indices()!=[7,19]:
        raise ValueError('Неожиданный паспорт модели: 101 признак, категории land_use/morphotype')
    return model

def prepare(tag):
    actual=gpd.read_file(ROOT/f'data/processed/analysis/blocks_{tag}.geojson').to_crs(MCRS)
    baseline=gpd.read_file(ROOT/'data/processed/analysis/blocks_today.geojson').to_crs(MCRS)
    assert actual.index.equals(baseline.index) and actual.geometry.geom_equals(baseline.geometry).all()
    actual['land_use']=actual.land_use.map(lambda x:'missing' if pd.isna(x) else 'LandUse.'+str(x).split('.')[-1].upper())
    # Schema accepts only indicators, not the pre-existing Spacematrix morphotype.
    actual['morphotype']=get_strelka_morphotypes(actual[['l','fsi','mxi']])['morphotype'].fillna('missing')
    matrix=pd.read_pickle(ROOT/f'data/processed/analysis/acc_walk_{tag}.pkl')
    assert matrix.index.equals(actual.index) and matrix.columns.equals(actual.index)
    actual['area_accessibility']=area_accessibility(matrix,actual[['site_area']])['area_accessibility']
    result=baseline.copy()
    # Exercise Urbanomy scenario mechanics while preserving measured residents and living area.
    if tag!='today':
        result['population']=result.population.astype(float)
        for idx in actual.index[(actual.build_floor_area-baseline.build_floor_area).abs()>1e-6]:
            changes=actual.loc[idx,list(ORIGINAL_FEATURES)].to_dict()
            changes['land_use']=str(changes['land_use']).split('.')[-1].upper()
            result=ScenarioTEPModifier(result).apply(int(actual.at[idx,"id"]),changes)
        result=restore_actual_tep(result,actual)
    # Features/OD match canonical analysis, including land use changes outside building footprints.
    result.loc[:,list(ORIGINAL_FEATURES)]=actual.loc[:,list(ORIGINAL_FEATURES)]
    for col in set(ORIGINAL_FEATURES)-set(CATEGORICAL_FEATURES):
        result[col]=pd.to_numeric(result[col]).replace([np.inf,-np.inf],np.nan).fillna(0.)
    return result[['id',*ORIGINAL_FEATURES,'geometry']].copy()

class CachedEstimator(LandPriceEstimator):
    @staticmethod
    def _categorical_token(value):
        # Exact training_utils.prep_cat_inplace semantics; uppercase is a different category.
        if pd.isna(value):return 'missing'
        token=str(value)
        if token.startswith('LandUse.'):return token.split('.')[-1].upper()
        if token.upper() in {'RESIDENTIAL','BUSINESS','RECREATION','INDUSTRIAL','TRANSPORT','SPECIAL','AGRICULTURE'}:return token.upper()
        return token
    """Reuse identical geometry weights. Does not change distance/row normalisation."""
    def __init__(self,*args,weights=None,**kwargs):
        self.cached_weights=weights
        super().__init__(*args,**kwargs)
    def _build_distance_weights(self):
        return self.cached_weights if self.cached_weights is not None else super()._build_distance_weights()

def predict(blocks,model=None,weights=None):
    estimator=CachedEstimator(model=model or load_model(),blocks=blocks,weights=weights)
    return estimator.predict_prices(predictions_in_log_scale=True)

def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def save_frame(frame,path):
    frame.to_crs(4326).to_file(path,driver='GeoJSON')
    frame.drop(columns='geometry').to_csv(path.with_suffix('.csv'),index=False)

def map_delta(frame,path):
    import matplotlib.pyplot as plt
    import contextily as cx
    from matplotlib.patches import Patch
    from matplotlib_scalebar.scalebar import ScaleBar
    fig,ax=plt.subplots(figsize=(12,9))
    bins=[-np.inf,-10,-1,1,10,np.inf]
    labels=['Менее −10%','От −10 до −1%','От −1 до +1%','От +1 до +10%','Более +10%']
    colors=['#d73027','#fc8d59','#ffffbf','#91cf60','#1a9850']
    classes=pd.cut(frame.land_value_delta_pct,bins=bins,labels=False,include_lowest=True)
    frame.plot(color=[colors[int(c)] for c in classes],ax=ax,alpha=.8,edgecolor='#777',linewidth=.15)
    cache=ROOT/'data/cache/tiles';cache.mkdir(parents=True,exist_ok=True)
    cx.set_cache_dir(str(cache))
    cx.add_basemap(ax,source=cx.providers.Esri.WorldShadedRelief,crs=frame.crs,zoom=9,attribution='Подложка: © Esri',attribution_size=7)
    ax.annotate('С',xy=(.94,.97),xytext=(.94,.85),xycoords='axes fraction',ha='center',arrowprops={'arrowstyle':'->','color':'black'})
    ax.add_artist(ScaleBar(1,location='lower left',box_alpha=1))
    ax.legend(handles=[Patch(color=c,label=l) for c,l in zip(colors,labels)],title='Изменение полной стоимости',loc='lower right',facecolor='white',framealpha=1)
    ax.set_axis_off();fig.subplots_adjust(0,0.035,1,1)
    fig.text(.01,.008,'Учебная модель CatBoost; кварталы и OD: проект Приморск. EPSG:32635.',fontsize=9)
    fig.savefig(path,dpi=150);plt.close(fig)

def reference_area_hypothesis(blocks, matrix):
    """Alternative feature convention only; never change physical geometry or cashflows."""
    reference=blocks.copy()
    reference['site_area']=reference.to_crs(3857).area.to_numpy()
    reference['fsi']=reference.build_floor_area/reference.site_area
    reference['gsi']=reference.footprint_area/reference.site_area
    reference['morphotype']=get_strelka_morphotypes(reference[['l','fsi','mxi']])['morphotype'].fillna('missing')
    reference['area_accessibility']=area_accessibility(matrix,reference[['site_area']])['area_accessibility']
    return reference


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    model=load_model();base=None;summary=[];sensitivity=[]
    training=gpd.read_file(TRAIN) if TRAIN.exists() else None
    passport={'model':{'path':str(MODEL),'sha256':sha256(MODEL),'features':model.feature_names_,'categorical':['land_use','morphotype'],'categorical_encoding':'CBM CTR verified: uppercase land_use RESIDENTIAL/BUSINESS; lowercase Strelka; missing for null. LandUse.* and uppercase morphotype unseen.','target':'log1p(total land value RUB)','inverse':'expm1; unit=total/site_area','radii_m':list(RADIUS_LIST)},'training_reference':({'path':str(TRAIN),'sha256':sha256(TRAIN),'rows':len(training)} if training is not None else {'available':False,'note':'Диапазоны обучающего примера не проверены: внешний reference отсутствует.'}),'urbanomy_commit':'1f3ec003890524e557f56d7778d2393410dadd2e','accessibility':'BlocksNet area_accessibility, outgoing area-weighted mean walking OD minutes','limits':['Учебная модель; перенос на Приморск не валидирован рыночными сделками.','Прогноз не является кадастровой/рыночной оценкой и инвестиционной рекомендацией.','Нет доверительных интервалов, калибровки по Приморску и причинной интерпретации дельты.','Абсолютная цена не сопоставляется напрямую с кадастровой стоимостью участков: единица модели — квартал.','Файл модели и обучающий пример внешние, права на распространение не установлены.'],'inputs':{}}
    for tag in ['today','s1','s2']:
        blocks=prepare(tag);res=predict(blocks,model)
        if base is None:base=res.land_value.copy()
        res['land_value_before']=base
        res['land_value_delta']=res.land_value-base
        res['land_value_delta_pct']=100*(res.land_value/base-1)
        save_frame(res,OUT/f'land_{tag}.geojson')
        if tag!='today':map_delta(res,REPORT/f'land_delta_{tag}.png')
        numeric=[c for c in ORIGINAL_FEATURES if c not in CATEGORICAL_FEATURES]
        ranges={c:{'project_min':float(blocks[c].min()),'project_max':float(blocks[c].max()),'training_min':float(pd.to_numeric(training[c],errors='coerce').min()),'training_max':float(pd.to_numeric(training[c],errors='coerce').max()),'outside_training_range':int(((blocks[c]<pd.to_numeric(training[c],errors='coerce').min())|(blocks[c]>pd.to_numeric(training[c],errors='coerce').max())).sum())} for c in numeric} if training is not None else {}
        passport['inputs'][tag]={'blocks_sha256':sha256(ROOT/f'data/processed/analysis/blocks_{tag}.geojson'),'walk_od_sha256':sha256(ROOT/f'data/processed/analysis/acc_walk_{tag}.pkl'),'ranges':ranges}
        summary.append({'scenario':tag,'blocks':len(res),'population':int(res.population.sum()),'total_rub':float(res.land_value.sum()),'delta_rub':float(res.land_value_delta.sum()),'unit_median_rub_m2':float(res.land_value_per_sqm.median())})
        matrix=pd.read_pickle(ROOT/f'data/processed/analysis/acc_walk_{tag}.pkl')
        reference=reference_area_hypothesis(blocks,matrix)
        alternative=predict(reference,model)
        sensitivity.append({'scenario':tag,'physical_utm_total_rub':float(res.land_value.sum()),'reference_webmercator_site_total_rub':float(alternative.land_value.sum()),'sensitivity_minus_primary_rub':float(alternative.land_value.sum()-res.land_value.sum()),'status':'hypothesis_only_unverified_model_numeric_convention'})
        print(summary[-1],flush=True)
    pd.DataFrame(summary).to_csv(REPORT/'land_summary.csv',index=False)
    pd.DataFrame(sensitivity).to_csv(REPORT/'land_area_convention_sensitivity.csv',index=False)
    passport['numeric_convention']={'primary':'physical_utm EPSG32635 all physical areas','verification':'CBM numeric training area convention unverified: reference differs from CBM categories; no complete training provenance','sensitivity':'hypothesis only: reference_webmercator_site replaces site_area by EPSG3857 area and recomputes fsi/gsi, Strelka morphotype, area-weighted accessibility and their lags; other building areas, physical geometry/constraints and NPV unchanged','reference_evidence':'reference.site_area / geometry.area(EPSG3857) median1; /UTM32636area median3.88474835. Does not prove CBM convention.'}
    passport['limits'].append('Числовая конвенция площадей обучения CBM не подтверждена; sensitivity отдельная гипотеза, не исправленная цена.')
    (REPORT/'land_model_passport.json').write_text(json.dumps(passport,ensure_ascii=False,indent=2))
    return pd.DataFrame(summary)
if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',type=Path,default=MODEL,help='Внешний .cbm; также LAND_MODEL_PATH или PRIMORSK_LAND_MODEL')
    parser.add_argument('--training-reference',type=Path,default=TRAIN,help='Необязательный внешний GeoJSON для проверки диапазонов, не обучение')
    args=parser.parse_args()
    MODEL=args.model;TRAIN=args.training_reference
    main()
