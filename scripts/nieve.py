#!/usr/bin/env python3
"""Nieve en España · calentamientoglobal.es  (v1.1.0: primera nevada, SEO con Keyword Planner)

Qué hace
  Vigila la nieve en España con tres fuentes abiertas y gratuitas y con ellas escribe la página /nieve/ y una página
  hija por provincia (/nieve/<provincia>/), igual que /heladas/:
    1. Nieve caída y espesor de nieve, día a día desde 1971, en 106 puntos: la capital de cada provincia, su montaña
       de referencia (puerto o estación de esquí) y unas cuantas estaciones de esquí más de los grandes macizos.
       Reanálisis ERA5-Land (Copernicus/ECMWF) por la API de archivo de Open-Meteo. Da la temporada en curso, lo normal
       (1991-2021) y si nieva menos que antes (1971-1990 frente a 2006-2025).
    2. Superficie nevada vista por satélite: el producto diario IMS de 4 km de la NOAA (NSIDC G02156), que combina
       satélites ópticos y de microondas. Da qué parte de España, de cada provincia y de cada macizo está blanca hoy, y
       cómo era en la misma fecha de los inviernos desde 2005.
    3. Previsión de nevadas y cota de nieve a 15 días con cuatro modelos: ECMWF (Centro Europeo), ICON (DWD, Alemania),
       AROME/ARPEGE (Météo-France) y GFS (NOAA), por la API de previsión de Open-Meteo.

Salidas
  archivo/nieve/era5land/<punto>/historico.csv.gz   ERA5-Land de 1971-08-01 a 2025-07-31 (se baja una vez, por tandas)
  archivo/nieve/era5land/<punto>/reciente.csv       ERA5-Land desde el 1 de agosto de 2025 (se refresca cada pasada)
  archivo/nieve/satelite.csv                        % nevado de España, cada provincia y cada macizo, día a día (IMS)
  docs/nieve/index.json                             resumen nacional (macizos, provincias, satélite, previsión)
  docs/nieve/<provincia>.json / .csv                detalle de una provincia y sus temporadas, para descargar
  docs/nieve/satelite.csv                           la serie del satélite, para descargar
  docs/nieve/publicado.json                         registro de lo publicado en WordPress

Modos
  python scripts/nieve.py --clima [--presupuesto 1000]   baja por tandas la serie larga de ERA5-Land (pesada)
  python scripts/nieve.py --satelite                     añade los últimos días del satélite IMS
  python scripts/nieve.py --satelite-historico --desde 2005 --max 500   rellena inviernos pasados del satélite
  python scripts/nieve.py                                refresca ERA5-Land reciente + previsión y escribe docs/nieve/
  python scripts/nieve.py --publicar [--forzar]          además publica en WordPress (WP_USER, WP_APP_PASSWORD)
  python scripts/nieve.py --vista DIR                    deja el HTML de cada página en DIR para revisarlo
  python scripts/nieve.py --demo --vista DIR             datos simulados, sin red (solo para revisar el diseño)

Definiciones
  nieve caída         centímetros de nieve nueva (Open-Meteo pasa el agua equivalente a nieve con 7 cm por cada 10 mm)
  día de nieve        día con 1 cm o más de nieve caída
  espesor             máximo del día del espesor de nieve en el suelo
  temporada AAAA-AA   del 1 de agosto de AAAA al 31 de julio siguiente; cuenta si tiene el 95 % de los días
  normal              temporadas 1991-92 a 2020-21 (hacen falta 24 válidas)
  cambio              1971-1990 frente a 2006-2025 (16 temporadas válidas en cada tramo); es un cambio real solo si la
                      tendencia lineal desde 1971 tiene t >= 2
  cota de nieve       300 m por debajo de la isoterma de 0 °C en las horas con precipitación (si un modelo no da la
                      isoterma, se estima con la temperatura a 850 hPa)
Sin dependencias: solo la biblioteca estándar.
"""
from __future__ import annotations

import argparse
import base64
import csv
import gzip
import hashlib
import html
import json
import math
import os
import random
import statistics as st
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "1.3.0"
RAIZ = Path(os.environ.get("CG_RAIZ") or Path(__file__).resolve().parent.parent)
ARCHIVO = RAIZ / "archivo" / "nieve"
ERA = ARCHIVO / "era5land"
SAT_CSV = ARCHIVO / "satelite.csv"                 # lo reciente (lo escribe nieve.yml)
SAT_HIST = ARCHIVO / "satelite_historico.csv"     # inviernos pasados (lo escribe nieve-satelite-historico.yml)
CELDAS = ARCHIVO / "ims_celdas.json"
GEOJSON = ARCHIVO / "provincias.geojson"
CACHE_PREV = ARCHIVO / "prevision.json"
SALIDA = RAIZ / "docs" / "nieve"
PUBLICADO = SALIDA / "publicado.json"
WEB = "https://calentamientoglobal.es"
PAGES = "https://davidbebow.github.io/temperaturas-mar-espana"
API = os.environ.get("WP_API", WEB + "/wp-json/wp/v2")
TZ = ZoneInfo("Europe/Madrid")
AHORA = datetime.now(timezone.utc)
HOY = AHORA.astimezone(TZ).date()
PLANTILLA = "page-templates/no-wrapper.php"
ANCLA = "CGSSRSLOT"
UA = "calentamientoglobal.es/nieve (+https://calentamientoglobal.es/nieve/)"

OM_ARCHIVO = "https://archive-api.open-meteo.com/v1/archive"
OM_PREVISION = "https://api.open-meteo.com/v1/forecast"
GEOJSON_URL = ("https://raw.githubusercontent.com/codeforgermany/click_that_hood/main/public/data/"
               "spain-provinces.geojson")
IMS_URL = "https://noaadata.apps.nsidc.org/NOAA/G02156/4km/{y}/ims{y}{d:03d}_00UTC_4km_v{v}.asc.gz"

INICIO = date(1971, 8, 1)
CORTE = date(2025, 8, 1)          # lo anterior va a historico.csv.gz; lo posterior, a reciente.csv
TANDAS = [(date(1971, 8, 1), date(1989, 7, 31)), (date(1989, 8, 1), date(2007, 7, 31)),
          (date(2007, 8, 1), date(2025, 7, 31))]
NORMAL = (1991, 2020)
TRAMO1 = (1971, 1990)
TRAMO2 = (2006, 2025)
MIN_NORMAL = 24
MIN_TRAMO = 16
COBERTURA = 0.95
UMBRAL_DIA = 1.0                  # cm de nieve nueva para contar un día de nieve
SAT_DESDE = 2005                  # primer invierno completo del IMS de 4 km

MODELOS = [  # id de Open-Meteo, nombre corto, quién lo hace, alcance en días
    ("ecmwf_ifs025", "ECMWF", "Centro Europeo (ECMWF)", 15),
    ("icon_seamless", "ICON", "Servicio Meteorológico Alemán (DWD)", 7),
    ("meteofrance_seamless", "ARPEGE", "Météo-France", 4),
    ("gfs_seamless", "GFS", "NOAA, Estados Unidos", 16),
]

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]
DIAS_SEM = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
DIAS_C = ["lu", "ma", "mi", "ju", "vi", "sá", "do"]
REF = date(2021, 8, 1)

# --------------------------------------------------------------------------------------------------------- lugares
# slug web, provincia, nombre en el GeoJSON, capital (lat, lon, m), montaña de referencia (nombre, lat, lon, m), macizo
PROVINCIAS = [
    ("a-coruna", "A Coruña", "A Coruña", ("A Coruña", 43.362, -8.411, 30), ("Serra do Careón", 42.870, -8.010, 750), "galaico"),
    ("alava", "Álava", "Araba/Álava", ("Vitoria", 42.847, -2.672, 525), ("Gorbea", 43.035, -2.780, 1400), "vasco"),
    ("albacete", "Albacete", "Albacete", ("Albacete", 38.994, -1.858, 686), ("Calar del Mundo", 38.530, -2.390, 1600), "beticas"),
    ("alicante", "Alicante", "Alacant/Alicante", ("Alicante", 38.345, -0.481, 10), ("Sierra de Aitana", 38.650, -0.270, 1500), "beticas"),
    ("almeria", "Almería", "Almería", ("Almería", 36.834, -2.464, 20), ("Calar Alto", 37.220, -2.550, 2100), "nevada"),
    ("asturias", "Asturias", "Asturias", ("Oviedo", 43.361, -5.849, 230), ("Valgrande-Pajares", 42.985, -5.780, 1600), "cantabrica"),
    ("avila", "Ávila", "Ávila", ("Ávila", 40.656, -4.700, 1130), ("Sierra de Gredos", 40.270, -5.230, 1900), "central"),
    ("badajoz", "Badajoz", "Badajoz", ("Badajoz", 38.879, -6.970, 186), ("Sierra de Tentudía", 38.050, -6.330, 1100), "morena"),
    ("baleares", "Baleares", "Illes Balears", ("Palma", 39.570, 2.650, 20), ("Serra de Tramuntana (Lluc)", 39.810, 2.840, 1100), "tramuntana"),
    ("barcelona", "Barcelona", "Barcelona", ("Barcelona", 41.389, 2.170, 15), ("Montseny", 41.780, 2.440, 1600), "pirineo"),
    ("bizkaia", "Bizkaia", "Bizkaia/Vizcaya", ("Bilbao", 43.263, -2.935, 20), ("Puerto de Urkiola", 43.100, -2.645, 710), "vasco"),
    ("burgos", "Burgos", "Burgos", ("Burgos", 42.344, -3.697, 860), ("Sierra de la Demanda", 42.170, -3.170, 1600), "iberica"),
    ("caceres", "Cáceres", "Cáceres", ("Cáceres", 39.475, -6.372, 440), ("Sierra de Tormantos", 40.220, -5.620, 1600), "central"),
    ("cadiz", "Cádiz", "Cádiz", ("Cádiz", 36.527, -6.289, 10), ("Sierra de Grazalema", 36.760, -5.370, 1100), "beticas"),
    ("cantabria", "Cantabria", "Cantabria", ("Santander", 43.462, -3.810, 15), ("Alto Campoo", 43.030, -4.380, 1900), "cantabrica"),
    ("castellon", "Castellón", "Castelló/Castellón", ("Castellón", 39.986, -0.051, 30), ("Penyagolosa", 40.220, -0.350, 1600), "iberica"),
    ("ciudad-real", "Ciudad Real", "Ciudad Real", ("Ciudad Real", 38.985, -3.927, 630), ("Sierra Madrona", 38.430, -4.050, 1200), "morena"),
    ("cordoba", "Córdoba", "Córdoba", ("Córdoba", 37.888, -4.779, 120), ("Sierras Subbéticas", 37.420, -4.210, 1400), "beticas"),
    ("cuenca", "Cuenca", "Cuenca", ("Cuenca", 40.070, -2.137, 950), ("Serranía de Cuenca (Tragacete)", 40.360, -1.820, 1500), "iberica"),
    ("gipuzkoa", "Gipuzkoa", "Gipuzkoa/Guipúzcoa", ("San Sebastián", 43.318, -1.981, 10), ("Sierra de Aralar", 42.990, -2.080, 1200), "vasco"),
    ("girona", "Girona", "Girona", ("Girona", 41.979, 2.821, 75), ("La Molina", 42.330, 1.940, 1900), "pirineo"),
    ("granada", "Granada", "Granada", ("Granada", 37.177, -3.599, 690), ("Sierra Nevada (Pradollano)", 37.095, -3.395, 2500), "nevada"),
    ("guadalajara", "Guadalajara", "Guadalajara", ("Guadalajara", 40.633, -3.167, 690), ("Sierra de Ayllón", 41.140, -3.300, 1700), "central"),
    ("huelva", "Huelva", "Huelva", ("Huelva", 37.261, -6.945, 20), ("Sierra de Aracena", 37.900, -6.550, 900), "morena"),
    ("huesca", "Huesca", "Huesca", ("Huesca", 42.140, -0.409, 490), ("Formigal", 42.775, -0.375, 2000), "pirineo"),
    ("jaen", "Jaén", "Jaén", ("Jaén", 37.779, -3.785, 570), ("Sierra de Cazorla", 37.900, -2.950, 1700), "beticas"),
    ("leon", "León", "León", ("León", 42.599, -5.567, 840), ("San Isidro", 43.060, -5.360, 1700), "cantabrica"),
    ("lleida", "Lleida", "Lleida", ("Lleida", 41.617, 0.620, 155), ("Baqueira", 42.700, 0.930, 2000), "pirineo"),
    ("lugo", "Lugo", "Lugo", ("Lugo", 43.012, -7.556, 465), ("Os Ancares", 42.850, -6.850, 1600), "galaico"),
    ("madrid", "Madrid", "Madrid", ("Madrid", 40.416, -3.703, 650), ("Puerto de Navacerrada", 40.785, -4.005, 1900), "central"),
    ("malaga", "Málaga", "Málaga", ("Málaga", 36.721, -4.421, 15), ("Sierra de las Nieves", 36.680, -5.000, 1600), "beticas"),
    ("murcia", "Murcia", "Murcia", ("Murcia", 37.992, -1.131, 45), ("Sierra de Revolcadores", 38.070, -2.270, 1800), "beticas"),
    ("navarra", "Navarra", "Navarra", ("Pamplona", 42.812, -1.646, 450), ("Belagua", 42.950, -0.800, 1500), "pirineo"),
    ("ourense", "Ourense", "Ourense", ("Ourense", 42.336, -7.864, 130), ("Manzaneda", 42.270, -7.260, 1600), "galaico"),
    ("palencia", "Palencia", "Palencia", ("Palencia", 42.010, -4.533, 750), ("Montaña Palentina", 42.980, -4.600, 1700), "cantabrica"),
    ("las-palmas", "Las Palmas", "Las Palmas", ("Las Palmas de Gran Canaria", 28.124, -15.430, 10), ("Pico de las Nieves", 27.960, -15.570, 1900), "canarias"),
    ("pontevedra", "Pontevedra", "Pontevedra", ("Pontevedra", 42.431, -8.645, 20), ("Serra do Faro", 42.620, -7.950, 1100), "galaico"),
    ("la-rioja", "La Rioja", "La Rioja", ("Logroño", 42.466, -2.445, 385), ("Valdezcaray", 42.240, -3.000, 1800), "iberica"),
    ("salamanca", "Salamanca", "Salamanca", ("Salamanca", 40.965, -5.664, 800), ("La Covatilla", 40.360, -5.710, 2000), "central"),
    ("santa-cruz-de-tenerife", "Santa Cruz de Tenerife", "Santa Cruz De Tenerife",
     ("Santa Cruz de Tenerife", 28.469, -16.254, 10), ("Las Cañadas del Teide (Izaña)", 28.309, -16.499, 2370), "canarias"),
    ("segovia", "Segovia", "Segovia", ("Segovia", 40.948, -4.118, 1000), ("La Pinilla", 41.200, -3.470, 1800), "central"),
    ("sevilla", "Sevilla", "Sevilla", ("Sevilla", 37.389, -5.984, 10), ("Sierra Norte de Sevilla", 37.950, -5.700, 800), "morena"),
    ("soria", "Soria", "Soria", ("Soria", 41.764, -2.465, 1060), ("Sierra de Urbión", 42.000, -2.880, 1800), "iberica"),
    ("tarragona", "Tarragona", "Tarragona", ("Tarragona", 41.119, 1.245, 30), ("Els Ports", 40.800, 0.300, 1200), "iberica"),
    ("teruel", "Teruel", "Teruel", ("Teruel", 40.344, -1.107, 915), ("Javalambre", 40.100, -1.010, 1900), "iberica"),
    ("toledo", "Toledo", "Toledo", ("Toledo", 39.863, -4.027, 530), ("Montes de Toledo", 39.420, -4.700, 1200), "morena"),
    ("valencia", "Valencia", "València/Valencia", ("Valencia", 39.470, -0.376, 15), ("Rincón de Ademuz", 40.100, -1.200, 1500), "iberica"),
    ("valladolid", "Valladolid", "Valladolid", ("Valladolid", 41.652, -4.724, 690), ("Montes Torozos", 41.800, -4.950, 850), "duero"),
    ("zamora", "Zamora", "Zamora", ("Zamora", 41.503, -5.744, 650), ("Sierra de la Cabrera (Sanabria)", 42.130, -6.700, 1600), "cantabrica"),
    ("zaragoza", "Zaragoza", "Zaragoza", ("Zaragoza", 41.649, -0.889, 200), ("Moncayo", 41.790, -1.840, 1800), "iberica"),
]
# estaciones de esquí y puertos que completan los macizos: id, nombre, lat, lon, m, macizo, provincia
EXTRAS = [
    ("candanchu", "Candanchú", 42.788, -0.528, 1900, "pirineo", "huesca"),
    ("cerler", "Cerler", 42.560, 0.540, 2100, "pirineo", "huesca"),
    ("port-aine", "Port Ainé", 42.430, 1.210, 2000, "pirineo", "lleida"),
    ("leitariegos", "Leitariegos", 42.995, -6.420, 1600, "cantabrica", "leon"),
    ("valdelinares", "Valdelinares", 40.390, -0.620, 1900, "iberica", "teruel"),
    ("valdesqui", "Valdesquí", 40.800, -3.960, 2000, "central", "madrid"),
]
MACIZOS = {
    "pirineo": ("Pirineo", "de Navarra al Montseny"),
    "cantabrica": ("Cordillera Cantábrica", "de Sanabria a Alto Campoo"),
    "iberica": ("Sistema Ibérico", "de la Demanda a Javalambre y el Maestrazgo"),
    "central": ("Sistema Central", "de Gredos a Ayllón"),
    "nevada": ("Sierra Nevada y Penibético", "Granada y Almería"),
    "beticas": ("Sierras Béticas", "de Grazalema a Cazorla, Segura y Revolcadores"),
    "galaico": ("Macizo Galaico", "Manzaneda, Ancares y las sierras gallegas"),
    "vasco": ("Montes Vascos", "Gorbea, Aralar y Urkiola"),
    "morena": ("Sierra Morena y Montes de Toledo", "las sierras del sur de la Meseta"),
    "canarias": ("Canarias", "el Teide y la cumbre de Gran Canaria"),
    "tramuntana": ("Serra de Tramuntana", "Mallorca"),
}
ORDEN_MACIZOS = ["pirineo", "cantabrica", "iberica", "central", "nevada", "beticas", "galaico", "vasco", "morena",
                 "canarias", "tramuntana"]


def puntos() -> list:
    out = []
    for slug, prov, _g, cap, mon, mac in PROVINCIAS:
        out.append({"id": f"{slug}-monte", "nombre": mon[0], "tipo": "monte", "lat": mon[1], "lon": mon[2], "alt": mon[3],
                    "prov": slug, "provincia": prov, "macizo": mac})
    for i, n, la, lo, al, mac, prov in EXTRAS:
        out.append({"id": i, "nombre": n, "tipo": "esqui", "lat": la, "lon": lo, "alt": al, "prov": prov,
                    "provincia": next(p[1] for p in PROVINCIAS if p[0] == prov), "macizo": mac})
    for slug, prov, _g, cap, mon, mac in PROVINCIAS:
        out.append({"id": f"{slug}-capital", "nombre": cap[0], "tipo": "capital", "lat": cap[1], "lon": cap[2],
                    "alt": cap[3], "prov": slug, "provincia": prov, "macizo": None})
    return out


PUNTOS = puntos()
P_ID = {p["id"]: p for p in PUNTOS}


# ---------------------------------------------------------------------------------------------------------- utilidades
def log(m: str) -> None:
    print(m, flush=True)


def leer_json(p: Path, defecto):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return defecto


def escribir(p: Path, texto: str) -> bool:
    """Escribe solo si cambia (así el commit no se llena de archivos idénticos)."""
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        if p.read_text(encoding="utf-8") == texto:
            return False
    except OSError:
        pass
    p.write_text(texto, encoding="utf-8")
    return True


def num(x: float, dec: int = 1) -> str:
    s = f"{x:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def entero(x: float) -> str:
    return num(round(x), 0)


def cm(x: float) -> str:
    if x is None:
        return "—"
    return (entero(x) if x >= 10 or abs(x - round(x)) < 0.05 else num(x)) + " cm"


def pct(x: float) -> str:
    return (num(x, 0) if x >= 10 or x == 0 else num(x)) + " %"


def fecha_larga(d: date, anio: bool = True) -> str:
    return f"{d.day} de {MESES[d.month - 1]}" + (f" de {d.year}" if anio else "")


def dia_semana(d: date) -> str:
    return DIAS_SEM[d.weekday()]


def indice(d: date) -> int:
    """Día de la temporada, de 0 (1 de agosto) a 364 (31 de julio); el 29 de febrero cuenta como el 28."""
    m, dd = d.month, d.day
    if m == 2 and dd == 29:
        dd = 28
    y = REF.year if m >= 8 else REF.year + 1
    return (date(y, m, dd) - REF).days


def fecha_de_indice(i: float) -> date:
    return REF + timedelta(days=int(round(i)))


def dia_mes(i: float) -> str:
    f = fecha_de_indice(i)
    return f"{f.day} de {MESES[f.month - 1]}"


def temporada_de(d: date) -> int:
    return d.year if d.month >= 8 else d.year - 1


def temporada(y: int) -> str:
    return f"{y}-{str(y + 1)[-2:]}"


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def percentil(xs: list, p: float):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * p
    a, b = math.floor(k), math.ceil(k)
    return xs[a] + (xs[b] - xs[a]) * (k - a)


def tendencia(pares: list) -> tuple:
    """Pendiente por década y estadístico t de una regresión lineal simple."""
    n = len(pares)
    if n < 10:
        return None, None
    xs = [a for a, _ in pares]
    ys = [b for _, b in pares]
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None, None
    b = sum((x - mx) * (y - my) for x, y in pares) / sxx
    a = my - b * mx
    res = sum((y - (a + b * x)) ** 2 for x, y in pares)
    if n <= 2 or res == 0:
        return b * 10, None
    se = math.sqrt(res / (n - 2) / sxx)
    return b * 10, (b / se if se else None)


def lista(xs) -> str:
    xs = list(xs)
    if len(xs) <= 1:
        return "".join(xs)
    return ", ".join(xs[:-1]) + " y " + xs[-1]


def suave(xs: list, v: int = 3) -> list:
    out = []
    for i in range(len(xs)):
        tramo = [x for x in xs[max(0, i - v):i + v + 1] if x is not None]
        out.append(sum(tramo) / len(tramo) if tramo else None)
    return out


# ------------------------------------------------------------------------------------------------------- Open-Meteo
class Limite(Exception):
    """Open-Meteo dice que se ha llegado al límite de peticiones gratuitas: se para y se sigue en la próxima pasada."""


def peso(dias: int, variables: int, lugares: int = 1, modelos: int = 1) -> float:
    """Lo que cuenta Open-Meteo por petición (más de 14 días o de 10 variables cuentan como varias)."""
    return max(1.0, dias / 14) * max(1.0, variables * modelos / 10) * lugares


def om(url: str, params: dict, intentos: int = 4):
    q = urllib.parse.urlencode(params, safe=",:")
    full = f"{url}?{q}"
    for i in range(intentos):
        req = urllib.request.Request(full, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            cuerpo = e.read().decode("utf-8", "replace")[:300]
            if e.code == 429:
                if "inute" in cuerpo and i < intentos - 1:
                    time.sleep(65)
                    continue
                raise Limite(cuerpo) from None
            if e.code in (500, 502, 503, 504) and i < intentos - 1:
                time.sleep(15 * (i + 1))
                continue
            raise RuntimeError(f"HTTP {e.code} {url}: {cuerpo}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if i < intentos - 1:
                time.sleep(15 * (i + 1))
                continue
            raise RuntimeError(f"{type(e).__name__} {url}: {e}") from None


def era_descargar(pts: list, d0: date, d1: date) -> dict:
    """ERA5-Land diario de varios puntos: {id: {fecha: (nieve_cm, espesor_cm)}}."""
    p = {"latitude": ",".join(f"{x['lat']:.3f}" for x in pts), "longitude": ",".join(f"{x['lon']:.3f}" for x in pts),
         "start_date": d0.isoformat(), "end_date": d1.isoformat(), "daily": "snowfall_sum", "hourly": "snow_depth",
         "timezone": "Europe/Madrid"}   # mezcla ERA5-Land/ERA5 de Open-Meteo (con «era5_land» no da la nieve caída)
    r = om(OM_ARCHIVO, p)
    if isinstance(r, dict):
        r = [r]
    if "models" in p and r and all(not any(v is not None for v in (x.get("daily") or {}).get("snowfall_sum") or [])
                                    for x in r):
        log(f"  AVISO: ERA5-Land no da nieve para {d0}-{d1}; se prueba con la mezcla ERA5/ERA5-Land de Open-Meteo")
        p.pop("models")
        r = om(OM_ARCHIVO, p)
        if isinstance(r, dict):
            r = [r]
    out = {}
    for x, res in zip(pts, r):
        dd = res.get("daily") or {}
        hh = res.get("hourly") or {}
        nieve = dict(zip(dd.get("time") or [], dd.get("snowfall_sum") or []))
        esp = {}
        for t, v in zip(hh.get("time") or [], hh.get("snow_depth") or []):
            if v is None:
                continue
            f = t[:10]
            esp[f] = max(esp.get(f, 0.0), v * 100)
        serie = {}
        for f, n in nieve.items():
            if n is None and f not in esp:
                continue
            serie[f] = (None if n is None else round(n, 2), None if f not in esp else round(esp[f], 1))
        out[x["id"]] = serie
        if not serie:
            log(f"  AVISO {x['id']}: ERA5-Land sin datos entre {d0} y {d1} (claves: {list(res)[:8]})")
    return out


def era_leer(pid: str) -> dict:
    """La serie de un punto: {fecha: (nieve, espesor)} con lo histórico y lo reciente."""
    out = {}
    d = ERA / pid
    for nombre in ("historico.csv.gz", "reciente.csv"):
        f = d / nombre
        if not f.exists():
            continue
        abre = gzip.open if nombre.endswith(".gz") else open
        with abre(f, "rt", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                n = row.get("nieve")
                e = row.get("espesor")
                out[row["fecha"]] = (float(n) if n not in ("", None) else None, float(e) if e not in ("", None) else None)
    return out


def era_guardar(pid: str, serie: dict, parte: str) -> None:
    d = ERA / pid
    d.mkdir(parents=True, exist_ok=True)
    filas = ["fecha,nieve,espesor"]
    for f in sorted(serie):
        if (parte == "historico") != (f < CORTE.isoformat()):
            continue
        n, e = serie[f]
        filas.append(f"{f},{'' if n is None else n},{'' if e is None else e}")
    txt = "\n".join(filas) + "\n"
    if parte == "historico":
        with gzip.open(d / "historico.csv.gz", "wt", encoding="utf-8", compresslevel=9) as fh:
            fh.write(txt)
    else:
        escribir(d / "reciente.csv", txt)


def era_estado() -> dict:
    return leer_json(ARCHIVO / "era5land_estado.json", {})


def modo_clima(presupuesto: float) -> None:
    """Baja, por tandas de 18 años, la serie 1971-2025 de los puntos que aún no la tienen. Las montañas van primero."""
    est = era_estado()
    gastado = 0.0
    hechas = 0
    for p in PUNTOS:
        e = est.setdefault(p["id"], {})
        for d0, d1 in TANDAS:
            k = d0.isoformat()
            if e.get(k):
                continue
            w = peso((d1 - d0).days + 1, 2)
            if gastado + w > presupuesto:
                log(f"Presupuesto de la pasada agotado ({gastado:.0f} de {presupuesto:.0f}); sigue en la próxima")
                return _clima_fin(est, hechas)
            try:
                nuevo = era_descargar([p], d0, d1)[p["id"]]
            except Limite as ex:
                log(f"Límite de Open-Meteo alcanzado: {ex}; sigue en la próxima pasada")
                return _clima_fin(est, hechas)
            except RuntimeError as ex:
                log(f"  ERROR {p['id']} {d0}: {ex}")
                continue
            validos = sum(1 for v in nuevo.values() if v[0] is not None)
            if validos < 0.9 * ((d1 - d0).days + 1):
                log(f"  AVISO {p['id']} {d0}-{d1}: solo {validos} días con nieve; no se marca como hecha")
                continue
            serie = era_leer(p["id"])
            serie.update(nuevo)
            era_guardar(p["id"], serie, "historico")
            e[k] = AHORA.isoformat()[:19]
            gastado += w
            hechas += 1
            log(f"  {p['id']}: {d0.year}-{d1.year} ({validos} días)")
            escribir(ARCHIVO / "era5land_estado.json", json.dumps(est, indent=1, sort_keys=True))
            time.sleep(w / 9)   # no pasar de unas 600 por minuto
    _clima_fin(est, hechas)


def _clima_fin(est: dict, hechas: int) -> None:
    escribir(ARCHIVO / "era5land_estado.json", json.dumps(est, indent=1, sort_keys=True))
    total = len(PUNTOS) * len(TANDAS)
    hecho = sum(1 for p in PUNTOS for d0, _ in TANDAS if (est.get(p["id"]) or {}).get(d0.isoformat()))
    log(f"Serie larga: {hechas} tandas nuevas; {hecho} de {total} hechas ({100 * hecho / total:.0f} %)")
    if hecho == total:
        marcar_completo()


def marcar_completo() -> None:
    """Avisa al workflow (salida «completa=true») para que se desactive solo: ya no hace falta gastar ejecuciones."""
    log("COMPLETO: no queda nada por bajar")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write("completa=true\n")


def clima_completa(pid: str) -> bool:
    e = era_estado().get(pid) or {}
    return all(e.get(d0.isoformat()) for d0, _ in TANDAS)


def actualizar_reciente() -> None:
    """ERA5-Land desde el 1 de agosto de 2025 (o los últimos 25 días si ya está) de todos los puntos, por lotes."""
    lote, n = [], 0
    for p in PUNTOS:
        serie = era_leer(p["id"])
        hay = [f for f, v in serie.items() if f >= CORTE.isoformat() and v[0] is not None]
        d0 = max(CORTE, date.fromisoformat(max(hay)) - timedelta(days=25)) if hay else CORTE
        lote.append((p, d0))
    # agrupa por fecha de inicio para pedir varios puntos a la vez
    grupos = {}
    for p, d0 in lote:
        grupos.setdefault(d0, []).append(p)
    for d0, ps in sorted(grupos.items()):
        # Open-Meteo admite unas 600 «peticiones» por minuto: cada lote pesa días/14 por punto, así que se ajusta
        w1 = peso((HOY - d0).days + 1, 2)
        n_lote = max(1, min(20, int(400 // w1)))
        for i in range(0, len(ps), n_lote):
            trozo = ps[i:i + n_lote]
            try:
                nuevo = era_descargar(trozo, d0, HOY)
            except Limite as ex:
                log(f"Límite de Open-Meteo en ERA5-Land reciente: {ex}")
                return
            except RuntimeError as ex:
                log(f"  ERROR ERA5-Land reciente ({trozo[0]['id']}…): {ex}")
                continue
            for p in trozo:
                serie = era_leer(p["id"])
                for f, v in nuevo.get(p["id"], {}).items():
                    if v[0] is not None or f not in serie:
                        serie[f] = v
                era_guardar(p["id"], serie, "reciente")
                n += 1
            time.sleep(max(2, w1 * len(trozo) / 9))
    log(f"ERA5-Land reciente: {n} puntos al día")


# -------------------------------------------------------------------------------------------------------- previsión
def descargar_prevision() -> dict:
    """15 días de los cuatro modelos y los últimos 10 días de ECMWF (para tapar el retraso de ERA5-Land)."""
    out = {"generado": AHORA.isoformat()[:19] + "Z", "puntos": {}, "runs": {}}
    mods = ",".join(m[0] for m in MODELOS)
    for i in range(0, len(PUNTOS), 20):
        trozo = PUNTOS[i:i + 20]
        p = {"latitude": ",".join(f"{x['lat']:.3f}" for x in trozo),
             "longitude": ",".join(f"{x['lon']:.3f}" for x in trozo),
             "elevation": ",".join(str(x["alt"]) for x in trozo),
             "daily": "snowfall_sum,precipitation_sum,temperature_2m_max,temperature_2m_min,wind_gusts_10m_max",
             "hourly": "freezing_level_height,temperature_850hPa,precipitation,snow_depth",
             "models": mods, "forecast_days": 16, "past_days": 10, "timezone": "Europe/Madrid"}
        try:
            r = om(OM_PREVISION, p)
        except Limite as ex:
            log(f"Límite de Open-Meteo en la previsión: {ex}")
            break
        except RuntimeError as ex:
            log(f"  ERROR previsión ({trozo[0]['id']}…): {ex}")
            continue
        if isinstance(r, dict):
            r = [r]
        for x, res in zip(trozo, r):
            out["puntos"][x["id"]] = recortar_prevision(res)
        time.sleep(15)   # cada lote pesa unas 120 peticiones: así no se pasa de 600 por minuto
    log(f"Previsión: {len(out['puntos'])} de {len(PUNTOS)} puntos")
    return out


def recortar_prevision(res: dict) -> dict:
    """De la respuesta de Open-Meteo, lo que hace falta por modelo y día: nieve, lluvia, máx, mín, cota y espesor."""
    dd, hh = res.get("daily") or {}, res.get("hourly") or {}
    dias = dd.get("time") or []
    hts = hh.get("time") or []
    out = {"dias": dias, "m": {}}
    for mid, _n, _o, _a in MODELOS:
        sf = dd.get(f"snowfall_sum_{mid}") or [None] * len(dias)
        pr = dd.get(f"precipitation_sum_{mid}") or [None] * len(dias)
        tx = dd.get(f"temperature_2m_max_{mid}") or [None] * len(dias)
        tn = dd.get(f"temperature_2m_min_{mid}") or [None] * len(dias)
        rv = dd.get(f"wind_gusts_10m_max_{mid}") or [None] * len(dias)
        fl = hh.get(f"freezing_level_height_{mid}") or [None] * len(hts)
        t8 = hh.get(f"temperature_850hPa_{mid}") or [None] * len(hts)
        hp = hh.get(f"precipitation_{mid}") or [None] * len(hts)
        sd = hh.get(f"snow_depth_{mid}") or [None] * len(hts)
        cota, esp = {}, {}
        for t, a, b, c, e in zip(hts, fl, t8, hp, sd):
            f = t[:10]
            if e is not None:
                esp[f] = max(esp.get(f, 0.0), e * 100)
            if c is None or c < 0.2:
                continue
            iso = a if a is not None else (None if b is None else 1500 + 154 * b)
            if iso is None:
                continue
            cota[f] = min(cota.get(f, 99999), iso - 300)
        out["m"][mid] = {
            "n": [None if v is None else round(v, 1) for v in sf],
            "ll": [None if v is None else round(v, 1) for v in pr],
            "tx": [None if v is None else round(v, 1) for v in tx],
            "tn": [None if v is None else round(v, 1) for v in tn],
            "rv": [None if v is None else round(v) for v in rv],
            "cota": [None if f not in cota else max(0, int(round(cota[f] / 100.0) * 100)) for f in dias],
            "esp": [None if f not in esp else round(esp[f], 1) for f in dias],
        }
        if all(v is None for v in out["m"][mid]["n"]):
            del out["m"][mid]
    return out


# --------------------------------------------------------------------------------------------------------- satélite
# IMS 4 km: rejilla de 6144 x 6144 celdas en estereográfica polar norte (verdadera a 60° N, meridiano central 80° O).
# Valores: 0 fuera del disco, 1 mar, 2 tierra sin nieve, 3 hielo marino, 4 nieve. La orientación de las filas se
# comprueba con puntos de control (Sáhara, Groenlandia, Atlántico…) en cada archivo, para no depender de una suposición.
IMS_N = 6144
IMS_PASO = 4000.0
IMS_X0 = -12288000.0
IMS_A, IMS_B = 6378137.0, 6356752.314245
IMS_E = math.sqrt(1 - (IMS_B / IMS_A) ** 2)
IMS_LON0 = math.radians(-80.0)
IMS_LATC = math.radians(60.0)


def _t(phi: float) -> float:
    s = IMS_E * math.sin(phi)
    return math.tan(math.pi / 4 - phi / 2) / ((1 - s) / (1 + s)) ** (IMS_E / 2)


IMS_MC = math.cos(IMS_LATC) / math.sqrt(1 - (IMS_E * math.sin(IMS_LATC)) ** 2)
IMS_TC = _t(IMS_LATC)


def ims_xy(lat: float, lon: float) -> tuple:
    phi, lam = math.radians(lat), math.radians(lon)
    rho = IMS_A * IMS_MC * _t(phi) / IMS_TC
    return rho * math.sin(lam - IMS_LON0), -rho * math.cos(lam - IMS_LON0)


def ims_latlon(x: float, y: float) -> tuple:
    rho = math.hypot(x, y)
    t = rho * IMS_TC / (IMS_A * IMS_MC)
    phi = math.pi / 2 - 2 * math.atan(t)
    for _ in range(8):
        s = IMS_E * math.sin(phi)
        phi = math.pi / 2 - 2 * math.atan(t * ((1 - s) / (1 + s)) ** (IMS_E / 2))
    lam = IMS_LON0 + math.atan2(x, -y)
    return math.degrees(phi), (math.degrees(lam) + 540) % 360 - 180


def ims_celda(lat: float, lon: float) -> tuple:
    """(fila contada desde arriba, columna contada desde la izquierda) en la orientación de referencia."""
    x, y = ims_xy(lat, lon)
    return int((-IMS_X0 - y) // IMS_PASO), int((x - IMS_X0) // IMS_PASO)


ORIENTACIONES = [(fv, fh, tr) for tr in (False, True) for fv in (False, True) for fh in (False, True)]


def ims_rc(fr: int, co: int, ori: tuple) -> tuple:
    fv, fh, tr = ori
    if tr:
        fr, co = co, fr
    if fv:
        fr = IMS_N - 1 - fr
    if fh:
        co = IMS_N - 1 - co
    return fr, co


CONTROL = [((23.0, 10.0), "2"), ((25.0, 29.0), "2"), ((20.0, 78.0), "2"), ((35.0, -40.0), "1"), ((38.5, 5.0), "1"),
           ((15.0, -150.0), "1"), ((30.0, -60.0), "1"), ((75.0, -40.0), "4"), ((72.0, -38.0), "4"),
           ((40.0, -4.0), "24"), ((55.0, 90.0), "24"), ((40.0, -100.0), "24")]


def ims_orientacion(filas: list) -> tuple:
    mejor, puntos_mejor = None, -1
    for ori in ORIENTACIONES:
        ok = 0
        for (la, lo), vale in CONTROL:
            r, c = ims_rc(*ims_celda(la, lo), ori)
            if 0 <= r < IMS_N and 0 <= c < IMS_N and filas[r][c] in vale:
                ok += 1
        if ok > puntos_mejor:
            mejor, puntos_mejor = ori, ok
    return mejor, puntos_mejor


def ims_leer(datos: bytes) -> list:
    txt = gzip.decompress(datos).decode("ascii", "replace")
    filas = []
    for linea in txt.splitlines():
        s = linea.strip().replace(" ", "")
        if len(s) >= IMS_N and set(s[:IMS_N]) <= set("01234"):
            filas.append(s[:IMS_N])
    if len(filas) != IMS_N:
        raise RuntimeError(f"IMS: {len(filas)} filas de datos (se esperaban {IMS_N})")
    return filas


def descargar(url: str, intentos: int = 3) -> bytes | None:
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if i == intentos - 1:
                raise RuntimeError(f"HTTP {e.code} {url}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if i == intentos - 1:
                raise RuntimeError(f"{type(e).__name__} {url}: {e}") from None
        time.sleep(10 * (i + 1))
    return None


def ims_archivo(d: date) -> bytes | None:
    """El archivo del día D+1 a las 00 UTC es el análisis del día D (su cabecera dice «Julian day … D»)."""
    f = d + timedelta(days=1)
    doy = f.timetuple().tm_yday
    for v in ("1.3", "1.2", "1.1"):
        b = descargar(IMS_URL.format(y=f.year, d=doy, v=v))
        if b:
            return b
    return None


def _geojson() -> dict:
    g = leer_json(GEOJSON, None)
    if g:
        return g
    b = descargar(GEOJSON_URL)
    if not b:
        raise RuntimeError("No se pudo bajar el GeoJSON de provincias")
    GEOJSON.parent.mkdir(parents=True, exist_ok=True)
    GEOJSON.write_bytes(b)
    return json.loads(b.decode("utf-8"))


def _anillos(geom: dict) -> list:
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    return geom["coordinates"]


def _dentro(lon: float, lat: float, poligono: list) -> bool:
    dentro = False
    for k, anillo in enumerate(poligono):
        d = False
        n = len(anillo)
        j = n - 1
        for i in range(n):
            xi, yi = anillo[i][0], anillo[i][1]
            xj, yj = anillo[j][0], anillo[j][1]
            if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-15) + xi:
                d = not d
            j = i
        if k == 0:
            dentro = d
        elif d:
            return False
    return dentro


def _simplificar(anillo: list, paso: float = 0.015) -> list:
    out = [anillo[0]]
    for pt in anillo[1:]:
        if abs(pt[0] - out[-1][0]) + abs(pt[1] - out[-1][1]) >= paso:
            out.append(pt)
    return out if len(out) >= 4 else anillo


def ims_celdas() -> dict:
    """Celdas IMS (en la orientación de referencia) de cada provincia y de cada macizo. Se calcula una vez."""
    c = leer_json(CELDAS, None)
    if c and c.get("v") == 1:
        return c
    g = _geojson()
    por_nombre = {f["properties"]["name"]: f["geometry"] for f in g["features"]}
    geoms = {}
    for slug, _p, gname, *_ in PROVINCIAS:
        geom = por_nombre.get(gname)
        if not geom:
            raise RuntimeError(f"Provincia {gname} no está en el GeoJSON")
        polys = [[_simplificar(an) for an in pl] for pl in _anillos(geom)]
        lons = [pt[0] for pl in polys for pt in pl[0]]
        lats = [pt[1] for pl in polys for pt in pl[0]]
        geoms[slug] = (polys, (min(lons), min(lats), max(lons), max(lats)))
    # rejilla de búsqueda: todas las celdas cuyo centro cae en la caja de la península, Baleares o Canarias
    cajas = [(-9.6, 35.8, 4.5, 44.0), (-18.4, 27.4, -13.2, 29.5)]
    celdas = set()
    for lo0, la0, lo1, la1 in cajas:
        la = la0
        while la <= la1:
            lo = lo0
            while lo <= lo1:
                celdas.add(ims_celda(la, lo))
                lo += 0.02
            la += 0.02
    prov = {s: [] for s in geoms}
    for r, co in sorted(celdas):
        x = IMS_X0 + (co + 0.5) * IMS_PASO
        y = -IMS_X0 - (r + 0.5) * IMS_PASO
        la, lo = ims_latlon(x, y)
        for slug, (polys, (a, b, cc, d)) in geoms.items():
            if a <= lo <= cc and b <= la <= d and any(_dentro(lo, la, pl) for pl in polys):
                prov[slug].append([r, co])
                break
    for slug in prov:
        log(f"  celdas IMS {slug}: {len(prov[slug])}")
    mac = {}
    for m in MACIZOS:
        cs = set()
        for p in PUNTOS:
            if p["macizo"] != m:
                continue
            r0, c0 = ims_celda(p["lat"], p["lon"])
            for dr in range(-4, 5):
                for dc in range(-4, 5):
                    if dr * dr + dc * dc <= 16:   # unos 16 km alrededor de cada punto de montaña
                        cs.add((r0 + dr, c0 + dc))
        mac[m] = sorted([list(x) for x in cs])
    c = {"v": 1, "provincias": prov, "macizos": mac}
    escribir(CELDAS, json.dumps(c, separators=(",", ":")))
    return c


def ims_resumen(filas: list, ori: tuple, celdas: dict) -> dict:
    def frac(cs):
        nieve = tierra = 0
        for r, c in cs:
            rr, cc = ims_rc(r, c, ori)
            v = filas[rr][cc]
            if v == "4":
                nieve += 1
                tierra += 1
            elif v == "2":
                tierra += 1
        return (round(100 * nieve / tierra, 2) if tierra >= 3 else None), nieve, tierra
    out = {}
    tn = tt = 0
    for slug, cs in celdas["provincias"].items():
        f, n, t = frac(cs)
        out[slug] = f
        tn += n
        tt += t
    out["espana"] = round(100 * tn / tt, 2) if tt else None
    out["espana_km2"] = round(tn * 16 / 1.29)   # celda de 4 km en la proyección; en España, unos 12,4 km² reales
    for m, cs in celdas["macizos"].items():
        out["m_" + m] = frac(cs)[0]
    return out


def sat_leer(solo: Path | None = None) -> dict:
    out = {}
    for f in ([solo] if solo else [SAT_HIST, SAT_CSV]):
        if not f.exists():
            continue
        with open(f, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                out[row["fecha"]] = {k: (float(v) if v not in ("", None) else None) for k, v in row.items()
                                     if k != "fecha"}
    return out


def sat_columnas() -> list:
    return ["espana", "espana_km2"] + [p[0] for p in PROVINCIAS] + ["m_" + m for m in ORDEN_MACIZOS]


def sat_guardar(datos: dict, destino: Path = SAT_CSV) -> None:
    cols = sat_columnas()
    filas = [",".join(["fecha"] + cols)]
    for f in sorted(datos):
        filas.append(",".join([f] + ["" if datos[f].get(c) is None else f"{datos[f][c]:g}" for c in cols]))
    escribir(destino, "\n".join(filas) + "\n")


def modo_satelite(fechas: list, limite_s: float = 3000, destino: Path = SAT_CSV) -> None:
    celdas = ims_celdas()
    todo = sat_leer()
    datos = sat_leer(destino)
    t0 = time.time()
    hechas = 0
    for d in fechas:
        if d.isoformat() in todo:
            continue
        if time.time() - t0 > limite_s:
            log("Tiempo de la pasada agotado; el resto, en la próxima")
            break
        try:
            b = ims_archivo(d)
        except RuntimeError as e:
            log(f"  ERROR IMS {d}: {e}")
            continue
        if not b:
            log(f"  IMS {d}: aún no publicado")
            continue
        try:
            filas = ims_leer(b)
        except RuntimeError as e:
            log(f"  ERROR IMS {d}: {e}")
            continue
        ori, ok = ims_orientacion(filas)
        if ok < len(CONTROL) - 2:
            log(f"  ERROR IMS {d}: solo {ok} de {len(CONTROL)} puntos de control casan; no se usa")
            continue
        datos[d.isoformat()] = ims_resumen(filas, ori, celdas)
        hechas += 1
        log(f"  IMS {d}: {datos[d.isoformat()]['espana']} % de España nevado (orientación {ori}, control {ok}/"
            f"{len(CONTROL)})")
        if hechas % 20 == 0:
            sat_guardar(datos, destino)
    sat_guardar(datos, destino)
    log(f"Satélite: {hechas} días nuevos, {len(datos)} en total")


def fechas_historico(desde: int, maximo: int) -> list:
    """Días de octubre a mayo de los inviernos pasados que faltan, del más reciente al más antiguo."""
    datos = sat_leer()
    out = []
    for y in range(temporada_de(HOY) - 1, desde - 1, -1):
        d = date(y, 10, 1)
        while d <= date(y + 1, 5, 31):
            if d.isoformat() not in datos:
                out.append(d)
            d += timedelta(days=1)
    return out[:maximo]


# --------------------------------------------------------------------------------------------------------- cálculo
def series_temporada(serie: dict) -> dict:
    """{temporada: {"n": [nieve por índice], "e": [espesor por índice], "cob": cobertura}}."""
    t = {}
    for f, (n, e) in serie.items():
        d = date.fromisoformat(f)
        if d < INICIO:
            continue
        y = temporada_de(d)
        x = t.setdefault(y, {"n": [None] * 365, "e": [None] * 365})
        i = indice(d)
        if n is not None:
            x["n"][i] = n if x["n"][i] is None else max(x["n"][i], n)
        if e is not None:
            x["e"][i] = e if x["e"][i] is None else max(x["e"][i], e)
    for y, x in t.items():
        x["cob"] = sum(1 for v in x["n"] if v is not None) / 365
    return t


def acumulado(ns: list) -> list:
    s, out = 0.0, []
    for v in ns:
        s += v or 0.0
        out.append(round(s, 1))
    return out


def calcular_punto(p: dict, prev: dict) -> dict:
    serie = era_leer(p["id"])
    ts = series_temporada(serie)
    ya = temporada_de(HOY)
    ihoy = indice(HOY)
    validas = {y: x for y, x in ts.items() if x["cob"] >= COBERTURA and y < ya}
    x = {"id": p["id"], "nombre": p["nombre"], "tipo": p["tipo"], "alt": p["alt"], "lat": p["lat"], "lon": p["lon"],
         "prov": p["prov"], "provincia": p["provincia"], "macizo": p["macizo"], "completo": clima_completa(p["id"])}
    # temporadas
    temps = {}
    for y, t in sorted(validas.items()):
        ns = [v or 0.0 for v in t["n"]]
        dias = sum(1 for v in ns if v >= UMBRAL_DIA)
        es = [v for v in t["e"] if v is not None]
        dias_suelo = sum(1 for v in es if v >= 1)
        temps[y] = {"total": round(sum(ns), 1), "dias": dias, "dias_suelo": dias_suelo,
                    "max_dia": round(max(ns), 1), "max_espesor": round(max(es), 1) if es else None,
                    "hasta_hoy": acumulado(ns)[ihoy],
                    "primera": next((i for i, v in enumerate(ns) if v >= UMBRAL_DIA), None),
                    "ultima": next((i for i in range(364, -1, -1) if ns[i] >= UMBRAL_DIA), None)}
    x["_temps"] = temps
    x["_ts"] = ts
    # climatología
    norm = [y for y in temps if NORMAL[0] <= y <= NORMAL[1]]
    clima = {"n": len(norm)}
    if len(norm) >= MIN_NORMAL:
        acs = [acumulado([v or 0.0 for v in validas[y]["n"]]) for y in norm]
        clima["acum_media"] = [round(sum(a[i] for a in acs) / len(acs), 1) for i in range(365)]
        clima["acum_p10"] = [round(percentil([a[i] for a in acs], 0.1), 1) for i in range(365)]
        clima["acum_p90"] = [round(percentil([a[i] for a in acs], 0.9), 1) for i in range(365)]
        esp = []
        for i in range(365):
            vs = [validas[y]["e"][i] for y in norm if validas[y]["e"][i] is not None]
            esp.append(percentil(vs, 0.5) if vs else None)
        clima["esp_mediana"] = [None if v is None else round(v, 1) for v in suave(esp, 3)]
        clima["total"] = round(st.mean(temps[y]["total"] for y in norm), 1)
        clima["dias"] = round(st.mean(temps[y]["dias"] for y in norm), 1)
        clima["dias_suelo"] = round(st.mean(temps[y]["dias_suelo"] for y in norm), 1)
        clima["con_nieve"] = sum(1 for y in norm if temps[y]["dias"] > 0)
        # día de la temporada con más probabilidad de nevar (para "cuándo nieva")
        prob = []
        for i in range(365):
            prob.append(sum(1 for y in norm if (validas[y]["n"][i] or 0) >= UMBRAL_DIA) / len(norm))
        prob = suave(prob, 7)
        clima["prob"] = [round(v, 3) for v in prob]
        tot = sum(prob)
        if tot > 0:
            c = 0
            for i, v in enumerate(prob):
                c += v
                if "p10" not in clima and c >= 0.1 * tot:
                    clima["p10"] = i
                if "p50" not in clima and c >= 0.5 * tot:
                    clima["p50"] = i
                if "p90" not in clima and c >= 0.9 * tot:
                    clima["p90"] = i
        d = clima["dias"]
        clima["tipo"] = ("frecuente" if d >= 4 else "ocasional" if clima["con_nieve"] >= 0.3 * len(norm) else "rara")
    x["clima"] = clima
    # cambio
    t1 = [temps[y] for y in temps if TRAMO1[0] <= y <= TRAMO1[1]]
    t2 = [temps[y] for y in temps if TRAMO2[0] <= y <= TRAMO2[1]]
    cambio = {}
    if len(t1) >= MIN_TRAMO and len(t2) >= MIN_TRAMO:
        for k in ("total", "dias", "dias_suelo"):
            a, b = st.mean(v[k] for v in t1), st.mean(v[k] for v in t2)
            pend, tt = tendencia([(y, temps[y][k]) for y in sorted(temps)])
            cambio[k] = {"t1": round(a, 1), "t2": round(b, 1), "pct": round(100 * (b - a) / a, 0) if a > 0.5 else None,
                         "decada": None if pend is None else round(pend, 2), "t": None if tt is None else round(tt, 2)}
    # primera y última nevada: solo donde nieva casi todos los años (si no, la mediana engaña)
    con = [y for y in norm if temps[y]["primera"] is not None]
    if len(norm) >= MIN_NORMAL and len(con) >= 0.8 * len(norm):
        pr = [temps[y]["primera"] for y in con]
        ul = [temps[y]["ultima"] for y in con]
        clima["primera"] = round(st.median(pr))
        clima["primera_p10"], clima["primera_p90"] = round(percentil(pr, 0.1)), round(percentil(pr, 0.9))
        clima["ultima"] = round(st.median(ul))
        clima["ultima_p10"], clima["ultima_p90"] = round(percentil(ul, 0.1)), round(percentil(ul, 0.9))
        for k in ("primera", "ultima"):
            a = [temps[y][k] for y in temps if TRAMO1[0] <= y <= TRAMO1[1] and temps[y][k] is not None]
            b = [temps[y][k] for y in temps if TRAMO2[0] <= y <= TRAMO2[1] and temps[y][k] is not None]
            if len(a) >= MIN_TRAMO and len(b) >= MIN_TRAMO:
                pend, tt = tendencia([(y, temps[y][k]) for y in sorted(temps) if temps[y][k] is not None])
                cambio[k] = {"t1": round(st.median(a)), "t2": round(st.median(b)), "dias": round(st.median(b) - st.median(a)),
                             "decada": None if pend is None else round(pend, 1), "t": None if tt is None else round(tt, 2)}
        if cambio.get("primera") and cambio.get("ultima"):
            d1 = cambio["ultima"]["t1"] - cambio["primera"]["t1"]
            d2 = cambio["ultima"]["t2"] - cambio["primera"]["t2"]
            cambio["duracion"] = {"t1": d1, "t2": d2, "dias": d2 - d1}
    x["cambio"] = cambio
    # récords
    rec = {}
    if temps:
        ymax = max(temps, key=lambda y: temps[y]["total"])
        ymin = min(temps, key=lambda y: temps[y]["total"])
        rec["temporada_max"] = {"t": temporada(ymax), "cm": temps[ymax]["total"]}
        rec["temporada_min"] = {"t": temporada(ymin), "cm": temps[ymin]["total"]}
        best = max(((f, v[0]) for f, v in serie.items() if v[0] is not None), key=lambda z: z[1], default=None)
        if best and best[1] >= UMBRAL_DIA:
            rec["dia_max"] = {"f": best[0], "cm": round(best[1], 1)}
        bese = max(((f, v[1]) for f, v in serie.items() if v[1] is not None), key=lambda z: z[1], default=None)
        if bese and bese[1] >= 1:
            rec["espesor_max"] = {"f": bese[0], "cm": round(bese[1], 0)}
        ult = max((f for f, v in serie.items() if v[0] is not None and v[0] >= UMBRAL_DIA), default=None)
        if ult:
            rec["ultima"] = {"f": ult, "cm": round(serie[ult][0], 1)}
        rec["desde"] = min(temps)
        rec["temporadas"] = len(temps)
    x["records"] = rec
    # esta temporada: ERA5-Land validado y, para los últimos días, ECMWF (provisional)
    t = ts.get(ya) or {"n": [None] * 365, "e": [None] * 365}
    ns = list(t["n"][:ihoy + 1])
    es = list(t["e"][:ihoy + 1])
    ultimo_era = max((i for i, v in enumerate(ns) if v is not None), default=None)
    pv = (prev.get("puntos") or {}).get(p["id"])
    provisional_desde = None
    if pv and "ecmwf_ifs025" in pv["m"]:
        m = pv["m"]["ecmwf_ifs025"]
        for f, v, e in zip(pv["dias"], m["n"], m["esp"]):
            d = date.fromisoformat(f)
            if d > HOY or temporada_de(d) != ya:
                continue
            i = indice(d)
            if ns[i] is None and v is not None:
                ns[i] = v
                provisional_desde = min(provisional_desde or f, f)
            if e is not None and (es[i] is None or i > (ultimo_era or -1)):
                es[i] = e
    o = {"desde": date(ya, 8, 1).isoformat(), "hasta": HOY.isoformat(),
         "era_hasta": None if ultimo_era is None else fecha_de_indice_temp(ya, ultimo_era).isoformat(),
         "provisional_desde": provisional_desde}
    nn = [v or 0.0 for v in ns]
    o["acum"] = round(sum(nn), 1)
    o["serie"] = acumulado(nn)
    o["dias"] = sum(1 for v in nn if v >= UMBRAL_DIA)
    o["ult7"] = round(sum(nn[-7:]), 1)
    o["ult1"] = round(nn[-1], 1) if nn else 0.0
    o["esp"] = next((round(v, 0) for v in reversed(es) if v is not None), None)
    o["esp_serie"] = [None if v is None else round(v, 0) for v in es]
    ult = max((i for i, v in enumerate(nn) if v >= UMBRAL_DIA), default=None)
    o["ultima"] = None if ult is None else fecha_de_indice_temp(ya, ult).isoformat()
    pri = next((i for i, v in enumerate(nn) if v >= UMBRAL_DIA), None)
    o["primera"] = None if pri is None else fecha_de_indice_temp(ya, pri).isoformat()
    if clima.get("acum_media"):
        o["normal"] = clima["acum_media"][ihoy]
        o["esp_normal"] = clima["esp_mediana"][ihoy]
        # puesto entre todas las temporadas a esta misma altura
        a_esta = [v["hasta_hoy"] for v in temps.values()]
        o["puesto"] = 1 + sum(1 for v in a_esta if v > o["acum"])
        o["de"] = len(a_esta) + 1
    x["temporada"] = o
    # previsión
    x["prevision"] = prevision_punto(pv)
    return x


def fecha_de_indice_temp(y: int, i: int) -> date:
    f = fecha_de_indice(i)
    return date(y if f.month >= 8 else y + 1, f.month, f.day)


def prevision_punto(pv: dict | None) -> dict:
    if not pv:
        return {"dias": [], "modelos": {}}
    dias = []
    idx = []
    for k, f in enumerate(pv["dias"]):
        if date.fromisoformat(f) >= HOY:
            dias.append(f)
            idx.append(k)
    dias, idx = dias[:16], idx[:16]
    mods = {}
    for mid, nombre, _o, alc in MODELOS:
        m = pv["m"].get(mid)
        if not m:
            continue
        mods[mid] = {k: [(m.get(k) or [None] * len(m["n"]))[j] for j in idx] for k in ("n", "ll", "tx", "tn", "cota", "rv")}
    cons, cota_c, vistos, txc, tnc, rvc, llc = [], [], [], [], [], [], []
    med = lambda k, j, dec=1: (lambda vs: round(st.median(vs), dec) if vs else None)(
        [mods[mid][k][j] for mid in mods if mods[mid][k][j] is not None])
    for j in range(len(dias)):
        vs = [mods[mid]["n"][j] for mid in mods if mods[mid]["n"][j] is not None]
        cs = [mods[mid]["cota"][j] for mid in mods if mods[mid]["cota"][j] is not None]
        cons.append(round(st.median(vs), 1) if vs else None)
        cota_c.append(int(st.median(cs)) // 100 * 100 if cs else None)
        vistos.append(sum(1 for v in vs if v >= UMBRAL_DIA))
        txc.append(med("tx", j)); tnc.append(med("tn", j)); rvc.append(med("rv", j, 0)); llc.append(med("ll", j))
    return {"dias": dias, "modelos": mods, "consenso": cons, "cota": cota_c, "vistos": vistos,
            "tx": txc, "tn": tnc, "racha": rvc, "precip": llc,
            "total7": round(sum(v or 0 for v in cons[:7]), 1), "total15": round(sum(v or 0 for v in cons[:15]), 1),
            "max_modelo15": round(max((sum(v or 0 for v in mods[mid]["n"][:15]) for mid in mods), default=0), 1)}


def calcular_sat(sat: dict) -> dict:
    """Hoy y lo normal (mediana de los inviernos desde 2005) del % nevado, nacional, por provincia y por macizo."""
    if not sat:
        return {}
    ultima = max(sat)
    d = date.fromisoformat(ultima)
    i = indice(d)
    ya = temporada_de(d)
    por_t = {}
    for f, v in sat.items():
        dd = date.fromisoformat(f)
        por_t.setdefault(temporada_de(dd), {})[indice(dd)] = v
    out = {"fecha": ultima, "hoy": sat[ultima], "normal": {}, "inviernos": sorted(y for y in por_t if y != ya),
           "max_temporada": None}
    pasadas = [y for y in por_t if y != ya]
    for k in sat_columnas():
        vs = []
        for y in pasadas:
            ventana = [por_t[y].get(j, {}).get(k) for j in range(i - 3, i + 4)]
            ventana = [v for v in ventana if v is not None]
            if ventana:
                vs.append(sum(ventana) / len(ventana))
        out["normal"][k] = round(percentil(vs, 0.5), 2) if len(vs) >= 5 else None
    # serie de esta temporada y bandas por día (solo España), para el gráfico del hub
    serie = [None] * 365
    for j, v in (por_t.get(ya) or {}).items():
        serie[j] = v.get("espana")
    out["serie"] = serie
    med, p10, p90 = [], [], []
    for j in range(365):
        vs = [por_t[y][j]["espana"] for y in pasadas if j in por_t[y] and por_t[y][j].get("espana") is not None]
        med.append(percentil(vs, 0.5) if len(vs) >= 5 else None)
        p10.append(percentil(vs, 0.1) if len(vs) >= 5 else None)
        p90.append(percentil(vs, 0.9) if len(vs) >= 5 else None)
    out["med"], out["p10"], out["p90"] = suave(med, 3), suave(p10, 3), suave(p90, 3)
    hoyes = [v for v in serie if v is not None]
    if hoyes:
        jm = max(range(365), key=lambda j: serie[j] if serie[j] is not None else -1)
        out["max_temporada"] = {"pct": serie[jm], "f": fecha_de_indice_temp(ya, jm).isoformat()}
    # récord de cada invierno
    rec = []
    for y in pasadas:
        vs = [(j, v.get("espana")) for j, v in por_t[y].items() if v.get("espana") is not None]
        if len(vs) > 150:
            j, v = max(vs, key=lambda z: z[1])
            rec.append({"t": temporada(y), "pct": v, "f": fecha_de_indice_temp(y, j).isoformat()})
    out["max_inviernos"] = sorted(rec, key=lambda r: -r["pct"])[:5]
    return out


# ----------------------------------------------------------------------------------------------------------- gráficos
# Paleta «noche de nieve», la misma familia que /heladas/: azul noche de fondo y la nieve brilla en blanco; la brasa
# marca hoy y esta temporada.
TINTA = "#e8f1f8"
GRIS = "#8fa9bd"
FONDO = "#163a55"
REJILLA = "#2a4a63"
BRASA = "#ff7a45"
NIEVE = [(0.0, (31, 77, 112)), (0.25, (58, 127, 179)), (0.5, (140, 198, 238)), (0.75, (212, 238, 255)),
         (1.0, (255, 255, 255))]
MESES_EJE = [(8, "ago"), (9, "sep"), (10, "oct"), (11, "nov"), (12, "dic"), (1, "ene"), (2, "feb"), (3, "mar"), (4, "abr"),
             (5, "may"), (6, "jun"), (7, "jul")]
I_OCT, I_JUN = indice(date(2021, 10, 1)), indice(date(2022, 6, 30))


def color_nieve(p: float) -> str:
    p = max(0.0, min(1.0, p))
    for (a, ca), (b, cb) in zip(NIEVE, NIEVE[1:]):
        if p <= b:
            f = (p - a) / (b - a)
            return "#%02x%02x%02x" % tuple(round(ca[k] + f * (cb[k] - ca[k])) for k in range(3))
    return "#ffffff"


def escala_cm(v: float) -> float:
    """0-1 para colorear centímetros de nieve nueva: 1 cm ya se ve, 30 cm o más es blanco."""
    if not v or v < 0.5:
        return 0.0
    return min(1.0, 0.18 + 0.82 * math.log1p(v) / math.log1p(30))


def _rango_temporada(c: dict) -> tuple:
    """Días del eje: de octubre a junio, o más si en esa montaña nieva antes o después."""
    lo, hi = I_OCT, I_JUN
    if c.get("p10") is not None:
        lo = min(lo, max(0, c["p10"] - 20))
        hi = max(hi, min(364, c["p90"] + 20))
    return lo, hi


def svg_acumulado(x: dict, movil: bool = False) -> str:
    """Nieve caída acumulada desde el 1 de agosto: esta temporada frente a lo normal (banda de 8 de cada 10)."""
    c, o = x["clima"], x["temporada"]
    sf = "-m" if movil else ""
    W, H, L, R, T, B, F = (380, 250, 40, 10, 14, 26, 11.5) if movil else (760, 300, 52, 14, 16, 30, 13)
    lo, hi = _rango_temporada(c)
    serie = o["serie"]
    ihoy = len(serie) - 1
    top = max([v for v in c.get("acum_p90", [0])[lo:hi + 1] if v is not None] + [max(serie or [0]), 1]) * 1.08
    paso_y = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000][
        min(range(12), key=lambda k: abs(top / 4 - [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000][k]))]
    X = lambda i: L + (W - L - R) * (i - lo) / (hi - lo)
    Y = lambda v: T + (H - T - B) * (1 - v / top)
    s = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-labelledby="cgnv-ac{sf}" class="cgnv-svg">'
         f'<title id="cgnv-ac{sf}">Nieve caída acumulada en {esc(x["nombre"])} esta temporada frente a lo normal</title>']
    v = 0
    while v <= top:
        s.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{REJILLA}"/>'
                 f'<text x="{L - 6}" y="{Y(v) + 4:.1f}" font-size="{F}" text-anchor="end" fill="{GRIS}">{entero(v)}</text>')
        v += paso_y
    s.append(f'<text x="{L - 6}" y="{T - 2}" font-size="{F}" text-anchor="end" fill="{GRIS}">cm</text>')
    for m, lab in MESES_EJE:
        i = indice(date(2021 if m >= 8 else 2022, m, 1))
        if lo <= i <= hi:
            s.append(f'<line x1="{X(i):.1f}" x2="{X(i):.1f}" y1="{H - B}" y2="{H - B + 5}" stroke="{REJILLA}"/>'
                     f'<text x="{X(min(i + 15, hi)):.1f}" y="{H - 8}" font-size="{F}" text-anchor="middle" fill="{GRIS}">'
                     f'{lab}</text>')
    if c.get("acum_p90"):
        arriba = " ".join(f"{X(i):.1f},{Y(c['acum_p90'][i]):.1f}" for i in range(lo, hi + 1))
        abajo = " ".join(f"{X(i):.1f},{Y(c['acum_p10'][i]):.1f}" for i in range(hi, lo - 1, -1))
        s.append(f'<polygon points="{arriba} {abajo}" fill="#2f6f9f" fill-opacity=".45"/>')
        s.append('<polyline points="' + " ".join(f"{X(i):.1f},{Y(c['acum_media'][i]):.1f}" for i in range(lo, hi + 1))
                 + f'" fill="none" stroke="#bfe6ff" stroke-width="2" stroke-dasharray="6 5"/>')
    pts = [(i, serie[i]) for i in range(max(lo, 0), min(ihoy, hi) + 1)]
    if pts:
        s.append('<polyline points="' + " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in pts)
                 + f'" fill="none" stroke="#fff" stroke-width="3.2" stroke-linejoin="round"/>')
        i, v = pts[-1]
        s.append(f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="5.5" fill="#fff" stroke="{BRASA}" stroke-width="3"/>')
    if lo <= ihoy <= hi:
        s.append(f'<text x="{X(ihoy):.1f}" y="{T + 10}" font-size="{F}" font-weight="700" text-anchor="middle" '
                 f'fill="{BRASA}">hoy</text>')
    s.append("</svg>")
    return "".join(s)


def svg_espesor(x: dict, movil: bool = False) -> str:
    """Espesor de nieve en el suelo: esta temporada frente a la mediana 1991-2021."""
    c, o = x["clima"], x["temporada"]
    sf = "-m" if movil else ""
    W, H, L, R, T, B, F = (380, 210, 40, 10, 14, 26, 11.5) if movil else (760, 250, 52, 14, 16, 30, 13)
    lo, hi = _rango_temporada(c)
    med = c.get("esp_mediana") or [None] * 365
    serie = o.get("esp_serie") or []
    ihoy = len(serie) - 1
    top = max([v for v in med[lo:hi + 1] if v is not None] + [v for v in serie if v is not None] + [5]) * 1.12
    paso_y = 5 if top <= 30 else 10 if top <= 60 else 25 if top <= 150 else 50
    X = lambda i: L + (W - L - R) * (i - lo) / (hi - lo)
    Y = lambda v: T + (H - T - B) * (1 - v / top)
    s = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-labelledby="cgnv-es{sf}" class="cgnv-svg">'
         f'<title id="cgnv-es{sf}">Espesor de nieve en {esc(x["nombre"])}: esta temporada frente a un año normal</title>']
    v = 0
    while v <= top:
        s.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{REJILLA}"/>'
                 f'<text x="{L - 6}" y="{Y(v) + 4:.1f}" font-size="{F}" text-anchor="end" fill="{GRIS}">{entero(v)}</text>')
        v += paso_y
    s.append(f'<text x="{L - 6}" y="{T - 2}" font-size="{F}" text-anchor="end" fill="{GRIS}">cm</text>')
    for m, lab in MESES_EJE:
        i = indice(date(2021 if m >= 8 else 2022, m, 1))
        if lo <= i <= hi:
            s.append(f'<text x="{X(min(i + 15, hi)):.1f}" y="{H - 8}" font-size="{F}" text-anchor="middle" fill="{GRIS}">'
                     f'{lab}</text>')
    if any(v for v in med[lo:hi + 1]):
        pts = [f"{X(i):.1f},{Y(med[i] or 0):.1f}" for i in range(lo, hi + 1)]
        s.append(f'<polygon points="{X(lo):.1f},{Y(0):.1f} {" ".join(pts)} {X(hi):.1f},{Y(0):.1f}" fill="#2f6f9f" '
                 f'fill-opacity=".55"/>')
    pts = [(i, serie[i]) for i in range(lo, min(ihoy, hi) + 1) if serie[i] is not None]
    if pts:
        s.append('<polyline points="' + " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in pts)
                 + '" fill="none" stroke="#fff" stroke-width="3" stroke-linejoin="round"/>')
        i, v = pts[-1]
        s.append(f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="5" fill="#fff" stroke="{BRASA}" stroke-width="3"/>')
    s.append("</svg>")
    return "".join(s)


def svg_temporadas(x: dict) -> str:
    """Una barra por temporada: nieve caída de agosto a julio, con la media 1991-2021 y la de cada tramo."""
    temps = x["_temps"]
    ys = sorted(temps)
    if not ys:
        return ""
    ya = temporada_de(HOY)
    W, H, L, R, T, B = 760, 300, 52, 10, 14, 30
    n = ya - ys[0] + 1
    vals = [temps[y]["total"] for y in ys] + [x["temporada"]["acum"]]
    top = max(vals + [1]) * 1.08
    paso_y = [5, 10, 20, 25, 50, 100, 200, 250, 500, 1000][
        min(range(10), key=lambda k: abs(top / 4 - [5, 10, 20, 25, 50, 100, 200, 250, 500, 1000][k]))]
    paso = (W - L - R) / n
    Y = lambda v: T + (H - T - B) * (1 - v / top)
    s = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-labelledby="cgnv-t" class="cgnv-svg">'
         f'<title id="cgnv-t">Nieve caída cada temporada en {esc(x["nombre"])} desde {temporada(ys[0])}</title>']
    v = 0
    while v <= top:
        s.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{REJILLA}"/>'
                 f'<text x="{L - 6}" y="{Y(v) + 4:.1f}" font-size="12.5" text-anchor="end" fill="{GRIS}">{entero(v)}</text>')
        v += paso_y
    s.append(f'<text x="{L - 6}" y="{T - 2}" font-size="12.5" text-anchor="end" fill="{GRIS}">cm</text>')
    for k, y in enumerate(range(ys[0], ya + 1)):
        cx = L + (k + 0.5) * paso
        w = max(2.0, paso * 0.66)
        if y == ya:
            v = x["temporada"]["acum"]
            s.append(f'<rect x="{cx - w / 2:.1f}" y="{Y(v):.1f}" width="{w:.1f}" height="{max(1.5, Y(0) - Y(v)):.1f}" '
                     f'fill="{BRASA}"><title>{temporada(y)} (en curso): {esc(cm(v))} hasta hoy</title></rect>')
            continue
        t = temps.get(y)
        if not t:
            continue
        col = "#bfe6ff" if NORMAL[0] <= y <= NORMAL[1] else "#5b93bf"
        s.append(f'<rect x="{cx - w / 2:.1f}" y="{Y(t["total"]):.1f}" width="{w:.1f}" '
                 f'height="{max(1.0, Y(0) - Y(t["total"])):.1f}" fill="{col}"><title>{temporada(y)}: {esc(cm(t["total"]))}, '
                 f'{t["dias"]} días de nieve</title></rect>')
    for (a, b), lab in ((TRAMO1, "1971-1990"), (TRAMO2, "2006-2025")):
        vs = [temps[y]["total"] for y in temps if a <= y <= b]
        if len(vs) >= MIN_TRAMO:
            m = st.mean(vs)
            x0, x1 = L + (a - ys[0]) * paso, L + (min(b, ya - 1) - ys[0] + 1) * paso
            s.append(f'<line x1="{x0:.1f}" x2="{x1:.1f}" y1="{Y(m):.1f}" y2="{Y(m):.1f}" stroke="#fff" stroke-width="2.5"/>'
                     f'<text x="{(x0 + x1) / 2:.1f}" y="{Y(m) - 7:.1f}" font-size="12.5" font-weight="700" '
                     f'text-anchor="middle" fill="#fff" stroke="#0c2133" stroke-width="5" paint-order="stroke">media {lab}: '
                     f'{esc(cm(m))}</text>')
    for y in range(ys[0], ya + 1):
        if y % 10 == 0:
            s.append(f'<text x="{L + (y - ys[0] + 0.5) * paso:.1f}" y="{H - 8}" font-size="12.5" text-anchor="middle" '
                     f'fill="{GRIS}">{y}</text>')
    s.append("</svg>")
    return "".join(s)


def svg_sat_temporada(sat: dict, movil: bool = False) -> str:
    """% de España nevado, día a día, esta temporada frente a los inviernos desde 2005."""
    sf = "-m" if movil else ""
    W, H, L, R, T, B, F = (380, 230, 36, 10, 14, 26, 11.5) if movil else (760, 280, 46, 14, 16, 30, 13)
    lo, hi = I_OCT, indice(date(2022, 5, 31))
    serie, med, p10, p90 = sat.get("serie") or [None] * 365, sat.get("med"), sat.get("p10"), sat.get("p90")
    vals = [v for v in serie[lo:hi + 1] if v is not None] + [v for v in (p90 or [])[lo:hi + 1] if v is not None]
    top = max(vals + [5]) * 1.12
    paso_y = 2 if top <= 10 else 5 if top <= 25 else 10
    X = lambda i: L + (W - L - R) * (i - lo) / (hi - lo)
    Y = lambda v: T + (H - T - B) * (1 - v / top)
    s = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-labelledby="cgnv-st{sf}" class="cgnv-svg">'
         f'<title id="cgnv-st{sf}">Parte de España cubierta de nieve cada día de esta temporada, según el satélite</title>']
    v = 0
    while v <= top:
        s.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="{REJILLA}"/>'
                 f'<text x="{L - 6}" y="{Y(v) + 4:.1f}" font-size="{F}" text-anchor="end" fill="{GRIS}">{entero(v)} %</text>')
        v += paso_y
    for m, lab in MESES_EJE:
        i = indice(date(2021 if m >= 8 else 2022, m, 1))
        if lo <= i <= hi:
            s.append(f'<text x="{X(min(i + 15, hi)):.1f}" y="{H - 8}" font-size="{F}" text-anchor="middle" fill="{GRIS}">'
                     f'{lab}</text>')
    if p90 and any(v is not None for v in p90[lo:hi + 1]):
        idx = [i for i in range(lo, hi + 1) if p90[i] is not None and p10[i] is not None]
        arriba = " ".join(f"{X(i):.1f},{Y(p90[i]):.1f}" for i in idx)
        abajo = " ".join(f"{X(i):.1f},{Y(p10[i]):.1f}" for i in reversed(idx))
        s.append(f'<polygon points="{arriba} {abajo}" fill="#2f6f9f" fill-opacity=".45"/>')
        s.append('<polyline points="' + " ".join(f"{X(i):.1f},{Y(med[i]):.1f}" for i in idx if med[i] is not None)
                 + '" fill="none" stroke="#bfe6ff" stroke-width="2" stroke-dasharray="6 5"/>')
    pts = [(i, serie[i]) for i in range(lo, hi + 1) if serie[i] is not None]
    if pts:
        s.append('<polyline points="' + " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in pts)
                 + '" fill="none" stroke="#fff" stroke-width="3" stroke-linejoin="round"/>')
        i, v = pts[-1]
        s.append(f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="5" fill="#fff" stroke="{BRASA}" stroke-width="3"/>')
    s.append("</svg>")
    return "".join(s)


_MAPA = None


def mapa_trazos() -> dict:
    """Trazos SVG de cada provincia (Canarias, en un recuadro abajo a la izquierda). Se calcula una vez por pasada."""
    global _MAPA
    if _MAPA is not None:
        return _MAPA
    g = _geojson()
    nombres = {p[2]: p[0] for p in PROVINCIAS}
    K, LON0, LAT1, COSL = 46.0, -9.9, 44.0, math.cos(math.radians(40))
    out = {}
    for f in g["features"]:
        slug = nombres.get(f["properties"]["name"])
        if not slug:
            continue
        d = []
        for pl in _anillos(f["geometry"]):
            for an in pl[:1]:
                an = _simplificar(an, 0.03)
                if len(an) < 4:
                    continue
                pts = []
                for lon, lat in an:
                    if lon < -12.5:      # Canarias al recuadro
                        lon, lat = lon + 8.4, lat + 6.6
                    pts.append(f"{(lon - LON0) * COSL * K:.1f},{(LAT1 - lat) * K:.1f}")
                d.append("M" + "L".join(pts) + "Z")
        out[slug] = "".join(d)
    _MAPA = out
    return out


def svg_mapa(valores: dict, titulo: str, enlaces: bool = True) -> str:
    """Mapa de provincias coloreado por el % de superficie nevada."""
    trazos = mapa_trazos()
    W, H = round(14.6 * math.cos(math.radians(40)) * 46), round(10.0 * 46)
    s = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-labelledby="cgnv-map" class="cgnv-svg cgnv-mapa">'
         f'<title id="cgnv-map">{esc(titulo)}</title>',
         f'<rect x="2" y="{(44 - 36.4) * 46:.0f}" width="{(5.3 * math.cos(math.radians(40)) * 46):.0f}" height="{2.6 * 46:.0f}" '
         f'rx="8" fill="none" stroke="{REJILLA}" stroke-dasharray="4 4"/>']
    for slug, prov, *_ in PROVINCIAS:
        v = valores.get(slug)
        col = FONDO if v is None or v < 0.5 else color_nieve(min(1.0, 0.15 + v / 60))
        t = f"{prov}: {'sin dato' if v is None else pct(v) + ' nevado'}"
        trazo = f'<path d="{trazos.get(slug, "")}" fill="{col}" stroke="#0c2133" stroke-width="1.2"><title>{esc(t)}</title></path>'
        s.append(f'<a href="/nieve/{slug}/">{trazo}</a>' if enlaces else trazo)
    s.append("</svg>")
    return "".join(s)


# ------------------------------------------------------------------------------------------------------------ páginas
FUENTE = ('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" '
          'crossorigin><link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500..800'
          '&amp;display=swap" rel="stylesheet">')
CSS = FUENTE + """<style>
.cgnv{--tinta:#1a2530;--gris:#5d6b78;--escarcha:#eaf3fa;--hielo:#24608f;--noche:#0f3554;--brasa:#c4471d;
--p-txt:#e8f1f8;--p-sub:#b9cddc;--p-mut:#8fa9bd;--p-cel:#132f45;--p-hondo:#0a1b2a;--p-cristal:#bfe6ff;--p-brasa:#ff7a45;
max-width:1120px;margin:0 auto;padding:24px 20px 12px;box-sizing:border-box;background:#fff;color:var(--tinta);
font:17px/1.62 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.cgnv *{box-sizing:border-box}
.cgnv a{color:var(--hielo);text-decoration-thickness:1px;text-underline-offset:3px}
.cgnv a:hover{color:var(--noche)}
.cgnv a:focus-visible,.cgnv summary:focus-visible,.cgnv label:focus-visible{outline:2px solid var(--brasa);outline-offset:2px;border-radius:4px}
.cgnv h1,.cgnv h2,.cgnv h3,.cgnv-cifra-n,.cgnv-hoy-v b,.cgnv-rec b,.cgnv-antes b,.cgnv-mac-n{font-family:"Bricolage Grotesque",-apple-system,"Segoe UI",sans-serif}
.cgnv h2{font-size:30px;line-height:1.15;letter-spacing:-.015em;font-weight:720;margin:56px 0 12px;color:var(--noche)}
.cgnv h3{font-size:18px;line-height:1.35;margin:0;font-weight:700}
.cgnv p{margin:0 0 14px;max-width:70ch}
.cgnv-svg{display:block;width:100%;height:auto;overflow:visible}
.cgnv .cgnv-img{display:block;width:100%;height:auto;max-width:none;margin:0;border-radius:0}
.cgnv-svg text{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.cgnv-m{display:none}
.cgnv-panel{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(0,1fr);column-gap:40px;
grid-template-areas:"intro hoy" "cifras cifras" "prev prev" "graf graf";grid-template-rows:repeat(4,auto);grid-auto-rows:0;
background:radial-gradient(1100px 520px at 88% -12%,#1d4a6e 0,#0c2133 58%);color:var(--p-txt);border-radius:28px;padding:40px 44px 38px}
.cgnv-panel a{color:var(--p-cristal)}.cgnv-panel a:hover{color:#fff}
.cgnv-intro{grid-area:intro;align-self:end}
.cgnv-migas{font-size:14px;color:var(--p-mut);margin:0 0 16px}.cgnv-migas a{color:var(--p-mut);text-decoration:none}
.cgnv-migas a:hover{text-decoration:underline;color:#fff}.cgnv-migas span{margin:0 6px;opacity:.6}
.cgnv h1{font-size:50px;line-height:1.02;letter-spacing:-.025em;font-weight:760;margin:0 0 18px;color:#fff}
.cgnv h1 span{display:block;font-size:.5em;line-height:1.15;font-weight:560;letter-spacing:-.01em;color:#9fd2f3;margin-top:8px}
.cgnv .lede{font-size:18.5px;line-height:1.55;margin:0;color:var(--p-sub);max-width:36em}
.cgnv-panel .cg-ssr-slot,.cgnv-panel .cgnv-dia{display:contents}
.cg-ssr-slot{visibility:hidden;font-size:0;line-height:0}
.cg-ssr-slot .cgnv-hoy,.cg-ssr-slot .cgnv-cifras,.cg-ssr-slot .cgnv-prev,.cg-ssr-slot .cgnv-graf-p,.cg-ssr-slot .cgnv-top,.cg-ssr-slot .cgnv-macs{visibility:visible;font-size:17px;line-height:1.55}
.cgnv-hoy{grid-area:hoy;align-self:end;background:rgba(255,255,255,.06);border:1px solid rgba(191,230,255,.16);border-radius:22px;padding:22px 24px}
.cgnv .cgnv-hoy h2{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;font-size:15px;font-weight:500;letter-spacing:0;color:var(--p-mut);margin:0}
.cgnv .cgnv-hoy-v{margin:4px 0 8px;display:flex;align-items:baseline;flex-wrap:wrap;gap:4px 12px}
.cgnv-hoy-v b{font-size:60px;line-height:1;font-weight:760;color:#fff;letter-spacing:-.02em}
.cgnv-hoy-v span{font-size:16px;line-height:1.35;color:var(--p-cristal);font-weight:600}
.cgnv .cgnv-hoy p{font-size:15.5px;line-height:1.5;color:var(--p-sub);margin:0}
.cgnv-hoy ul{margin:10px 0 0;padding:0;list-style:none;font-size:15px;color:var(--p-sub)}
.cgnv-hoy li{padding:6px 0;border-top:1px solid rgba(191,230,255,.12)}
.cgnv-hoy li b{color:#fff}
.cgnv-cifras{grid-area:cifras;display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin-top:26px}
.cgnv-cifra{background:var(--p-cel);border-radius:18px;padding:18px 20px}
.cgnv-cifra-n{display:block;font-size:34px;line-height:1.05;font-weight:760;color:#fff;letter-spacing:-.015em}
.cgnv-cifra-l{display:block;font-size:14px;line-height:1.4;color:#9fb6c8;margin-top:6px}
.cgnv-prev{grid-area:prev;margin-top:20px;background:var(--p-hondo);border-radius:22px;padding:22px 24px 18px}
.cgnv .cgnv-prev h3{font-size:21px;color:#fff;font-weight:700;margin:0 0 6px}
.cgnv .cgnv-prev .cgnv-psub{font-size:15px;color:var(--p-sub);margin:0 0 14px;max-width:none}
.cgnv-tw{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:0 -6px;padding:0 6px}
.cgnv-tp{border-collapse:separate;border-spacing:3px;width:100%;min-width:700px;font-size:13.5px}
.cgnv-tp th,.cgnv-tp td{border:0!important;padding:0}.cgnv-tp th{font-weight:600;color:var(--p-mut);text-align:center;padding:2px 0 6px;white-space:nowrap}
.cgnv-tp th b{display:block;color:var(--p-txt);font-size:14px}
.cgnv-tp th.cgnv-fin{color:#ffd2bf}
.cgnv-tp td{text-align:center;border-radius:8px;height:38px;min-width:36px;background:#11293d;color:#0c2133;font-weight:700}
.cgnv-tp td.cgnv-0{color:transparent}.cgnv-tp td.cgnv-nd{background:transparent;color:#3d5a72;font-weight:400}
.cgnv-tp td.cgnv-claro{color:#e8f1f8}
.cgnv-tp th.cgnv-mod{text-align:left;color:var(--p-txt);padding-right:8px;min-width:96px}
.cgnv-tp th.cgnv-mod small{display:block;font-weight:400;color:var(--p-mut);font-size:12px}
.cgnv-tp tr.cgnv-cons td{box-shadow:inset 0 0 0 2px var(--p-cristal)}
.cgnv-tp tr.cgnv-cota td{background:transparent;color:var(--p-sub);font-weight:600;font-size:12.5px;height:24px}
.cgnv .cgnv-prev .cgnv-pie{font-size:13.5px;line-height:1.5;color:var(--p-mut);margin:14px 0 0;max-width:none}
.cgnv-clave{display:flex;flex-wrap:wrap;align-items:center;gap:8px 18px;font-size:13.5px;color:var(--p-mut);margin:10px 0 0}
.cgnv-escala .cgnv-esc{display:inline-block;width:120px;height:10px;border-radius:5px;vertical-align:-1px;margin:0 8px;background:linear-gradient(90deg,#1f4d70,#3a7fb3,#8cc6ee,#d4eeff,#fff)}
.cgnv-graf-p{grid-area:graf;margin-top:20px;display:grid;grid-template-columns:1fr 1fr;gap:16px}
.cgnv-graf-p figure{margin:0;background:var(--p-hondo);border-radius:22px;padding:20px 20px 14px}
.cgnv .cgnv-graf-p h3{font-size:17px;color:#fff;margin:0 0 10px}
.cgnv-graf-p figcaption{font-size:13.5px;color:var(--p-mut);margin-top:10px}
.cgnv-chips{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:8px}
.cgnv-chips li{background:var(--p-cel);border-radius:999px;padding:7px 14px;font-size:15px;color:var(--p-sub)}
.cgnv-chips li b{color:#fff;font-weight:700}.cgnv-chips li.cgnv-chip-n{background:#1f4d70}
.cgnv-panel-hub{grid-template-areas:"intro hoy" "mapa top" "prev prev" "macs macs" "graf graf";grid-template-rows:repeat(5,auto)}
.cgnv-mapaw{grid-area:mapa;margin-top:30px;align-self:center}
.cgnv-mapa a{cursor:pointer;outline:none}
.cgnv-ley{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:13px;color:var(--p-mut);margin-top:10px}
.cgnv-ley span{display:inline-flex;align-items:center;gap:6px}.cgnv-ley i{display:inline-block;width:14px;height:14px;border-radius:4px;border:1px solid rgba(191,230,255,.25)}
.cgnv-top{grid-area:top;margin-top:30px;align-self:center;font-size:15px;color:var(--p-sub)}
.cgnv-macs-h{grid-column:1/-1;margin:4px 0 0!important}
.cgnv-lista{margin:18px 0 10px;background:#0c2133;border-radius:24px;padding:12px 14px;color:var(--p-txt)}
.cgnv-lista-c,.cgnv .cgnv-fila{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,1.6fr) 90px 120px;gap:14px;align-items:center}
.cgnv-lista-c{font-size:12.5px;color:var(--p-mut);padding:6px 12px 8px;text-transform:uppercase;letter-spacing:.04em}
.cgnv-lista-c span:nth-child(n+3){text-align:right}
.cgnv .cgnv-fila{padding:10px 12px;border-radius:14px;text-decoration:none;color:var(--p-txt);border-top:1px solid rgba(191,230,255,.08)}
.cgnv .cgnv-fila:hover,.cgnv .cgnv-fila:focus-visible{background:#163a55;color:#fff}
.cgnv-fila-n b{display:block;font-family:"Bricolage Grotesque",-apple-system,"Segoe UI",sans-serif;font-size:17px;font-weight:700;color:#fff;line-height:1.2}
.cgnv-fila-n small{display:block;font-size:13px;color:var(--p-mut);line-height:1.3}
.cgnv-fila-b{display:flex;align-items:center;gap:10px}
.cgnv-fila-b i{display:block;height:12px;border-radius:6px;background:linear-gradient(90deg,#3a7fb3,#bfe6ff)}
.cgnv-fila-b em{font-style:normal;font-weight:700;font-size:15px;color:#fff;white-space:nowrap}
.cgnv-chip{justify-self:end;font-size:13.5px;font-weight:700;padding:4px 10px;border-radius:999px;background:#163a55;color:var(--p-sub);white-space:nowrap}
.cgnv-chip-baja{background:rgba(255,122,69,.18);color:#ffb08f}.cgnv-chip-sube{background:rgba(140,198,238,.2);color:#bfe6ff}
.cgnv-fila-d{text-align:right;font-weight:700;font-size:15px;color:#fff}
.cgnv-h3{font-size:20px!important;color:var(--noche);margin:28px 0 10px!important}
.cgnv-retrasos{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:10px;margin:8px 0}
.cgnv .cgnv-ret{display:grid;grid-template-columns:minmax(0,1fr) auto;grid-template-areas:"n d" "f f" "b b";gap:4px 12px;background:#0c2133;border-radius:18px;padding:14px 16px;text-decoration:none;color:var(--p-sub)}
.cgnv .cgnv-ret:hover{background:#163a55}
.cgnv-ret-n{grid-area:n;font-weight:700;color:#fff;font-size:16px;line-height:1.25}.cgnv-ret-n small{display:block;font-weight:400;font-size:13px;color:var(--p-mut)}
.cgnv-ret-d{grid-area:d;font-family:"Bricolage Grotesque",sans-serif;font-size:24px;font-weight:760;color:#ff9a70;white-space:nowrap}
.cgnv-ret-f{grid-area:f;font-size:14px}.cgnv-ret-f b{color:#fff}
.cgnv-ret-b{grid-area:b;height:8px;border-radius:4px;background:#163a55;margin-top:4px}.cgnv-ret-b i{display:block;height:100%;border-radius:4px;background:linear-gradient(90deg,#bfe6ff,#ff7a45)}
.cgnv-cal-n{cursor:pointer}a:hover .cgnv-cal-n{fill:#fff;text-decoration:underline}
.cgnv-graf-des{max-width:860px}
.cgnv .cgnv-graf figcaption a{color:#bfe6ff}
.cgnv-top ol{margin:8px 0 0;padding:0;list-style:none;counter-reset:t}
.cgnv-top li{display:flex;justify-content:space-between;gap:10px;padding:7px 0;border-top:1px solid rgba(191,230,255,.12)}
.cgnv-top li b{color:#fff}
.cgnv .cgnv-panel-h2{color:#fff;font-size:24px;margin:0 0 12px}
.cgnv-macs{grid-area:macs;margin-top:20px;display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px}
.cgnv-mac{background:var(--p-cel);border-radius:18px;padding:16px 18px;font-size:14.5px;color:var(--p-sub)}
.cgnv .cgnv-mac h3{font-size:17px;color:#fff;margin:0 0 2px}
.cgnv-mac-s{font-size:13px;color:var(--p-mut);margin:0 0 10px}
.cgnv .cgnv-mac-l{font-size:14.5px;color:var(--p-sub);margin:2px 0 0;max-width:none}
.cgnv .cgnv-hoy .cgnv-enl{margin:12px 0 0;font-size:14.5px}
.cgnv-tm td{color:var(--p-txt);font-weight:600;padding:0 8px;white-space:nowrap}.cgnv-tm th{padding:0 8px}
.cgnv .cgnv-tm th.cgnv-mod a{color:#fff}
.cgnv .cgnv-mac-a{font-size:14px;margin:12px 0 0;max-width:none}.cgnv .cgnv-mac h3 a{color:#fff;text-decoration:none}.cgnv .cgnv-mac h3 a:hover{text-decoration:underline}
.cgnv-mac-n{display:block;font-size:28px;font-weight:760;color:#fff;line-height:1.1}
.cgnv-mac dl{margin:10px 0 0;display:grid;grid-template-columns:auto 1fr;gap:3px 10px}
.cgnv-mac dt{color:var(--p-mut)}.cgnv-mac dl.cgnv-cerca{grid-template-columns:1fr auto auto;gap:6px 12px}.cgnv-cerca dt:first-child+dd,.cgnv-cerca dt:first-child+dd+dd{color:var(--p-mut);font-weight:400;font-size:12.5px}.cgnv-mac dd{margin:0;text-align:right;color:#fff;font-weight:600}
.cgnv .cgnv-pnota{font-size:14px;color:var(--p-mut);margin:10px 0 0;max-width:none}
.cgnv-nota{font-size:14.5px;color:var(--gris)}
.cgnv-graf{margin:22px 0 6px;background:#0c2133;border-radius:24px;padding:26px 26px 18px}
.cgnv-graf figcaption{font-size:14px;color:var(--p-mut);margin-top:12px;max-width:70ch}
.cgnv-antes{margin:18px 0 16px;display:grid;grid-template-columns:auto 1fr;gap:14px 18px;align-items:center;max-width:760px;background:#0c2133;border-radius:22px;padding:22px 24px;color:var(--p-txt)}
.cgnv-antes span{font-size:15px;color:var(--p-mut);white-space:nowrap}
.cgnv-barra{height:40px;border-radius:12px;background:#2f6f9f;display:flex;align-items:center;justify-content:flex-end;padding:0 14px;min-width:max-content}
.cgnv-barra b{font-size:20px;font-weight:760;color:#fff}
.cgnv-barra.cgnv-ahora{background:linear-gradient(90deg,#6fb0dc,#bfe6ff)}.cgnv-barra.cgnv-ahora b{color:var(--noche)}
.cgnv-recs{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin:18px 0 0}
.cgnv-rec{background:var(--escarcha);border-radius:18px;padding:18px 20px}
.cgnv-rec span{display:block;font-size:14px;color:var(--gris);line-height:1.4}
.cgnv-rec b{display:block;font-size:24px;line-height:1.15;font-weight:740;color:var(--noche);margin:6px 0 2px;letter-spacing:-.01em}
.cgnv-rec small{display:block;font-size:14px;color:var(--gris)}
.cgnv-faq{max-width:820px}
.cgnv-faq details{border-bottom:1px solid #e1e8ee}
.cgnv-faq summary{list-style:none;cursor:pointer;display:flex;justify-content:space-between;align-items:center;gap:16px;padding:16px 0}
.cgnv-faq summary::-webkit-details-marker{display:none}
.cgnv-faq summary::after{content:"+";font-size:26px;line-height:1;color:var(--hielo);font-weight:300;transition:transform .2s}
.cgnv-faq details[open] summary::after{transform:rotate(45deg)}
.cgnv-faq summary h3{color:var(--noche)}
.cgnv-faq details p{margin:0 0 18px}
.cgnv-tabla{width:100%;border-collapse:collapse;font-size:15.5px;margin:12px 0}
.cgnv-tabla th,.cgnv-tabla td{border-bottom:1px solid #e3e8ec;padding:10px 8px 10px 0;text-align:left;vertical-align:top}
.cgnv-tabla th{font-size:14px;color:var(--gris);font-weight:600}
.cgnv-tabla tbody tr:hover{background:var(--escarcha)}
.cgnv-tabla td.n,.cgnv-tabla th.n{text-align:right;white-space:nowrap}
.cgnv-tabla .baja{color:#a8361a;font-weight:600}
.cgnv-metodo{margin:56px 0 12px;padding:22px 26px 10px;border-radius:20px;background:#f2f5f8;font-size:15px;color:#33414e}
.cgnv-metodo p{max-width:none}
.cgnv-mapa a path:hover{stroke:#fff;stroke-width:2}
.cgnv .cgnv-img{display:block;width:100%;height:0;background-size:100% 100%;background-repeat:no-repeat}
.cgnv-sr{position:absolute!important;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.cgnv-graf-p .cgnv-fig{margin:0;background:var(--p-hondo);border-radius:22px;padding:20px 20px 14px}
.cgnv .cgnv-graf-p .cgnv-cap{font-size:13.5px;color:var(--p-mut);margin:10px 0 0;max-width:none}
.cgnv-mac .cgnv-dl{margin:10px 0 0;display:grid;grid-template-columns:auto 1fr;gap:3px 10px}
.cgnv-mac .cgnv-dt{color:var(--p-mut)}.cgnv-mac .cgnv-dd{margin:0;text-align:right;color:#fff;font-weight:600}
.cgnv-mac .cgnv-dl.cgnv-cerca{grid-template-columns:1fr auto auto;gap:6px 12px}
.cgnv-cerca .cgnv-dt:first-child+.cgnv-dd,.cgnv-cerca .cgnv-dt:first-child+.cgnv-dd+.cgnv-dd{color:var(--p-mut);font-weight:400;font-size:12.5px}
@media(max-width:860px){.cgnv-panel{grid-template-columns:minmax(0,1fr);grid-template-areas:"intro" "hoy" "cifras" "prev" "graf";grid-template-rows:repeat(5,auto);padding:28px 22px 24px}
.cgnv-panel-hub{grid-template-areas:"intro" "hoy" "mapa" "top" "prev" "macs" "graf";grid-template-rows:repeat(7,auto)}
.cgnv-hoy{margin-top:24px}.cgnv h1{font-size:40px}.cgnv-graf-p{grid-template-columns:1fr}.cgnv-top{margin-top:18px}}
@media(max-width:600px){.cgnv{padding:12px 10px 4px;font-size:16.5px}
.cgnv-graf-p .cgnv-fig{padding:14px 10px 10px}
.cgnv-panel{padding:22px 14px 16px;border-radius:22px;background:radial-gradient(600px 400px at 90% -10%,#1d4a6e 0,#0c2133 60%)}
.cgnv h1{font-size:31px}.cgnv .lede{font-size:17px}.cgnv h2{font-size:24px;margin-top:44px}
.cgnv-hoy{padding:18px 18px}.cgnv-hoy-v b{font-size:46px}
.cgnv-d{display:none}.cgnv-m{display:block}
.cgnv-cifras{grid-template-columns:1fr 1fr;gap:10px}.cgnv-cifra{padding:14px 14px}.cgnv-cifra-n{font-size:25px}
.cgnv-prev{padding:16px 10px 14px}.cgnv .cgnv-prev h3{font-size:17px;padding:0 4px}
.cgnv-graf-p figure{padding:14px 10px 10px}
.cgnv-graf{padding:16px 12px 12px;border-radius:18px;margin-left:-4px;margin-right:-4px}
.cgnv-svgw{overflow-x:auto;direction:rtl}.cgnv-svgw svg{min-width:600px;direction:ltr}
.cgnv-antes{padding:16px 14px;gap:10px 12px}.cgnv-barra{height:34px}.cgnv-barra b{font-size:17px}
.cgnv-tabla{font-size:14.5px}
.cgnv-lista{padding:8px 6px;border-radius:18px}.cgnv-lista-c{display:none}
.cgnv .cgnv-fila{grid-template-columns:minmax(0,1fr) auto;grid-template-areas:"n c" "b d";gap:6px 10px;padding:12px 10px}
.cgnv-fila-n{grid-area:n}.cgnv-fila-b{grid-area:b}.cgnv-chip{grid-area:c}.cgnv-fila-d{grid-area:d;font-size:13px;font-weight:400;color:var(--p-mut)}
.cgnv-fila-d::after{content:" días de nieve en la capital"}
.cgnv-retrasos{grid-template-columns:1fr}.cgnv-escala .cgnv-esc{width:70px}.cgnv-metodo{padding:18px 16px 6px}}
@media(prefers-reduced-motion:reduce){.cgnv *{transition:none!important}}
</style>"""


def img_svg(nombre: str, svg: str, alt: str) -> str:
    """WordPress pasa el bloque del día (meta cg_ssr_html) por una lista cerrada de etiquetas (cg-ssr-bloque.php):
    no deja <svg> ni <img>. El gráfico se guarda como archivo en GitHub Pages (docs/nieve/graf/) y el bloque lo
    pinta como fondo de un <div> (style sí pasa). El ?v= cambia solo si cambia el dibujo."""
    import re as _re
    m = _re.search(r'viewBox="0 0 (\d+) (\d+)"', svg)
    w, hh = (int(m.group(1)), int(m.group(2))) if m else (760, 300)
    svg = svg.replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" font-family="-apple-system,BlinkMacSystemFont,'
                      'Segoe UI,Roboto,Helvetica,Arial,sans-serif" ', 1)
    svg = _re.sub(r"</?a\b[^>]*>", "", svg)   # los enlaces no funcionan dentro de una imagen
    svg = '<?xml version="1.0" encoding="UTF-8"?>' + svg
    escribir(SALIDA / "graf" / f"{nombre}.svg", svg)
    url = f"{PAGES}/nieve/graf/{nombre}.svg?v={h(svg)[:10]}"
    return (f'<div class="cgnv-img" title="{esc(alt)}" style="background-image:url({url});padding-top:{100 * hh / w:.2f}%">'
            f'</div><span class="cgnv-sr">{esc(alt)}</span>')


def ssr_compatible(html_: str) -> str:
    """Cambia las etiquetas que cg-ssr-bloque.php no deja pasar por otras que sí, con la misma clase visual."""
    import re as _re
    r = [(r"<figure>", '<div class="cgnv-fig">'), (r"</figure>", "</div>"),
         (r"<figcaption>", '<p class="cgnv-cap">'), (r"</figcaption>", "</p>"),
         (r'<dl class="([^"]*)">', r'<div class="cgnv-dl \1">'), (r"<dl>", '<div class="cgnv-dl">'), (r"</dl>", "</div>"),
         (r"<dt>", '<span class="cgnv-dt">'), (r"</dt>", "</span>"),
         (r"<dd>", '<span class="cgnv-dd">'), (r"</dd>", "</span>")]
    for a, b in r:
        html_ = _re.sub(a, b, html_)
    return html_


def faq_jsonld(preguntas: list) -> str:
    d = {"@context": "https://schema.org", "@type": "FAQPage",
         "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
                        for q, a in preguntas]}
    return '<script type="application/ld+json">' + json.dumps(d, ensure_ascii=False) + "</script>"


def faq_html(q: list) -> str:
    out = ['<div class="cgnv-faq"><h2>Preguntas frecuentes</h2>']
    for k, (a, b) in enumerate(q):
        out.append(f'<details{" open" if k == 0 else ""}><summary><h3>{esc(a)}</h3></summary><p>{esc(b)}</p></details>')
    out.append("</div>")
    return "".join(out)


def tarjeta(etiqueta: str, valor: str, detalle: str = "") -> str:
    return (f'<div class="cgnv-rec"><span>{esc(etiqueta)}</span><b>{esc(valor)}</b>'
            + (f"<small>{esc(detalle)}</small>" if detalle else "") + "</div>")


def cifra(n: str, l: str) -> str:
    return f'<div class="cgnv-cifra"><span class="cgnv-cifra-n">{esc(n)}</span><span class="cgnv-cifra-l">{esc(l)}</span></div>'


def url_prov(slug: str) -> str:
    return f"{WEB}/nieve/{slug}/"


def fd(f: str, anio: bool = True) -> str:
    return fecha_larga(date.fromisoformat(f), anio)


def frente_normal(v: float, n: float | None) -> str:
    """«el doble de lo normal», «un 40 % menos de lo normal»…"""
    if n is None:
        return ""
    if n < 0.5:
        return "cuando lo normal a estas alturas es no tener nieve" if v >= 1 else "como es normal a estas alturas"
    r = v / n
    if r >= 1.9:
        return f"{num(r, 1).replace(',0', '')} veces lo normal a estas alturas ({cm(n)})"
    if r >= 1.1:
        return f"un {entero(100 * (r - 1))} % más de lo normal a estas alturas ({cm(n)})"
    if r > 0.9:
        return f"lo normal a estas alturas ({cm(n)})"
    if v < 0.5:
        return f"cuando lo normal a estas alturas son {cm(n)}"
    return f"un {entero(100 * (1 - r))} % menos de lo normal a estas alturas ({cm(n)})"


def frase_temporada(x: dict) -> str:
    o, ya = x["temporada"], temporada_de(HOY)
    t = f"Desde el 1 de agosto han caído {cm(o['acum'])} de nieve en {x['nombre']}"
    fn = frente_normal(o["acum"], o.get("normal"))
    if o["acum"] < 0.5:
        t = f"Todavía no ha nevado en {x['nombre']} esta temporada"
        if o.get("normal") and o["normal"] >= 1:
            t += f", cuando lo normal a estas alturas son {cm(o['normal'])}"
        return t + "."
    t += f", {fn}" if fn else ""
    if o.get("puesto") and o["puesto"] <= 5 and o["acum"] >= 5:
        t += f". Es el {o['puesto']}.º arranque de temporada más nevado desde {temporada(x['records']['desde'])}"
    return t + "."


# ----------------------------------------------------------------------------------------------- bloque de previsión
def tabla_prevision(pv: dict, nombre: str, dias: int = 15) -> str:
    if not pv.get("dias"):
        return "<h3>La previsión de los modelos no está disponible ahora mismo.</h3>"
    ds = [date.fromisoformat(f) for f in pv["dias"][:dias]]
    cab = ['<tr><th></th>'] + [
        f'<th class="{"cgnv-fin" if d.weekday() >= 5 else ""}">{"hoy" if d == HOY else DIAS_C[d.weekday()]}<b>{d.day}</b></th>'
        for d in ds] + ["</tr>"]

    def fila(etq: str, sub: str, vals: list, cls: str = "") -> str:
        cel = []
        for j in range(len(ds)):
            v = vals[j] if j < len(vals) else None
            if v is None:
                cel.append('<td class="cgnv-nd">·</td>')
                continue
            p = escala_cm(v)
            clase = "cgnv-0" if p == 0 else ("cgnv-claro" if p < 0.5 else "")
            fondo = f' style="background:{color_nieve(p)}"' if p > 0 else ""
            txt = "" if p == 0 else (entero(v) if v >= 9.5 else num(v))
            cel.append(f'<td class="{clase}"{fondo} title="{esc(etq)}: {esc(cm(v))} el {esc(fecha_larga(ds[j], False))}">'
                       f'{txt}</td>')
        return f'<tr class="{cls}"><th class="cgnv-mod">{esc(etq)}<small>{esc(sub)}</small></th>{"".join(cel)}</tr>'

    filas = []
    for mid, nom, org, alc in MODELOS:
        m = pv["modelos"].get(mid)
        if m:
            filas.append(fila(nom, {"ECMWF": "Europa", "ICON": "Alemania", "ARPEGE": "Francia", "GFS": "EE. UU."}[nom], m["n"]))
    filas.append(fila("Consenso", "mediana", pv["consenso"], "cgnv-cons"))
    cotas = ['<tr class="cgnv-cota"><th class="cgnv-mod">Cota (m)<small>si precipita</small></th>']
    for j in range(len(ds)):
        c = pv["cota"][j] if j < len(pv["cota"]) else None
        cotas.append(f"<td>{'' if c is None else (str(c) if c < 3500 else '—')}</td>")
    cotas.append("</tr>")
    return ('<div class="cgnv-tw"><table class="cgnv-tp"><thead>' + "".join(cab) + "</thead><tbody>" + "".join(filas)
            + "".join(cotas) + "</tbody></table></div>"
            '<div class="cgnv-clave"><span class="cgnv-escala">cm de nieve nueva al día: 1<span class="cgnv-esc"></span>30 o más</span>'
            '<span>· sin dato: el modelo no llega a ese día</span></div>')


def resumen_prevision(pv: dict, nombre: str) -> str:
    if not pv.get("dias"):
        return ""
    cons = pv["consenso"]
    con = [(pv["dias"][j], v, pv["vistos"][j]) for j, v in enumerate(cons[:15]) if v is not None and v >= UMBRAL_DIA]
    if not con:
        mx = pv.get("max_modelo15") or 0
        if mx >= 2:
            return (f"Los modelos no se ponen de acuerdo en ninguna nevada en {nombre} en los próximos 15 días; el más "
                    f"nevado suma {cm(mx)} en total.")
        return f"Ningún modelo ve nevadas en {nombre} en los próximos 15 días."
    f, v, vis = max(con, key=lambda z: z[1])
    d = date.fromisoformat(f)
    cuando = "hoy" if d == HOY else "mañana" if d == HOY + timedelta(days=1) else f"el {dia_semana(d)} {d.day}"
    t = (f"Los modelos ven nieve en {nombre} {len(con)} de los próximos 15 días, "
         f"{cm(pv['total15'])} en total según la mediana. El día más nevado sería {cuando}, con {cm(v)}")
    t += f" ({vis} de {len([m for m in pv['modelos']])} modelos lo ven)." if vis else "."
    return t


# ------------------------------------------------------------------------------------------- página de provincia
def va_a_nevar(x: dict) -> str:
    """Respuesta directa, en una frase, a «¿va a nevar en X?» con la mediana de los modelos."""
    pv = x["prevision"]
    if not pv.get("dias"):
        return f"La previsión de los modelos para {x['nombre']} no está disponible ahora mismo."
    cons = pv["consenso"]
    dias = [(date.fromisoformat(f), v, pv["cota"][j]) for j, (f, v) in enumerate(zip(pv["dias"], cons))
            if v is not None and v >= UMBRAL_DIA]
    cuando = lambda d: ("hoy" if d == HOY else "mañana" if d == HOY + timedelta(days=1)
                        else f"el {dia_semana(d)} {d.day}")
    pronto = [z for z in dias if z[0] <= HOY + timedelta(days=6)]
    if pronto:
        d, v, c = max(pronto, key=lambda z: z[1])
        t = (f"Sí: los modelos ven nieve en {x['nombre']} {lista([cuando(z[0]) for z in pronto[:4]])}"
             f"{' y más días' if len(pronto) > 4 else ''}, {cm(sum(z[1] for z in pronto))} en total esta semana; el día "
             f"más nevado sería {cuando(d)}, con {cm(v)}")
        return t + (f" y la cota en torno a {entero(c)} m." if c is not None else ".")
    lejos = [z for z in dias if z[0] > HOY + timedelta(days=6)]
    if lejos:
        d, v, c = lejos[0]
        return (f"Esta semana no: los modelos no ven nieve en {x['nombre']} en los próximos 7 días. Algunos apuntan a "
                f"nieve a partir del {fecha_larga(d, False)}, todavía muy lejos para darlo por hecho.")
    return f"No: ninguno de los cuatro modelos ve nieve apreciable en {x['nombre']} en los próximos 15 días."


def svg_primera(x: dict) -> str:
    """Una barra por temporada, de la primera a la última nevada, con la mediana de cada tramo."""
    temps = x["_temps"]
    ys = sorted(temps)
    c, ch = x["clima"], x["cambio"]
    W, H, L, R, T, B = 760, 330, 52, 8, 10, 30
    idx = [v[k] for v in temps.values() for k in ("primera", "ultima") if v[k] is not None]
    if x["temporada"].get("primera"):
        idx.append(indice(date.fromisoformat(x["temporada"]["primera"])))
    lo, hi = max(0, min(idx) - 8), min(364, max(idx) + 8)
    ya = temporada_de(HOY)
    n = ya - ys[0] + 1
    paso = (W - L - R) / n
    Y = lambda i: T + (H - T - B) * (i - lo) / max(1, hi - lo)
    s = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-labelledby="cgnv-pr" class="cgnv-svg">'
         f'<title id="cgnv-pr">Primera y última nevada de cada temporada en {esc(x["nombre"])} desde {temporada(ys[0])}</title>']
    for m, lab in MESES_EJE:
        i = indice(date(2021 if m >= 8 else 2022, m, 1))
        if lo <= i <= hi:
            s.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(i):.1f}" y2="{Y(i):.1f}" stroke="{REJILLA}"/>'
                     f'<text x="{L - 8}" y="{Y(i) + 4:.1f}" font-size="12.5" text-anchor="end" fill="{GRIS}">1 {lab}</text>')
    for k, y in enumerate(range(ys[0], ya + 1)):
        v = temps.get(y)
        cx = L + (k + 0.5) * paso
        w = max(2.0, paso * 0.6)
        if v and v["primera"] is not None:
            a, b = Y(v["primera"]), Y(v["ultima"])
            col = "#bfe6ff" if NORMAL[0] <= y <= NORMAL[1] else "#5b93bf"
            s.append(f'<rect x="{cx - w / 2:.1f}" y="{a:.1f}" width="{w:.1f}" height="{max(2, b - a):.1f}" rx="{w / 2:.1f}" '
                     f'fill="{col}"><title>{temporada(y)}: primera nevada el {esc(dia_mes(v["primera"]))}, última el '
                     f'{esc(dia_mes(v["ultima"]))}</title></rect>')
        if y == ya and x["temporada"].get("primera"):
            s.append(f'<circle cx="{cx:.1f}" cy="{Y(indice(date.fromisoformat(x["temporada"]["primera"]))):.1f}" r="5" '
                     f'fill="#fff" stroke="{BRASA}" stroke-width="3"/>')
    for (a0, b0), clave in ((TRAMO1, "t1"), (TRAMO2, "t2")):
        cp = (ch.get("primera") or {}).get(clave)
        if cp is not None:
            x0, x1 = L + (a0 - ys[0]) * paso, L + (min(b0, ya - 1) - ys[0] + 1) * paso
            s.append(f'<line x1="{x0:.1f}" x2="{x1:.1f}" y1="{Y(cp):.1f}" y2="{Y(cp):.1f}" stroke="#fff" stroke-width="2.5" '
                     f'stroke-dasharray="7 4"/><text x="{(x0 + x1) / 2:.1f}" y="{Y(cp) - 7:.1f}" font-size="12.5" '
                     f'font-weight="700" text-anchor="middle" fill="#fff" stroke="#0c2133" stroke-width="5" '
                     f'paint-order="stroke">primera nevada típica: {esc(dia_mes(cp))}</text>')
    for y in range(ys[0], ya + 1):
        if y % 10 == 0:
            s.append(f'<text x="{L + (y - ys[0] + 0.5) * paso:.1f}" y="{H - 8}" font-size="12.5" text-anchor="middle" '
                     f'fill="{GRIS}">{y}</text>')
    s.append("</svg>")
    return "".join(s)


def frase_primera(x: dict) -> str | None:
    c, ch = x["clima"], x["cambio"]
    if c.get("primera") is None:
        return None
    t = (f"En un año normal, la primera nevada llega a {x['nombre']} hacia el {dia_mes(c['primera'])} y la última cae "
         f"hacia el {dia_mes(c['ultima'])}. En 8 de cada 10 temporadas, la primera llega entre el "
         f"{dia_mes(c['primera_p10'])} y el {dia_mes(c['primera_p90'])}.")
    p = ch.get("primera")
    if p:
        sig = p["t"] is not None and abs(p["t"]) >= 2
        d = p["dias"]
        if abs(d) >= 3:
            t += (f" La primera nevada llega ahora {abs(d)} días {'más tarde' if d > 0 else 'antes'} que en 1971-1990 "
                  f"(hacia el {dia_mes(p['t2'])}, frente al {dia_mes(p['t1'])})")
            t += (f", un retraso de unos {num(abs(p['decada']))} días por década con una tendencia estadísticamente "
                  f"significativa." if sig and d > 0 and p.get("decada") else
                  ", con una tendencia estadísticamente significativa." if sig else
                  ", aunque la diferencia entre unos inviernos y otros es tan grande que la tendencia no es "
                  "estadísticamente significativa.")
        else:
            t += " La fecha de la primera nevada apenas se ha movido desde los años setenta."
        u, du = ch.get("ultima"), ch.get("duracion")
        if u and abs(u["dias"]) >= 3:
            t += (f" La última nevada llega {abs(u['dias'])} días {'antes' if u['dias'] < 0 else 'más tarde'} que entonces")
            if du and du["dias"] <= -5:
                t += f", así que la temporada de nieve es {abs(du['dias'])} días más corta."
            else:
                t += "."
    return t


def preguntas_prov(px: dict) -> list:
    mo, ca, prov = px["monte"], px["capital"], px["provincia"]
    q = []
    cm_, cc = mo["clima"], ca["clima"]
    if cc.get("tipo"):
        if cc["tipo"] == "frecuente":
            r = (f"Sí, casi todos los inviernos: nieva unos {entero(cc['dias'])} días al año en {ca['nombre']}, casi "
                 f"siempre entre el {dia_mes(cc['p10'])} y el {dia_mes(cc['p90'])}.")
        elif cc["tipo"] == "ocasional":
            r = (f"Algunos inviernos: nevó en {cc['con_nieve']} de las {cc['n']} temporadas de 1991 a 2021, de media "
                 f"{num(cc['dias'])} días al año, sobre todo hacia el {dia_mes(cc['p50'])}.")
        else:
            r = (f"Muy pocas veces: en {cc['n']} temporadas de 1991 a 2021 solo nevó de forma apreciable en "
                 f"{cc['con_nieve']}." if cc["con_nieve"] else
                 f"Casi nunca: en las {cc['n']} temporadas de 1991 a 2021 no hubo ningún día con 1 cm de nieve o más.")
        q.append((f"¿Cuándo nieva en {ca['nombre']}?", r))
    ult = ca["records"].get("ultima")
    if ult:
        ev = evento(ult["f"])
        q.append((f"¿Cuándo nevó por última vez en {ca['nombre']}?",
                  f"El último día con al menos 1 cm de nieve nueva en {ca['nombre']} fue el {fd(ult['f'])}"
                  + (f", con {ev}" if ev else "") + f": {cm(ult['cm'])}, según el reanálisis ERA5-Land."))
    rd = ca["records"].get("dia_max")
    if rd:
        ev = evento(rd["f"])
        q.append((f"¿Cuál ha sido la mayor nevada en {ca['nombre']}?",
                  f"La del {fd(rd['f'])}" + (f", con {ev}" if ev else "") + f": {cm(rd['cm'])} de nieve en un día, la mayor "
                  f"desde {ca['records']['desde']} en la serie de ERA5-Land."))
    if cm_.get("total") is not None:
        q.append((f"¿Cuánto nieva en {mo['nombre']}?",
                  f"En una temporada normal (1991-92 a 2020-21) caen unos {cm(cm_['total'])} de nieve en {mo['nombre']} "
                  f"({entero(mo['alt'])} m), repartidos en {entero(cm_['dias'])} días, y el suelo está nevado unos "
                  f"{entero(cm_['dias_suelo'])} días al año."))
    fp = frase_primera(mo)
    if fp:
        q.append((f"¿Cuándo es la primera nevada en {mo['nombre']}?", fp))
    fc = frase_cambio(mo)
    if fc:
        q.append((f"¿Nieva menos que antes en {prov}?", fc))
    q.append((f"¿Qué es la cota de nieve?",
              "La altitud a partir de la cual la precipitación cae en forma de nieve. Suele estar unos 300 metros por debajo de "
              "la isoterma de 0 °C; aquí se calcula así con los datos de cada modelo, en las horas en que se prevé "
              "precipitación."))
    return q


def frase_cambio(x: dict) -> str | None:
    c = x["cambio"].get("total")
    if not c or c["t1"] < 1:
        return None
    sig = c["t"] is not None and abs(c["t"]) >= 2
    if c["t2"] < c["t1"]:
        base = (f"En {x['nombre']} caían {cm(c['t1'])} de nieve por temporada en 1971-1990 y {cm(c['t2'])} en 2006-2025"
                + (f", un {entero(-c['pct'])} % menos" if c.get("pct") is not None else ""))
    else:
        base = (f"En {x['nombre']} caían {cm(c['t1'])} de nieve por temporada en 1971-1990 y {cm(c['t2'])} en 2006-2025"
                + (f", un {entero(c['pct'])} % más" if c.get("pct") is not None else ""))
    if sig:
        return base + (". La tendencia desde 1971 es estadísticamente significativa: no es ruido de unos pocos inviernos."
                       if c["t2"] < c["t1"] else ". La tendencia desde 1971 es estadísticamente significativa.")
    return base + (". Pero la nieve varía tanto de un invierno a otro que la tendencia desde 1971 no es estadísticamente "
                   "significativa: no se puede decir que haya un cambio claro.")


def bloque_antes(c: dict, unidad: str) -> str:
    if not c or max(c["t1"], c["t2"]) < 0.5:
        return ""
    m = max(c["t1"], c["t2"])
    fila = lambda lab, v, cls: (f'<span>{lab}</span><div class="cgnv-barra{cls}" style="width:{max(16, 100 * v / m):.0f}%">'
                                f'<b>{entero(v) if v >= 10 else num(v)} {unidad}</b></div>')
    return '<div class="cgnv-antes">' + fila("1971-1990", c["t1"], "") + fila("2006-2025", c["t2"], " cgnv-ahora") + "</div>"


def html_prov(px: dict) -> str:
    mo, ca, prov = px["monte"], px["capital"], px["provincia"]
    cmo, cca, rmo, rca = mo["clima"], ca["clima"], mo["records"], ca["records"]
    h1 = (f"<h1>{esc(titulo_prov(px))}:<span> ¿va a nevar? Previsión, cota de nieve y cuánto ha nevado</span></h1>")
    lede = (f"Si va a nevar en {ca['nombre']} o en {mo['nombre']} ({entero(mo['alt'])} m), a qué cota y cuánto, día a día "
            f"durante 15 días según cuatro modelos. Y cuánta nieve ha caído esta temporada frente a un año normal, dónde "
            f"hay nieve hoy en la provincia según el satélite y cuándo llega la primera nevada.")
    out = [CSS, '<div class="cgnv">', '<div class="cgnv-panel">',
           f'<div class="cgnv-intro"><div class="cgnv-migas"><a href="/">Inicio</a><span>/</span><a href="/nieve/">Nieve</a>'
           f'<span>/</span>{esc(prov)}</div>{h1}<p class="lede">{esc(lede)}</p></div>',
           f'<div class="cg-ssr-slot">{ANCLA}</div>', "</div>"]
    if cmo.get("total") is not None:
        out.append(f"<h2>¿Cuánto nieva en {esc(mo['nombre'])}?</h2>")
        t = (f"En una temporada normal caen unos <b>{esc(cm(cmo['total']))}</b> de nieve en {esc(mo['nombre'])}, en "
             f"{esc(entero(cmo['dias']))} días de nieve, y el suelo pasa nevado unos {esc(entero(cmo['dias_suelo']))} días. ")
        if cmo.get("p10") is not None:
            t += (f"Lo normal es que la nieve caiga entre el {esc(dia_mes(cmo['p10']))} y el {esc(dia_mes(cmo['p90']))}, con "
                  f"el centro de la temporada hacia el {esc(dia_mes(cmo['p50']))}.")
        out.append(f"<p>{t}</p>")
        out.append('<figure class="cgnv-graf"><div class="cgnv-svgw">' + svg_temporadas(mo) + "</div>"
                   "<figcaption>Nieve caída cada temporada, de agosto a julio. Las barras claras son las de 1991 a 2021, las "
                   "del año normal; la naranja, la temporada en curso hasta hoy. Fuente: ERA5-Land (Copernicus) vía "
                   "Open-Meteo.</figcaption></figure>")
    fp = frase_primera(mo)
    if fp:
        out.append(f"<h2>¿Cuándo es la primera nevada en {esc(mo['nombre'])}?</h2>")
        out.append(f"<p>{esc(fp)}</p>")
        if (mo["cambio"].get("primera") or {}).get("t1") is not None:
            out.append('<figure class="cgnv-graf cgnv-graf-des">' + svg_desplazamiento(mo) + '<figcaption>Fecha típica (mediana) '
                       'de la primera nevada del otoño en 1971-1990 y en 2006-2025. <a href="/nieve/#primera-nevada">Compárala '
                       'con el resto de España</a>.</figcaption></figure>')
        out.append('<figure class="cgnv-graf"><div class="cgnv-svgw">' + svg_primera(mo) + "</div>"
                   "<figcaption>Cada barra va de la primera a la última nevada de una temporada (días con 1 cm o más de "
                   "nieve nueva); las claras son las de 1991 a 2021. Las líneas discontinuas marcan la fecha típica de la "
                   "primera nevada en 1971-1990 y en 2006-2025. Fuente: ERA5-Land (Copernicus).</figcaption></figure>")
    fc = frase_cambio(mo)
    if fc:
        out.append(f"<h2>¿Nieva menos que antes en {esc(prov)}?</h2>")
        out.append(bloque_antes(mo["cambio"].get("total"), "cm"))
        out.append(f"<p>{esc(fc)}</p>")
        d = mo["cambio"].get("dias_suelo")
        if d and d["t1"] >= 1:
            out.append(f"<p>Los días con el suelo nevado en {esc(mo['nombre'])} han pasado de {esc(entero(d['t1']))} a "
                       f"{esc(entero(d['t2']))} por temporada entre esos dos periodos.</p>")
        dc = ca["cambio"].get("dias")
        if dc and dc["t1"] >= 0.5:
            out.append(f"<p>En {esc(ca['nombre'])}, los días de nieve han pasado de {esc(num(dc['t1']))} a "
                       f"{esc(num(dc['t2']))} al año.</p>")
    if cca.get("tipo"):
        out.append(f"<h2>¿Cuándo nieva en {esc(ca['nombre'])}?</h2>")
        if cca["tipo"] == "frecuente":
            t = (f"Sí: nieva unos {entero(cca['dias'])} días al año, sobre todo entre el {dia_mes(cca['p10'])} y el "
                 f"{dia_mes(cca['p90'])}, y caen {cm(cca['total'])} en una temporada normal.")
        elif cca["tipo"] == "ocasional":
            t = (f"Algunos inviernos: nevó en {cca['con_nieve']} de las {cca['n']} temporadas de 1991 a 2021, de media "
                 f"{num(cca['dias'])} días al año.")
        else:
            t = (f"Casi nunca: solo en {cca['con_nieve']} de las {cca['n']} temporadas de 1991 a 2021 hubo algún día con "
                 f"1 cm de nieve o más." if cca["con_nieve"] else
                 f"Prácticamente nunca: en las {cca['n']} temporadas de 1991 a 2021 no hubo ni un día con 1 cm de nieve.")
        if rca.get("ultima"):
            ev = evento(rca["ultima"]["f"])
            t += f" La última nevada apreciable fue el {fd(rca['ultima']['f'])}" + (f", con {ev}." if ev else ".")
        if rca.get("dia_max"):
            ev = evento(rca["dia_max"]["f"])
            t += (f" La mayor, la del {fd(rca['dia_max']['f'])}" + (f" ({ev})" if ev else "")
                  + f", con {cm(rca['dia_max']['cm'])} en un día.")
        out.append(f"<p>{esc(t)}</p>")
        fpc = frase_primera(ca)
        if fpc:
            out.append(f"<p>{esc(fpc)}</p>")
    out.append('<h2>Récords</h2><div class="cgnv-recs">')
    if rmo.get("temporada_max"):
        out.append(tarjeta(f"La temporada más nevada en {mo['nombre']}", cm(rmo["temporada_max"]["cm"]),
                           f"la de {rmo['temporada_max']['t']}"))
        out.append(tarjeta("La temporada con menos nieve", cm(rmo["temporada_min"]["cm"]), f"la de {rmo['temporada_min']['t']}"))
    if rmo.get("dia_max"):
        out.append(tarjeta("El día más nevado", cm(rmo["dia_max"]["cm"]), f"el {fd(rmo['dia_max']['f'])}"))
    if rmo.get("espesor_max"):
        out.append(tarjeta("El mayor espesor de nieve", cm(rmo["espesor_max"]["cm"]), f"el {fd(rmo['espesor_max']['f'])}"))
    if rca.get("dia_max"):
        out.append(tarjeta(f"La mayor nevada en {ca['nombre']}", cm(rca["dia_max"]["cm"]), f"el {fd(rca['dia_max']['f'])}"))
    out.append("</div>")
    q = preguntas_prov(px)
    out.append(faq_html(q))
    out.append(
        '<div class="cgnv-metodo"><p><b>Cómo se calcula.</b> La nieve caída y el espesor salen del reanálisis ERA5-Land de '
        'Copernicus (ECMWF), una reconstrucción del tiempo de cada día desde 1950 en una rejilla de unos 9 km, descargado de '
        'la API de archivo de Open-Meteo. Son datos de modelo, no de un nivómetro: en las cumbres suele haber más nieve y en '
        'el fondo de los valles, menos. Un día de nieve es un día con 1 cm o más de nieve nueva; cada temporada va del 1 de '
        'agosto al 31 de julio, y «un año normal» es la media de 1991-92 a 2020-21. Los últimos días, que ERA5-Land tarda '
        'una semana en publicar, se completan con el análisis del ECMWF y se dan como provisionales. La superficie nevada '
        'es la del producto diario IMS de la NOAA (4 km), y la previsión, la de los modelos ECMWF, ICON, ARPEGE y GFS, que '
        'se actualiza dos veces al día; la cota de nieve se estima 300 m por debajo de la isoterma de 0 °C. Las temporadas '
        f'se pueden <a href="{PAGES}/nieve/{esc(px["slug"])}.csv">descargar en CSV</a> (CC BY 4.0, citando a '
        'calentamientoglobal.es y a Copernicus).</p>'
        f'<p>Sigue con <a href="/nieve/">la nieve en toda España</a>, <a href="/heladas/">las heladas</a>, '
        f'<a href="/el-tiempo/{esc(px["slug"])}/">el tiempo en {esc(prov)}</a> o '
        f'<a href="/cambio-climatico-en-{esc(px["slug"])}/">el cambio climático en {esc(prov)}</a>.</p></div>')
    out.append("</div>")
    out.append(faq_jsonld(q))
    return "<!-- wp:html -->\n" + "\n".join(out) + "\n<!-- /wp:html -->"


def ssr_prov(px: dict, sat: dict) -> str:
    mo, ca = px["monte"], px["capital"]
    o, oc = mo["temporada"], ca["temporada"]
    p = ['<div class="cgnv-dia"><div class="cgnv-hoy">', f'<h2>Esta temporada en {esc(mo["nombre"])}</h2>',
         f'<p class="cgnv-hoy-v"><b>{esc(cm(o["acum"]))}</b><span>de nieve caída desde el 1 de agosto</span></p>',
         f"<p>{esc(frase_temporada(mo))}</p><ul>"]
    if o.get("esp") is not None:
        n = o.get("esp_normal")
        p.append(f"<li>Espesor hoy: <b>{esc(cm(o['esp']))}</b>"
                 + (f" (lo normal hoy: {esc(cm(n))})" if n is not None else "") + "</li>")
    if o.get("primera"):
        np_ = mo["clima"].get("primera")
        p.append(f"<li>Primera nevada de la temporada: <b>{esc(fd(o['primera'], False))}</b>"
                 + (f" (normal: {esc(dia_mes(np_))})" if np_ is not None else "") + "</li>")
    elif mo["clima"].get("primera") is not None:
        p.append(f"<li>Primera nevada: <b>aún no</b> (normal: {esc(dia_mes(mo['clima']['primera']))})</li>")
    if o.get("ultima") and o.get("ultima") != o.get("primera"):
        p.append(f"<li>Última nevada: <b>{esc(fd(o['ultima'], False))}</b></li>")
    sv = (sat.get("hoy") or {}).get(px["slug"])
    if sv is not None:
        sn = (sat.get("normal") or {}).get(px["slug"])
        p.append(f"<li>Superficie de la provincia nevada (satélite, {esc(fd(sat['fecha'], False))}): <b>{esc(pct(sv))}</b>"
                 + (f"; lo normal, {esc(pct(sn))}" if sn is not None else "") + "</li>")
    p.append("</ul>")
    enl = [f'<a href="{url_ficha(mo["id"])}">Ficha de {esc(mo["nombre"])} para compartir</a>']
    if mo["macizo"] in MACIZO_PAG:
        enl.append(f'<a href="/nieve/{MACIZO_PAG[mo["macizo"]]["slug"]}/">La nieve en {esc(MACIZO_PAG[mo["macizo"]]["corto"])}</a>')
    enl += [f'<a href="{url_ficha(e["id"])}">Ficha de {esc(e["nombre"])}</a>' for e in px["extras"]]
    p.append('<p class="cgnv-enl">' + " · ".join(enl) + "</p></div>")
    # cifras
    p.append('<div class="cgnv-cifras">')
    p.append(cifra(cm(o["ult7"]), f"de nieve en los últimos 7 días en {mo['nombre']}"))
    p.append(cifra(str(o["dias"]), "días de nieve esta temporada" + (f" (normal: {entero(mo['clima']['dias'])} al año)"
                                                                      if mo["clima"].get("dias") is not None else "")))
    p.append(cifra(cm(oc["acum"]), f"caídos en {ca['nombre']} esta temporada"))
    pv = mo["prevision"]
    p.append(cifra(cm(pv.get("total15") or 0), "previstos a 15 días en la montaña (mediana de los modelos)"))
    p.append("</div>")
    # previsión
    p.append('<div class="cgnv-prev">')
    p.append(f'<h2 class="cgnv-panel-h2">¿Va a nevar en {esc(ca["nombre"])}?</h2>')
    p.append(f'<p class="cgnv-psub"><b>{esc(ca["nombre"])}.</b> {esc(va_a_nevar(ca))}</p>')
    p.append(f'<p class="cgnv-psub"><b>{esc(mo["nombre"])}.</b> {esc(va_a_nevar(mo))}</p>')
    p.append(f"<h3>Previsión de nieve y cota de nieve en {esc(mo['nombre'])} ({esc(entero(mo['alt']))} m), día a día</h3>")
    p.append(f'<p class="cgnv-psub">{esc(resumen_prevision(pv, mo["nombre"]))}</p>')
    p.append(tabla_prevision(pv, mo["nombre"]))
    p.append(f'<p class="cgnv-pie">Cifras de modelo en centímetros de nieve nueva por día, con la hora de España. ECMWF llega a 15 días, GFS '
             f'a 16, ICON a 7 y ARPEGE a 4; más allá de una semana, toma la previsión como una tendencia. Actualizado el '
             f'{esc(fecha_larga(AHORA.astimezone(TZ).date(), False))} a las {AHORA.astimezone(TZ):%H:%M}.</p></div>')
    # gráficos de la temporada
    if mo["clima"].get("acum_media"):
        prov_txt = (f" Los últimos días, desde el {fd(o['provisional_desde'], False)}, son provisionales."
                    if o.get("provisional_desde") else "")
        p.append('<div class="cgnv-graf-p"><figure><h3>Nieve acumulada esta temporada</h3>'
                 + img_svg(f"{px['slug']}-acumulado", svg_acumulado(mo, True),
                           f"Nieve acumulada esta temporada en {mo['nombre']} frente a un año normal") +
                 f"<figcaption>Línea blanca: esta temporada. Discontinua: un año normal (1991-2021); la banda, 8 de cada "
                 f"10 temporadas.{esc(prov_txt)}</figcaption></figure>"
                 '<figure><h3>Espesor de nieve en el suelo</h3>' + img_svg(f"{px['slug']}-espesor", svg_espesor(mo, True),
                                                                          f"Espesor de nieve en {mo['nombre']} esta temporada") +
                 "<figcaption>Línea blanca: esta temporada. Zona azul: el espesor de un año normal, día a día "
                 "(mediana de 1991 a 2021).</figcaption></figure></div>")
    p.append("</div>")
    return ssr_compatible("".join(p))


# Títulos según Keyword Planner (España, oct 2025 – sept 2026): «nieve en <capital/provincia>» manda (Madrid 27.100,
# Barcelona 4.400, Murcia 3.600, Granada 2.900, Zaragoza 2.900…), seguido de «va a nevar en…» (Madrid 2.900, +367 %) y
# «cota de nieve» (27.100 en genérico). Donde la capital o la montaña se buscan más que la provincia, van en el título.
BASE_TITULO = {
    "santa-cruz-de-tenerife": "Nieve en el Teide y Tenerife", "las-palmas": "Nieve en Gran Canaria",
    "navarra": "Nieve en Navarra y Pamplona", "alava": "Nieve en Vitoria y Álava", "bizkaia": "Nieve en Bilbao y Bizkaia",
    "gipuzkoa": "Nieve en Gipuzkoa y San Sebastián", "asturias": "Nieve en Asturias y Oviedo",
    "ourense": "Nieve en Ourense y Manzaneda", "baleares": "Nieve en Mallorca", "cantabria": "Nieve en Cantabria y Alto Campoo",
    "granada": "Nieve en Granada y Sierra Nevada", "madrid": "Nieve en Madrid", "huesca": "Nieve en Huesca y Formigal",
    "lleida": "Nieve en Lleida y Baqueira", "girona": "Nieve en Girona y La Molina",
}
# eventos con nombre que conviene citar cuando un récord cae en esas fechas
EVENTOS = {("2021-01-07", "2021-01-11"): "la borrasca Filomena", ("2018-02-26", "2018-03-02"): "la ola de frío de 2018",
           ("2010-03-07", "2010-03-09"): "la nevada de marzo de 2010 en Cataluña",
           ("2009-01-08", "2009-01-10"): "la gran nevada de enero de 2009", ("2005-01-26", "2005-01-29"): "la ola de frío de 2005",
           ("1997-12-17", "1997-12-21"): "el temporal de diciembre de 1997"}


def evento(f: str) -> str:
    for (a, b), n in EVENTOS.items():
        if a <= f <= b:
            return n
    return ""


def titulo_prov(px: dict) -> str:
    return BASE_TITULO.get(px["slug"], f"Nieve en {px['provincia']}")


def metas_prov(px: dict) -> dict:
    mo, ca = px["monte"], px["capital"]
    t = f"{titulo_prov(px)}: ¿va a nevar? Previsión y cota de nieve"
    if len(t) > 66:
        t = f"{titulo_prov(px)}: previsión y cota de nieve"
    d = (f"¿Va a nevar en {ca['nombre']}? Previsión de nieve y cota de nieve a 15 días según cuatro modelos, cuánto ha "
         f"nevado este año en {mo['nombre']} y cuándo nevó por última vez en {ca['nombre']}.")
    return {"rank_math_title": t, "rank_math_description": d[:300]}


def jsonld_prov(px: dict) -> str:
    mo, ca = px["monte"], px["capital"]
    vm = []
    if mo["clima"].get("total") is not None:
        vm.append({"@type": "PropertyValue", "name": f"Nieve caída por temporada en {mo['nombre']} (media 1991-2021)",
                   "value": mo["clima"]["total"], "unitText": "cm"})
    if ca["clima"].get("dias") is not None:
        vm.append({"@type": "PropertyValue", "name": f"Días de nieve al año en {ca['nombre']} (media 1991-2021)",
                   "value": ca["clima"]["dias"], "unitText": "días"})
    d = {"@context": "https://schema.org", "@type": "Dataset",
         "name": f"Nieve en {px['provincia']}: nieve caída y espesor de cada temporada desde 1971",
         "description": (f"Nieve caída, días de nieve y espesor de nieve de cada temporada desde 1971 en {mo['nombre']} y "
                         f"{ca['nombre']}, con la temporada en curso, la superficie nevada por satélite y la previsión de "
                         f"cuatro modelos."),
         "url": url_prov(px["slug"]), "license": "https://creativecommons.org/licenses/by/4.0/",
         "creator": {"@type": "Organization", "name": "calentamientoglobal.es", "url": WEB + "/"},
         "temporalCoverage": "1971-08-01/..", "dateModified": AHORA.isoformat()[:10],
         "spatialCoverage": {"@type": "Place", "name": f"{px['provincia']}, España"},
         "variableMeasured": vm,
         "distribution": [{"@type": "DataDownload", "encodingFormat": "text/csv",
                           "contentUrl": f"{PAGES}/nieve/{px['slug']}.csv"}],
         "isBasedOn": ["https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land",
                       "https://nsidc.org/data/g02156"]}
    return json.dumps(d, ensure_ascii=False)


# ------------------------------------------------------------------------------------------------------------ hub
def resumen_macizos(xs: list, sat: dict) -> list:
    out = []
    for m in ORDEN_MACIZOS:
        ps = [x for x in xs if x["macizo"] == m]
        if not ps:
            continue
        con_esp = [x for x in ps if x["temporada"].get("esp") is not None]
        top = max(con_esp, key=lambda x: x["temporada"]["esp"]) if con_esp else None
        acs = [x["temporada"]["acum"] for x in ps]
        nos = [x["temporada"].get("normal") for x in ps if x["temporada"].get("normal") is not None]
        p7 = max(ps, key=lambda x: x["prevision"].get("total7") or 0)
        out.append({"id": m, "nombre": MACIZOS[m][0], "sub": MACIZOS[m][1], "puntos": [x["id"] for x in ps],
                    "esp_max": None if not top else {"cm": top["temporada"]["esp"], "donde": top["nombre"],
                                                     "normal": top["temporada"].get("esp_normal")},
                    "acum_media": round(st.mean(acs), 1), "normal_media": round(st.mean(nos), 1) if len(nos) == len(ps) else None,
                    "prev7": {"cm": p7["prevision"].get("total7") or 0, "donde": p7["nombre"]},
                    "sat": (sat.get("hoy") or {}).get("m_" + m), "sat_normal": (sat.get("normal") or {}).get("m_" + m)})
    return out


# ------------------------------------------------------------------------- hub: mapa pulsable, lista y primera nevada
# El mapa va en el contenido fijo (SVG con un enlace por provincia, que WordPress deja pasar en el contenido) y el bloque
# del día solo dice de qué color va cada provincia: un <span> oculto con una clase por provincia (cgnv-mc-<slug>-<nivel>)
# y reglas .cgnv:has(.cgnv-mc-<slug>-<nivel>) .cgnv-p-<slug>{fill:…}. Así el mapa es pulsable sin reescribir la página
# cada día. Sin :has() (navegadores muy viejos) el mapa sale en un solo color, pero sigue siendo pulsable.
NIVELES_MAPA = [0.5, 5, 15, 30, 50]          # % de la provincia nevado: 0 · <5 · <15 · <30 · <50 · 50 o más
COLORES_MAPA = [FONDO] + [color_nieve(min(1.0, 0.15 + v / 60)) for v in (2.5, 10, 22, 40, 60)]


def nivel_mapa(v) -> int:
    if v is None or v < NIVELES_MAPA[0]:
        return 0
    return sum(1 for u in NIVELES_MAPA if v >= u)


def css_mapa() -> str:
    r = [f".cgnv-p{{fill:{FONDO};stroke:#0c2133;stroke-width:1.2;transition:fill .2s}}",
         ".cgnv-mapa a:hover .cgnv-p,.cgnv-mapa a:focus .cgnv-p{stroke:#fff;stroke-width:2.2}",
         ".cgnv-mc{display:none}"]
    for slug, *_ in PROVINCIAS:
        for n in range(1, 6):
            r.append(f".cgnv:has(.cgnv-mc-{slug}-{n}) .cgnv-p-{slug}{{fill:{COLORES_MAPA[n]}}}")
    return "\n".join(r)


def svg_mapa_hub() -> str:
    trazos = mapa_trazos()
    W, H = round(14.6 * math.cos(math.radians(40)) * 46), round(10.0 * 46)
    s = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-labelledby="cgnv-maph" class="cgnv-svg cgnv-mapa">'
         '<title id="cgnv-maph">Mapa de la nieve en España hoy: pulsa en una provincia para ver su página</title>',
         f'<rect x="2" y="{(44 - 36.4) * 46:.0f}" width="{(5.3 * math.cos(math.radians(40)) * 46):.0f}" height="{2.6 * 46:.0f}" '
         f'rx="8" fill="none" stroke="{REJILLA}" stroke-dasharray="4 4"/>']
    for slug, prov, *_ in PROVINCIAS:
        s.append(f'<a href="/nieve/{slug}/" aria-label="Nieve en {esc(prov)}"><path class="cgnv-p cgnv-p-{slug}" '
                 f'd="{trazos.get(slug, "")}"><title>{esc(prov)}</title></path></a>')
    s.append("</svg>")
    return "".join(s)


def leyenda_mapa() -> str:
    et = ["sin nieve", "menos del 5 %", "5-15 %", "15-30 %", "30-50 %", "50 % o más"]
    return ('<div class="cgnv-ley">' + "".join(f'<span><i style="background:{c}"></i>{e}</span>'
                                               for c, e in zip(COLORES_MAPA, et)) + "</div>")


def html_lista_provincias(pxs: list) -> str:
    """La nieve de un año normal en la montaña de cada provincia, con barra, cambio y días de nieve en la capital."""
    filas = sorted([px for px in pxs if px["monte"]["clima"].get("total") is not None],
                   key=lambda p: -p["monte"]["clima"]["total"])
    if not filas:
        return ""
    mx = max(p["monte"]["clima"]["total"] for p in filas) or 1
    out = ['<div class="cgnv-lista"><div class="cgnv-lista-c"><span>Provincia y montaña</span><span>Nieve en un año normal'
           '</span><span>Cambio</span><span>Días/año en la capital</span></div>']
    for px in filas:
        mo, ca = px["monte"], px["capital"]
        c = mo["cambio"].get("total") or {}
        if c.get("pct") is None:
            chip = '<span class="cgnv-chip">—</span>'
        else:
            sig = (c.get("t") or 0) <= -2 and c["pct"] < 0
            sube = (c.get("t") or 0) >= 2 and c["pct"] > 0
            txt = ("+" if c["pct"] > 0 else "−") + entero(abs(c["pct"])) + " %"
            chip = f'<span class="cgnv-chip{" cgnv-chip-baja" if sig else " cgnv-chip-sube" if sube else ""}">{esc(txt)}</span>'
        d = ca["clima"].get("dias")
        out.append(f'<a class="cgnv-fila" href="/nieve/{esc(px["slug"])}/"><span class="cgnv-fila-n"><b>{esc(px["provincia"])}</b>'
                   f'<small>{esc(mo["nombre"])} · {esc(entero(mo["alt"]))} m</small></span>'
                   f'<span class="cgnv-fila-b"><i style="width:{max(2, 100 * mo["clima"]["total"] / mx):.0f}%"></i>'
                   f'<em>{esc(cm(mo["clima"]["total"]))}</em></span>{chip}'
                   f'<span class="cgnv-fila-d">{esc("—" if d is None else (num(d) if d < 10 else entero(d)))}</span></a>')
    out.append("</div>")
    return "".join(out)


def svg_calendario_primera(filas: list, movil: bool = False) -> str:
    """El calendario de la nieve, montaña a montaña: cada día de la temporada coloreado según en cuántas temporadas de
    1991 a 2021 nevó, con la fecha típica de la primera nevada en 1971-1990 (raya) y en 2006-2025 (punto)."""
    sf = "-m" if movil else ""
    if movil:
        W, L, R, T, FH, G, F = 380, 112, 46, 30, 13, 5, 11.5
    else:
        W, L, R, T, FH, G, F = 860, 250, 74, 34, 14, 5, 13
    lo, hi = indice(date(2021, 9, 1)), indice(date(2022, 6, 30))
    AN = W - L - R
    H = T + len(filas) * (FH + G) + 30
    X = lambda i: L + AN * (min(max(i, lo), hi) - lo + 0.5) / (hi - lo + 1)
    s = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-labelledby="cgnv-cal{sf}" class="cgnv-svg">'
         f'<title id="cgnv-cal{sf}">Calendario de la nieve en {len(filas)} montañas de España y cuánto se ha movido la primera '
         f'nevada entre 1971-1990 y 2006-2025</title>']
    for m, lab in MESES_EJE:
        i = indice(date(2021 if m >= 8 else 2022, m, 1))
        if lo <= i <= hi and not (movil and m % 2 == 0):
            s.append(f'<text x="{X(i + 14):.1f}" y="{T - 12}" font-size="{F}" text-anchor="middle" fill="{GRIS}">{lab}</text>')
    s.append(f'<text x="{W}" y="{T - 12}" font-size="{F}" text-anchor="end" fill="{GRIS}">{"días" if movil else "cambio"}</text>')
    for k, x in enumerate(filas):
        y = T + k * (FH + G)
        c, cp = x["clima"], x["cambio"]["primera"]
        prob = [v or 0 for v in suave(c.get("prob") or [0] * 365, 3)]
        nombre = x["nombre"]
        lim = 15 if movil else 30
        if len(nombre) > lim:
            nombre = nombre[:lim - 1] + "…"
        s.append(f'<a href="/nieve/{esc(x["prov"])}/"><text x="{L - 8}" y="{y + FH - 2}" font-size="{F}" text-anchor="end" '
                 f'fill="{TINTA}" class="cgnv-cal-n">{esc(nombre)}</text></a>')
        s.append(f'<rect x="{L}" y="{y}" width="{AN}" height="{FH}" rx="3" fill="#0f2a40"/>')
        # tramos de color (rachas de días con el mismo color)
        i = lo
        while i <= hi:
            p = prob[i]
            if p < 0.01:
                i += 1
                continue
            col = color_nieve(min(1.0, p / 0.4))
            j = i
            while j + 1 <= hi and prob[j + 1] >= 0.01 and color_nieve(min(1.0, prob[j + 1] / 0.4)) == col:
                j += 1
            s.append(f'<rect x="{X(i) - AN / (hi - lo + 1) / 2:.1f}" y="{y}" width="{(j - i + 1) * AN / (hi - lo + 1) + 0.4:.1f}" '
                     f'height="{FH}" fill="{col}"/>')
            i = j + 1
        x1, x2 = X(cp["t1"]), X(cp["t2"])
        col = BRASA if cp["dias"] >= 3 and (cp.get("t") or 0) >= 2 else "#ffffff"
        s.append(f'<line x1="{x1:.1f}" x2="{x2:.1f}" y1="{y + FH / 2:.1f}" y2="{y + FH / 2:.1f}" stroke="{col}" stroke-width="2"/>'
                 f'<line x1="{x1:.1f}" x2="{x1:.1f}" y1="{y - 1}" y2="{y + FH + 1}" stroke="{col}" stroke-width="2"/>'
                 f'<circle cx="{x2:.1f}" cy="{y + FH / 2:.1f}" r="{3.6 if movil else 4.2}" fill="{col}" stroke="#0c2133" '
                 f'stroke-width="1.2"><title>{esc(x["nombre"])}: primera nevada típica hacia el {esc(dia_mes(cp["t1"]))} en '
                 f'1971-1990 y hacia el {esc(dia_mes(cp["t2"]))} en 2006-2025</title></circle>')
        d = cp["dias"]
        txt = "=" if abs(d) < 3 else (("+" if d > 0 else "−") + str(abs(d)) + (" d" if movil else " días"))
        s.append(f'<text x="{W}" y="{y + FH - 2}" font-size="{F}" text-anchor="end" font-weight="700" '
                 f'fill="{BRASA if d >= 3 and (cp.get("t") or 0) >= 2 else GRIS if abs(d) < 3 else TINTA}">{esc(txt)}</text>')
    s.append("</svg>")
    return "".join(s)


def html_primera_hub(montes: list) -> str:
    filas = sorted([x for x in montes if (x["cambio"].get("primera") or {}).get("t1") is not None],
                   key=lambda x: x["cambio"]["primera"]["t2"])
    if len(filas) < 3:
        return ""
    dl = [x["cambio"]["primera"]["dias"] for x in filas]
    med = st.median(dl)
    tarde = [x for x in filas if x["cambio"]["primera"]["dias"] >= 3]
    sig = [x for x in tarde if (x["cambio"]["primera"].get("t") or 0) >= 2]
    out = ['<h2 id="primera-nevada">¿Llega más tarde la primera nevada? Historia de las primeras nevadas en España</h2>']
    t = (f"En {len(tarde)} de las {len(filas)} montañas de referencia la primera nevada del otoño llega hoy más tarde que "
         f"en 1971-1990")
    t += (f": de mediana, {entero(abs(med))} días {'más tarde' if med > 0 else 'antes'}." if abs(med) >= 1 else
          ", aunque de mediana la fecha apenas se ha movido.")
    if sig:
        t += (f" En {len(sig)} el retraso es estadísticamente significativo, no ruido de unos pocos inviernos: "
              + lista([f"{x['nombre']} ({x['cambio']['primera']['dias']} días)"
                       for x in sorted(sig, key=lambda x: -x["cambio"]["primera"]["dias"])[:3]]) + ".")
    out.append(f"<p>{esc(t)}</p>")
    out.append('<figure class="cgnv-graf"><div class="cgnv-d">' + svg_calendario_primera(filas) + '</div><div class="cgnv-m">'
               + svg_calendario_primera(filas, True) + '</div><div class="cgnv-clave"><span class="cgnv-escala">nevó en pocas '
               'temporadas<span class="cgnv-esc"></span>en muchas</span><span>raya: primera nevada típica en 1971-1990 · '
               'punto: en 2006-2025 · en naranja, retrasos significativos</span></div><figcaption>Cada fila es la montaña de '
               'referencia de una provincia y cada columna, un día de septiembre a junio: cuanto más blanco, en más temporadas '
               'de 1991 a 2021 nevó ese día (1 cm o más). A la derecha, cuántos días se ha movido la primera nevada. Pulsa en '
               'una montaña para ver su provincia. Fuente: ERA5-Land (Copernicus).</figcaption></figure>')
    top = sorted(tarde, key=lambda x: -x["cambio"]["primera"]["dias"])[:8]
    if top:
        out.append("<h3 class=\"cgnv-h3\">Donde más se ha retrasado</h3>")
        mx = max(x["cambio"]["primera"]["dias"] for x in top)
        out.append('<div class="cgnv-retrasos">')
        for x in top:
            cp = x["cambio"]["primera"]
            out.append(f'<a class="cgnv-ret" href="/nieve/{esc(x["prov"])}/"><span class="cgnv-ret-n">{esc(x["nombre"])}'
                       f'<small>{esc(x["provincia"])}</small></span><span class="cgnv-ret-f">{esc(dia_mes(cp["t1"]))} → '
                       f'<b>{esc(dia_mes(cp["t2"]))}</b></span><span class="cgnv-ret-b"><i style="width:{100 * cp["dias"] / mx:.0f}%">'
                       f'</i></span><span class="cgnv-ret-d">+{cp["dias"]} días</span></a>')
        out.append('</div><p class="cgnv-nota">Fecha típica (mediana) de la primera nevada del otoño en 1971-1990 → en '
                   '2006-2025.</p>')
    return "".join(out)


def svg_desplazamiento(x: dict) -> str:
    """Una línea de septiembre a enero con la primera nevada típica de 1971-1990 y la de 2006-2025."""
    cp = x["cambio"].get("primera")
    if not cp:
        return ""
    W, H, L, R = 760, 120, 20, 20
    lo, hi = indice(date(2021, 9, 1)), indice(date(2022, 1, 31))
    lo = min(lo, cp["t1"] - 10, cp["t2"] - 10)
    hi = max(hi, cp["t1"] + 10, cp["t2"] + 10)
    X = lambda i: L + (W - L - R) * (i - lo) / (hi - lo)
    y = 70
    s = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-labelledby="cgnv-des" class="cgnv-svg">'
         f'<title id="cgnv-des">Primera nevada típica en {esc(x["nombre"])}: hacia el {esc(dia_mes(cp["t1"]))} en 1971-1990 y '
         f'hacia el {esc(dia_mes(cp["t2"]))} en 2006-2025</title>',
         f'<line x1="{L}" x2="{W - R}" y1="{y}" y2="{y}" stroke="{REJILLA}" stroke-width="2"/>']
    for m, lab in MESES_EJE:
        i = indice(date(2021 if m >= 8 else 2022, m, 1))
        if lo <= i <= hi:
            s.append(f'<line x1="{X(i):.1f}" x2="{X(i):.1f}" y1="{y - 5}" y2="{y + 5}" stroke="{REJILLA}"/>'
                     f'<text x="{X(i) + 4:.1f}" y="{y + 26}" font-size="13" fill="{GRIS}">1 {lab}</text>')
    x1, x2 = X(cp["t1"]), X(cp["t2"])
    col = BRASA if abs(cp["dias"]) >= 3 else TINTA
    s.append(f'<line x1="{x1:.1f}" x2="{x2:.1f}" y1="{y}" y2="{y}" stroke="{col}" stroke-width="5" stroke-linecap="round"/>'
             f'<circle cx="{x1:.1f}" cy="{y}" r="8" fill="#0c2133" stroke="#bfe6ff" stroke-width="3"/>'
             f'<circle cx="{x2:.1f}" cy="{y}" r="9" fill="#fff" stroke="{col}" stroke-width="3"/>')
    izq = x1 <= x2
    s.append(f'<text x="{x1:.1f}" y="{y - 22}" font-size="14" text-anchor="{"end" if izq else "start"}" fill="#bfe6ff">'
             f'1971-1990: {esc(dia_mes(cp["t1"]))}</text>'
             f'<text x="{x2:.1f}" y="{y - 22}" font-size="15" font-weight="700" text-anchor="{"start" if izq else "end"}" '
             f'fill="#ffffff">2006-2025: {esc(dia_mes(cp["t2"]))}</text>')
    s.append("</svg>")
    return "".join(s)



def html_hub(pxs: list, xs: list) -> str:
    montes = [px["monte"] for px in pxs]
    con_clima = [x for x in montes if x["clima"].get("total") is not None]
    out = [CSS, '<div class="cgnv">', '<div class="cgnv-panel cgnv-panel-hub">',
           '<div class="cgnv-intro"><div class="cgnv-migas"><a href="/">Inicio</a><span>/</span>Nieve</div>'
           '<h1>Nieve en España:<span> dónde hay nieve hoy, cota de nieve y previsión de nevadas</span></h1>'
           '<p class="lede">El mapa de la nieve en España cada mañana, según el satélite; dónde va a nevar y a qué cota en los '
           'próximos 15 días, según cuatro modelos; y cuánta nieve ha caído esta temporada en cada montaña y en cada capital '
           'frente a los inviernos desde 1971.</p></div>',
           '<div class="cgnv-mapaw">' + svg_mapa_hub() + leyenda_mapa() + '</div>',
           f'<div class="cg-ssr-slot">{ANCLA}</div>', "</div>"]
    out[0] = out[0].replace("</style>", css_mapa() + "\n</style>")
    if con_clima:
        out.append("<h2>La nieve de un año normal, provincia a provincia</h2>")
        out.append("<p>Nieve caída en una temporada normal (1991-92 a 2020-21) en la montaña de referencia de cada provincia y "
                   "días de nieve al año en su capital. Y cómo ha cambiado entre 1971-1990 y 2006-2025.</p>")
        out.append(html_lista_provincias(pxs))
        out.append('<p class="cgnv-nota">En rojo, las bajadas con una tendencia estadísticamente significativa desde 1971; en azul, las subidas. '
                   'Son datos de modelo en celdas de unos 9 km: en las cumbres hay más nieve que la que se ve aquí.</p>')
        bajan = [x for x in con_clima if (x["cambio"].get("total") or {}).get("t") is not None
                 and x["cambio"]["total"]["t"] <= -2 and (x["cambio"]["total"].get("pct") or 0) < 0]
        if bajan:
            out.append("<h2>¿Nieva menos que antes en España?</h2>")
            peor = sorted(bajan, key=lambda x: x["cambio"]["total"]["pct"])[:3]
            out.append(f"<p>En {len(bajan)} de las {len(con_clima)} montañas de referencia nieva hoy claramente menos que hace "
                       f"cincuenta años, con una tendencia estadísticamente significativa. Donde más ha bajado: "
                       + esc(lista([f"{x['nombre']} ({x['provincia']}), un {entero(-x['cambio']['total']['pct'])} % menos"
                                    for x in peor])) + ".</p>")
    out.append(html_primera_hub(montes))
    q = [("¿Dónde nieva más en España?",
          "En el Pirineo, la Cordillera Cantábrica y las cumbres de Sierra Nevada, el Sistema Central y el Sistema Ibérico. "
          "Por debajo de 1.000 metros, la nieve es escasa salvo en el norte de la Meseta, Soria, Teruel o Burgos."),
         ("¿Cómo se sabe cuánta parte de España está nevada?",
          "Con el producto IMS de la NOAA, que cada día combina imágenes de satélite ópticas y de microondas en una rejilla "
          "de 4 km y marca cada celda como nevada o no. Las nubes no lo ciegan del todo porque también usa microondas y "
          "estaciones en tierra."),
         ("¿Dónde hay nieve hoy en España?",
          "El mapa de arriba lo dice cada mañana con el satélite IMS de la NOAA: qué parte de cada provincia y de cada macizo "
          "está cubierta de nieve, comparada con lo normal en la misma fecha desde 2005."),
         ("¿Dónde va a nevar estos días?",
          "La previsión de arriba junta los modelos ECMWF, ICON, ARPEGE y GFS en 106 puntos de España y se actualiza tres "
          "veces al día: dónde va a nevar en los próximos 7 días, cuánto y a qué cota. En la página de cada provincia está "
          "el detalle día a día a 15 días."),
         ("¿Qué es la cota de nieve?",
          "La altitud a partir de la cual la precipitación cae en forma de nieve. Suele estar unos 300 metros por debajo de "
          "la isoterma de 0 °C, que es como se estima aquí con los datos de cada modelo."),
         ("¿Qué modelo acierta más con la nieve?",
          "A más de tres o cuatro días, el ECMWF suele ser el más fiable de media; ICON y ARPEGE tienen más detalle a corto "
          "plazo y GFS es el que más lejos llega. Cuando todos coinciden, la previsión es mucho más segura.")]
    if con_clima:
        top = max(con_clima, key=lambda x: x["clima"]["total"])
        q.insert(0, ("¿Cuánta nieve cae en una temporada normal?",
                     f"Depende mucho de la altitud. De las montañas de referencia, la más nevada es {top['nombre']} "
                     f"({top['provincia']}), con unos {cm(top['clima']['total'])} por temporada (1991-2021, ERA5-Land)."))
    out.append(faq_html(q))
    out.append('<div class="cgnv-metodo"><p><b>Cómo se calcula.</b> Tres fuentes abiertas: el reanálisis ERA5-Land de '
               'Copernicus (nieve caída y espesor, día a día desde 1971, en 106 puntos: cada capital, una montaña de referencia '
               'por provincia y seis estaciones de esquí más), el producto diario de superficie nevada IMS de la NOAA (4 km, '
               'desde 2005) y la previsión de los modelos ECMWF, ICON, ARPEGE y GFS a través de Open-Meteo. «Un año normal» es '
               'la media de las temporadas de 1991-92 a 2020-21. Las cifras de ERA5-Land son de modelo, en celdas de unos 9 km, '
               'y sirven para comparar unos años con otros, no para saber cuánta nieve hay en una pista concreta. Datos en '
               f'<a href="{PAGES}/nieve/index.json">JSON</a> y <a href="{PAGES}/nieve/satelite.csv">CSV</a> (CC BY 4.0).</p>'
               '<p>Sigue con <a href="/heladas/">las heladas en cada ciudad</a>, <a href="/avisos-meteorologicos-activos/">'
               'los avisos meteorológicos</a>, <a href="/el-tiempo/">el tiempo municipio a municipio</a> o '
               '<a href="/metodologia/">la metodología</a>.</p></div>')
    out.append("</div>")
    out.append(faq_jsonld(q))
    return "<!-- wp:html -->\n" + "\n".join(out) + "\n<!-- /wp:html -->"


CERCA = {"Madrid": ["madrid-monte", "valdesqui", "segovia-monte", "avila-monte", "guadalajara-monte"],
         "Barcelona": ["barcelona-monte", "girona-monte", "port-aine", "lleida-monte"],
         "Valencia": ["valencia-monte", "teruel-monte", "valdelinares", "castellon-monte", "cuenca-monte"]}


def tabla_cotas(xs: list) -> str:
    """Cota de nieve de los próximos 7 días, macizo a macizo (mediana de sus puntos, solo los días con precipitación)."""
    ref = next((x for x in xs if x["prevision"].get("dias")), None)
    if not ref:
        return ""
    ds = [date.fromisoformat(f) for f in ref["prevision"]["dias"][:7]]
    filas = []
    for m in ORDEN_MACIZOS:
        ps = [x for x in xs if x["macizo"] == m and x["prevision"].get("dias")]
        if not ps:
            continue
        cel = []
        for j in range(len(ds)):
            cs = [x["prevision"]["cota"][j] for x in ps if j < len(x["prevision"]["cota"]) and x["prevision"]["cota"][j] is not None]
            nv = max((x["prevision"]["consenso"][j] or 0) for x in ps if j < len(x["prevision"]["consenso"]))
            if not cs:
                cel.append('<td class="cgnv-nd">·</td>')
                continue
            c = int(st.median(cs)) // 100 * 100
            p_ = escala_cm(nv)
            fondo = f' style="background:{color_nieve(p_)}"' if p_ > 0 else ""
            cel.append(f'<td class="{"cgnv-claro" if p_ < 0.5 else ""}"{fondo} title="{esc(MACIZOS[m][0])}: cota {c} m, '
                       f'hasta {esc(cm(nv))} de nieve">{c if c < 3500 else "—"}</td>')
        filas.append(f'<tr><th class="cgnv-mod">{esc(MACIZOS[m][0])}</th>{"".join(cel)}</tr>')
    cab = "<tr><th></th>" + "".join(
        f'<th class="{"cgnv-fin" if d.weekday() >= 5 else ""}">{"hoy" if d == HOY else DIAS_C[d.weekday()]}<b>{d.day}</b></th>'
        for d in ds) + "</tr>"
    return ('<h2 class="cgnv-panel-h2" style="margin-top:22px">Cota de nieve hoy y los próximos días</h2>'
            '<p class="cgnv-psub">Altitud en metros a partir de la cual nevaría en cada macizo, los días en que los modelos '
            'prevén precipitación (mediana de sus puntos y de los cuatro modelos). El fondo, más blanco cuanta más nieve '
            'nueva.</p><div class="cgnv-tw"><table class="cgnv-tp" style="min-width:560px"><thead>' + cab + "</thead><tbody>"
            + "".join(filas) + "</tbody></table></div>")


def bloque_cerca(xs: list) -> str:
    xi = {x["id"]: x for x in xs}
    p = ['<h2 class="cgnv-panel-h2" style="margin-top:22px">¿Dónde hay nieve cerca de Madrid, Barcelona y Valencia?</h2>'
         '<div class="cgnv-macs" style="margin-top:0">']
    for ciudad, ids in CERCA.items():
        ps = [xi[i] for i in ids if i in xi]
        p.append(f'<div class="cgnv-mac"><h3>Nieve cerca de {esc(ciudad)}</h3><dl class="cgnv-cerca">'
                 '<dt></dt><dd>hoy</dd><dd>7 días</dd>')
        for x in ps:
            e = x["temporada"].get("esp")
            p7 = x["prevision"].get("total7") or 0
            p.append(f'<dt><a href="/nieve/{esc(x["prov"])}/">{esc(x["nombre"])}</a></dt>'
                     f'<dd>{esc(cm(e) if e is not None else "—")}</dd><dd>{"+" + esc(cm(p7)) if p7 >= 1 else "—"}</dd>')
        p.append("</dl></div>")
    p.append('</div><p class="cgnv-pnota">Espesor de nieve hoy en el suelo (modelo) y nieve nueva prevista para la próxima '
             'semana. Son cifras de modelo en celdas de unos 9 km: para el estado de las pistas, el parte oficial de cada '
             'estación.</p>')
    return "".join(p)


def ssr_hub(pxs: list, xs: list, sat: dict, macs: list) -> str:
    p = ['<div class="cgnv-dia"><div class="cgnv-hoy"><h2>Mapa de la nieve en España hoy, según el satélite</h2>']
    hoy = sat.get("hoy") or {}
    if hoy.get("espana") is not None:
        n = (sat.get("normal") or {}).get("espana")
        p.append(f'<p class="cgnv-hoy-v"><b>{esc(pct(hoy["espana"]))}</b><span>del territorio cubierto de nieve el '
                 f'{esc(fd(sat["fecha"], False))}</span></p><p>Unos {esc(entero(hoy.get("espana_km2") or 0))} km²'
                 + (f"; lo normal en esta fecha es un {esc(pct(n))} (mediana de los inviernos desde {SAT_DESDE})." if n is not None
                    else ".") + "</p><ul>")
        if sat.get("max_temporada") and sat["max_temporada"]["pct"] is not None:
            mt = sat["max_temporada"]
            p.append(f"<li>Máximo de esta temporada: <b>{esc(pct(mt['pct']))}</b>, el {esc(fd(mt['f'], False))}</li>")
        if sat.get("max_inviernos"):
            r = sat["max_inviernos"][0]
            p.append(f"<li>Récord desde {SAT_DESDE}: <b>{esc(pct(r['pct']))}</b>, el {esc(fd(r['f']))}</li>")
        p.append("</ul>")
    else:
        p.append("<p>El dato del satélite de hoy todavía no está disponible.</p>")
    p.append("</div>")
    # mapa
    vals = {px["slug"]: hoy.get(px["slug"]) for px in pxs}
    top = sorted([(v, px) for px in pxs for v in [vals[px["slug"]]] if v is not None and v >= 0.5], key=lambda z: -z[0])
    p.append('<span class="cgnv-mc ' + " ".join(f"cgnv-mc-{px['slug']}-{nivel_mapa(vals[px['slug']])}" for px in pxs)
             + '"></span>')
    p.append('<div class="cgnv-top"><h2 class="cgnv-panel-h2">Dónde hay nieve hoy: las provincias más blancas</h2>')
    if top:
        p.append("<ol>" + "".join(f'<li><a href="/nieve/{esc(px["slug"])}/">{esc(px["provincia"])}</a><b>{esc(pct(v))}</b></li>'
                                  for v, px in top[:8]) + "</ol>")
    else:
        p.append("<p>Hoy no hay nieve apreciable en ninguna provincia según el satélite.</p>")
    p.append('<p class="cgnv-pnota">Cuanto más blanca la provincia en el mapa, más parte de su superficie está nevada. Pulsa en una '
             'para ver su página.</p></div>')
    # previsión
    lugares = []
    for x in xs:
        pv = x["prevision"]
        if (pv.get("total7") or 0) >= 2:
            lugares.append((pv["total7"], x))
    lugares.sort(key=lambda z: -z[0])
    p.append('<div class="cgnv-prev">')
    if lugares:
        p.append(f"<h2 class=\"cgnv-panel-h2\">¿Dónde va a nevar? Los próximos 7 días</h2><p class=\"cgnv-psub\">Nieve nueva prevista en {len(lugares)}"
                 f" de los {len(xs)} puntos vigilados (mediana de los cuatro modelos). Los de más nieve:</p>"
                 '<ul class="cgnv-chips">')
        for v, x in lugares[:14]:
            cota = [c for c, n in zip(x["prevision"]["cota"][:7], x["prevision"]["consenso"][:7])
                    if c is not None and (n or 0) >= UMBRAL_DIA]
            p.append(f'<li class="cgnv-chip-n"><a href="/nieve/{esc(x["prov"])}/">{esc(x["nombre"])}</a> <b>{esc(cm(v))}</b>'
                     + (f" · cota {esc(entero(min(cota)))} m" if cota else "") + "</li>")
        p.append("</ul>")
    else:
        p.append('<h2 class="cgnv-panel-h2">¿Dónde va a nevar? Los modelos no ven nevadas apreciables en 7 días</h2>')
    lejos = [(x["prevision"].get("total15") or 0) - (x["prevision"].get("total7") or 0) for x in xs]
    if max(lejos + [0]) >= 5:
        x = xs[max(range(len(xs)), key=lambda k: lejos[k])]
        p.append(f'<p class="cgnv-pie">Más allá de una semana, los modelos apuntan a más nieve en {esc(x["nombre"])} '
                 f'({esc(cm(lejos[xs.index(x)]))} entre los días 8 y 15), una tendencia que aún puede cambiar mucho.</p>')
    p.append(tabla_cotas(xs))
    p.append(bloque_cerca(xs))
    p.append(f'<p class="cgnv-pie">Previsión de ECMWF, ICON, ARPEGE y GFS. Actualizado el '
             f'{esc(fecha_larga(AHORA.astimezone(TZ).date(), False))} a las {AHORA.astimezone(TZ):%H:%M}.</p></div>')
    # macizos: cada tarjeta lleva a la página del macizo
    p.append('<div class="cgnv-macs"><h2 class="cgnv-panel-h2 cgnv-macs-h">La nieve, macizo a macizo</h2>')
    for m in macs:
        e = m["esp_max"]
        url = f"/nieve/{MACIZO_PAG[m['id']]['slug']}/"
        p.append(f'<div class="cgnv-mac"><h3><a href="{url}">{esc(m["nombre"])}</a></h3><p class="cgnv-mac-s">{esc(m["sub"])}</p>')
        p.append(f'<span class="cgnv-mac-n">{esc(cm(e["cm"]) if e else "—")}</span>'
                 + '<p class="cgnv-mac-l">' + (f'de espesor en {esc(e["donde"])}'
                                               + (f" (normal: {esc(cm(e['normal']))})" if e.get("normal") is not None else "")
                                               if e else "espesor sin dato") + "</p><dl>")
        p.append(f"<dt>Caída esta temporada</dt><dd>{esc(cm(m['acum_media']))}"
                 + (f" <span style=\"color:#8fa9bd;font-weight:400\">/ {esc(cm(m['normal_media']))}</span>"
                    if m["normal_media"] is not None else "") + "</dd>")
        if m["sat"] is not None:
            p.append(f"<dt>Nevado hoy (satélite)</dt><dd>{esc(pct(m['sat']))}</dd>")
        p.append(f"<dt>Próximos 7 días</dt><dd>{esc(cm(m['prev7']['cm']))}</dd></dl>"
                 f'<p class="cgnv-mac-a"><a href="{url}">Ver {esc(MACIZO_PAG[m["id"]]["corto"])} →</a> · '
                 f'<a href="{PAGES}/nieve/ficha.html?m={m["id"]}">Ficha para compartir</a></p></div>')
    p.append("</div>")
    if sat.get("serie") and any(v is not None for v in sat["serie"]):
        p.append('<div class="cgnv-graf-p" style="grid-template-columns:1fr"><figure><h3>España cubierta de nieve, día a día'
                 '</h3><div class="cgnv-d">' + img_svg("satelite-temporada", svg_sat_temporada(sat),
                                                       "Parte de España cubierta de nieve cada día de esta temporada")
                 + '</div><div class="cgnv-m">' + img_svg("satelite-temporada-m", svg_sat_temporada(sat, True),
                                                          "Parte de España cubierta de nieve cada día de esta temporada")
                 + "</div><figcaption>Línea blanca: esta temporada. Discontinua: la mediana de "
                 f"los inviernos desde {SAT_DESDE}; la banda, 8 de cada 10 inviernos. Fuente: NOAA IMS, 4 km."
                 "</figcaption></figure></div>")
    p.append("</div>")
    return ssr_compatible("".join(p))


# --------------------------------------------------------------------------------------------- macizos y fichas
# Una página por macizo (/nieve/<slug>/) y una ficha para compartir por montaña, estación de esquí y macizo
# (docs/nieve/ficha.html la dibuja con los datos de docs/nieve/fichas.json). Títulos según Keyword Planner
# (España, oct 2025 – sept 2026): «nieve sierra nevada» 1.300 + «hay nieve en sierra nevada» 1.000 + «nieve en
# sierra nevada» 1.900; «nieve pirineo» 720; «nieve sierra de madrid» 390; «nieve gredos» 170; «nieve teide» 1.900.
MACIZO_PAG = {
    "pirineo": {"slug": "pirineo", "corto": "el Pirineo", "titulo": "Nieve en el Pirineo",
                "sub": "espesor, nevadas y previsión en Formigal, Baqueira, La Molina y Candanchú",
                "rm": "Nieve en el Pirineo hoy: espesor y previsión a 15 días"},
    "cantabrica": {"slug": "cordillera-cantabrica", "corto": "la Cordillera Cantábrica",
                   "titulo": "Nieve en la Cordillera Cantábrica",
                   "sub": "Alto Campoo, San Isidro, Valgrande-Pajares y Leitariegos",
                   "rm": "Nieve en la Cordillera Cantábrica: espesor y previsión"},
    "iberica": {"slug": "sistema-iberico", "corto": "el Sistema Ibérico", "titulo": "Nieve en el Sistema Ibérico",
                "sub": "Moncayo, Javalambre, Valdelinares, Urbión y la Demanda",
                "rm": "Nieve en el Sistema Ibérico: Javalambre, Moncayo y más"},
    "central": {"slug": "sistema-central", "corto": "la sierra de Madrid y el Sistema Central",
                "titulo": "Nieve en la sierra de Madrid y el Sistema Central",
                "sub": "Navacerrada, Valdesquí, La Pinilla, Gredos y La Covatilla",
                "rm": "Nieve en la sierra de Madrid: Navacerrada y Gredos"},
    "nevada": {"slug": "sierra-nevada", "corto": "Sierra Nevada", "titulo": "¿Hay nieve en Sierra Nevada?",
               "sub": "espesor, nevadas y previsión en Pradollano y Calar Alto",
               "rm": "¿Hay nieve en Sierra Nevada? Espesor y previsión"},
    "beticas": {"slug": "sierras-beticas", "corto": "las Sierras Béticas", "titulo": "Nieve en las Sierras Béticas",
                "sub": "Cazorla, Grazalema, Sierra de las Nieves, Aitana y Revolcadores",
                "rm": "Nieve en las Sierras Béticas: Cazorla, Grazalema"},
    "galaico": {"slug": "galicia", "corto": "las montañas de Galicia", "titulo": "Nieve en Galicia",
                "sub": "Manzaneda, Os Ancares y las sierras gallegas",
                "rm": "Nieve en Galicia: Manzaneda y Os Ancares, previsión"},
    "vasco": {"slug": "montes-vascos", "corto": "los montes vascos", "titulo": "Nieve en los montes vascos",
              "sub": "Gorbea, Aralar y Urkiola", "rm": "Nieve en los montes vascos: Gorbea, Aralar, Urkiola"},
    "morena": {"slug": "sierra-morena", "corto": "Sierra Morena", "titulo": "Nieve en Sierra Morena y los Montes de Toledo",
               "sub": "Aracena, Tentudía, Sierra Madrona y los Montes de Toledo",
               "rm": "Nieve en Sierra Morena y los Montes de Toledo"},
    "canarias": {"slug": "canarias", "corto": "Canarias", "titulo": "Nieve en Canarias",
                 "sub": "el Teide y el Pico de las Nieves", "rm": "Nieve en Canarias: el Teide y el Pico de las Nieves"},
    "tramuntana": {"slug": "mallorca", "corto": "Mallorca", "titulo": "Nieve en Mallorca",
                   "sub": "la Serra de Tramuntana", "rm": "Nieve en Mallorca: Serra de Tramuntana y previsión"},
}


def de(t: str) -> str:
    """«de el Pirineo» → «del Pirineo»."""
    return "del " + t[3:] if t.startswith("el ") else "de " + t


def url_ficha(pid: str = "", macizo: str = "") -> str:
    return f"{PAGES}/nieve/ficha.html?" + (f"m={macizo}" if macizo else f"id={pid}")


def mejor_dia(x: dict) -> dict | None:
    """El mejor día para ir esta semana: nieve recién caída (los dos días anteriores), poco viento, sin lluvia y sin
    una nevada tan fuerte que cierre accesos. Solo si hay nieve en el suelo (o la va a haber) según el modelo."""
    pv, o = x["prevision"], x["temporada"]
    if not pv.get("dias"):
        return None
    cons = [v or 0.0 for v in pv["consenso"][:7]]
    esp = (o.get("esp") or 0) + sum(cons)
    if esp < 10:
        return None
    mejor, puntos = None, -1e9
    for j, f in enumerate(pv["dias"][:7]):
        fresca = sum(cons[max(0, j - 2):j])
        racha = (pv.get("racha") or [None] * 7)[j] or 0
        cota = pv["cota"][j]
        lluvia = (pv.get("precip") or [0] * 7)[j] or 0
        sc = 2 * fresca - (12 if racha >= 70 else 5 if racha >= 50 else 0) - (8 if cons[j] >= 15 else 0)
        if lluvia >= 1 and cota is not None and cota > x["alt"]:
            sc -= 10
        if date.fromisoformat(f).weekday() >= 5:
            sc += 0.5   # a igualdad, el fin de semana
        if sc > puntos:
            mejor, puntos = (f, fresca, racha), sc
    f, fresca, racha = mejor
    motivo = []
    if fresca >= 3:
        motivo.append(f"{cm(fresca)} de nieve recién caída")
    if racha and racha < 40:
        motivo.append("poco viento")
    elif racha >= 50:
        motivo.append(f"aunque con rachas de {entero(racha)} km/h")
    return {"f": f, "motivo": lista(motivo) or "el día con mejores condiciones de la semana"}


def ficha_punto(x: dict) -> dict:
    o, pv, c = x["temporada"], x["prevision"], x["clima"]
    dias = []
    for j, f in enumerate(pv.get("dias", [])[:7]):
        dias.append({"f": f, "n": pv["consenso"][j], "cota": pv["cota"][j], "tx": (pv.get("tx") or [None] * 16)[j],
                     "tn": (pv.get("tn") or [None] * 16)[j], "racha": (pv.get("racha") or [None] * 16)[j]})
    prox = next(({"f": f, "cm": v} for f, v in zip(pv.get("dias", []), pv.get("consenso", []))
                 if v is not None and v >= UMBRAL_DIA), None)
    mac = x["macizo"] if x["macizo"] in MACIZO_PAG else None   # Montes Torozos (Valladolid) no tiene página de macizo
    return {"id": x["id"], "nombre": x["nombre"], "alt": x["alt"], "tipo": x["tipo"], "prov": x["prov"],
            "provincia": x["provincia"], "macizo": mac, "macizo_nombre": MACIZOS[mac][0] if mac else None,
            "url": f"{WEB}/nieve/{x['prov']}/",
            "url_macizo": f"{WEB}/nieve/{MACIZO_PAG[mac]['slug']}/" if mac else None,
            "esp": o.get("esp"), "esp_normal": o.get("esp_normal"), "n24": o.get("ult1"), "n7": o.get("ult7"),
            "acum": o.get("acum"), "acum_normal": o.get("normal"), "ultima": o.get("ultima"),
            "primera_normal": dia_mes(c["primera"]) if c.get("primera") is not None else None,
            "total7": pv.get("total7"), "total15": pv.get("total15"), "proxima": prox, "dias": dias,
            "mejor": mejor_dia(x), "frase": va_a_nevar(x)}


def ficha_macizo(m: dict, xs: list) -> dict:
    ps = sorted([x for x in xs if x["macizo"] == m["id"]], key=lambda x: -(x["temporada"].get("esp") or 0))
    fs = [ficha_punto(x) for x in ps]
    # «próximos 7 días» del macizo: el máximo de sus puntos cada día (donde más nieva)
    dias = []
    if fs and fs[0]["dias"]:
        for j, d in enumerate(fs[0]["dias"]):
            ns = [(f["dias"][j]["n"] or 0, f) for f in fs if len(f["dias"]) > j]
            v, top = max(ns, key=lambda z: z[0])
            cotas = [f["dias"][j]["cota"] for f in fs if len(f["dias"]) > j and f["dias"][j]["cota"] is not None]
            dias.append({"f": d["f"], "n": v, "donde": top["nombre"], "cota": min(cotas) if cotas else None})
    return {"id": m["id"], "nombre": m["nombre"], "sub": m["sub"], "url": f"{WEB}/nieve/{MACIZO_PAG[m['id']]['slug']}/",
            "esp_max": m["esp_max"], "acum_media": m["acum_media"], "normal_media": m["normal_media"],
            "sat": m["sat"], "sat_normal": m["sat_normal"], "prev7": m["prev7"], "dias": dias,
            "puntos": [{k: f[k] for k in ("id", "nombre", "alt", "esp", "esp_normal", "n7", "total7")} for f in fs]}


def macizo_puntos(mid: str, xs: list) -> list:
    """Los puntos de montaña y esquí de un macizo, primero los de más altitud."""
    return sorted([x for x in xs if x["macizo"] == mid], key=lambda x: -x["alt"])


def html_macizo(m: dict, xs: list, pxs: list) -> str:
    mp, ps = MACIZO_PAG[m["id"]], macizo_puntos(m["id"], xs)
    provs = sorted({(x["prov"], x["provincia"]) for x in ps}, key=lambda z: z[1])
    h1 = f"<h1>{esc(mp['titulo'])}:<span> {esc(mp['sub'])}</span></h1>"
    lede = (f"Cuánta nieve hay hoy en {mp['corto']}, cuánta ha caído esta temporada frente a un año normal y si va a nevar "
            f"en los próximos 15 días, montaña a montaña. Con una ficha de cada sitio para descargar y compartir.")
    out = [CSS, '<div class="cgnv">', '<div class="cgnv-panel cgnv-panel-mac">',
           f'<div class="cgnv-intro"><div class="cgnv-migas"><a href="/">Inicio</a><span>/</span><a href="/nieve/">Nieve</a>'
           f'<span>/</span>{esc(MACIZOS[m["id"]][0])}</div>{h1}<p class="lede">{esc(lede)}</p></div>',
           f'<div class="cg-ssr-slot">{ANCLA}</div>', "</div>"]
    con = [x for x in ps if x["clima"].get("total") is not None]
    if con:
        out.append(f"<h2>¿Cuánto nieva en {esc(mp['corto'])}?</h2>")
        top = max(con, key=lambda x: x["clima"]["total"])
        out.append(f"<p>En una temporada normal (1991-92 a 2020-21), el sitio más nevado de {esc(mp['corto'])} entre los "
                   f"que vigilamos es {esc(top['nombre'])} ({esc(entero(top['alt']))} m), con unos "
                   f"<b>{esc(cm(top['clima']['total']))}</b> de nieve por temporada y el suelo nevado "
                   f"{esc(entero(top['clima']['dias_suelo']))} días al año.</p>")
        out.append('<table class="cgnv-tabla"><thead><tr><th>Lugar</th><th class="n">Altitud</th><th class="n">Nieve por '
                   'temporada</th><th class="n">Días con nieve en el suelo</th><th>Primera nevada</th>'
                   '<th class="n">Cambio desde 1971-1990</th></tr></thead><tbody>')
        for x in con:
            c, ch = x["clima"], x["cambio"].get("total") or {}
            cam = "—" if ch.get("pct") is None else (("+" if ch["pct"] > 0 else "−") + entero(abs(ch["pct"])) + " %")
            cls = ' class="n baja"' if ch.get("pct") is not None and ch["pct"] < 0 and (ch.get("t") or 0) <= -2 else ' class="n"'
            out.append(f'<tr><td><a href="/nieve/{esc(x["prov"])}/">{esc(x["nombre"])}</a></td>'
                       f'<td class="n">{esc(entero(x["alt"]))} m</td><td class="n">{esc(cm(c["total"]))}</td>'
                       f'<td class="n">{esc(entero(c["dias_suelo"]))}</td>'
                       f'<td>{esc(dia_mes(c["primera"]) if c.get("primera") is not None else "—")}</td><td{cls}>{esc(cam)}</td></tr>')
        out.append("</tbody></table>")
        out.append('<p class="cgnv-nota">En rojo, las bajadas con una tendencia estadísticamente significativa desde 1971; en azul, las subidas. '
                   'Datos de ERA5-Land (Copernicus) en celdas de unos 9 km: en las cumbres hay más nieve.</p>')
        bajan = [x for x in con if (x["cambio"].get("total") or {}).get("t") is not None and x["cambio"]["total"]["t"] <= -2]
        if bajan:
            out.append(f"<h2>¿Nieva menos que antes en {esc(mp['corto'])}?</h2>")
            out.append("<p>" + esc(lista([frase_cambio(x) for x in bajan[:2]]).replace(". y ", ". ")) + "</p>")
    q = [(f"¿Hay nieve ahora en {mp['corto']}?",
          f"El bloque de arriba lo dice cada día: el espesor de nieve en cada montaña y estación de {mp['corto']}, "
          f"comparado con lo normal en esta fecha, y qué parte del macizo ve nevada el satélite."),
         (f"¿Va a nevar en {mp['corto']}?",
          "La previsión de arriba junta cuatro modelos (ECMWF, ICON, ARPEGE y GFS) y se actualiza tres veces al día: "
          "dónde va a nevar en los próximos 7 y 15 días, cuánto y a qué cota."),
         ("¿Qué datos da la ficha para compartir?",
          "La nieve que hay en el suelo frente a lo normal, la nieve nueva de las últimas 24 horas y de la semana, la "
          "previsión de 7 días con la cota de nieve, la temperatura y el viento, y el mejor día para ir. Se descarga como "
          "imagen para mandarla por WhatsApp o redes."),
         ("¿Sirve para saber qué pistas están abiertas?",
          "No: son datos de modelo y de satélite, no el parte de la estación. Las pistas, los remontes y el estado de la "
          "nieve los da cada estación en su parte oficial.")]
    out.append(faq_html(q))
    out.append('<div class="cgnv-metodo"><p><b>Cómo se calcula.</b> La nieve caída y el espesor salen del reanálisis '
               'ERA5-Land de Copernicus (ECMWF), día a día desde 1971; los últimos días, del análisis del ECMWF. La parte '
               'nevada del macizo es la del producto IMS de la NOAA (4 km) en un radio de unos 16 km alrededor de cada '
               'punto. La previsión es la mediana de ECMWF, ICON, ARPEGE y GFS; la cota de nieve, 300 m por debajo de la '
               'isoterma de 0 °C. Datos en <a href="' + PAGES + '/nieve/fichas.json">JSON</a> (CC BY 4.0).</p>'
               '<p>Sigue con <a href="/nieve/">la nieve en toda España</a>' + "".join(
                   f', <a href="/nieve/{esc(sl)}/">la nieve en {esc(pr)}</a>' for sl, pr in provs) + ' o '
               '<a href="/heladas/">las heladas</a>.</p></div>')
    out.append("</div>")
    out.append(faq_jsonld(q))
    return "<!-- wp:html -->\n" + "\n".join(out) + "\n<!-- /wp:html -->"


def ssr_macizo(m: dict, xs: list, sat: dict) -> str:
    mp, ps = MACIZO_PAG[m["id"]], macizo_puntos(m["id"], xs)
    e = m["esp_max"]
    hay = bool(e and e["cm"] >= 1)
    p = ['<div class="cgnv-dia"><div class="cgnv-hoy">', f'<h2>{esc(MACIZOS[m["id"]][0])} hoy</h2>',
         f'<p class="cgnv-hoy-v"><b>{esc(cm(e["cm"]) if hay else "Sin nieve")}</b><span>'
         + (f'de nieve en el suelo en {esc(e["donde"])}, lo más alto que vigilamos' if hay
            else "en el suelo en ninguno de sus puntos, según el modelo")
         + "</span></p><ul>"]
    if hay and e.get("normal") is not None:
        p.append(f"<li>Lo normal en esta fecha allí: <b>{esc(cm(e['normal']))}</b></li>")
    p.append(f"<li>Nieve caída esta temporada (media del macizo): <b>{esc(cm(m['acum_media']))}</b>"
             + (f"; normal, {esc(cm(m['normal_media']))}" if m["normal_media"] is not None else "") + "</li>")
    if m["sat"] is not None:
        p.append(f"<li>Superficie nevada según el satélite: <b>{esc(pct(m['sat']))}</b>"
                 + (f"; lo normal, {esc(pct(m['sat_normal']))}" if m["sat_normal"] is not None else "") + "</li>")
    p.append(f'</ul><p><a href="{url_ficha(macizo=m["id"])}">Descargar la ficha {esc(de(mp["corto"]))} para compartir</a></p></div>')
    # tabla de hoy
    p.append('<div class="cgnv-prev"><h2 class="cgnv-panel-h2">Montaña a montaña</h2><div class="cgnv-tw">'
             '<table class="cgnv-tp cgnv-tm"><thead><tr><th class="cgnv-mod">Lugar</th><th>Espesor hoy</th><th>Normal hoy</th>'
             '<th>Últimos 7 días</th><th>Próximos 7 días</th><th>Cota mañana</th><th>Ficha</th></tr></thead><tbody>')
    for x in ps:
        o, pv = x["temporada"], x["prevision"]
        cota = pv["cota"][1] if len(pv.get("cota", [])) > 1 else None
        p.append(f'<tr><th class="cgnv-mod"><a href="/nieve/{esc(x["prov"])}/">{esc(x["nombre"])}</a>'
                 f'<small>{esc(entero(x["alt"]))} m · {esc(x["provincia"])}</small></th>'
                 f'<td>{esc(cm(o.get("esp")) if o.get("esp") is not None else "—")}</td>'
                 f'<td>{esc(cm(o.get("esp_normal")) if o.get("esp_normal") is not None else "—")}</td>'
                 f'<td>{esc(cm(o.get("ult7") or 0))}</td><td>{esc(cm(pv.get("total7") or 0))}</td>'
                 f'<td>{esc(entero(cota) + " m" if cota is not None and cota < 3500 else "—")}</td>'
                 f'<td><a href="{url_ficha(x["id"])}">Ficha</a></td></tr>')
    p.append("</tbody></table></div>")
    top = max(ps, key=lambda x: x["prevision"].get("total15") or 0)
    p.append(f'<h2 class="cgnv-panel-h2" style="margin-top:22px">¿Va a nevar en {esc(mp["corto"])}?</h2>')
    p.append(f'<p class="cgnv-psub">{esc(va_a_nevar(top))}</p>')
    md = mejor_dia(top)
    if md:
        d = date.fromisoformat(md["f"])
        p.append(f'<p class="cgnv-psub">Mejor día para ir esta semana a {esc(top["nombre"])}: <b>el {esc(dia_semana(d))} '
                 f'{d.day}</b> ({esc(md["motivo"])}).</p>')
    p.append(f"<h3>Previsión de nieve y cota en {esc(top['nombre'])} ({esc(entero(top['alt']))} m), día a día</h3>")
    p.append(tabla_prevision(top["prevision"], top["nombre"]))
    p.append(f'<p class="cgnv-pie">Cifras de modelo en centímetros de nieve nueva por día. Actualizado el '
             f'{esc(fecha_larga(AHORA.astimezone(TZ).date(), False))} a las {AHORA.astimezone(TZ):%H:%M}. Para pistas y '
             f'remontes, el parte oficial de cada estación.</p></div></div>')
    return ssr_compatible("".join(p))


def metas_macizo(m: dict) -> dict:
    mp = MACIZO_PAG[m["id"]]
    d = (f"¿Hay nieve en {mp['corto']}? Espesor de nieve hoy frente a lo normal, nieve caída esta temporada y previsión "
         f"de nevadas y cota a 15 días en {mp['sub']}. Con ficha para compartir.")
    return {"rank_math_title": mp["rm"], "rank_math_description": d[:300]}


def jsonld_macizo(m: dict) -> str:
    mp = MACIZO_PAG[m["id"]]
    return json.dumps({"@context": "https://schema.org", "@type": "Dataset",
                       "name": f"{mp['titulo']}: espesor de nieve, nieve caída y previsión",
                       "description": f"Espesor de nieve, nieve caída por temporada desde 1971, superficie nevada por "
                                      f"satélite y previsión de cuatro modelos en {mp['sub']}.",
                       "url": f"{WEB}/nieve/{mp['slug']}/", "license": "https://creativecommons.org/licenses/by/4.0/",
                       "dateModified": AHORA.isoformat()[:10],
                       "creator": {"@type": "Organization", "name": "calentamientoglobal.es", "url": WEB + "/"},
                       "distribution": [{"@type": "DataDownload", "encodingFormat": "application/json",
                                         "contentUrl": f"{PAGES}/nieve/fichas.json"}]}, ensure_ascii=False)


# ----------------------------------------------------------------------------------------------------------- salidas
def guardar_datos(pxs: list, xs: list, sat: dict, macs: list) -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    gen = AHORA.isoformat().replace("+00:00", "Z")
    fuente = ("ERA5-Land (Copernicus/ECMWF) vía Open-Meteo · NOAA IMS 4 km (NSIDC G02156) · ECMWF, ICON, ARPEGE y GFS "
              "vía Open-Meteo · cálculo de calentamientoglobal.es")

    def ficha(x):
        return {"id": x["id"], "nombre": x["nombre"], "tipo": x["tipo"], "altitud_m": x["alt"], "lat": x["lat"],
                "lon": x["lon"], "macizo": x["macizo"], "clima": {k: v for k, v in x["clima"].items()
                                                                   if k not in ("acum_p10", "acum_p90", "prob")},
                "cambio": x["cambio"], "records": x["records"],
                "temporada": {k: v for k, v in x["temporada"].items() if k not in ("esp_serie",)},
                "prevision": x["prevision"]}

    idx = {"generado": gen, "version": VERSION, "fuente": fuente, "licencia": "CC BY 4.0",
           "definiciones": {"dia_de_nieve": "1 cm o más de nieve nueva", "temporada": "del 1 de agosto al 31 de julio",
                            "normal": "temporadas de 1991-92 a 2020-21",
                            "cota": "300 m por debajo de la isoterma de 0 °C en las horas con precipitación"},
           "satelite": {k: v for k, v in sat.items() if k not in ("serie", "med", "p10", "p90")},
           "macizos": macs, "provincias": []}
    for px in pxs:
        mo, ca = px["monte"], px["capital"]
        idx["provincias"].append({
            "slug": px["slug"], "provincia": px["provincia"], "url": url_prov(px["slug"]),
            "monte": {"nombre": mo["nombre"], "altitud_m": mo["alt"], "temporada_cm": mo["temporada"]["acum"],
                      "normal_hoy_cm": mo["temporada"].get("normal"), "espesor_cm": mo["temporada"].get("esp"),
                      "normal_temporada_cm": mo["clima"].get("total"), "prevision_7d_cm": mo["prevision"].get("total7"),
                      "prevision_15d_cm": mo["prevision"].get("total15")},
            "capital": {"nombre": ca["nombre"], "temporada_cm": ca["temporada"]["acum"],
                        "dias_nieve_normal": ca["clima"].get("dias"), "ultima_nevada": ca["records"].get("ultima")},
            "satelite_pct": (sat.get("hoy") or {}).get(px["slug"])})
        det = {"generado": gen, "version": VERSION, "fuente": fuente, "licencia": "CC BY 4.0", "slug": px["slug"],
               "provincia": px["provincia"], "monte": ficha(mo), "capital": ficha(ca),
               "extras": [ficha(x) for x in px["extras"]],
               "satelite": {"fecha": sat.get("fecha"), "pct": (sat.get("hoy") or {}).get(px["slug"]),
                            "normal": (sat.get("normal") or {}).get(px["slug"])}}
        escribir(SALIDA / f"{px['slug']}.json", json.dumps(det, ensure_ascii=False, indent=1, default=str))
        filas = ["punto,altitud_m,temporada,nieve_cm,dias_de_nieve,dias_suelo_nevado,max_nieve_dia_cm,max_espesor_cm"]
        for x in [mo, ca] + px["extras"]:
            for y, t in sorted(x["_temps"].items()):
                filas.append(",".join(str(z if z is not None else "") for z in (
                    x["nombre"].replace(",", ""), x["alt"], temporada(y), t["total"], t["dias"], t["dias_suelo"],
                    t["max_dia"], t["max_espesor"])))
        escribir(SALIDA / f"{px['slug']}.csv", "\n".join(filas) + "\n")
    escribir(SALIDA / "index.json", json.dumps(idx, ensure_ascii=False, indent=1, default=str))
    fichas = {"generado": gen, "version": VERSION, "fuente": fuente, "licencia": "CC BY 4.0",
              "puntos": {x["id"]: ficha_punto(x) for x in xs if x["tipo"] != "capital"},
              "macizos": {m["id"]: ficha_macizo(m, xs) for m in macs}}
    escribir(SALIDA / "fichas.json", json.dumps(fichas, ensure_ascii=False, separators=(",", ":"), default=str))
    todo = sat_leer()
    if todo:
        sat_guardar(todo, SALIDA / "satelite.csv")


# ----------------------------------------------------------------------------------------------------------- WordPress
class WP:
    def __init__(self, usuario: str, clave: str):
        self.aut = "Basic " + base64.b64encode(f"{usuario}:{clave}".encode()).decode()

    def pedir(self, metodo: str, ruta: str, datos: dict | None = None, intentos: int = 4):
        url = ruta if ruta.startswith("http") else API + ruta
        cuerpo = json.dumps(datos).encode() if datos is not None else None
        for i in range(intentos):
            req = urllib.request.Request(url, data=cuerpo, method=metodo, headers={
                "Authorization": self.aut, "Content-Type": "application/json", "Accept": "application/json",
                "User-Agent": "calentamientoglobal.es/nieve"})
            try:
                with urllib.request.urlopen(req, timeout=90) as r:
                    return json.loads(r.read().decode("utf-8") or "null")
            except urllib.error.HTTPError as e:
                txt = e.read().decode("utf-8", "replace")[:400]
                if e.code in (429, 500, 502, 503, 504) and i < intentos - 1:
                    time.sleep(10 * (i + 1))
                    continue
                raise RuntimeError(f"{metodo} {url} → HTTP {e.code}: {txt}") from None
            except Exception as e:  # noqa: BLE001
                if i < intentos - 1:
                    time.sleep(10 * (i + 1))
                    continue
                raise RuntimeError(f"{metodo} {url} → {type(e).__name__}: {e}") from None

    def buscar(self, slug: str, padre: int) -> dict | None:
        r = self.pedir("GET", f"/pages?slug={slug}&parent={padre}&status=publish,draft,private,pending&context=edit"
                              f"&_fields=id,slug,parent,status")
        return r[0] if r else None


def h(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def publicar(pxs: list, xs: list, sat: dict, macs: list, forzar: bool) -> None:
    usuario, clave = os.environ.get("WP_USER"), os.environ.get("WP_APP_PASSWORD")
    if not usuario or not clave:
        log("Faltan WP_USER / WP_APP_PASSWORD: no se publica")
        sys.exit(1)
    wp = WP(usuario, clave)
    reg = leer_json(PUBLICADO, {})
    errores = 0

    def subir(clave_reg, padre, slug, titulo, contenido, ssr, jsonld, metas, listo):
        nonlocal errores
        r = reg.get(clave_reg) or {}
        pid = r.get("id")
        if not pid:
            try:
                ex = wp.buscar(slug, padre)
            except RuntimeError as e:
                log(f"  ERROR {slug}: {e}")
                errores += 1
                return None
            pid = ex["id"] if ex else None
        # una página se queda en borrador hasta que su serie larga está completa; una vez publicada, no se despublica
        estado = "publish" if (listo or r.get("estado") == "publish") else "draft"
        hc, hs = h(titulo + contenido + json.dumps(metas, sort_keys=True) + jsonld + estado), h(ssr)
        datos = {}
        if forzar or not pid or r.get("hc") != hc:
            datos.update({"title": titulo, "content": contenido, "status": estado, "parent": padre, "slug": slug,
                          "template": PLANTILLA, "comment_status": "closed", "ping_status": "closed"})
            meta = {"cg_ssr_anchor": ANCLA, "cg_ssr_jsonld": jsonld}
            meta.update(metas)
            datos["meta"] = meta
        if forzar or not pid or r.get("hs") != hs or datos:
            datos.setdefault("meta", {})["cg_ssr_html"] = ssr
        if not datos:
            return pid
        try:
            res = wp.pedir("POST", f"/pages/{pid}" if pid else "/pages", datos)
            pid = res["id"]
        except RuntimeError as e:
            if "rank_math" in str(e) and "meta" in datos:
                for k in list(datos["meta"]):
                    if k.startswith("rank_math"):
                        datos["meta"].pop(k)
                res = wp.pedir("POST", f"/pages/{pid}" if pid else "/pages", datos)
                pid = res["id"]
            else:
                log(f"  ERROR {slug}: {e}")
                errores += 1
                return pid
        guardado = (res.get("meta") or {}).get("cg_ssr_html") or ""
        if ssr and not guardado:
            log(f"  AVISO {slug}: el bloque del día no se ha guardado (¿snippet cg-ssr-bloque activo?)")
        reg[clave_reg] = {"id": pid, "hc": hc if "content" in datos else r.get("hc"), "hs": hs, "estado": estado,
                          "link": res.get("link"), "actualizado": AHORA.isoformat()}
        log(f"  {slug} ({estado}): {'contenido y bloque' if 'content' in datos else 'bloque del día'} → {res.get('link')}")
        return pid

    listos = sum(1 for px in pxs if px["monte"]["completo"])
    hub_id = subir("_hub", 0, "nieve", "Nieve en España: dónde hay nieve hoy, cota de nieve y previsión de nevadas",
                   html_hub(pxs, xs), ssr_hub(pxs, xs, sat, macs),
                   json.dumps({"@context": "https://schema.org", "@type": "Dataset",
                               "name": "Nieve en España: superficie nevada, nieve caída y previsión de nevadas",
                               "description": "Superficie nevada diaria por satélite (NOAA IMS), nieve caída y espesor de "
                                              "cada temporada desde 1971 (ERA5-Land) y previsión de cuatro modelos a 15 días, "
                                              "por provincia y por macizo.",
                               "url": WEB + "/nieve/", "license": "https://creativecommons.org/licenses/by/4.0/",
                               "dateModified": AHORA.isoformat()[:10],
                               "creator": {"@type": "Organization", "name": "calentamientoglobal.es", "url": WEB + "/"},
                               "distribution": [{"@type": "DataDownload", "encodingFormat": "application/json",
                                                 "contentUrl": f"{PAGES}/nieve/index.json"},
                                                {"@type": "DataDownload", "encodingFormat": "text/csv",
                                                 "contentUrl": f"{PAGES}/nieve/satelite.csv"}]}, ensure_ascii=False),
                   {"rank_math_title": "Nieve en España hoy: mapa, cota de nieve y previsión de nevadas",
                    "rank_math_description": "Dónde hay nieve hoy en España según el satélite, la cota de nieve de los "
                                             "próximos días y dónde va a nevar en 15 días según cuatro modelos. Mapa por "
                                             "provincias y por macizos."},
                   True)   # 4-11-2026: el hub va publicado desde el primer día (lo pidió David)
    if not hub_id:
        log("No se pudo crear la página /nieve/")
        sys.exit(1)
    for px in pxs:
        subir(px["slug"], hub_id, px["slug"], titulo_prov(px), html_prov(px), ssr_prov(px, sat),
              jsonld_prov(px), metas_prov(px), px["monte"]["completo"])
    for m in macs:   # las páginas de macizo van publicadas desde el primer día (5-11-2026, a petición de David)
        mp = MACIZO_PAG[m["id"]]
        subir("_m_" + m["id"], hub_id, mp["slug"], mp["titulo"], html_macizo(m, xs, pxs), ssr_macizo(m, xs, sat),
              jsonld_macizo(m), metas_macizo(m), True)
    escribir(PUBLICADO, json.dumps(reg, ensure_ascii=False, indent=1, sort_keys=True))
    if errores:
        log(f"{errores} páginas con error")
        sys.exit(1)


# -------------------------------------------------------------------------------------------------------------- demo
def simular() -> None:
    """Datos inventados (y marcados como tales) para revisar el diseño sin red. Nunca se ejecuta en producción."""
    rnd = random.Random(7)
    est = {}
    for p in PUNTOS:
        base = max(0.0, (p["alt"] - 300) / 1700)
        serie = {}
        d = INICIO
        esp = 0.0
        while d <= HOY:
            y = temporada_de(d)
            i = indice(d)
            inv = math.exp(-((i - 175) / 55) ** 2)
            tend = 1 - 0.006 * (y - 1971)
            n = 0.0
            if rnd.random() < 0.22 * inv * (0.3 + base):
                n = rnd.expovariate(1 / (6 * base + 0.6)) * tend
            esp = max(0.0, esp * (0.93 if inv > 0.3 else 0.7) + n - (1.5 if inv < 0.3 else 0.2))
            serie[d.isoformat()] = (round(n, 2), round(esp, 1))
            d += timedelta(days=1)
        for parte in ("historico", "reciente"):
            era_guardar(p["id"], serie, parte)
        est[p["id"]] = {d0.isoformat(): "demo" for d0, _ in TANDAS}
    escribir(ARCHIVO / "era5land_estado.json", json.dumps(est))
    prev = {"generado": AHORA.isoformat(), "puntos": {}}
    for p in PUNTOS:
        dias = [(HOY + timedelta(days=k)).isoformat() for k in range(-10, 16)]
        m = {}
        base = max(0.0, (p["alt"] - 400) / 1500)
        for mid, _n, _o, alc in MODELOS:
            ns = []
            for k in range(len(dias)):
                dd = k - 10
                ns.append(None if dd >= alc else round(max(0.0, rnd.gauss(4 * base, 6) if 3 <= dd <= 6 else
                                                           rnd.gauss(0, 1.5)), 1))
            m[mid] = {"n": ns, "ll": ns, "tx": [5] * len(dias), "tn": [-2] * len(dias),
                      "cota": [None if v is None or v < 0.2 else 900 + 100 * rnd.randint(0, 6) for v in ns],
                      "esp": [round(30 * base, 1)] * len(dias)}
        prev["puntos"][p["id"]] = {"dias": dias, "m": m}
    escribir(CACHE_PREV, json.dumps(prev))
    datos = {}
    d = date(SAT_DESDE, 10, 1)
    while d <= HOY:
        if 10 <= d.month or d.month <= 5:
            inv = math.exp(-((indice(d) - 175) / 50) ** 2)
            fila = {"espana": round(max(0, rnd.gauss(9 * inv, 3 * inv)), 2)}
            fila["espana_km2"] = round(fila["espana"] * 5060)
            for slug, *_ in PROVINCIAS:
                fila[slug] = round(max(0, rnd.gauss(14 * inv, 6 * inv)), 2)
            for mm in ORDEN_MACIZOS:
                fila["m_" + mm] = round(max(0, rnd.gauss(40 * inv, 15 * inv)), 2)
            datos[d.isoformat()] = fila
        d += timedelta(days=1)
    sat_guardar(datos)


# ---------------------------------------------------------------------------------------------------------- principal
def construir() -> tuple:
    prev = leer_json(CACHE_PREV, {})
    xs = [calcular_punto(p, prev) for p in PUNTOS]
    xi = {x["id"]: x for x in xs}
    pxs = []
    for slug, prov, *_ in PROVINCIAS:
        pxs.append({"slug": slug, "provincia": prov, "monte": xi[f"{slug}-monte"], "capital": xi[f"{slug}-capital"],
                    "extras": [xi[e[0]] for e in EXTRAS if e[6] == slug]})
    sat = calcular_sat(sat_leer())
    macs = resumen_macizos([x for x in xs if x["macizo"]], sat)
    return pxs, xs, sat, macs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clima", action="store_true")
    ap.add_argument("--presupuesto", type=float, default=1000)
    ap.add_argument("--satelite", action="store_true")
    ap.add_argument("--satelite-historico", action="store_true")
    ap.add_argument("--desde", type=int, default=SAT_DESDE)
    ap.add_argument("--max", type=int, default=500)
    ap.add_argument("--sin-datos", action="store_true", help="no baja ERA5-Land reciente ni la previsión")
    ap.add_argument("--publicar", action="store_true")
    ap.add_argument("--forzar", action="store_true")
    ap.add_argument("--vista", default="")
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    log(f"Nieve v{VERSION} · {HOY}")
    if a.demo:
        simular()
        a.sin_datos = True
    if a.clima:
        modo_clima(a.presupuesto)
        return
    if a.satelite_historico:
        pendientes = fechas_historico(a.desde, 100000)
        log(f"Satélite histórico: {len(pendientes)} días pendientes desde {a.desde}")
        if not pendientes:
            marcar_completo()
            return
        modo_satelite(pendientes[:a.max], limite_s=float(os.environ.get("CG_LIMITE_S", 3300)), destino=SAT_HIST)
        return
    if a.satelite:
        modo_satelite([HOY - timedelta(days=k) for k in range(6, -1, -1)], limite_s=1200)
    if not a.sin_datos:
        actualizar_reciente()
        prev = descargar_prevision()
        if len(prev["puntos"]) >= 0.8 * len(PUNTOS):
            escribir(CACHE_PREV, json.dumps(prev, separators=(",", ":")))
        else:
            log("Previsión incompleta: se mantiene la anterior")
    pxs, xs, sat, macs = construir()
    con_datos = sum(1 for x in xs if x["temporada"]["era_hasta"])
    log(f"{con_datos} de {len(xs)} puntos con datos de esta temporada; "
        f"{sum(1 for x in xs if x['completo'])} con la serie larga completa")
    if con_datos < 0.8 * len(xs):
        log("Faltan datos de demasiados puntos: no se escribe nada")
        sys.exit(1)
    guardar_datos(pxs, xs, sat, macs)
    if a.vista:
        d = Path(a.vista)
        d.mkdir(parents=True, exist_ok=True)
        envolver = lambda c: ('<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" '
                              'content="width=device-width,initial-scale=1"><title>vista</title></head><body style="margin:0">'
                              + c + "</body></html>")
        (d / "nieve.html").write_text(envolver(html_hub(pxs, xs).replace(ANCLA, ssr_hub(pxs, xs, sat, macs))),
                                      encoding="utf-8")
        for px in pxs:
            (d / f"{px['slug']}.html").write_text(envolver(html_prov(px).replace(ANCLA, ssr_prov(px, sat))),
                                                  encoding="utf-8")
        for m in macs:
            (d / f"m-{MACIZO_PAG[m['id']]['slug']}.html").write_text(
                envolver(html_macizo(m, xs, pxs).replace(ANCLA, ssr_macizo(m, xs, sat))), encoding="utf-8")
        log(f"Vista en {d}")
    if a.publicar:
        publicar(pxs, xs, sat, macs, a.forzar)


if __name__ == "__main__":
    main()
