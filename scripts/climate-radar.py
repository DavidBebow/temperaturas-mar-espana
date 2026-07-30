#!/usr/bin/env python3
"""
Climate Radar v2 — cazador de EXCLUSIVAS climáticas.

Objetivo (cambia respecto a v1): no resumir el ciclo de noticias que ya cubre
Carbon Brief y las grandes cabeceras, sino detectar la noticia IMPACTANTE, RECIENTE
y todavía NO cubierta en español, para que David la publique el primero.

Palancas nuevas:
  · Fuentes orientadas al long-tail: GDELT filtrado por idiomas NO inglés/español
    (hindi, portugués, indonesio, árabe...) + consultas de sucesos dramáticos.
  · Scoring con IA reescrito para premiar impacto + primicia + origen extranjero + viral.
  · Filtro "¿ya está en español?": descarta lo que la prensa ES ya publicó.
  · Vídeo (YouTube) y viralidad (Bluesky/Reddit) arreglados.
  · Sin subcarpetas de estado (arreglado el crash de v1).

Variables de entorno:
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   -> avisos (si faltan, imprime en log)
  ANTHROPIC_API_KEY  -> scoring inteligente (MUY recomendado: es lo que da las exclusivas)
  YOUTUBE_API_KEY    -> activa la fuente de vídeo
  RADAR_WINDOW_HOURS (def. 3)  ·  RADAR_MAX_ALERTS (def. 12)  ·  RADAR_MIN_SCORE (def. 7)
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
# CONFIGURACIÓN
# --------------------------------------------------------------------------- #

WINDOW_HOURS = int(os.getenv("RADAR_WINDOW_HOURS", "9"))
MAX_ALERTS   = int(os.getenv("RADAR_MAX_ALERTS", "12"))
MIN_SCORE    = float(os.getenv("RADAR_MIN_SCORE", "6"))
VIDEO_LOOKBACK_HOURS = int(os.getenv("RADAR_VIDEO_LOOKBACK", "72"))  # vídeos: mira 3 días atrás y ordena por velocidad
VIRAL_VPH = int(os.getenv("RADAR_VIRAL_VPH", "3000"))  # visitas/hora para considerar un vídeo "viral"
CHECK_SPANISH_NOVELTY = True   # descarta lo ya cubierto por prensa española
HEARTBEAT    = True            # avisa aunque no haya primicias (para saber que corrió)

UA = "Mozilla/5.0 (ClimateRadar/2.0; +https://calentamientoglobal.es)"
STATE_FILE = Path(__file__).parent / "radar_seen.json"   # fichero plano, sin subcarpeta
SEEN_CAP = 8000

# GDELT global — red AMPLIA en la ingesta; el impacto lo filtra la IA en el scoring.
GDELT_QUERIES = [
    'theme:ENV_CLIMATECHANGE',   # firehose amplio (mucho volumen; la IA elige)
    'theme:ENV_CLIMATECHANGE (animal OR wildlife OR species OR whale OR dolphin OR coral OR elephant OR penguin OR bird OR fish)',
    '("climate change" OR "global warming") ("mass mortality" OR die-off OR "washed ashore" OR stranded OR "found dead" OR extinction OR viral)',
]
# GDELT por idioma — el long-tail donde puedes llegar PRIMERO en español.
GDELT_LANGS = ["hindi", "portuguese", "indonesian", "arabic", "thai"]

# Google News RSS: dirigido a países no hispanohablantes (evita duplicar prensa ES).
GNEWS_QUERIES = [
    ("climate change animals",           "en", "IN", "IN:en"),   # India
    ("climate wildlife disaster",        "en", "PH", "PH:en"),   # Filipinas
    ("climate change animals viral",     "en", "US", "US:en"),
    ("mudança climática animais",        "pt", "BR", "BR:pt-419"),
]

# Reddit: subs de VÍDEO/imagen virales + clima. Se filtra por keyword para no salirse del nicho.
REDDIT_SUBS = ("climate+climatechange+environment+collapse+nature+NatureIsFuckingLit"
               "+Damnthatsinteresting+interestingasfuck+NatureIsMetal+weather")
BLUESKY_QUERIES = ["climate animals", "wildlife climate", "climate disaster video", "heatwave record"]
# YouTube: consultas orientadas a CLIP viral (animales, desastres, fenómenos), EN + ES.
YOUTUBE_QUERIES = [
    "climate change animals", "wildlife rescue flood", "extreme weather caught on camera",
    "animals heatwave", "wildfire footage", "storm flood viral", "cambio climático animales",
]

# Prensa española: si la noticia ya está aquí, NO eres el primero -> se descarta.
SPANISH_MAINSTREAM = {
    "elpais.com", "elmundo.es", "lavanguardia.com", "abc.es", "20minutos.es",
    "eldiario.es", "larazon.es", "elconfidencial.com", "rtve.es", "efeverde.com",
    "agenciasinc.es", "publico.es", "elperiodico.com", "lavozdegalicia.es",
    "nationalgeographic.com.es", "xataka.com", "3djuegos.com",
}
# Agregadores/cabeceras globales que "ya lee todo el mundo" -> baja novedad.
LOW_NOVELTY = {"carbonbrief.org", "theguardian.com", "reuters.com", "apnews.com",
               "bbc.com", "bbc.co.uk", "nytimes.com", "washingtonpost.com"}

# Idiomas con potencial de primicia (no inglés/español) -> bonus.
PRIORITY_LANGS = {"hin", "por", "ind", "ara", "tha", "vie", "tur", "ben", "urd",
                  "swa", "tgl", "msa", "fas", "rus", "zho", "jpn", "kor"}

CLIMATE_TERMS = [
    "climate", "clima", "climat", "klima", "warming", "calentamiento", "carbon",
    "co2", "heatwave", "ola de calor", "drought", "sequía", "wildfire", "incendio",
    "flood", "inundación", "glacier", "glaciar", "extinction", "extinción",
    "biodiversity", "coral", "whale", "ballena", "wildlife", "fauna", "species",
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
    return re.sub(r"\s+", " ", t).strip()

def item_id(it):
    key = norm_title(it.get("title", "")) or it.get("url", "")
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]

def domain_of(url):
    m = re.search(r"https?://([^/]+)", url or "")
    d = (m.group(1) if m else "").lower().replace("www.", "")
    return d

def within_window(published_iso, slack=1):
    if not published_iso:
        return True
    try:
        d = dt.datetime.fromisoformat(published_iso.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=dt.timezone.utc)
        return (now_utc() - d) <= dt.timedelta(hours=WINDOW_HOURS + slack)
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
    ids = list(seen)[-SEEN_CAP:]
    STATE_FILE.write_text(json.dumps({"ids": ids, "updated": now_utc().isoformat()}))

def get(url, **kw):
    kw.setdefault("timeout", 30)
    h = kw.setdefault("headers", {})
    h.setdefault("User-Agent", UA)
    h.setdefault("Accept", "application/json, text/plain, */*")
    return requests.get(url, **kw)


# --------------------------------------------------------------------------- #
# FUENTES
# --------------------------------------------------------------------------- #

def _gdelt_query(q):
    out = []
    try:
        url = ("https://api.gdeltproject.org/api/v2/doc/doc"
               f"?query={quote(q)}&mode=artlist&maxrecords=60"
               f"&timespan={WINDOW_HOURS}h&sort=datedesc&format=json")
        r = get(url)
        if not r.text.strip().startswith("{"):
            return out
        for a in r.json().get("articles", []):
            sd = a.get("seendate", "")
            iso = f"{sd[0:4]}-{sd[4:6]}-{sd[6:8]}T{sd[9:11]}:{sd[11:13]}:{sd[13:15]}Z" if len(sd) >= 15 else None
            out.append({
                "source": "gdelt", "title": a.get("title", ""), "url": a.get("url", ""),
                "origin": a.get("domain", ""), "lang": a.get("language", ""),
                "country": a.get("sourcecountry", ""), "published": iso,
                "image": a.get("socialimage", ""), "metric": 0,
            })
    except Exception as e:
        print(f"[gdelt] error: {e}")
    return out

def fetch_gdelt():
    out = []
    for q in GDELT_QUERIES:
        out += _gdelt_query(q)
        time.sleep(1.4)
    for lang in GDELT_LANGS:                       # long-tail por idioma
        out += _gdelt_query(f"theme:ENV_CLIMATECHANGE sourcelang:{lang}")
        time.sleep(1.4)
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
                src = getattr(getattr(e, "source", None), "title", "") if getattr(e, "source", None) else ""
                out.append({
                    "source": "googlenews", "title": getattr(e, "title", ""),
                    "url": getattr(e, "link", ""), "origin": src, "lang": hl,
                    "country": gl, "published": pub, "image": "", "metric": 0,
                })
        except Exception as e:
            print(f"[googlenews] error {q}: {e}")
    return [i for i in out if within_window(i["published"])]

def fetch_reddit():
    """Best-effort: los runners de GitHub a veces los bloquea Reddit. Vía RSS."""
    out = []
    try:
        url = f"https://www.reddit.com/r/{REDDIT_SUBS}/rising/.rss?limit=60"   # rising = lo que sube rápido
        feed = feedparser.parse(url, request_headers={"User-Agent": UA})
        for e in feed.entries[:50]:
            title = getattr(e, "title", "")
            if not keyword_relevant(title):
                continue
            pub = None
            if getattr(e, "updated_parsed", None):
                pub = dt.datetime(*e.updated_parsed[:6], tzinfo=dt.timezone.utc).isoformat()
            out.append({
                "source": "reddit", "title": title, "url": getattr(e, "link", ""),
                "origin": "reddit", "lang": "en", "country": "", "published": pub,
                "image": "", "metric": 0,
            })
        if not out:
            print("[reddit] 0 (posible bloqueo de IP de GitHub Actions; no crítico)")
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
            if r.status_code != 200 or not r.text.strip().startswith("{"):
                print(f"[bluesky] '{q}' HTTP {r.status_code}")
                continue
            for p in r.json().get("posts", []):
                rec = p.get("record", {})
                text = rec.get("text", "")
                if not keyword_relevant(text):
                    continue
                handle = p.get("author", {}).get("handle", "")
                rkey = p.get("uri", "").split("/")[-1]
                langs = rec.get("langs") or [""]
                out.append({
                    "source": "bluesky", "title": text[:180],
                    "url": f"https://bsky.app/profile/{handle}/post/{rkey}",
                    "origin": "@" + handle, "lang": langs[0][:3],
                    "country": "", "published": rec.get("createdAt"),
                    "image": "", "metric": int(p.get("likeCount", 0)),
                })
        except Exception as e:
            print(f"[bluesky] error {q}: {e}")
    return [i for i in out if within_window(i["published"])]

def fetch_youtube():
    """Caza vídeo VIRAL: mira los últimos días y ordena por VELOCIDAD (visitas/hora),
    no por visitas totales. Así detecta lo que está explotando ahora, no lo ya popular."""
    key = os.getenv("YOUTUBE_API_KEY")
    if not key:
        print("[youtube] sin YOUTUBE_API_KEY -> SIN VÍDEO. Es la fuente clave para lo viral: añádela.")
        return []
    out, ids = [], []
    after = (now_utc() - dt.timedelta(hours=VIDEO_LOOKBACK_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for q in YOUTUBE_QUERIES:
        try:
            url = ("https://www.googleapis.com/youtube/v3/search"
                   f"?part=snippet&type=video&order=viewCount&maxResults=15"
                   f"&publishedAfter={after}&q={quote(q)}&key={key}")
            for it in get(url).json().get("items", []):
                vid = it.get("id", {}).get("videoId")
                sn = it.get("snippet", {})
                if not vid:
                    continue
                ids.append(vid)
                out.append({
                    "source": "youtube", "title": sn.get("title", ""),
                    "url": f"https://www.youtube.com/watch?v={vid}",
                    "origin": sn.get("channelTitle", ""), "lang": "",
                    "country": "", "published": sn.get("publishedAt"),
                    "image": sn.get("thumbnails", {}).get("high", {}).get("url", ""),
                    "metric": 0, "velocity": 0,
                })
        except Exception as e:
            print(f"[youtube] error {q}: {e}")
    # 2ª llamada: estadísticas -> velocidad = visitas / horas desde publicación
    try:
        uniq = list(dict.fromkeys(ids))
        for chunk in [uniq[i:i + 50] for i in range(0, len(uniq), 50)]:
            vurl = ("https://www.googleapis.com/youtube/v3/videos"
                    f"?part=statistics,snippet&id={','.join(chunk)}&key={key}")
            for v in get(vurl).json().get("items", []):
                views = int(v.get("statistics", {}).get("viewCount", 0))
                pub = v.get("snippet", {}).get("publishedAt", "")
                hours = 1.0
                try:
                    d = dt.datetime.fromisoformat(pub.replace("Z", "+00:00"))
                    hours = max((now_utc() - d).total_seconds() / 3600.0, 1.0)
                except Exception:
                    pass
                for it in out:
                    if it["url"].endswith(v["id"]):
                        it["metric"] = views
                        it["velocity"] = int(views / hours)   # visitas por hora
    except Exception as e:
        print(f"[youtube] stats error: {e}")
    # nos quedamos con los que realmente están corriendo
    viral = [it for it in out if it.get("velocity", 0) >= VIRAL_VPH * 0.4]
    viral.sort(key=lambda x: x.get("velocity", 0), reverse=True)
    print(f"[youtube] {len(out)} vídeos, {len(viral)} con tracción (>= {int(VIRAL_VPH*0.4)} vis/h)")
    return viral[:25]


# --------------------------------------------------------------------------- #
# FILTRADO
# --------------------------------------------------------------------------- #

def prefilter(items):
    """Quita lo que ya está en prensa española (no serías el primero)."""
    kept = []
    for it in items:
        if domain_of(it["url"]) in SPANISH_MAINSTREAM:
            continue
        kept.append(it)
    return kept

def dedup(items, seen):
    fresh, batch = [], set()
    for it in items:
        if not it.get("title") or not it.get("url"):
            continue
        iid = item_id(it)
        if iid in seen or iid in batch:
            continue
        batch.add(iid)
        it["id"] = iid
        fresh.append(it)
    return fresh

def already_in_spanish(spanish_title):
    """True si Google News en español YA tiene la noticia (=> no es primicia)."""
    q = " ".join(re.findall(r"[A-Za-zÁÉÍÓÚÑáéíóúñ]{4,}", spanish_title or ""))[:120]
    if len(q) < 8:
        return False
    try:
        url = f"https://news.google.com/rss/search?q={quote(q)}&hl=es&gl=ES&ceid=ES:es"
        feed = feedparser.parse(url)
        recent = 0
        for e in feed.entries[:10]:
            if getattr(e, "published_parsed", None):
                d = dt.datetime(*e.published_parsed[:6], tzinfo=dt.timezone.utc)
                if (now_utc() - d) <= dt.timedelta(days=3):
                    recent += 1
        return recent >= 2   # ya cubierto por >=2 medios ES en 72h
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# SCORING
# --------------------------------------------------------------------------- #

def score_with_llm(items):
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return None
    payload = [{"i": n, "title": it["title"], "source": it["source"],
                "lang": it["lang"], "country": it["country"],
                "domain": domain_of(it["url"]), "views": it.get("metric", 0),
                "vel_vph": it.get("velocity", 0)}
               for n, it in enumerate(items)]
    prompt = (
        "Eres el editor de un medio español de clima (calentamientoglobal.es). Tu MÁXIMA prioridad "
        "son los VÍDEOS VIRALES y clips impactantes de clima/fauna/desastres que se estén "
        "compartiendo mucho AHORA, para publicarlos el PRIMERO en español. Puntúa 0-10 (10 = "
        "'clip viral que publico YA').\n\n"
        "PREMIA al máximo: vídeos con alta velocidad de visualizaciones (campo 'vel_vph' = visitas/hora; "
        ">3000 es fuerte, >10000 es un bombazo) y posts que suben rápido en Reddit; imágenes/vídeos "
        "de animales, rescates, fenómenos extremos, algo espectacular grabado en cámara. "
        "PREMIA también sucesos dramáticos de prensa NO inglesa/española (India, sudeste asiático, "
        "Latinoamérica, África) que casi seguro la prensa española AÚN no tiene.\n"
        "PENALIZA fuerte (score <=3): opinión, análisis, 'explainers', divulgación, política/cumbres, "
        "y cabeceras que ya lee todo el mundo (Carbon Brief, Guardian, Reuters, BBC).\n\n"
        "Devuelve SOLO un array JSON: [{\"i\":int,\"score\":float,"
        "\"cat\":\"video|fauna|desastre|record|viral|ciencia|otros\","
        "\"primicia\":true|false,\"es\":\"titular en español, gancho, max 90 car\"}].\n\n"
        f"Elementos:\n{json.dumps(payload, ensure_ascii=False)}"
    )
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-haiku-4-5-20251001", "max_tokens": 2500,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=90)
        txt = r.json()["content"][0]["text"]
        txt = txt[txt.find("["): txt.rfind("]") + 1]
        for row in json.loads(txt):
            i = row.get("i")
            if isinstance(i, int) and 0 <= i < len(items):
                items[i]["score"] = float(row.get("score", 0))
                items[i]["cat"] = row.get("cat", "otros")
                items[i]["es"] = row.get("es", items[i]["title"])
                items[i]["primicia"] = bool(row.get("primicia", False))
        return items
    except Exception as e:
        print(f"[llm] error: {e}")
        return None

def score_by_keywords(items):
    """Fallback SIN IA. Aviso: no distingue 'impactante', solo aproxima. Añade la IA."""
    for it in items:
        low = it["title"].lower()
        hits = sum(1 for t in CLIMATE_TERMS if t in low)
        base = 5.0 + hits * 0.8
        if it.get("lang", "")[:3] in PRIORITY_LANGS:      # origen extranjero -> primicia
            base += 1.5
        if domain_of(it["url"]) in LOW_NOVELTY:           # todo el mundo lo lee
            base -= 3.0
        vel = it.get("velocity", 0)                       # vídeo viral: visitas/hora
        if vel >= VIRAL_VPH * 3:
            base += 4.0
        elif vel >= VIRAL_VPH:
            base += 2.5
        elif vel >= VIRAL_VPH * 0.4:
            base += 1.2
        if it["source"] == "reddit":                      # rising = subiendo rápido
            base += 1.0
        if it["source"] in ("youtube", "bluesky"):
            base += 0.5
        it["score"] = round(max(0.0, min(base, 10.0)), 1)
        it["cat"] = "otros"
        it["es"] = it["title"]
        it["primicia"] = it.get("lang", "")[:3] in PRIORITY_LANGS
    return items


# --------------------------------------------------------------------------- #
# ENTREGA
# --------------------------------------------------------------------------- #

ICON = {"gdelt": "📰", "googlenews": "🗞️", "reddit": "👽", "bluesky": "🦋", "youtube": "▶️"}

def format_digest(items):
    lines = [f"🌍 <b>Climate Radar</b> · {len(items)} posibles exclusivas · {now_utc():%d %b %H:%M} UTC\n"]
    for it in items:
        title = html.escape(it.get("es") or it["title"])
        origin = html.escape(it.get("origin", ""))
        cat = it.get("cat", "")
        tag = f" · <i>{cat}</i>" if cat and cat != "otros" else ""
        star = "🔥PRIMICIA " if it.get("primicia") else ""
        if it.get("velocity", 0) >= VIRAL_VPH * 0.4:      # vídeo con tracción
            metric = f" · 🚀{it['velocity']:,}/h ({it.get('metric',0):,} vis)"
        elif it.get("metric", 0) > 500:
            metric = f" · 👁{it['metric']:,}"
        else:
            metric = ""
        lang = f" [{it['lang']}]" if it.get("lang") else ""
        lines.append(
            f"{ICON.get(it['source'],'•')} <b>{it['score']:.0f}</b>{tag} {star}"
            f"<a href=\"{html.escape(it['url'])}\">{title}</a>\n"
            f"    <i>{origin}{lang} · {it['source']}{metric}</i>"
        )
    return "\n".join(lines)

def send_telegram(text):
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("[telegram] sin credenciales -> digest por consola:\n\n" + text)
        return
    for chunk in [text[i:i + 3900] for i in range(0, len(text), 3900)]:
        try:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": chunk, "parse_mode": "HTML",
                                "disable_web_page_preview": True}, timeout=30)
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

    total = len(raw)
    raw = prefilter(raw)                     # fuera lo que ya está en prensa ES
    fresh = dedup(raw, seen)
    print(f"Nuevos tras dedup+prefiltro: {len(fresh)}")
    if not fresh:
        if HEARTBEAT:
            send_telegram(f"🌍 <b>Climate Radar</b> · ejecutado, sin novedades "
                          f"(candidatos: {total}, nada nuevo) · {now_utc():%d %b %H:%M} UTC")
        save_seen(seen)
        print("Nada nuevo. Fin.")
        return

    # prioriza vídeo viral (velocidad) al elegir qué manda a la IA
    fresh.sort(key=lambda x: (x.get("velocity", 0), x.get("metric", 0)), reverse=True)
    candidates = fresh[:70]

    scored = score_with_llm(candidates)
    if scored is None:
        scored = score_by_keywords(candidates)
        print("Scoring: KEYWORDS (sin ANTHROPIC_API_KEY -> añádela para cazar exclusivas)")
    else:
        print("Scoring: IA (Claude Haiku)")

    hits = sorted([it for it in scored if it.get("score", 0) >= MIN_SCORE],
                  key=lambda x: x.get("score", 0), reverse=True)[:MAX_ALERTS * 2]
    print(f"Superan umbral (>= {MIN_SCORE}): {len(hits)}")

    # Filtro de primicia: descarta lo que la prensa española ya publicó.
    final = []
    if CHECK_SPANISH_NOVELTY:
        for it in hits:
            if already_in_spanish(it.get("es") or it["title"]):
                continue
            final.append(it)
            if len(final) >= MAX_ALERTS:
                break
        print(f"Tras filtro 'ya en español': {len(final)}")
    else:
        final = hits[:MAX_ALERTS]

    if final:
        send_telegram(format_digest(final))
    elif HEARTBEAT:
        send_telegram(f"🌍 <b>Climate Radar</b> · ejecutado, sin exclusivas nuevas "
                      f"(analizados: {len(candidates)}) · {now_utc():%d %b %H:%M} UTC")

    for it in fresh:
        seen.add(it["id"])
    save_seen(seen)
    print("Estado guardado. Fin.")


if __name__ == "__main__":
    main()
