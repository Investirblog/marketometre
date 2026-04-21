# MarketOmètre

Indice de sentiment pour les marchés financiers américains et européens.  
Score composite 0–100 agrégeant volatilité, sentiment, breadth et stress de crédit.

## Structure

```
/index.html               → page principale
/widget.html              → widget compact pour embed Substack
/netlify/functions/
  telegram-alert.js       → alerte Telegram quotidienne (cron 8h UTC lun-ven)
/netlify.toml             → config Netlify (functions + cron)
```

## Sources de données

| Indicateur | Source | Fréquence |
|---|---|---|
| VIX | FRED (VIXCLS) | Quotidienne |
| HY Spread | FRED (BAMLH0A0HYM2) | Quotidienne |
| ZEW Sentiment | FRED (ZEWSELMU) | Mensuelle |
| S&P 500, Eurostoxx 50, VSTOXX | Yahoo Finance | Temps réel |
| Put/Call ratio | CBOE CSV public | Quotidienne |

## Déploiement

1. Connecter ce repo à Netlify via "Import from GitHub"
2. Publish directory : `.`  
3. Functions directory : `netlify/functions`
4. La fonction cron `telegram-alert` s'exécute automatiquement chaque jour de semaine à 8h UTC

## Embed Substack

```html
<iframe src="https://TON-SITE.netlify.app/widget" 
        width="100%" height="420" 
        frameborder="0" scrolling="no"
        style="border-radius:16px;max-width:560px">
</iframe>
```
