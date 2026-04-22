#!/usr/bin/env python3
"""
generate_score_image.py — MarketOmetre
Génère score.png et le commit sur GitHub.
Usage : python generate_score_image.py
Deps  : pip install Pillow requests
"""

import math, base64, os
from datetime import date
import requests
from PIL import Image, ImageDraw, ImageFont

# ── CONFIG ──
FRED_KEY = os.getenv('FRED_KEY', '96e939128c65bf0f827ccfaa87820026')
GH_TOKEN = os.getenv('GH_TOKEN', 'ghp_oNLNlMFbF2xYWKJx6oWIFbshjD1HKCH4')
GH_OWNER = 'Investirblog'
GH_REPO  = 'marketometre'
GH_FILE  = 'score.png'
GH_API   = f'https://api.github.com/repos/{GH_OWNER}/{GH_REPO}/contents/{GH_FILE}'
OUTPUT   = 'score.png'

W, H = 800, 300
BG    = (13,17,23); BG2=(22,28,38); BORDER=(40,48,60)
TEXT  = (240,242,248); MUTED=(155,163,180)

def find_font(bold=False):
    paths = [
        '/usr/share/fonts/truetype/liberation/LiberationSans-{}.ttf'.format('Bold' if bold else 'Regular'),
        '/usr/share/fonts/truetype/dejavu/DejaVuSans{}.ttf'.format('-Bold' if bold else ''),
        'C:/Windows/Fonts/{}.ttf'.format('arialbd' if bold else 'arial'),
    ]
    return next((p for p in paths if os.path.exists(p)), None)

FB = find_font(True); FR = find_font(False)
def fnt(size, bold=False):
    p = FB if bold else FR
    return ImageFont.truetype(p, size) if p else ImageFont.load_default()

def zone_color(s):
    if s<20: return (239,68,68)
    if s<35: return (249,115,22)
    if s<50: return (234,179,8)
    if s<65: return (96,165,250)
    if s<80: return (132,204,22)
    return (34,197,94)

def zone_label(s):
    if s<20: return 'PANIQUE EXTREME'
    if s<35: return 'PEUR'
    if s<50: return 'PRUDENCE'
    if s<65: return 'OPTIMISME MODERE'
    if s<80: return 'OPTIMISME ELEVE'
    return "EXCES D'OPTIMISME"

def clamp(v,lo=0,hi=100): return max(lo,min(hi,v))
def norm(v,lo,hi,inv=False):
    p=(v-lo)/(hi-lo)*100
    return clamp(100-p if inv else p)

# ── FETCH ──
S = requests.Session()
S.headers['User-Agent'] = 'MarketOmetre/1.0'

def fred(series):
    j=S.get(f'https://api.stlouisfed.org/fred/series/observations?series_id={series}&api_key={FRED_KEY}&file_type=json&sort_order=desc&limit=5',timeout=15).json()
    return float(next(o for o in j['observations'] if o['value']!='.')['value'])

def yc(sym,r='1y',i='1d'):
    j=S.get(f'https://query1.finance.yahoo.com/v8/finance/chart/{requests.utils.quote(sym)}?range={r}&interval={i}&includePrePost=false',timeout=15).json()
    return [c for c in j['chart']['result'][0]['indicators']['quote'][0]['close'] if c]

def ylatest(sym): return yc(sym,'5d','1d')[-1]

def yma(sym,days):
    c=yc(sym,'1y','1d'); latest=c[-1]; sl=c[-days:]
    return {'latest':latest,'pct':(latest-sum(sl)/len(sl))/(sum(sl)/len(sl))*100}

def putcall():
    txt=S.get('https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/equitypc.csv',timeout=15).text
    lines=[l for l in txt.strip().split('\n') if l.strip() and not l.startswith(('Your',',',' ','DATE'))]
    pc=float(lines[-1].split(',')[4])
    return pc if not math.isnan(pc) else 0.70

def breadth():
    try: return ylatest('%24SPXA50R')
    except: return 50.0

def safe(fn,fb,lbl):
    try: return fn()
    except Exception as e: print(f'  [WARN] {lbl}: {e}'); return fb

def compute():
    print('Fetching...')
    vix    = safe(lambda:fred('VIXCLS'),           22.0, 'VIX')
    hy     = safe(lambda:fred('BAMLH0A0HYM2'),     4.5,  'HY')
    zew    = safe(lambda:fred('ZEWSELMU'),          0.0,  'ZEW')
    pc     = safe(putcall,                          0.70, 'Put/Call')
    sp     = safe(lambda:yma('^GSPC',125),          {'pct':4.0},'SP500')
    vst    = safe(lambda:ylatest('^V2TX'),          22.0, 'VSTOXX')
    sx5e   = safe(lambda:yma('^STOXX50E',125),      {'pct':3.0},'SX5E')
    br     = safe(breadth,                          50.0, 'Breadth')
    print(f'  VIX={vix:.1f} VSTOXX={vst:.1f} HY={hy:.2f}% PC={pc:.2f} Breadth={br:.1f} ZEW={zew:.1f}')

    us0=norm(vix,10,50,True); us1=norm(pc,0.4,1.2,True)
    us2=norm(br,20,80);       us3=norm(hy,2,10,True); us4=norm(sp['pct'],-30,30)
    sUS=round(clamp(us0*.25+us1*.20+us2*.20+us3*.20+us4*.15))

    itr=vst*0.18
    eu0=norm(vst,10,45,True); eu1=norm(zew,-60,80)
    eu2=norm(sx5e['pct'],-30,30); eu3=norm(itr,2,10,True); eu4=norm(sx5e['pct'],-30,30)
    sEU=round(clamp(eu0*.25+eu1*.20+eu2*.20+eu3*.20+eu4*.15))
    print(f'  Score US={sUS}  EU={sEU}')

    return dict(scoreUS=sUS,scoreEU=sEU,vix=vix,vstoxx=vst,hy=hy,pc=pc,
        us_pillars=[('Volatilite VIX',us0),('Sentiment Put/Call',us1),
                    ('Breadth >MA50',us2),('Stress credit HY',us3),('Momentum S&P',us4)],
        eu_pillars=[('Volatilite VSTOXX',eu0),('Sentiment ZEW',eu1),
                    ('Breadth SX5E',eu2),('Stress iTraxx',eu3),('Momentum SX5E',eu4)])

# ── DRAW ──
def gauge_arc(img,cx,cy,r,score,color,thick=8):
    ov=Image.new('RGBA',img.size,(0,0,0,0)); od=ImageDraw.Draw(ov)
    bb=[cx-r,cy-r,cx+r,cy+r]
    od.arc(bb,180,360,fill=(40,48,60,255),width=thick)
    if score>0: od.arc(bb,180,180+(score/100)*180,fill=(*color,255),width=thick)
    img.paste(Image.alpha_composite(img.convert('RGBA'),ov).convert('RGB'))

def needle(draw,cx,cy,rn,score):
    a=math.radians(180+(score/100)*180)
    draw.line([(cx,cy),(cx+rn*math.cos(a),cy+rn*math.sin(a))],fill=(255,255,255),width=3)
    draw.ellipse([cx-4,cy-4,cx+4,cy+4],fill=(255,255,255))

def pillar_row(draw,x,y,w,name,score):
    color=zone_color(score)
    nw=130; vw=28; bx=x+nw+6; bw=w-nw-vw-14; bh=5; by=y+4
    draw.text((x,y),name,font=fnt(10),fill=MUTED)
    draw.rounded_rectangle([bx,by,bx+bw,by+bh],radius=3,fill=(40,48,60))
    fw=max(0,int(bw*score/100))
    if fw>0: draw.rounded_rectangle([bx,by,bx+fw,by+bh],radius=3,fill=color)
    draw.text((bx+bw+6,y),str(round(score)),font=fnt(10,True),fill=color)

def draw_card(img,draw,cx,cy,cw,ch,label,idx_lbl,score,pillars,accent):
    pad=18; color=zone_color(score)
    draw.rounded_rectangle([cx,cy,cx+cw,cy+ch],radius=12,fill=BG2,outline=BORDER,width=1)
    draw.rounded_rectangle([cx+1,cy+1,cx+cw-1,cy+4],radius=3,fill=accent)
    draw.ellipse([cx+pad,cy+15,cx+pad+8,cy+23],fill=accent)
    draw.text((cx+pad+12,cy+14),label.upper(),font=fnt(11,True),fill=MUTED)
    iw=draw.textlength(idx_lbl,font=fnt(11))
    draw.text((cx+cw-pad-iw,cy+14),idx_lbl,font=fnt(11),fill=MUTED)
    draw.line([(cx+pad,cy+34),(cx+cw-pad,cy+34)],fill=BORDER,width=1)

    # Gauge
    arc_r=44; arc_cx=cx+cw//2; arc_cy=cy+34+arc_r+8
    gauge_arc(img,arc_cx,arc_cy,arc_r,score,color)
    needle(draw,arc_cx,arc_cy,arc_r-10,score)

    # Score below gauge pivot
    ss=str(score); sw=draw.textlength(ss,font=fnt(42,True))
    score_y=arc_cy+6
    draw.text((arc_cx-sw//2,score_y),ss,font=fnt(42,True),fill=color)
    zl=zone_label(score); zlw=draw.textlength(zl,font=fnt(9,True))
    draw.text((arc_cx-zlw//2,score_y+50),zl,font=fnt(9,True),fill=color)

    # Pillars — start well below zone label
    py=score_y+50+18
    for pname,pscore in pillars:
        pillar_row(draw,cx+pad,py,cw-pad*2,pname,pscore)
        py+=19

def generate(data):
    img=Image.new('RGB',(W,H),BG); draw=ImageDraw.Draw(img)
    # Header
    draw.rectangle([0,0,W,46],fill=(16,21,30))
    draw.line([(0,46),(W,46)],fill=BORDER,width=1)
    draw.text((20,12),'Market',font=fnt(18,True),fill=TEXT)
    mw=draw.textlength('Market',font=fnt(18,True))
    draw.text((20+mw,12),'Ometre',font=fnt(18),fill=MUTED)
    be=20+mw+draw.textlength('Ometre',font=fnt(18))
    draw.line([(be+14,13),(be+14,35)],fill=BORDER,width=1)

    kpis=[('VIX',f"{data['vix']:.1f}",(96,165,250)),
          ('VSTOXX',f"{data['vstoxx']:.1f}",(96,165,250)),
          ('HY Spread',f"{data['hy']:.2f}%",zone_color(round(norm(data['hy'],2,10,True)))),
          ('Put/Call',f"{data['pc']:.2f}",MUTED)]
    kx=be+26
    for k,v,vc in kpis:
        draw.text((kx,11),k,font=fnt(10),fill=MUTED)
        draw.text((kx,25),v,font=fnt(13,True),fill=vc)
        kx+=max(draw.textlength(k,font=fnt(10)),draw.textlength(v,font=fnt(13,True)))+20

    ds=date.today().strftime('%d/%m/%Y')
    dw=draw.textlength(ds,font=fnt(11))
    draw.text((W-20-dw,17),ds,font=fnt(11),fill=MUTED)

    margin=13; gap=6; cw=(W-margin*2-gap)//2; ch=H-52-10
    draw_card(img,draw,margin,      52,cw,ch,'Etats-Unis','S&P 500  VIX',   data['scoreUS'],data['us_pillars'],(59,130,246))
    draw_card(img,draw,margin+cw+gap,52,cw,ch,'Europe',  'Eurostoxx  VSTOXX',data['scoreEU'],data['eu_pillars'],(16,185,129))

    ft='marketometre.netlify.app  |  FRED · CBOE · Yahoo Finance  |  A titre informatif'
    fw=draw.textlength(ft,font=fnt(9))
    draw.text(((W-fw)//2,H-12),ft,font=fnt(9),fill=(70,80,100))
    img.save(OUTPUT); print(f'  Image: {OUTPUT}')

# ── GITHUB ──
def commit():
    if not GH_TOKEN: print('  [SKIP] Pas de GH_TOKEN'); return
    with open(OUTPUT,'rb') as f: content=base64.b64encode(f.read()).decode()
    hdrs={'Authorization':f'token {GH_TOKEN}','Accept':'application/vnd.github.v3+json'}
    sha=None
    r=requests.get(GH_API,headers=hdrs,timeout=15)
    if r.status_code==200: sha=r.json().get('sha')
    body={'message':f'chore: score image {date.today()}','content':content}
    if sha: body['sha']=sha
    r2=requests.put(GH_API,headers=hdrs,json=body,timeout=30)
    if r2.status_code in(200,201): print(f'  GitHub OK → https://raw.githubusercontent.com/{GH_OWNER}/{GH_REPO}/main/{GH_FILE}')
    else: print(f'  [ERROR] GitHub {r2.status_code}: {r2.text[:200]}')

if __name__=='__main__':
    print('=== MarketOmetre score image ===')
    data=compute(); generate(data); commit()
    print('=== Done ===')
