// netlify/functions/telegram-alert.js
// Cron: chaque jour de semaine à 8h UTC (10h heure belge)
// IMPORTANT: côté serveur Netlify, on fetch DIRECTEMENT sans proxy CORS

const FRED_KEY = '96e939128c65bf0f827ccfaa87820026';
const TG_TOKEN = '8798775874:AAHgmCMZ1KJfHAw1D8uVn0_0GDhKZDGakvo';
// Envoie à ton chat perso ET au canal public
const TG_CHATS = ['8712054832', '@marketometre'];

const SEUIL_PANIQUE  = 25;
const SEUIL_EUPHORIE = 75;
const SEUIL_TOUJOURS = true;

// ── ZONE HELPERS — identiques au site ──
function zoneLabel(s){
  if(s<15) return 'Panique extrême';
  if(s<30) return 'Peur';
  if(s<45) return 'Prudence';
  if(s<55) return 'Neutre';
  if(s<70) return 'Optimisme';
  if(s<85) return 'Euphorie';
  return 'Euphorie extrême';
}
function zoneEmoji(s){
  if(s<15) return '🔴';
  if(s<30) return '🟠';
  if(s<45) return '🟡';
  if(s<55) return '⚪';
  if(s<70) return '🔵';
  if(s<85) return '🟢';
  return '🟢✨';
}

// ── SCORING — identique au site ──
function clamp(v,a=0,b=100){return Math.max(a,Math.min(b,v))}
function normalize(v,lo,hi,inv=false){
  let p=(v-lo)/(hi-lo)*100;
  return clamp(inv?100-p:p);
}
const scoreVix     = v  => normalize(v,   10, 50,  true);
const scoreVstoxx  = v  => normalize(v,   10, 45,  true);
const scorePutCall = pc => normalize(pc, 0.4, 1.2, true);
const scoreHY      = s  => normalize(s,    2, 10,  true);
const scoreMom     = p  => normalize(p,  -30, 30);
const scoreBreadth = b  => normalize(b,   20, 80);
const scoreZEW     = z  => normalize(z,  -60, 80);

// ── FETCH HELPERS — directs, sans proxy (côté serveur) ──
const HEADERS = {'User-Agent':'MarketOmetre-Bot/1.0','Accept':'application/json'};

async function fredLatest(series){
  const url=`https://api.stlouisfed.org/fred/series/observations?series_id=${series}&api_key=${FRED_KEY}&file_type=json&sort_order=desc&limit=5`;
  const r=await fetch(url,{headers:HEADERS});
  if(!r.ok) throw new Error(`FRED ${series}: HTTP ${r.status}`);
  const j=await r.json();
  const obs=j.observations?.find(o=>o.value!=='.');
  if(!obs) throw new Error(`FRED ${series}: no data`);
  const v=parseFloat(obs.value);
  console.log(`FRED ${series} = ${v} (${obs.date})`);
  return v;
}

async function yahooFetch(sym, range='1y'){
  // Yahoo Finance v8 — direct depuis serveur, pas de CORS problem
  const url=`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?range=${range}&interval=1d&includePrePost=false`;
  const r=await fetch(url,{headers:{...HEADERS,'Accept':'*/*'}});
  if(!r.ok){
    // Fallback sur query2
    const url2=`https://query2.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?range=${range}&interval=1d&includePrePost=false`;
    const r2=await fetch(url2,{headers:{...HEADERS,'Accept':'*/*'}});
    if(!r2.ok) throw new Error(`Yahoo ${sym}: HTTP ${r.status}/${r2.status}`);
    const j2=await r2.json();
    return j2.chart.result[0].indicators.quote[0].close.filter(v=>v!=null);
  }
  const j=await r.json();
  return j.chart.result[0].indicators.quote[0].close.filter(v=>v!=null);
}

async function yahooLatest(sym){
  const c=await yahooFetch(sym,'5d');
  const v=c[c.length-1];
  console.log(`Yahoo ${sym} = ${v.toFixed(2)}`);
  return v;
}

async function yahooMA(sym,days){
  const c=await yahooFetch(sym,'1y');
  const latest=c[c.length-1];
  const slice=c.slice(-days);
  const ma=slice.reduce((a,b)=>a+b,0)/slice.length;
  const pct=(latest-ma)/ma*100;
  console.log(`Yahoo ${sym} latest=${latest.toFixed(1)} MA${days}=${ma.toFixed(1)} pct=${pct.toFixed(2)}%`);
  return{latest,pct};
}

async function fetchPutCall(){
  // CBOE CSV direct — pas de CORS côté serveur
  const url='https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/equitypc.csv';
  const r=await fetch(url,{headers:{...HEADERS,'Accept':'text/csv,text/plain,*/*'}});
  if(!r.ok) throw new Error(`CBOE: HTTP ${r.status}`);
  const txt=await r.text();
  const lines=txt.trim().split('\n').filter(l=>
    l.trim()&&!l.startsWith('Your')&&!l.startsWith(',')&&
    !l.startsWith('DATE')&&!l.startsWith(' '));
  const parts=lines[lines.length-1].split(',');
  const pc=parseFloat(parts[4]);
  if(isNaN(pc)) throw new Error('CBOE: NaN');
  console.log(`CBOE Put/Call = ${pc} (${lines[lines.length-1].split(',')[0]})`);
  return pc;
}

async function fetchBreadth(){
  const v=await yahooLatest('%24SPXA50R');
  return v;
}

async function safe(fn,fallback,label){
  try{return await fn();}
  catch(e){console.warn(`[WARN] ${label}: ${e.message}`);return fallback;}
}

// ── TELEGRAM ──
async function sendTelegram(message){
  for(const chatId of TG_CHATS){
    try{
      const r=await fetch(`https://api.telegram.org/bot${TG_TOKEN}/sendMessage`,{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({chat_id:chatId,text:message,parse_mode:'HTML'})
      });
      const j=await r.json();
      if(j.ok) console.log(`Telegram OK → ${chatId}`);
      else console.warn(`Telegram ERREUR ${chatId}: ${j.description}`);
    }catch(e){
      console.warn(`Telegram EXCEPTION ${chatId}: ${e.message}`);
    }
  }
}

// ── HANDLER PRINCIPAL ──
export async function handler(event){
  try{
    const now=new Date();
    console.log('=== MarketOmetre cron start', now.toISOString(),'===');

    // Fetch toutes les données — SANS proxy, direct serveur
    const [vix,hy,pc,spData,vstoxx,sx5eData,zew,breadth]=await Promise.all([
      safe(()=>fredLatest('VIXCLS'),            22.0,          'VIX'),
      safe(()=>fredLatest('BAMLH0A0HYM2'),       4.5,          'HY Spread'),
      safe(()=>fetchPutCall(),                   0.70,          'Put/Call'),
      safe(()=>yahooMA('^GSPC',125),    {latest:5200,pct:4.0}, 'SP500'),
      safe(()=>yahooLatest('^V2TX'),            22.0,          'VSTOXX'),
      safe(()=>yahooMA('^STOXX50E',125),{latest:4900,pct:3.0}, 'SX5E'),
      safe(()=>fredLatest('ZEWSELMU'),           0.0,          'ZEW'),
      safe(()=>fetchBreadth(),                  50.0,          'Breadth'),
    ]);

    const iTraxx=vstoxx*0.18;

    // Calcul US
    const us0=scoreVix(vix), us1=scorePutCall(pc),
          us2=scoreBreadth(breadth), us3=scoreHY(hy), us4=scoreMom(spData.pct);
    const scoreUS=Math.round(clamp(us0*.25+us1*.20+us2*.20+us3*.20+us4*.15));

    // Calcul EU
    const eu0=scoreVstoxx(vstoxx), eu1=scoreZEW(zew),
          eu2=scoreMom(sx5eData.pct), eu3=scoreHY(iTraxx), eu4=scoreMom(sx5eData.pct);
    const scoreEU=Math.round(clamp(eu0*.25+eu1*.20+eu2*.20+eu3*.20+eu4*.15));

    console.log(`Scores: US=${scoreUS} (${zoneLabel(scoreUS)}) EU=${scoreEU} (${zoneLabel(scoreEU)})`);

    // Décision envoi
    const alertUS=scoreUS<SEUIL_PANIQUE||scoreUS>SEUIL_EUPHORIE;
    const alertEU=scoreEU<SEUIL_PANIQUE||scoreEU>SEUIL_EUPHORIE;
    if(!SEUIL_TOUJOURS&&!alertUS&&!alertEU){
      console.log('Pas de seuil atteint, pas d\'envoi.');
      return{statusCode:200,body:'No alert needed'};
    }

    const flagUS=alertUS?(scoreUS<SEUIL_PANIQUE?'🚨 ':'🔔 '):'';
    const flagEU=alertEU?(scoreEU<SEUIL_PANIQUE?'🚨 ':'🔔 '):'';
    const today=now.toLocaleDateString('fr-FR',{weekday:'long',day:'numeric',month:'long'});
    const spSign=spData.pct>=0?'+':'';
    const sx5eSign=sx5eData.pct>=0?'+':'';

    const msg=
`📊 <b>MarketOmètre — ${today}</b>

${flagUS}${zoneEmoji(scoreUS)} <b>États-Unis</b> → <b>${scoreUS}/100</b> — ${zoneLabel(scoreUS)}
  • VIX : ${vix.toFixed(1)}  |  Put/Call : ${pc.toFixed(2)}
  • HY Spread : ${hy.toFixed(2)}%  |  Breadth : ${breadth.toFixed(0)}%

${flagEU}${zoneEmoji(scoreEU)} <b>Europe</b> → <b>${scoreEU}/100</b> — ${zoneLabel(scoreEU)}
  • VSTOXX : ${vstoxx.toFixed(1)}  |  ZEW : ${zew.toFixed(1)}
  • Eurostoxx vs MA125 : ${sx5eSign}${sx5eData.pct.toFixed(1)}%

${alertUS||alertEU?'⚠️ <b>Seuil d\'alerte atteint !</b>':'✅ Marchés dans la zone normale'}

🔗 <a href="https://marketometre.netlify.app">Voir le détail complet</a>`;

    await sendTelegram(msg);
    console.log('=== Done ===');
    return{statusCode:200,body:'OK'};

  }catch(err){
    console.error('Erreur critique:', err.message);
    try{
      await sendTelegram(`⚠️ <b>MarketOmètre — Erreur cron</b>\n\n${err.message}`);
    }catch(_){}
    return{statusCode:500,body:err.message};
  }
}
