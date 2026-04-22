// netlify/functions/telegram-alert.js
// Cron : chaque jour de semaine à 8h UTC (10h heure belge)
// Calcul IDENTIQUE au frontend index.html

const FRED_KEY = '96e939128c65bf0f827ccfaa87820026';
const TG_TOKEN = '8798775874:AAHgmCMZ1KJfHAw1D8uVn0_0GDhKZDGakvo';
const TG_CHAT  = '8712054832';
const PROXY    = 'https://corsproxy.io/?';

const SEUIL_PANIQUE  = 25;
const SEUIL_EUPHORIE = 75;
const SEUIL_TOUJOURS = true;

// ── Helpers — IDENTIQUES au frontend ──
function clamp(v,a=0,b=100){return Math.max(a,Math.min(b,v))}
function normalize(v,lo,hi,inv=false){let p=(v-lo)/(hi-lo)*100;if(inv)p=100-p;return clamp(p)}

const scoreVix    = v  => normalize(v,   10, 50,  true);
const scoreVstoxx = v  => normalize(v,   10, 45,  true);
const scorePutCall= pc => normalize(pc,  0.4, 1.2, true);
const scoreHY     = s  => normalize(s,   2,  10,  true);
const scoreMom    = p  => normalize(p,  -30, 30);
const scoreBreadth= b  => normalize(b,   20, 80);        // % titres > MA50
const scoreZEW    = z  => normalize(z,  -60, 80);

// 6 zones — identiques au site
function zoneLabel(s){
  if(s<20) return 'Panique extrême';
  if(s<35) return 'Peur';
  if(s<50) return 'Prudence';
  if(s<65) return 'Optimisme modéré';
  if(s<80) return 'Optimisme élevé';
  return "Excès d'optimisme";
}
function zoneEmoji(s){
  if(s<20) return '🔴';
  if(s<35) return '🟠';
  if(s<50) return '🟡';
  if(s<65) return '🔵';
  if(s<80) return '🟢';
  return '🟢✨';
}

// ── Fetch FRED (direct, pas de proxy — FRED supporte CORS côté serveur) ──
async function fredLatest(series){
  const url=`https://api.stlouisfed.org/fred/series/observations?series_id=${series}&api_key=${FRED_KEY}&file_type=json&sort_order=desc&limit=5`;
  const r=await fetch(url,{headers:{'User-Agent':'MarketOmetre/1.0'}});
  if(!r.ok) throw new Error(`FRED ${series} HTTP ${r.status}`);
  const j=await r.json();
  const obs=j.observations?.find(o=>o.value!=='.');
  if(!obs) throw new Error(`FRED ${series}: no valid observation`);
  const v=parseFloat(obs.value);
  console.log(`[FRED] ${series} = ${v} (date: ${obs.date})`);
  return v;
}

// ── Fetch CBOE Put/Call via proxy ──
async function fetchPutCall(){
  const url='https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/equitypc.csv';
  const r=await fetch(PROXY+encodeURIComponent(url),{headers:{'User-Agent':'MarketOmetre/1.0'}});
  if(!r.ok) throw new Error(`CBOE HTTP ${r.status}`);
  const txt=await r.text();
  const lines=txt.trim().split('\n').filter(l=>
    l.trim()&&!l.startsWith('Your')&&!l.startsWith(',')&&!l.startsWith('DATE')&&!l.startsWith(' '));
  const parts=lines[lines.length-1].split(',');
  const pc=parseFloat(parts[4]);
  if(isNaN(pc)) throw new Error('CBOE: NaN Put/Call');
  console.log(`[CBOE] Put/Call = ${pc} (line: ${lines[lines.length-1]})`);
  return pc;
}

// ── Fetch Yahoo Finance via proxy ──
async function yahooCloses(sym,range='1y'){
  const url=`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?range=${range}&interval=1d&includePrePost=false`;
  const r=await fetch(PROXY+encodeURIComponent(url),{headers:{'User-Agent':'MarketOmetre/1.0'}});
  if(!r.ok) throw new Error(`Yahoo ${sym} HTTP ${r.status}`);
  const j=await r.json();
  const closes=j.chart?.result?.[0]?.indicators?.quote?.[0]?.close?.filter(v=>v!=null);
  if(!closes?.length) throw new Error(`Yahoo ${sym}: no closes`);
  return closes;
}

async function yahooLatest(sym){
  const c=await yahooCloses(sym,'5d');
  const v=c[c.length-1];
  console.log(`[Yahoo] ${sym} latest = ${v.toFixed(2)}`);
  return v;
}

async function yahooMA(sym,days){
  const c=await yahooCloses(sym,'1y');
  const latest=c[c.length-1];
  const slice=c.slice(-days);
  const ma=slice.reduce((a,b)=>a+b,0)/slice.length;
  const pct=(latest-ma)/ma*100;
  console.log(`[Yahoo] ${sym} latest=${latest.toFixed(1)} MA${days}=${ma.toFixed(1)} pct=${pct.toFixed(2)}%`);
  return{latest,pct};
}

async function fetchBreadth(){
  // $SPXA50R = % des titres S&P 500 au-dessus de leur MA50 (NYSE)
  const v=await yahooLatest('%24SPXA50R');
  console.log(`[Yahoo] Breadth SPXA50R = ${v.toFixed(1)}%`);
  return v;
}

async function safe(fn,fb,label){
  try{return await fn()}
  catch(e){console.warn(`[WARN] ${label}: ${e.message}`);return fb}
}

// ── Telegram ──
async function sendTelegram(message){
  const r=await fetch(`https://api.telegram.org/bot${TG_TOKEN}/sendMessage`,{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({chat_id:TG_CHAT,text:message,parse_mode:'HTML'})
  });
  const j=await r.json();
  if(!j.ok) throw new Error('Telegram: '+j.description);
  return j;
}

// ── MAIN ──
export async function handler(event){
  try{
    console.log('[MarketOmètre] Cron start', new Date().toISOString());

    // Fetch — même sources et même MA que le frontend (125j)
    const [vix,hy,pc,spData,vstoxx,sx5eData,zew,breadth]=await Promise.all([
      safe(()=>fredLatest('VIXCLS'),          22,            'VIX'),
      safe(()=>fredLatest('BAMLH0A0HYM2'),    4.5,           'HY Spread'),
      safe(()=>fetchPutCall(),                0.70,          'Put/Call'),
      safe(()=>yahooMA('^GSPC',125),          {latest:5200,pct:4}, 'SP500 MA125'),
      safe(()=>yahooLatest('^V2TX'),          22,            'VSTOXX'),
      safe(()=>yahooMA('^STOXX50E',125),      {latest:4900,pct:3}, 'SX5E MA125'),
      safe(()=>fredLatest('ZEWSELMU'),        0,             'ZEW'),
      safe(()=>fetchBreadth(),                50,            'Breadth'),
    ]);

    const iTraxxProxy=vstoxx*0.18;

    // US — identique au frontend
    const us0=scoreVix(vix), us1=scorePutCall(pc),
          us2=scoreBreadth(breadth), us3=scoreHY(hy), us4=scoreMom(spData.pct);
    const scoreUS=Math.round(clamp(us0*.25+us1*.20+us2*.20+us3*.20+us4*.15));

    // EU — identique au frontend
    const eu0=scoreVstoxx(vstoxx), eu1=scoreZEW(zew),
          eu2=scoreMom(sx5eData.pct), eu3=scoreHY(iTraxxProxy), eu4=scoreMom(sx5eData.pct);
    const scoreEU=Math.round(clamp(eu0*.25+eu1*.20+eu2*.20+eu3*.20+eu4*.15));

    console.log(`[MarketOmètre] Score US=${scoreUS} (${zoneLabel(scoreUS)}) EU=${scoreEU} (${zoneLabel(scoreEU)})`);

    const alertUS = scoreUS<SEUIL_PANIQUE || scoreUS>SEUIL_EUPHORIE;
    const alertEU = scoreEU<SEUIL_PANIQUE || scoreEU>SEUIL_EUPHORIE;
    if(!SEUIL_TOUJOURS && !alertUS && !alertEU){
      console.log('[MarketOmètre] Pas de seuil atteint.');
      return{statusCode:200,body:'No alert needed'};
    }

    const flagUS=alertUS?(scoreUS<SEUIL_PANIQUE?'🚨 ':'🔔 '):'';
    const flagEU=alertEU?(scoreEU<SEUIL_PANIQUE?'🚨 ':'🔔 '):'';
    const today=new Date().toLocaleDateString('fr-FR',{weekday:'long',day:'numeric',month:'long'});

    const msg=
`📊 <b>MarketOmètre — ${today}</b>

${flagUS}${zoneEmoji(scoreUS)} <b>États-Unis</b>  →  <b>${scoreUS}/100</b> — ${zoneLabel(scoreUS)}
  • VIX : ${vix.toFixed(1)}   |   Put/Call : ${pc.toFixed(2)}
  • HY Spread : ${hy.toFixed(2)}%   |   Breadth : ${breadth.toFixed(0)}%

${flagEU}${zoneEmoji(scoreEU)} <b>Europe</b>  →  <b>${scoreEU}/100</b> — ${zoneLabel(scoreEU)}
  • VSTOXX : ${vstoxx.toFixed(1)}   |   ZEW : ${zew.toFixed(1)}
  • Eurostoxx vs MA125 : ${sx5eData.pct>=0?'+':''}${sx5eData.pct.toFixed(1)}%

${alertUS||alertEU?'⚠️ <b>Seuil d\'alerte atteint !</b>\n':''}\
🔗 <a href="https://marketometre.netlify.app">Voir le détail complet</a>`;

    await sendTelegram(msg);
    console.log('[MarketOmètre] Message envoyé.');
    return{statusCode:200,body:'Alert sent'};

  }catch(err){
    console.error('[MarketOmètre] Erreur:', err.message);
    try{await sendTelegram(`⚠️ <b>MarketOmètre — Erreur cron</b>\n\n${err.message}`);}catch(_){}
    return{statusCode:500,body:err.message};
  }
}
