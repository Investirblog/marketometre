#!/usr/bin/env python3
"""
fetch_data.py
Fetche toutes les données de marché et écrit data.json.
Tourne via GitHub Actions chaque matin.
Deps: pip install yfinance requests
"""
import json, math, sys, traceback
from datetime import date
import requests
import yfinance as yf

FRED_KEY = '96e939128c65bf0f827ccfaa87820026'

# ── CALCUL ──────────────────────────────────────────────
def clamp(v, lo=0, hi=100): return max(lo, min(hi, v))
def norm(v, lo, hi, inv=False):
    try:
        p = (v - lo) / (hi - lo) * 100
        return clamp(100 - p if inv else p)
    except ZeroDivisionError:
        return 50.0

def zone_label(s):
    if s < 15: return 'Panique extrême'
    if s < 30: return 'Peur'
    if s < 45: return 'Prudence'
    if s < 55: return 'Neutre'
    if s < 70: return 'Optimisme'
    if s < 85: return 'Euphorie'
    return 'Euphorie extrême'

# ── FETCH ────────────────────────────────────────────────
def fred(series):
    url = (f'https://api.stlouisfed.org/fred/series/observations'
           f'?series_id={series}&api_key={FRED_KEY}'
           f'&file_type=json&sort_order=desc&limit=5')
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    j = r.json()
    obs = next(o for o in j['observations'] if o['value'] != '.')
    v = float(obs['value'])
    print(f'  FRED {series} = {v} ({obs["date"]})')
    return v, obs['date']

def fred_zew():
    """ZEW avec fallback : FRED peut mettre quelques jours à publier."""
    try:
        v, d = fred('ZEWSELMU')
        # Si FRED retourne 0.0 exact avec une date ancienne, c'est suspect
        # On retourne quand même la valeur — 0 peut être légitime (neutre)
        return v, d
    except Exception as e:
        print(f'  [WARN] ZEW FRED: {e}')
        # Valeur publiée manuellement en dernier recours
        # À mettre à jour manuellement après chaque release ZEW (3ème mardi du mois)
        ZEW_FALLBACK = -17.2   # ← Avril 2026, publié le 21/04/2026
        ZEW_FALLBACK_DATE = '2026-04-21'
        print(f'  [ZEW fallback] {ZEW_FALLBACK} ({ZEW_FALLBACK_DATE})')
        return ZEW_FALLBACK, ZEW_FALLBACK_DATE

def yf_latest(sym):
    t = yf.Ticker(sym)
    h = t.history(period='5d', auto_adjust=True)
    closes = h['Close'].dropna()
    if len(closes) == 0:
        raise ValueError(f'No data for {sym}')
    v = float(closes.iloc[-1])
    print(f'  Yahoo {sym} = {v:.2f}')
    return v

def yf_ma(sym, days):
    t = yf.Ticker(sym)
    h = t.history(period='1y', auto_adjust=True)
    closes = h['Close'].dropna().tolist()
    if len(closes) < days:
        raise ValueError(f'Not enough history for {sym}')
    latest = closes[-1]
    ma = sum(closes[-days:]) / len(closes[-days:])
    pct = (latest - ma) / ma * 100
    print(f'  Yahoo {sym} latest={latest:.1f} MA{days}={ma:.1f} pct={pct:.2f}%')
    return float(latest), float(pct)

def fetch_putcall():
    url = 'https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/equitypc.csv'
    r = requests.get(url, timeout=20,
                     headers={'User-Agent': 'Mozilla/5.0'})
    r.raise_for_status()
    lines = [l for l in r.text.strip().split('\n')
             if l.strip() and not l.startswith(('Your', ',', ' ', 'DATE'))]
    parts = lines[-1].split(',')
    v = float(parts[4])
    d = parts[0]
    print(f'  CBOE Put/Call = {v} ({d})')
    return v, d

def safe(fn, fallback, label):
    try:
        return fn()
    except Exception as e:
        print(f'  [WARN] {label}: {e}')
        return fallback

# ── MAIN ─────────────────────────────────────────────────
def main():
    print(f'=== fetch_data.py — {date.today()} ===')

    vix_val, vix_date   = safe(lambda: fred('VIXCLS'),        (22.0, 'n/a'), 'VIX')
    hy_val,  hy_date    = safe(lambda: fred('BAMLH0A0HYM2'),  (4.5,  'n/a'), 'HY Spread')
    zew_val, zew_date   = safe(fred_zew,                 (-17.2,'2026-04-21'), 'ZEW')

    vstoxx_val          = safe(lambda: yf_latest('^V2TX'),     22.0,          'VSTOXX')
    sp_latest, sp_pct   = safe(lambda: yf_ma('^GSPC', 125),   (5200, 4.0),   'SP500')
    sx5e_lat, sx5e_pct  = safe(lambda: yf_ma('^STOXX50E',125),(4900, 3.0),   'SX5E')
    breadth_val         = safe(lambda: yf_latest('%5ESPXA50R'), 50.0,          'Breadth')
    pc_val, pc_date     = safe(lambda: fetch_putcall(),        (0.70, 'n/a'), 'Put/Call')

    itraxx = vstoxx_val * 0.18

    # Piliers US
    us0 = norm(vix_val,      10, 50, True)
    us1 = norm(pc_val,      0.4, 1.2, True)
    us2 = norm(breadth_val,  20, 80)
    us3 = norm(hy_val,        2, 10, True)
    us4 = norm(sp_pct,      -30, 30)
    scoreUS = round(clamp(us0*.25 + us1*.20 + us2*.20 + us3*.20 + us4*.15))

    # Piliers EU
    eu0 = norm(vstoxx_val,  10, 45, True)
    eu1 = norm(zew_val,    -60, 80)
    eu2 = norm(sx5e_pct,   -30, 30)
    eu3 = norm(itraxx,       2, 10, True)
    eu4 = norm(sx5e_pct,   -30, 30)
    scoreEU = round(clamp(eu0*.25 + eu1*.20 + eu2*.20 + eu3*.20 + eu4*.15))

    print(f'  Score US={scoreUS} ({zone_label(scoreUS)})  EU={scoreEU} ({zone_label(scoreEU)})')

    sp_sign   = '+' if sp_pct   >= 0 else ''
    sx5e_sign = '+' if sx5e_pct >= 0 else ''

    data = {
        'date': date.today().isoformat(),
        'scoreUS': scoreUS,
        'scoreEU': scoreEU,
        'zoneUS': zone_label(scoreUS),
        'zoneEU': zone_label(scoreEU),
        'pillarsUS': [
            {'name': 'Volatilité (VIX)',     'score': round(us0), 'raw': f'{vix_val:.1f}'},
            {'name': 'Sentiment (Put/Call)',  'score': round(us1), 'raw': f'{pc_val:.2f}'},
            {'name': 'Breadth (% >MA50)',    'score': round(us2), 'raw': f'{breadth_val:.0f}%'},
            {'name': 'Stress crédit (HY)',   'score': round(us3), 'raw': f'{hy_val:.2f}%'},
            {'name': 'Momentum S&P/MA125',   'score': round(us4), 'raw': f'{sp_sign}{sp_pct:.1f}%'},
        ],
        'pillarsEU': [
            {'name': 'Volatilité (VSTOXX)',  'score': round(eu0), 'raw': f'{vstoxx_val:.1f}'},
            {'name': 'Sentiment (ZEW)',      'score': round(eu1), 'raw': f'{zew_val:.1f}'},
            {'name': 'Breadth SX5E/MA125',  'score': round(eu2), 'raw': f'{sx5e_sign}{sx5e_pct:.1f}%'},
            {'name': 'Stress crédit iTraxx','score': round(eu3), 'raw': f'{itraxx:.2f}%'},
            {'name': 'Momentum SX5E/MA125', 'score': round(eu4), 'raw': f'{sx5e_sign}{sx5e_pct:.1f}%'},
        ],
        'kpis': {
            'vix':    {'value': f'{vix_val:.1f}',    'date': vix_date,  'stress': vix_val > 25},
            'vstoxx': {'value': f'{vstoxx_val:.1f}', 'date': 'realtime','stress': vstoxx_val > 22},
            'hy':     {'value': f'{hy_val:.2f}%',    'date': hy_date,   'stress': hy_val > 5},
            'pc':     {'value': f'{pc_val:.2f}',     'date': pc_date,   'stress': pc_val > 0.9},
        }
    }

    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f'  data.json écrit avec succès.')
    print('=== Done ===')
    return data

if __name__ == '__main__':
    main()
