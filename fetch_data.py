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

def fred_eu_sentiment():
    """
    Sentiment Zone Euro via FRED — Consumer Confidence OCDE Euro Area.
    Range OCDE typique : -25 à +5. On multiplie ×4 pour avoir une échelle comparable au ZEW (-100/+100).
    """
    for series in ['CSCICP03EAM665S', 'CSCICP02EAM460S', 'BSCICP02EAM460S']:
        try:
            v, d = fred(series)
            v_scaled = v * 4.0  # étire vers range -100/+20 comparable au ZEW
            print(f'  EU Sentiment ({series}) = {v} → scaled {v_scaled:.1f} ({d})')
            return v_scaled, d
        except Exception as e:
            print(f'  [EU Sentiment] {series} échoué: {e}')
    print('  [EU Sentiment] fallback -17.2')
    return -17.2, 'n/a'

def fetch_vstoxx():
    """VSTOXX via plusieurs tickers — essaie 1 mois de données pour éviter les soucis weekend."""
    for sym in ['^V2TX', 'V2TX.DE', '^VSTOXX50']:
        try:
            t = yf.Ticker(sym)
            h = t.history(period='1mo', auto_adjust=True)
            closes = h['Close'].dropna()
            if len(closes) > 0:
                v = float(closes.iloc[-1])
                print(f'  VSTOXX ({sym}) = {v:.2f}')
                return v
        except Exception as e:
            print(f'  [VSTOXX] {sym}: {e}')
    raise ValueError('VSTOXX: tous les tickers ont échoué')

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
    lines = r.text.strip().split('\n')
    for line in reversed(lines):
        parts = line.strip().split(',')
        if len(parts) >= 5:
            try:
                d_str = parts[0].strip()
                v = float(parts[4])
                if not d_str.startswith(('DATE','Your',' ',',')) and not math.isnan(v) and 0.1 < v < 5.0:
                    print(f'  CBOE Put/Call = {v} ({d_str})')
                    return v, d_str
            except (ValueError, IndexError):
                continue
    raise ValueError('CBOE: aucune ligne valide')

def yf_breadth():
    """
    Calcule le % de titres S&P 500 au-dessus de leur MA50.
    Utilise un échantillon de 20 grands titres pour rester rapide.
    """
    tickers = [
        'AAPL','MSFT','NVDA','AMZN','GOOGL','META','TSLA','BRK-B','JPM','JNJ',
        'V','PG','UNH','XOM','HD','MA','LLY','ABBV','MRK','PEP'
    ]
    above = 0
    total = 0
    for sym in tickers:
        try:
            t = yf.Ticker(sym)
            h = t.history(period='3mo', auto_adjust=True)
            closes = h['Close'].dropna().tolist()
            if len(closes) >= 50:
                latest = closes[-1]
                ma50 = sum(closes[-50:]) / 50
                if latest > ma50:
                    above += 1
                total += 1
        except:
            pass
    if total == 0:
        raise ValueError('Breadth: aucun ticker disponible')
    result = (above / total) * 100
    print(f'  Breadth (sample 20) = {result:.1f}% ({above}/{total} au-dessus MA50)')
    return result

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
    zew_val, zew_date   = safe(fred_eu_sentiment,              (-17.2,'n/a'), 'EU Sentiment')
    vstoxx_val          = safe(fetch_vstoxx,                    22.0,          'VSTOXX')
    sp_latest, sp_pct   = safe(lambda: yf_ma('^GSPC', 125),   (5200, 4.0),   'SP500')
    sx5e_lat, sx5e_pct  = safe(lambda: yf_ma('^STOXX50E',125),(4900, 3.0),   'SX5E')
    # Breadth : % S&P 500 au-dessus MA50 via FRED (série USABSCI = Bull/Bear non dispo)
    # On utilise ^SP500-45 (secteur) comme proxy ou on calcule depuis SP500 vs MA50
    # Alternative fiable : on garde le fallback SP500 pct comme proxy breadth
    breadth_val         = safe(lambda: yf_breadth(),            50.0,          'Breadth')
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
    print(f'  data.json écrit.')

    # ── HISTORIQUE — mis à jour directement ici ──
    history_file = 'history.json'
    today_str = date.today().isoformat()

    # Lire l'historique existant
    try:
        with open(history_file, 'r', encoding='utf-8') as f:
            history = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        history = []

    # Supprimer l'entrée du jour si elle existe déjà (on la remplace)
    history = [e for e in history if e.get('date') != today_str]

    # Ajouter l'entrée du jour
    history.append({
        'date':    today_str,
        'scoreUS': scoreUS,
        'scoreEU': scoreEU,
        'vix':     f'{vix_val:.1f}',
        'vstoxx':  f'{vstoxx_val:.1f}',
        'hy':      f'{hy_val:.2f}',
        'pc':      f'{pc_val:.2f}',
        'zew':     f'{zew_val:.1f}',
        'breadth': f'{breadth_val:.0f}',
    })

    # Garder max 365 jours, trié par date
    history = sorted(history, key=lambda e: e['date'])[-365:]

    with open(history_file, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    print(f'  history.json mis à jour ({len(history)} entrées).')

    print('=== Done ===')
    return data

if __name__ == '__main__':
    main()
