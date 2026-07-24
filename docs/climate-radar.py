#!/usr/bin/env python3
"""
Climate Radar — vigilancia global de noticias climáticas en tiempo real.

Reúne noticias sobre clima / cambio climático de todo el mundo (cualquier idioma)
desde cinco fuentes, las deduplica, las puntúa (con LLM opcional) y te envía
los mejores resultados por Telegram.

Fuentes:
  1. GDELT DOC 2.0    -> prensa mundial, 65+ idiomas, traducida, cada 15 min (GRATIS, sin key)
  2. Google News RSS  -> consultas dirigidas por país/idioma (GRATIS, sin key)
  3. YouTube Data API -> vídeo (necesita YOUTUBE_API_KEY)
  4. Reddit           -> comunidades de clima, señal de viralidad (GRATIS, sin key)
  5. Bluesky          -> posts virales (GRATIS, API pública sin key)

Diseñado para correr en GitHub Actions cada 1-2 h. Degrada con elegancia:
si falta una clave, esa fuente/paso se omite y el resto sigue funcionando.

Variables de entorno (todas opcionales salvo que quieras esa función):
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID  -> envío de avisos (si faltan, imprime en log)
  ANTHROPIC_API_KEY                     -> scoring y titular ES con IA (si falta, scoring por keywords)
  YOUTUBE_API_KEY                       -> activa la fuente de vídeo
  RADAR_WINDOW_HOURS (def. 3)           -> ventana temporal de búsqueda
  RADAR_MAX_ALERTS   (def. 12)          -> nº máx. de noticias por ejecución
  RADAR_MIN_SCORE    (def. 6)           -> umbral de score (0-10) para avisar
"""

import os
import re
import json
import time
import html
import hashlib
import datetime as dt
from pathlib import Path
from urllib.parse import quote

import requests
import feedparser

# --------------------------------------------------------------------------- #
# CONFIGURACIÓN  (edita libremente)
# --------------------------------------------------------------------------- #

WINDOW_HOURS = int(os.getenv("RADAR_WINDOW_HOURS", "3"))
MAX_ALERTS   = int(os.getenv("RADAR_MAX_ALERTS", "12"))
MIN_SCORE    = float(os.getenv("RADAR_MIN_SCORE", "6"))

UA = "ClimateRadar/1.0 (+https://calentamientoglobal.es)"
STATE_FILE = Path(__file__).parent / "data" / "seen.json"
SEEN_CAP = 8000  # cuántos IDs recordamos para no repetir avisos

# GDELT: consultas por tema del Global Knowledge Graph + frases.
# theme:ENV_CLIMATECHANGE captura clima en todos los idiomas (traducido).
GDELT_QUERIES = [
    "theme:ENV_CLIMATECHANGE",
    'theme:ENV_CLIMATECHANGE (animal OR wildlife OR species OR whale OR bird OR coral)',
    '"climate change" (extinction OR migration OR heatwave OR wildfire OR flood OR drought)',
]

# Google News RSS: (consulta, hl=idioma, gl=país, ceid).
# Añade/quita países para orientar la cobertura donde te interese.
GNEWS_QUERIES = [
    ("cambio climático animales",          "es", "ES", "ES:es"),
    ("climate change wildlife",            "en", "US", "US:en"),
    ("climate change animals",             "en", "IN", "IN:en"),
    ("climate change extreme weather",     "en", "GB", "GB:en"),
    ("réchauffement climatique animaux",   "fr", "FR", "FR:fr"),
    ("Klimawandel Tiere",                  "de", "DE", "DE:de"),
    ("mudança climática animais",          "pt", "BR", "BR:pt-419"),
    ("cambiamento climatico animali",      "it", "IT", "IT:it"),
]

# Reddit: comunidades de clima/naturaleza (señal de viralidad vía top del día).
REDDIT_SUBS = "climate+climatechange+environment+collapse+nature+ClimateOffensive"

# Bluesky: búsquedas públicas.
BLUESKY_QUERIES = ["climate change", "climate crisis", "global warming", "cambio climático"]

# YouTube: consultas de vídeo (solo si hay YOUTUBE_API_KEY).
YOUTUBE_QUERIES = ["climate change", "cambio climático", "climate disaster wildlife"]

# Prefiltro de relevancia (multilingüe) usado como red de seguridad y para el
# scoring por keywords cuando no hay LLM.
CLIMATE_TERMS = [
    "climate", "clima", "climat", "klima", "climático", "climática", "climatico",
    "warming", "calentamiento", "réchauffement", "erwärmung", "aquecimento",
    "carbon", "co2", "emission", "emisión", "greenhouse", "invernadero",
    "heatwave", "ola de calor", "drought", "sequía", "wildfire", "incendio",
    "flood", "inundación", "glacier", "glaciar", "sea level", "nivel del mar",
    "extinction", "extinción", "biodiversity", "biodiversidad", "coral", "arrecife",
    "ipcc", "cop30", "cop31", "el niño", "la niña", "deforestation", "deforestación",
]


# --------------------------------------------------------------------------- #
# UTILIDADES
# --------------------------------------------------------------------------- #

def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def norm_title(t):
    t = (t or "").lower().strip()
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"[^a-z0-9áéíóúüñç ]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def item_id(it):
    """ID estable para dedup: título normalizado (fusiona la misma noticia entre medios)."""
    key = norm_title(it.get("title", "")) or it.get("url", "")
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def within_window(published_iso):
    if not published_iso:
        return True
    try:
        d = dt.datetime.fromisoformat(published_iso.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return (now_utc() - d) <= dt.timedelta(hours=WINDOW_HOURS + 1)
    except Exception:
        return True


def keyword_relevant(text):
    low = (text or "").lower()
    return any(term in low for term in CLIMATE_TERMS)


def load_seen():
    try:
        return set(json.loads(STATE_FILE.read_text()).get("ids", []))
    except Exception:
        return set()


def save_seen(seen):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    ids = list(seen)[-SEEN_CAP:]
    STATE_FILE.write_text(json.dumps({"ids": ids, "updated": now_utc().isoformat()}))


def get(url, **kw):
    kw.setdefault("timeout", 30)
    kw.setdefault("headers", {}).setdefault("User-Agent", UA)
    return requests.get(url, **kw)


# --------------------------------------------------------------------------- #
# FUENTES
# --------------------------------------------------------------------------- #

def fetch_gdelt():
    out = []
    for q in GDELT_QUERIES:
        try:
            url = (
                "https://api.gdeltproject.org/api/v2/doc/doc"
                f"?query={quote(q)}&mode=artlist&maxrecords=75"
                f"&timespan={WINDOW_HOURS}h&sort=datedesc&format=json"
            )
            r = get(url)
            if not r.text.strip().startswith("{"):
                continue
            for a in r.json().get("articles", []):
                sd = a.get("seendate", "")  # YYYYMMDDTHHMMSSZ
                iso = None
                if len(sd) >= 15:
                    iso = f"{sd[0:4]}-{sd[4:6]}-{sd[6:8]}T{sd[9:11]}:{sd[11:13]}:{sd[13:15]}Z"
                out.append({
                    "source": "gdelt",
                    "title": a.get("title", ""),
                    "url": a.get("url", ""),
                    "origin": a.get("domain", ""),
                    "lang": a.get("language", ""),
                    "country": a.get("sourcecountry", ""),
                    "published": iso,
                    "image": a.get("socialimage", ""),
                    "metric": 0,
                })
            time.sleep(1.5)  # cortesía con la API
        except Exception as e:
            print(f"[gdelt] error: {e}")
    return out


def fetch_google_news():
    out = []
    for q, hl, gl, ceid in GNEWS_QUERIES:
        try:
            url = f"https://news.google.com/rss/search?q={quote(q)}&hl={hl}&gl={gl}&ceid={ceid}"
            feed = feedparser.parse(url)
            for e in feed.entries[:20]:
                pub = None
                if getattr(e, "published_parsed", None):
                    pub = dt.datetime(*e.published_parsed[:6], tzinfo=dt.timezone.utc).isoformat()
                src = ""
                if getattr(e, "source", None):
                    src = getattr(e.source, "title", "")
                out.append({
                    "source": "googlenews",
                    "title": getattr(e, "title", ""),
                    "url": getattr(e, "link", ""),
                    "origin": src,
                    "lang": hl,
                    "country": gl,
                    "published": pub,
                    "image": "",
                    "metric": 0,
                })
        except Exception as e:
            print(f"[googlenews] error {q}: {e}")
    return [i for i in out if within_window(i["published"])]


def fetch_reddit():
    out = []
    try:
        url = f"https://www.reddit.com/r/{REDDIT_SUBS}/top.json?t=day&limit=60"
        r = get(url, headers={"User-Agent": UA})
        for c in r.json().get("data", {}).get("children", []):
            d = c.get("data", {})
            title = d.get("title", "")
            if not keyword_relevant(title):
                continue
            pub = dt.datetime.fromtimestamp(d.get("created_utc", 0), dt.timezone.utc).isoformat()
            out.append({
                "source": "reddit",
                "title": title,
                "url": d.get("url_overridden_by_dest") or ("https://reddit.com" + d.get("permalink", "")),
                "origin": "r/" + d.get("subreddit", ""),
                "lang": "en",
                "country": "",
                "published": pub,
                "image": "",
                "metric": int(d.get("ups", 0)),
            })
    except Exception as e:
        print(f"[reddit] error: {e}")
    return out


def fetch_bluesky():
    out = []
    for q in BLUESKY_QUERIES:
        try:
            url = ("https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts"
                   f"?q={quote(q)}&sort=latest&limit=25")
            r = get(url)
            for p in r.json().get("posts", []):
                rec = p.get("record", {})
                text = rec.get("text", "")
                if not keyword_relevant(text):
                    continue
                handle = p.get("author", {}).get("handle", "")
                rkey = p.get("uri", "").split("/")[-1]
                out.append({
                    "source": "bluesky",
                    "title": text[:180],
                    "url": f"https://bsky.app/profile/{handle}/post/{rkey}",
                    "origin": "@" + handle,
                    "lang": rec.get("langs", [""])[0] if rec.get("langs") else "",
                    "country": "",
                    "published": rec.get("createdAt"),
                    "image": "",
                    "metric": int(p.get("likeCount", 0)),
                })
        except Exception as e:
            print(f"[bluesky] error {q}: {e}")
    return [i for i in out if within_window(i["published"])]


def fetch_youtube():
    key = os.getenv("YOUTUBE_API_KEY")
    if not key:
        print("[youtube] sin YOUTUBE_API_KEY -> fuente omitida")
        return []
    out = []
    after = (now_utc() - dt.timedelta(hours=WINDOW_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for q in YOUTUBE_QUERIES:
        try:
            url = ("https://www.googleapis.com/youtube/v3/search"
                   f"?part=snippet&type=video&order=viewCount&maxResults=15"
                   f"&publishedAfter={after}&q={quote(q)}&key={key}")
            r = get(url)
            for it in r.json().get("items", []):
                sn = it.get("snippet", {})
                vid = it.get("id", {}).get("videoId")
                if not vid:
                    continue
                out.append({
                    "source": "youtube",
                    "title": sn.get("title", ""),
                    "url": f"https://www.youtube.com/watch?v={vid}",
                    "origin": sn.get("channelTitle", ""),
                    "lang": "",
                    "country": "",
                    "published": sn.get("publishedAt"),
                    "image": sn.get("thumbnails", {}).get("high", {}).get("url", ""),
                    "metric": 0,
                })
        except Exception as e:
            print(f"[youtube] error {q}: {e}")
    return out


# --------------------------------------------------------------------------- #
# DEDUP + SCORING
# --------------------------------------------------------------------------- #

def dedup(items, seen):
    fresh, batch_ids = [], set()
    for it in items:
        if not it.get("title") or not it.get("url"):
            continue
        iid = item_id(it)
        if iid in seen or iid in batch_ids:
            continue
        batch_ids.add(iid)
        it["id"] = iid
        fresh.append(it)
    return fresh


def score_with_llm(items):
    """Puntúa 0-10 y genera un titular en español. Devuelve None si no hay clave/error."""
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return None
    payload_items = [
        {"i": n, "title": it["title"], "source": it["source"],
         "lang": it["lang"], "country": it["country"]}
        for n, it in enumerate(items)
    ]
    prompt = (
        "Eres editor de un medio español de periodismo climático (calentamientoglobal.es). "
        "Puntúa cada noticia de 0 a 10 según: relevancia climática real, novedad y "
        "atractivo para una audiencia española interesada en clima, fauna y fenómenos extremos. "
        "Penaliza opinión genérica, promociones y ruido. Premia hechos concretos, sucesos, "
        "estudios y ángulos poco cubiertos (fauna, países lejanos, vídeos virales).\n"
        "Devuelve SOLO un array JSON: [{\"i\":int,\"score\":float,"
        "\"cat\":\"fauna|extremos|ciencia|energia|politica|virales|otros\","
        "\"es\":\"titular reescrito en español (max 90 car)\"}].\n\n"
        f"Noticias:\n{json.dumps(payload_items, ensure_ascii=False)}"
    )
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 2000,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=90,
        )
        txt = r.json()["content"][0]["text"]
        txt = txt[txt.find("["): txt.rfind("]") + 1]
        for row in json.loads(txt):
            i = row.get("i")
            if isinstance(i, int) and 0 <= i < len(items):
                items[i]["score"] = float(row.get("score", 0))
                items[i]["cat"] = row.get("cat", "otros")
                items[i]["es"] = row.get("es", items[i]["title"])
        return items
    except Exception as e:
        print(f"[llm] error: {e}")
        return None


def score_by_keywords(items):
    """Fallback sin LLM: score por densidad de términos climáticos + señal social."""
    for it in items:
        low = it["title"].lower()
        hits = sum(1 for t in CLIMATE_TERMS if t in low)
        # GDELT y Google News ya vienen de consultas climáticas -> base garantizada.
        floor = 6.0 if it["source"] in ("gdelt", "googlenews") else 4.0
        base = min(9.0, floor + hits * 1.2)
        if it["metric"] > 200:      # viralidad social
            base += 1.0
        if it["source"] in ("reddit", "bluesky", "youtube"):
            base += 0.3            # ligeramente pro-viral
        it["score"] = round(min(base, 10.0), 1)
        it["cat"] = "otros"
        it["es"] = it["title"]
    return items


# --------------------------------------------------------------------------- #
# ENTREGA (TELEGRAM)
# --------------------------------------------------------------------------- #

FLAG = {"IN": "🇮🇳", "US": "🇺🇸", "ES": "🇪🇸", "GB": "🇬🇧", "FR": "🇫🇷",
        "DE": "🇩🇪", "BR": "🇧🇷", "IT": "🇮🇹"}
ICON = {"gdelt": "📰", "googlenews": "🗞️", "reddit": "👽", "bluesky": "🦋", "youtube": "▶️"}


def format_digest(items):
    lines = [f"🌍 <b>Climate Radar</b> · {len(items)} noticias · {now_utc():%d %b %H:%M} UTC\n"]
    for it in items:
        title = html.escape(it.get("es") or it["title"])
        origin = html.escape(it.get("origin", ""))
        flag = FLAG.get(it.get("country", ""), "")
        cat = it.get("cat", "")
        cat_tag = f" · <i>{cat}</i>" if cat and cat != "otros" else ""
        metric = f" · 🔥{it['metric']}" if it.get("metric", 0) > 200 else ""
        lines.append(
            f"{ICON.get(it['source'],'•')} <b>{it['score']:.0f}</b>{cat_tag} {flag} "
            f"<a href=\"{html.escape(it['url'])}\">{title}</a>\n"
            f"    <i>{origin} · {it['source']}{metric}</i>"
        )
    return "\n".join(lines)


def send_telegram(text):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("[telegram] sin credenciales -> muestro el digest por consola:\n")
        print(text)
        return
    for chunk in [text[i:i + 3900] for i in range(0, len(text), 3900)]:
        try:
            requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat, "text": chunk, "parse_mode": "HTML",
                      "disable_web_page_preview": True},
                timeout=30,
            )
            time.sleep(0.5)
        except Exception as e:
            print(f"[telegram] error: {e}")


# --------------------------------------------------------------------------- #
# MAIN
# --------------------------------------------------------------------------- #

def main():
    seen = load_seen()
    print(f"Ventana: {WINDOW_HOURS}h · IDs recordados: {len(seen)}")

    raw = []
    for name, fn in [("GDELT", fetch_gdelt), ("Google News", fetch_google_news),
                     ("Reddit", fetch_reddit), ("Bluesky", fetch_bluesky),
                     ("YouTube", fetch_youtube)]:
        got = fn()
        print(f"  {name}: {len(got)} candidatos")
        raw += got

    fresh = dedup(raw, seen)
    print(f"Nuevos tras dedup: {len(fresh)}")
    if not fresh:
        print("Nada nuevo. Fin.")
        return

    # Limita el volumen enviado al LLM (coste): prioriza por señal social previa.
    fresh.sort(key=lambda x: x.get("metric", 0), reverse=True)
    candidates = fresh[:60]

    scored = score_with_llm(candidates)
    if scored is None:
        scored = score_by_keywords(candidates)
        print("Scoring: keywords (sin ANTHROPIC_API_KEY)")
    else:
        print("Scoring: LLM (Claude Haiku)")

    hits = [it for it in scored if it.get("score", 0) >= MIN_SCORE]
    hits.sort(key=lambda x: x.get("score", 0), reverse=True)
    hits = hits[:MAX_ALERTS]
    print(f"Superan umbral (>= {MIN_SCORE}): {len(hits)}")

    if hits:
        send_telegram(format_digest(hits))

    # Marca como vistos TODOS los nuevos (aunque no superen umbral) para no re-evaluarlos.
    for it in fresh:
        seen.add(it["id"])
    save_seen(seen)
    print("Estado guardado. Fin.")


if __name__ == "__main__":
    main()
