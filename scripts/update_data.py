#!/usr/bin/env python3
"""Fetch the same public data used by the requested source pages; no API keys."""
import copy
import csv
import io
from html import unescape
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
GOLD_CODES = ['985', '999']
INTERNATIONAL = {
    'gold': ('/commodities/gold-price', 'Vàng quốc tế', 'USD/ounce troy'),
    'fx': ('/currencies/usd-vnd', 'USD/VND', 'VND/USD'),
    'oil': ('/commodities/oil-price?type=wti', 'Dầu WTI · NYMEX', 'USD/thùng'),
}
FRED = 'https://fred.stlouisfed.org'

def fetch(url, headers=None, *, attempts=3, timeout=40):
    for attempt in range(attempts):
        try:
            request_headers = {k: v for k, v in {**HEADERS, **(headers or {})}.items() if v is not None}
            request = urllib.request.Request(url, headers=request_headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read().decode('utf-8')
        except Exception:
            if attempt == attempts - 1:
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
    return {'name': 'Mi Hồng ' + code, 'source': 'https://www.mihong.vn/gia-vang-trong-nuoc',
            'unit': 'VND/chỉ', 'latest': latest,
            'history': merge_history(previous.get('history', []), daily + [latest], now),
            'monthly': merge_history(previous.get('monthly', []), monthly, now),
            'intraday': sorted(intraday, key=lambda p: p['time']),
            'status': 'ok', 'lastSuccessAt': now.isoformat()}

def international(key, previous, now):
    path, name, unit = INTERNATIONAL[key]
    html = fetch(BI + path)
    quote = embedded_json(html, 'priceSection')
    config = embedded_json(html, 'historicalPrices')
    if key == 'oil' and ('WTI' not in quote.get('label', '') or quote.get('postTimePushText') != 'NYMEX'):
        raise ValueError('Expected WTI quote on NYMEX')
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
    result = {'name': name, 'source': BI + path, 'unit': unit,
              'latest': latest, 'history': merge_history(previous.get('history', []), history + [latest], now),
              'intraday': [], 'monthly': [], 'status': 'partial' if warning else 'ok',
              'lastSuccessAt': now.isoformat()}
    if warning: result['warning'] = warning
    return result

def fed_points(raw, now):
    rows = csv.DictReader(io.StringIO(raw.lstrip('\ufeff')))
    if not {'observation_date', 'DFEDTARL', 'DFEDTARU'}.issubset(rows.fieldnames or []):
        raise ValueError('FRED CSV columns changed')
    points = []
    for row in rows:
        date = datetime.strptime(row['observation_date'], '%Y-%m-%d').date()
        if not now.date() - timedelta(days=400) <= date <= now.date():
            continue
        if any(row[key] in ('', '.') for key in ('DFEDTARL', 'DFEDTARU')):
            continue
        lower, upper = float(row['DFEDTARL']), float(row['DFEDTARU'])
        # Zero is a valid target rate; missing observations are not zero.
        if not all(math.isfinite(v) for v in (lower, upper)) or not 0 <= lower <= upper:
            raise ValueError('Invalid FRED target range')
        points.append({'date': date.isoformat(), 'lower': lower, 'value': upper, 'kind': 'fed_target'})
    if not points:
        raise ValueError('Empty FRED target rate history')
    return sorted(points, key=lambda p: p['date'])

def fred_recent(html, code):
    title = re.search(r'<title>(.*?)</title>', html, re.S)
    table = re.search(r'<table\b[^>]*\bid=["\']recent-obs["\'][^>]*>(.*?)</table>', html, re.S)
    if not title or code not in title[1] or not table:
        raise ValueError('FRED observation page format changed: ' + code)
    observations = {}
    for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>', table[1], re.S):
        cells = [unescape(re.sub(r'<[^>]+>', '', cell)).strip()
                 for cell in re.findall(r'<td\b[^>]*>(.*?)</td>', row, re.S)]
        if len(cells) >= 2 and re.fullmatch(r'\d{4}-\d{2}-\d{2}:', cells[0]):
            if cells[1] not in ('', '.'):
                observations[cells[0][:-1]] = cells[1]
    if not observations:
        raise ValueError('No recent FRED observations: ' + code)
    return observations

def fed(previous, now):
    headers = {'User-Agent': 'Mozilla/5.0', 'Accept': None}
    recent_only = False
    mismatched_dates = False
    try:
        # Open-ended export covering the initial year; trim the rolling window locally.
        raw = fetch(FRED + '/graph/fredgraph.csv?id=DFEDTARL,DFEDTARU&cosd=2025-10-01',
                    headers, attempts=1, timeout=15)
        points = fed_points(raw, now)
    except Exception as exc:
        # The CSV service can time out on cloud runners while series pages still work.
        # Only use dated observations published by FRED; never carry a rate forward.
        print('FRED CSV unavailable; using official recent observations: ' + type(exc).__name__, file=sys.stderr)
        lower = fred_recent(fetch(FRED + '/series/DFEDTARL', headers), 'DFEDTARL')
        upper = fred_recent(fetch(FRED + '/series/DFEDTARU', headers), 'DFEDTARU')
        dates = sorted(lower.keys() & upper.keys())
        raw = 'observation_date,DFEDTARL,DFEDTARU\n' + '\n'.join(f'{date},{lower[date]},{upper[date]}' for date in dates)
        points = fed_points(raw, now)
        recent_only = True
        mismatched_dates = max(lower) != max(upper)
    history = merge_history(previous.get('history', []), points, now)
    latest = {**points[-1], 'collectedAt': now.isoformat()}
    stale = (now.date() - datetime.strptime(latest['date'], '%Y-%m-%d').date()).days > 3
    try:
        year_start = now.date().replace(year=now.year - 1)
    except ValueError:  # Leap day.
        year_start = now.date().replace(year=now.year - 1, day=28)
    observed = {p['date'] for p in history}
    last_date = datetime.strptime(latest['date'], '%Y-%m-%d').date()
    complete_history = all((year_start + timedelta(days=i)).isoformat() in observed
                           for i in range((last_date - year_start).days + 1))
    partial = stale or mismatched_dates or (recent_only and not complete_history)
    result = {'name': 'Lãi suất mục tiêu Fed', 'source': FRED + '/series/DFEDTARU',
              'lowerSource': FRED + '/series/DFEDTARL', 'unit': '%/năm', 'latest': latest,
              'history': history, 'collectionMethod': 'recent_observations' if recent_only else 'csv',
              'intraday': [], 'monthly': [], 'status': 'partial' if partial else 'ok',
              'lastSuccessAt': now.isoformat()}
    if stale:
        result['warning'] = 'Nguồn FRED chưa có quan sát mới trong hơn 3 ngày.'
    elif partial:
        result['warning'] = 'Đã lấy các quan sát FRED gần nhất; lịch sử hoặc ngày công bố của hai biên chưa đầy đủ.'
    return result

def update(previous, now):
    result = copy.deepcopy(previous)
    result.update({'schemaVersion': 1, 'attemptedAt': now.isoformat(), 'timezone': 'Asia/Ho_Chi_Minh',
                   'scheduledTime': '18:37', 'scheduleUtc': '37 11 * * *'})
    active_keys = [*GOLD_CODES, *INTERNATIONAL, 'fed']
    # Keep history only for the configured instruments; never relabel another gold code.
    markets = {key: result.get('markets', {}).get(key, {}) for key in active_keys}
    result['markets'] = markets
    failures = []
    current = None
    try:
        current = json.loads(fetch(MIHONG + '?market=domestic', {'x-market': 'mihong'}))
    except Exception as exc:
        print('Mi Hong current: ' + type(exc).__name__, file=sys.stderr)
    for key in active_keys:
        old = markets.get(key, {})
        try:
            if key in GOLD_CODES:
                if not current: raise ValueError('Missing Mi Hong current data')
                fresh = domestic(key, old, now, current)
            elif key == 'fed':
                fresh = fed(old, now)
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
