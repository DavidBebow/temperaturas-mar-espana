#!/usr/bin/env python3
"""Niebla en España, en directo · generador de docs/niebla/niebla.json (solo biblioteca estándar).

Fuentes de suelo (el satélite lo carga el navegador desde EUMETView, no pasa por aquí):
  DGT      tramos con niebla: registros sit:PoorEnvironmentConditions con poorEnvironmentType = fog (DATEX II v3.7,
           mismo lector que nieve_puertos.py). Sin Cataluña ni País Vasco.
  METAR    aeródromos españoles (aviationweather.gov, por lista de códigos OACI). Visibilidad en metros desde rawOb.
  AEMET    observación convencional (campo vis, km, solo estaciones con sensor). Secreto AEMET_API_KEY.

Uso:  python scripts/niebla.py            pasada normal
      python scripts/niebla.py --diag     escribe docs/niebla/diag.json (recuentos y tres ejemplos) y nada más
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nieve_puertos as NP  # noqa: E402  (descarga y lectura de registros de la DGT)

VERSION = "1.0.0"
RAIZ = Path(os.environ.get("CG_RAIZ") or Path(__file__).resolve().parent.parent)
SALIDA = RAIZ / "docs" / "niebla"
JSON_OUT = SALIDA / "niebla.json"
DIAG_OUT = SALIDA / "diag.json"
ARCHIVO = RAIZ / "archivo" / "niebla"
HIST = ARCHIVO / "niebla_hist.csv"
DIA = ARCHIVO / "provincias_dia.csv"
GEOJSON = RAIZ / "archivo" / "nieve" / "provincias.geojson"      # el mismo que usan los widgets de nieve

TZ = ZoneInfo("Europe/Madrid")
UA = "calentamientoglobal.es/niebla (+https://calentamientoglobal.es/niebla/)"
DGT_URL = "https://nap.dgt.es/datex2/v3/dgt/SituationPublication/datex2_v37.xml"
DGT_URL_36 = "https://nap.dgt.es/datex2/v3/dgt/SituationPublication/datex2_v36.xml"
METAR_URL = "https://aviationweather.gov/api/data/metar?ids={ids}&format=json&hours=3"
AEMET_URL = "https://opendata.aemet.es/opendata/api/observacion/convencional/todas"
AEMET_VIS_A_M = 1000.0           # vis viene en km (se mide en diag.json: rango y ejemplos)
MAX_EDAD_MIN = 90                # observaciones más viejas no cuentan
UMBRAL_NIEBLA_M = 1000
UMBRAL_BRUMA_M = 5000
KEEPALIVE_MIN = 150              # sin cambios, se reescribe igualmente pasado este tiempo (el vigilante caduca a las 3 h)
MESES = NP.MESES

# slug, nombre, nombre en el GeoJSON (50 provincias + Ceuta y Melilla)
PROVINCIAS = [
    ('a-coruna', 'A Coruña', 'A Coruña'), ('alava', 'Álava', 'Araba/Álava'), ('albacete', 'Albacete', 'Albacete'),
    ('alicante', 'Alicante', 'Alacant/Alicante'), ('almeria', 'Almería', 'Almería'), ('asturias', 'Asturias', 'Asturias'),
    ('avila', 'Ávila', 'Ávila'), ('badajoz', 'Badajoz', 'Badajoz'), ('baleares', 'Baleares', 'Illes Balears'),
    ('barcelona', 'Barcelona', 'Barcelona'), ('bizkaia', 'Bizkaia', 'Bizkaia/Vizcaya'), ('burgos', 'Burgos', 'Burgos'),
    ('caceres', 'Cáceres', 'Cáceres'), ('cadiz', 'Cádiz', 'Cádiz'), ('cantabria', 'Cantabria', 'Cantabria'),
    ('castellon', 'Castellón', 'Castelló/Castellón'), ('ceuta', 'Ceuta', 'Ceuta'), ('ciudad-real', 'Ciudad Real', 'Ciudad Real'),
    ('cordoba', 'Córdoba', 'Córdoba'), ('cuenca', 'Cuenca', 'Cuenca'), ('gipuzkoa', 'Gipuzkoa', 'Gipuzkoa/Guipúzcoa'),
    ('girona', 'Girona', 'Girona'), ('granada', 'Granada', 'Granada'), ('guadalajara', 'Guadalajara', 'Guadalajara'),
    ('huelva', 'Huelva', 'Huelva'), ('huesca', 'Huesca', 'Huesca'), ('jaen', 'Jaén', 'Jaén'), ('leon', 'León', 'León'),
    ('lleida', 'Lleida', 'Lleida'), ('lugo', 'Lugo', 'Lugo'), ('madrid', 'Madrid', 'Madrid'), ('malaga', 'Málaga', 'Málaga'),
    ('melilla', 'Melilla', 'Melilla'), ('murcia', 'Murcia', 'Murcia'), ('navarra', 'Navarra', 'Navarra'),
    ('ourense', 'Ourense', 'Ourense'), ('palencia', 'Palencia', 'Palencia'), ('las-palmas', 'Las Palmas', 'Las Palmas'),
    ('pontevedra', 'Pontevedra', 'Pontevedra'), ('la-rioja', 'La Rioja', 'La Rioja'), ('salamanca', 'Salamanca', 'Salamanca'),
    ('santa-cruz-de-tenerife', 'Santa Cruz de Tenerife', 'Santa Cruz De Tenerife'), ('segovia', 'Segovia', 'Segovia'),
    ('sevilla', 'Sevilla', 'Sevilla'), ('soria', 'Soria', 'Soria'), ('tarragona', 'Tarragona', 'Tarragona'),
    ('teruel', 'Teruel', 'Teruel'), ('toledo', 'Toledo', 'Toledo'), ('valencia', 'Valencia', 'València/Valencia'),
    ('valladolid', 'Valladolid', 'Valladolid'), ('zamora', 'Zamora', 'Zamora'), ('zaragoza', 'Zaragoza', 'Zaragoza'),
]
NOMBRE = {s: n for s, n, _g in PROVINCIAS}
SIN_DGT = {"barcelona": "Cataluña", "girona": "Cataluña", "lleida": "Cataluña", "tarragona": "Cataluña",
           "alava": "el País Vasco", "bizkaia": "el País Vasco", "gipuzkoa": "el País Vasco"}
ALIAS = {"coruna a": "a-coruna", "la coruna": "a-coruna", "orense": "ourense", "illes balears": "baleares",
         "islas baleares": "baleares", "palmas las": "las-palmas", "rioja la": "la-rioja", "guipuzcoa": "gipuzkoa",
         "vizcaya": "bizkaia", "araba": "alava", "gerona": "girona", "lerida": "lleida", "castello": "castellon",
         "santa cruz tenerife": "santa-cruz-de-tenerife", "tenerife": "santa-cruz-de-tenerife",
         "gran canaria": "las-palmas", "balears illes": "baleares", "alacant": "alicante", "valencia valencia": "valencia"}
ORDEN_ESTADO = {"sin_dato": 0, "sin_niebla": 1, "bruma": 2, "niebla": 3}

# Aeródromos españoles con METAR (prefijos LE, GC y GE). En la primera pasada se comprueba cuáles responden.
OACI = ["LEAB", "LEAL", "LEAM", "LEAS", "LEBA", "LEBB", "LEBG", "LEBL", "LEBZ", "LECH", "LECO", "LECU", "LEDA", "LEGE",
        "LEGR", "LEGT", "LEHC", "LEIB", "LEJR", "LELC", "LELL", "LELN", "LEMD", "LEMG", "LEMH", "LEMO", "LEPA", "LEPP",
        "LERI", "LERJ", "LERL", "LERS", "LERT", "LESA", "LESB", "LESO", "LEST", "LETO", "LEVC", "LEVD", "LEVT", "LEVX",
        "LEXJ", "LEZG", "LEZL", "LECI", "LEVS", "LEBT", "LEMI", "LESU", "LEAG", "LEGA", "LEMR", "LEPI", "LEVP", "LEZA",
        "GCFV", "GCGM", "GCHI", "GCLA", "GCLP", "GCRR", "GCTS", "GCXO", "GCLB", "GCLZ", "GEML", "GECE"]


def log(m: str) -> None:
    print(f"[niebla] {m}", flush=True)


# --------------------------------------------------------------------------------------------- territorio
class Territorio:
    """Provincia por nombre (la DGT) o por punto (GeoJSON de provincias que ya usan los widgets)."""

    def __init__(self, geojson: Path = GEOJSON):
        self.por_nombre = {}
        for s, n, g in PROVINCIAS:
            for parte in {n, g, *g.split("/")}:
                self.por_nombre[NP.norm(parte)] = s
        self.por_nombre.update(ALIAS)
        self.polis: list = []                    # (slug, anillos, bbox)
        try:
            gj = json.loads(Path(geojson).read_text(encoding="utf-8"))
            por_g = {g: s for s, _n, g in PROVINCIAS}
            for f in gj["features"]:
                s = por_g.get(f["properties"].get("name"))
                if not s:
                    continue
                geom = f["geometry"]
                pols = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
                for pol in pols:
                    xs = [p[0] for p in pol[0]]
                    ys = [p[1] for p in pol[0]]
                    self.polis.append((s, pol, (min(xs), min(ys), max(xs), max(ys))))
        except (OSError, ValueError, KeyError):
            self.polis = []

    def slug_nombre(self, nombre) -> str | None:
        return self.por_nombre.get(NP.norm(nombre)) if nombre else None

    @staticmethod
    def _dentro(lon, lat, pol) -> bool:
        def anillo(a):
            d, j = False, len(a) - 1
            for i in range(len(a)):
                xi, yi, xj, yj = a[i][0], a[i][1], a[j][0], a[j][1]
                if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-15) + xi:
                    d = not d
                j = i
            return d
        return anillo(pol[0]) and not any(anillo(h) for h in pol[1:])

    def slug_punto(self, lat, lon) -> str | None:
        if lat is None or lon is None or not self.polis:
            return None
        for s, pol, (x0, y0, x1, y1) in self.polis:
            if x0 <= lon <= x1 and y0 <= lat <= y1 and self._dentro(lon, lat, pol):
                return s
        mejor, dmin = None, 0.3 ** 2             # costa: el vértice más cercano a menos de ~30 km
        for s, pol, (x0, y0, x1, y1) in self.polis:
            if x0 - 0.3 <= lon <= x1 + 0.3 and y0 - 0.3 <= lat <= y1 + 0.3:
                for x, y in pol[0]:
                    d = (x - lon) ** 2 + (y - lat) ** 2
                    if d < dmin:
                        mejor, dmin = s, d
        return mejor


# ------------------------------------------------------------------------------------------------- DGT
def es_niebla(r: dict) -> bool:
    return r["tipo"] == "PoorEnvironmentConditions" and any("fog" in x.lower() for x in r["v"].get("poorEnvironmentType", []))


def leer_dgt(contenido: bytes, terr: Territorio, ahora: datetime, diag: dict | None = None) -> dict:
    """Tramos activos con niebla, deduplicados por id (gana la versión más reciente)."""
    corte, vistos, n_reg = None, {}, 0
    tipos, cualquier = {}, 0
    for _ev, el in ET.iterparse(io.BytesIO(contenido), events=("end",)):
        n = NP._l(el.tag)
        if n == "publicationTime" and corte is None:
            corte = el.text
        elif n == "situationRecord":
            n_reg += 1
            r = NP._registro(el)
            for t in r["v"].get("poorEnvironmentType", []):
                tipos[t] = tipos.get(t, 0) + 1
            if any("fog" in x.lower() for x in r["v"].get("poorEnvironmentType", [])):
                cualquier += 1
            if es_niebla(r) and r["id"] and NP.activo(r, ahora):
                ant = vistos.get(r["id"])
                if ant is None or r["version"] >= ant["version"]:
                    vistos[r["id"]] = r
            el.clear()
        elif n == "situation":
            el.clear()
    if n_reg == 0:
        raise RuntimeError("el fichero no trae ningún situationRecord")
    tramos = [_tramo(r, terr) for r in vistos.values()]
    tramos.sort(key=lambda t: (t["provincia"] or "", t["carretera"] or "", t["id"]))
    if diag is not None:
        diag.update({"registros": n_reg, "niebla_activos": len(tramos), "fog_en_cualquier_tipo_y_estado": cualquier,
                     "poorEnvironmentType": dict(sorted(tipos.items(), key=lambda kv: -kv[1])[:12]),
                     "sin_provincia": sum(1 for t in tramos if not t["provincia_slug"])})
    return {"corte": (NP._hora(corte) or ahora).astimezone(TZ).isoformat(timespec="seconds"), "n_registros": n_reg,
            "tramos": tramos}


def _tramo(r: dict, terr: Territorio) -> dict:
    d, h = r["desde"] or {}, r["hasta"] or {}
    v = r["v"]
    prov = d.get("provincia") or h.get("provincia")
    lat1, lon1 = d.get("lat"), d.get("lon")
    lat2, lon2 = h.get("lat"), h.get("lon")
    if lat1 is None:
        lat1, lon1 = lat2, lon2
    if lat2 is None:
        lat2, lon2 = lat1, lon1
    slug = terr.slug_nombre(prov) or terr.slug_nombre(h.get("provincia")) or terr.slug_punto(lat1, lon1)
    ini = NP._hora((v.get("overallStartTime") or [None])[0])
    return {"id": r["id"], "carretera": (v.get("roadName") or [None])[0], "pk_ini": d.get("pk"), "pk_fin": h.get("pk"),
            "municipio": d.get("municipio") or h.get("municipio"), "provincia": NOMBRE.get(slug) or prov,
            "provincia_slug": slug, "desde": ini.astimezone(TZ).isoformat(timespec="minutes") if ini else None,
            "lat1": lat1, "lon1": lon1, "lat2": lat2, "lon2": lon2}


# ----------------------------------------------------------------------------------------------- METAR
def parse_vis_m(raw: str) -> int | None:
    """Visibilidad en metros desde el METAR en crudo: grupo de cuatro cifras, o CAVOK (= 10 km o más)."""
    if not raw:
        return None
    cuerpo = re.split(r"\b(?:RMK|TEMPO|BECMG|NOSIG)\b", raw)[0]
    if re.search(r"\bCAVOK\b", cuerpo):
        return 10000
    toks = cuerpo.split()
    for i, t in enumerate(toks):
        if re.fullmatch(r"\d{6}Z", t):           # tras el grupo de hora vienen viento y visibilidad
            toks = toks[i + 1:]
            break
    for t in toks:
        m = re.fullmatch(r"(\d{4})(?:[NSEW]{1,2})?", t)
        if m:
            return int(m.group(1))
        if re.fullmatch(r"(?:Q|A)\d{4}|\d{2}/\d{2}|M?\d{2}/M?\d{2}", t):
            break
    return None


def clase(vis_m, wx: str) -> str:
    wx = wx or ""
    if re.search(r"(?<![A-Z])(?:BC|MI|PR|VC|FZ)?FG\b", wx) or (vis_m is not None and vis_m < UMBRAL_NIEBLA_M):
        return "niebla"
    if re.search(r"(?<![A-Z])BR\b", wx) or (vis_m is not None and vis_m <= UMBRAL_BRUMA_M):
        return "bruma"
    return "despejado"


def _hora_metar(m: dict, ahora: datetime):
    if isinstance(m.get("obsTime"), (int, float)):
        return datetime.fromtimestamp(m["obsTime"], timezone.utc)
    s = str(m.get("reportTime") or "").replace(" ", "T")
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _json_get(url: str, headers: dict | None = None, reintentos: int = 2):
    ultimo = None
    for i in range(reintentos + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:           # noqa: BLE001
            ultimo = e
            if i < reintentos:
                time.sleep(4 * (i + 1))
    raise RuntimeError(f"{type(ultimo).__name__}: {ultimo}")


def leer_metar(datos: list, terr: Territorio, ahora: datetime) -> dict:
    """Último METAR de cada aeródromo, con visibilidad en metros y clase. Descarta lo más viejo de 90 minutos."""
    ult = {}
    for m in datos:
        h = _hora_metar(m, ahora)
        if h and m.get("icaoId") and (m["icaoId"] not in ult or h > ult[m["icaoId"]][0]):
            ult[m["icaoId"]] = (h, m)
    puntos, viejos = [], 0
    for icao, (h, m) in sorted(ult.items()):
        if ahora - h > timedelta(minutes=MAX_EDAD_MIN):
            viejos += 1
            continue
        raw = m.get("rawOb") or ""
        vis = parse_vis_m(raw)
        wx = (m.get("wxString") or "").strip()
        lat, lon = m.get("lat"), m.get("lon")
        if vis is None and not wx:
            continue
        puntos.append({"id": icao, "tipo": "aeropuerto", "nombre": (m.get("name") or icao).split(",")[0].strip(),
                       "lat": lat, "lon": lon, "vis_m": vis, "wx": wx, "clase": clase(vis, wx),
                       "hora": h.astimezone(TZ).strftime("%H:%M"), "provincia_slug": terr.slug_punto(lat, lon)})
    return {"respondidos": sorted(ult), "viejos": viejos, "puntos": puntos}


def pedir_metar() -> list:
    return _json_get(METAR_URL.format(ids=",".join(OACI)))


# ----------------------------------------------------------------------------------------------- AEMET
def _aemet_get(url: str, clave: str | None = None):
    cab = {"Accept": "application/json"}
    if clave:
        cab["api_key"] = clave
    req = urllib.request.Request(url, headers=cab)
    with urllib.request.urlopen(req, timeout=90) as r:
        crudo = r.read()
    try:
        return json.loads(crudo.decode("utf-8"))
    except UnicodeDecodeError:
        return json.loads(crudo.decode("ISO-8859-15", "replace"))


def pedir_aemet() -> list:
    clave = (os.environ.get("AEMET_API_KEY") or "").strip()
    if not clave:
        raise RuntimeError("falta el secreto AEMET_API_KEY")
    ultimo = None
    for i in range(3):
        try:
            r = _aemet_get(AEMET_URL, clave)
            if not isinstance(r, dict) or not r.get("datos"):
                raise RuntimeError(f"respuesta sin datos: {str(r)[:120]}")
            return _aemet_get(r["datos"])
        except Exception as e:           # noqa: BLE001
            ultimo = e
            if i < 2:
                time.sleep(6 * (i + 1))
    raise RuntimeError(f"{type(ultimo).__name__}: {ultimo}")


def _hora_aemet(s) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)      # fint de la observación convencional: UTC


def leer_aemet(datos: list, terr: Territorio, ahora: datetime, diag: dict | None = None) -> dict:
    """Última observación con visibilidad de cada estación (vis en km)."""
    ult, total = {}, set()
    for o in datos:
        est = o.get("idema")
        if not est:
            continue
        total.add(est)
        v, h = o.get("vis"), _hora_aemet(o.get("fint"))
        if v is None or h is None or not isinstance(v, (int, float)) or isinstance(v, bool) or math.isnan(v):
            continue
        if est not in ult or h > ult[est][0]:
            ult[est] = (h, o)
    puntos, viejos = [], 0
    for est, (h, o) in sorted(ult.items()):
        if ahora - h > timedelta(minutes=MAX_EDAD_MIN):
            viejos += 1
            continue
        vis = int(round(o["vis"] * AEMET_VIS_A_M))
        lat, lon = o.get("lat"), o.get("lon")
        puntos.append({"id": est, "tipo": "aemet", "nombre": str(o.get("ubi") or est).title(), "lat": lat, "lon": lon,
                       "vis_m": vis, "wx": "", "clase": clase(vis, ""), "hora": h.astimezone(TZ).strftime("%H:%M"),
                       "provincia_slug": terr.slug_punto(lat, lon)})
    if diag is not None:
        vals = [o["vis"] for _h, o in ult.values()]
        diag.update({"estaciones_en_respuesta": len(total), "estaciones_con_vis": len(ult), "con_vis_reciente": len(puntos),
                     "vis_rango": [min(vals), max(vals)] if vals else None,
                     "ejemplos": [{k: o.get(k) for k in ("idema", "ubi", "fint", "vis", "lat", "lon")}
                                  for _h, o in list(ult.values())[:3]]})
    return {"puntos": puntos, "viejos": viejos, "n_estaciones": len(total)}


# ------------------------------------------------------------------------------------------ provincias
def _lista(xs: list) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " y " + xs[-1]


def _plural(n: int, uno: str, varios: str) -> str:
    return f"{n} {uno if n == 1 else varios}"


def estados(tramos: list, puntos: list, dgt_ok: bool) -> dict:
    """Estado de cada provincia y en qué se apoya."""
    out = {}
    for slug, nombre, _g in PROVINCIAS:
        tr = [t for t in tramos if t["provincia_slug"] == slug]
        pt = [p for p in puntos if p["provincia_slug"] == slug]
        pn = [p for p in pt if p["clase"] == "niebla"]
        pb = [p for p in pt if p["clase"] == "bruma"]
        cubre = dgt_ok and slug not in SIN_DGT
        if tr or pn:
            estado = "niebla"
        elif pb:
            estado = "bruma"
        elif not pt and not cubre:
            estado = "sin_dato"
        else:
            estado = "sin_niebla"
        partes = []
        if tr:
            partes.append(_plural(len(tr), "tramo de la DGT", "tramos de la DGT"))
        for lista, etiqueta in ((pn, "niebla"), (pb, "bruma")):
            if estado == "bruma" and etiqueta == "niebla":
                continue
            aer = [p for p in lista if p["tipo"] == "aeropuerto"]
            est = [p for p in lista if p["tipo"] == "aemet"]
            if aer:
                partes.append(f"el aeropuerto de {aer[0]['nombre']}" if len(aer) == 1 else f"{len(aer)} aeropuertos")
            if est:
                partes.append("una estación de AEMET" if len(est) == 1 else f"{len(est)} estaciones de AEMET")
        if estado in ("niebla", "bruma"):
            apoyo = _lista(partes)
            apoyo = apoyo[0].upper() + apoyo[1:] + (" con bruma" if estado == "bruma" else "")
        elif estado == "sin_niebla":
            fuentes = []
            if cubre:
                fuentes.append("tramos de la DGT")
            if pt:
                fuentes.append(_plural(len(pt), "punto de observación", "puntos de observación"))
            apoyo = "Sin niebla en " + (_lista(fuentes) if fuentes else "los datos disponibles")
        else:
            apoyo = "Sin datos de suelo en esta provincia"
        if slug in SIN_DGT:
            apoyo += f". La DGT no cubre {SIN_DGT[slug]}"
        vis = [p["vis_m"] for p in pt if p["vis_m"] is not None]
        out[slug] = {"estado": estado, "apoyo": apoyo, "tramos": len(tr), "vis_min": min(vis) if vis else None}
    return out


def frase(ahora: datetime, tramos: list, puntos_niebla: int, provincias_con_tramos: int, provincias_niebla: int,
          dgt_ok: bool) -> str:
    t = ahora.astimezone(TZ)
    cuando = f"{'A la' if t.hour == 1 else 'A las'} {t:%H:%M} del {t.day} de {MESES[t.month - 1]}"
    n = len(tramos)
    if n:
        s = (f"{cuando} hay niebla en {_plural(n, 'tramo', 'tramos')} de carretera de "
             f"{_plural(provincias_con_tramos, 'provincia', 'provincias')}")
        if puntos_niebla:
            s += f" y en {_plural(puntos_niebla, 'punto', 'puntos')} de observación"
        return s + "."
    if puntos_niebla:
        return (f"{cuando} hay niebla en {_plural(puntos_niebla, 'punto', 'puntos')} de observación de "
                f"{_plural(provincias_niebla, 'provincia', 'provincias')}.")
    if dgt_ok:
        return f"{cuando} no hay niebla en los tramos de la DGT ni en los aeropuertos y estaciones con datos."
    return f"{cuando} no hay niebla en los aeropuertos y estaciones con datos."


# ----------------------------------------------------------------------------------------------- pasada
def construir(ahora: datetime, dgt: dict | None, metar: dict | None, aemet: dict | None, errores: dict) -> dict:
    tramos = dgt["tramos"] if dgt else []
    puntos = (metar["puntos"] if metar else []) + (aemet["puntos"] if aemet else [])
    dgt_ok = dgt is not None
    provs = estados(tramos, puntos, dgt_ok)
    pn = sum(1 for p in puntos if p["clase"] == "niebla")
    pb = sum(1 for p in puntos if p["clase"] == "bruma")
    pniebla = sum(1 for v in provs.values() if v["estado"] == "niebla")
    con_tramos = len({t["provincia_slug"] for t in tramos if t["provincia_slug"]})
    ordenados = sorted(puntos, key=lambda p: ({"niebla": 0, "bruma": 1, "despejado": 2}[p["clase"]], p["id"]))

    return {
        "version": VERSION,
        "generado": ahora.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "fuentes": {
            "dgt": ({"ok": True, "corte": dgt["corte"], "n": dgt["n_registros"], "tramos": len(tramos)} if dgt else
                    {"ok": False, "corte": None, "n": 0, "error": errores.get("dgt") or "sin datos"}),
            "metar": _fuente_puntos(metar, ahora, errores.get("metar")),
            "aemet": _fuente_puntos(aemet, ahora, errores.get("aemet")),
        },
        "totales": {"tramos": len(tramos), "puntos_niebla": pn, "puntos_bruma": pb, "provincias_niebla": pniebla},
        "frase": frase(ahora, tramos, pn, con_tramos, pniebla, dgt_ok),
        "cobertura": "La DGT no incluye Cataluña ni el País Vasco.",
        "provincias": provs,
        "tramos": tramos,
        "puntos": ordenados,
    }


def _fuente_puntos(d: dict | None, ahora: datetime, err: str | None) -> dict:
    if d is None:
        return {"ok": False, "corte": None, "n": 0, "error": err or "sin datos"}
    horas = [p["hora"] for p in d["puntos"]]
    return {"ok": True, "corte": ahora.astimezone(TZ).isoformat(timespec="seconds"), "ultima_observacion": max(horas) if horas else None,
            "n": len(d["puntos"])}


def firma(datos: dict | None) -> str:
    """Huella del contenido sin la hora: generado, frase, cortes y horas de observación no cuentan."""
    if not datos:
        return ""
    c = json.loads(json.dumps(datos))
    for k in ("generado", "frase"):
        c.pop(k, None)
    for f in c.get("fuentes", {}).values():
        f.pop("corte", None)
        f.pop("ultima_observacion", None)
    for p in c.get("puntos", []):
        p.pop("hora", None)
    return hashlib.sha1(json.dumps(c, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def leer_json(p: Path):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def escribir_hist(datos: dict, ahora: datetime) -> None:
    ARCHIVO.mkdir(parents=True, exist_ok=True)
    t = ahora.astimezone(TZ)
    tot = datos["totales"]
    nuevo = not HIST.exists()
    with open(HIST, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        if nuevo:
            w.writerow(["fecha", "hora", "tramos", "puntos_niebla", "puntos_bruma", "provincias_niebla"])
        w.writerow([t.date().isoformat(), t.strftime("%H:%M"), tot["tramos"], tot["puntos_niebla"], tot["puntos_bruma"],
                    tot["provincias_niebla"]])


def escribir_dia(datos: dict, ahora: datetime) -> None:
    """Una línea por provincia y día con el peor estado del día; se rehace el día de hoy en cada pasada."""
    hoy = ahora.astimezone(TZ).date().isoformat()
    filas = {}
    if DIA.exists():
        with open(DIA, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                filas[(r["fecha"], r["provincia"])] = r
    for slug, p in datos["provincias"].items():
        ant = filas.get((hoy, slug))
        peor = p["estado"]
        tr = p["tramos"]
        vm = p["vis_min"]
        if ant:
            if ORDEN_ESTADO[ant["estado"]] > ORDEN_ESTADO[peor]:
                peor = ant["estado"]
            tr = max(tr, int(ant["tramos_max"] or 0))
            if ant["vis_min_m"]:
                vm = int(ant["vis_min_m"]) if vm is None else min(vm, int(ant["vis_min_m"]))
        filas[(hoy, slug)] = {"fecha": hoy, "provincia": slug, "estado": peor, "tramos_max": tr,
                              "vis_min_m": "" if vm is None else vm}
    ARCHIVO.mkdir(parents=True, exist_ok=True)
    with open(DIA, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, ["fecha", "provincia", "estado", "tramos_max", "vis_min_m"], lineterminator="\n")
        w.writeheader()
        for k in sorted(filas):
            w.writerow(filas[k])


def pasada(ahora: datetime, bajar_dgt=None, bajar_metar=None, bajar_aemet=None, terr: Territorio | None = None,
           salida: Path | None = None) -> tuple:
    """Devuelve (datos, mensaje). Cada fuente va en su try; si fallan todas, se conserva el JSON anterior."""
    terr = terr or Territorio()
    salida = salida or JSON_OUT
    errores, dgt, metar, aemet = {}, None, None, None
    try:
        dgt = leer_dgt((bajar_dgt or (lambda: NP.descargar(DGT_URL)))(), terr, ahora)
    except Exception as e:               # noqa: BLE001
        errores["dgt"] = f"{type(e).__name__}: {e}"
    try:
        metar = leer_metar((bajar_metar or pedir_metar)(), terr, ahora)
    except Exception as e:               # noqa: BLE001
        errores["metar"] = f"{type(e).__name__}: {e}"
    try:
        aemet = leer_aemet((bajar_aemet or pedir_aemet)(), terr, ahora)
        if len(aemet["puntos"]) < 30:
            errores["aemet"] = f"solo {len(aemet['puntos'])} estaciones con visibilidad reciente (mínimo 30)"
            aemet = None
    except Exception as e:               # noqa: BLE001
        errores["aemet"] = f"{type(e).__name__}: {e}"
    previo = leer_json(salida)
    if dgt is None and metar is None and aemet is None:
        return previo, "FALLAN TODAS LAS FUENTES, se conserva el niebla.json anterior: " + "; ".join(errores.values())
    datos = construir(ahora, dgt, metar, aemet, errores)
    resumen = (f"{datos['frase']} fuentes: dgt={'ok' if dgt else 'FALLO'} metar={'ok' if metar else 'FALLO'} "
               f"aemet={'ok' if aemet else 'FALLO/omitida'}")
    if previo and firma(previo) == firma(datos):
        edad = None
        try:
            edad = ahora - datetime.fromisoformat(previo["generado"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            pass
        if edad is not None and edad < timedelta(minutes=KEEPALIVE_MIN):
            return previo, "sin cambios; " + resumen
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(json.dumps(datos, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if salida == JSON_OUT:
        escribir_hist(datos, ahora)
        escribir_dia(datos, ahora)
    return datos, "publicado; " + resumen


# ------------------------------------------------------------------------------------------- diagnóstico
def diagnostico(ahora: datetime) -> None:
    """Modo temporal de la primera pasada: recuentos y tres ejemplos por fuente. Se borra al terminar la tarea."""
    terr = Territorio()
    d: dict = {"generado": ahora.astimezone(timezone.utc).isoformat(timespec="seconds"), "provincias_geojson": len(terr.polis)}
    for nombre, url in (("dgt_v37", DGT_URL), ("dgt_v36", DGT_URL_36)):
        x: dict = {"url": url}
        try:
            b = NP.descargar(url)
            x["bytes"] = len(b)
            leido = leer_dgt(b, terr, ahora, x)
            x["ok"] = True
            x["corte"] = leido["corte"]
            x["ejemplos"] = [{k: t[k] for k in ("id", "carretera", "pk_ini", "pk_fin", "municipio", "provincia", "desde", "lat1",
                                                "lon1", "lat2", "lon2")} for t in leido["tramos"][:3]]
            x["provincias_con_tramos"] = sorted({t["provincia_slug"] for t in leido["tramos"] if t["provincia_slug"]})
        except Exception as e:           # noqa: BLE001
            x.update({"ok": False, "error": f"{type(e).__name__}: {e}"})
        d[nombre] = x
    m: dict = {"pedidos": len(OACI)}
    try:
        datos = pedir_metar()
        leido = leer_metar(datos, terr, ahora)
        resp = set(leido["respondidos"])
        m.update({"ok": True, "filas": len(datos), "respondidos": len(resp), "no_responden": sorted(set(OACI) - resp),
                  "fuera_de_la_lista": sorted(resp - set(OACI)), "viejos_90min": leido["viejos"],
                  "con_niebla": sum(1 for p in leido["puntos"] if p["clase"] == "niebla"),
                  "con_bruma": sum(1 for p in leido["puntos"] if p["clase"] == "bruma"),
                  "sin_provincia": [p["id"] for p in leido["puntos"] if not p["provincia_slug"]],
                  "sin_visibilidad": sum(1 for p in leido["puntos"] if p["vis_m"] is None),
                  "ejemplos": [{k: p[k] for k in ("id", "nombre", "vis_m", "wx", "clase", "hora", "provincia_slug")}
                               for p in leido["puntos"][:3]],
                  "ejemplos_raw": [{"icao": x.get("icaoId"), "rawOb": x.get("rawOb"), "wx": x.get("wxString"),
                                    "reportTime": x.get("reportTime")} for x in datos[:3]]})
    except Exception as e:               # noqa: BLE001
        m.update({"ok": False, "error": f"{type(e).__name__}: {e}"})
    d["metar"] = m
    a: dict = {}
    try:
        datos = pedir_aemet()
        a.update({"ok": True, "registros": len(datos)})
        leer_aemet(datos, terr, ahora, a)
        a["claves_primer_registro"] = sorted(datos[0].keys()) if datos else []
    except Exception as e:               # noqa: BLE001
        a.update({"ok": False, "error": f"{type(e).__name__}: {e}"})
    d["aemet"] = a
    SALIDA.mkdir(parents=True, exist_ok=True)
    DIAG_OUT.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"diagnóstico escrito en {DIAG_OUT}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--diag", action="store_true", help="diagnóstico de la primera pasada (docs/niebla/diag.json)")
    a = ap.parse_args()
    ahora = datetime.now(TZ)
    if a.diag:
        diagnostico(ahora)
        return 0
    datos, msg = pasada(ahora)
    log(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
