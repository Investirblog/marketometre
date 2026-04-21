// netlify/functions/save-history.js
// Reçoit POST {date, scoreUS, scoreEU, vix, vstoxx, hy, pc, breadth, zew}
// Lit history.json depuis GitHub, ajoute/remplace l'entrée du jour, réécrit le fichier

const GH_TOKEN = process.env.GH_TOKEN; // à ajouter dans Netlify > Environment Variables
const GH_OWNER = 'Investirblog';
const GH_REPO  = 'marketometre';
const GH_FILE  = 'history.json';
const GH_API   = `https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/contents/${GH_FILE}`;

export async function handler(event) {
  // CORS — accepter depuis n'importe quelle origine (le site public)
  const headers = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  };

  if (event.httpMethod === 'OPTIONS') {
    return { statusCode: 204, headers, body: '' };
  }

  if (event.httpMethod !== 'POST') {
    return { statusCode: 405, headers, body: 'Method not allowed' };
  }

  if (!GH_TOKEN) {
    console.error('[save-history] GH_TOKEN manquant dans les variables Netlify');
    return { statusCode: 500, headers, body: 'Server config error' };
  }

  try {
    const entry = JSON.parse(event.body);
    if (!entry.date || isNaN(entry.scoreUS) || isNaN(entry.scoreEU)) {
      return { statusCode: 400, headers, body: 'Invalid payload' };
    }

    // 1. Lire le fichier actuel depuis GitHub
    const getRes = await fetch(GH_API, {
      headers: {
        Authorization: `token ${GH_TOKEN}`,
        Accept: 'application/vnd.github.v3+json',
      }
    });

    let history = [];
    let sha = null;

    if (getRes.ok) {
      const ghData = await getRes.json();
      sha = ghData.sha; // nécessaire pour mettre à jour
      const decoded = Buffer.from(ghData.content, 'base64').toString('utf8');
      history = JSON.parse(decoded);
    } else if (getRes.status === 404) {
      // Fichier n'existe pas encore — on va le créer
      sha = null;
    } else {
      throw new Error(`GitHub GET failed: ${getRes.status}`);
    }

    // 2. Ajouter/remplacer l'entrée du jour
    history = history.filter(e => e.date !== entry.date);
    history.push(entry);
    // Trier par date croissante, garder max 365 jours
    history.sort((a, b) => a.date.localeCompare(b.date));
    if (history.length > 365) history = history.slice(-365);

    // 3. Réécrire sur GitHub
    const content = Buffer.from(JSON.stringify(history, null, 2)).toString('base64');
    const body = {
      message: `chore: update history ${entry.date}`,
      content,
      ...(sha ? { sha } : {})
    };

    const putRes = await fetch(GH_API, {
      method: 'PUT',
      headers: {
        Authorization: `token ${GH_TOKEN}`,
        Accept: 'application/vnd.github.v3+json',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body)
    });

    if (!putRes.ok) {
      const err = await putRes.text();
      throw new Error(`GitHub PUT failed: ${putRes.status} — ${err}`);
    }

    console.log(`[save-history] ✓ ${entry.date} US=${entry.scoreUS} EU=${entry.scoreEU}`);
    return { statusCode: 200, headers, body: JSON.stringify({ ok: true, date: entry.date }) };

  } catch (err) {
    console.error('[save-history] Erreur:', err.message);
    return { statusCode: 500, headers, body: err.message };
  }
}
