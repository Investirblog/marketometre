// netlify/functions/telegram-alert.js
// Tourne automatiquement chaque jour de semaine à 8h00 UTC (10h00 heure belge)
// Envoie une alerte Telegram si le score US ou EU dépasse les seuils

const FRED_KEY  = '96e939128c65bf0f827ccfaa87820026';
const TG_TOKEN  = '8798775874:AAHgmCMZ1KJfHAw1D8uVn0_0GDhKZDGakvo';
const TG_CHAT   = '8712054832';
const PROXY     = 'https://corsproxy.io/?';

// Seuils d'alerte
const SEUIL_PANIQUE   = 25;   // score < 25 → alerte panique
const SEUIL_EUPHORIE  = 75;   // score > 75 → alerte euphorie
const SEUIL_TOUJOURS  = true; // mettre false pour n'alerter qu'aux seuils extrêmes

// ── helpers ──
function clamp(v,a=0,b=100){return Math.max(a,Math.min(b,v))}
function normalize(v,lo,hi,inv=false){let p=(v-lo)/(hi-lo)*100;if(inv)p=100-p;return clamp(p)}

const scoreVix    = v  => normalize(v,   10, 50,  true);
const scoreVstoxx = v  => normalize(v,   10, 45,  true);
const scorePutCall= pc => normalize(pc,  0.4, 1.2, true);
const scoreHY     = s  => normalize(s,   2,  10,  true);
const scoreMom    = p  => normalize(p,  -30, 30);
const scoreZEW    = z  => normalize(z,  -60, 80);

function zoneEmoji(s){
  if(s<20) return '🔴 PANIQUE EXTRÊME';
  if(s<40) return '🟠 Peur';
  if(s<60) return '🟡 Neutre';
  if(s<80) return '🟢 Euphorie';
  return '🟢🟢 EUPHORIE EXTRÊME';
}

// ── fetch FRED ──
async function fredLatest(series){
  const url=`https://api.stlouisfed.org/fred/series/observations?series_id=${series}&api_key=${FRED_KEY}&file_type=json&sort_order=desc&limit=5`;
  const r=await fetch(url);
  const j=await r.json();
  const obs=j.observations.find(o=>o.value!=='.');
  return parseFloat(obs.value);
}

// ── fetch CBOE Put/Call ──
async function fetchPutCall(){
  const url='https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/equitypc.csv';
  const r=await fetch(PROXY+encodeURIComponent(url));
  const txt=await r.text();
  const lines=txt.trim().split('\n').filter(l=>l.trim()&&!l.startsWith('Your')&&!l.startsWith(',')&&!l.startsWith('DATE')&&!l.startsWith(' '));
  const parts=lines[lines.length-1].split(',');
  const pc=parseFloat(parts[4]);
  return isNaN(pc)?0.7:pc;
}

// ── fetch Yahoo Finance ──
async function yahooCloses(sym,range){
  const url=`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?range=${range}&interval=1d&includePrePost=false`;
  const r=await fetch(PROXY+encodeURIComponent(url));
  const j=await r.json();
  return j.chart.result[0].indicators.quote[0].close.filter(v=>v!=null);
}
async function yahooLatest(sym){const c=await yahooCloses(sym,'5d');return c[c.length-1]}
async function yahooMA(sym,days){
  const c=await yahooCloses(sym,'1y');
  const latest=c[c.length-1];
  const slice=c.slice(-days);
  const ma=slice.reduce((a,b)=>a+b,0)/slice.length;
  return{latest,pct:(latest-ma)/ma*100};
}

async function safe(fn,fb,label){
  try{return await fn()}
  catch(e){console.warn('[Telegram cron]',label,e.message);return fb}
}

// ── send Telegram ──
async function sendTelegram(message){
  const url=`https://api.telegram.org/bot${TG_TOKEN}/sendMessage`;
  const r=await fetch(url,{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({
      chat_id:TG_CHAT,
      text:message,
      parse_mode:'HTML'
    })
  });
  const j=await r.json();
  if(!j.ok) throw new Error('Telegram API error: '+j.description);
  return j;
}

// ── MAIN HANDLER ──
export async function handler(event){
  try{
    console.log('[MarketOmètre] Cron démarré —', new Date().toISOString());

    const [vix,hySpread,putCall,spData,vstoxx,sx5eData,zew]=await Promise.all([
      safe(()=>fredLatest('VIXCLS'),         22,  'VIX'),
      safe(()=>fredLatest('BAMLH0A0HYM2'),   4.5, 'HY Spread'),
      safe(()=>fetchPutCall(),               0.70,'Put/Call'),
      safe(()=>yahooMA('^GSPC',200),         {latest:5200,pct:4},'SP500'),
      safe(()=>yahooLatest('^V2TX'),         22,  'VSTOXX'),
      safe(()=>yahooMA('^STOXX50E',200),     {latest:4900,pct:3},'Eurostoxx'),
      safe(()=>fredLatest('ZEWSELMU'),       0,   'ZEW'),
    ]);

    const iTraxxProxy=vstoxx*0.18;

    // Calcul scores
    const us0=scoreVix(vix),us1=scorePutCall(putCall),us2=scoreMom(spData.pct),us3=scoreHY(hySpread),us4=scoreMom(spData.pct);
    const scoreUS=Math.round(clamp(us0*.25+us1*.20+us2*.20+us3*.20+us4*.15));

    const eu0=scoreVstoxx(vstoxx),eu1=scoreZEW(zew),eu2=scoreMom(sx5eData.pct),eu3=scoreHY(iTraxxProxy),eu4=scoreMom(sx5eData.pct);
    const scoreEU=Math.round(clamp(eu0*.25+eu1*.20+eu2*.20+eu3*.20+eu4*.15));

    console.log(`[MarketOmètre] Score US=${scoreUS} EU=${scoreEU}`);

    // Décision d'envoi
    const alertUS = scoreUS < SEUIL_PANIQUE || scoreUS > SEUIL_EUPHORIE;
    const alertEU = scoreEU < SEUIL_PANIQUE || scoreEU > SEUIL_EUPHORIE;
    const shouldSend = SEUIL_TOUJOURS || alertUS || alertEU;

    if(!shouldSend){
      console.log('[MarketOmètre] Pas de seuil atteint, pas d\'envoi.');
      return{statusCode:200,body:'No alert needed'};
    }

    // Icône alerte si seuil dépassé
    const flagUS = alertUS ? (scoreUS<SEUIL_PANIQUE?'🚨':'🔔') : '';
    const flagEU = alertEU ? (scoreEU<SEUIL_PANIQUE?'🚨':'🔔') : '';

    const today=new Date().toLocaleDateString('fr-FR',{weekday:'long',day:'numeric',month:'long'});

    const message=`📊 <b>MarketOmètre — ${today}</b>

${flagUS}<b>États-Unis</b>  →  <b>${scoreUS}/100</b>  ${zoneEmoji(scoreUS)}
  • VIX : ${vix.toFixed(1)}   Put/Call : ${putCall.toFixed(2)}
  • HY Spread : ${hySpread.toFixed(2)}%   S&amp;P500 vs MA200 : ${spData.pct>=0?'+':''}${spData.pct.toFixed(1)}%

${flagEU}<b>Europe</b>  →  <b>${scoreEU}/100</b>  ${zoneEmoji(scoreEU)}
  • VSTOXX : ${vstoxx.toFixed(1)}   ZEW : ${zew.toFixed(1)}
  • Eurostoxx vs MA200 : ${sx5eData.pct>=0?'+':''}${sx5eData.pct.toFixed(1)}%

${alertUS||alertEU?'⚠️ <b>Seuil d\'alerte atteint !</b>':'✅ Marchés dans la zone normale'}

🔗 <a href="https://marketometre.netlify.app">Voir le détail</a>`;

    await sendTelegram(message);
    console.log('[MarketOmètre] Message Telegram envoyé.');

    return{statusCode:200,body:'Alert sent'};

  }catch(err){
    console.error('[MarketOmètre] Erreur critique:', err.message);
    // Notifier l'erreur sur Telegram aussi
    try{
      await sendTelegram(`⚠️ <b>MarketOmètre — Erreur cron</b>\n\n${err.message}`);
    }catch(_){}
    return{statusCode:500,body:err.message};
  }
}
