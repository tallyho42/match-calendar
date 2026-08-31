#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
download_logos.py  (v4)
=======================
Stahne loga fotbalovych klubu do ./img/ jako <zkratka>.png, presne jak je
ocekava fotbalovy-rozpis.html.  Vystup je VZDY validni PNG.

Co je nove proti v3 (a proc v3 padala):
  * v3 ukladala i JPEG/SVG pod priponou .png (resp. jako .svg) -> web ani
    test to neuznaly.  v4 vsechno prevede na skutecne PNG (Pillow, resp.
    serverovy rendering SVG na Wikimedii).
  * v3 mela jen jednu strategii (prop=pageimages na en.wiki).  U klubu s
    "non-free" logem, u presmerovanych clanku a u clanku bez infobox
    obrazku vratila prazdno.  v4 zkousi retezec:
       1) en.wiki  prop=pageimages  (davkove, 40 clanku na dotaz)
       2) en.wiki  prop=images      -> vybere nejlogovitejsi soubor
       3) lokalni jazykova mutace clanku (es/de/it/cs/pt/tr/nl/uk/ar/el/fr)
       4) Wikimedia Commons - fulltext hledani souboru
       5) placeholder (kruh v barve klubu + zkratka)
  * Slusne davkovani, prodleva mezi stazenimi a exponencialni backoff pri
    HTTP 429 s respektovanim hlavicky Retry-After.

Spusteni:
    python download_logos.py                # dostahne jen to, co chybi
    python download_logos.py --force        # prestahne vse
    python download_logos.py --only rso,val # jen vybrane zkratky
    python download_logos.py --no-placeholder
    python download_logos.py --report       # jen vypis tabulku a skonci

Pozn.: loga klubu jsou ochranne znamky; skript je pro osobni pouziti a bere
obrazky vyhradne z Wikipedie / Wikimedia Commons.
"""

import argparse
import io
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import unicodedata

IMG_DIR = "img"
MANIFEST = os.path.join(IMG_DIR, "_sources.json")
UA = "FootballScheduleLogoFetcher/4.0 (personal use)"
DEFAULT_WIDTH = 400
DEFAULT_DELAY = 0.4
MAX_RETRIES = 6
BATCH = 40
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

COMMONS_API = "https://commons.wikimedia.org/w/api.php"


def api(lang="en"):
    return "https://%s.wikipedia.org/w/api.php" % lang


# zkratka -> (nazev clanku na en.wikipedii, lokalni jazyk pro fallback)
ARTICLES = {
    "fcb": ("FC Barcelona", "es"),
    "rm":  ("Real Madrid CF", "es"),
    "ars": ("Arsenal F.C.", "en"),
    # La Liga
    "ath": ("Athletic Bilbao", "es"),
    "ray": ("Rayo Vallecano", "es"),
    "val": ("Valencia CF", "es"),
    "lev": ("Levante UD", "es"),
    "rac": ("Racing de Santander", "es"),
    "sev": ("Sevilla FC", "es"),
    "get": ("Getafe CF", "es"),
    "bet": ("Real Betis", "es"),
    "ala": ("Deportivo Alavés", "es"),
    "atm": ("Atlético Madrid", "es"),
    "vil": ("Villarreal CF", "es"),
    "dep": ("Deportivo de La Coruña", "es"),
    "cel": ("RC Celta de Vigo", "es"),
    "mal": ("Málaga CF", "es"),
    "rso": ("Real Sociedad", "es"),
    "esp": ("RCD Espanyol", "es"),
    "osa": ("CA Osasuna", "es"),
    "elc": ("Elche CF", "es"),
    # Premier League / EFL
    "cov": ("Coventry City F.C.", "en"),
    "avl": ("Aston Villa F.C.", "en"),
    "che": ("Chelsea F.C.", "en"),
    "sun": ("Sunderland A.F.C.", "en"),
    "bha": ("Brighton & Hove Albion F.C.", "en"),
    "lee": ("Leeds United F.C.", "en"),
    "nfo": ("Nottingham Forest F.C.", "en"),
    "eve": ("Everton F.C.", "en"),
    "liv": ("Liverpool F.C.", "en"),
    "hul": ("Hull City A.F.C.", "en"),
    "new": ("Newcastle United F.C.", "en"),
    "bre": ("Brentford F.C.", "en"),
    "tot": ("Tottenham Hotspur F.C.", "en"),
    "bou": ("AFC Bournemouth", "en"),
    "mun": ("Manchester United F.C.", "en"),
    "cry": ("Crystal Palace F.C.", "en"),
    "ful": ("Fulham F.C.", "en"),
    "ips": ("Ipswich Town F.C.", "en"),
    "mci": ("Manchester City F.C.", "en"),
    # Champions League / evropska scena
    "fey": ("Feyenoord", "nl"),
    "gal": ("Galatasaray S.K. (football)", "tr"),
    "psg": ("Paris Saint-Germain FC", "fr"),
    "sab": ("Sabah FK", "az"),
    "scp": ("Sporting CP", "pt"),
    "com": ("Como 1907", "it"),
    "int": ("Inter Milan", "it"),
    "rom": ("AS Roma", "it"),
    "rbl": ("RB Leipzig", "de"),
    "aek": ("AEK Athens F.C.", "el"),
    "psv": ("PSV Eindhoven", "nl"),
    "las": ("LASK", "de"),
    "shk": ("FC Shakhtar Donetsk", "uk"),
    "nap": ("SSC Napoli", "it"),
    "lil": ("Lille OSC", "fr"),
    "bay": ("FC Bayern Munich", "de"),
    "sla": ("SK Slavia Prague", "cs"),
    "bvb": ("Borussia Dortmund", "de"),
    "ahl": ("Al Ahly SC", "ar"),
}

# hledany vyraz na Commons, kdyz clanek zadne pouzitelne logo nenabidne
COMMONS_HINT = {
    "ath": "Athletic Club Bilbao logo",
    "rac": "Real Racing Club Santander logo",
    "dep": "Deportivo La Coruna logo",
    "sab": "Sabah FK logo",
    "ahl": "Al Ahly SC logo",
    "aek": "AEK Athens FC logo",
    "shk": "Shakhtar Donetsk logo",
    "cel": "RC Celta de Vigo logo",
    "mal": "Malaga CF logo",
}

# primarni klubova barva pro pripadny placeholder
COLORS = {
    "fcb": "#a50044", "rm": "#00529f", "ars": "#ef0107", "ath": "#ee2523",
    "ray": "#e53027", "val": "#f5820d", "lev": "#004fa3", "rac": "#009b3a",
    "sev": "#d81920", "get": "#005999", "bet": "#0bb363", "ala": "#0761af",
    "atm": "#cb3524", "vil": "#e2a400", "dep": "#00519e", "cel": "#8ac3ee",
    "mal": "#0e4c92", "rso": "#0067b1", "esp": "#0067b1", "osa": "#0a346f",
    "elc": "#0a5c36", "cov": "#5ab6e6", "avl": "#670e36", "che": "#034694",
    "sun": "#eb172b", "bha": "#0057b8", "lee": "#1d428a", "nfo": "#dd0000",
    "eve": "#003399", "liv": "#c8102e", "hul": "#f18a01", "new": "#241f20",
    "bre": "#e30613", "tot": "#132257", "bou": "#da291c", "mun": "#da291c",
    "cry": "#1b458f", "ful": "#000000", "ips": "#3a64a3", "mci": "#6cabdd",
    "fey": "#cc0000", "gal": "#a90432", "psg": "#004170", "sab": "#00843d",
    "scp": "#008057", "com": "#005baa", "int": "#0068a8", "rom": "#8e1f2f",
    "rbl": "#dd0741", "aek": "#f9d616", "psv": "#ed1c24", "las": "#000000",
    "shk": "#f47b20", "nap": "#12a0d7", "lil": "#e01e13", "bay": "#dc052d",
    "sla": "#d7141a", "bvb": "#fde100", "ahl": "#c8102e",
}

BAD_FILE_WORDS = (
    "commons-logo", "wikimedia", "wikidata", "wiki", "edit-", "oojs", "icon",
    "ambox", "question_book", "padlock", "symbol", "flag_of", "bandera_de",
    "map", "stadium", "estadio", "estado", "arena", "fairytale", "folder",
    "portal", "disambig", "red_link", "office-book", "people_icon", "search",
    "magnify", "star_full", "increase", "decrease", "soccerball", "pictogram",
    "location_map", "uefa", "fifa", "premier_league", "laliga", "serie_a",
    "bundesliga", "copa_del_rey", "kit_", "_kit", "shirt", "socks", "shorts",
    "stub", "sound", "speaker", "panoramio",
    # grafy/tabulky, ktere se tvari jako logo klubu:
    "performance", "league_perf", "chart", "graph", "attendance", "timeline",
    "statistics", "results_", "_results", "seasons", "history_of",
    # cizi loga vyskytujici se v clancich (sponzori, kampane):
    "united24", "adidas", "nike", "puma", "hummel", "kappa", "lotto_",
    "castore", "macron", "joma", "umbro", "new_balance", "estrella_galicia",
    "citroen", "emblem_of_the_united_nations",
)
GOOD_FILE_WORDS = ("logo", "crest", "badge", "escudo", "wappen", "stemma",
                   "emblem", "shield", "arms", "brasao")

_NORM_RE = re.compile(r"[^a-z0-9]+")


def _norm(s):
    """Male pismo, bez diakritiky, jen alfanumericke tokeny.

    Bez odstraneni diakritiky by se 'Malaga CF' neshodlo s 'Málaga CF.svg'
    a vyhral by mestsky znak 'Escudo de Málaga.svg'.
    """
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return _NORM_RE.sub(" ", s.lower()).strip()


# ---------------------------------------------------------------- HTTP vrstva
_last_call = [0.0]
MIN_GAP = 0.35   # minimalni odstup mezi jakymikoli dotazy (slusnost k API)


def _throttle():
    gap = time.time() - _last_call[0]
    if gap < MIN_GAP:
        time.sleep(MIN_GAP - gap)
    _last_call[0] = time.time()


def fetch(url, want="json", quiet=False):
    """Stahne URL s retry/backoff. want: 'json' | 'bytes'. Vraci (data, ctype)."""
    delay, last = 1.0, None
    for attempt in range(1, MAX_RETRIES + 1):
        _throttle()
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
                ctype = r.headers.get("Content-Type", "")
                if want == "json":
                    return json.loads(data.decode("utf-8")), ctype
                return data, ctype
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 502, 503, 504):
                ra = e.headers.get("Retry-After")
                wait = float(ra) if (ra and str(ra).isdigit()) else delay
                if not quiet:
                    print("        ... HTTP %d, cekam %.0fs (pokus %d/%d)"
                          % (e.code, wait, attempt, MAX_RETRIES))
                time.sleep(wait)
                delay = min(delay * 2, 60)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            if not quiet:
                print("        ... sit selhala (%s), cekam %.0fs (pokus %d/%d)"
                      % (e, delay, attempt, MAX_RETRIES))
            time.sleep(delay)
            delay = min(delay * 2, 60)
            continue
    raise last


def apiq(endpoint, **params):
    params.setdefault("format", "json")
    params.setdefault("formatversion", "2")
    data, _ = fetch(endpoint + "?" + urllib.parse.urlencode(params), want="json")
    return data


# ---------------------------------------------------------------- obrazky
def sniff(data):
    if data.startswith(PNG_MAGIC):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    head = data[:1024].lstrip()
    if head.startswith(b"<?xml") or head.startswith(b"<svg") or b"<svg" in data[:1024]:
        return "svg"
    return None


def to_png(data, kind, width):
    """Vrati PNG bajty, nebo None kdyz to nejde."""
    if kind == "png":
        return data
    if kind in ("jpg", "gif", "webp"):
        try:
            from PIL import Image
            im = Image.open(io.BytesIO(data)).convert("RGBA")
            if im.width > width:
                h = max(1, round(im.height * width / im.width))
                im = im.resize((width, h), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "PNG")
            return buf.getvalue()
        except Exception as e:
            print("        ! prevod %s->PNG selhal: %s" % (kind, e))
            return None
    if kind == "svg":
        return svg_to_png(data, width)
    return None


def svg_to_png(data, width):
    """SVG -> PNG: cairosvg, jinak rsvg-convert / Inkscape / ImageMagick."""
    try:
        import cairosvg
        return cairosvg.svg2png(bytestring=data, output_width=width)
    except Exception:
        pass
    import shutil
    import subprocess
    import tempfile
    tmpd = tempfile.mkdtemp()
    src = os.path.join(tmpd, "in.svg")
    dst = os.path.join(tmpd, "out.png")
    with open(src, "wb") as f:
        f.write(data)
    for cmd in (["rsvg-convert", "-w", str(width), "-o", dst, src],
                ["inkscape", src, "--export-type=png",
                 "--export-filename=" + dst, "--export-width=" + str(width)],
                ["magick", "-background", "none", "-density", "300", src,
                 "-resize", "%dx" % width, dst]):
        if not shutil.which(cmd[0]):
            continue
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=120)
            if os.path.exists(dst) and os.path.getsize(dst) > 0:
                with open(dst, "rb") as f:
                    out = f.read()
                if out.startswith(PNG_MAGIC):
                    return out
        except Exception:
            continue
    return None


def save_png(abbr, data, width):
    """Overi/prevede a ulozi img/<abbr>.png. Vrati velikost v bajtech nebo None."""
    kind = sniff(data)
    if kind is None:
        return None
    png = to_png(data, kind, width)
    if not png or not png.startswith(PNG_MAGIC):
        return None
    with open(os.path.join(IMG_DIR, abbr + ".png"), "wb") as f:
        f.write(png)
    return len(png)


# ---------------------------------------------------------------- strategie
def strat_pageimages_batch(items, width, lang="en", strict=True):
    """items = [(abbr, title)] -> {abbr: (url, filename)}. Davkove po BATCH.

    strict=True zahodi vysledky, jejichz nazev souboru nevypada na logo -
    pageimages u rady klubu vraci uvodni fotku (stadion), ne znak.
    """
    out = {}
    for i in range(0, len(items), BATCH):
        chunk = items[i:i + BATCH]
        try:
            d = apiq(api(lang), action="query",
                     titles="|".join(t for _, t in chunk),
                     prop="pageimages", piprop="thumbnail|original|name",
                     pithumbsize=str(width), pilimit="50", redirects="1")
        except Exception as e:
            print("    ! davkovy dotaz selhal: %s" % e)
            continue
        q = d.get("query", {})
        fwd = {}
        for n in q.get("normalized", []):
            fwd[n["from"]] = n["to"]
        for r in q.get("redirects", []):
            fwd[r["from"]] = r["to"]

        def final(t):
            seen = set()
            while t in fwd and t not in seen:
                seen.add(t)
                t = fwd[t]
            return t

        by_title = {final(t): a for a, t in chunk}
        titles = {a: t for a, t in chunk}
        for page in q.get("pages", []):
            abbr = by_title.get(page.get("title", ""))
            if not abbr:
                continue
            src = ((page.get("thumbnail") or {}).get("source")
                   or (page.get("original") or {}).get("source"))
            if not src:
                continue
            name = page.get("pageimage", "")
            if strict and name and score_file(name, titles[abbr]) <= 0:
                continue          # uvodni fotka clanku, ne logo
            out[abbr] = (src, name or "pageimage")
    return out


def score_file(name, article):
    """Jak moc soubor vypada jako klubove logo. <=0 znamena 'nepouzivat'.

    Klicove je, ze nazev souboru odpovida nazvu clanku ("Malaga CF.svg",
    "AFC Bournemouth (2013).svg") - prave tyhle soubory bez slova "logo"
    v nazvu drivejsi verze prehlizela a brala misto nich grafy sezon.
    """
    n = name.lower().replace(" ", "_")
    if not n.endswith((".svg", ".png", ".jpg", ".jpeg")):
        return -1
    if any(b in n for b in BAD_FILE_WORDS):
        return -1

    base = _norm(os.path.splitext(name)[0])
    art = _norm(article)
    art_toks = set(art.split())
    base_toks = base.split()

    s = 0
    if any(g in n for g in GOOD_FILE_WORDS):
        s += 10
    if base == art:
        s += 18                      # presna shoda s nazvem clanku
    elif base.startswith(art) or art.startswith(base):
        s += 12
    for tok in art_toks:
        if len(tok) >= 4 and tok in base_toks:
            s += 3
    # kazde slovo navic, ktere neni v nazvu clanku ani "logo/crest/...",
    # snizuje duveru (odfiltruje "League Performance", "Advertisement", ...)
    for tok in base_toks:
        if tok in art_toks or tok in GOOD_FILE_WORDS or tok.isdigit():
            continue
        s -= 2
    if n.endswith(".svg"):
        s += 4
    elif n.endswith(".png"):
        s += 3
    else:
        s += 1
    return s


def file_thumb_url(filetitle, width, endpoint):
    """File:X -> URL nahledu (SVG rendruje na PNG primo server Wikimedie)."""
    try:
        d = apiq(endpoint, action="query", titles=filetitle, prop="imageinfo",
                 iiprop="url|mime|size", iiurlwidth=str(width))
    except Exception:
        return None
    for page in d.get("query", {}).get("pages", []):
        for ii in page.get("imageinfo", []) or []:
            return ii.get("thumburl") or ii.get("url")
    return None


def local_title(title, lang):
    """Prelozi nazev en-clanku na nazev v jine jazykove mutaci pres langlinks.

    Bez tohohle by fallback poslal anglicky nazev na cizi wiki a dostal
    'missing' (napr. Shakhtar na uk.wikipedii).
    """
    if lang == "en":
        return title
    try:
        d = apiq(api("en"), action="query", titles=title, prop="langlinks",
                 lllang=lang, lllimit="1", redirects="1")
    except Exception:
        return None
    for page in d.get("query", {}).get("pages", []):
        for ll in page.get("langlinks", []) or []:
            return ll.get("title")
    return None


def strat_article_images(title, width, lang="en"):
    """prop=images na clanku -> nejlogovitejsi soubor -> URL nahledu."""
    t = local_title(title, lang)
    if not t:
        return None
    try:
        d = apiq(api(lang), action="query", titles=t, prop="images",
                 imlimit="300", redirects="1")
    except Exception:
        return None
    cands = []
    for page in d.get("query", {}).get("pages", []):
        if page.get("missing"):
            continue
        for im in page.get("images", []) or []:
            name = im["title"]
            sc = score_file(name.split(":", 1)[-1], t)
            if sc > 0:
                # pri shode skore vyhrava kratsi nazev (mene "pribalenych" slov)
                cands.append((sc, -len(name), name))
    if not cands:
        return None
    cands.sort(reverse=True)
    for _, _, name in cands[:3]:
        url = file_thumb_url(name, width, api(lang))
        if url:
            return url, name
    return None


def strat_commons_search(query, width):
    """Fulltext hledani souboru na Wikimedia Commons."""
    try:
        d = apiq(COMMONS_API, action="query", generator="search",
                 gsrsearch=query, gsrnamespace="6", gsrlimit="20",
                 prop="imageinfo", iiprop="url|mime", iiurlwidth=str(width))
    except Exception:
        return None
    cands = []
    for page in (d.get("query") or {}).get("pages", []) or []:
        name = page.get("title", "")
        sc = score_file(name.split(":", 1)[-1], query)
        if sc <= 0:
            continue
        for ii in page.get("imageinfo", []) or []:
            url = ii.get("thumburl") or ii.get("url")
            if url:
                cands.append((sc, name, url))
    if not cands:
        return None
    cands.sort(key=lambda c: c[0], reverse=True)
    return cands[0][2], cands[0][1]


# ---------------------------------------------------------------- placeholder
def make_placeholder(abbr, width):
    """Kruh v barve klubu se zkratkou -> PNG bajty."""
    from PIL import Image, ImageDraw, ImageFont
    S = width
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    hexc = COLORS.get(abbr, "#444444").lstrip("#")
    rgb = tuple(int(hexc[i:i + 2], 16) for i in (0, 2, 4))
    pad = int(S * 0.04)
    d.ellipse([pad, pad, S - pad, S - pad], fill=rgb + (255,),
              outline=(255, 255, 255, 255), width=max(2, S // 50))
    lum = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
    fg = (17, 17, 17, 255) if lum > 150 else (255, 255, 255, 255)
    txt = abbr.upper()
    size = int(S * 0.34)
    font = None
    for cand in ("arialbd.ttf", "seguisb.ttf", "DejaVuSans-Bold.ttf", "arial.ttf"):
        try:
            font = ImageFont.truetype(cand, size)
            break
        except Exception:
            continue
    if font is None:
        try:
            font = ImageFont.load_default(size=size)
        except Exception:
            font = ImageFont.load_default()
    bb = d.textbbox((0, 0), txt, font=font)
    d.text(((S - (bb[2] - bb[0])) / 2 - bb[0], (S - (bb[3] - bb[1])) / 2 - bb[1]),
           txt, font=font, fill=fg)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


# ---------------------------------------------------------------- manifest
def load_manifest():
    try:
        with open(MANIFEST, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_manifest(m):
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(m, f, ensure_ascii=False, indent=1, sort_keys=True)


def valid_png(abbr):
    p = os.path.join(IMG_DIR, abbr + ".png")
    if not os.path.exists(p) or os.path.getsize(p) == 0:
        return False
    with open(p, "rb") as f:
        return f.read(8) == PNG_MAGIC


# ---------------------------------------------------------------- hlavni beh
def expected_keys():
    """Autorita je HTML; fallback na ARTICLES, kdyby HTML nebylo po ruce."""
    try:
        h = open("fotbalovy-rozpis.html", encoding="utf-8").read()
    except OSError:
        return sorted(ARTICLES)
    keys = set(m.lower() for m in
               re.findall(r'data-(?:home|away)-key="([^"]+)"', h))
    keys |= {"fcb", "rm", "ars"}
    keys |= set(re.findall(r'src="img/([a-z0-9_-]+)\.png"', h))
    return sorted(keys)


def report(keys):
    man = load_manifest()
    print("\n%-6s %-12s %-48s %10s" % ("ZKR", "ZDROJ", "ODKUD", "VELIKOST"))
    print("-" * 80)
    real = ph = 0
    for k in keys:
        p = os.path.join(IMG_DIR, k + ".png")
        size = "%d kB" % (os.path.getsize(p) // 1024) if os.path.exists(p) else "-"
        info = man.get(k, {})
        kind = info.get("kind", "wiki?")
        where = info.get("source", "(stazeno drivejsim behem)")
        if len(where) > 48:
            where = where[:45] + "..."
        if kind == "placeholder":
            ph += 1
        elif os.path.exists(p):
            real += 1
        print("%-6s %-12s %-48s %10s" % (k, kind, where, size))
    print("-" * 80)
    print("Prava loga: %d   |   Placeholdery: %d   |   Celkem: %d"
          % (real, ph, len(keys)))
    return real, ph


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="prestahnout i existujici")
    ap.add_argument("--only", default="", help="carkou oddelene zkratky")
    ap.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    ap.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    ap.add_argument("--no-placeholder", action="store_true")
    ap.add_argument("--report", action="store_true", help="jen vypsat tabulku")
    args = ap.parse_args()

    os.makedirs(IMG_DIR, exist_ok=True)
    keys = expected_keys()
    man = load_manifest()

    if args.report:
        report(keys)
        return

    unknown = [k for k in keys if k not in ARTICLES]
    if unknown:
        print("! HTML chce zkratky, ktere nejsou v ARTICLES: %s" % unknown)

    if args.only:
        want = [k.strip().lower() for k in args.only.split(",") if k.strip()]
    else:
        want = keys

    todo = [k for k in want if args.force or not valid_png(k)]
    skipped = [k for k in want if k not in todo]
    if not todo:
        print("Vse uz je stazeno a validni. (--force pro prestazeni.)")
        report(keys)
        return

    print("Chybi/nevalidni: %d  (preskakuji %d hotovych)" % (len(todo), len(skipped)))

    # --- 1) davkove pageimages na en.wiki
    items = [(k, ARTICLES[k][0]) for k in todo if k in ARTICLES]
    print("\n[1] en.wikipedia prop=pageimages (davkove po %d)..." % BATCH)
    resolved = strat_pageimages_batch(items, args.width, "en")
    print("    nalezeno %d/%d" % (len(resolved), len(items)))

    ok, still = [], []
    for i, k in enumerate(sorted(todo), 1):
        hit = resolved.get(k)
        if not hit:
            still.append(k)
            continue
        src, name = hit
        try:
            data, _ = fetch(src, want="bytes")
        except Exception as e:
            print("  [%2d/%d] %-4s ! stazeni selhalo: %s" % (i, len(todo), k, e))
            still.append(k)
            continue
        n = save_png(k, data, args.width)
        if n:
            print("  [%2d/%d] %-4s OK  %s (%d kB)" % (i, len(todo), k, name, n // 1024))
            man[k] = {"kind": "wiki",
                      "source": "en pageimages / %s" % name, "url": src}
            ok.append(k)
        else:
            print("  [%2d/%d] %-4s ! odpoved neni pouzitelny obrazek" % (i, len(todo), k))
            still.append(k)
        time.sleep(args.delay)

    # --- 2..4) per-klub retezec fallbacku
    if still:
        print("\n[2-4] Fallbacky pro %d klubu: %s" % (len(still), still))
    for k in list(still):
        title, lang = ARTICLES.get(k, (k, "en"))
        attempts = [("en clanek prop=images",
                     lambda t=title: strat_article_images(t, args.width, "en"))]
        if lang != "en":
            attempts.append(("%s clanek prop=images" % lang,
                             lambda t=title, l=lang: strat_article_images(t, args.width, l)))
            attempts.append(("%s pageimages" % lang,
                             lambda t=title, l=lang, kk=k:
                             strat_pageimages_batch(
                                 [(kk, local_title(t, l) or t)], args.width, l).get(kk)))
        q = COMMONS_HINT.get(k, title + " logo")
        attempts.append(("commons hledani",
                         lambda qq=q: strat_commons_search(qq, args.width)))
        attempts.append(("commons intitle",
                         lambda t=title: strat_commons_search(
                             " ".join("intitle:" + w for w in _norm(t).split()
                                      if len(w) > 2) + " logo", args.width)))
        # uplne nakonec: uvodni obrazek clanku bez kontroly nazvu souboru
        attempts.append(("en pageimages (volne)",
                         lambda t=title, kk=k: strat_pageimages_batch(
                             [(kk, t)], args.width, "en", strict=False).get(kk)))
        got = False
        for label, fn in attempts:
            try:
                res = fn()
            except Exception as e:
                print("  %-4s %-26s ! %s" % (k, label, e))
                continue
            if not res:
                print("  %-4s %-26s - nic" % (k, label))
                continue
            url, name = res if isinstance(res, tuple) else (res, "?")
            if not url:
                print("  %-4s %-26s - nic" % (k, label))
                continue
            try:
                data, _ = fetch(url, want="bytes")
            except Exception as e:
                print("  %-4s %-26s ! stazeni: %s" % (k, label, e))
                continue
            n = save_png(k, data, args.width)
            if n:
                print("  %-4s %-26s OK %s (%d kB)" % (k, label, name, n // 1024))
                man[k] = {"kind": "commons" if "commons" in label else "wiki",
                          "source": "%s / %s" % (label, name), "url": url}
                ok.append(k)
                still.remove(k)
                got = True
                break
            print("  %-4s %-26s ! neni pouzitelny obrazek" % (k, label))
            time.sleep(args.delay)
        if not got:
            print("  %-4s VSECHNY STRATEGIE SELHALY" % k)
        time.sleep(args.delay)

    # --- 5) placeholder
    if still and not args.no_placeholder:
        print("\n[5] Placeholdery pro: %s" % still)
        for k in list(still):
            try:
                data = make_placeholder(k, args.width)
            except Exception as e:
                print("  %-4s ! placeholder selhal: %s" % (k, e))
                continue
            with open(os.path.join(IMG_DIR, k + ".png"), "wb") as f:
                f.write(data)
            man[k] = {"kind": "placeholder", "source": "vygenerovano lokalne", "url": ""}
            print("  %-4s placeholder OK (%d kB)" % (k, len(data) // 1024))
            still.remove(k)

    save_manifest(man)

    print("\n=========== SHRNUTI BEHU ===========")
    print("Ziskano ted: %d" % len(ok))
    print("Preskoceno:  %d" % len(skipped))
    print("Nevyreseno:  %d %s" % (len(still), still if still else ""))
    report(keys)


if __name__ == "__main__":
    main()
