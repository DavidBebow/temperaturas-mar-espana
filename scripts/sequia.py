#!/usr/bin/env python3
"""Monitor de sequía de España (calentamientoglobal.es/sequia/) · bloque A: datos, gráficos y JSON.

Para cada provincia calcula, con la precipitación oficial de AEMET de su capital (o la estación de referencia):
  · el SPI a 3, 6 y 12 meses (gamma ajustada por máxima verosimilitud sobre 1991-2020, mezcla para ceros de McKee);
  · el semáforo de sequía meteorológica (niveles 0-5, regla escrita en REGLA_SEMAFORO y no se cambia);
  · la lluvia del año hidrológico en curso (desde el 1 de octubre) frente a lo normal 1991-2020;
  · los días sin lluvia significativa (< 1 mm) en la capital;
  · los embalses de la provincia (MITECO, ya en docs/embalses/), la nieve (docs/nieve/) y la lluvia prevista a 15 días;
  · los cinco episodios de sequía más intensos de la serie.

Deja en docs/sequia/: index.json, nacional.json, prensa.json, <slug>.json, <slug>.csv, graf/<slug>-spi.svg,
graf/<slug>-hidro.svg y graf/mapa.svg. Solo stdlib + scipy. Sin claves ni APIs de pago.

Uso:  python scripts/sequia.py [--sin-red] [--solo slug,slug] [--tabla]
  --sin-red   no llama a Open-Meteo: la cola provisional sale del ERA5 del archivo del repo y no hay previsión.
"""
from __future__ import annotations

import calendar
import csv
import gzip
import io
import json
import math
import os
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
from balance_mensual import ESTACIONES, NORMAL, PROVINCIA, SIN_SERIE, Historia, f1, r1  # noqa: E402,F401

VERSION = "1.0.0"
RAIZ = Path(__file__).resolve().parent.parent
DOCS = RAIZ / "docs"
SALIDA = DOCS / "sequia"
GRAF = SALIDA / "graf"
ERA5 = RAIZ / "archivo" / "era5"
EMB = DOCS / "embalses"
NIEVE_IDX = DOCS / "nieve" / "index.json"
PAGES = "https://davidbebow.github.io/temperaturas-mar-espana/sequia/"
WEB = "https://calentamientoglobal.es"
TZ = ZoneInfo("Europe/Madrid")
HOY = date.fromisoformat(os.environ["SEQUIA_HOY"]) if os.environ.get("SEQUIA_HOY") else datetime.now(TZ).date()
UA = "calentamientoglobal.es/sequia (+https://calentamientoglobal.es/sequia/)"
OM_ARCHIVO = "https://archive-api.open-meteo.com/v1/archive"
OM_PREVISION = "https://api.open-meteo.com/v1/forecast"

REF0, REF1 = NORMAL            # 1991-2020
MIN_REF = 24                   # años válidos exigidos en 1991-2020
MIN_SERIE_LARGA = 30           # si no, toda la serie con al menos 30 años
COBERTURA = 0.90               # días con dato exigidos en una ventana diaria
UMBRAL_LLUVIA = 1.0            # mm: día de lluvia significativa
FUENTE = ("AEMET (precipitación) · MITECO (embalses) · ECMWF, DWD, Météo-France y NOAA (previsión, vía Open-Meteo) · "
          "cálculo de calentamientoglobal.es")
LICENCIA = "CC BY 4.0"

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]
MES_C = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

# nivel del semáforo → (texto, color). El 5 (sin dato) no figura en la escala pública: gris neutro.
NIVELES = {0: ("Normal", "#3d8bd1"), 1: ("Vigilancia", "#e9d36a"), 2: ("Sequía moderada", "#f0a04b"),
           3: ("Sequía severa", "#e0552b"), 4: ("Sequía extrema", "#8b1a1a"), 5: ("Sin dato", "#6b7c8a")}
COLOR_EXCEDENTE = "#1f6f5b"    # SPI ≥ 1
TXT, SEC, ACENTO, DESTACADO = "#e8f1f8", "#9fb6c8", "#bfe6ff", "#ff7a45"

REGLA_SEMAFORO = (
    "Nivel 0 (normal o húmedo): SPI a 3, 6 y 12 meses por encima de −1 y ninguno igual o inferior a −0,7. "
    "Nivel 1 (vigilancia): alguna de las tres escalas entre −0,7 y −1, o SPI a 3 meses igual o inferior a −1 con los de "
    "6 y 12 meses por encima de −0,7 (un mes seco, no una sequía). "
    "Niveles 2 (sequía moderada), 3 (severa) y 4 (extrema) según el peor de los SPI a 6 y 12 meses, que son los que miden "
    "sequía y no un mes malo: igual o inferior a −1, −1,5 y −2. "
    "Nivel 5: sin serie suficiente para calcular el SPI.")

# --------------------------------------------------------------------------------------------------- provincias
SLUG = {  # código INE → slug de la página (las 47 con estación; el de scripts/tu_capital.py)
    "01": "alava", "02": "albacete", "03": "alicante", "04": "almeria", "05": "avila", "06": "badajoz",
    "07": "baleares", "08": "barcelona", "09": "burgos", "10": "caceres", "11": "cadiz", "12": "castellon",
    "13": "ciudad-real", "14": "cordoba", "15": "a-coruna", "16": "cuenca", "17": "girona", "18": "granada",
    "20": "gipuzkoa", "21": "huelva", "22": "huesca", "23": "jaen", "24": "leon", "25": "lleida",
    "26": "la-rioja", "27": "lugo", "28": "madrid", "29": "malaga", "30": "murcia", "31": "navarra",
    "32": "ourense", "35": "las-palmas", "36": "pontevedra", "37": "salamanca", "38": "santa-cruz-de-tenerife",
    "40": "segovia", "41": "sevilla", "42": "soria", "43": "tarragona", "44": "teruel", "45": "toledo",
    "46": "valencia", "47": "valladolid", "48": "bizkaia", "49": "zamora", "50": "zaragoza", "52": "melilla",
}
SLUG.update({"19": "guadalajara", "33": "asturias", "34": "palencia", "39": "cantabria", "51": "ceuta"})
assert set(SLUG) == set(PROVINCIA), "SLUG debe cubrir las 52 provincias"
COD = {s: c for c, s in SLUG.items()}
ORDEN = [SLUG[c] for c in sorted(SLUG)]
NOMBRE = dict(PROVINCIA)
NOMBRE["07"] = "Baleares"

# capital: (lat, lon, altitud m), las mismas que usa scripts/nieve.py para la previsión; Ceuta y Melilla, a mano
COORD = {
    "a-coruna": (43.362, -8.411, 30), "alava": (42.847, -2.672, 525), "albacete": (38.994, -1.858, 686),
    "alicante": (38.345, -0.481, 10), "almeria": (36.834, -2.464, 20), "asturias": (43.361, -5.849, 230),
    "avila": (40.656, -4.7, 1130), "badajoz": (38.879, -6.97, 186), "baleares": (39.57, 2.65, 20),
    "barcelona": (41.389, 2.17, 15), "bizkaia": (43.263, -2.935, 20), "burgos": (42.344, -3.697, 860),
    "caceres": (39.475, -6.372, 440), "cadiz": (36.527, -6.289, 10), "cantabria": (43.462, -3.81, 15),
    "castellon": (39.986, -0.051, 30), "ciudad-real": (38.985, -3.927, 630), "cordoba": (37.888, -4.779, 120),
    "cuenca": (40.07, -2.137, 950), "gipuzkoa": (43.318, -1.981, 10), "girona": (41.979, 2.821, 75),
    "granada": (37.177, -3.599, 690), "guadalajara": (40.633, -3.167, 690), "huelva": (37.261, -6.945, 20),
    "huesca": (42.14, -0.409, 490), "jaen": (37.779, -3.785, 570), "leon": (42.599, -5.567, 840),
    "lleida": (41.617, 0.62, 155), "lugo": (43.012, -7.556, 465), "madrid": (40.416, -3.703, 650),
    "malaga": (36.721, -4.421, 15), "murcia": (37.992, -1.131, 45), "navarra": (42.812, -1.646, 450),
    "ourense": (42.336, -7.864, 130), "palencia": (42.01, -4.533, 750), "las-palmas": (28.124, -15.43, 10),
    "pontevedra": (42.431, -8.645, 20), "la-rioja": (42.466, -2.445, 385), "salamanca": (40.965, -5.664, 800),
    "santa-cruz-de-tenerife": (28.469, -16.254, 10), "segovia": (40.948, -4.118, 1000),
    "sevilla": (37.389, -5.984, 10), "soria": (41.764, -2.465, 1060), "tarragona": (41.119, 1.245, 30),
    "teruel": (40.344, -1.107, 915), "toledo": (39.863, -4.027, 530), "valencia": (39.47, -0.376, 15),
    "valladolid": (41.652, -4.724, 690), "zamora": (41.503, -5.744, 650), "zaragoza": (41.649, -0.889, 200),
    "ceuta": (35.889, -5.32, 10), "melilla": (35.292, -2.938, 30),
}
CAPITAL_SIN_SERIE = {"19": "Guadalajara", "33": "Oviedo", "34": "Palencia", "39": "Santander", "51": "Ceuta"}

# slug de la página → slug de docs/embalses/ (46 provincias; el resto no tiene embalse monitorizado)
EMB_SLUG = {s: s for s in ORDEN}
EMB_SLUG.update({"a-coruna": "a_coruña", "ciudad-real": "ciudad_real", "gipuzkoa": "guipuzcoa", "la-rioja": "la_rioja"})
for _s in ("baleares", "bizkaia", "las-palmas", "santa-cruz-de-tenerife", "ceuta", "melilla"):
    EMB_SLUG.pop(_s)

# superficie provincial en km² (INE, redondeada al km²), solo para ponderar la media nacional
SUPERFICIE_KM2 = {
    "alava": 3037, "albacete": 14926, "alicante": 5816, "almeria": 8775, "avila": 8050, "badajoz": 21766,
    "baleares": 4992, "barcelona": 7728, "burgos": 14292, "caceres": 19868, "cadiz": 7436, "castellon": 6632,
    "ciudad-real": 19813, "cordoba": 13771, "a-coruna": 7950, "cuenca": 17141, "girona": 5910, "granada": 12647,
    "guadalajara": 12214, "gipuzkoa": 1980, "huelva": 10148, "huesca": 15636, "jaen": 13489, "leon": 15581,
    "lleida": 12150, "la-rioja": 5045, "lugo": 9856, "madrid": 8028, "malaga": 7306, "murcia": 11313,
    "navarra": 10391, "ourense": 7273, "asturias": 10604, "palencia": 8052, "las-palmas": 4066, "pontevedra": 4495,
    "salamanca": 12350, "santa-cruz-de-tenerife": 3381, "cantabria": 5321, "segovia": 6949, "sevilla": 14036,
    "soria": 10306, "tarragona": 6303, "teruel": 14810, "toledo": 15370, "valencia": 10807, "valladolid": 8110,
    "bizkaia": 2217, "zamora": 10561, "zaragoza": 17274, "ceuta": 19, "melilla": 12,
}
assert set(SUPERFICIE_KM2) == set(ORDEN)

MODELOS = [  # id de Open-Meteo, nombre corto (los mismos que scripts/nieve.py)
    ("ecmwf_ifs025", "ECMWF"), ("icon_seamless", "ICON"), ("meteofrance_seamless", "ARPEGE"), ("gfs_seamless", "GFS"),
]
MOD_CLAVE = {"ecmwf_ifs025": "ecmwf", "icon_seamless": "icon", "meteofrance_seamless": "arpege", "gfs_seamless": "gfs"}


def log(m: str):
    print(time.strftime("%H:%M:%S ") + m, flush=True)


# --------------------------------------------------------------------------------------------------- formato
def r2(v) -> float:
    return float(Decimal(repr(round(float(v), 8))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def f2(v) -> str:
    s = f"{r2(v):.2f}".replace(".", ",")
    return ("−" + s[1:]) if s.startswith("-") else s


def f1s(v) -> str:
    s = f1(v)
    return ("−" + s[1:]) if s.startswith("-") else s


def p0(v) -> int:
    return int(Decimal(repr(round(float(v), 6))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fecha_txt(d: date) -> str:
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def mes_txt(ym: str) -> str:
    return f"{MESES[int(ym[5:7]) - 1]} de {ym[:4]}"


def ym(y: int, m: int) -> str:
    return f"{y}-{m:02d}"


def leer_json(p: Path, defecto=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return defecto


def escribir(p: Path, texto: str) -> bool:
    """Escribe solo si cambia (menos commits). Devuelve True si escribió."""
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        if p.read_text(encoding="utf-8") == texto:
            return False
    except Exception:  # noqa: BLE001
        pass
    p.write_text(texto, encoding="utf-8")
    return True


def escribir_json(p: Path, obj, compacto: bool = False) -> bool:
    if compacto:
        t = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    else:
        t = json.dumps(obj, ensure_ascii=False, indent=1)
    return escribir(p, t)


def palabras(t: str) -> int:
    return len(t.split())


# --------------------------------------------------------------------------------------------------- red (Open-Meteo)
class Limite(Exception):
    pass


RED = {"activa": True, "fallos_seguidos": 0}


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


def om_seguro(url: str, params: dict):
    """Una petición con un disyuntor: tras 3 provincias seguidas sin respuesta se abandona la red en esta pasada."""
    if not RED["activa"]:
        return None
    try:
        r = om(url, params, intentos=3 if RED["fallos_seguidos"] == 0 else 1)
        RED["fallos_seguidos"] = 0
        time.sleep(0.4)
        return r
    except (RuntimeError, Limite) as ex:
        RED["fallos_seguidos"] += 1
        log(f"  Open-Meteo no responde ({str(ex)[:120]})")
        if RED["fallos_seguidos"] >= 3:
            RED["activa"] = False
            log("  Se abandona Open-Meteo en esta pasada: cola provisional desde el ERA5 del archivo y sin previsión.")
        return None


def parse_archivo(r: dict) -> dict[date, float]:
    d = (r or {}).get("daily") or {}
    out = {}
    for t, v in zip(d.get("time") or [], d.get("precipitation_sum") or []):
        if v is not None:
            out[date.fromisoformat(t)] = float(v)
    return out


def parse_prevision(r: dict) -> dict[str, dict[date, float]]:
    """{modelo: {fecha: mm}} de la respuesta de Open-Meteo (varios modelos → columnas precipitation_sum_<modelo>)."""
    d = (r or {}).get("daily") or {}
    t = d.get("time") or []
    out = {}
    for mid, _n in MODELOS:
        col = d.get(f"precipitation_sum_{mid}")
        if not col:
            continue
        m = {date.fromisoformat(x): float(v) for x, v in zip(t, col) if v is not None}
        if m:
            out[mid] = m
    return out


# --------------------------------------------------------------------------------------------------- series diarias
def leer_era5(cod: str) -> dict[date, float]:
    """Lluvia diaria ERA5 en la capital: hasta_2025_era5.csv.gz + los ficheros del año en curso (20xx.csv)."""
    out: dict[date, float] = {}
    carpeta = ERA5 / cod
    filas = []
    p = carpeta / "hasta_2025_era5.csv.gz"
    if p.exists():
        filas.append(csv.DictReader(io.TextIOWrapper(gzip.open(p), encoding="utf-8")))
    for q in sorted(carpeta.glob("20*.csv")):
        filas.append(csv.DictReader(open(q, encoding="utf-8")))
    for rd in filas:
        for r in rd:
            try:
                v = float(r["lluvia"])
            except (KeyError, TypeError, ValueError):
                continue
            out[date.fromisoformat(r["fecha"])] = v
    return out


class Diaria:
    """Serie diaria de la capital: base (validada AEMET o ERA5) + cola provisional."""

    def __init__(self):
        self.base: dict[date, float] = {}
        self.cola: dict[date, float] = {}
        self.cola_fuente: dict[date, str] = {}
        self.fuente_base = ""

    @property
    def serie(self) -> dict[date, float]:
        s = dict(self.cola)
        s.update(self.base)
        return s


def construir_cola(dia: Diaria, cod: str, slug: str, sin_red: bool):
    """Días posteriores al último de la base hasta ayer: Open-Meteo archivo (hasta anteayer) y previsión con past_days=7;
    lo que falte, del ERA5 del archivo del repo. Todo provisional."""
    if not dia.base:
        return None
    ultimo = max(dia.base)
    ayer = HOY - timedelta(days=1)
    desde = ultimo + timedelta(days=1)
    lat, lon, alt = COORD[slug]
    prev = None
    if not sin_red:
        if desde <= HOY - timedelta(days=2):
            r = om_seguro(OM_ARCHIVO, {"latitude": f"{lat:.3f}", "longitude": f"{lon:.3f}", "start_date": desde.isoformat(),
                                       "end_date": (HOY - timedelta(days=2)).isoformat(), "daily": "precipitation_sum",
                                       "timezone": "Europe/Madrid"})
            for d, v in parse_archivo(r).items():
                if desde <= d <= ayer:
                    dia.cola[d] = v
                    dia.cola_fuente[d] = "Open-Meteo archivo"
        r = om_seguro(OM_PREVISION, {"latitude": f"{lat:.3f}", "longitude": f"{lon:.3f}", "elevation": str(alt),
                                     "daily": "precipitation_sum", "models": ",".join(m[0] for m in MODELOS),
                                     "forecast_days": 16, "past_days": 7, "timezone": "Europe/Madrid"})
        if r:
            prev = parse_prevision(r)
            ec = prev.get("ecmwf_ifs025", {})
            for d, v in ec.items():
                if desde <= d <= ayer and d not in dia.cola:
                    dia.cola[d] = v
                    dia.cola_fuente[d] = "Open-Meteo previsión (últimos días)"
    # lo que siga sin cubrirse: ERA5 del archivo del repo (si llega)
    falta = [desde + timedelta(days=i) for i in range((ayer - desde).days + 1) if desde + timedelta(days=i) not in dia.cola]
    if falta:
        era = leer_era5(cod)
        for d in falta:
            if d in era:
                dia.cola[d] = era[d]
                dia.cola_fuente[d] = "ERA5 del archivo"
    return prev


# --------------------------------------------------------------------------------------------------- serie mensual
def serie_mensual(hist: Historia, cod: str, dia: Diaria, tipo_era5: bool):
    """{'AAAA-MM': {'p', 'fuente', 'prov'}} desde el primer mes con dato hasta el último mes cerrado. Mes sin dato: None."""
    serie = dia.serie
    if not serie:
        return {}, None
    primero = min(serie)
    ide = ESTACIONES[cod][0] if cod in ESTACIONES else None
    if ide:
        ofi = hist.oficial.get(ide) or {}
        if ofi:
            primero = min(primero, date.fromisoformat(min(ofi) + "-01"))
    cierre = (HOY.replace(day=1) - timedelta(days=1))
    out: dict[str, dict | None] = {}
    y, m = primero.year, primero.month
    while (y, m) <= (cierre.year, cierre.month):
        clave = ym(y, m)
        nd = calendar.monthrange(y, m)[1]
        reg = None
        if ide:
            mm = hist.mensual(ide, y, m)
            if mm and mm.get("p") is not None:
                f = {"mensual oficial": "AEMET, mensual oficial", "diarios": "AEMET, diarios validados",
                     "balance verificado": "balance verificado"}.get(mm["fuente"], mm["fuente"])
                reg = {"p": float(mm["p"]), "fuente": f, "prov": False}
            else:
                o = (hist.oficial.get(ide) or {}).get(clave)
                if o and len(o) > 5 and o[5] is not None:
                    reg = {"p": float(o[5]), "fuente": "AEMET, mensual oficial", "prov": False}
        if reg is None:
            dias = [date(y, m, d) for d in range(1, nd + 1)]
            if all(d in serie for d in dias):
                en_cola = any(d in dia.cola and d not in dia.base for d in dias)
                if tipo_era5:
                    f = "ERA5 en la capital" + (" (último tramo provisional)" if en_cola else "")
                else:
                    f = "AEMET, diarios validados + cola provisional" if en_cola else "AEMET, diarios validados"
                reg = {"p": sum(serie[d] for d in dias), "fuente": f, "prov": en_cola}
        out[clave] = reg
        m += 1
        if m == 13:
            y, m = y + 1, 1
    # recorta los huecos del principio: la serie empieza en el primer mes con dato
    claves = list(out)
    while claves and out[claves[0]] is None:
        out.pop(claves.pop(0))
    return out, (claves[0] if claves else None)


def lista_meses(mensual: dict) -> list[str]:
    return list(mensual)


def normal_mensual(mensual: dict) -> dict[int, tuple[float | None, str]]:
    """Normal de cada mes del calendario: media 1991-2020 (≥ 24 años) o, si no, toda la serie con ≥ 30 años."""
    out = {}
    for mo in range(1, 13):
        ref = [r["p"] for k, r in mensual.items() if r and int(k[5:]) == mo and REF0 <= int(k[:4]) <= REF1]
        if len(ref) >= MIN_REF:
            out[mo] = (sum(ref) / len(ref), f"{REF0}-{REF1}")
            continue
        todo = [r["p"] for k, r in mensual.items() if r and int(k[5:]) == mo]
        out[mo] = ((sum(todo) / len(todo), "serie completa") if len(todo) >= MIN_SERIE_LARGA else (None, "sin referencia"))
    return out


# --------------------------------------------------------------------------------------------------- SPI
def spi_escala(mensual: dict, k: int):
    """{'AAAA-MM': spi} para la escala k (meses). Gamma por máxima verosimilitud sobre 1991-2020 (o toda la serie con
    ≥ 30 años), mezcla para ceros de McKee: H = q + (1−q)·G. Un acumulado con un mes sin dato no se calcula."""
    from scipy.stats import gamma, norm

    meses = list(mensual)
    acum: dict[str, float] = {}
    for i in range(k - 1, len(meses)):
        ventana = meses[i - k + 1:i + 1]
        vals = [mensual[x]["p"] if mensual[x] else None for x in ventana]
        if all(v is not None for v in vals):
            acum[meses[i]] = sum(vals)
    out: dict[str, float] = {}
    alternativas = []
    for mo in range(1, 13):
        del_mes = {c: x for c, x in acum.items() if int(c[5:]) == mo}
        ref = [x for c, x in del_mes.items() if REF0 <= int(c[:4]) <= REF1]
        if len(ref) >= MIN_REF:
            muestra = ref
        elif len(del_mes) >= MIN_SERIE_LARGA:
            muestra = list(del_mes.values())
            alternativas.append(mo)
        else:
            continue
        q = sum(1 for x in muestra if x <= 0) / len(muestra)
        pos = [x for x in muestra if x > 0]
        if len(pos) < 8 or statistics.pvariance(pos) <= 0:
            continue
        a, _loc, escala = gamma.fit(pos, floc=0)
        for c, x in del_mes.items():
            g = float(gamma.cdf(x, a, loc=0, scale=escala)) if x > 0 else 0.0
            h = q + (1 - q) * g
            h = min(max(h, 1e-6), 1 - 1e-6)
            out[c] = float(norm.ppf(h))
    return out, alternativas


def clase_spi(v) -> str | None:
    if v is None:
        return None
    v = r2(v)
    if v >= 2:
        return "extremadamente húmedo"
    if v >= 1.5:
        return "muy húmedo"
    if v >= 1:
        return "moderadamente húmedo"
    if v > -1:
        return "normal"
    if v > -1.5:
        return "sequía moderada"
    if v > -2:
        return "sequía severa"
    return "sequía extrema"


def nivel_semaforo(s3, s6, s12) -> int:
    """Regla del semáforo (REGLA_SEMAFORO). 5 = sin SPI a 6 y 12 meses."""
    if s6 is None or s12 is None:
        return 5
    s6, s12 = r2(s6), r2(s12)
    s3 = None if s3 is None else r2(s3)
    peor = min(s6, s12)
    if peor <= -2:
        return 4
    if peor <= -1.5:
        return 3
    if peor <= -1:
        return 2
    vals = [x for x in (s3, s6, s12) if x is not None]
    return 1 if min(vals) <= -0.7 else 0


def episodios(spi12: dict, mensual: dict, normal: dict):
    """Meses consecutivos con SPI-12 ≤ −1. Devuelve los 5 de mínimo más bajo (con la lluvia de los 12 meses del mínimo)."""
    meses = list(mensual)
    eps, cur = [], []
    for c in meses:
        v = spi12.get(c)
        if v is not None and r2(v) <= -1:
            cur.append(c)
        else:
            if cur:
                eps.append(cur)
            cur = []
    if cur:
        eps.append(cur)
    res = []
    for e in eps:
        vmin = min(e, key=lambda c: spi12[c])
        i = meses.index(vmin)
        ventana = meses[max(0, i - 11):i + 1]
        pct = None
        if len(ventana) == 12 and all(mensual[c] for c in ventana) and all(normal[int(c[5:])][0] for c in ventana):
            real = sum(mensual[c]["p"] for c in ventana)
            norm_ = sum(normal[int(c[5:])][0] for c in ventana)
            pct = p0(real / norm_ * 100) if norm_ > 0 else None
        res.append({"inicio": e[0], "fin": e[-1], "meses": len(e), "spi_min": r2(spi12[vmin]), "mes_min": vmin,
                    "pct_normal": pct, "en_curso": e[-1] == meses[-1]})
    res.sort(key=lambda x: x["spi_min"])
    return res[:5]


# --------------------------------------------------------------------------------------------------- ventanas diarias
def dia_seguro(y: int, m: int, d: int) -> date:
    return date(y, m, min(d, calendar.monthrange(y, m)[1]))


def sumar(serie: dict, a: date, b: date):
    """(suma, días con dato, días de la ventana)."""
    n = (b - a).days + 1
    s, c = 0.0, 0
    d = a
    for _ in range(n):
        v = serie.get(d)
        if v is not None:
            s += v
            c += 1
        d += timedelta(days=1)
    return s, c, n


def normal_ventana(serie: dict, fin_mes: int, fin_dia: int, largo: int | None = None, hidro: bool = False,
                   inicio_hidro: bool = True):
    """Media 1991-2020 de la lluvia (o del nº de días ≥ 1 mm si largo se da con hidro=False y cuenta=…) en una ventana.
    hidro=True: ventana del 1 de octubre al día (fin_mes, fin_dia), con años hidrológicos 1991/92 a 2019/20."""
    vals = []
    if hidro:
        for y0 in range(REF0, REF1):          # 1991..2019
            a = date(y0, 10, 1)
            b = dia_seguro(y0 if fin_mes >= 10 else y0 + 1, fin_mes, fin_dia)
            s, c, n = sumar(serie, a, b)
            if n and c / n >= COBERTURA:
                vals.append(s)
    else:
        for y in range(REF0, REF1 + 1):
            b = dia_seguro(y, fin_mes, fin_dia)
            a = b - timedelta(days=largo - 1)
            s, c, n = sumar(serie, a, b)
            if n and c / n >= COBERTURA:
                vals.append(s)
    return (sum(vals) / len(vals), len(vals)) if len(vals) >= MIN_REF else (None, len(vals))


def normal_dias_lluvia(serie: dict, fin: date, largo: int):
    vals = []
    for y in range(REF0, REF1 + 1):
        b = dia_seguro(y, fin.month, fin.day)
        a = b - timedelta(days=largo - 1)
        c = sum(1 for i in range(largo) if (a + timedelta(days=i)) in serie)
        if c / largo >= COBERTURA:
            vals.append(sum(1 for i in range(largo) if serie.get(a + timedelta(days=i), 0) >= UMBRAL_LLUVIA))
    return (sum(vals) / len(vals), len(vals)) if len(vals) >= MIN_REF else (None, len(vals))


def calc_hidro(serie: dict, ult: date) -> dict | None:
    y0 = ult.year if ult.month >= 10 else ult.year - 1
    ini = date(y0, 10, 1)
    s, c, n = sumar(serie, ini, ult)
    nor, nn = normal_ventana(serie, ult.month, ult.day, hidro=True)
    res = {"inicio": ini.isoformat(), "hasta": ult.isoformat(), "mm": r1(s) if c / n >= COBERTURA else None,
           "normal_mm": r1(nor) if nor is not None else None, "pct": None, "dias_con_dato": c, "dias": n,
           "anios_normal": nn, "anterior": None}
    if res["mm"] is not None and nor:
        res["pct"] = p0(s / nor * 100)
    a0, a1 = date(y0 - 1, 10, 1), date(y0, 9, 30)
    s2, c2, n2 = sumar(serie, a0, a1)
    nor2, _ = normal_ventana(serie, 9, 30, hidro=True)
    if c2 / n2 >= COBERTURA:
        res["anterior"] = {"inicio": a0.isoformat(), "fin": a1.isoformat(), "mm": r1(s2),
                           "normal_mm": r1(nor2) if nor2 is not None else None,
                           "pct": p0(s2 / nor2 * 100) if nor2 else None}
    return res


def curvas_hidro(serie: dict, ult: date):
    """Curvas acumuladas por día desde el 1 de octubre: año en curso, anterior y normal (1991/92-2019/20)."""
    y0 = ult.year if ult.month >= 10 else ult.year - 1

    def acum(a: date, n: int, hasta: date | None = None):
        out, s = [], 0.0
        for i in range(n):
            d = a + timedelta(days=i)
            if hasta and d > hasta:
                break
            s += serie.get(d, 0.0)
            out.append(s)
        return out
    act = acum(date(y0, 10, 1), 366, ult)
    ant = acum(date(y0 - 1, 10, 1), 365)
    cs = []
    for y in range(REF0, REF1):
        a = date(y, 10, 1)
        s, c, n = sumar(serie, a, date(y + 1, 9, 30))
        if c / n >= COBERTURA:
            cs.append(acum(a, 365))
    nor = [sum(x[i] for x in cs) / len(cs) for i in range(365)] if len(cs) >= MIN_REF else None
    return act, ant, nor


def calc_dias(dia: Diaria, ult: date) -> dict:
    serie = dia.serie
    # días consecutivos sin lluvia significativa hasta el último día con dato
    n, d, hueco = 0, ult, False
    ultimo_llu, mm_llu = None, None
    while True:
        v = serie.get(d)
        if v is None:
            hueco = True
            break
        if v >= UMBRAL_LLUVIA:
            ultimo_llu, mm_llu = d, v
            break
        n += 1
        d -= timedelta(days=1)
        if n > 4000:
            break
    res = {"hasta": ult.isoformat(), "sin_lluvia": n, "ultimo_dia_lluvia": ultimo_llu.isoformat() if ultimo_llu else None,
           "mm_ultimo": r1(mm_llu) if mm_llu is not None else None, "hueco_en_la_cuenta": hueco}
    for largo in (30, 90):
        a = ult - timedelta(days=largo - 1)
        c = sum(1 for i in range(largo) if (a + timedelta(days=i)) in serie)
        res[f"dias_lluvia_{largo}"] = (sum(1 for i in range(largo) if serie.get(a + timedelta(days=i), 0) >= UMBRAL_LLUVIA)
                                       if c / largo >= COBERTURA else None)
        nm, _ = normal_dias_lluvia(serie, ult, largo)
        res[f"normal_{largo}"] = r1(nm) if nm is not None else None
    prov_desde = min((x for x in dia.cola if x not in dia.base), default=None)
    res["provisional"] = bool(ultimo_llu and prov_desde and ultimo_llu >= prov_desde)
    res["ultimo_dia_es_provisional"] = bool(prov_desde and ult >= prov_desde)
    return res


# --------------------------------------------------------------------------------------------------- embalses, nieve, previsión
def calc_embalses(slug: str, url_web: dict) -> dict | None:
    es = EMB_SLUG.get(slug)
    if not es:
        return None
    d = leer_json(EMB / f"{es}.json")
    if not d:
        return None
    cap, vol = d.get("capacidad_total_hm3"), d.get("volumen_total_hm3")
    pct = d.get("pct")
    if pct is None and cap:
        pct = vol / cap * 100
    if pct is None:
        return None
    grandes = sorted((e for e in d.get("embalses") or [] if e.get("capacidad_hm3")), key=lambda e: -e["capacidad_hm3"])[:3]
    return {"pct": r1(pct), "pct_hace_1a": d.get("pct_hace_1a"), "pct_media_10a": d.get("pct_media_10a"),
            "volumen_hm3": vol, "capacidad_hm3": cap, "boletin": d.get("boletin_fecha"),
            "grandes": [{"nombre": e["nombre"], "pct": e.get("pct"), "capacidad_hm3": e["capacidad_hm3"]} for e in grandes],
            "pagina": url_web.get(es) or d.get("url_web") or f"{WEB}/embalses-{slug}/"}


def calc_nieve(slug: str, idx: dict) -> dict | None:
    if HOY.month not in (11, 12, 1, 2, 3, 4, 5):
        return None
    p = idx.get(slug)
    if not p:
        return None
    m = p.get("monte") or {}
    return {"monte": m.get("nombre"), "altitud_m": m.get("altitud_m"), "temporada_cm": m.get("temporada_cm"),
            "normal_hoy_cm": m.get("normal_hoy_cm"), "espesor_cm": m.get("espesor_cm"), "satelite_pct": p.get("satelite_pct"),
            "pagina": p.get("url") or f"{WEB}/nieve/{slug}/"}


def calc_prevision(prev: dict | None, serie: dict) -> dict | None:
    if not prev:
        return None
    dias15 = [HOY + timedelta(days=i) for i in range(15)]
    dias7 = dias15[:7]

    def suma(m: dict, ds: list):
        vs = [m.get(d) for d in ds]
        return None if any(v is None for v in vs) else r1(sum(vs))
    mods, v7, v15 = {}, [], []
    for mid, nombre in MODELOS:
        m = prev.get(mid)
        if not m:
            mods[MOD_CLAVE[mid]] = {"nombre": nombre, "d7": None, "d15": None, "respondio": False}
            continue
        s7, s15 = suma(m, dias7), suma(m, dias15)
        mods[MOD_CLAVE[mid]] = {"nombre": nombre, "d7": s7, "d15": s15, "respondio": True}
        if s7 is not None:
            v7.append(s7)
        if s15 is not None:
            v15.append(s15)
    if not v7 and not v15:
        return None
    nor, _ = normal_ventana(serie, dias15[-1].month, dias15[-1].day, largo=15)
    return {"modelos": mods, "mediana_7": r1(statistics.median(v7)) if v7 else None,
            "mediana_15": r1(statistics.median(v15)) if v15 else None,
            "min_15": min(v15) if v15 else None, "max_15": max(v15) if v15 else None, "n_modelos_15": len(v15),
            "normal_15": r1(nor) if nor is not None else None, "desde": dias15[0].isoformat(),
            "hasta": dias15[-1].isoformat()}


# --------------------------------------------------------------------------------------------------- textos
FRASES = {
    0: "Ni el SPI a 3, 6 ni a 12 meses señalan un déficit de lluvia relevante: la situación es normal.",
    1: "Hay señales de déficit en alguna escala, pero ni el SPI a 6 ni el de 12 meses llegan al umbral de sequía.",
    5: "No hay serie de lluvia suficiente para calcular el SPI: la provincia se publica sin semáforo.",
}


def frase_nivel(nv: int, s6, s12) -> str:
    if nv in FRASES:
        return FRASES[nv]
    esc, v = (6, s6) if (s6 is not None and (s12 is None or s6 <= s12)) else (12, s12)
    return (f"El SPI a {esc} meses es {f2(v)}: {NIVELES[nv][0].lower()} en el semáforo de calentamientoglobal.es "
            f"(la regla mira el peor de los SPI a 6 y 12 meses).")


def textos_provincia(r: dict) -> dict:
    nom, nv = r["provincia"], r["nivel"]
    h = r["hidro"]
    esc_k = r["escala_clave"]
    v = r["spi"][str(esc_k)]["valor"]
    fuente = "reanálisis ERA5" if r["tipo"] == "reanalisis" else "AEMET"
    cierre = mes_txt(r["ultimo_mes_cerrado"]) if r["ultimo_mes_cerrado"] else ""
    if nv == 5:
        huecos = ", ".join(mes_txt(x) for x in r["huecos"][-2:]) or "meses recientes"
        resumen = (f"{nom}, a {fecha_txt(HOY)}: sin semáforo. A la serie de lluvia de {r['capital']} le falta {huecos} "
                   f"completo, y sin ese mes no se calcula el SPI. Se muestran los embalses y la lluvia prevista a 15 días "
                   f"({fuente}).")
        titular = f"{nom}: sin semáforo de sequía por un mes sin lluvia completa en la serie"
    else:
        hid = ""
        if h and h["mm"] is not None and h["pct"] is not None:
            ini = date.fromisoformat(h["inicio"])
            hid = (f"; del {ini.day} de {MESES[ini.month - 1]} al {fecha_txt(date.fromisoformat(h['hasta']))} cayeron "
                   f"{f1(h['mm'])} mm en {r['capital']}, el {h['pct']} % de lo normal")
        resumen = (f"{nom}, a {fecha_txt(HOY)}: «{NIVELES[nv][0].lower()}». SPI a {esc_k} meses de {f2(v)} en {cierre}{hid} "
                   f"({fuente}).")
        titular = f"{NIVELES[nv][0]} en {nom}: SPI a {esc_k} meses de {f2(v)}"
        if h and h["pct"] is not None:
            titular += f" y el {h['pct']} % de la lluvia normal del año hidrológico"
    est = ESTACIONES.get(r["cod"])
    nota = None
    if est and est[3] == "referencia":
        nota = f"La capital no tiene serie larga: se usa la estación de referencia de {est[2]}."
    return {"titular": titular, "resumen": resumen, "frase_nivel": frase_nivel(nv, r["spi"]["6"]["valor"], r["spi"]["12"]["valor"]),
            "nota_estacion": nota}


# --------------------------------------------------------------------------------------------------- cálculo por provincia
def calcular(hist: Historia, cod: str, slug: str, url_web_emb: dict, nieve_idx: dict, sin_red: bool) -> dict:
    nombre = NOMBRE[cod]
    era5 = cod in SIN_SERIE
    dia = Diaria()
    if era5:
        dia.base = leer_era5(cod)
        dia.fuente_base = "ERA5 en la capital"
        capital, estacion, ide, tipo = CAPITAL_SIN_SERIE[cod], "ERA5 en la capital (reanálisis Copernicus/ECMWF)", None, "reanalisis"
    else:
        ide, capital, estacion, tipo = ESTACIONES[cod][0], ESTACIONES[cod][1], ESTACIONES[cod][2], ESTACIONES[cod][3]
        dia.base = {fe: float(v[2]) for fe, v in (hist.diarios.get(ide) or {}).items() if v[2] is not None}
        dia.fuente_base = "AEMET, diarios validados"
        fe_parse = {}
        for k, v in dia.base.items():
            fe_parse[date.fromisoformat(k) if isinstance(k, str) else k] = v
        dia.base = fe_parse
    prev = construir_cola(dia, cod, slug, sin_red)
    serie = dia.serie
    mensual, inicio = serie_mensual(hist, cod, dia, era5)
    res = {"cod": cod, "provincia": nombre, "slug": slug, "capital": capital, "estacion": estacion, "indicativo": ide,
           "tipo": tipo}
    if not mensual or len(mensual) < 24:
        res.update({"fuente_serie": dia.fuente_base, "inicio_serie": inicio, "sin_serie": True})
    ult = max(serie) if serie else None
    meses = list(mensual)
    cerrado = meses[-1] if meses else None
    # SPI
    spi_all, alts = {}, {}
    for k in (3, 6, 12):
        spi_all[k], a = spi_escala(mensual, k) if mensual else ({}, [])
        if a:
            alts[str(k)] = a
    s = {k: spi_all[k].get(cerrado) for k in (3, 6, 12)}
    nv = nivel_semaforo(s[3], s[6], s[12])
    normal = normal_mensual(mensual) if mensual else {}
    eps = episodios(spi_all[12], mensual, normal) if spi_all[12] else []
    puesto = None
    if s[12] is not None:
        todos = sorted(spi_all[12].values())
        puesto = {"puesto": 1 + sum(1 for v in todos if r2(v) < r2(s[12])), "de": len(todos)}
    provisional_desde = min((x for x in dia.cola if x not in dia.base), default=None)
    res.update({
        "fuente_serie": ("ERA5 en la capital (reanálisis Copernicus/ECMWF)" if era5 else "AEMET (precipitación oficial)"),
        "inicio_serie": inicio, "ultimo_mes_cerrado": cerrado,
        "ultimo_dia_dato": ult.isoformat() if ult else None,
        "provisional_desde": provisional_desde.isoformat() if provisional_desde else None,
        "cola": {"dias": len([x for x in dia.cola if x not in dia.base]),
                 "fuentes": sorted(set(dia.cola_fuente.values()))},
        "nivel": nv, "nivel_texto": NIVELES[nv][0], "color": NIVELES[nv][1],
        "escala_clave": (6 if (nv >= 2 and s[6] is not None and (s[12] is None or r2(s[6]) <= r2(s[12]))) else 12),
        "huecos": [c for c in meses[-24:] if mensual[c] is None],
        "excedentaria": bool(s[12] is not None and r2(s[12]) >= 1),
        "spi": {str(k): {"valor": None if s[k] is None else r2(s[k]), "clase": clase_spi(s[k])} for k in (3, 6, 12)},
        "referencia": {"periodo": f"{REF0}-{REF1}", "meses_con_serie_completa": alts,
                       "nota": ("en las escalas y meses indicados se usó toda la serie (≥ 30 años) por no llegar a 24 "
                                "años válidos en 1991-2020") if alts else None},
        "serie_spi12": [{"mes": c, "spi": r2(v)} for c, v in sorted(spi_all[12].items())],
        "serie_mensual_24": [{"mes": c, "p": r1(mensual[c]["p"]) if mensual[c] else None,
                              "normal": r1(normal[int(c[5:])][0]) if normal.get(int(c[5:]), (None,))[0] is not None else None,
                              "fuente": mensual[c]["fuente"] if mensual[c] else None,
                              "provisional": bool(mensual[c] and mensual[c]["prov"])} for c in meses[-24:]],
        "normal_anual_mm": r1(sum(v[0] for v in normal.values())) if normal and all(v[0] is not None for v in normal.values()) else None,
        "hidro": calc_hidro(serie, ult) if ult else None,
        "dias": calc_dias(dia, ult) if ult else None,
        "embalses": calc_embalses(slug, url_web_emb),
        "nieve": calc_nieve(slug, nieve_idx),
        "prevision": calc_prevision(prev, serie),
        "episodios": eps, "puesto_actual": puesto,
    })
    res["textos"] = textos_provincia(res)
    res["generado"] = HOY.isoformat()
    res["fuente"] = FUENTE
    res["licencia"] = LICENCIA
    base = PAGES + slug
    res["urls"] = {"pagina": f"{WEB}/sequia/{slug}/", "json": base + ".json", "csv": base + ".csv",
                   "lluvias": f"{WEB}/lluvias-en-{slug}/", "embalses": (res["embalses"] or {}).get("pagina"),
                   "nieve": f"{WEB}/nieve/{slug}/" if slug in nieve_idx else None,
                   "cambio_climatico": f"{WEB}/cambio-climatico-en-{slug}/",
                   "grafico_spi": f"{PAGES}graf/{slug}-spi.svg", "grafico_hidro": f"{PAGES}graf/{slug}-hidro.svg"}
    # interno (no va al JSON)
    res["_interno"] = {"mensual": mensual, "spi_all": spi_all, "curvas": curvas_hidro(serie, ult) if ult else None,
                       "cola": dia.cola, "base": dia.base}
    return res


# --------------------------------------------------------------------------------------------------- CSV y SVG
def csv_provincia(r: dict) -> str:
    it = r["_interno"]
    lin = [f"# Fuente: AEMET, cálculo de calentamientoglobal.es, {LICENCIA}, {r['urls']['pagina']}"
           + (" (precipitación: reanálisis ERA5 en la capital)" if r["tipo"] == "reanalisis" else ""),
           "mes,p,fuente,spi3,spi6,spi12"]
    for c, reg in it["mensual"].items():
        if not reg:
            lin.append(f"{c},,sin dato,,,")
            continue
        sp = ["" if it["spi_all"][k].get(c) is None else f"{r2(it['spi_all'][k][c]):.2f}" for k in (3, 6, 12)]
        f = reg["fuente"] + ("; provisional" if reg["prov"] and "provisional" not in reg["fuente"] else "")
        lin.append(f'{c},{reg["p"]:.1f},"{f}",' + ",".join(sp))
    return "\n".join(lin) + "\n"


def esc(t) -> str:
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def cab_svg(w: int, h: int, titulo: str, desc: str) -> list[str]:
    return [f'<?xml version="1.0" encoding="UTF-8"?><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
            f'width="{w}" height="{h}" role="img" aria-labelledby="t d" font-family="-apple-system,BlinkMacSystemFont,'
            f'\'Segoe UI\',Roboto,Helvetica,Arial,sans-serif">',
            f'<title id="t">{esc(titulo)}</title><desc id="d">{esc(desc)}</desc>']


def svg_spi(r: dict) -> str:
    W, H = 1600, 420
    X0, X1, Y0, Y1 = 64, 1580, 22, 356
    serie = r["_interno"]["spi_all"][12]
    meses = list(r["_interno"]["mensual"])
    n = len(meses)
    pw = X1 - X0
    paso = pw / max(n, 1)
    vmax = 3.2

    def y(v):
        v = max(-vmax, min(vmax, v))
        return Y0 + (vmax - v) / (2 * vmax) * (Y1 - Y0)
    s = cab_svg(W, H, f"SPI a 12 meses en {r['provincia']}", f"SPI a 12 meses de {r['capital']} desde {r['inicio_serie']} "
                f"hasta {r['ultimo_mes_cerrado']}; rojo por debajo de −1, azul por encima de 1.")
    for v, lab, dash in ((0, "0", ""), (1, "1", "4 6"), (-1, "−1", "4 6"), (-1.5, "−1,5", "4 6"), (-2, "−2", "4 6")):
        s.append(f'<line x1="{X0}" x2="{X1}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="{SEC}" stroke-opacity="{0.7 if v == 0 else 0.4}" '
                 f'stroke-width="1.4"{(" stroke-dasharray=%s" % chr(34) + dash + chr(34)) if dash else ""}/>')
        s.append(f'<text x="{X0 - 8}" y="{y(v) + 6:.1f}" font-size="20" fill="{SEC}" text-anchor="end">{lab}</text>')
    bw = max(0.9, paso * 0.86)
    ult_i = None
    trazos: dict[str, list[str]] = {}
    y0 = y(0)
    for i, c in enumerate(meses):
        v = serie.get(c)
        if v is None:
            continue
        col = ("#8b1a1a" if v <= -2 else "#e0552b" if v <= -1.5 else "#f0a04b" if v <= -1 else "#3d8bd1" if v >= 1
               else "#7f9db3")
        if c == r["ultimo_mes_cerrado"]:
            col, ult_i = DESTACADO, i
        yv = y(v)
        trazos.setdefault(col, []).append(f"M{X0 + i * paso:.1f} {y0:.1f}H{X0 + i * paso + bw:.1f}V{yv:.1f}H{X0 + i * paso:.1f}z")
    for col, ds in trazos.items():
        s.append(f'<path fill="{col}" d="{"".join(ds)}"/>')
    # años cada 10
    for i, c in enumerate(meses):
        if c.endswith("-01") and int(c[:4]) % 10 == 0:
            s.append(f'<text x="{X0 + i * paso:.1f}" y="{Y1 + 26}" font-size="20" fill="{SEC}" text-anchor="middle">{c[:4]}</text>')
    if ult_i is not None:
        xv = X0 + ult_i * paso
        v = serie[r["ultimo_mes_cerrado"]]
        etq = f"{MES_C[int(r['ultimo_mes_cerrado'][5:]) - 1]} {r['ultimo_mes_cerrado'][:4]}: {f2(v)}"
        ancho = len(etq) * 12.5 + 18
        s.append(f'<circle cx="{xv + bw / 2:.1f}" cy="{y(v):.1f}" r="6" fill="{DESTACADO}"/>')
        s.append(f'<rect x="{X1 - ancho:.1f}" y="{Y0 - 4}" width="{ancho:.1f}" height="34" rx="8" fill="#0c2133" fill-opacity="0.85"/>')
        s.append(f'<text x="{X1 - 10:.1f}" y="{Y0 + 20}" font-size="22" font-weight="700" fill="{DESTACADO}" '
                 f'text-anchor="end">{esc(etq)}</text>')
    s.append(f'<text x="{X0}" y="{H - 16}" font-size="19" fill="{SEC}">SPI a 12 meses · {esc(r["capital"])} · '
             f'{esc(r["urls"]["pagina"])} · {LICENCIA}</text>')
    s.append("</svg>")
    return "".join(s)


def svg_hidro(r: dict) -> str | None:
    cur = r["_interno"]["curvas"]
    if not cur or not cur[0]:
        return None
    act, ant, nor = cur
    W, H = 1600, 520
    X0, X1, Y0, Y1 = 90, 1560, 40, 440
    vmax = max([max(act), max(ant) if ant else 0, max(nor) if nor else 0, 10]) * 1.08
    paso = 10 ** math.floor(math.log10(vmax / 4))
    for k in (1, 2, 2.5, 5, 10):
        if vmax / (paso * k) <= 6:
            paso *= k
            break

    def px(i):
        return X0 + i / 365 * (X1 - X0)

    def py(v):
        return Y1 - v / vmax * (Y1 - Y0)

    def ruta(c):
        return "M" + "L".join(f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(c))
    h = r["hidro"]
    s = cab_svg(W, H, f"Lluvia acumulada del año hidrológico en {r['provincia']}",
                f"Lluvia acumulada desde el 1 de octubre en {r['capital']}: año en curso, año anterior y normal 1991-2020.")
    v = 0
    while v <= vmax:
        s.append(f'<line x1="{X0}" x2="{X1}" y1="{py(v):.1f}" y2="{py(v):.1f}" stroke="{SEC}" stroke-opacity="0.25" stroke-width="1.2"/>')
        s.append(f'<text x="{X0 - 10}" y="{py(v) + 6:.1f}" font-size="20" fill="{SEC}" text-anchor="end">{p0(v)}</text>')
        v += paso
    s.append(f'<text x="{X0 - 10}" y="{Y0 - 14}" font-size="20" fill="{SEC}" text-anchor="end">mm</text>')
    a = date(2001, 10, 1)   # año no bisiesto para las etiquetas de mes
    for k in range(12):
        d = date(2001 + (1 if (9 + k) >= 12 else 0), (9 + k) % 12 + 1, 1)
        i = (d - a).days
        s.append(f'<text x="{px(i) + 6:.1f}" y="{Y1 + 28}" font-size="20" fill="{SEC}">{MES_C[d.month - 1]}</text>')
        s.append(f'<line x1="{px(i):.1f}" x2="{px(i):.1f}" y1="{Y1}" y2="{Y1 + 6}" stroke="{SEC}" stroke-opacity="0.6"/>')
    if nor:
        s.append(f'<path d="{ruta(nor)}" fill="none" stroke="{SEC}" stroke-width="3.2" stroke-dasharray="9 7"/>')
    if ant:
        s.append(f'<path d="{ruta(ant)}" fill="none" stroke="#3d8bd1" stroke-width="2.6" stroke-opacity="0.9"/>')
    s.append(f'<path d="{ruta(act)}" fill="none" stroke="{DESTACADO}" stroke-width="4.6" stroke-linejoin="round"/>')
    i = len(act) - 1
    s.append(f'<circle cx="{px(i):.1f}" cy="{py(act[-1]):.1f}" r="7" fill="{DESTACADO}"/>')
    etq = f"{f1(act[-1])} mm" + (f" · {h['pct']} % de lo normal" if h and h.get("pct") is not None else "")
    ancho = len(etq) * 12.2 + 20
    ex = min(px(i) + 16, X1 - ancho)
    ey = max(Y0 + 8, py(act[-1]) - 54)
    s.append(f'<rect x="{ex:.1f}" y="{ey:.1f}" width="{ancho:.1f}" height="34" rx="8" fill="#0c2133" fill-opacity="0.85"/>')
    s.append(f'<text x="{ex + 10:.1f}" y="{ey + 24:.1f}" font-size="22" font-weight="700" fill="{DESTACADO}">{esc(etq)}</text>')
    lx, ly = X0 + 16, Y0 + 8
    for j, (col, dash, txt) in enumerate(((DESTACADO, "", f"Año hidrológico en curso (desde {r['hidro']['inicio'][:4]})"),
                                          (SEC, "9 7", "Normal 1991-2020"),
                                          ("#3d8bd1", "", "Año hidrológico anterior"))):
        s.append(f'<line x1="{lx}" x2="{lx + 40}" y1="{ly + j * 28}" y2="{ly + j * 28}" stroke="{col}" stroke-width="4"'
                 f'{(" stroke-dasharray=" + chr(34) + dash + chr(34)) if dash else ""}/>')
        s.append(f'<text x="{lx + 52}" y="{ly + j * 28 + 6}" font-size="21" fill="{TXT}">{esc(txt)}</text>')
    s.append(f'<text x="{X0}" y="{H - 16}" font-size="19" fill="{SEC}">Lluvia acumulada desde el 1 de octubre · {esc(r["capital"])} · '
             f'{esc(r["urls"]["pagina"])} · {LICENCIA}</text>')
    s.append("</svg>")
    return "".join(s)


_MAPA = None


def trazos_mapa() -> dict:
    """Trazos por provincia del mapa de /nieve/ (misma función, mismos trazos). Solo hay 50: Ceuta y Melilla no están."""
    global _MAPA
    if _MAPA is None:
        import nieve  # noqa: PLC0415  (se importa aquí: nieve.py no se toca)
        _MAPA = nieve.mapa_trazos()
    return _MAPA


def svg_mapa(niveles: dict, nombres: dict) -> str:
    W = round(14.6 * math.cos(math.radians(40)) * 46)
    H = round(10.0 * 46) + 40            # 40 px más de alto que el de /nieve/ para la leyenda en fila
    s = cab_svg(W, H, "Sequía en España por provincias", "Semáforo de sequía meteorológica por provincia (SPI a 3, 6 y 12 meses).")
    s.append(f'<rect x="2" y="{(44 - 36.4) * 46:.0f}" width="{(5.3 * math.cos(math.radians(40)) * 46):.0f}" '
             f'height="{2.6 * 46:.0f}" rx="8" fill="none" stroke="#2f5a7d" stroke-dasharray="4 4"/>')
    tr = trazos_mapa()
    for slug in ORDEN:
        if slug not in tr:
            continue
        nv = niveles.get(slug, 5)
        s.append(f'<path class="cgsq-p cgsq-p-{slug}" d="{tr[slug]}" fill="{NIVELES[nv][1]}" stroke="#0c2133" stroke-width="1.2">'
                 f'<title>{esc(nombres[slug])}: {esc(NIVELES[nv][0].lower())}</title></path>')
    # Ceuta y Melilla: no tienen trazo en el GeoJSON; recuadro propio junto al de Canarias
    s.append('<rect x="204" y="368" width="150" height="76" rx="8" fill="none" stroke="#2f5a7d" stroke-dasharray="4 4"/>')
    for j, (slug, etq) in enumerate((("ceuta", "Ceuta"), ("melilla", "Melilla"))):
        nv = niveles.get(slug, 5)
        cx = 244 + j * 70
        s.append(f'<circle class="cgsq-p cgsq-p-{slug}" cx="{cx}" cy="396" r="14" fill="{NIVELES[nv][1]}" stroke="#0c2133" '
                 f'stroke-width="1.2"><title>{etq}: {esc(NIVELES[nv][0].lower())}</title></circle>')
        s.append(f'<text x="{cx}" y="430" font-size="14" fill="{TXT}" text-anchor="middle">{etq}</text>')
    cortos = ("Normal", "Vigilancia", "Moderada", "Severa", "Extrema")
    for j in range(5):
        lx = 8 + j * 100
        s.append(f'<rect x="{lx}" y="{H - 38}" width="14" height="14" rx="3" fill="{NIVELES[j][1]}"/>')
        s.append(f'<text x="{lx + 20}" y="{H - 26}" font-size="14" fill="{TXT}">{cortos[j]}</text>')
    s.append(f'<text x="{W - 6}" y="{H - 6}" font-size="12" fill="{SEC}" text-anchor="end">{WEB}/sequia/ · {LICENCIA}</text>')
    s.append("</svg>")
    return "".join(s)


# --------------------------------------------------------------------------------------------------- índices nacionales
def sin_dato_item(r: dict) -> dict:
    hu = r.get("huecos") or []
    motivo = ("AEMET no publica la lluvia de algún día de " + ", ".join(hu[-3:]) + "; sin el mes completo no se calcula el SPI "
              "que lo incluye (los huecos no se rellenan)") if hu else "serie de lluvia insuficiente para calcular el SPI"
    return {"slug": r["slug"], "provincia": r["provincia"], "huecos": hu, "motivo": motivo}


def fila_index(r: dict) -> dict:
    return {"slug": r["slug"], "provincia": r["provincia"], "capital": r["capital"], "nivel": r["nivel"],
            "nivel_texto": r["nivel_texto"], "spi3": r["spi"]["3"]["valor"], "spi6": r["spi"]["6"]["valor"],
            "spi12": r["spi"]["12"]["valor"], "ultimo_mes_cerrado": r["ultimo_mes_cerrado"],
            "puesto_spi12": (r["puesto_actual"] or {}).get("puesto"),
            "hidro_pct": (r["hidro"] or {}).get("pct"), "hidro_mm": (r["hidro"] or {}).get("mm"),
            "dias_sin_lluvia": (r["dias"] or {}).get("sin_lluvia"),
            "embalses_pct": (r["embalses"] or {}).get("pct"),
            "prevision_mediana_15": (r["prevision"] or {}).get("mediana_15"), "url": r["urls"]["pagina"]}


def nacional(res: list[dict], emb_nac: dict | None) -> dict:
    cnt = {n: sum(1 for r in res if r["nivel"] == n) for n in range(6)}
    con = [r for r in res if r["spi"]["12"]["valor"] is not None]
    secas = sorted(con, key=lambda r: r["spi"]["12"]["valor"])[:10]
    humedas = sorted(con, key=lambda r: -r["spi"]["12"]["valor"])[:5]

    def corto(r):
        return {"slug": r["slug"], "provincia": r["provincia"], "spi12": r["spi"]["12"]["valor"], "nivel": r["nivel"],
                "url": r["urls"]["pagina"]}
    # media ponderada por superficie: lluvia del año hidrológico / lluvia normal de la misma ventana
    num = den = 0.0
    for r in res:
        h = r["hidro"]
        if h and h.get("mm") is not None and h.get("normal_mm"):
            w = SUPERFICIE_KM2[r["slug"]]
            num += w * h["mm"]
            den += w * h["normal_mm"]
    cobertura = sum(SUPERFICIE_KM2[r["slug"]] for r in res if (r["hidro"] or {}).get("mm") is not None
                    and (r["hidro"] or {}).get("normal_mm")) / sum(SUPERFICIE_KM2.values()) * 100
    hid = None
    if den:
        w_mm = sum(SUPERFICIE_KM2[r["slug"]] * r["hidro"]["mm"] for r in res if (r["hidro"] or {}).get("mm") is not None
                   and r["hidro"].get("normal_mm")) / sum(SUPERFICIE_KM2[r["slug"]] for r in res
                                                         if (r["hidro"] or {}).get("mm") is not None and r["hidro"].get("normal_mm"))
        w_nor = den / sum(SUPERFICIE_KM2[r["slug"]] for r in res if (r["hidro"] or {}).get("mm") is not None
                          and r["hidro"].get("normal_mm"))
        hasta = max(r["hidro"]["hasta"] for r in res if r["hidro"])
        hid = {"inicio": next(r["hidro"]["inicio"] for r in res if r["hidro"]), "hasta": hasta, "mm": r1(w_mm),
               "normal_mm": r1(w_nor), "pct": p0(num / den * 100), "deficit_mm": r1(w_mm - w_nor),
               "superficie_cubierta_pct": p0(cobertura)}
    cap30 = [r for r in res if (r["dias"] or {}).get("sin_lluvia", 0) >= 30]
    cap30.sort(key=lambda r: -r["dias"]["sin_lluvia"])
    sin_dato = [sin_dato_item(r) for r in res if r["nivel"] == 5]
    nac = {"generado": HOY.isoformat(), "niveles": {str(n): {"texto": NIVELES[n][0], "n": cnt[n]} for n in range(6)},
           "n_provincias": len(res), "n_con_semaforo": len(res) - cnt[5],
           "n_en_sequia": cnt[2] + cnt[3] + cnt[4],
           "top10_secas": [corto(r) for r in secas], "top5_humedas": [corto(r) for r in humedas],
           "hidro_nacional": hid,
           "capitales_30_dias": {"n": len(cap30), "lista": [{"slug": r["slug"], "capital": r["capital"],
                                                             "dias": r["dias"]["sin_lluvia"]} for r in cap30]},
           "embalses": ({"pct": emb_nac.get("pct"), "pct_hace_1a": emb_nac.get("pct_hace_1a"),
                         "pct_media_10a": emb_nac.get("pct_media_10a"), "boletin": emb_nac.get("boletin")} if emb_nac else None),
           "sin_dato": sin_dato, "periodo_referencia": f"{REF0}-{REF1}", "regla_semaforo": REGLA_SEMAFORO,
           "fuente": FUENTE, "licencia": LICENCIA}
    nac["nota"] = nota_nacional(nac, res)
    return nac


def nota_nacional(n: dict, res: list[dict]) -> str:
    cont = n["n_con_semaforo"]
    nv = {k: v["n"] for k, v in n["niveles"].items()}
    p = [f"A {fecha_txt(HOY)}, el Monitor de sequía de calentamientoglobal.es sitúa a {n['n_en_sequia']} de las {cont} provincias "
         f"con semáforo en sequía meteorológica: {nv['2']} en nivel moderado, {nv['3']} severo y {nv['4']} extremo. "
         f"Otras {nv['1']} están en vigilancia y {nv['0']} en situación normal."]
    if n["top10_secas"]:
        t = n["top10_secas"][:3]
        p.append("Las de SPI a 12 meses más bajo son " + ", ".join(x["provincia"] for x in t[:-1]) + f" y {t[-1]['provincia']}.")
    h = n["hidro_nacional"]
    if h:
        ini, fin = date.fromisoformat(h["inicio"]), date.fromisoformat(h["hasta"])
        p.append(f"Del {ini.day} de {MESES[ini.month - 1]} al {fecha_txt(fin)}, la lluvia media ponderada por superficie es de "
                 f"{f1(h['mm'])} mm, el {h['pct']} % de lo normal 1991-2020.")
    if n["embalses"] and n["embalses"].get("pct") is not None:
        p.append(f"Los embalses de España están al {f1(n['embalses']['pct']).replace(',0', '')} % (MITECO).")
    c = n["capitales_30_dias"]["n"]
    p.append(f"{c} capitales llevan 30 días o más sin lluvia significativa (1 mm o más).")
    p.append("Método: SPI a 3, 6 y 12 meses sobre la precipitación oficial de AEMET en la capital (ERA5 donde no hay serie "
             "larga), gamma ajustada a 1991-2020. Los últimos días son provisionales hasta que AEMET los valida.")
    return " ".join(p)


def hallazgos(res: list[dict], prev_idx: dict | None) -> dict:
    previos = {x["slug"]: x for x in (prev_idx or {}).get("provincias", [])}
    out = []

    def base(r, tipo, indicador, titular, dato, contexto, prov_flag):
        return {"serie": "sequia", "fuente": FUENTE, "serie_desde": r["inicio_serie"], "territorio": r["provincia"],
                "provincia": r["provincia"], "ambito": "provincial", "pagina": r["urls"]["pagina"], "provisional": prov_flag,
                "tipo": tipo, "fecha_dato": r["ultimo_dia_dato"], "indicador": indicador, "titular": titular, "dato": dato,
                "contexto": contexto,
                "metodo": "SPI a 3, 6 y 12 meses (gamma 1991-2020, McKee) sobre la precipitación de la capital; regla del "
                          "semáforo publicada en /metodologia/. Los últimos días son provisionales hasta la validación de AEMET.",
                "limites": ["Sequía meteorológica medida en la capital: no equivale a la situación hidrológica de la cuenca.",
                            "La estación mide un punto; la provincia puede tener otra lluvia."],
                "citabilidad": "media" if prov_flag else "alta"}
    for r in res:
        pv = previos.get(r["slug"])
        h, d = r["hidro"] or {}, r["dias"] or {}
        prov = bool(r["provisional_desde"])
        if pv and r["nivel"] != 5 and pv.get("nivel") is not None and r["nivel"] > pv["nivel"] and pv["nivel"] != 5:
            pct = f"; la lluvia del año hidrológico es el {h['pct']} % de lo normal" if h.get("pct") is not None else ""
            out.append(base(r, "sequia_nivel_peor", "semaforo_sequia",
                            f"{r['provincia']} pasa a «{r['nivel_texto'].lower()}» en el Monitor de sequía",
                            f"SPI a {r['escala_clave']} meses de {f2(r['spi'][str(r['escala_clave'])]['valor'])} a cierre de "
                            f"{mes_txt(r['ultimo_mes_cerrado'])}; antes estaba en «{NIVELES[pv['nivel']][0].lower()}»{pct}.",
                            [f"SPI a 6 meses: {f2(r['spi']['6']['valor'])}.", f"Serie desde {r['inicio_serie']}."], prov))
        for umbral in (90, 60, 30):
            if d.get("sin_lluvia", 0) >= umbral and pv and (pv.get("dias_sin_lluvia") or 0) < umbral:
                out.append(base(r, "dias_sin_lluvia", f"dias_sin_lluvia_{umbral}",
                                f"{r['capital']} supera los {umbral} días sin lluvia significativa",
                                f"{d['sin_lluvia']} días seguidos con menos de 1 mm hasta el {fecha_txt(date.fromisoformat(d['hasta']))}"
                                + (f"; el último día con lluvia fue el {fecha_txt(date.fromisoformat(d['ultimo_dia_lluvia']))} "
                                   f"({f1(d['mm_ultimo'])} mm)" if d.get("ultimo_dia_lluvia") else ""),
                                [f"Días con 1 mm o más en los últimos 30: {d.get('dias_lluvia_30')} (normal {d.get('normal_30')})."],
                                bool(d.get("ultimo_dia_es_provisional"))))
                break
        pu = r["puesto_actual"]
        if pu and pu["puesto"] <= 5 and (not pv or (pv.get("puesto_spi12") or 99) > 5 or pv.get("ultimo_mes_cerrado") != r["ultimo_mes_cerrado"]):
            out.append(base(r, "spi12_historico", "spi12_top5",
                            f"El SPI a 12 meses de {r['provincia']} es el {pu['puesto']}.º más bajo de su serie",
                            f"SPI a 12 meses de {f2(r['spi']['12']['valor'])} a cierre de {mes_txt(r['ultimo_mes_cerrado'])}: "
                            f"puesto {pu['puesto']} de {pu['de']} meses desde {r['inicio_serie']}.",
                            [f"Nivel actual: {r['nivel_texto'].lower()}."], prov))
    return {"generado": HOY.isoformat(), "total": len(out), "hay_comparacion_con_ayer": bool(prev_idx),
            "enviables": out, "licencia": "Cálculo propio de CalentamientoGlobal.es · CC BY 4.0 · los datos de origen "
                                          "conservan la licencia de su organismo"}


# --------------------------------------------------------------------------------------------------- tabla y comprobaciones
def tabla(res: list[dict]):
    cab = ["prov", "fuente", "inicio", "cierre", "spi3", "spi6", "spi12", "niv", "mm", "%", "normal", "sinLl", "emb%", "med15"]
    print(" ".join(f"{c:>9}" for c in cab))
    for r in res:
        h, d, e, p = r["hidro"] or {}, r["dias"] or {}, r["embalses"] or {}, r["prevision"] or {}
        fila = [r["slug"][:9], "ERA5" if r["tipo"] == "reanalisis" else "AEMET", r["inicio_serie"] or "-",
                r["ultimo_mes_cerrado"] or "-"]
        fila += [("-" if r["spi"][k]["valor"] is None else f"{r['spi'][k]['valor']:.2f}") for k in ("3", "6", "12")]
        fila += [str(r["nivel"]), str(h.get("mm", "-")), str(h.get("pct", "-")), str(h.get("normal_mm", "-")),
                 str(d.get("sin_lluvia", "-")), str(e.get("pct", "-")), str(p.get("mediana_15", "-"))]
        print(" ".join(f"{c:>9}" for c in fila))


def comprobaciones(res: list[dict]) -> list[str]:
    malos = []
    # 1) SPI estandarizado: media ≈ 0 y desviación ≈ 1 en 1991-2020
    for r in res:
        for k in (3, 6, 12):
            if str(k) in r["referencia"]["meses_con_serie_completa"]:
                continue   # con toda la serie como referencia el tramo 1991-2020 no tiene por qué salir en 0 y 1
            v = [x for c, x in r["_interno"]["spi_all"][k].items() if REF0 <= int(c[:4]) <= REF1]
            if len(v) >= 120:
                m, sd = statistics.mean(v), statistics.pstdev(v)
                if abs(m) > 0.12 or abs(sd - 1) > 0.15:
                    malos.append(f"SPI-{k} {r['slug']}: media {m:.2f}, sd {sd:.2f}")
    # 2) año hidrológico > 130 % no puede estar en sequía severa o extrema
    for r in res:
        pct = (r["hidro"] or {}).get("pct")
        if pct is not None and pct > 130 and r["nivel"] in (3, 4):
            malos.append(f"{r['slug']}: {pct} % de lo normal y nivel {r['nivel']}")
    # 3) las secas frente a las húmedas
    na = {r["slug"]: r["normal_anual_mm"] for r in res}
    for seco in ("murcia", "sevilla", "zaragoza"):
        for hum in ("bizkaia", "a-coruna", "gipuzkoa"):
            if na.get(seco) and na.get(hum) and na[seco] >= na[hum]:
                malos.append(f"normal anual {seco} {na[seco]} ≥ {hum} {na[hum]}")
    return malos


# --------------------------------------------------------------------------------------------------- principal
def main():
    args = sys.argv[1:]
    sin_red = "--sin-red" in args or bool(os.environ.get("SEQUIA_SIN_RED"))
    solo = None
    if "--solo" in args:
        solo = set(args[args.index("--solo") + 1].split(","))
    log(f"Monitor de sequía {VERSION} · hoy {HOY} · {'sin red' if sin_red else 'con Open-Meteo'}")
    hist = Historia()
    prev_idx = leer_json(SALIDA / "index.json")
    emb_all = leer_json(DOCS / "embalses.json", {}) or {}
    url_web = {x.get("slug"): x.get("url_web") for x in emb_all.get("provincias", []) if isinstance(x, dict)}
    emb_nac = dict(emb_all.get("nacional") or {}) or None
    if emb_nac:
        emb_nac["boletin"] = emb_all.get("boletin_fecha")
    nieve_idx = {p["slug"]: p for p in (leer_json(NIEVE_IDX, {}) or {}).get("provincias", [])}
    res = []
    for slug in ORDEN:
        if solo and slug not in solo:
            continue
        t0 = time.time()
        r = calcular(hist, COD[slug], slug, url_web, nieve_idx, sin_red)
        res.append(r)
        log(f"  {slug:<24} nivel {r['nivel']} · SPI12 {r['spi']['12']['valor']} · {time.time() - t0:.1f} s")
    if not res:
        log("Nada que calcular")
        return 1
    # salidas
    cambios = 0
    niveles = {r["slug"]: r["nivel"] for r in res}
    nombres = {r["slug"]: r["provincia"] for r in res}
    for r in res:
        slug = r["slug"]
        pub = {k: v for k, v in r.items() if k != "_interno"}
        cambios += escribir_json(SALIDA / f"{slug}.json", pub, compacto=True)
        cambios += escribir(SALIDA / f"{slug}.csv", csv_provincia(r))
        cambios += escribir(GRAF / f"{slug}-spi.svg", svg_spi(r))
        s = svg_hidro(r)
        if s:
            cambios += escribir(GRAF / f"{slug}-hidro.svg", s)
    if len(res) == len(ORDEN):
        cambios += escribir(GRAF / "mapa.svg", svg_mapa(niveles, nombres))
        idx = {"generado": HOY.isoformat(), "version": VERSION, "fuente": FUENTE, "licencia": LICENCIA,
               "periodo_referencia": f"{REF0}-{REF1}", "regla_semaforo": REGLA_SEMAFORO,
               "niveles": {str(n): {"texto": NIVELES[n][0], "color": NIVELES[n][1]} for n in NIVELES},
               "provincias": [fila_index(r) for r in res],
               "sin_dato": [sin_dato_item(r) for r in res if r["nivel"] == 5]}
        nac = nacional(res, emb_nac)
        prensa = hallazgos(res, prev_idx)
        cambios += escribir_json(SALIDA / "nacional.json", nac)
        cambios += escribir_json(SALIDA / "prensa.json", prensa)
        cambios += escribir_json(SALIDA / "index.json", idx)   # el último: compara antes con el anterior
    log(f"Ficheros escritos o cambiados: {cambios}")
    if "--tabla" in args or solo or sin_red:
        tabla(res)
    malos = comprobaciones(res) if len(res) == len(ORDEN) else []
    for m in malos:
        log("  COMPROBACIÓN FALLIDA: " + m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
