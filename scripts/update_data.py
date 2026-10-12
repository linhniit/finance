#!/usr/bin/env python3
"""Fetch the same public data used by the requested source pages; no API keys."""
import copy
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
FED_POLICY = 'https://www.federalreserve.gov/monetarypolicy/openmarket.htm'

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

def fed_policy_points(html, now):
    if "FOMC's target federal funds rate or range" not in html:
        raise ValueError('Federal Reserve policy page format changed')
    tables = re.findall(r'<h4[^>]*>\s*(20\d{2})\s*</h4>\s*(?:<div[^>]*>\s*)?<table\b[^>]*>(.*?)</table>', html, re.S)
    months = {name: i + 1 for i, name in enumerate('January February March April May June July August September October November December'.split())}
    changes = {}
    for year, table in tables:
        if 'Level (%)' not in table:
            raise ValueError('Missing Fed target range column')
        body = re.search(r'<tbody[^>]*>(.*?)</tbody>', table, re.S)
        if not body:
            raise ValueError('Missing Fed target changes')
        for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>', body[1], re.S):
            cells = [unescape(re.sub(r'<[^>]+>', '', cell)).strip()
                     for cell in re.findall(r'<td\b[^>]*>(.*?)</td>', row, re.S)]
            if len(cells) != 4:
                raise ValueError('Invalid Fed policy row')
            day = re.fullmatch(r'([A-Za-z]+)\s+(\d{1,2})\s*\*?', cells[0])
            bounds = re.fullmatch(r'(\d+(?:\.\d+)?)(?:\s*[-–]\s*(\d+(?:\.\d+)?))?', cells[3])
            if not day or not bounds:
                raise ValueError('Invalid Fed date or target range')
            date = datetime(int(year), months[day[1]], int(day[2])).date()
            lower, upper = float(bounds[1]), float(bounds[2] or bounds[1])
            if not all(math.isfinite(v) for v in (lower, upper)) or not 0 <= lower <= upper:
                raise ValueError('Invalid Fed target bounds')
            if date in changes:
                raise ValueError('Duplicate Fed effective date')
            changes[date] = {'lower': lower, 'value': upper, 'effectiveFrom': date.isoformat(), 'kind': 'fed_policy'}
    # Policy levels remain in force until the next effective decision. Expand the
    # published intervals by calendar day, stopping at today's date in New York.
    end = now.astimezone(ZoneInfo('America/New_York')).date()
    start = end - timedelta(days=400)
    dates = sorted(date for date in changes if date <= end)
    if not dates or dates[0] > start:
        raise ValueError('Fed policy history does not cover the requested year')
    points, index = [], 0
    for offset in range((end - start).days + 1):
        date = start + timedelta(days=offset)
        while index + 1 < len(dates) and dates[index + 1] <= date:
            index += 1
        points.append({'date': date.isoformat(), **changes[dates[index]]})
    return points

def fed(previous, now):
    html = fetch(FED_POLICY, {'User-Agent': 'Mozilla/5.0', 'Accept': None})
    points = fed_policy_points(html, now)
    return {'name': 'Lãi suất mục tiêu Fed', 'source': FED_POLICY, 'unit': '%/năm',
            'latest': {**points[-1], 'collectedAt': now.isoformat()},
            'history': merge_history(previous.get('history', []), points, now),
            'intraday': [], 'monthly': [], 'status': 'ok',
            'collectionMethod': 'official_policy_intervals', 'lastSuccessAt': now.isoformat()}

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
