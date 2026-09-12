# RateScout FR — ratescout.info.gf

Version française (FR-only) de RateScout : répertoire des taux de change
crypto et monnaies d'après le monitoring des changeurs BestChange.

- **Prod :** https://ratescout.info.gf
- **Générateur :** `python3 build.py` → `dist/` (GitHub Pages)
- **Langue unique :** `langs: ["fr"]` dans `data.json`
- **Pas de marquage ERID / pas d'ORD** (uniquement divulgation d'affiliation,
  voir `/raskrytie/`)
- **Analytics :** Google (gtag/GTM) uniquement, pas de Yandex.Metrica

## Workflows

| Fichier | Rôle |
|---|---|
| `deploy.yml` | fetch (rates/market/trending/OFAC/F&G) + build + verify + Pages, chaque heure |
| `keepalive.yml` | heartbeat hebdo (anti-veille des crons) |
| `watchdog.yml` | fraîcheur de `history.json` toutes les 2 h |
| `history-squash.yml` | squash manuel de l'historique git |
| `repo-size-guard.yml` | alerte taille du repo |

## Secrets requis

`BESTCHANGE_API_KEY`, `BESTCHANGE_RATES_URL`, `GH_PAT`
(optionnels : `COINGECKO_KEY`, `TELEGRAM_TOKEN`/`ALERT_CHAT_ID` pour les alertes,
`GSC_SA_JSON`/`GSC_SITE` pour Search Console).

## Vérification locale

```bash
pip install markdown Pillow
python3 build.py
python3 verify_build.py
```

Dépôt source RU/EN : `sementsul/ratescout`.
