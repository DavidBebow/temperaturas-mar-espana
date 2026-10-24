#!/usr/bin/env python3
"""
Balance del mes, capital a capital · Observatorio climático (calentamientoglobal.es).

El «balance mensual» de Climate Central (EEUU, el día 2 de cada mes) hecho con estaciones de AEMET:
para cada capital, la temperatura media del mes frente a su normal 1991-2020, el puesto del mes en
toda la serie de la estación y cuánto se ha calentado ese mes desde 1970. Y el resumen nacional:
en cuántas capitales fue más cálido de lo normal, en cuántas fue de los cinco más cálidos de su serie.
Solo datos medidos: nada de atribución con modelos ni proyecciones.

Una estación por provincia (ESTACIONES): la de la capital cuando tiene al menos 24 de los 30 octubres
(o el mes que toque) de 1991-2020; si la capital no tiene serie, la estación de referencia de la
provincia, dicho en el texto; si ninguna tiene serie, la provincia queda fuera (SIN_SERIE).

De dónde sale cada dato
  historia (hasta el año pasado)  manda el valor mensual oficial de AEMET (archivo/aemet_mensual, hasta
                                  agosto de 2026); si falta, la media de los diarios validados
                                  (archivo/aemet_diario). Comprobado el 24-10-2026 en 26.607 meses
                                  completos: antes de redondear no se separan nunca 0,1 °C (media 0,03),
                                  pero redondeados a una décima difieren en el 11 % de los meses; por eso
                                  manda el oficial y un margen de una décima se trata como empate.
  meses ya cerrados por nosotros  archivo/balance/propios.json (los meses verificados se guardan para
                                  la historia de los años siguientes, porque el mensual oficial va con
                                  meses de retraso).
  el mes del balance              1) diarios validados de AEMET (los pide este script a la API para las
                                     estaciones elegidas; AEMET los publica con unos 4-6 días de
                                     retraso) y los del archivo diario;
                                  2) para los días que AEMET aún no ha validado, la máxima y la mínima
                                     de la observación horaria de la propia estación (docs/records/
                                     obs_dias.json, que mantiene el detector de récords). Ese archivo
                                     solo guarda seis días: cada pasada copia aquí los días completos
                                     (archivo/balance/obs/AAAA-MM.json) para no perderlos.

Estados del balance de un mes
  provisional   algún día sale de la observación horaria (no validada). Se publica el día 1. Los récords y
                los top-5 solo se cuentan si su margen cubre lo que pueden mover los días sin validar.
                El primer provisional se congela en AAAA-MM_provisional.json (es el que se envía).
  verificado    ya no queda ningún día de observación (hacia el día 6); los huecos de AEMET se dicen
                estación a estación. Se comparan las cifras con el provisional y se congela.
  cerrado       el día 12 del mes siguiente se cierra con lo que haya, con las mismas cautelas.
Récords: superar al mejor año anterior en 0,2 °C o más; a una décima o menos es empate técnico.
La lluvia del mes solo se da cuando todos los días están validados: la observación horaria no la trae.

Escribe (docs/prensa/balance/):
  AAAA-MM.json           el balance: resumen nacional, capitales, textos listos para enviar, método
  AAAA-MM.csv            una fila por capital
  AAAA-MM/nacional.png   anomalía de cada capital, ordenada
  AAAA-MM/NN.png         la serie del mes en la estación, con la normal y la tendencia
  AAAA-MM_provisional.json  copia congelada del provisional, para comparar al verificar
  en_curso.json          el mes en curso hasta el último día con dato, frente a los mismos días de
                         otros años (solo estaciones con serie diaria): «¿va camino de…?»
  index.json             meses disponibles y su estado

Nada se envía solo: el balance propone, David decide.

Uso: python scripts/balance_mensual.py [--auto] [--mes AAAA-MM] [--forzar] [--sin-api]
  --auto: lo que hace el workflow cada media hora (guarda la observación; la pasada completa, cuando toca).
Variables: AEMET_API_KEY (para pedir los diarios validados), BALANCE_HOY=AAAA-MM-DD (ensayos).
"""
from __future__ import annotations

import argparse
import calendar
import csv
import gzip
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DOCS = RAIZ / "docs"
SALIDA = DOCS / "prensa" / "balance"
ARCH = RAIZ / "archivo"
STORE = ARCH / "balance"
OBS_DIAS = DOCS / "records" / "obs_dias.json"
MENSUALES = ARCH / "aemet_mensual" / "mensuales.json.gz"
DIARIO = ARCH / "aemet_diario"
PROPIOS = STORE / "propios.json"

URL_BASE = "https://davidbebow.github.io/temperaturas-mar-espana/prensa/balance/"
API = "https://opendata.aemet.es/opendata/api"
KEY = os.environ.get("AEMET_API_KEY", "")
PAUSA = float(os.environ.get("BALANCE_PAUSA", "1.6"))
AHORA = datetime.now(timezone.utc).replace(microsecond=0)
HOY = date.fromisoformat(os.environ["BALANCE_HOY"]) if os.environ.get("BALANCE_HOY") else AHORA.date()

NORMAL = (1991, 2020)
MIN_NORMAL = 24            # años válidos exigidos dentro de 1991-2020
INICIO_TENDENCIA = 1970
MIN_TENDENCIA = 40         # años válidos exigidos dentro de 1970-año anterior
MIN_DIAS_HIST = 27         # días con máxima y mínima para dar por bueno un mes de la serie diaria
MIN_DIAS_MES = 28          # días exigidos en el mes del balance para que la capital entre
HORAS_DIA_OBS = 22         # horas de observación exigidas para usar la máxima/mínima horaria del día
DIA_CIERRE = 12            # el día 12 del mes siguiente se cierra el balance con lo que haya
MARGEN_PROV = 0.15         # con días sin validar, un puesto es firme si su margen cubre esto (o 0,03 °C por día sin validar)

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]

# Código INE → (indicativo AEMET, ciudad, estación tal como se cita, tipo)
# tipo «capital»: estación de la capital o de su aeropuerto · «referencia»: la capital no tiene serie
# larga y se usa la estación de referencia de la provincia (se dice en el texto).
ESTACIONES = {
    "01": ("9091O", "Vitoria", "Vitoria, Foronda", "capital"),
    "02": ("8175", "Albacete", "Albacete, Base Aérea", "capital"),
    "03": ("8025", "Alicante", "Alicante", "capital"),
    "04": ("6325O", "Almería", "Almería Aeropuerto", "capital"),
    "05": ("2444", "Ávila", "Ávila", "capital"),
    "06": ("4452", "Badajoz", "Badajoz Aeropuerto", "capital"),
    "07": ("B228", "Palma", "Palma, Puerto", "capital"),
    "08": ("0076", "Barcelona", "Barcelona Aeropuerto", "capital"),
    "09": ("2331", "Burgos", "Burgos Aeropuerto", "capital"),
    "10": ("3469A", "Cáceres", "Cáceres", "capital"),
    "11": ("5973", "Cádiz", "Cádiz", "capital"),
    "12": ("8500A", "Castellón", "Castelló-Almassora", "capital"),
    "13": ("4121", "Ciudad Real", "Ciudad Real", "capital"),
    "14": ("5402", "Córdoba", "Córdoba Aeropuerto", "capital"),
    "15": ("1387", "A Coruña", "A Coruña", "capital"),
    "16": ("8096", "Cuenca", "Cuenca", "capital"),
    "17": ("0367", "Girona", "Girona Aeropuerto", "capital"),
    "18": ("5514", "Granada", "Granada, Base Aérea", "capital"),
    "20": ("1024E", "San Sebastián", "Donostia, Igeldo", "capital"),
    "21": ("4642E", "Huelva", "Huelva, Ronda Este", "capital"),
    "22": ("9898", "Huesca", "Huesca Aeropuerto", "capital"),
    "23": ("5270B", "Jaén", "Jaén", "capital"),
    "24": ("2661", "León", "León, Virgen del Camino", "capital"),
    "25": ("9771C", "Lleida", "Lleida", "capital"),
    "26": ("9170", "Logroño", "Logroño Aeropuerto", "capital"),
    "27": ("1518A", "Lugo", "Lugo", "capital"),
    "28": ("3195", "Madrid", "Madrid, Retiro", "capital"),
    "29": ("6155A", "Málaga", "Málaga Aeropuerto", "capital"),
    "30": ("7178I", "Murcia", "Murcia", "capital"),
    "31": ("9263D", "Pamplona", "Pamplona Aeropuerto", "capital"),
    "32": ("1690A", "Ourense", "Ourense", "capital"),
    "35": ("C649I", "Las Palmas", "aeropuerto de Gran Canaria", "referencia"),
    "36": ("1495", "Pontevedra", "aeropuerto de Vigo", "referencia"),
    "37": ("2867", "Salamanca", "Salamanca Aeropuerto", "capital"),
    "38": ("C449C", "Santa Cruz de Tenerife", "Santa Cruz de Tenerife", "capital"),
    "40": ("2465", "Segovia", "Segovia", "capital"),
    "41": ("5783", "Sevilla", "Sevilla Aeropuerto", "capital"),
    "42": ("2030", "Soria", "Soria", "capital"),
    "43": ("9981A", "Tarragona", "Observatorio del Ebro (Tortosa)", "referencia"),
    "44": ("8368U", "Teruel", "Teruel", "capital"),
    "45": ("3260B", "Toledo", "Toledo", "capital"),
    "46": ("8416", "Valencia", "València", "capital"),
    "47": ("2422", "Valladolid", "Valladolid", "capital"),
    "48": ("1082", "Bilbao", "Bilbao Aeropuerto", "capital"),
    "49": ("2614", "Zamora", "Zamora", "capital"),
    "50": ("9434", "Zaragoza", "Zaragoza Aeropuerto", "capital"),
    "52": ("6000A", "Melilla", "Melilla", "capital"),
}
# La observación horaria de algunas estaciones sale con otro indicativo (mismo sitio o al lado): para los días
# sin validar del provisional se usa ese, y el texto lo dice.
OBS_ALIAS = {"9091O": "9091R", "5514": "5514Z"}
SIN_SERIE = {
    "19": "Guadalajara: la estación de la ciudad (3168D) empieza en 2011.",
    "33": "Asturias: la estación de Oviedo (1249X) empieza en 2013 y la del aeropuerto no está en el archivo del observatorio.",
    "34": "Palencia: la estación actual (2401X) empieza en 2009.",
    "39": "Cantabria: la serie larga del aeropuerto de Santander (1109) se interrumpe; la actual (1109X) empieza en 2006.",
    "51": "Ceuta: la estación actual (5000C) empieza en 2004.",
}
PROVINCIA = {
    "01": "Álava", "02": "Albacete", "03": "Alicante", "04": "Almería", "05": "Ávila", "06": "Badajoz",
    "07": "Illes Balears", "08": "Barcelona", "09": "Burgos", "10": "Cáceres", "11": "Cádiz", "12": "Castellón",
    "13": "Ciudad Real", "14": "Córdoba", "15": "A Coruña", "16": "Cuenca", "17": "Girona", "18": "Granada",
    "19": "Guadalajara", "20": "Gipuzkoa", "21": "Huelva", "22": "Huesca", "23": "Jaén", "24": "León",
    "25": "Lleida", "26": "La Rioja", "27": "Lugo", "28": "Madrid", "29": "Málaga", "30": "Murcia",
    "31": "Navarra", "32": "Ourense", "33": "Asturias", "34": "Palencia", "35": "Las Palmas", "36": "Pontevedra",
    "37": "Salamanca", "38": "Santa Cruz de Tenerife", "39": "Cantabria", "40": "Segovia", "41": "Sevilla",
    "42": "Soria", "43": "Tarragona", "44": "Teruel", "45": "Toledo", "46": "Valencia", "47": "Valladolid",
    "48": "Bizkaia", "49": "Zamora", "50": "Zaragoza", "51": "Ceuta", "52": "Melilla",
}
FUENTE = "AEMET (valores climatológicos diarios y mensuales de cada estación) · cálculo propio de calentamientoglobal.es"
LICENCIA = "Información elaborada por la Agencia Estatal de Meteorología (AEMET)"


def log(m: str):
    print(time.strftime("%H:%M:%S ") + m, flush=True)


# ----------------------------------------------------------------------------
# formato
# ----------------------------------------------------------------------------
def r1(v) -> float:
    """Redondeo a una décima «de toda la vida» (la mitad hacia arriba), igual en el texto, la tabla y el gráfico."""
    return float(Decimal(repr(round(float(v), 6))).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def f1(v) -> str:
    """Un decimal con coma: 1,2 · 0,0 · 15,0 (en temperaturas el cero decimal se escribe)."""
    return f"{r1(v):.1f}".replace(".", ",")


def signo(v) -> str:
    r = r1(v)
    if r == 0:
        return "0,0"
    return ("+" if r > 0 else "−") + f1(abs(r))


def ord_m(n: int) -> str:
    """Ordinal ante un nombre masculino: el 1.er octubre, el 3.er octubre, el 2.º octubre."""
    return f"{n}.er" if n % 10 in (1, 3) and n % 100 not in (11, 13) else f"{n}.º"


def ord_s(n: int) -> str:
    """Ordinal sin nombre detrás: el 3.º más cálido."""
    return f"{n}.º"


def plural_mes(mes: str) -> str:
    return mes + ("es" if mes.endswith(("r", "l")) else "s")


def mes_nombre(clave: str) -> str:
    a, m = clave.split("-")
    return f"{MESES[int(m) - 1]} de {a}"


def lista_y(xs: list[str]) -> str:
    xs = [x for x in xs if x]
    if not xs:
        return ""
    if len(xs) == 1:
        return xs[0]
    return ", ".join(xs[:-1]) + " y " + xs[-1]


def nombres(xs: list[str], tope: int = 8) -> str:
    if len(xs) <= tope:
        return lista_y(xs)
    return "entre ellas " + lista_y(xs[:tope])


def leer_json(p: Path, defecto):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return defecto


def escribir_json(p: Path, obj, indent=1):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)
    tmp.replace(p)


def num(v):
    if v is None:
        return None
    s = str(v).strip().replace(",", ".")
    if s == "Ip":
        return 0.0
    if s in ("", "Acum", "Varias", "None"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ----------------------------------------------------------------------------
# historia de cada estación
# ----------------------------------------------------------------------------
class Historia:
    """Valores mensuales por estación. Para la historia manda el mensual oficial de AEMET; si falta, la media
    de los diarios validados; si tampoco, los meses que verificamos nosotros. Guarda también los diarios para
    el mes en curso frente a los mismos días de otros años."""

    def __init__(self):
        m = json.load(gzip.open(MENSUALES, "rt", encoding="utf-8")) if MENSUALES.exists() else {}
        self.oficial = {k: v.get("meses", {}) for k, v in ((m or {}).get("estaciones") or {}).items()}
        self.propios = leer_json(PROPIOS, {})
        self.diarios: dict[str, dict[str, tuple]] = {}
        for ide, *_ in ESTACIONES.values():
            self.diarios[ide] = self._leer_diario(ide)

    @staticmethod
    def _leer_diario(ide: str) -> dict:
        p = DIARIO / f"{ide}.csv.gz"
        out = {}
        if not p.exists():
            return out
        for r in csv.DictReader(io.TextIOWrapper(gzip.open(p), encoding="utf-8")):
            # lluvia vacía = «Acum» o falta: no se distingue, así que no cuenta como cero
            out[r["fecha"]] = (num(r.get("tmax")), num(r.get("tmin")), num(r.get("prec")))
        return out

    def mensual(self, ide: str, anio: int, mes: int) -> dict | None:
        """{'tm','tx','tn','p','fuente'} del mes completo, o None si no hay dato fiable."""
        clave = f"{anio}-{mes:02d}"
        o = (self.oficial.get(ide) or {}).get(clave)
        d = self.de_diarios(ide, anio, mes, calendar.monthrange(anio, mes)[1])
        p_diarios = d["p"] if d and d["p_completa"] else None
        if o and o[0] is not None and o[1] is not None and o[2] is not None:
            return {"tm": o[0], "tx": o[1], "tn": o[2], "p": o[5] if o[5] is not None else p_diarios, "fuente": "mensual oficial"}
        if d and d["n"] >= MIN_DIAS_HIST:
            return {"tm": d["tm"], "tx": d["tx"], "tn": d["tn"], "p": (o[5] if o and o[5] is not None else p_diarios),
                    "fuente": "diarios"}
        pr = (self.propios.get(ide) or {}).get(clave)
        if pr and pr.get("tm") is not None:
            return {"tm": pr["tm"], "tx": pr["tx"], "tn": pr["tn"], "p": pr.get("p"), "fuente": "balance verificado"}
        return None

    def de_diarios(self, ide: str, anio: int, mes: int, hasta_dia: int) -> dict | None:
        serie = self.diarios.get(ide) or {}
        xs, ns, ps, filas = [], [], [], 0
        for dia in range(1, hasta_dia + 1):
            r = serie.get(f"{anio}-{mes:02d}-{dia:02d}")
            if not r:
                continue
            filas += 1
            if r[0] is not None and r[1] is not None:
                xs.append(r[0])
                ns.append(r[1])
            if r[2] is not None:
                ps.append(r[2])
        if not xs:
            return None
        tx = sum(xs) / len(xs)
        tn = sum(ns) / len(ns)
        # la lluvia solo vale si todos los días tienen cifra (un «Acum» deja el día vacío en el archivo)
        return {"tm": (tx + tn) / 2, "tx": tx, "tn": tn, "n": len(xs), "p": sum(ps),
                "p_completa": filas == hasta_dia and len(ps) == hasta_dia}


# ----------------------------------------------------------------------------
# el mes del balance: diarios validados + observación horaria
# ----------------------------------------------------------------------------
def guardar_obs() -> int:
    """Copia los días completos de la observación horaria (6 días que rotan) al almacén del mes.
    Solo escribe si hay algo nuevo, para no hacer un commit en cada pasada."""
    o = leer_json(OBS_DIAS, {})
    dias = o.get("dias") or {}
    buscar = {}
    for ide, *_ in ESTACIONES.values():
        buscar[OBS_ALIAS.get(ide, ide)] = ide
    por_mes: dict[str, dict] = {}
    for fecha, est in dias.items():
        for ide_obs, v in est.items():
            ide = buscar.get(ide_obs)
            if not ide:
                continue
            horas = bin(int(v.get("m") or 0)).count("1")
            if horas < HORAS_DIA_OBS or v.get("tx") is None or v.get("tn") is None:
                continue
            por_mes.setdefault(fecha[:7], {}).setdefault(ide, {})[fecha] = {"tx": v["tx"], "tn": v["tn"], "h": horas,
                                                                          "id": ide_obs}
    nuevos = 0
    for mes, est in por_mes.items():
        p = STORE / "obs" / f"{mes}.json"
        actual = leer_json(p, {"estaciones": {}})
        cambia = False
        for ide, fechas in est.items():
            dst = actual["estaciones"].setdefault(ide, {})
            for f, v in fechas.items():
                if f not in dst or (v["h"] > dst[f].get("h", 0)) or (v["h"] == dst[f].get("h") and v != dst[f]):
                    nuevos += f not in dst
                    dst[f] = v
                    cambia = True
        if cambia:
            actual["actualizado"] = AHORA.isoformat().replace("+00:00", "Z")
            escribir_json(p, actual, indent=0)
    log(f"Observación horaria: {nuevos} días nuevos guardados")
    return nuevos


def peticion(url: str, intentos: int = 4):
    msg = "sin respuesta"
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "calentamientoglobal.es/balance"})
            with urllib.request.urlopen(req, timeout=90) as r:
                cuerpo = r.read()
            try:
                return json.loads(cuerpo.decode("utf-8")), "ok"
            except UnicodeDecodeError:
                return json.loads(cuerpo.decode("latin-1")), "ok"
        except urllib.error.HTTPError as e:
            if e.code == 429:
                log(f"  429: espero {60 * (i + 1)} s")
                time.sleep(60 * (i + 1))
                continue
            if e.code == 404:
                return {"estado": 404}, "404"
            msg = f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {e}"
        time.sleep(5 * (i + 1))
    return None, msg


def pedir_diarios(ides: list[str], ini: date, fin: date):
    """Diarios validados de AEMET para varias estaciones a la vez (AEMET admite indicativos separados por comas).
    Devuelve (lista o None, mensaje)."""
    url = (f"{API}/valores/climatologicos/diarios/datos/fechaini/{ini.isoformat()}T00:00:00UTC/"
           f"fechafin/{fin.isoformat()}T23:59:59UTC/estacion/{urllib.parse.quote(','.join(ides), safe=',')}?api_key={KEY}")
    for intento in range(3):
        meta, msg = peticion(url)
        time.sleep(PAUSA)
        if meta is None:
            return None, msg
        est = meta.get("estado")
        if est == 429:                      # límite por minuto dicho en el cuerpo de la respuesta
            log("  AEMET pide esperar (429): 60 s")
            time.sleep(60)
            continue
        if est == 404:
            return [], "sin datos"
        if est != 200 or not meta.get("datos"):
            return None, f"estado {est}: {str(meta.get('descripcion'))[:80]}"
        datos, msg = peticion(meta["datos"])
        time.sleep(PAUSA)
        if datos is None:
            return None, msg
        return (datos if isinstance(datos, list) else []), "ok"
    return None, "429 repetido"


def actualizar_validados(clave: str):
    """Pide a AEMET los diarios validados del mes para todas las estaciones del balance."""
    if not KEY:
        log("Sin AEMET_API_KEY: uso solo el archivo diario y la observación horaria")
        return
    a, m = map(int, clave.split("-"))
    ini = date(a, m, 1)
    fin = min(date(a, m, calendar.monthrange(a, m)[1]), HOY - timedelta(days=1))
    if fin < ini:
        return
    p = STORE / "diarios" / f"{clave}.json"
    actual = leer_json(p, {"estaciones": {}})
    ides = [v[0] for v in ESTACIONES.values()]
    recibidos = 0
    for i in range(0, len(ides), 10):
        lote = ides[i:i + 10]
        datos, msg = pedir_diarios(lote, ini, fin)
        if datos is None:
            log(f"  lote {lote[0]}…: fallo ({msg}); pido una a una")
            datos = []
            for ide in lote:
                d1, m1 = pedir_diarios([ide], ini, fin)
                if d1 is None:
                    log(f"    {ide}: fallo ({m1})")
                    continue
                datos.extend(d1)
        for d in datos:
            ide, fecha = d.get("indicativo"), d.get("fecha")
            if not ide or not fecha or ide not in ides:
                continue
            crudo = str(d.get("prec") or "").strip()
            # [máxima, mínima, lluvia, la lluvia es «Acum» (se suma en un día posterior)]
            actual["estaciones"].setdefault(ide, {})[fecha] = [num(d.get("tmax")), num(d.get("tmin")), num(d.get("prec")),
                                                               crudo == "Acum"]
            recibidos += 1
    actual["actualizado"] = AHORA.isoformat().replace("+00:00", "Z")
    escribir_json(p, actual, indent=0)
    log(f"AEMET: {recibidos} días validados recibidos para {clave}")


def dias_del_mes(hist: Historia, ide: str, clave: str, hasta_dia: int) -> dict:
    """Cada día del mes con su máxima, mínima, lluvia y de dónde sale (validado / observación)."""
    a, m = map(int, clave.split("-"))
    val = (leer_json(STORE / "diarios" / f"{clave}.json", {}).get("estaciones") or {}).get(ide) or {}
    obs = (leer_json(STORE / "obs" / f"{clave}.json", {}).get("estaciones") or {}).get(ide) or {}
    arch = hist.diarios.get(ide) or {}
    out = {}
    for dia in range(1, hasta_dia + 1):
        f = f"{a}-{m:02d}-{dia:02d}"
        v = val.get(f)
        if v and v[0] is not None and v[1] is not None:
            out[f] = {"tx": v[0], "tn": v[1], "p": v[2], "acum": bool(v[3]) if len(v) > 3 else False, "fuente": "validado"}
            continue
        r = arch.get(f)
        if r and r[0] is not None and r[1] is not None:
            out[f] = {"tx": r[0], "tn": r[1], "p": r[2], "acum": False, "fuente": "validado"}
            continue
        o = obs.get(f)
        if o:
            out[f] = {"tx": o["tx"], "tn": o["tn"], "p": None, "acum": False, "fuente": "observación",
                      "otra_estacion": o.get("id") not in (None, ide)}
    return out


def lluvia_del_mes(dias: dict, ndias: int) -> float | None:
    """Total del mes solo si todos los días están validados y la lluvia es completa: cada día con cifra, o
    «Acum» cerrado por un día posterior del mismo mes (que trae lo acumulado)."""
    if len(dias) != ndias or any(d["fuente"] != "validado" for d in dias.values()):
        return None
    pendiente = False
    total = 0.0
    for f in sorted(dias):
        d = dias[f]
        if d["p"] is not None:
            total += d["p"]
            pendiente = False
        elif d.get("acum"):
            pendiente = True
        else:
            return None                      # día sin lluvia y sin «Acum»: no se sabe
    return None if pendiente else total


def calibracion(hist: Historia) -> dict | None:
    """Cuánto se parece la máxima/mínima de la observación horaria al dato que AEMET valida después:
    se mide en todos los días guardados que ya tienen las dos cosas."""
    dx, dn = [], []
    for p in sorted((STORE / "obs").glob("*.json")):
        clave = p.stem
        obs = leer_json(p, {}).get("estaciones") or {}
        val = leer_json(STORE / "diarios" / f"{clave}.json", {}).get("estaciones") or {}
        for ide, dias in obs.items():
            for f, o in dias.items():
                v = (val.get(ide) or {}).get(f)
                if not (v and v[0] is not None and v[1] is not None):
                    r = (hist.diarios.get(ide) or {}).get(f)
                    v = [r[0], r[1]] if r and r[0] is not None and r[1] is not None else None
                if v:
                    dx.append(o["tx"] - v[0])
                    dn.append(o["tn"] - v[1])
    if len(dx) < 20:
        return None
    dm = [(a + b) / 2 for a, b in zip(dx, dn)]
    return {"dias": len(dx), "sesgo_tx": round(sum(dx) / len(dx), 2), "sesgo_tn": round(sum(dn) / len(dn), 2),
            "sesgo_tm": round(sum(dm) / len(dm), 2), "dif_abs_media_tm": round(sum(abs(x) for x in dm) / len(dm), 2),
            "dias_mas_de_0_5": sum(1 for x in dm if abs(x) > 0.5)}


# ----------------------------------------------------------------------------
# cálculo
# ----------------------------------------------------------------------------
def tendencia(pares: list[tuple[int, float]]):
    """Recta de mínimos cuadrados con su error típico: pendiente/año y t de la pendiente."""
    n = len(pares)
    if n < 10:
        return None
    mx = sum(x for x, _ in pares) / n
    my = sum(y for _, y in pares) / n
    sxx = sum((x - mx) ** 2 for x, _ in pares)
    sxy = sum((x - mx) * (y - my) for x, y in pares)
    if sxx == 0:
        return None
    b = sxy / sxx
    a = my - b * mx
    sse = sum((y - (a + b * x)) ** 2 for x, y in pares)
    se = (sse / (n - 2) / sxx) ** 0.5 if n > 2 else None
    t = b / se if se else None
    return {"pendiente": b, "origen": a, "n": n, "t": t}


def posicion(valor1: float, pasado1: dict[int, float], calido: bool) -> dict:
    """Puesto del valor (ya redondeado a una décima) entre los de otros años (también redondeados).
    - puesto: 1 + años estrictamente por delante (más cálidos si calido, más fríos si no)
    - empatados: años con el mismo valor
    - margen_mejor: cuánto le saca al mejor de los demás años (negativo si queda por detrás)
    - margen_quinto: cuánto le saca al 5.º de los demás años (para saber si el top-5 aguanta)"""
    def delante(x):
        return x > valor1 if calido else x < valor1
    orden = sorted(pasado1.items(), key=lambda kv: -kv[1] if calido else kv[1])
    p = 1 + sum(1 for x in pasado1.values() if delante(x))
    emp = sorted(y for y, x in pasado1.items() if x == valor1)
    mejor = orden[0] if orden else None
    sgn = 1 if calido else -1
    m_mejor = r1(sgn * (valor1 - mejor[1])) if mejor else None
    m_quinto = r1(sgn * (valor1 - orden[4][1])) if len(orden) >= 5 else None
    return {"puesto": p, "empatados": emp, "mejor_anio": mejor[0] if mejor else None,
            "mejor_valor": mejor[1] if mejor else None, "margen_mejor": m_mejor, "margen_quinto": m_quinto,
            "por_delante": [{"anio": y, "valor": x} for y, x in orden if delante(x)][:4]}


def clasificar(pos: dict, sin_validar: int) -> dict:
    """Récord, empate técnico o puesto, y si aguanta aunque cambien los días sin validar.
    · récord: le saca al mejor año anterior al menos 0,2 °C (una décima puede ser redondeo o la fuente).
    · empate técnico con el récord: a ±0,1 °C del mejor año anterior.
    · firme: con días sin validar, el margen tiene que cubrir además lo que esos días pueden mover."""
    extra = 0.0 if sin_validar == 0 else max(MARGEN_PROV, 0.03 * sin_validar)
    mm = pos["margen_mejor"]
    if mm is None:
        return {"tipo": None, "firme": True, "top5": False, "top5_firme": True}
    if mm >= 0.2 - 1e-9:
        tipo = "record"
    elif mm >= -0.1 - 1e-9:
        tipo = "empate"
    else:
        tipo = None
    firme = sin_validar == 0 or (tipo == "record" and mm >= 0.2 + extra - 1e-9) or \
        (tipo is None and mm <= -0.1 - extra - 1e-9)
    top5 = pos["puesto"] <= 5
    mq = pos["margen_quinto"]
    top5_firme = sin_validar == 0 or mq is None or (top5 and mq >= extra) or (not top5 and mq <= -extra)
    return {"tipo": tipo, "firme": bool(firme), "top5": top5, "top5_firme": bool(top5_firme)}


def balance_capital(hist: Historia, cod: str, clave: str, hasta_dia: int, completo: bool) -> dict:
    ide, ciudad, estacion, tipo = ESTACIONES[cod]
    a, m = map(int, clave.split("-"))
    ndias = calendar.monthrange(a, m)[1]
    base = {"cod": cod, "provincia": PROVINCIA[cod], "ciudad": ciudad, "estacion": estacion, "indicativo": ide, "tipo": tipo}

    dias = dias_del_mes(hist, ide, clave, hasta_dia)
    n = len(dias)
    n_obs = sum(1 for d in dias.values() if d["fuente"] == "observación")
    faltan = [f for f in (f"{a}-{m:02d}-{d:02d}" for d in range(1, hasta_dia + 1)) if f not in dias]
    base.update(dias=n, dias_observacion=n_obs, dias_faltan=faltan,
                obs_otra_estacion=sorted({OBS_ALIAS[ide]} if any(d.get("otra_estacion") for d in dias.values()) else set()))
    exigidos = MIN_DIAS_MES if completo else max(1, hasta_dia - 2)
    if n < exigidos:
        return {**base, "valido": False, "motivo": f"solo {n} de {hasta_dia} días con dato"}
    tx = sum(d["tx"] for d in dias.values()) / n
    tn = sum(d["tn"] for d in dias.values()) / n
    tm = (tx + tn) / 2

    serie: dict[int, dict] = {}
    for y in range(1920, a):
        if completo:
            v = hist.mensual(ide, y, m)
        else:
            d = hist.de_diarios(ide, y, m, hasta_dia)
            v = d if d and d["n"] >= hasta_dia - 2 else None
        if v and v.get("tm") is not None and v.get("tx") is not None and v.get("tn") is not None:
            serie[y] = v
    norm = [serie[y] for y in range(NORMAL[0], NORMAL[1] + 1) if y in serie]
    if len(norm) < MIN_NORMAL:
        return {**base, "valido": False, "motivo": f"solo {len(norm)} años de 1991-2020 en la serie"}
    n_tm = sum(v["tm"] for v in norm) / len(norm)
    n_tx = sum(v["tx"] for v in norm) / len(norm)
    n_tn = sum(v["tn"] for v in norm) / len(norm)

    # lo publicado va a una décima y la anomalía es la resta de lo publicado: las cuentas cuadran a la vista
    tm1, ntm1 = r1(tm), r1(n_tm)
    anom = r1(tm1 - ntm1)
    calido = anom >= 0
    pasado1 = {y: r1(v["tm"]) for y, v in serie.items()}
    pos = posicion(tm1, pasado1, calido)
    sin_validar = n_obs + len(faltan)
    cl = clasificar(pos, sin_validar)

    tms = {y: v["tm"] for y, v in serie.items()}
    pares_t = [(y, tms[y]) for y in range(INICIO_TENDENCIA, a) if y in tms]
    tend = tendencia(pares_t)
    if tend and tend["n"] < MIN_TENDENCIA:
        tend = None
    tend_desde = pares_t[0][0] if pares_t else None
    out = {
        **base, "valido": True,
        "tm": tm1, "tx": r1(tx), "tn": r1(tn),
        "normal_tm": ntm1, "normal_tx": r1(n_tx), "normal_tn": r1(n_tn),
        "anomalia": anom, "anomalia_tx": r1(r1(tx) - r1(n_tx)), "anomalia_tn": r1(r1(tn) - r1(n_tn)),
        "anios_normal": len(norm), "serie_desde": min(serie), "anios_serie": len(serie) + 1,
        "sentido": "calido" if calido else "frio",
        "puesto": pos["puesto"], "empatado_con": pos["empatados"],
        "por_delante": pos["por_delante"], "mejor_anterior": {"anio": pos["mejor_anio"], "valor": pos["mejor_valor"]},
        "margen_mejor": pos["margen_mejor"],
        "record": cl["tipo"] == "record", "empate_record": cl["tipo"] == "empate",
        "puesto_firme": cl["firme"], "top5": cl["top5"], "top5_firme": cl["top5_firme"],
        "dias_sin_validar": sin_validar,
        "tendencia_desde": tend_desde if tend else None,
        "tendencia_decada": r1(tend["pendiente"] * 10) if tend else None,
        "calentamiento_tramo": r1(tend["pendiente"] * (a - 1 - tend_desde)) if tend else None,
        "tendencia_significativa": bool(tend and tend["t"] is not None and abs(tend["t"]) >= 2),
        "serie": {str(y): r1(v) for y, v in sorted(tms.items())},
    }
    if completo:
        p_mes = lluvia_del_mes(dias, ndias)
        p_hist = {y: v["p"] for y, v in serie.items() if v.get("p") is not None}
        p_norm = [p_hist[y] for y in range(NORMAL[0], NORMAL[1] + 1) if y in p_hist]
        if p_mes is not None and len(p_norm) >= MIN_NORMAL:
            pn = sum(p_norm) / len(p_norm)
            p1 = r1(p_mes)
            ph1 = {y: r1(v) for y, v in p_hist.items()}
            humedo = posicion(p1, ph1, True)
            seco = posicion(p1, ph1, False)
            out.update(lluvia=p1, lluvia_normal=r1(pn), lluvia_pct=round(100 * p_mes / pn) if pn > 0 else None,
                       lluvia_anios=len(ph1) + 1,
                       lluvia_puesto_humedo=humedo["puesto"], lluvia_empatado_humedo=humedo["empatados"],
                       lluvia_puesto_seco=seco["puesto"], lluvia_empatado_seco=seco["empatados"],
                       lluvia_anios_cero=sorted(y for y, v in ph1.items() if v == 0))
    return out


def resumen_nacional(caps: list[dict], provisional: bool) -> dict:
    v = [c for c in caps if c.get("valido")]
    if not v:
        return {"n": 0}
    an = [c["anomalia"] for c in v]
    calidos = [c for c in v if c["anomalia"] > 0]
    frios = [c for c in v if c["anomalia"] < 0]
    sentido = "calido" if r1(sum(an) / len(an)) >= 0 else "frio"
    mismo = [c for c in v if c["sentido"] == sentido and c["anomalia"] != 0]

    def orden(xs):
        return sorted(xs, key=lambda c: (c["puesto"], -abs(c["anomalia"])))
    record = orden([c for c in mismo if c["record"]])
    empate = orden([c for c in mismo if c["empate_record"]])
    top5 = orden([c for c in mismo if c["top5"]])
    # 1970: solo estaciones cuya serie arranca en 1972 o antes, para que el promedio sea del mismo tramo
    t70 = [c for c in v if c.get("tendencia_decada") is not None and c["tendencia_desde"] <= 1972]
    out = {
        "n": len(v), "sentido": sentido,
        "anomalia_media": r1(sum(an) / len(an)),
        "anomalia_tx_media": r1(sum(c["anomalia_tx"] for c in v) / len(v)),
        "anomalia_tn_media": r1(sum(c["anomalia_tn"] for c in v) / len(v)),
        "n_calidas": len(calidos), "n_frias": len(frios), "n_normales": len(v) - len(calidos) - len(frios),
        "n_record": len(record), "n_record_firme": sum(1 for c in record if c["puesto_firme"]),
        "record": [lugar(c) for c in record], "record_firme": [lugar(c) for c in record if c["puesto_firme"]],
        "n_empate_record": len(empate), "empate_record": [lugar(c) for c in empate],
        "empate_record_firme": [lugar(c) for c in empate if c["dias_sin_validar"] == 0],
        "n_top5": len(top5), "n_top5_firme": sum(1 for c in top5 if c["top5_firme"]),
        "top5": [lugar(c) for c in top5], "top5_firme": [lugar(c) for c in top5 if c["top5_firme"]],
        "n_tendencia_1970": len(t70),
        "n_calentado_1970": sum(1 for c in t70 if c["tendencia_decada"] > 0),
        "n_calentado_1970_signif": sum(1 for c in t70 if c["tendencia_decada"] > 0 and c["tendencia_significativa"]),
        "tendencia_decada_media_1970": r1(sum(c["tendencia_decada"] for c in t70) / len(t70)) if t70 else None,
        "mas_calida": lugar(max(v, key=lambda c: c["anomalia"])), "anomalia_max": max(an),
        "mas_fria": lugar(min(v, key=lambda c: c["anomalia"])), "anomalia_min": min(an),
        "dias_sin_validar": sum(c["dias_sin_validar"] for c in v),
        "dias_observacion": sum(c["dias_observacion"] for c in v),
        "dias_faltan": sum(len(c["dias_faltan"]) for c in v),
        "estaciones_con_huecos": [lugar(c) for c in v if c["dias_faltan"]],
        "provincias_fuera": len(SIN_SERIE) + sum(1 for c in caps if not c.get("valido")),
    }
    ll = [c for c in v if c.get("lluvia") is not None and c.get("lluvia_pct") is not None]
    if ll:
        out.update(n_lluvia=len(ll),
                   n_lluvia_por_encima=sum(1 for c in ll if c["lluvia_pct"] > 100),
                   n_lluvia_por_debajo=sum(1 for c in ll if c["lluvia_pct"] < 100),
                   record_humedo=[lugar(c) for c in ll if c["lluvia_puesto_humedo"] == 1 and not c["lluvia_empatado_humedo"]],
                   record_seco=[lugar(c) for c in ll if c["lluvia"] > 0 and c["lluvia_puesto_seco"] == 1 and not c["lluvia_empatado_seco"]],
                   sin_lluvia=[lugar(c) for c in ll if c["lluvia"] == 0])
    return out


# ----------------------------------------------------------------------------
# textos
# ----------------------------------------------------------------------------
def lugar(c: dict) -> str:
    return c["ciudad"] if c["tipo"] == "capital" else f"{c['ciudad']} ({c['estacion']})"


def frase_serie(c: dict) -> str:
    return f"en {c['anios_serie']} años de registros (desde {c['serie_desde']})"


def frase_posicion(c: dict, mes: str) -> str:
    """La frase del puesto, sin presumir: récord, empate técnico o puesto con los años que van por delante."""
    adj = "cálido" if c["sentido"] == "calido" else "frío"
    mej = c["mejor_anterior"]
    if c["record"]:
        return (f"Es el {mes} más {adj} {frase_serie(c)} en {estacion_txt(c)}: supera en {f1(c['margen_mejor'])} °C "
                f"al anterior récord, el de {mej['anio']} ({f1(mej['valor'])} °C).")
    if c["empate_record"]:
        rel = ("iguala al" if c["margen_mejor"] == 0 else ("supera por una décima al" if c["margen_mejor"] > 0 else "se queda a una décima del"))
        return (f"Empata con el {mes} más {adj} {frase_serie(c)} en {estacion_txt(c)}: {rel} de {mej['anio']} "
                f"({f1(mej['valor'])} °C), una diferencia que no va más allá del redondeo.")
    s = f"Es el {ord_m(c['puesto'])} {mes} más {adj} {frase_serie(c)} en {estacion_txt(c)}"
    if c["empatado_con"]:
        s += f", con la misma media que el de {lista_y([str(y) for y in c['empatado_con']])}"
    if c["puesto"] <= 5 and c["por_delante"]:
        pd = c["por_delante"]
        s += (f". Solo fue más {adj} el de {pd[0]['anio']}" if len(pd) == 1 else
              f". Solo fueron más {adj}s los de {lista_y([str(x['anio']) for x in pd])}")
    return s + "."


def estacion_txt(c: dict) -> str:
    if c["tipo"] == "referencia":
        return f"la estación de AEMET del {c['estacion']}, la de serie larga de la provincia de {c['provincia']}"
    return f"la estación de AEMET de {c['estacion']}"


def texto_capital(c: dict, clave: str, estado: str) -> dict:
    mes, anio = MESES[int(clave[5:]) - 1], clave[:4]
    mes_a = f"{mes} de {anio}"
    an = c["anomalia"]
    adj = "cálido" if c["sentido"] == "calido" else "frío"
    pendiente = c["dias_sin_validar"] > 0
    firme_puesto = c["puesto_firme"] and (c["top5_firme"] or not c["top5"])
    sujeto = c["ciudad"] if c["tipo"] == "capital" else f"La estación del {c['estacion']} ({c['provincia']})"
    # titular: el puesto solo si está firme
    if c["record"] and c["puesto_firme"]:
        tit = f"{mes_a.capitalize()}: en {lugar(c)}, el más {adj} {frase_serie(c)}"
    elif c["empate_record"] and c["puesto_firme"]:
        tit = f"{mes_a.capitalize()} empata en {lugar(c)} con el más {adj} {frase_serie(c)}"
    elif c["top5"] and an != 0 and c["top5_firme"] and c["puesto_firme"]:
        tit = f"{mes_a.capitalize()}: en {lugar(c)}, el {ord_s(c['puesto'])} más {adj} {frase_serie(c)}"
    elif an > 0:
        tit = f"{mes_a.capitalize()} fue {f1(an)} °C más cálido de lo normal en {lugar(c)}"
    elif an < 0:
        tit = f"{mes_a.capitalize()} fue {f1(abs(an))} °C más frío de lo normal en {lugar(c)}"
    else:
        tit = f"{mes_a.capitalize()} fue un mes normal de temperatura en {lugar(c)}"
    rel = (f"{f1(abs(an))} °C por encima de lo normal" if an > 0 else
           f"{f1(abs(an))} °C por debajo de lo normal" if an < 0 else "justo en lo normal")
    verbo = "cerró" if c["tipo"] == "capital" else "registró en"
    p1 = (f"{sujeto} {verbo} {mes_a} {'con ' if c['tipo'] == 'capital' else ''}una temperatura media de {f1(c['tm'])} °C, "
          f"{rel} para el mes (media de 1991-2020 en la misma estación: {f1(c['normal_tm'])} °C).")
    if an != 0:
        if firme_puesto:
            p1 += " " + frase_posicion(c, mes)
        else:
            p1 += (f" Su puesto en la serie de la estación ({c['anios_serie']} años desde {c['serie_desde']}) depende de "
                   f"unas décimas y se dará cuando AEMET valide los días que faltan.")
    ax, anx = c["anomalia_tx"], c["anomalia_tn"]
    p2 = (f"Las máximas quedaron de media en {f1(c['tx'])} °C ({signo(ax)} °C respecto a lo normal) y las mínimas, en "
          f"{f1(c['tn'])} °C ({signo(anx)} °C).")
    if an > 0 and anx - ax >= 0.5 and anx > 0:
        p2 += " El exceso estuvo sobre todo en las mínimas: las noches se enfriaron menos de lo habitual."
    elif an > 0 and ax - anx >= 0.5 and ax > 0:
        p2 += " El exceso estuvo sobre todo en las máximas, en las horas centrales del día."
    elif an < 0 and ax - anx <= -0.5 and ax < 0:
        p2 += " El frío estuvo sobre todo en las máximas: fueron días más frescos de lo normal" + (
            ", con noches que no se enfriaron más de lo habitual." if anx >= 0 else ".")
    elif an < 0 and anx - ax <= -0.5 and anx < 0:
        p2 += " El frío estuvo sobre todo en las mínimas: las noches fueron más frías de lo normal."
    p3 = ""
    if c.get("tendencia_decada") is not None:
        td, dec, tot = c["tendencia_desde"], c["tendencia_decada"], c["calentamiento_tramo"]
        if c["tendencia_significativa"] and dec > 0:
            p3 = (f"Desde {td}, el {mes} se ha calentado {f1(tot)} °C en esta estación según la tendencia lineal de la serie "
                  f"({signo(dec)} °C por década).")
        elif dec > 0:
            p3 = (f"Desde {td}, la tendencia del {mes} en esta estación es de {signo(dec)} °C por década, pero no es "
                  f"estadísticamente significativa: los años varían demasiado para afirmarla.")
        else:
            p3 = f"En esta estación, el {mes} no muestra calentamiento desde {td} (tendencia de {signo(dec)} °C por década)."
    p4 = ""
    if c.get("lluvia") is not None and c.get("lluvia_pct") is not None:
        if c["lluvia"] == 0:
            otros = c["lluvia_anios_cero"]
            p4 = ("En cuanto a la lluvia, no se recogió nada" +
                  (f", algo que en esta estación ya había pasado en {len(otros)} {mes}{'es' if mes.endswith('r') else 's'} "
                   f"(el último, {otros[-1]})." if otros else ": es el primer " + mes + " sin lluvia de la serie."))
        else:
            p4 = (f"En cuanto a la lluvia, se recogieron {f1(c['lluvia'])} l/m², el {c['lluvia_pct']} % de lo normal "
                  f"({f1(c['lluvia_normal'])} l/m²).")
            for k, adjl in (("humedo", "lluvioso"), ("seco", "seco")):
                p, emp = c[f"lluvia_puesto_{k}"], c[f"lluvia_empatado_{k}"]
                if p <= 5:
                    if p == 1 and not emp:
                        p4 += f" Es el {mes} más {adjl} de la serie."
                    elif p == 1:
                        p4 += f" Iguala el {mes} más {adjl} de la serie ({lista_y([str(y) for y in emp])})."
                    else:
                        p4 += f" Es el {ord_m(p)} {mes} más {adjl} de la serie."
                    break
    avisos = []
    if c.get("dias_observacion"):
        avisos.append(f"Dato provisional: {c['dias_observacion']} de los {c['dias']} días salen de la observación horaria"
                      + (f" (estación {', '.join(c['obs_otra_estacion'])}, junto a la de la serie)" if c.get("obs_otra_estacion") else " de la estación")
                      + "; AEMET aún no los ha validado.")
    if c.get("dias_faltan"):
        nf = len(c["dias_faltan"])
        avisos.append(f"{'Falta un día' if nf == 1 else f'Faltan {nf} días'} sin dato: la media es de {c['dias']} días.")
    if pendiente and not firme_puesto and an != 0:
        avisos.append("No dar el puesto en la serie hasta la verificación.")
    return {"titular": tit, "texto": " ".join(x for x in (p1, p2, p3, p4) if x), "aviso": " ".join(avisos),
            "fuente": f"Fuente: AEMET (estación {c['estacion']}, {c['indicativo']}). Análisis: observatorio climático de calentamientoglobal.es."}


def texto_nacional(r: dict, caps: list[dict], clave: str, estado: str) -> dict:
    mes, anio = MESES[int(clave[5:]) - 1], clave[:4]
    mes_a = f"{mes} de {anio}"
    meses_pl = plural_mes(mes)
    n = r["n"]
    am = r["anomalia_media"]
    calido = r["sentido"] == "calido"
    adj = "cálido" if calido else "frío"
    adjs = "cálidos" if calido else "fríos"
    nmismo = r["n_calidas"] if calido else r["n_frias"]
    pend = r["dias_sin_validar"] > 0
    rec = r["n_record_firme"] if pend else r["n_record"]
    rec_l = r["record_firme"] if pend else r["record"]
    t5 = r["n_top5_firme"] if pend else r["n_top5"]
    t5_l = r["top5_firme"] if pend else r["top5"]
    # «al menos» solo cuando de verdad hay puestos pendientes de confirmar
    al_r = "al menos " if pend and r["n_record_firme"] < r["n_record"] else ""
    al_t = "al menos " if pend and r["n_top5_firme"] < r["n_top5"] else ""
    cuantas = f"las {n}" if nmismo == n else f"{nmismo} de las {n}"
    tit = f"{mes_a.capitalize()} fue más {adj} de lo normal en {cuantas} provincias analizadas"
    if rec:
        tit += f" y el más {adj} jamás medido en {al_r}{rec}"
    elif t5 >= 3:
        tit += f"; en {al_t}{t5}, uno de los cinco más {adjs} de su historia"
    sentido = "por encima" if am >= 0 else "por debajo"
    p1 = (f"{mes_a.capitalize()} terminó {f1(abs(am))} °C {sentido} de lo normal (1991-2020) de media en {n} provincias, "
          f"con una estación de AEMET de serie larga en cada una (la de la capital salvo en Las Palmas, Pontevedra y "
          f"Tarragona), según el análisis del observatorio climático de calentamientoglobal.es.")
    partes = []
    if r["n_calidas"]:
        partes.append(f"más cálido de lo normal en {'todas' if r['n_calidas'] == n else r['n_calidas']}")
    if r["n_frias"]:
        partes.append(f"más frío en {'todas' if r['n_frias'] == n else r['n_frias']}")
    if r["n_normales"]:
        partes.append(f"normal en {r['n_normales']}")
    if len(partes) > 1:
        p1 += f" Fue {lista_y(partes)}."
    p2 = ""
    if t5:
        p2 = f"En {al_t}{t5} fue uno de los cinco {meses_pl} más {adjs} de toda su serie"
        if rec:
            p2 += f", y en {al_r}{rec}, el más {adj} desde que hay registros: {nombres(rec_l)}."
        else:
            p2 += f": {nombres(t5_l)}."
    e = r["empate_record_firme"]
    if e:
        p2 += f" En {nombres(e)} {'empata' if len(e) == 1 else 'empatan'} con su récord: la diferencia no pasa de una décima."
    if al_r or al_t:
        p2 += (" Otros puestos de la tabla dependen de unas décimas y se confirmarán cuando AEMET valide los últimos "
               "días del mes.")
    ext_l, ext_v = (r["mas_calida"], r["anomalia_max"]) if calido else (r["mas_fria"], r["anomalia_min"])
    p3 = (f"La mayor anomalía se dio en {ext_l} ({signo(ext_v)} °C). De media, las máximas quedaron "
          f"{signo(r['anomalia_tx_media'])} °C respecto a lo normal y las mínimas, {signo(r['anomalia_tn_media'])} °C.")
    p4 = ""
    if r.get("n_tendencia_1970"):
        p4 = (f"A más largo plazo, en las {r['n_tendencia_1970']} estaciones con serie desde 1970 el {mes} se ha calentado en "
              f"{r['n_calentado_1970']} (en {r['n_calentado_1970_signif']} de ellas la tendencia es estadísticamente "
              f"significativa), a un ritmo medio de {signo(r['tendencia_decada_media_1970'])} °C por década.")
    p5 = ""
    if r.get("n_lluvia"):
        p5 = (f"En lluvia, el mes quedó por encima de lo normal en {r['n_lluvia_por_encima']} de {r['n_lluvia']} provincias "
              f"con el dato completo y por debajo en {r['n_lluvia_por_debajo']}.")
        if r.get("record_humedo"):
            p5 += f" Fue el {mes} más lluvioso de la serie en {nombres(r['record_humedo'])}."
        if r.get("record_seco"):
            p5 += f" Fue el más seco de la serie en {nombres(r['record_seco'])}."
        if r.get("sin_lluvia"):
            p5 += f" En {nombres(r['sin_lluvia'])} no se recogió lluvia."
    claves = [
        (f"Las {n} provincias, más {'cálidas' if calido else 'frías'} de lo normal" if nmismo == n
         else f"{nmismo} de {n} provincias, más {'cálidas' if calido else 'frías'} de lo normal"),
        f"Anomalía media: {signo(am)} °C frente a 1991-2020",
        f"{(al_t + str(t5)).capitalize()} con uno de sus cinco {meses_pl} más {adjs}; {al_r}{rec} con récord",
    ]
    if r.get("n_tendencia_1970"):
        claves.append(f"{r['n_calentado_1970']} de {r['n_tendencia_1970']} estaciones: el {mes} se ha calentado desde 1970")
    avisos = []
    if r.get("dias_observacion"):
        avisos.append(f"Cifras provisionales: {r['dias_observacion']} días-estación, los últimos del mes, salen de la observación "
                      f"horaria de cada estación porque AEMET aún no los ha validado. Los récords y los top-5 se cuentan solo "
                      f"cuando su margen cubre lo que pueden mover esos días. El balance se recalcula solo y se marca como "
                      f"verificado cuando AEMET ha validado todos los días.")
    if r.get("dias_faltan"):
        h = r["estaciones_con_huecos"]
        avisos.append(f"AEMET no tiene dato de {r['dias_faltan']} días-estación ({nombres(h)}): en "
                      f"{'esa estación' if len(h) == 1 else 'esas estaciones'} la media es de los días disponibles y sus puestos "
                      f"en la serie solo se dan si el margen lo cubre.")
    aviso = " ".join(avisos)
    return {"titular": tit, "texto": " ".join(x for x in (p1, p2, p3, p4, p5) if x), "datos_clave": claves, "aviso": aviso,
            "cita": "Fuente: AEMET. Análisis: observatorio climático de calentamientoglobal.es."}


METODO = (
    "Una estación de AEMET por provincia: la de la capital (o su aeropuerto) cuando tiene al menos 24 de los 30 años de 1991-2020; "
    "si no, la estación de serie larga de la provincia, y se dice. La temperatura media del mes es la media de (máxima + mínima) / 2 "
    "de cada día, como la calcula AEMET. Para los años anteriores manda el valor mensual oficial de AEMET; si falta, la media de los "
    "diarios validados (antes de redondear, las dos no se separan nunca 0,1 °C). La normal es la media del mismo mes en 1991-2020 "
    "en la misma estación. Todas las cifras se redondean a una décima y el puesto se cuenta con ellas: un récord exige superar al "
    "mejor año anterior en 0,2 °C o más; a una décima o menos se da como empate técnico. La tendencia es la recta de mínimos "
    "cuadrados desde 1970 (o desde que empieza la serie, si es posterior; al menos 40 años) hasta el año anterior; solo se dice que "
    "el mes «se ha calentado» si la tendencia es estadísticamente significativa (t ≥ 2). La lluvia solo se da con todos los días "
    "validados y con cifra."
)
LIMITES = [
    "Es una estación por provincia: no describe toda la provincia, y una estación de aeropuerto puede diferir del centro de la ciudad.",
    "Algunas series tienen huecos o cambios de emplazamiento; el puesto se refiere a los años con dato de esa estación.",
    "El provisional usa, para los días que AEMET aún no ha validado, la máxima y la mínima de la observación horaria de la misma estación (o de la de al lado, y se dice).",
    "AEMET puede revisar sus datos diarios después de publicarlos.",
    "Sin atribución con modelos: que un mes sea cálido no dice por sí solo cuánto se debe al cambio climático; la tendencia desde 1970 sí mide el calentamiento en esa estación.",
]


# ----------------------------------------------------------------------------
# gráficos y CSV
# ----------------------------------------------------------------------------
def graficos(caps: list[dict], clave: str, nacional: dict, estado: str):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:  # noqa: BLE001
        log("Sin matplotlib: no hago gráficos")
        return
    d = SALIDA / clave
    d.mkdir(parents=True, exist_ok=True)
    mes, anio = MESES[int(clave[5:]) - 1], int(clave[:4])
    pl = plural_mes(mes)
    pie = "Observatorio climático · calentamientoglobal.es · Datos: AEMET · normal 1991-2020"
    if nacional.get("dias_observacion"):
        pie += " · PROVISIONAL"
    v = sorted([c for c in caps if c.get("valido")], key=lambda c: c["anomalia"])
    if v:
        calido = nacional.get("sentido") == "calido"
        fig, ax = plt.subplots(figsize=(10, max(6, 0.26 * len(v) + 1.6)), dpi=110)
        ys = list(range(len(v)))
        cols = ["#cc4416" if c["anomalia"] > 0 else ("#0071b8" if c["anomalia"] < 0 else "#8a8f94") for c in v]
        ax.barh(ys, [c["anomalia"] for c in v], color=cols, height=0.72)
        ax.set_yticks(ys)

        def marca(c):
            if c["sentido"] != nacional.get("sentido") or c["anomalia"] == 0:
                return ""
            if c["record"] and c["puesto_firme"]:
                return " ★"
            if c["top5"] and c["top5_firme"] and c["puesto_firme"]:
                return " ●"
            return ""
        ax.set_yticklabels([lugar(c) if c["tipo"] == "capital" else c["provincia"] + "*" for c in v], fontsize=9)
        for i, c in enumerate(v):
            a = c["anomalia"]
            ax.text(a + (0.04 if a >= 0 else -0.04), i, signo(a) + marca(c), va="center", ha="left" if a >= 0 else "right",
                    fontsize=8, color="#1d1d1f")
        ax.axvline(0, color="#1d1d1f", lw=0.8)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.tick_params(axis="y", length=0)
        ax.grid(axis="x", color="#eeeeee")
        ax.set_axisbelow(True)
        ax.set_xlabel("°C respecto a la media de 1991-2020 en cada estación · * estación de referencia de la provincia",
                      fontsize=8.5, color="#6e6e73")
        nm = nacional.get("n_calidas", 0) if calido else nacional.get("n_frias", 0)
        ax.set_title(f"{mes.capitalize()} de {anio}, provincia a provincia\n{signo(nacional.get('anomalia_media', 0))} °C de media · "
                     f"{nm} de {nacional.get('n', 0)} más {'cálidas' if calido else 'frías'} de lo normal\n"
                     f"★ récord de su serie · ● uno de sus cinco {pl} más {'cálidos' if calido else 'fríos'}",
                     loc="left", fontsize=12, fontweight="bold", color="#1d1d1f")
        lo, hi = min(c["anomalia"] for c in v), max(c["anomalia"] for c in v)
        ax.set_xlim(min(-0.5, lo - 0.7), max(0.5, hi + 0.7))
        fig.text(0.99, 0.005, pie, ha="right", fontsize=7.5, color="#6e6e73")
        fig.tight_layout(rect=(0, 0.02, 1, 1))
        fig.savefig(d / "nacional.png")
        plt.close(fig)
    for c in caps:
        if not c.get("valido"):
            continue
        serie = {int(y): t for y, t in c["serie"].items()}
        xs = sorted(serie)
        fig, ax = plt.subplots(figsize=(10, 5.6), dpi=110)
        nm = c["normal_tm"]
        ax.bar(xs, [serie[y] - nm for y in xs], bottom=nm, width=0.8,
               color=["#e7a58c" if serie[y] >= nm else "#9cc3e0" for y in xs])
        col = "#cc4416" if c["anomalia"] >= 0 else "#0071b8"
        ax.bar([anio], [c["tm"] - nm], bottom=nm, width=0.8, color=col)
        ax.axhline(nm, color="#6e6e73", lw=0.9)
        ax.text(xs[0], nm, " normal 1991-2020", va="bottom", fontsize=8, color="#6e6e73")
        if c.get("tendencia_decada") is not None:
            pares = [(y, serie[y]) for y in xs if INICIO_TENDENCIA <= y < anio]
            t = tendencia(pares)
            if t:
                x0, x1 = pares[0][0], anio - 1
                lab = f"tendencia desde {c['tendencia_desde']}: {signo(c['tendencia_decada'])} °C por década"
                if not c["tendencia_significativa"]:
                    lab += " (no significativa)"
                ax.plot([x0, x1], [t["origen"] + t["pendiente"] * x0, t["origen"] + t["pendiente"] * x1], color="#1d1d1f",
                        lw=1.6, ls="--", label=lab)
                ax.legend(frameon=False, fontsize=9, loc="upper left")
        ax.annotate(f"{anio}\n{f1(c['tm'])} °C", (anio, c["tm"]), xytext=(0, 6), textcoords="offset points",
                    ha="center", fontsize=9, fontweight="bold", color=col)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", color="#eeeeee")
        ax.set_axisbelow(True)
        ax.set_ylabel(f"temperatura media de {mes} (°C)", fontsize=9, color="#6e6e73")
        an = c["anomalia"]
        rel = f"{signo(an)} °C respecto a lo normal"
        if c["puesto_firme"] and c["top5_firme"] and an != 0:
            adj = "cálido" if c["sentido"] == "calido" else "frío"
            if c["record"]:
                rel += f" · el más {adj} de {c['anios_serie']}"
            elif c["empate_record"]:
                rel += f" · empata con el más {adj} ({c['mejor_anterior']['anio']})"
            else:
                rel += f" · {ord_s(c['puesto'])} más {adj} de {c['anios_serie']}"
        ax.set_title(f"{lugar(c)} · {mes} de cada año\n{mes.capitalize()} de {anio}: {rel}",
                     loc="left", fontsize=12, fontweight="bold", color="#1d1d1f")
        fig.text(0.99, 0.005, pie + f" · estación {c['estacion']} ({c['indicativo']})", ha="right", fontsize=7, color="#6e6e73")
        fig.tight_layout(rect=(0, 0.02, 1, 1))
        fig.savefig(d / f"{c['cod']}.png")
        plt.close(fig)


def escribir_csv(caps: list[dict], p: Path, estado: str):
    cols = ["cod", "provincia", "ciudad", "estacion", "indicativo", "tipo", "dias", "dias_observacion", "dias_sin_validar",
            "tm", "normal_tm", "anomalia", "tx", "normal_tx", "anomalia_tx", "tn", "normal_tn", "anomalia_tn",
            "sentido", "puesto", "anios_serie", "serie_desde", "record", "empate_record", "empatado_con", "top5",
            "puesto_firme", "top5_firme", "tendencia_desde", "tendencia_decada", "tendencia_significativa",
            "lluvia", "lluvia_normal", "lluvia_pct"]
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["estado"] + cols)
        for c in sorted(caps, key=lambda c: c["cod"]):
            if not c.get("valido"):
                continue
            fila = []
            for k in cols:
                x = c.get(k)
                if isinstance(x, list):
                    x = " ".join(str(i) for i in x)
                elif isinstance(x, bool):
                    x = "sí" if x else "no"
                fila.append("" if x is None else x)
            w.writerow([estado] + fila)


# ----------------------------------------------------------------------------
# orquestación
# ----------------------------------------------------------------------------
def calcular(hist: Historia, clave: str, completo: bool, hasta_dia: int | None = None) -> dict:
    a, m = map(int, clave.split("-"))
    ndias = calendar.monthrange(a, m)[1]
    hd = ndias if completo else hasta_dia
    caps = [balance_capital(hist, cod, clave, hd, completo) for cod in sorted(ESTACIONES)]
    validas = [c for c in caps if c.get("valido")]
    n_obs = sum(c.get("dias_observacion", 0) for c in validas)
    faltan_por_dias = [c for c in caps if not c.get("valido") and "días con dato" in (c.get("motivo") or "")]
    if not completo:
        estado = "en curso"
    elif n_obs == 0 and not faltan_por_dias:
        estado = "verificado"          # ningún día de observación; los huecos de AEMET se dicen estación a estación
    elif HOY >= date(a, m, ndias) + timedelta(days=DIA_CIERRE):
        estado = "cerrado"
    else:
        estado = "provisional"
    nac = resumen_nacional(caps, estado == "provisional")
    cal = calibracion(hist)
    for c in caps:
        if c.get("valido") and completo:
            c["nota"] = texto_capital(c, clave, estado)
    out = {
        "mes": clave, "titulo_mes": mes_nombre(clave), "estado": estado,
        "generado": AHORA.isoformat().replace("+00:00", "Z"),
        "hasta_dia": hd,
        "nacional": nac,
        "nota_nacional": texto_nacional(nac, caps, clave, estado) if nac.get("n") and completo else None,
        "calibracion_observacion": cal,
        "capitales": caps,
        "sin_serie": [{"cod": k, "provincia": PROVINCIA[k], "motivo": v} for k, v in sorted(SIN_SERIE.items())],
        "metodo": METODO, "limites": LIMITES, "fuente": FUENTE, "licencia": LICENCIA,
        "archivos": {
            "csv": f"{URL_BASE}{clave}.csv", "grafico_nacional": f"{URL_BASE}{clave}/nacional.png",
            "grafico_capital": f"{URL_BASE}{clave}/" + "{cod}.png",
        },
    }
    if out["nota_nacional"] and nac.get("dias_sin_validar") and cal:
        out["nota_nacional"]["aviso"] += (
            f" En los {cal['dias']} días-estación ya validados, la media diaria de la observación horaria difirió de la "
            f"validada en {f1(cal['dif_abs_media_tm'])} °C de media (sesgo {signo(cal['sesgo_tm'])} °C).")
    if not completo:
        out["metodo"] = ("Mes en curso: la media de los días que van (validados y, los últimos, de la observación horaria) frente a la "
                         "media de esos mismos días en 1991-2020, y el puesto entre los mismos días de cada año. Solo estaciones con "
                         "serie diaria en el archivo. No es el balance del mes: el balance sale el día 1.")
        for c in caps:
            # la tendencia de medio mes es demasiado ruidosa para darla
            for k in ("tendencia_decada", "tendencia_desde", "calentamiento_tramo"):
                c[k] = None
            c["tendencia_significativa"] = False
        nac["n_tendencia_1970"] = 0
    return out


def comparar(prov: dict, ver: dict) -> list[dict]:
    """Qué cambió entre el provisional (el del día 1, el que se envió) y el verificado."""
    pv = {c["cod"]: c for c in prov.get("capitales", []) if c.get("valido")}
    cambios = []
    for c in ver.get("capitales", []):
        if not c.get("valido"):
            if c["cod"] in pv:
                cambios.append({"provincia": c["provincia"], "cambio": "sale del balance", "motivo": c.get("motivo")})
            continue
        if c["cod"] not in pv:
            cambios.append({"provincia": c["provincia"], "cambio": "entra en el balance"})
            continue
        p = pv[c["cod"]]
        dif = {}
        if abs(c["anomalia"] - p["anomalia"]) >= 0.1 - 1e-9:
            dif["anomalia"] = [p["anomalia"], c["anomalia"]]
        for k in ("puesto", "sentido", "record", "empate_record", "top5"):
            if c.get(k) != p.get(k):
                dif[k] = [p.get(k), c.get(k)]
        if dif:
            cambios.append({"provincia": c["provincia"], "ciudad": c["ciudad"], **dif})
    a, b = prov.get("nacional", {}), ver.get("nacional", {})
    for k in ("n", "anomalia_media", "n_calidas", "n_frias", "n_top5", "n_record", "n_empate_record"):
        if a.get(k) != b.get(k):
            cambios.append({"nacional": k, "provisional": a.get(k), "verificado": b.get(k)})
    return cambios


def guardar_propios(bal: dict):
    """Los meses ya sin días de observación entran en la historia para los años siguientes."""
    propios = leer_json(PROPIOS, {})
    for c in bal["capitales"]:
        if c.get("valido") and not c.get("dias_observacion") and not c.get("dias_faltan"):
            propios.setdefault(c["indicativo"], {})[bal["mes"]] = {
                "tm": c["tm"], "tx": c["tx"], "tn": c["tn"], "p": c.get("lluvia")}
    escribir_json(PROPIOS, propios)


def actualizar_index():
    meses = []
    for p in sorted(SALIDA.glob("[12][0-9][0-9][0-9]-[01][0-9].json")):
        b = leer_json(p, {})
        nac = b.get("nacional") or {}
        meses.append({"mes": b.get("mes"), "titulo_mes": b.get("titulo_mes"), "estado": b.get("estado"),
                      "generado": b.get("generado"), "titular": (b.get("nota_nacional") or {}).get("titular"),
                      "n": nac.get("n"), "anomalia_media": nac.get("anomalia_media"),
                      "json": f"{URL_BASE}{p.name}"})
    meses.sort(key=lambda x: x["mes"], reverse=True)
    escribir_json(SALIDA / "index.json", {
        "generado": AHORA.isoformat().replace("+00:00", "Z"), "ultimo": meses[0]["mes"] if meses else None,
        "en_curso": f"{URL_BASE}en_curso.json" if (SALIDA / "en_curso.json").exists() else None, "meses": meses})


def toca_pasada_completa() -> bool:
    """En modo --auto (cada media hora, tras la lluvia por municipio): la pasada completa una vez al día, y del día 1
    al 13 cada 6 horas, para coger los diarios de AEMET en cuanto salen."""
    est = leer_json(STORE / "estado.json", {})
    ult = est.get("ultima_completa")
    if not ult:
        return True
    ult = datetime.fromisoformat(ult.replace("Z", "+00:00"))
    horas = (AHORA - ult).total_seconds() / 3600
    if ult.date() != AHORA.date() and AHORA.hour >= 6:
        return True
    return HOY.day <= DIA_CIERRE + 1 and horas >= 6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mes", help="AAAA-MM: calcula ese mes (completo, ya terminado)")
    ap.add_argument("--forzar", action="store_true", help="recalcula aunque el mes ya esté verificado o cerrado")
    ap.add_argument("--sin-api", action="store_true", help="no pide nada a AEMET")
    ap.add_argument("--auto", action="store_true", help="guarda la observación y solo hace la pasada completa cuando toca")
    args = ap.parse_args()
    global KEY
    if args.sin_api:
        KEY = ""
    mes_actual = f"{HOY.year}-{HOY.month:02d}"
    if args.mes:
        if not re.fullmatch(r"(19|20)\d\d-(0[1-9]|1[0-2])", args.mes) or args.mes >= mes_actual:
            log(f"--mes {args.mes!r} no vale: tiene que ser AAAA-MM de un mes ya terminado")
            return 2
    SALIDA.mkdir(parents=True, exist_ok=True)
    guardar_obs()
    if args.auto and not args.mes and not toca_pasada_completa():
        log("Pasada corta: solo la observación horaria")
        return 0

    previo = HOY.replace(day=1) - timedelta(days=1)
    mes_previo = f"{previo.year}-{previo.month:02d}"
    objetivos = [args.mes] if args.mes else ([mes_previo] if HOY.day <= DIA_CIERRE + 1 else [])

    hist = None
    for clave in objetivos:
        p = SALIDA / f"{clave}.json"
        previo_bal = leer_json(p, {})
        if previo_bal.get("estado") in ("verificado", "cerrado") and not args.forzar:
            log(f"{clave}: ya {previo_bal['estado']}, no se toca")
            continue
        actualizar_validados(clave)
        hist = hist or Historia()
        bal = calcular(hist, clave, completo=True)
        prov_p = SALIDA / f"{clave}_provisional.json"
        if bal["estado"] == "provisional":
            if not prov_p.exists():             # el primero, el que se envía el día 1, queda congelado
                escribir_json(prov_p, bal)
        else:
            prov = leer_json(prov_p, {})
            bal["cambios_desde_provisional"] = comparar(prov, bal) if prov else []
            guardar_propios(bal)
        escribir_json(p, bal)
        escribir_csv(bal["capitales"], SALIDA / f"{clave}.csv", bal["estado"])
        graficos(bal["capitales"], clave, bal["nacional"], bal["estado"])
        nac = bal["nacional"]
        log(f"{clave}: {bal['estado']} · {nac.get('n')} provincias · {signo(nac.get('anomalia_media', 0))} °C · "
            f"{nac.get('n_calidas')} cálidas · top-5 {nac.get('n_top5')} ({nac.get('n_top5_firme')} firmes) · "
            f"récords {nac.get('n_record')} ({nac.get('n_record_firme')} firmes) · empates {nac.get('n_empate_record')}")
        if bal.get("nota_nacional"):
            log("  " + bal["nota_nacional"]["titular"])

    if not args.mes:
        cur = SALIDA / "en_curso.json"
        if HOY.day >= 4:
            hist = hist or Historia()
            hasta = HOY.day - 1
            bal = calcular(hist, mes_actual, completo=False, hasta_dia=hasta)
            escribir_json(cur, bal)
            nac = bal["nacional"]
            log(f"En curso {mes_actual} (1-{hasta}): {nac.get('n')} provincias · {signo(nac.get('anomalia_media', 0))} °C · "
                f"top-5 {nac.get('n_top5')} · récords {nac.get('n_record')}")
        elif cur.exists():
            cur.unlink()                          # del 1 al 3 no hay días suficientes: fuera el del mes pasado
        escribir_json(STORE / "estado.json", {"ultima_completa": AHORA.isoformat().replace("+00:00", "Z")})
    actualizar_index()
    return 0


if __name__ == "__main__":
    sys.exit(main())
