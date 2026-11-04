"""NSGA-II Urbanomy: независимый эксперимент каждого проектного квартала на фоне s2."""
from __future__ import annotations
import json
import time
import numpy as np
import pandas as pd
import geopandas as gpd
from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.optimize import minimize
from pymoo.core.callback import Callback
from pymoo.util.nds.non_dominated_sorting import NonDominatedSorting
from urbanomy.methods.land_value_modeling.ga_mc_optimizer import DistrictProblem
from urbanomy.methods.investment_potential import InvestmentAttractivenessAnalyzer
from land_value import (ROOT,OUT,REPORT,ORIGINAL_FEATURES,CATEGORICAL_FEATURES,RADIUS_LIST,
                        load_model,prepare,CachedEstimator,ScenarioTEPModifier,restore_actual_tep,
                        get_strelka_morphotypes,predict,save_frame)
from scenarios import BUILDING_USE,DEFAULT_USE

def physical_floor_constraint(gfa_factor,footprint_factor,gfa,footprint,max_floors):
    return float(np.max(np.asarray(gfa)*gfa_factor/(np.asarray(footprint)*footprint_factor))-max_floors)

def project_blocks():
    blocks=prepare('s2')
    sites=gpd.read_file(ROOT/'data/processed/scenario/boundary.geojson').to_crs(blocks.crs)
    # Парусная школа — функция марины (решение 04.11.2026, docs/implementation-ledger.md):
    # отдельной программы застройки нет, территория школы в оптимизацию не входит.
    names={'Кампус ИНТЦ «Приморская долина»':'campus','Марина, рыбный рынок, клубный дом':'marina'}
    sites=sites[sites['name'].isin(names)]
    kinder=gpd.read_file(ROOT/'data/raw/scenario_design/kindergarten_site.geojson').to_crs(blocks.crs)
    rows=[]
    for name,geom in list(zip(sites['name'].map(names),sites.geometry))+[('kindergarten',kinder.union_all())]:
        for idx in blocks.index[blocks.geometry.intersects(geom)]:
            area=blocks.at[idx,'geometry'].intersection(geom).area
            if area>1e-8:
                rows.append({'project':name,'id':int(blocks.at[idx,'id']),'site_area':area,'geometry':blocks.at[idx,'geometry'].intersection(geom)})
    return gpd.GeoDataFrame(rows,crs=blocks.crs)

class FixedProgrammeProblem(DistrictProblem):
    """No mix/population genes; project-only footprint and GFA scale factors.

    Land objective follows DistrictProblem (sum of all block values). NPV uses the
    fixed project building uses and the project's share of predicted block land
    cost, avoiding demolition/redevelopment of the rest of the block.
    """
    def __init__(self,blocks,model,project,estimator):
        self.project=project
        super().__init__(blocks=blocks,model=model,estimator_kwargs={'orig_features':ORIGINAL_FEATURES,'categorical_features':CATEGORICAL_FEATURES},constraints={'footprint_factor':{'min':.8,'max':1.2},'gfa_factor':{'min':1.,'max':1.2}},target_id=int(project.id))
        self.n_ieq_constr=2
        self.label=self._resolve_target_label()
        self.row=blocks.loc[self.label]
        buildings=gpd.read_file(ROOT/'data/processed/scenario/building.geojson').to_crs(blocks.crs)
        # Exactly the canonical aggregator: representative point, nearest if outside.
        points=buildings[['geometry']].copy();points.geometry=points.representative_point()
        joined=gpd.sjoin(points,blocks[['geometry']],how='left')
        joined=joined[~joined.index.duplicated()]
        missing=joined.index[joined.index_right.isna()]
        if len(missing):
            nearest=gpd.sjoin_nearest(points.loc[missing],blocks[['geometry']],how='left')
            nearest=nearest[~nearest.index.duplicated()]
            joined.loc[missing,'index_right']=nearest.index_right
        self.buildings=buildings.loc[joined.index_right==self.label].copy()
        if self.buildings.empty:raise ValueError(f'No project building in quarter {self.target_id}')
        self.bfa=float(self.buildings.build_floor_area.sum())
        self.footprint=float(self.buildings.footprint_area.sum())
        self.floor_max=float(self.buildings.number_of_floors.max()+1)
        existing=gpd.read_file(ROOT/'data/processed/building.geojson').to_crs(blocks.crs)
        existing_footprint=existing.geometry.intersection(project.geometry).union_all().area
        self.available_site=float(project.site_area-existing_footprint)
        self.site_capacity_proof={'project':str(project.project),'block_id':int(project.id),'site_area_m2':float(project.site_area),'existing_footprint_m2':float(existing_footprint),'available_m2':self.available_site,'upper_project_footprint_m2':self.footprint*1.2,'upper_bound_feasible':bool(self.footprint*1.2<=self.available_site)}
        # Capacity is redundant across the entire gene domain; fail if this proof stops holding.
        if not self.site_capacity_proof['upper_bound_feasible']:
            self.n_ieq_constr=3
        self.estimator=estimator
        self.base_dm=estimator._align_features_to_model(estimator._design_matrix(blocks))
        self.base_values=np.expm1(model.predict(self.base_dm,thread_count=1))
        self.base_total=float(self.base_values.sum())
        self.numeric=[c for c in ORIGINAL_FEATURES if c not in CATEGORICAL_FEATURES]
        self.numeric_model=[c for c in model.feature_names_ if c not in CATEGORICAL_FEATURES]
        self.positions={c:i for i,c in enumerate(self.numeric_model)}
        self.affected=np.unique(np.r_[self.label,*[w.sparse[:,self.label].nonzero()[0] for w in estimator._weights.values()]])
        self.target_position=int(np.where(self.affected==self.label)[0][0])
        self.base_numeric=self.base_dm.loc[self.affected,self.numeric_model].to_numpy(float)
        self.base_cats=self.base_dm.loc[self.affected,list(CATEGORICAL_FEATURES)]
        self.influence={radius:w.sparse[self.affected,self.label].toarray().ravel() for radius,w in estimator._weights.items()}
        self.site_fraction=float(project.site_area/self.row.site_area)
        inputs=json.loads((ROOT/'data/raw/urbanomy_inputs.json').read_text())
        self.analyzer=InvestmentAttractivenessAnalyzer(benchmarks={k:v for k,v in inputs['benchmarks'].items() if not k.startswith('_')})
        self.npv0=self.direct_npv(1.,0.)
        self.npv_slope=(self.direct_npv(1.2,0.)-self.npv0)/.2
        self.land_slope=(self.direct_npv(1.,1e7)-self.npv0)/1e7
        expected=self.npv0+self.npv_slope*.073+self.land_slope*3e6
        np.testing.assert_allclose(self.direct_npv(1.073,3e6),expected,atol=.02,rtol=1e-10)

    def direct_npv(self,gfa_factor,land_cost):
        b=self.buildings.copy()
        b['land_use']=b.id.map(BUILDING_USE).fillna(DEFAULT_USE)
        b['build_floor_area']=b.build_floor_area*gfa_factor
        b['non_living_area']=b.build_floor_area-b.living_area
        b['site_area']=float(self.project.site_area)*b.build_floor_area/b.build_floor_area.sum()
        b['land_value']=land_cost*b.site_area/b.site_area.sum()
        b['build_floor_area_before']=0. # additions only, no demolition of nonproject buildings
        b['is_project']=True
        res=self.analyzer.calculate_investment_metrics(b,discount_rate=.18,show_project_totals=False,show_warning=False)
        return float(pd.to_numeric(res.NPV).sum())

    def _repair_genome(self,genome):
        fp=float(genome['footprint_factor']);gf=float(genome['gfa_factor'])
        row=self.row
        footprint=float(row.footprint_area+self.footprint*(fp-1))
        build=float(row.build_floor_area+self.bfa*(gf-1))
        result={'footprint_area':footprint,'build_floor_area':build,'living_area':float(row.living_area),'non_living_area':build-float(row.living_area),'population':int(row.population),'fsi':build/row.site_area,'gsi':footprint/row.site_area,'mxi':row.living_area/build if build else 0.,'l':build/footprint if footprint else 0.}
        result['morphotype']=get_strelka_morphotypes(pd.DataFrame([{k:result[k] for k in ['l','fsi','mxi']}]))['morphotype'].fillna('missing').iloc[0]
        return result

    def candidate(self,x):
        changes=self._repair_genome(dict(zip(self.var_names,x)))
        modifier_input=self.blocks.copy()
        modifier_input['population']=modifier_input.population.astype(float)
        after=ScenarioTEPModifier(modifier_input).apply(self.target_id,changes)
        # apply() estimates living_area/20; restore observed permanent residents.
        after['population']=self.blocks.population.copy()
        after.at[self.label,'living_area']=float(self.row.living_area)
        after.at[self.label,'non_living_area']=changes['non_living_area']
        after.at[self.label,'mxi']=changes['mxi']
        assert after.population.equals(self.blocks.population)
        return after

    def _evaluate(self,X,out,*args,**kwargs):
        X=np.atleast_2d(X);count=len(X);n=len(self.affected)
        repaired=[self._repair_genome(dict(zip(self.var_names,x))) for x in X]
        numeric=np.broadcast_to(self.base_numeric,(count,*self.base_numeric.shape)).copy()
        for c in self.numeric:
            values=np.array([r.get(c,self.row[c]) for r in repaired],dtype=float)
            numeric[:,self.target_position,self.positions[c]]=values
            delta=values-float(self.row[c])
            for radius,influence in self.influence.items():
                numeric[:,:,self.positions[f'lag{radius}_{c}']]+=delta[:,None]*influence[None,:]
        dm=pd.DataFrame(numeric.reshape(count*n,-1),columns=self.numeric_model)
        for c in CATEGORICAL_FEATURES:
            cats=np.tile(self.base_cats[c].to_numpy(),(count,1))
            if c=='morphotype':cats[:,self.target_position]=[str(r[c]) for r in repaired]
            dm[c]=cats.ravel()
        predictions=np.expm1(self.model.predict(dm[self.model.feature_names_],thread_count=1)).reshape(count,n)
        totals=self.base_total-self.base_values[self.affected].sum()+predictions.sum(axis=1)
        land_cost=predictions[:,self.target_position]*self.site_fraction
        npv=self.npv0+self.npv_slope*(X[:,1]-1)+self.land_slope*land_cost
        out['F']=-np.column_stack([totals,npv])
        floors=np.array([physical_floor_constraint(x[1],x[0],self.buildings.build_floor_area.to_numpy(),self.buildings.footprint_area.to_numpy(),self.floor_max) for x in X])
        footprints=np.array([r['footprint_area']/self.row.site_area-.8 for r in repaired])
        out['G']=np.column_stack([floors,footprints])
        if self.n_ieq_constr==3:out['G']=np.column_stack([out['G'],self.footprint*X[:,0]-self.available_site])

class History(Callback):
    def __init__(self):super().__init__();self.rows=[]
    def notify(self,algorithm):
        F=algorithm.pop.get('F');cv=algorithm.pop.get('CV').ravel();valid=cv<=1e-8
        self.rows.append({'generation':int(algorithm.n_gen),'evaluations':int(algorithm.evaluator.n_eval),'feasible':int(valid.sum()),'min_cv':float(cv.min()),'max_land_rub':float(-F[valid,0].min()) if valid.any() else None,'max_npv_rub':float(-F[valid,1].min()) if valid.any() else None})
        if algorithm.n_gen%25==0:print('generation',algorithm.n_gen,'feasible',valid.sum(),'min CV',cv.min(),flush=True)

def checkpoint_matches(record, signature):
    return (record.get('input_signature')==signature
            and record.get('generations_executed')==100
            and record.get('evaluations')==6400)

def input_signature():
    import hashlib
    import land_value
    paths=[land_value.MODEL,ROOT/'scripts/land_value.py',ROOT/'scripts/district_optimization.py',
           ROOT/'data/raw/urbanomy_inputs.json',ROOT/'data/processed/scenario/building.geojson',
           ROOT/'data/processed/scenario/boundary.geojson',ROOT/'data/processed/building.geojson',
           ROOT/'data/raw/scenario_design/kindergarten_site.geojson',
           ROOT/'data/processed/analysis/blocks_s2.geojson',ROOT/'data/processed/analysis/acc_walk_s2.pkl']
    digest=hashlib.sha256(b'nsga2:64:100:seeds42,43,44:physical_utm:v1')
    for path in paths:
        digest.update(str(path.name).encode());digest.update(path.read_bytes())
    return digest.hexdigest()


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    blocks=prepare('s2');model=load_model();estimator=CachedEstimator(model=model,blocks=blocks)
    projects=project_blocks();projects.drop(columns='geometry').to_csv(REPORT/'optimization_targets.csv',index=False)
    all_front=[];runs=[];selected=[];diagnostics=[];site_proofs=[]
    signature=input_signature()
    for _,project in projects.iterrows():
        name=project.project;pid=int(project.id)
        print('PROJECT',name,'quarter',pid,flush=True)
        problem=FixedProgrammeProblem(blocks,model,project,estimator)
        site_proofs.append(problem.site_capacity_proof)
        diag=problem.buildings[['id','build_floor_area','footprint_area','number_of_floors']].copy()
        diag['project']=name;diag['block_id']=pid
        diag['physical_floors']=diag.build_floor_area/diag.footprint_area
        diag['min_possible_physical_floors']=diag.physical_floors/1.2
        diag['max_allowed_floors']=problem.floor_max
        diagnostics.append(diag)
        # Validate accelerated objective against actual Urbanomy modifier + estimator.
        direct=problem.candidate(np.array([1.,1.]))
        direct_pred=predict(direct,model,estimator._weights)
        check=problem.evaluate(np.array([[1.,1.]]),return_as_dictionary=True)
        np.testing.assert_allclose(-check['F'][0,0],direct_pred.land_value.sum(),rtol=1e-12,atol=.001)
        for seed in [42,43,44]:
            checkpoint=REPORT/f'optimization_run_{name}_{seed}.json'
            front_checkpoint=REPORT/f'optimization_seed_front_{name}_{seed}.csv'
            record=json.loads(checkpoint.read_text()) if checkpoint.exists() else {}
            if checkpoint_matches(record,signature) and (not record['feasible_front'] or front_checkpoint.exists()):
                runs.append(record)
                if record['feasible_front']:all_front.append(pd.read_csv(front_checkpoint))
                print('RESUME',name,seed,flush=True)
                continue
            t=time.monotonic();hist=History()
            rng=np.random.default_rng(seed)
            initial=np.column_stack([rng.uniform(.8,1.2,64),rng.uniform(1.,1.2,64)])
            initial[0]=[1.,1.] # original programme included, never falsely marked feasible
            result=minimize(problem,NSGA2(pop_size=64,sampling=initial),('n_gen',100),seed=seed,callback=hist,verbose=False)
            pd.DataFrame(hist.rows).to_csv(REPORT/f'optimization_history_{name}_{seed}.csv',index=False)
            feasible=result.X is not None
            runs.append({'project':name,'block_id':pid,'seed':seed,'population':64,'generations':100,'evaluations':int(result.algorithm.evaluator.n_eval),'feasible_front':bool(feasible),'seconds':time.monotonic()-t,'original_feasible':bool(np.all(check['G'][0]<=0)),'max_floor_limit':problem.floor_max,'generations_requested':100,'generations_executed':100,'status':'completed' if feasible else 'infeasible'})
            if feasible:
                frame=pd.DataFrame(np.atleast_2d(result.X),columns=problem.var_names)
                frame[['land_value_total_rub','investor_npv_rub']]=-np.atleast_2d(result.F)
                frame['project']=name;frame['block_id']=pid;frame['seed']=seed
                all_front.append(frame)
                frame.to_csv(front_checkpoint,index=False)
            runs[-1]['input_signature']=signature
            checkpoint.write_text(json.dumps(runs[-1],ensure_ascii=False,indent=2))
            print(runs[-1],flush=True)
        front=pd.concat([f for f in all_front if (f.project==name).all()],ignore_index=True) if any((f.project==name).all() for f in all_front) else pd.DataFrame()
        if len(front):
            obj=front[['land_value_total_rub','investor_npv_rub']].to_numpy()
            nd=NonDominatedSorting().do(-obj,only_non_dominated_front=True)
            front=front.iloc[nd].drop_duplicates(['footprint_factor','gfa_factor']).reset_index(drop=True)
            front.to_csv(REPORT/f'optimization_front_{name}.csv',index=False)
            values=front[['land_value_total_rub','investor_npv_rub']].to_numpy()
            normal=(values-values.min(axis=0))/np.maximum(np.ptp(values,axis=0),1e-12)
            choices={'land_extreme':int(values[:,0].argmax()),'npv_extreme':int(values[:,1].argmax()),'compromise':int(np.square(1-normal).sum(axis=1).argmin())}
            for choice,pos in choices.items():
                row=front.iloc[pos];x=row[problem.var_names].to_numpy(float)
                after=problem.candidate(x);pred=predict(after,model,estimator._weights)
                direct_npv=problem.direct_npv(x[1],pred.loc[problem.label,'land_value']*problem.site_fraction)
                np.testing.assert_allclose([pred.land_value.sum(),direct_npv],row[['land_value_total_rub','investor_npv_rub']].to_numpy(float),rtol=1e-10,atol=.1)
                constraints=problem.evaluate(x[None,:],return_as_dictionary=True)['G'][0]
                assert np.all(constraints<=1e-8)
                pred['experimental']=True;pred['variant']=choice
                pred['is_project_target']=pred.id==pid
                pred['land_value_before']=problem.base_values
                pred['land_value_delta']=pred.land_value-problem.base_values
                pred['land_value_delta_pct']=100*(pred.land_value/problem.base_values-1)
                save_frame(pred,OUT/f'optimization_{name}_{choice}.geojson')
                selected.append({**row.to_dict(),'choice':choice,'recalculated_land_rub':float(pred.land_value.sum()),'recalculated_npv_rub':direct_npv,'max_constraint':float(constraints.max())})
    pd.DataFrame(site_proofs).to_csv(REPORT/'optimization_site_capacity.csv',index=False)
    pd.DataFrame(runs).to_csv(REPORT/'optimization_runs.csv',index=False)
    pd.DataFrame(selected).to_csv(REPORT/'optimization_selected.csv',index=False)
    pd.concat(diagnostics).to_csv(REPORT/'optimization_building_diagnostics.csv',index=False)
    if all_front:pd.concat(all_front).to_csv(REPORT/'optimization_front_all_seeds.csv',index=False)
    plot_results(runs,selected)
    return pd.DataFrame(runs)

def plot_results(runs,selected):
    names={'campus':'Кампус','marina':'Марина','kindergarten':'Детский сад'}
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter
    fig,ax=plt.subplots(figsize=(12,9))
    for name in sorted({r['project'] for r in runs}):
        p=REPORT/f'optimization_front_{name}.csv'
        if p.exists():
            f=pd.read_csv(p);ax.scatter(f.land_value_total_rub/1e9,f.investor_npv_rub/1e6,label=names[name],s=18)
    ax.set_xlabel('Полная стоимость земли поселения, млрд ₽');ax.set_ylabel('NPV проекта, млн ₽')
    ax.legend(facecolor='white');ax.grid(alpha=.25);fig.tight_layout();fig.savefig(REPORT/'optimization_pareto.png',dpi=150);plt.close(fig)
    fig,axes=plt.subplots(2,2,figsize=(12,9))
    done=sorted({r['project'] for r in runs})
    for ax,name in zip(axes.ravel(),done):
        for seed in [42,43,44]:
            f=pd.read_csv(REPORT/f'optimization_history_{name}_{seed}.csv')
            ax.plot(f.generation,f.max_npv_rub/1e6,label=str(seed))
        ax.set_xlabel('Поколение');ax.set_ylabel(f'{names[name]}: макс. NPV, млн ₽');ax.legend(facecolor='white');ax.grid(alpha=.25)
    for ax in axes.ravel()[len(done):]:
        ax.set_axis_off()
    fig.tight_layout();fig.savefig(REPORT/'optimization_convergence.png',dpi=150);plt.close(fig)
if __name__=='__main__':
    import argparse
    import land_value
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',type=land_value.Path,default=land_value.MODEL,help='Внешний .cbm; также LAND_MODEL_PATH')
    args=parser.parse_args()
    land_value.MODEL=args.model
    main()
