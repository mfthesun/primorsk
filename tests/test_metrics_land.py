"""Protect land value units and missing-data behavior in the public TEP table."""
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import metrics

class LandMetricsTest(unittest.TestCase):
    def test_total_is_converted_to_millions_not_mistaken_for_unit_price(self):
        self.assertTrue(hasattr(metrics,"land_value_rows"),"land integration missing")
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"summary.csv"
            p.write_text("scenario,total_rub,delta_rub,unit_median_rub_m2\ntoday,1200000,0,300\ns1,1500000,300000,350\ns2,1800000,600000,400\n")
            rows=metrics.land_value_rows(p)
            self.assertEqual([rows[0][t] for t in ["today","s1","s2"]],[1.2,1.5,1.8])
            self.assertEqual(rows[1]["s2"],400)
    def test_absent_run_is_unknown_not_zero_land_value(self):
        self.assertTrue(hasattr(metrics,"land_value_rows"),"land integration missing")
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(metrics.land_value_rows(Path(d)/"missing.csv"),[])

if __name__=="__main__":unittest.main()
