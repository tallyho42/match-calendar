---
name: update
description: Pravidelná aktualizace rozpisu Matchday (index.html) - odstraní staré zápasy, ověří na webu změny termínů a časů zbývajících zápasů, zapíše je, ověří stránku a commitne + pushne. Spouští uživatel ručně přes /update.
disable-model-invocation: true
---

# /update - aktualizace rozpisu Matchday

Projekt: `/Users/premek/Code/Match Calendar` (statické `index.html`, GitHub Pages, remote `origin/main`).
Stránka sleduje FC Barcelonu, Real Madrid, Arsenal (+ záložka Národní). Časy jsou **pražské** (CET/CEST).
Uživatel vyvolání `/update` bere jako zadání celého postupu včetně **commitu a pushe na main** na konci.

## Postup

1. **Dnešek:** `date "+%Y-%m-%d %H:%M"`. Stránka skrývá zápasy starší než 10 dní, takže zápasy s datem před (dnes - 10 dní) se odstraňují.
2. **Co zbývá:** vypiš zbylé zápasy (`data-date`, `data-teams`, `data-when`, `data-comp-label`) a vyber ty, které je potřeba ověřit:
   - všechny s `čas TBA` v horizontu cca 3-4 týdnů (La Liga potvrzuje čas 15-20 dní předem, PL TV výběry po dávkách cca 6 týdnů předem),
   - všechny ostatní zápasy v nejbližších ~6 týdnech (mohly se přesunout o den, např. na sobotu/neděli/pondělí kvůli TV),
   - u záložky Národní: pokud je prázdná, nabídni doplnění nejbližšího reprezentačního okna (Liga národů ČR/Francie/Španělsko), ale nepřidávej bez pokynu.
3. **Ověření na webu** (WebSearch, případně WebFetch). Hledej zprávy typu "El X-Y se jugará el ... a las ..." (realmadrid.com, infobae, eldesmarque), "LaLiga horarios jornada N", "Premier League fixture amendments", arsenal.com novinky, UEFA seznam zápasů pro UCL (jen 3 zápasy v 18:45, ostatní 21:00).
   - **Převod času:** Španělsko, Francie, Itálie atd. = stejné jako Praha. **UK čas + 1 h = Praha** (celoročně, DST se mění ve stejný den).
   - `laliga.com/en-GB` ukazuje UTC (o 2 h méně než Praha v létě), nespoléhat na něj.
   - Shrnutí z WebSearch/WebFetch bývají nespolehlivá (špatná data, vymyšlené detaily). Každou změnu ověř **alespoň ve dvou nezávislých zdrojích**, preferuj oficiální oznámení klubu/ligy. Při rozporu nebo nejistotě zápas **neměň** (nech TBA) a uveď to v závěru.
   - Zapisuj jen změny, které opravdu platí; nic nehádej. Neudělané/nejisté body vypiš uživateli.
4. **Zápis:** vytvoř JSON a spusť skript (cesta relativně k projektu):
   ```bash
   python3 "/Users/premek/Code/Match Calendar/.claude/skills/update/update.py" /cesta/updates.json --dry-run   # nejdřív nanečisto
   python3 "/Users/premek/Code/Match Calendar/.claude/skills/update/update.py" /cesta/updates.json
   ```
   JSON (dočasný soubor patří do scratchpadu, ne do repa):
   ```json
   {"updates": [
     {"teams": "Arsenal – Brentford", "date": "2027-01-06", "new": "2027-01-05T20:30:00"},
     {"teams": "Real Madrid – Celta", "date": "2026-11-22", "tba": true}
   ]}
   ```
   `teams` = přesný text `data-teams` (s pomlčkou "–"), `date` = **aktuální** datum karty v souboru. Skript: smaže staré zápasy, přepíše `data-date`/`data-when`/`mc-day`/`mc-date`/`mc-time`, přeřadí karty do správných měsíčních sekcí a seřadí je, odstraní prázdné měsíce a nastaví razítko "Aktualizováno" (`#updatedPill`) na aktuální čas. Při neshodě `teams`/`date` skončí chybou.
   Nové zápasy (např. reprezentace) skript nepřidává: zkopíruj existující kartu (9 řádků `<article class="match-card ...">`), pro národní týmy `t-nat`, `data-team="nat"`, `data-competition="nations"`, klíče `CZE`/`FRA`/`SPA` (obrázky `img/cze.png`, `fra.png`, `spa.png`; `SPA`, ne `ESP`, to je Espanyol), sledovaná strana má `class="name tracked"`; poté znovu spusť skript s prázdným `updates` kvůli seřazení.
5. **Kontrola:**
   - počty `<article>`/`</article>`, `<section>`/`</section>`, `<div>`/`</div>` sedí,
   - karty jsou chronologicky, dny v týdnu sedí s datem (dělá skript),
   - stránka: otevři `index.html` v prohlížeči (`mcp__Claude_Browser__navigate` na `file://...`; relativní obrázky se tam nenačtou, to je normální, pro obrázky použij `preview_start` s dočasným `launch.json` na `python3 -m http.server`, po testu smaž) a přes `javascript_tool` ověř: počty karet pro Vše/Barça/Real/Arsenal/Národní, text banneru `#usText` ("Rozpis je aktuální" vs. "Doporučená aktualizace"), nejbližší zápas.
   - Zavři záložky prohlížeče, ukonči servery, nenechávej v repu dočasné soubory.
6. **Commit + push:** `git add index.html` (a jen nové soubory, které patří k změně), commit česky/anglicky stručně "co a proč" (styl předchozích commitů: např. "Prune past fixtures and refresh kickoff times and dates"), připoj trailer `Co-Authored-By` podle aktuálního system-reminderu, `git push origin main`.
7. **Závěr uživateli (stručně, česky):** hash commitu; co se odebralo; které termíny/časy se změnily; které zápasy zůstávají TBA nebo nejisté a proč; zda je záložka Národní prázdná; stav banneru.

## Pravidla stránky, na která pozor

- Banner "Doporučená aktualizace" se zobrazí, když je zápas do 14 dnů bez potvrzeného času (`čas TBA`). Cíl updatu je dostat banner na zelenou.
- Razítko "Aktualizováno" je statický text, skript ho přepisuje; při ruční úpravě bez skriptu ho přepiš ručně.
- Neodstraňuj záložky ani nepřidávej funkce; update se týká jen dat zápasů.
