"""Защита смысла целевой переменной, демографии и ограничений оптимизации."""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import box
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from land_value import restore_actual_tep, inverse_prices, ORIGINAL_FEATURES

def test_log_target_is_total_not_unit():
    total, unit = inverse_prices(np.log1p([1000., 5000.]), np.array([100., 250.]))
    np.testing.assert_allclose(total, [1000,5000])
    np.testing.assert_allclose(unit, [10,20])

def test_actual_population_and_living_area_override_urbanomy_default():
    source = gpd.GeoDataFrame({'population':[0,35], 'living_area':[800.,1400.], 'build_floor_area':[1000.,2000.]},geometry=[box(0,0,1,1),box(1,0,2,1)])
    modified=source.assign(population=[40.,70.],living_area=[700.,1300.])
    out=restore_actual_tep(modified,source)
    assert out.population.tolist()==[0,35]
    assert out.living_area.tolist()==[800.,1400.]
    np.testing.assert_allclose(out.non_living_area,[200.,600.])

def test_infeasible_campus_is_not_repaired_into_fake_floors():
    from district_optimization import physical_floor_constraint
    # Даже при максимальном пятне исходная BFA общежития не помещается в шесть этажей.
    assert physical_floor_constraint(1.,1.2,np.array([9172.7]),np.array([749.41]),6)>0

def test_cached_weights_do_not_change_prediction():
    from land_value import prepare, load_model, CachedEstimator
    blocks=prepare('today').iloc[:12].copy()
    model=load_model()
    first=CachedEstimator(model=model,blocks=blocks)
    second=CachedEstimator(model=model,blocks=blocks,weights=first._weights)
    np.testing.assert_array_equal(first.predict().land_value,second.predict().land_value)

def test_experimental_change_preserves_residents_and_outside_buildings():
    from district_optimization import FixedProgrammeProblem,project_blocks
    from land_value import prepare,load_model,CachedEstimator,predict
    blocks=prepare('s2');model=load_model()
    estimator=CachedEstimator(model=model,blocks=blocks)
    project=project_blocks().query("project == 'marina'").iloc[0]
    problem=FixedProgrammeProblem(blocks,model,project,estimator)
    x=np.array([.93,1.08]);after=problem.candidate(x)
    assert after.population.equals(blocks.population)
    assert after.living_area.equals(blocks.living_area)
    other=blocks.index!=problem.label
    pd.testing.assert_frame_equal(after.loc[other,list(ORIGINAL_FEATURES)],blocks.loc[other,list(ORIGINAL_FEATURES)],check_dtype=False)
    predicted=predict(after,model,estimator._weights)
    fast=problem.evaluate(x[None,:],return_as_dictionary=True)
    np.testing.assert_allclose(-fast['F'][0,0],predicted.land_value.sum(),rtol=1e-12)
    np.testing.assert_allclose(-fast['F'][0,1],problem.direct_npv(x[1],predicted.loc[problem.label,'land_value']*problem.site_fraction),atol=.1)

def test_categories_are_registered_in_actual_cbm_ctr_hashes(tmp_path):
    import json,runpy
    from catboost import Pool
    from land_value import load_model,CachedEstimator
    model=load_model()
    land=['RESIDENTIAL','BUSINESS','LandUse.RESIDENTIAL','LandUse.BUSINESS']
    morph=['individual residential','low-rise non-residential','low-rise model','mid-rise','missing','INDIVIDUAL RESIDENTIAL','LOW-RISE NON-RESIDENTIAL']
    tokens=list(dict.fromkeys(land+morph))
    dm=pd.DataFrame(np.zeros((len(tokens),101)),columns=model.feature_names_)
    dm['land_use']=tokens;dm['morphotype']=tokens
    pool=Pool(dm,cat_features=[7,19])
    code=tmp_path/'probe.py';meta=tmp_path/'probe.json'
    model.save_model(str(code),format='python',pool=pool)
    model.save_model(str(meta),format='json')
    module=runpy.run_path(str(code));data=json.loads(meta.read_text())
    hashes={}
    for key,value in data['ctr_data'].items():
        ident=json.loads(key)['identifier']
        if len(ident)==1 and ident[0].get('combination_element')=='cat_feature_value':
            cat=ident[0]['cat_feature_index']
            hashes[cat]=set(map(int,value['hash_map'][::value['hash_stride']]))
    def seen(cat,token):
        raw=module['cat_features_hashes'][token]
        return module['calc_hash'](0,raw) in hashes[cat]
    assert seen(0,'RESIDENTIAL') and seen(0,'BUSINESS')
    assert not seen(0,'LandUse.RESIDENTIAL') and not seen(0,'LandUse.BUSINESS')
    for token in morph[:5]:assert seen(1,token)
    for token in morph[5:]:assert not seen(1,token)
    assert CachedEstimator._categorical_token('LandUse.RESIDENTIAL')=='RESIDENTIAL'
    assert CachedEstimator._categorical_token('individual residential')=='individual residential'


def test_reference_area_hypothesis_recalculates_area_weighted_od():
    import land_value
    assert hasattr(land_value, 'reference_area_hypothesis'), 'sensitivity feature chain missing'
    frame=gpd.GeoDataFrame({'site_area':[100.,200.], 'build_floor_area':[1000.,2000.],
        'footprint_area':[200.,400.], 'living_area':[0.,0.], 'fsi':[10.,10.],
        'gsi':[2.,2.], 'l':[5.,5.], 'mxi':[0.,0.], 'morphotype':['old','old']},
        geometry=[box(3100000,8400000,3100100,8400100),box(3100200,8400000,3100400,8400200)],crs=3857).to_crs(32635)
    od=pd.DataFrame([[0.,10.],[20.,0.]])
    out=land_value.reference_area_hypothesis(frame,od)
    np.testing.assert_allclose(out.site_area,[10000.,40000.],rtol=1e-8)
    np.testing.assert_allclose(out.fsi,[.1,.05],rtol=1e-8)
    np.testing.assert_allclose(out.gsi,[.02,.01],rtol=1e-8)
    np.testing.assert_allclose(out.area_accessibility,[8.,4.],rtol=1e-8)
    np.testing.assert_array_equal(out.build_floor_area,frame.build_floor_area)
    assert list(out.morphotype)!=['old','old']
    assert out.geometry.geom_equals(frame.geometry).all()

def test_checkpoint_rejects_stale_model_or_code_signature():
    import district_optimization as optimization
    assert hasattr(optimization, 'checkpoint_matches'), 'unsafe checkpoint resume'
    record={'input_signature':'model-and-code-A','generations_executed':100,'evaluations':6400}
    assert optimization.checkpoint_matches(record,'model-and-code-A')
    assert not optimization.checkpoint_matches(record,'model-and-code-B')
    assert not optimization.checkpoint_matches({'generations_executed':100},'model-and-code-A')
    assert not optimization.checkpoint_matches({**record,'generations_executed':20},'model-and-code-A')
