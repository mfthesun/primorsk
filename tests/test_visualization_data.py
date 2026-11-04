"""Проверка пространственного присоединения: без подмены ближайшим объектом."""
import json
import sys
import unittest
from pathlib import Path
import geopandas as gpd
from shapely.geometry import box, Point
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from visualization_data import assign_services, feature_collection

class VisualizationDataTest(unittest.TestCase):
    def test_smallest_intersection_and_outdoor_are_explicit(self):
        buildings = gpd.GeoDataFrame({'stable_id':['today_1','today_2']}, geometry=[box(0,0,10,10), box(2,2,4,4)], crs=32635)
        services = gpd.GeoDataFrame({'service_id':[1,2,3], 'service_name':['Школа','Магазин','Остановка'], 'capacity':[20,0,0], 'service_type':['school','convenience','bus_stop']}, geometry=[Point(3,3),Point(11,11),Point(20,20)], crs=32635)
        out, report = assign_services(buildings, services)
        self.assertEqual(out.iloc[0].services, [])
        self.assertEqual(out.iloc[1].services[0]['capacity'],20)
        self.assertEqual(report['ambiguous'],1)
        self.assertEqual(report['unmatched'],1)
        self.assertEqual(report['outdoor'],1)
        self.assertEqual(report['records'][1]['status'],'unmatched')
    def test_nested_json_and_missing_values(self):
        buildings=gpd.GeoDataFrame({'stable_id':['scenario_1'], 'services':[[{'service':4,'name':'<школа>','capacity':10}]], 'provision':[{'school':None}], 'population':[float('nan')]},geometry=[box(28,60,28.001,60.001)],crs=4326)
        result=feature_collection(buildings)
        encoded=json.dumps(result,allow_nan=False)
        self.assertIsNone(result['features'][0]['properties']['population'])
        self.assertIsInstance(result['features'][0]['properties']['services'],list)
        self.assertEqual(result['features'][0]['id'],'scenario_1')
        self.assertIn('school',encoded)
if __name__=='__main__': unittest.main()
