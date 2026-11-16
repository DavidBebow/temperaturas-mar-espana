#!/usr/bin/env python3
"""Niebla en España, en directo · generador de docs/niebla/niebla.json (solo biblioteca estándar).

Fuentes de suelo (el satélite lo carga el navegador desde EUMETView, no pasa por aquí):
  DGT      tramos con niebla: registros sit:PoorEnvironmentConditions con poorEnvironmentType = fog (DATEX II v3.7,
           mismo lector que nieve_puertos.py). Sin Cataluña ni País Vasco.
  METAR    aeródromos españoles (aviationweather.gov, por lista de códigos OACI). Visibilidad en metros desde rawOb.
  AEMET    observación convencional (campo vis, km, solo estaciones con sensor). Secreto AEMET_API_KEY.

Uso:  python scripts/niebla.py            pasada normal
"""
from __future__ import annotations

import base64
import csv
import hashlib
import html
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

VERSION = "1.1.0"
RAIZ = Path(os.environ.get("CG_RAIZ") or Path(__file__).resolve().parent.parent)
SALIDA = RAIZ / "docs" / "niebla"
JSON_OUT = SALIDA / "niebla.json"
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
AEMET_VIS_A_M = 1000.0           # vis viene en km (confirmado: rango 0,1-30 en 93 estaciones)
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

# Nombres en español de los aeródromos (el parte los trae en inglés: «Seville/San Pablo Arpt»)
AER = {"GCFV": "Fuerteventura", "GCGM": "La Gomera", "GCHI": "El Hierro", "GCLA": "La Palma", "GCLP": "Gran Canaria",
       "GCRR": "Lanzarote", "GCTS": "Tenerife Sur", "GCXO": "Tenerife Norte", "GECE": "Ceuta (helipuerto)", "GEML": "Melilla",
       "LEAB": "Albacete", "LEAG": "Algeciras (helipuerto)", "LEAL": "Alicante-Elche", "LEAM": "Almería", "LEAS": "Asturias",
       "LEBA": "Córdoba", "LEBB": "Bilbao", "LEBG": "Burgos", "LEBL": "Barcelona-El Prat", "LEBT": "Bétera (Valencia)",
       "LEBZ": "Badajoz", "LECH": "Castellón", "LECO": "A Coruña", "LEDA": "Lleida-Alguaire", "LEGA": "Armilla (Granada)",
       "LEGE": "Girona", "LEGR": "Granada", "LEGT": "Getafe (Madrid)", "LEHC": "Huesca", "LEIB": "Ibiza", "LEJR": "Jerez",
       "LELC": "San Javier (Murcia)", "LELL": "Sabadell", "LELN": "León", "LEMD": "Madrid-Barajas", "LEMG": "Málaga",
       "LEMH": "Menorca", "LEMI": "Región de Murcia", "LEMO": "Morón (Sevilla)", "LEPA": "Palma de Mallorca",
       "LEPP": "Pamplona", "LERI": "Alcantarilla (Murcia)", "LERS": "Reus", "LERT": "Rota (Cádiz)", "LESA": "Salamanca",
       "LESB": "Son Bonet (Mallorca)", "LESO": "San Sebastián", "LEST": "Santiago de Compostela",
       "LETO": "Torrejón (Madrid)", "LEVC": "Valencia", "LEVD": "Valladolid", "LEVS": "Cuatro Vientos (Madrid)",
       "LEVT": "Vitoria", "LEVX": "Vigo", "LEXJ": "Santander", "LEZG": "Zaragoza", "LEZL": "Sevilla"}


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


def leer_dgt(contenido: bytes, terr: Territorio, ahora: datetime) -> dict:
    """Tramos activos con niebla, deduplicados por id (gana la versión más reciente)."""
    corte, vistos, n_reg = None, {}, 0
    for _ev, el in ET.iterparse(io.BytesIO(contenido), events=("end",)):
        n = NP._l(el.tag)
        if n == "publicationTime" and corte is None:
            corte = el.text
        elif n == "situationRecord":
            n_reg += 1
            r = NP._registro(el)
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
        puntos.append({"id": icao, "tipo": "aeropuerto", "nombre": AER.get(icao) or re.sub(r"\s*(Arpt|Arpr|Intl|Heliport)\b|\)$", "", (m.get("name") or icao).split(",")[0]).strip(),
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
    for i in range(5):
        try:
            r = _aemet_get(AEMET_URL, clave)
            if not isinstance(r, dict) or not r.get("datos"):
                raise RuntimeError(f"respuesta sin datos: {str(r)[:120]}")
            return _aemet_get(r["datos"])
        except Exception as e:           # noqa: BLE001
            ultimo = e
            if i < 4:
                time.sleep(10 * (i + 1))
    raise RuntimeError(f"{type(ultimo).__name__}: {ultimo}")


def _hora_aemet(s) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)      # fint de la observación convencional: UTC


def leer_aemet(datos: list, terr: Territorio, ahora: datetime) -> dict:
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


# ------------------------------------------------------------------------------- bloque del día en WordPress
# La página /niebla/ (id 16898) lleva un hueco <div class="cg-ssr-slot">CGSSRSLOT</div>; el snippet cg-ssr-bloque.php
# lo sustituye por el meta cg_ssr_html. Lista cerrada de etiquetas: aquí solo div, p, h2, ul, li, span, b.
WP_API = os.environ.get("WP_API", "https://calentamientoglobal.es/wp-json/wp/v2")
WP_PAGINA = 16898
ANCLA = "CGSSRSLOT"
PUBLICADO = ARCHIVO / "publicado.json"
_MINUS = {"De", "Del", "La", "Las", "Los", "El", "Y", "En"}


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def _nombre(s: str) -> str:
    """'Jerez De Los Caballeros' -> 'Jerez de los Caballeros'."""
    ps = str(s or "").split()
    return " ".join(w.lower() if i and w in _MINUS else w for i, w in enumerate(ps))


def _vis(m) -> str:
    m = int(m)
    if m < 1000:
        return f"{m} m"
    km = m / 1000
    return (f"{km:.1f}".replace(".", ",").replace(",0", "") if km < 10 else str(int(round(km)))) + " km"


def _pk(x) -> str:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return ""
    return str(int(x)) if x == int(x) else f"{x:.1f}".replace(".", ",")


def _fecha(d: datetime, anio: bool = True) -> str:
    return f"{d.day} de {MESES[d.month - 1]}" + (f" de {d.year}" if anio else "")


def _desde(iso: str, ahora: datetime) -> str:
    try:
        d = datetime.fromisoformat(iso).astimezone(TZ)
    except (TypeError, ValueError):
        return ""
    if d.date() == ahora.date():
        return f"desde las {d:%H:%M}"
    return f"desde el {_fecha(d, False)}, {d:%H:%M}"


def ssr(datos: dict) -> str:
    """Bloque del día: cifra del momento, provincias y carreteras. Todo sale de niebla.json."""
    try:
        gen = datetime.fromisoformat(datos["generado"].replace("Z", "+00:00")).astimezone(TZ)
    except (KeyError, ValueError):
        gen = datetime.now(TZ)
    provs, tramos, puntos = datos.get("provincias") or {}, datos.get("tramos") or [], datos.get("puntos") or []
    por = {"niebla": [], "bruma": [], "sin_niebla": [], "sin_dato": []}
    for slug, v in provs.items():
        por.setdefault(v.get("estado") or "sin_dato", []).append((NOMBRE.get(slug, slug), slug, v))
    for k in por:
        por[k].sort(key=lambda z: z[0].lower().replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o")
                    .replace("ú", "u"))
    pn = [q for q in puntos if q.get("clase") == "niebla"]
    n_prov, n_tr = len(por["niebla"]), len(tramos)
    sello = f"A las {gen:%H:%M} del {_fecha(gen)}"

    o = ['<div class="cgnb-hoy"><div class="cgnb-ahora"><p class="cgnb-eyeb">Ahora mismo</p>']
    o.append(f'<p class="cgnb-cifra"><b>{n_prov}</b><span>{"provincia con niebla" if n_prov == 1 else "provincias con niebla"}'
             f'</span></p><ul class="cgnb-kpi">')
    o.append(f'<li><b>{n_tr}</b><span>{"tramo de carretera con niebla" if n_tr == 1 else "tramos de carretera con niebla"}'
             f' (DGT)</span></li>')
    o.append(f'<li><b>{len(pn)}</b><span>{"aeropuerto o estación" if len(pn) == 1 else "aeropuertos y estaciones"} con menos '
             f'de 1 km de visibilidad</span></li>')
    con_vis = [q for q in pn if isinstance(q.get("vis_m"), (int, float))]
    if con_vis:
        q = min(con_vis, key=lambda z: z["vis_m"])
        donde = _nombre(q.get("nombre"))
        pr = NOMBRE.get(q.get("provincia_slug"), "")
        o.append(f'<li><b>{esc(_vis(q["vis_m"]))}</b><span>la visibilidad más baja, en {esc(donde)}'
                 + (f" ({esc(pr)})" if pr and pr.lower() not in donde.lower() else "") + "</span></li>")
    o.append(f'</ul><p class="cgnb-sello">{esc(sello)}</p></div>')

    o.append('<div class="cgnb-prov"><h2>Niebla ahora, provincia a provincia</h2>')
    if por["niebla"]:
        o.append('<ul class="cgnb-pl">')
        for nom, _slug, v in por["niebla"]:
            vm = v.get("vis_min")
            vis = f'<span class="cgnb-vis">{esc(_vis(vm))}</span>' if isinstance(vm, (int, float)) and vm < 5000 else ""
            o.append(f'<li><b>{esc(nom)}</b>{vis}<span class="cgnb-ap">{esc(v.get("apoyo") or "")}</span></li>')
        o.append("</ul>")
    else:
        o.append(f'<p class="cgnb-nada">{esc(sello)} no hay niebla en ninguna provincia, según los tramos de la DGT, '
                 f'los aeropuertos y las estaciones de AEMET.</p>')
    for clave, rot in (("bruma", "Con bruma"), ("sin_niebla", "Sin niebla"), ("sin_dato", "Sin dato de suelo")):
        if por[clave]:
            o.append(f'<p class="cgnb-resto cgnb-r-{clave}"><b>{rot} ({len(por[clave])})</b> '
                     f'{esc(", ".join(n for n, _s, _v in por[clave]))}.</p>')
    o.append("</div>")

    o.append('<div class="cgnb-vias"><h2>Carreteras con niebla ahora</h2>')
    if tramos:
        o.append('<ul class="cgnb-vl">')
        for t in sorted(tramos, key=lambda z: (z.get("provincia") or "", z.get("carretera") or "", z.get("pk_ini") or 0)):
            a, b = _pk(t.get("pk_ini")), _pk(t.get("pk_fin"))
            km = f"km {a} a {b}" if a and b and a != b else (f"km {a or b}" if (a or b) else "")
            lugar = ", ".join(x for x in (t.get("municipio"), t.get("provincia")) if x)
            o.append(f'<li><b>{esc(t.get("carretera") or "Carretera")}</b><span class="cgnb-km">{esc(km)}</span>'
                     f'<span class="cgnb-lu">{esc(lugar)}</span>'
                     f'<span class="cgnb-de">{esc(_desde(t.get("desde"), gen))}</span></li>')
        o.append("</ul>")
    elif (datos.get("fuentes") or {}).get("dgt", {}).get("ok"):
        o.append(f'<p class="cgnb-nada">{esc(sello)} la DGT no tiene ningún tramo de carretera con niebla.</p>')
    else:
        o.append('<p class="cgnb-nada">El dato de carreteras de la DGT no está disponible en esta pasada.</p>')
    o.append(f'<p class="cgnb-pie2">Fuente: DGT, incidencias activas. No incluye Cataluña ni el País Vasco. '
             f'{esc(sello)}; el estado de una carretera cambia en minutos.</p></div></div>')
    return "".join(o)


def publicar(datos: dict, forzar: bool = False) -> str:
    """Escribe el bloque del día en la página. Nunca tumba la pasada."""
    usuario, clave = os.environ.get("WP_USER"), os.environ.get("WP_APP_PASSWORD")
    if not usuario or not clave:
        return "bloque del día: sin WP_USER / WP_APP_PASSWORD, no se publica"
    bloque = ssr(datos)
    hs = hashlib.sha256(bloque.encode("utf-8")).hexdigest()[:16]
    reg = leer_json(PUBLICADO) or {}
    if not forzar and reg.get("hs") == hs:
        return "bloque del día: sin cambios"
    cuerpo = json.dumps({"meta": {"cg_ssr_html": bloque, "cg_ssr_anchor": ANCLA}}).encode()
    aut = "Basic " + base64.b64encode(f"{usuario}:{clave}".encode()).decode()
    ultimo = None
    for i in range(3):
        req = urllib.request.Request(f"{WP_API}/pages/{WP_PAGINA}", data=cuerpo, method="POST", headers={
            "Authorization": aut, "Content-Type": "application/json", "Accept": "application/json", "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                res = json.loads(r.read().decode("utf-8") or "null") or {}
            if not ((res.get("meta") or {}).get("cg_ssr_html") or ""):
                return "bloque del día: AVISO, WordPress no ha guardado el meta cg_ssr_html"
            ARCHIVO.mkdir(parents=True, exist_ok=True)
            PUBLICADO.write_text(json.dumps({"id": WP_PAGINA, "hs": hs, "actualizado": datos.get("generado")}),
                                 encoding="utf-8")
            return f"bloque del día: publicado ({len(bloque)} caracteres)"
        except Exception as e:           # noqa: BLE001
            ultimo = e
            if i < 2:
                time.sleep(8 * (i + 1))
    return f"bloque del día: ERROR {type(ultimo).__name__}: {ultimo}"


def main() -> int:
    ahora = datetime.now(TZ)
    datos, msg = pasada(ahora)
    log(msg)
    if datos:
        try:
            log(publicar(datos, forzar="--forzar" in sys.argv))
        except Exception as e:           # noqa: BLE001
            log(f"bloque del día: ERROR {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
