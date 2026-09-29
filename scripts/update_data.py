#!/usr/bin/env python3
"""Fetch the same public data used by the requested source pages; no API keys."""
import copy
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / 'data' / 'market.json'
TZ = ZoneInfo('Asia/Ho_Chi_Minh')
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; DailyMarketDashboard/1.0)', 'Accept': 'application/json,text/html'}
MIHONG = 'https://api.mihong.com/v1/gold-prices'
BI = 'https://markets.businessinsider.com'
GOLD_CODES = ['SJC', '999']

def fetch(url, headers=None):
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={**HEADERS, **(headers or {})})
            with urllib.request.urlopen(request, timeout=40) as response:
                return response.read().decode('utf-8')
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)

def positive(value):
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError('Invalid/non-positive price')
    return result

def embedded_json(html, key):
    match = re.search(r'\b' + re.escape(key) + r'\s*:\s*(\{)', html)
    if not match:
        raise ValueError('Source page format changed: ' + key)
    # Parse JSON only. Never execute JavaScript supplied by a source website.
    return json.JSONDecoder().raw_decode(html[match.start(1):])[0]

def mh_point(row, kind):
    date = datetime.strptime(row['dateTime'], '%d/%m/%Y %H:%M').replace(tzinfo=TZ)
    return {'date': date.date().isoformat(), 'time': date.isoformat(),
            'value': positive(row['sellingPrice']), 'buy': positive(row['buyingPrice']), 'kind': kind}

def bi_point(row):
    date = datetime.strptime(row['Date'], '%m/%d/%y').date().isoformat()
    point = {'date': date, 'value': positive(row['Close']), 'kind': 'close'}
    for src, dest in [('Open', 'open'), ('High', 'high'), ('Low', 'low')]:
        if row.get(src) and float(row[src]) > 0:
            point[dest] = positive(row[src])
    return point

def merge_history(old, fresh, now):
    # Official history supersedes earlier collected quotes for the same date.
    points = {p['date']: p for p in old}
    points.update({p['date']: p for p in fresh})
    cutoff = (now.date() - timedelta(days=400)).isoformat()
    return [points[d] for d in sorted(points) if cutoff <= d <= now.date().isoformat()]

def domestic(code, previous, now, current):
    def api(period):
        query = urllib.parse.urlencode({'market': 'domestic', 'goldCode': code, 'last': period})
        result = json.loads(fetch(MIHONG + '?' + query, {'x-market': 'mihong'}))
        if not isinstance(result, list) or not result:
            raise ValueError('Empty Mi Hong history: ' + code + '/' + period)
        return result
    daily = [mh_point(r, 'source_day') for r in api('1M')]
    monthly = [mh_point(r, 'source_month') for r in api('1y')]
    latest = mh_point(next(r for r in current if r['code'] == code), 'snapshot')
    latest['collectedAt'] = now.isoformat()
    intraday = [mh_point(r, 'intraday') for r in api('24h')]
    return {'name': 'Mi Hồng ' + code, 'source': 'https://mihong.com/gia-vang-trong-nuoc',
            'unit': 'VND/chỉ', 'latest': latest,
            'history': merge_history(previous.get('history', []), daily + [latest], now),
            'monthly': merge_history(previous.get('monthly', []), monthly, now),
            'intraday': sorted(intraday, key=lambda p: p['time']),
            'status': 'ok', 'lastSuccessAt': now.isoformat()}

def international(key, previous, now):
    path = '/commodities/gold-price' if key == 'gold' else '/currencies/usd-vnd'
    html = fetch(BI + path)
    quote = embedded_json(html, 'priceSection')
    config = embedded_json(html, 'historicalPrices')
    start = now.date() - timedelta(days=370)
    # English month names are stable regardless of machine locale.
    months = ['Jan.', 'Feb.', 'Mar.', 'Apr.', 'May.', 'Jun.', 'Jul.', 'Aug.', 'Sep.', 'Oct.', 'Nov.', 'Dec.']
    def bi_date(d): return f'{months[d.month-1]} {d.day:02d} {d.year}'
    url = BI + '/ajax/' + config['instrumentTypeName'] + '_HistoricPriceList/' + config['instrumentIdentifier'] + '/' + urllib.parse.quote(bi_date(start) + '_' + bi_date(now.date()), safe='') + '/' + config['currentStockMarket']
    warning = None
    try:
        rows = json.loads(fetch(url))
        if not isinstance(rows, list) or not rows: raise ValueError('Empty history')
    except Exception as exc:
        rows = config['model']
        warning = 'Không tải được lịch sử dài hạn; đã giữ lịch sử cũ và bổ sung dữ liệu trong trang nguồn.'
        print(f'Warning {key}: long history fetch failed ({type(exc).__name__})', file=sys.stderr)
    history = [bi_point(row) for row in rows]
    latest = {'date': now.date().isoformat(), 'time': now.isoformat(),
              'collectedAt': now.isoformat(), 'sourceClock': quote.get('time'),
              'value': positive(quote['currentValue']), 'kind': 'snapshot',
              'previousClose': positive(quote['previousClose'])}
    result = {'name': 'Vàng quốc tế' if key == 'gold' else 'USD/VND',
              'source': BI + path, 'unit': 'USD/ounce troy' if key == 'gold' else 'VND/USD',
              'latest': latest, 'history': merge_history(previous.get('history', []), history + [latest], now),
              'intraday': [], 'monthly': [], 'status': 'partial' if warning else 'ok',
              'lastSuccessAt': now.isoformat()}
    if warning: result['warning'] = warning
    return result

def update(previous, now):
    result = copy.deepcopy(previous)
    result.update({'schemaVersion': 1, 'attemptedAt': now.isoformat(), 'timezone': 'Asia/Ho_Chi_Minh',
                   'scheduledTime': '18:37', 'scheduleUtc': '37 11 * * *'})
    markets = result.setdefault('markets', {})
    failures = []
    current = None
    try:
        current = json.loads(fetch(MIHONG + '?market=domestic', {'x-market': 'mihong'}))
    except Exception as exc:
        print('Mi Hong current: ' + type(exc).__name__, file=sys.stderr)
    for key in ['SJC', '999', 'gold', 'fx']:
        old = markets.get(key, {})
        try:
            if key in GOLD_CODES:
                if not current: raise ValueError('Missing Mi Hong current data')
                fresh = domestic(key, old, now, current)
            else:
                fresh = international(key, old, now)
            markets[key] = fresh
            print(f'{key}: {len(fresh["history"])} daily / {len(fresh.get("monthly", []))} monthly points')
            if fresh['status'] != 'ok': failures.append(key)
        except Exception as exc:
            failures.append(key)
            markets[key] = {**old, 'status': 'error', 'warning': 'Chưa lấy được dữ liệu mới từ nguồn. Đang hiển thị bản ghi thành công gần nhất.'}
            print(f'ERROR {key}: {type(exc).__name__}: {exc}', file=sys.stderr)
    successes = [m.get('lastSuccessAt') for m in markets.values() if m.get('lastSuccessAt')]
    result['updatedAt'] = max(successes) if successes else None
    return result, failures

def main():
    previous = json.loads(FILE.read_text()) if FILE.exists() else {}
    result, failures = update(previous, datetime.now(TZ))
    FILE.parent.mkdir(exist_ok=True)
    temp = FILE.with_suffix('.tmp')
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    temp.replace(FILE)
    if failures:
        print('Incomplete sources: ' + ', '.join(failures), file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
