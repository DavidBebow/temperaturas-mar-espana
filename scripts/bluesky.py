#!/usr/bin/env python3
"""bluesky.py 1.0.0 · 1-11-2026

«El dato del día» de calentamientoglobal.es en Bluesky (protocolo AT, sin librerías).
Publica como máximo un post por la mañana y, si salta un récord, otro por la tarde.
Si no hay nada fuerte, ese día no publica (un bot que inunda se silencia).

REGLAS DE ELECCIÓN (primer candidato que exista y cuya `clave` no esté ya en
docs/bluesky/publicados.json; para cambiarlas basta editar `ORDEN_MANANA`)
  Turno de mañana (BLUESKY_TURNO=manana)
    a) Balance del mes anterior (prensa/balance/index.json): el día 1 con estado
       «provisional»; hasta el día 15, otra vez cuando pasa a «verificado». Nunca con
       otro estado (p. ej. «cerrado»). Clave: balance-<AAAA-MM>-<estado>.
    b) Récord de hoy o de ayer (records/hoy.json), cerrado (no en curso), no marcado
       «revisar» y que no esté en `en_revision`. Absoluto antes que mensual; luego mayor
       margen. Clave: record-<id del récord>.
    c) Historia tipo «exclusiva» de prensa/noticias/hoy.json. Clave: la suya.
    d) Historia con más puntos si tiene >= 90 (PUNTOS_MIN). Clave: la suya.
    e) Martes y miércoles, si el boletín de embalses (embalses.json) es de esta semana.
       Clave: embalses-<boletin_fecha>.
    f) Viernes: frase_dia de Tu capital (tu-capital/nacional.json).
       Clave: tu-capital-<fecha_datos_max>.
    g) Nada: termina sin publicar y lo dice en el log.
  Turno de tarde (BLUESKY_TURNO=tarde): solo b), y solo si esa clave no se publicó antes.

REGLAS DE TEXTO E IMAGEN
  * Todo sale de un JSON del repo con su fecha y su fuente; nunca nada «en revisión».
    Una historia sin fuente identificable (AEMET, MITECO, NOAA…) no se publica.
  * <= 300 caracteres, fecha absoluta, «provisional» si lo es, enlace con UTM, <= 2 etiquetas.
  * Una sola imagen (grafico.png de la historia > PNG del balance / ranking de Tu capital >
    captura del día de capturas/indice.json) con texto alternativo; si no hay imagen,
    tarjeta de enlace con og:title / og:description / og:image. Nunca las dos.

VARIABLES DE ENTORNO
  BLUESKY_HANDLE, BLUESKY_APP_PASSWORD   credenciales (contraseña de aplicación)
  BLUESKY_TURNO     manana | tarde (por defecto manana)
  BLUESKY_SECO=1    elige y compone, imprime el post; no publica ni escribe registro
  BLUESKY_PERFIL=1  sube el perfil (nombre, descripción, avatar), imprime el DID y sale
  Solo para pruebas: BLUESKY_FECHA=AAAA-MM-DD, BLUESKY_SOLO=a..f, BLUESKY_REPETIR=1
  (ignora publicados), BLUESKY_SALTAR=clave1,clave2, BLUESKY_PUNTOS_MIN=<n>.
"""
import io
import json
import os
import re
import sys
import time
import datetime as dt
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

VERSION = "1.0.0"
RAIZ = Path(__file__).resolve().parent.parent
DOCS = RAIZ / "docs"
DIR_REG = DOCS / "bluesky"
WEB = "https://calentamientoglobal.es"
PDS = "https://bsky.social"
PUBLICO = "https://public.api.bsky.app"
UTM = "?utm_source=bluesky&utm_medium=social&utm_campaign=dato-del-dia"
UA = "Mozilla/5.0 (calentamientoglobal.es bluesky.py/%s)" % VERSION
LOGO = "https://calentamientoglobal.es/wp-content/uploads/2024/04/LOGO-WEB-CALENTAMIENTO-GLOBL.png"

LIMITE_TEXTO = 300
OBJETIVO_TEXTO = 295        # margen: len() cuenta puntos de código, no grafemas
MAX_IMG = 950_000           # bytes; el límite de Bluesky es ~976 KB
MAX_ALT = 1000
PUNTOS_MIN = float(os.getenv("BLUESKY_PUNTOS_MIN", "90"))
SERIE_MIN_ANIOS = 0         # 0 = sin filtro. Si se pone p. ej. 30, los récords de estaciones con
                            # menos años de serie no se publican (decisión editorial pendiente).

SECO = os.getenv("BLUESKY_SECO") == "1"
PERFIL = os.getenv("BLUESKY_PERFIL") == "1"
TURNO = os.getenv("BLUESKY_TURNO", "manana")
SOLO = os.getenv("BLUESKY_SOLO", "").lower()
REPETIR = os.getenv("BLUESKY_REPETIR") == "1"
SALTAR = {s for s in os.getenv("BLUESKY_SALTAR", "").split(",") if s}

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]

FUENTES = [  # (patrón, nombre mostrado)
    (r"AEMET", "AEMET"), (r"MITECO", "MITECO"), (r"NOAA", "NOAA"),
    (r"NASA FIRMS|FIRMS", "NASA FIRMS"), (r"NSIDC", "NSIDC"), (r"WGMS", "WGMS"),
    (r"Copernicus|ERA5|C3S", "Copernicus"), (r"Open-Meteo", "Open-Meteo"),
    (r"NCEP", "NCEP/NCAR"),
]


def log(*a):
    print(*a, flush=True)


def hoy_fecha():
    f = os.getenv("BLUESKY_FECHA")
    if f:
        return dt.date.fromisoformat(f)
    if ZoneInfo:
        return dt.datetime.now(ZoneInfo("Europe/Madrid")).date()
    return dt.datetime.utcnow().date()


HOY = hoy_fecha()


# ------------------------------------------------------------------ utilidades
def leer(ruta, defecto=None):
    p = DOCS / ruta if not str(ruta).startswith("/") else Path(ruta)
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defecto


def num(x, dec=1):
    s = f"{abs(x):,.{dec}f}".replace(",", "§").replace(".", ",").replace("§", ".")
    if abs(x) < 10000:
        s = s.replace(".", "")
    return s


def con_signo(x, dec=1):
    return ("+" if x >= 0 else "-") + num(x, dec)


def fecha_es(d, anio=None):
    if isinstance(d, str):
        d = dt.date.fromisoformat(d[:10])
    s = f"{d.day} de {MESES[d.month - 1]}"
    if anio or (anio is None and d.year != HOY.year):
        s += f" de {d.year}"
    return s


def cap1(s):
    return s[:1].upper() + s[1:]


def fuente_de(*textos):
    t = " ".join(x for x in textos if x)
    hallada = []
    for pat, nombre in FUENTES:
        if re.search(pat, t) and nombre not in hallada:
            hallada.append(nombre)
    return " y ".join(hallada[:2]) if hallada else None


def http(met, url, reintentos=2, espera=20, **kw):
    ultimo = None
    kw.setdefault("timeout", 30)
    for i in range(reintentos + 1):
        try:
            r = requests.request(met, url, **kw)
            if r.status_code < 500 and r.status_code != 429:
                return r
            ultimo = "HTTP %s" % r.status_code
        except requests.RequestException as e:
            ultimo = str(e)[:200]
        if i < reintentos:
            time.sleep(espera)
    raise RuntimeError("%s %s: %s" % (met, url, ultimo))


# ------------------------------------------------------------------ candidatos
def _pub():
    return SALTAR if REPETIR else CLAVES_PUBLICADAS | SALTAR


def cand_balance():
    idx = leer("prensa/balance/index.json", {}) or {}
    ant = (HOY.replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m")
    ent = next((m for m in idx.get("meses", []) if m.get("mes") == ant), None)
    if not ent:
        return None
    estado = ent.get("estado")
    if estado == "provisional" and HOY.day != 1:
        return None
    if estado == "verificado" and HOY.day > 15:
        return None
    if estado not in ("provisional", "verificado"):
        return None
    clave = "balance-%s-%s" % (ant, estado)
    if clave in _pub():
        return None
    b = leer("prensa/balance/%s.json" % ant)
    if not b or not b.get("nacional"):
        return None
    nac = b["nacional"]
    mes = (b.get("titulo_mes") or ent.get("titulo_mes") or ant)
    fuente = fuente_de(b.get("fuente")) or "AEMET"
    anom = nac["anomalia_media"]
    n = nac["n"]
    if nac.get("sentido") == "frio" or nac.get("n_frias", 0) > nac.get("n_calidas", 0):
        k, adj = nac.get("n_frias", 0), "frías"
    else:
        k, adj = nac.get("n_calidas", 0), "cálidas"
    nombre_mes = mes.split(" de ")[0]
    obl = [f"{cap1(mes)}: {con_signo(anom)} °C sobre lo normal (1991-2020) de media en {n} provincias."]
    opc = [f"Las {n} fueron más {adj} de lo normal." if k == n else f"{k} de {n} fueron más {adj} de lo normal."]
    if nac.get("n_top5_firme"):
        opc.append(f"En {nac['n_top5_firme']} de ellas, uno de los cinco {nombre_mes}s más cálidos de su serie.")
    if estado == "provisional":
        obl.append("Dato provisional.")
    obl.append(f"Datos: {fuente} · cálculo propio.")
    png = DOCS / ("prensa/balance/%s/nacional.png" % ant)
    alt_desc = (f"barras con la anomalía de la temperatura media de {mes} respecto a la media 1991-2020 "
                f"en cada una de las {n} provincias analizadas, de la más a la menos cálida")
    return dict(letra="a", clave=clave, emoji="📊", obl=obl, opc=opc,
                url=WEB + "/prensa/balance-del-mes/", tags=["#clima", "#temperatura"],
                img=("local", png) if png.exists() else None, alt_desc=alt_desc,
                alt_frase=obl[0], fuente=fuente,
                og=(cap1(mes) + ": balance provincia a provincia", (b.get("nota_nacional") or {}).get("titular") or ""))


def _hallazgo_de(rid):
    h = leer("prensa/hallazgos.json", {}) or {}
    return next((e for e in h.get("enviables", []) if e.get("id_record") == rid), None)


def cand_record():
    r = leer("records/hoy.json")
    if not r:
        return None
    rev = set()
    for e in r.get("en_revision", []) or []:
        rev.add(e if isinstance(e, str) else e.get("id"))
    rev.discard(None)
    lista = list(r.get("records_hoy", []) or []) + list(r.get("records_ayer", []) or [])
    ok = []
    for e in lista:
        if e.get("id") in rev or e.get("revisar") or e.get("en_curso"):
            continue
        if e.get("estado") not in ("provisional", "confirmado"):
            continue
        if ("record-" + e["id"]) in _pub():
            continue
        if SERIE_MIN_ANIOS and e.get("desde") and (HOY.year - int(e["desde"])) < SERIE_MIN_ANIOS:
            continue
        ok.append(e)
    if not ok:
        return None
    peso = {"absoluto": 3, "mes": 2}
    ok.sort(key=lambda e: (peso.get(e.get("nivel"), 1), e.get("margen") or 0, e.get("fecha", "")), reverse=True)
    e = ok[0]
    d = dt.date.fromisoformat(e["fecha"])
    mes = MESES[d.month - 1]
    v = e["valor"]
    ant = e.get("record_anterior") or {}
    es_min = e.get("variable") == "tmin"
    if e.get("nivel") == "absoluto":
        alcance = "récord absoluto de su estación"
    else:
        alcance = ("la más baja" if es_min else "la más alta") + f" en un {mes} desde que su estación tiene registros"
    primera = (f"{e['bonito']} ({e['provincia']}): {'mínima' if es_min else 'máxima'} de {num(v)} °C "
               f"el {fecha_es(d)}, {alcance}")
    if ant.get("valor") is not None:
        primera += f" (anterior: {num(ant['valor'])} °C, {ant.get('anio')})"
    primera += "."
    obl = [primera]
    if e.get("estado") == "provisional":
        obl.append("Dato provisional.")
    if e.get("desde") and int(e["desde"]) >= 1990:
        obl.append(f"Serie de la estación: desde {e['desde']}.")
    obl.append("Datos: AEMET · cálculo propio.")
    h = _hallazgo_de(e["id"])
    img = None
    alt_desc = ""
    if h and h.get("grafico") and (DOCS / h["grafico"]).exists():
        img = ("local", DOCS / h["grafico"])
        alt_desc = (f"barras con el récord de {'mínima' if es_min else 'máxima'} de cada mes en la estación de "
                    f"{e['bonito']} ({e['provincia']}), con el valor del {fecha_es(d)} señalado")
    return dict(letra="b", clave="record-" + e["id"], emoji="🌡️", obl=obl, opc=[],
                url=WEB + "/records-de-temperatura/", tags=["#clima", "#récord"],
                img=img, img_captura="records", alt_desc=alt_desc, alt_frase=primera, fuente="AEMET",
                og=(e.get("titular", ""), e.get("dato", "")))


def _captura(cid):
    idx = leer("capturas/indice.json", {}) or {}
    c = (idx.get("capturas") or {}).get(cid)
    if not c or not c.get("url"):
        return None
    try:
        f = dt.date.fromisoformat(c["fecha"][:10])
    except (KeyError, ValueError):
        return None
    if (HOY - f).days > 1:
        return None
    cat = leer("reutilizar/herramientas.json", {}) or {}
    tit = next((x.get("titulo") for x in cat.get("herramientas", []) if x.get("id") == cid), None)
    return c["url"], tit, c["fecha"][:10]


def _captura_para(h, hoy_json):
    provs = h.get("provincias") or []
    if len(provs) == 1:
        info = (hoy_json.get("provincias") or {}).get(provs[0]) or {}
        slug = (info.get("slug") or "").replace("-", "_")
        c = _captura("provincia-" + slug)
        if c:
            return "provincia-" + slug, c, info.get("nombre")
    t = ((h.get("titular") or "") + " " + (h.get("clave") or "")).lower()
    sec = h.get("seccion")
    cid = None
    if sec == "agua" or (sec in ("ultima", "analisis") and re.search(r"lluvi|otoñ|otono|litros|seco|\bmm\b", t)):
        cid = "caudal" if re.search(r"río|rios|caudal", t) else ("embalses" if "embalse" in t else "lluvias")
    elif sec == "calor":
        cid = "records"
    elif sec == "mar":
        cid = "oceano"
    elif sec == "aire":
        cid = "incendios" if re.search(r"incendi|foco|fuego", t) else "calidad_aire"
    if cid:
        c = _captura(cid)
        if c:
            return cid, c, None
    return None


def _cand_historia(h, letra, hoy_json):
    clave = h.get("clave") or h["id"]
    if clave in _pub():
        return None
    gr = h.get("grafico") or {}
    cifras = " ".join(f"{c.get('n','')} {c.get('l','')}" for c in h.get("cifras", []))
    fuente = fuente_de(h.get("titular"), h.get("subtitulo"), cifras, gr.get("pie"))
    if not fuente:
        log(f"  · {h['id']}: sin fuente identificable en el JSON, no se publica")
        return None
    sec = h.get("seccion")
    t = h.get("titular", "")
    emoji = {"agua": "💧" if "embalse" in t.lower() else "🌧️", "calor": "🌡️"}.get(sec, "")
    if sec == "ultima" and re.search(r"lluvi|otoñ|litros|seco", t.lower()):
        emoji = "🌧️"
    obl = [t if t.endswith((".", "?", "!")) else t + "."]
    opc = []
    if h.get("cifras"):
        c0 = h["cifras"][0]
        m0 = re.match(r"[\d.,+-]+", str(c0.get("n", "")))
        if m0 and m0.group(0) not in t:   # no repetir la cifra que ya está en el titular
            opc.append(f"{c0['n']} {c0['l']}.")
    if re.search(r"provisional|preliminar", " ".join([h.get("subtitulo", ""), gr.get("pie", "") or ""]), re.I):
        obl.append("Dato provisional.")
    obl.append(f"Datos: {fuente}, {fecha_es(h['fecha'])} · cálculo propio.")
    tema = "#embalses" if "embalse" in t.lower() else {"agua": "#lluvia", "calor": "#calor", "mar": "#mar"}.get(sec)
    if sec == "ultima" and emoji == "🌧️":
        tema = "#lluvia"
    tags = ["#clima"] + ([tema] if tema else [])
    img, alt_desc, nombre = None, "", None
    png = gr.get("png")
    if png and (DOCS / png).exists():
        img = ("local", DOCS / png)
        alt_desc = gr.get("titulo", "gráfico de la historia")
    else:
        cp = _captura_para(h, hoy_json)
        if cp:
            cid, (url, tit, f), nombre = cp
            img = ("url", url)
            alt_desc = (f"captura de la herramienta «{tit}» con los datos del {fecha_es(f)}" if tit else
                        f"captura del observatorio climático de {nombre} con los datos del {fecha_es(f)}")
    return dict(letra=letra, clave=clave, emoji=emoji, obl=obl, opc=opc,
                url=f"{WEB}/prensa/noticia/{h['id']}/", tags=tags, img=img, alt_desc=alt_desc,
                alt_frase=" ".join([obl[0]] + ([h["subtitulo"]] if h.get("subtitulo") else [])),
                fuente=fuente, og=(t, h.get("subtitulo", "")))


def cand_exclusiva():
    hj = leer("prensa/noticias/hoy.json")
    if not hj:
        return None
    for h in sorted(hj.get("historias", []), key=lambda x: -x.get("puntos", 0)):
        if h.get("tipo") == "exclusiva":
            c = _cand_historia(h, "c", hj)
            if c:
                return c
    return None


def cand_puntos():
    hj = leer("prensa/noticias/hoy.json")
    if not hj:
        return None
    for h in sorted(hj.get("historias", []), key=lambda x: -x.get("puntos", 0)):
        if h.get("puntos", 0) < PUNTOS_MIN:
            break
        c = _cand_historia(h, "d", hj)
        if c:
            return c
    return None


def cand_embalses():
    if HOY.weekday() not in (1, 2):
        return None
    e = leer("embalses.json")
    if not e or not e.get("nacional") or not e.get("boletin_fecha"):
        return None
    b = dt.date.fromisoformat(e["boletin_fecha"])
    lunes = HOY - dt.timedelta(days=HOY.weekday())
    if not (lunes <= b <= HOY):
        return None
    clave = "embalses-" + e["boletin_fecha"]
    if clave in _pub():
        return None
    n = e["nacional"]
    obl = [f"Los embalses de España están al {num(n['pct'])} % de su capacidad "
           f"({num(n['volumen_total_hm3'], 0)} de {num(n['capacidad_total_hm3'], 0)} hm³) en el boletín del {fecha_es(b)}."]
    opc = [f"Hace un año: {num(n['pct_hace_1a'])} %; media de diez años: {num(n['pct_media_10a'])} %."]
    obl.append("Datos: MITECO · cálculo propio.")
    c = _captura("embalses")
    img, alt_desc = None, ""
    if c:
        img = ("url", c[0])
        alt_desc = f"captura de la herramienta «{c[1] or 'Embalses de España'}» con los datos del {fecha_es(c[2])}"
    return dict(letra="e", clave=clave, emoji="💧", obl=obl, opc=opc,
                url=e.get("url_web_nacional") or WEB + "/embalses-espana/", tags=["#clima", "#embalses"],
                img=img, alt_desc=alt_desc, alt_frase=obl[0], fuente="MITECO",
                og=("Embalses de España: nivel y evolución", obl[0]))


def cand_tu_capital():
    if HOY.weekday() != 4:
        return None
    t = leer("tu-capital/nacional.json")
    if not t or not t.get("frase_dia") or not t.get("fecha_datos_max"):
        return None
    clave = "tu-capital-" + t["fecha_datos_max"]
    if clave in _pub():
        return None
    frase = t["frase_dia"].rstrip(".")
    m = re.match(r"^(.*?),\s*según los valores diarios de AEMET.*$", frase)
    nucleo = (m.group(1) if m else frase) + "."
    obl = [nucleo, "Estimación con el año en curso.", "Datos: AEMET · cálculo propio."]
    png = DOCS / "tu-capital/nacional-ranking.png"
    img = ("local", png) if png.exists() else None
    alt_desc = ("barras con el calentamiento de la temperatura media anual entre 1970 y 2025, en °C, "
                "de las 24 capitales con serie homogénea y tendencia significativa, de más a menos")
    return dict(letra="f", clave=clave, emoji="📊", obl=obl, opc=[], url=WEB + "/tu-capital/",
                tags=["#clima", "#temperatura"], img=img, alt_desc=alt_desc, alt_frase=nucleo,
                fuente="AEMET", og=("Tu capital, año a año: las 45 capitales", nucleo))


ORDEN_MANANA = [("a", cand_balance), ("b", cand_record), ("c", cand_exclusiva),
                ("d", cand_puntos), ("e", cand_embalses), ("f", cand_tu_capital)]
ORDEN_TARDE = [("b", cand_record)]


def elegir():
    for letra, fn in (ORDEN_TARDE if TURNO == "tarde" else ORDEN_MANANA):
        if SOLO and letra != SOLO:
            continue
        c = fn()
        if c:
            log(f"Candidato elegido: ({letra}) {c['clave']}")
            return c
    return None


# ------------------------------------------------------------------ texto
def mostrar_enlace(url):
    p = urlparse(url)
    s = p.netloc + p.path
    if len(s) > 34:
        partes = [x for x in p.path.split("/") if x]
        if len(partes) > 1:
            s = p.netloc + "/" + partes[0] + "/…"
        else:
            s = p.netloc + p.path
    return s


def componer(c):
    disp = mostrar_enlace(c["url"])
    url_full = c["url"] + UTM

    def armar(opc_n, tags):
        partes = list(c["obl"])
        # los opcionales van tras la primera frase
        partes[1:1] = c["opc"][:opc_n]
        head = ((c["emoji"] + " ") if c["emoji"] else "") + " ".join(partes)
        return head + "\n" + disp + (("\n" + " ".join(tags)) if tags else "")

    tags = list(c["tags"][:2])
    for n_opc in range(len(c["opc"]), -1, -1):
        for tg in (tags, tags[:1], []):
            texto = armar(n_opc, tg)
            if len(texto) <= OBJETIVO_TEXTO:
                return texto, disp, url_full, tg
    # último recurso: recortar la primera frase obligatoria
    exceso = len(armar(0, [])) - OBJETIVO_TEXTO
    c = dict(c)
    c["obl"] = [c["obl"][0][: -(exceso + 2)].rsplit(" ", 1)[0] + "…"] + c["obl"][1:]
    texto = ((c["emoji"] + " ") if c["emoji"] else "") + " ".join(c["obl"]) + "\n" + disp
    return texto, disp, url_full, []


def facets(texto, disp, url_full, tags):
    fs = []
    i = texto.rfind(disp)
    b0 = len(texto[:i].encode("utf-8"))
    fs.append({"index": {"byteStart": b0, "byteEnd": b0 + len(disp.encode("utf-8"))},
               "features": [{"$type": "app.bsky.richtext.facet#link", "uri": url_full}]})
    if tags:
        ini = texto.rfind("\n") + 1
        for m in re.finditer(r"#\w+", texto[ini:]):
            s = len(texto[: ini + m.start()].encode("utf-8"))
            e = len(texto[: ini + m.end()].encode("utf-8"))
            fs.append({"index": {"byteStart": s, "byteEnd": e},
                       "features": [{"$type": "app.bsky.richtext.facet#tag", "tag": m.group(0)[1:]}]})
    return fs


# ------------------------------------------------------------------ imagen
def bytes_imagen(src):
    tipo, ref = src
    if tipo == "local":
        return Path(ref).read_bytes()
    r = http("GET", ref, reintentos=1, espera=5, headers={"User-Agent": UA})
    if r.status_code != 200:
        raise RuntimeError("HTTP %s al descargar %s" % (r.status_code, ref))
    return r.content


def preparar_png(datos):
    """Devuelve (bytes, ancho, alto) con el PNG dentro del límite de Bluesky."""
    im = Image.open(io.BytesIO(datos))
    im.load()
    if len(datos) <= MAX_IMG and im.format == "PNG":
        return datos, im.width, im.height
    im = im.convert("RGBA") if im.mode in ("P", "LA") else im
    for lado in (1600, 1400, 1200, 1000, 800, 600):
        w = im.copy()
        w.thumbnail((lado, lado), Image.LANCZOS)
        for q in (False, True):
            buf = io.BytesIO()
            (w.convert("RGB").quantize(256) if q else w).save(buf, "PNG", optimize=True)
            if buf.tell() <= MAX_IMG:
                return buf.getvalue(), w.width, w.height
    raise RuntimeError("no se logra reducir la imagen por debajo de %d bytes" % MAX_IMG)


def construir_alt(c):
    alt = (f"Gráfico de calentamientoglobal.es: {c['alt_desc']}. {c['alt_frase']} "
           f"Fuente: {c['fuente']}.")
    alt = re.sub(r"\s+", " ", alt).replace("..", ".")
    return alt[:MAX_ALT]


def og_de(url):
    """og:title / og:description / og:image de la página (None si no se alcanza)."""
    try:
        r = http("GET", url, reintentos=0, headers={"User-Agent": UA})
        if r.status_code != 200:
            return None
    except RuntimeError:
        return None
    out = {}
    for k in ("title", "description", "image"):
        m = re.search(r'<meta[^>]+property=["\']og:%s["\'][^>]+content=["\']([^"\']*)["\']' % k, r.text) or \
            re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+property=["\']og:%s["\']' % k, r.text)
        if m:
            import html as _h
            out[k] = _h.unescape(m.group(1))
    return out or None


# ------------------------------------------------------------------ protocolo AT
def credenciales():
    h, p = os.getenv("BLUESKY_HANDLE", "").strip(), os.getenv("BLUESKY_APP_PASSWORD", "").strip()
    if not h or not p:
        log("::error::Faltan los secretos BLUESKY_HANDLE y/o BLUESKY_APP_PASSWORD en el repositorio "
            "(Settings → Secrets and variables → Actions). No se publica.")
        sys.exit(2)
    return h, p


def sesion():
    h, p = credenciales()
    r = http("POST", PDS + "/xrpc/com.atproto.server.createSession", json={"identifier": h, "password": p})
    if r.status_code in (400, 401):
        log("::error::Bluesky rechaza las credenciales (%s). Revisa BLUESKY_HANDLE y que "
            "BLUESKY_APP_PASSWORD sea una contraseña de aplicación vigente." % r.text[:150])
        sys.exit(2)
    r.raise_for_status()
    j = r.json()
    return {"Authorization": "Bearer " + j["accessJwt"]}, j["did"], h


def subir_blob(cab, datos, mime):
    r = http("POST", PDS + "/xrpc/com.atproto.repo.uploadBlob",
             headers={**cab, "Content-Type": mime}, data=datos)
    r.raise_for_status()
    return r.json()["blob"]


def registrar(c, turno, uri, cid, texto, imagen):
    DIR_REG.mkdir(parents=True, exist_ok=True)
    f = DIR_REG / "publicados.json"
    reg = leer(str(f), {"publicados": []}) or {"publicados": []}
    ahora = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ent = {"clave": c["clave"], "fecha": ahora, "turno": turno, "uri": uri, "cid": cid,
           "texto": texto, "imagen": imagen}
    reg["publicados"].append(ent)
    f.write_text(json.dumps(reg, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (DIR_REG / "ultimo.json").write_text(json.dumps(ent, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def verificar(did, handle, uri):
    for i in range(4):
        time.sleep(5 if i else 3)
        try:
            r = http("GET", PUBLICO + "/xrpc/app.bsky.feed.getAuthorFeed",
                     reintentos=0, params={"actor": handle, "limit": 3})
            if r.status_code != 200:
                r = http("GET", PUBLICO + "/xrpc/app.bsky.feed.getAuthorFeed",
                         reintentos=0, params={"actor": did, "limit": 3})
            if r.status_code == 200 and any(x["post"]["uri"] == uri for x in r.json().get("feed", [])):
                return True
        except RuntimeError:
            pass
    return False


def publicar(post):
    cab, did, handle = sesion()
    log("DID de la cuenta:", did)
    c = post["c"]
    embed = None
    if post.get("png"):
        blob = subir_blob(cab, post["png"], "image/png")
        embed = {"$type": "app.bsky.embed.images", "images": [
            {"alt": post["alt"], "image": blob, "aspectRatio": {"width": post["w"], "height": post["h"]}}]}
    else:
        ext = {"uri": c["url"] + UTM, "title": post["og_titulo"][:300], "description": post["og_desc"][:1000]}
        if post.get("og_img"):
            try:
                d = http("GET", post["og_img"], reintentos=1, espera=5, headers={"User-Agent": UA}).content
                im = Image.open(io.BytesIO(d))
                buf = io.BytesIO()
                im = im.convert("RGB")
                im.thumbnail((1200, 1200))
                q = 85
                while True:
                    buf = io.BytesIO()
                    im.save(buf, "JPEG", quality=q)
                    if buf.tell() <= MAX_IMG or q <= 40:
                        break
                    q -= 15
                ext["thumb"] = subir_blob(cab, buf.getvalue(), "image/jpeg")
            except Exception as e:  # la miniatura es opcional
                log("  · sin miniatura de la tarjeta:", e)
        embed = {"$type": "app.bsky.embed.external", "external": ext}
    rec = {"$type": "app.bsky.feed.post", "text": post["texto"],
           "createdAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
           "langs": ["es"], "facets": post["facets"], "embed": embed}
    r = http("POST", PDS + "/xrpc/com.atproto.repo.createRecord", headers=cab,
             json={"repo": did, "collection": "app.bsky.feed.post", "record": rec})
    r.raise_for_status()
    j = r.json()
    log("Publicado:", j["uri"])
    # primero el registro (evita duplicados si falla la comprobación), luego se verifica
    registrar(c, TURNO, j["uri"], j["cid"], post["texto"], post.get("imagen_ref"))
    if verificar(did, handle, j["uri"]):
        log("Comprobado en la API pública: el post existe y su uri coincide.")
    else:
        log("::warning::Publicado, pero la API pública aún no devuelve el post (puede ser latencia). uri=" + j["uri"])
    rkey = j["uri"].rsplit("/", 1)[-1]
    log("Ver: https://bsky.app/profile/%s/post/%s" % (handle, rkey))


# ------------------------------------------------------------------ perfil
def perfil():
    cab, did, handle = sesion()
    log("DID de la cuenta (para el registro DNS _atproto):", did)
    r = http("GET", LOGO, reintentos=1, espera=5, headers={"User-Agent": UA})
    r.raise_for_status()
    im = Image.open(io.BytesIO(r.content)).convert("RGBA")
    lienzo = Image.new("RGB", (800, 800), "white")
    im.thumbnail((800, 800), Image.LANCZOS)
    lienzo.paste(im, ((800 - im.width) // 2, (800 - im.height) // 2), im)
    q = 90
    while True:
        buf = io.BytesIO()
        lienzo.save(buf, "JPEG", quality=q)
        if buf.tell() < 900_000 or q <= 40:
            break
        q -= 10
    avatar = subir_blob(cab, buf.getvalue(), "image/jpeg")
    previo = http("GET", PDS + "/xrpc/com.atproto.repo.getRecord", headers=cab,
                  params={"repo": did, "collection": "app.bsky.actor.profile", "rkey": "self"}, reintentos=0)
    rec = {"$type": "app.bsky.actor.profile"}
    swap = None
    if previo.status_code == 200:
        v = previo.json()
        rec.update({k: x for k, x in v.get("value", {}).items() if k in ("banner",)})
        swap = v.get("cid")
    rec["displayName"] = "Calentamiento Global · Observatorio climático"
    rec["description"] = ("Cuenta automatizada: un dato climático de España al día, medido por AEMET, MITECO y "
                          "NOAA y calculado por calentamientoglobal.es. Libre para publicar con CC BY 4.0. "
                          "Humanos y datos a medida: contacto@calentamientoglobal.es")
    assert len(rec["description"]) <= 256, len(rec["description"])
    rec["avatar"] = avatar
    body = {"repo": did, "collection": "app.bsky.actor.profile", "rkey": "self", "record": rec}
    if swap:
        body["swapRecord"] = swap
    r = http("POST", PDS + "/xrpc/com.atproto.repo.putRecord", headers=cab, json=body)
    r.raise_for_status()
    log("Perfil actualizado:", r.json().get("uri"))
    log("Perfil público: https://bsky.app/profile/" + handle)


# ------------------------------------------------------------------ principal
def preparar(c):
    texto, disp, url_full, tags = componer(c)
    post = {"c": c, "texto": texto, "facets": facets(texto, disp, url_full, tags), "url_full": url_full}
    if c.get("img"):
        try:
            datos = bytes_imagen(c["img"])
            png, w, h = preparar_png(datos)
            post.update(png=png, w=w, h=h, imagen_ref=str(c["img"][1]))
            desc = c["alt_desc"]
            if not desc:
                desc = "imagen de la herramienta"
            c2 = dict(c, alt_desc=desc)
            post["alt"] = construir_alt(c2)
        except Exception as e:
            log(f"  · imagen no disponible ({e}); se usará tarjeta de enlace")
    if not post.get("png") and c.get("img_captura"):
        cp = _captura(c["img_captura"])
        if cp:
            try:
                png, w, h = preparar_png(bytes_imagen(("url", cp[0])))
                post.update(png=png, w=w, h=h, imagen_ref=cp[0])
                post["alt"] = construir_alt(dict(c, alt_desc=f"captura de la herramienta «{cp[1]}» con los datos del {fecha_es(cp[2])}"))
            except Exception as e:
                log(f"  · captura no disponible ({e})")
    if not post.get("png"):
        og = og_de(c["url"]) or {}
        post["og_titulo"] = og.get("title") or c["og"][0]
        post["og_desc"] = og.get("description") or c["og"][1]
        post["og_img"] = og.get("image")
        post["og_origen"] = "página" if og else "JSON (la página no es accesible desde aquí)"
    return post


def imprimir(post):
    c = post["c"]
    t = post["texto"]
    log("\n" + "=" * 70)
    log(f"clave: {c['clave']}   turno: {TURNO}   fecha de prueba/real: {HOY}")
    log("-" * 70)
    log(t)
    log("-" * 70)
    log(f"longitud: {len(t)} caracteres (límite {LIMITE_TEXTO}); bytes UTF-8: {len(t.encode('utf-8'))}")
    bt = t.encode("utf-8")
    for f in post["facets"]:
        i = f["index"]
        log(f"facet {f['features'][0]['$type'].split('#')[1]:4} bytes {i['byteStart']}-{i['byteEnd']}: "
            f"{bt[i['byteStart']:i['byteEnd']].decode('utf-8')!r}  -> "
            f"{f['features'][0].get('uri') or f['features'][0].get('tag')}")
    if post.get("png"):
        log(f"imagen: {post.get('imagen_ref')}  {post['w']}x{post['h']}  {len(post['png'])} bytes")
        log(f"alt ({len(post['alt'])} car.): {post['alt']}")
    else:
        log(f"sin imagen: tarjeta de enlace  title={post['og_titulo']!r}")
        log(f"  description={post['og_desc'][:140]!r}  miniatura={post.get('og_img')}  origen={post['og_origen']}")
    log("=" * 70)


def main():
    log(f"bluesky.py {VERSION} · turno={TURNO} seco={SECO} perfil={PERFIL} fecha={HOY}")
    if PERFIL:
        perfil()
        return 0
    global CLAVES_PUBLICADAS
    reg = leer(str(DIR_REG / "publicados.json"), {"publicados": []}) or {"publicados": []}
    CLAVES_PUBLICADAS = {p["clave"] for p in reg.get("publicados", [])}
    if not SECO:
        credenciales()
    c = elegir()
    if not c:
        log("Hoy no hay ningún dato lo bastante fuerte (o ya publicado): no se publica nada.")
        return 0
    post = preparar(c)
    imprimir(post)
    if len(post["texto"]) > LIMITE_TEXTO:
        log("::error::El texto supera los 300 caracteres; no se publica.")
        return 1
    if SECO:
        log("Modo seco: no se publica ni se escribe el registro.")
        return 0
    publicar(post)
    return 0


CLAVES_PUBLICADAS = set()

if __name__ == "__main__":
    sys.exit(main())
