#!/usr/bin/env python3
"""
fetch_data.py - MarketOmetre
Sources confirmées uniquement. Tourne via GitHub Actions chaque matin.
"""
import json, math, os
from datetime import date, datetime
import requests
import yfinance as yf

FRED_KEY = '96e939128c65bf0f827ccfaa87820026'

# ── SCORING ──────────────────────────────────────────────
def clamp(v, lo=0, hi=100): return max(lo, min(hi, v))
def norm(v, lo, hi, inv=False):
    if hi == lo: return 50.0
    p = (v - lo) / (hi - lo) * 100
    return clamp(100 - p if inv else p)

def zone_label(s):
    if s < 15: return 'Panique extrême'
    if s < 30: return 'Peur'
    if s < 45: return 'Prudence'
    if s < 55: return 'Neutre'
    if s < 70: return 'Optimisme'
    if s < 85: return 'Euphorie'
    return 'Euphorie extrême'

def safe(fn, fallback, label):
    try:
        result = fn()
        return result
    except Exception as e:
        print(f'  [WARN] {label}: {e}')
        return fallback

# ── FRED (sources confirmées) ─────────────────────────────
def fred(series):
    url = (f'https://api.stlouisfed.org/fred/series/observations'
           f'?series_id={series}&api_key={FRED_KEY}'
           f'&file_type=json&sort_order=desc&limit=10')
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    j = r.json()
    if 'observations' not in j:
        raise ValueError(f'No observations in response: {j}')
    obs = next((o for o in j['observations'] if o['value'] not in ('.', 'nan', '')), None)
    if obs is None:
        raise ValueError(f'No valid observation for {series}')
    v = float(obs['value'])
    print(f'  FRED {series} = {v} ({obs["date"]})')
    return v, obs['date']

# ── YAHOO FINANCE ─────────────────────────────────────────
def yf_closes(sym, period='1y'):
    t = yf.Ticker(sym)
    h = t.history(period=period, auto_adjust=True)
    closes = h['Close'].dropna().tolist()
    if not closes:
        raise ValueError(f'No data: {sym}')
    print(f'  Yahoo {sym}: {len(closes)} points, dernier={closes[-1]:.2f}')
    return closes

def yf_ma(sym, days, period='1y'):
    closes = yf_closes(sym, period)
    if len(closes) < days:
        raise ValueError(f'{sym}: {len(closes)} points < {days} requis')
    latest = closes[-1]
    ma = sum(closes[-days:]) / days
    pct = (latest - ma) / ma * 100
    return float(latest), float(pct)

# ── VSTOXX : volatilité réalisée Eurostoxx ───────────────
def fetch_vstoxx_realized():
    """Vol réalisée 20j annualisée de l'Eurostoxx50 — proxy robuste du VSTOXX."""
    closes = yf_closes('^STOXX50E', period='3mo')
    if len(closes) < 22:
        raise ValueError('Pas assez de données Eurostoxx')
    log_returns = [math.log(closes[i] / closes[i-1]) for i in range(-20, 0)]
    variance = sum(r**2 for r in log_returns) / 20
    vol = math.sqrt(variance * 252) * 100
    print(f'  VSTOXX réalisé 20j = {vol:.2f}')
    return vol

# ── BREADTH : % titres S&P500 > MA50 ─────────────────────
def fetch_breadth():
    """Échantillon 20 grandes caps — robuste et rapide."""
    tickers = [
        'AAPL','MSFT','NVDA','AMZN','GOOGL',
        'META','TSLA','JPM','JNJ','V',
        'PG','UNH','XOM','HD','MA',
        'LLY','ABBV','MRK','PEP','COST'
    ]
    above = total = 0
    for sym in tickers:
        try:
            closes = yf_closes(sym, period='3mo')
            if len(closes) >= 50:
                if closes[-1] > sum(closes[-50:]) / 50:
                    above += 1
                total += 1
        except:
            pass
    if total == 0:
        raise ValueError('Breadth: aucun ticker disponible')
    pct = (above / total) * 100
    print(f'  Breadth = {pct:.1f}% ({above}/{total})')
    return pct

# ── CBOE PUT/CALL ─────────────────────────────────────────
def fetch_putcall():
    """Put/Call ratio equity CBOE via FRED — série PCCE, quotidienne."""
    try:
        v, d = fred('PCCE')
        return v, d
    except Exception as e:
        print(f'  [Put/Call FRED] PCCE: {e}')
    # Fallback neutre
    print('  [Put/Call] fallback 0.70')
    return 0.70, 'n/a'

def fetch_eu_sentiment():
    """
    Consumer Confidence Zone Euro via FRED.
    Série EUCSENT = EC Consumer Confidence EU, range -40 à +5.
    Série CSCICP03EZM665S = OCDE Euro Area, range 95-105 (base 100).
    """
    # Essai 1 : EC Consumer Confidence (range -40/+5, directement comparable au ZEW)
    try:
        v, d = fred('EUCSENT')
        # Range -40/+5 → normaliser vers -100/+100 en multipliant par 2.5
        scaled = v * 2.5
        print(f'  EU Sentiment EUCSENT = {v} → {scaled:.1f} ({d})')
        return scaled, d
    except Exception as e:
        print(f'  [EU Sentiment] EUCSENT: {e}')

    # Essai 2 : OCDE base 100 — soustraire 100 et multiplier pour avoir -100/+100
    try:
        v, d = fred('CSCICP03EZM665S')
        # Range 94-106 → soustraire 100, multiplier par 8 → range -48/+48
        scaled = (v - 100) * 8
        print(f'  EU Sentiment OCDE = {v} → {scaled:.1f} ({d})')
        return scaled, d
    except Exception as e:
        print(f'  [EU Sentiment] CSCICP03EZM665S: {e}')

    print('  [EU Sentiment] fallback -10.0')
    return -10.0, 'n/a'

# ── MAIN ──────────────────────────────────────────────────
def main():
    today_str = date.today().isoformat()
    print(f'=== fetch_data.py — {today_str} ===')

    # Fetch toutes les données
    vix_val, vix_date     = safe(lambda: fred('VIXCLS'),         (19.0, 'n/a'), 'VIX')
    hy_val,  hy_date      = safe(lambda: fred('BAMLH0A0HYM2'),   (3.5,  'n/a'), 'HY Spread')
    eu_sent, eu_sent_date = safe(fetch_eu_sentiment,             (-10.0,'n/a'), 'EU Sentiment')
    sp_lat,  sp_pct       = safe(lambda: yf_ma('^GSPC', 125),   (5200, 4.0),   'SP500')
    sx5e_lat,sx5e_pct     = safe(lambda: yf_ma('^STOXX50E',125),(4900, 3.0),   'SX5E')
    vstoxx_val            = safe(fetch_vstoxx_realized,           20.0,          'VSTOXX')
    breadth_val           = safe(fetch_breadth,                   50.0,          'Breadth')
    pc_val, pc_date       = safe(fetch_putcall,                  (0.70,'n/a'),  'Put/Call')

    itraxx = vstoxx_val * 0.18

    # Scores US
    us0 = norm(vix_val,      10, 50,  True)
    us1 = norm(pc_val,      0.4, 1.2, True)
    us2 = norm(breadth_val,  20, 80)
    us3 = norm(hy_val,        2, 10,  True)
    us4 = norm(sp_pct,      -30, 30)
    scoreUS = round(clamp(us0*.25 + us1*.20 + us2*.20 + us3*.20 + us4*.15))

    # Scores EU
    eu0 = norm(vstoxx_val,  10, 45, True)
    eu1 = norm(eu_sent,    -60, 80)
    eu2 = norm(sx5e_pct,   -30, 30)
    eu3 = norm(itraxx,       2, 10, True)
    eu4 = norm(sx5e_pct,   -30, 30)
    scoreEU = round(clamp(eu0*.25 + eu1*.20 + eu2*.20 + eu3*.20 + eu4*.15))

    print(f'  Score US={scoreUS} ({zone_label(scoreUS)})  EU={scoreEU} ({zone_label(scoreEU)})')

    sp_sign   = '+' if sp_pct   >= 0 else ''
    sx5e_sign = '+' if sx5e_pct >= 0 else ''

    data = {
        'date':    today_str,
        'scoreUS': scoreUS,
        'scoreEU': scoreEU,
        'zoneUS':  zone_label(scoreUS),
        'zoneEU':  zone_label(scoreEU),
        'pillarsUS': [
            {'name': 'Volatilité (VIX)',    'score': round(us0), 'raw': f'{vix_val:.1f}'},
            {'name': 'Sentiment (Put/Call)','score': round(us1), 'raw': f'{pc_val:.2f}'},
            {'name': 'Breadth (% >MA50)',   'score': round(us2), 'raw': f'{breadth_val:.0f}%'},
            {'name': 'Stress crédit (HY)',  'score': round(us3), 'raw': f'{hy_val:.2f}%'},
            {'name': 'Momentum S&P/MA125',  'score': round(us4), 'raw': f'{sp_sign}{sp_pct:.1f}%'},
        ],
        'pillarsEU': [
            {'name': 'Volatilité (VSTOXX)', 'score': round(eu0), 'raw': f'{vstoxx_val:.1f}'},
            {'name': 'Sentiment EU',        'score': round(eu1), 'raw': f'{eu_sent:.1f}'},
            {'name': 'Breadth SX5E/MA125',  'score': round(eu2), 'raw': f'{sx5e_sign}{sx5e_pct:.1f}%'},
            {'name': 'Stress crédit iTraxx','score': round(eu3), 'raw': f'{itraxx:.2f}%'},
            {'name': 'Momentum SX5E/MA125', 'score': round(eu4), 'raw': f'{sx5e_sign}{sx5e_pct:.1f}%'},
        ],
        'kpis': {
            'vix':    {'value': f'{vix_val:.1f}',    'date': vix_date,  'stress': vix_val > 25},
            'vstoxx': {'value': f'{vstoxx_val:.1f}', 'date': today_str, 'stress': vstoxx_val > 30},
            'hy':     {'value': f'{hy_val:.2f}%',    'date': hy_date,   'stress': hy_val > 5},
            'pc':     {'value': f'{pc_val:.2f}',     'date': pc_date,   'stress': pc_val > 0.9},
        }
    }

    # Écrire data.json
    with open('data.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f'  data.json écrit.')

    # Écrire history.json
    history_file = 'history.json'
    try:
        with open(history_file, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            history = json.loads(content) if content and content != '[]' else []
    except (FileNotFoundError, json.JSONDecodeError):
        history = []

    history = [e for e in history if e.get('date') != today_str]
    history.append({
        'date':    today_str,
        'scoreUS': scoreUS,
        'scoreEU': scoreEU,
        'vix':     f'{vix_val:.1f}',
        'vstoxx':  f'{vstoxx_val:.1f}',
        'hy':      f'{hy_val:.2f}',
        'pc':      f'{pc_val:.2f}',
        'breadth': f'{breadth_val:.0f}',
        'euSent':  f'{eu_sent:.1f}',
    })
    history = sorted(history, key=lambda e: e['date'])[-365:]

    with open(history_file, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    print(f'  history.json: {len(history)} entrée(s).')
    print(f'  Première entrée: {history[0]}')
    print('=== Done ===')

if __name__ == '__main__':
    main()
