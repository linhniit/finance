import importlib.util
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
spec = importlib.util.spec_from_file_location('update_data', Path(__file__).parents[1] / 'scripts/update_data.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class DataTests(unittest.TestCase):
    def test_vietnam_price_units_and_timezone(self):
        p = module.mh_point({'dateTime':'29/09/2026 18:15','buyingPrice':14100000,'sellingPrice':14250000}, 'snapshot')
        self.assertEqual(p['value'], 14250000)
        self.assertEqual(p['time'], '2026-09-29T18:15:00+07:00')

    def test_closed_market_zeros_are_not_zero_prices(self):
        p = module.bi_point({'Date':'09/26/26','Close':25971,'Open':0,'High':0,'Low':0})
        self.assertEqual(p['value'],25971)
        self.assertNotIn('low',p)
        for invalid in [0,-1,float('nan'),float('inf')]:
            with self.assertRaises(ValueError): module.positive(invalid)

    def test_official_close_replaces_snapshot_without_duplicates(self):
        now = datetime(2026,9,29,tzinfo=module.TZ)
        points = module.merge_history([{'date':'2026-09-28','value':4200}], [{'date':'2026-09-28','value':4115.27,'kind':'close'}], now)
        self.assertEqual(len(points),1)
        self.assertEqual(points[0]['value'],4115.27)

    def test_source_failure_keeps_history_and_old_timestamp(self):
        prior = {'updatedAt':'2026-09-28T18:00:00+07:00','markets':{'SJC':{'history':[{'date':'2026-09-28','value':1}], 'lastSuccessAt':'2026-09-28T18:00:00+07:00'}}}
        with patch.object(module,'fetch',side_effect=RuntimeError('offline')):
            result,failed = module.update(prior,datetime(2026,9,29,tzinfo=module.TZ))
        self.assertEqual(result['markets']['SJC']['history'],prior['markets']['SJC']['history'])
        self.assertEqual(result['updatedAt'],prior['updatedAt'])
        self.assertEqual(result['markets']['SJC']['status'],'error')
        self.assertEqual(len(failed),4)
        self.assertNotIn('status',prior['markets']['SJC'])

    def test_embedded_json_is_parsed_without_executing_scripts(self):
        self.assertEqual(module.embedded_json('priceSection: {"currentValue": 42}, malicious()', 'priceSection')['currentValue'],42)
        with self.assertRaises(ValueError): module.embedded_json('changed markup', 'priceSection')

if __name__ == '__main__': unittest.main()
