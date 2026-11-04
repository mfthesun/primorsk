"""Contract tests for reproducible course exports; no production fixtures required."""
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
import geopandas as gpd
import networkx as nx
from shapely.geometry import LineString, Point, Polygon, box
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from analytical_exports import graph_tables, export_graph, stable_ids, allocation_layers, write
from blocks_generation import compare_blocks
import pandas as pd
from types import SimpleNamespace

class ExportsTest(unittest.TestCase):
    def test_graph_weights_crs_and_pickle(self):
        g = nx.Graph(crs=32635)
        g.add_node(0,x=589000.,y=6693000.)
        g.add_node(1,x=589100.,y=6693000.)
        g.add_edge(0,1,length_meter=100.,time_min=1.2,geometry=LineString([(589000,6693000),(589100,6693000)]))
        nodes,edges=graph_tables(g,'s2','walk')
        self.assertEqual(nodes.crs.to_epsg(),4326)
        self.assertEqual(edges.iloc[0].time_min,1.2)
        self.assertEqual(edges.iloc[0].scenario,'s2')
        with TemporaryDirectory() as tmp:
            export_graph(g,Path(tmp),'s2','walk')
            import pickle
            with open(Path(tmp)/'graph_walk.pkl','rb') as stream:
                loaded=pickle.load(stream)
            self.assertEqual(loaded[0][1]['length_meter'],100.)

    def test_polygon_export_repairs_self_intersection_without_hull(self):
        bowtie=Polygon([(28,60),(28.01,60.01),(28,60.01),(28.01,60),(28,60)])
        frame=gpd.GeoDataFrame(geometry=[bowtie],crs=4326)
        with TemporaryDirectory() as tmp:
            path=Path(tmp)/'coverage.geojson'
            write(frame,path)
            exported=gpd.read_file(path)
            self.assertTrue(exported.is_valid.all())
            self.assertEqual(exported.geom_type.iloc[0],'MultiPolygon')
            self.assertAlmostEqual(exported.geometry.iloc[0].area,0.00005)

    def test_ids_survive_filtering_and_scenario_collision(self):
        df=pd.DataFrame({'id':[7,7], 'is_scenario':[False,True]})
        ids=stable_ids(df,'building')
        self.assertEqual(list(ids),['building:existing:7','building:scenario:7'])
        self.assertEqual(stable_ids(df.iloc[[1]],'building').iloc[0],ids.iloc[1])

    def test_links_from_actual_sparse_allocation_and_capacity_metrics(self):
        b=gpd.GeoDataFrame({'object_id':['b0','b1']},geometry=[Point(0,0),Point(10,0)],crs=32635)
        s=gpd.GeoDataFrame({'object_id':['s0'],'capacity':[5],'capacity_status':['source_reported']},geometry=[Point(20,0)],crs=32635)
        flow=pd.DataFrame({0:pd.arrays.SparseArray([2.25,2.75],fill_value=0.)})
        pr=SimpleNamespace(flow=flow,demand_rows=pd.DataFrame({'demand':[2,3]}),capacity_rows=pd.DataFrame({'capacity':[5],'capacity_left':[0]}),distance_matrix=pd.DataFrame({0:[1.,9.]}))
        outb,outs,links=allocation_layers(b,s,pr,'today','school',7)
        self.assertEqual(links.allocated.sum(),5)
        self.assertEqual(list(links.within_threshold),[True,False])
        self.assertEqual(list(links.building_id),['b0','b1'])
        self.assertEqual(outs.iloc[0].capacity_left,0)

    def test_block_comparison_detects_split_and_uncovered_area(self):
        canonical=gpd.GeoDataFrame(geometry=[box(0,0,10,10)],crs=32635)
        generated=gpd.GeoDataFrame(geometry=[box(0,0,5,10),box(5,0,9,10)],crs=32635)
        metrics,pairs=compare_blocks(generated,canonical,canonical)
        self.assertEqual(metrics['canonical_count'],1)
        self.assertAlmostEqual(metrics['canonical_area_covered_share'],.9)
        self.assertEqual(len(pairs),2)
        self.assertEqual(metrics['canonical_split_count'],1)

if __name__=='__main__':unittest.main()
