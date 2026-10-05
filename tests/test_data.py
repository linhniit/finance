import importlib.util
import json
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
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
        prior = {'updatedAt':'2026-09-28T18:00:00+07:00','markets':{'985':{'history':[{'date':'2026-09-28','value':1}], 'lastSuccessAt':'2026-09-28T18:00:00+07:00'}}}
        with patch.object(module,'fetch',side_effect=RuntimeError('offline')):
            result,failed = module.update(prior,datetime(2026,9,29,tzinfo=module.TZ))
        self.assertEqual(result['markets']['985']['history'],prior['markets']['985']['history'])
        self.assertEqual(result['updatedAt'],prior['updatedAt'])
        self.assertEqual(result['markets']['985']['status'],'error')
        self.assertEqual(len(failed),4)
        self.assertNotIn('status',prior['markets']['985'])

    def test_embedded_json_is_parsed_without_executing_scripts(self):
        self.assertEqual(module.embedded_json('priceSection: {"currentValue": 42}, malicious()', 'priceSection')['currentValue'],42)
        with self.assertRaises(ValueError): module.embedded_json('changed markup', 'priceSection')

    def test_switch_to_985_fetches_its_own_prices_and_discards_sjc(self):
        current = [
            {'code': 'SJC', 'dateTime': '05/10/2026 18:15', 'buyingPrice': 14000000, 'sellingPrice': 14200000},
            {'code': '985', 'dateTime': '05/10/2026 18:15', 'buyingPrice': 13000000, 'sellingPrice': 13200000},
            {'code': '999', 'dateTime': '05/10/2026 18:15', 'buyingPrice': 13900000, 'sellingPrice': 14100000},
        ]
        requested_codes = set()
        def source(url, headers=None):
            code = parse_qs(urlparse(url).query).get('goldCode', [None])[0]
            if code is None:
                return json.dumps(current)
            requested_codes.add(code)
            return json.dumps([dict(next(row for row in current if row['code'] == code), dateTime='04/10/2026 18:15')])
        old = {'markets': {'SJC': {'history': [{'date': '2026-10-01', 'value': 99999999}]}}}
        with patch.object(module, 'fetch', side_effect=source), patch.object(module, 'international', return_value={'history': [], 'status': 'ok'}):
            result, failed = module.update(old, datetime(2026, 10, 5, 19, tzinfo=module.TZ))
        self.assertEqual(requested_codes, {'985', '999'})
        self.assertEqual(failed, [])
        self.assertNotIn('SJC', result['markets'])
        gold = result['markets']['985']
        self.assertEqual(gold['latest']['value'], 13200000)
        self.assertEqual(gold['latest']['buy'], 13000000)
        self.assertTrue(all(point['value'] == 13200000 for point in gold['history']))
        self.assertIn('SJC', old['markets'])

if __name__ == '__main__': unittest.main()
