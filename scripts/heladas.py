#!/usr/bin/env python3
"""Heladas en cada capital · calentamientoglobal.es

Qué hace
  Para cada capital con serie diaria larga de AEMET calcula cuándo llega la primera helada, cuándo la última, cuántos
  días hiela al año y cuánto ha cambiado desde los años setenta; mira si ya ha helado este otoño y qué mínimas prevé
  AEMET para la semana. Con eso escribe:
    docs/heladas/index.json          resumen de todas las capitales (lo usa la página /heladas/)
    docs/heladas/<ciudad>.json       detalle de una capital, con todos sus inviernos
    docs/heladas/<ciudad>.csv        inviernos de la capital, para descargar
  y, con --publicar, crea o actualiza en WordPress (API REST) la página /heladas/ y una página hija por capital:
    contenido fijo (climatología, gráfico, récords, preguntas)   solo se reescribe si cambia
    bloque del día (meta cg_ssr_html: este otoño y previsión)     cada pasada, si cambia
    metas de Rank Math y JSON-LD Dataset (cg_ssr_jsonld)

Definiciones
  helada              día con temperatura mínima de 0 °C o menos en la estación de AEMET (como «días de helada» de AEMET)
  invierno AAAA-AA    del 1 de agosto de AAAA al 31 de julio del año siguiente; un invierno cuenta si tiene al menos el
                      95 % de los días con mínima
  normal              inviernos de 1991-92 a 2020-21 (30); hacen falta 24 válidos para dar la climatología
  fecha típica        mediana de los inviernos en que heló; «8 de cada 10» = percentiles 10 y 90
  cambio              1971-1990 (inviernos 1971-72 a 1990-91) frente a 2006-2025 (2006-07 a 2025-26), 16 inviernos válidos
                      en cada tramo como mínimo; se dice que es un cambio real solo si la tendencia lineal de la serie
                      desde 1971 tiene t >= 2

De dónde salen los datos
  historia            archivo/aemet_diario/<indicativo>.csv.gz (valores diarios validados de AEMET, series_diarias_aemet.py)
  este otoño          lo anterior + archivo/balance/diarios/AAAA-MM.json (validados del mes, balance_mensual.py) +
                      archivo/balance/obs/AAAA-MM.json (observación horaria sin validar, dicho en la página)
  previsión           docs/prediccion/<prov>.json (predicción municipal de AEMET, prediccion_municipios.py)

Uso
  python scripts/heladas.py                    calcula y escribe docs/heladas/
  python scripts/heladas.py --vista DIR        además deja el HTML de cada página en DIR (para revisarlo)
  python scripts/heladas.py --publicar         además publica en WordPress (WP_USER, WP_APP_PASSWORD)
  python scripts/heladas.py --publicar --forzar   reescribe el contenido aunque no haya cambiado
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
import statistics as st
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parent.parent
DIARIO = RAIZ / "archivo" / "aemet_diario"
BALANCE = RAIZ / "archivo" / "balance"
PREDICCION = RAIZ / "docs" / "prediccion"
SALIDA = RAIZ / "docs" / "heladas"
PUBLICADO = SALIDA / "publicado.json"
WEB = "https://calentamientoglobal.es"
API = os.environ.get("WP_API", WEB + "/wp-json/wp/v2")
TZ = ZoneInfo("Europe/Madrid")
AHORA = datetime.now(timezone.utc)
HOY = AHORA.astimezone(TZ).date()
PLANTILLA = "page-templates/no-wrapper.php"
ANCLA = "CGSSRSLOT"

NORMAL = (1991, 2020)       # años de otoño de los inviernos de la normal
TRAMO1 = (1971, 1990)
TRAMO2 = (2006, 2025)
MIN_NORMAL = 24
MIN_TRAMO = 16
COBERTURA = 0.95

# slug, ciudad, código de provincia, slug de provincia en la web, provincia, indicativo AEMET, nombre de la estación,
# código INE del municipio (predicción), nota sobre la estación
CIUDADES = [
    ("vitoria", "Vitoria", "01", "alava", "Álava", "9091O", "Vitoria, aeropuerto de Foronda", "01059", "afueras"),
    ("albacete", "Albacete", "02", "albacete", "Albacete", "8175", "Albacete, base aérea de Los Llanos", "02003", "afueras"),
    ("alicante", "Alicante", "03", "alicante", "Alicante", "8025", "Alicante, Ciudad Jardín", "03014", ""),
    ("almeria", "Almería", "04", "almeria", "Almería", "6325O", "Almería, aeropuerto", "04013", "afueras"),
    ("avila", "Ávila", "05", "avila", "Ávila", "2444", "Ávila", "05019", ""),
    ("badajoz", "Badajoz", "06", "badajoz", "Badajoz", "4452", "Badajoz, aeropuerto de Talavera la Real", "06015", "afueras"),
    ("palma", "Palma", "07", "baleares", "Baleares", "B228", "Palma, puerto", "07040", ""),
    ("barcelona", "Barcelona", "08", "barcelona", "Barcelona", "0076", "Barcelona, aeropuerto de El Prat", "08019", "afueras"),
    ("burgos", "Burgos", "09", "burgos", "Burgos", "2331", "Burgos, aeropuerto de Villafría", "09059", "afueras"),
    ("caceres", "Cáceres", "10", "caceres", "Cáceres", "3469A", "Cáceres", "10037", ""),
    ("cadiz", "Cádiz", "11", "cadiz", "Cádiz", "5973", "Cádiz", "11012", ""),
    ("castellon", "Castellón", "12", "castellon", "Castellón", "8500A", "Castelló-Almassora", "12040", "afueras"),
    ("ciudad-real", "Ciudad Real", "13", "ciudad-real", "Ciudad Real", "4121", "Ciudad Real", "13034", ""),
    ("cordoba", "Córdoba", "14", "cordoba", "Córdoba", "5402", "Córdoba, aeropuerto", "14021", "afueras"),
    ("a-coruna", "A Coruña", "15", "a-coruna", "A Coruña", "1387", "A Coruña", "15030", ""),
    ("cuenca", "Cuenca", "16", "cuenca", "Cuenca", "8096", "Cuenca", "16078", ""),
    ("girona", "Girona", "17", "girona", "Girona", "0367", "Girona, aeropuerto", "17079", "afueras"),
    ("granada", "Granada", "18", "granada", "Granada", "5514", "Granada, base aérea de Armilla", "18087", "afueras"),
    ("san-sebastian", "San Sebastián", "20", "gipuzkoa", "Gipuzkoa", "1024E", "Donostia, monte Igeldo", "20069", "igeldo"),
    ("huelva", "Huelva", "21", "huelva", "Huelva", "4642E", "Huelva, Ronda Este", "21041", ""),
    ("huesca", "Huesca", "22", "huesca", "Huesca", "9898", "Huesca, aeropuerto", "22125", "afueras"),
    ("jaen", "Jaén", "23", "jaen", "Jaén", "5270B", "Jaén", "23050", ""),
    ("leon", "León", "24", "leon", "León", "2661", "León, Virgen del Camino", "24089", "afueras"),
    ("lleida", "Lleida", "25", "lleida", "Lleida", "9771C", "Lleida", "25120", ""),
    ("logrono", "Logroño", "26", "la-rioja", "La Rioja", "9170", "Logroño, aeropuerto de Agoncillo", "26089", "afueras"),
    ("lugo", "Lugo", "27", "lugo", "Lugo", "1518A", "Lugo", "27028", ""),
    ("madrid", "Madrid", "28", "madrid", "Madrid", "3195", "Madrid, parque del Retiro", "28079", ""),
    ("malaga", "Málaga", "29", "malaga", "Málaga", "6155A", "Málaga, aeropuerto", "29067", "afueras"),
    ("murcia", "Murcia", "30", "murcia", "Murcia", "7178I", "Murcia", "30030", ""),
    ("pamplona", "Pamplona", "31", "navarra", "Navarra", "9263D", "Pamplona, aeropuerto de Noáin", "31201", "afueras"),
    ("ourense", "Ourense", "32", "ourense", "Ourense", "1690A", "Ourense", "32054", ""),
    ("vigo", "Vigo", "36", "pontevedra", "Pontevedra", "1495", "Vigo, aeropuerto de Peinador", "36057", "afueras"),
    ("salamanca", "Salamanca", "37", "salamanca", "Salamanca", "2867", "Salamanca, aeropuerto de Matacán", "37274", "afueras"),
    ("santa-cruz-de-tenerife", "Santa Cruz de Tenerife", "38", "santa-cruz-de-tenerife", "Santa Cruz de Tenerife",
     "C449C", "Santa Cruz de Tenerife", "38038", ""),
    ("segovia", "Segovia", "40", "segovia", "Segovia", "2465", "Segovia", "40194", ""),
    ("sevilla", "Sevilla", "41", "sevilla", "Sevilla", "5783", "Sevilla, aeropuerto de San Pablo", "41091", "afueras"),
    ("soria", "Soria", "42", "soria", "Soria", "2030", "Soria", "42173", ""),
    ("tortosa", "Tortosa", "43", "tarragona", "Tarragona", "9981A", "Observatorio del Ebro, en Roquetes", "43155", ""),
    ("teruel", "Teruel", "44", "teruel", "Teruel", "8368U", "Teruel", "44216", ""),
    ("toledo", "Toledo", "45", "toledo", "Toledo", "3260B", "Toledo", "45168", ""),
    ("valencia", "Valencia", "46", "valencia", "Valencia", "8416", "València", "46250", ""),
    ("valladolid", "Valladolid", "47", "valladolid", "Valladolid", "2422", "Valladolid", "47186", ""),
    ("bilbao", "Bilbao", "48", "bizkaia", "Bizkaia", "1082", "Bilbao, aeropuerto de Loiu", "48020", "afueras"),
    ("zamora", "Zamora", "49", "zamora", "Zamora", "2614", "Zamora", "49275", ""),
    ("zaragoza", "Zaragoza", "50", "zaragoza", "Zaragoza", "9434", "Zaragoza, aeropuerto", "50297", "afueras"),
    ("melilla", "Melilla", "52", "melilla", "Melilla", "6000A", "Melilla", "52001", ""),
]
# La observación horaria de algunas estaciones sale con otro indicativo (mismo sitio o al lado).
OBS_ALIAS = {"9091O": "9091R", "5514": "5514Z"}

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]
DIAS_SEM = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
REF = date(2021, 8, 1)       # invierno de referencia (sin 29 de febrero) para pasar fechas a «día del invierno»


def log(m: str) -> None:
    print(time.strftime("%H:%M:%S ") + m, flush=True)


def leer_json(p: Path, defecto):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return defecto


def escribir(p: Path, texto: str) -> bool:
    """Escribe solo si cambia. Devuelve si ha cambiado."""
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists() and p.read_text(encoding="utf-8") == texto:
        return False
    p.write_text(texto, encoding="utf-8")
    return True


# ------------------------------------------------------------------------------------------------ formatos en español
def num(x: float, dec: int = 1) -> str:
    s = f"{x:.{dec}f}".replace(".", ",")
    return s.replace("-", "−")


def grados(x: float) -> str:
    return num(x) + " °C"


def entero(x: float) -> str:
    n = int(round(x))
    s = f"{abs(n):,}".replace(",", ".")
    return ("−" if n < 0 else "") + s


def fecha_larga(d: date, anio: bool = True) -> str:
    s = f"{d.day} de {MESES[d.month - 1]}"
    return s + (f" de {d.year}" if anio else "")


def dia_semana(d: date) -> str:
    return f"{DIAS_SEM[d.weekday()]} {d.day}"


def indice(d: date) -> int:
    """Día del invierno (0 = 1 de agosto) en un calendario sin 29 de febrero."""
    m, dd = d.month, d.day
    if m == 2 and dd == 29:
        dd = 28
    y = REF.year if m >= 8 else REF.year + 1
    return (date(y, m, dd) - REF).days


def fecha_de_indice(i: float) -> date:
    return REF + timedelta(days=int(round(i)))


def dia_mes(i: float) -> str:
    return fecha_larga(fecha_de_indice(i), anio=False)


def invierno(y: int) -> str:
    return f"{y}-{str(y + 1)[2:]}"


def esc(s) -> str:
    return html.escape(str(s), quote=True)


def percentil(xs: list, p: float):
    xs = sorted(xs)
    if not xs:
        return None
    k = (len(xs) - 1) * p
    f = math.floor(k)
    c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def tendencia(pares: list) -> tuple:
    """Pendiente por década y su t, con mínimos cuadrados. pares = [(año, valor)]."""
    if len(pares) < 10:
        return None, None
    n = len(pares)
    mx = sum(a for a, _ in pares) / n
    my = sum(v for _, v in pares) / n
    sxx = sum((a - mx) ** 2 for a, _ in pares)
    if sxx == 0:
        return None, None
    b = sum((a - mx) * (v - my) for a, v in pares) / sxx
    res = [v - (my + b * (a - mx)) for a, v in pares]
    s2 = sum(r * r for r in res) / (n - 2)
    se = math.sqrt(s2 / sxx) if s2 > 0 else 0
    t = b / se if se > 0 else (math.inf if b else 0)
    return b * 10, t


# ---------------------------------------------------------------------------------------------------- lectura de datos
def serie_validada(ide: str) -> dict:
    """{fecha: mínima} del archivo diario de AEMET más los validados del mes que guarda el balance."""
    out = {}
    f = DIARIO / f"{ide}.csv.gz"
    if f.exists():
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                v = r.get("tmin")
                if v not in (None, "", "None"):
                    try:
                        out[r["fecha"]] = float(v)
                    except ValueError:
                        pass
    for p in sorted((BALANCE / "diarios").glob("*.json")):
        est = (leer_json(p, {}).get("estaciones") or {}).get(ide) or {}
        for fch, v in est.items():
            if isinstance(v, list) and len(v) > 1 and v[1] is not None:
                out[fch] = float(v[1])
    return out


def serie_observada(ide: str) -> dict:
    """{fecha: (mínima, indicativo)} de la observación horaria guardada por el balance (días completos)."""
    out = {}
    for p in sorted((BALANCE / "obs").glob("*.json")):
        est = (leer_json(p, {}).get("estaciones") or {}).get(ide) or {}
        for fch, v in est.items():
            if isinstance(v, dict) and v.get("tn") is not None:
                out[fch] = (float(v["tn"]), v.get("id") or ide)
    return out


def prevision(prov: str, ine: str) -> dict:
    d = leer_json(PREDICCION / f"{prov}.json", {})
    m = (d.get("municipios") or {}).get(ine) or {}
    dias = []
    for x in (m.get("d") or {}).get("dias") or []:
        try:
            f = date.fromisoformat(x["f"])
        except Exception:  # noqa: BLE001
            continue
        if f >= HOY and x.get("tn") is not None:
            dias.append({"f": f.isoformat(), "tn": float(x["tn"])})
    return {"elab": (m.get("d") or {}).get("elab"), "municipio": m.get("n"), "dias": dias}


# ----------------------------------------------------------------------------------------------------------- cálculo
def inviernos(tmin: dict) -> dict:
    """{año de otoño: datos del invierno} para los inviernos completos."""
    if not tmin:
        return {}
    y0 = int(min(tmin)[:4]) - 1
    y1 = HOY.year - 1 if HOY >= date(HOY.year, 8, 1) else HOY.year - 2   # último invierno ya cerrado
    out = {}
    for y in range(y0, y1 + 1):
        ini, fin = date(y, 8, 1), date(y + 1, 7, 31)
        total = (fin - ini).days + 1
        dias = [(ini + timedelta(days=k)) for k in range(total)]
        con = [(d, tmin[d.isoformat()]) for d in dias if d.isoformat() in tmin]
        if len(con) < COBERTURA * total:
            continue
        hel = [(d, t) for d, t in con if t <= 0]
        mn = min(con, key=lambda x: x[1])
        out[y] = {
            "cobertura": round(len(con) / total, 3),
            "dias": len(hel),
            "primera": hel[0][0].isoformat() if hel else None,
            "primera_t": hel[0][1] if hel else None,
            "ultima": hel[-1][0].isoformat() if hel else None,
            "ultima_t": hel[-1][1] if hel else None,
            "minima": mn[1],
            "minima_f": mn[0].isoformat(),
        }
    return out


def climatologia(inv: dict, tmin: dict) -> dict:
    nor = {y: v for y, v in inv.items() if NORMAL[0] <= y <= NORMAL[1]}
    n = len(nor)
    con = [v for v in nor.values() if v["primera"]]
    c = {"n": n, "con_helada": len(con)}
    if n < MIN_NORMAL:
        c["tipo"] = "sin_serie"
        return c
    cuota = len(con) / n
    c["tipo"] = "frecuente" if cuota >= 0.9 else ("irregular" if cuota >= 0.3 else "rara")
    c["dias"] = sum(v["dias"] for v in nor.values()) / n
    if con:
        pi = [indice(date.fromisoformat(v["primera"])) for v in con]
        ui = [indice(date.fromisoformat(v["ultima"])) for v in con]
        c["primera"] = st.median(pi)
        c["primera_p10"] = percentil(pi, 0.1)
        c["primera_p90"] = percentil(pi, 0.9)
        c["ultima"] = st.median(ui)
        c["ultima_p10"] = percentil(ui, 0.1)
        c["ultima_p90"] = percentil(ui, 0.9)
        c["primeras_idx"] = sorted(pi)
    # periodo sin heladas: de la última helada de la primavera a la primera del otoño siguiente
    libres = []
    for y in range(NORMAL[0], NORMAL[1] + 1):
        a, b = inv.get(y - 1), inv.get(y)
        if a and b and a["ultima"] and b["primera"]:
            libres.append((date.fromisoformat(b["primera"]) - date.fromisoformat(a["ultima"])).days)
    if len(libres) >= MIN_NORMAL - 4:
        c["libre"] = st.median(libres)
    c["mediana_minima"] = st.median(v["minima"] for v in nor.values())
    return c


def records(inv: dict, tmin: dict) -> dict:
    r = {"desde": int(min(tmin)[:4]) if tmin else None, "inviernos": len(inv)}
    con = [(y, v) for y, v in inv.items() if v["primera"]]
    if con:
        y, v = min(con, key=lambda x: indice(date.fromisoformat(x[1]["primera"])))
        r["mas_temprana"] = {"f": v["primera"], "t": v["primera_t"], "invierno": invierno(y)}
        y, v = max(con, key=lambda x: indice(date.fromisoformat(x[1]["ultima"])))
        r["mas_tardia"] = {"f": v["ultima"], "t": v["ultima_t"], "invierno": invierno(y)}
        y, v = max(inv.items(), key=lambda x: x[1]["dias"])
        r["mas_dias"] = {"dias": v["dias"], "invierno": invierno(y)}
    if tmin:
        f, t = min(tmin.items(), key=lambda x: (x[1], x[0]))
        r["minima"] = {"f": f, "t": t}
        hel = [f for f, t in tmin.items() if t <= 0]
        r["ultima_helada"] = max(hel) if hel else None
        r["n_dias_helada_serie"] = len(hel)
    return r


def cambio(inv: dict, clima: dict) -> dict:
    out = {}
    t1 = [v for y, v in inv.items() if TRAMO1[0] <= y <= TRAMO1[1]]
    t2 = [v for y, v in inv.items() if TRAMO2[0] <= y <= TRAMO2[1]]
    desde = [(y, v) for y, v in inv.items() if 1971 <= y <= TRAMO2[1]]
    pend, t = tendencia([(y, v["dias"]) for y, v in desde])
    out["dias_tendencia"] = {"por_decada": pend, "t": t, "desde": min((y for y, _ in desde), default=None),
                             "n": len(desde)}
    if len(t1) >= MIN_TRAMO and len(t2) >= MIN_TRAMO:
        out["dias"] = {"t1": sum(v["dias"] for v in t1) / len(t1), "t2": sum(v["dias"] for v in t2) / len(t2),
                       "n1": len(t1), "n2": len(t2)}
    if clima.get("tipo") == "frecuente":
        p = [(y, indice(date.fromisoformat(v["primera"]))) for y, v in desde if v["primera"]]
        u = [(y, indice(date.fromisoformat(v["ultima"]))) for y, v in desde if v["ultima"]]
        # solo si casi todos los inviernos tienen helada: si no, la fecha media se sesga
        if len(p) >= 0.9 * len(desde):
            pend, t = tendencia(p)
            out["primera_tendencia"] = {"por_decada": pend, "t": t}
            pend, t = tendencia(u)
            out["ultima_tendencia"] = {"por_decada": pend, "t": t}
            p1 = [indice(date.fromisoformat(v["primera"])) for v in t1 if v["primera"]]
            p2 = [indice(date.fromisoformat(v["primera"])) for v in t2 if v["primera"]]
            u1 = [indice(date.fromisoformat(v["ultima"])) for v in t1 if v["ultima"]]
            u2 = [indice(date.fromisoformat(v["ultima"])) for v in t2 if v["ultima"]]
            if min(len(p1), len(p2)) >= MIN_TRAMO and len(p1) >= 0.9 * len(t1) and len(p2) >= 0.9 * len(t2):
                out["primera"] = {"t1": st.median(p1), "t2": st.median(p2)}
                out["ultima"] = {"t1": st.median(u1), "t2": st.median(u2)}
    return out


def este_otono(val: dict, obs: dict, clima: dict) -> dict:
    """Lo que va de invierno: desde el 1 de agosto hasta el último día con dato."""
    y = HOY.year if HOY >= date(HOY.year, 8, 1) else HOY.year - 1
    ini = date(y, 8, 1)
    dias, d = [], ini
    while d < HOY:
        k = d.isoformat()
        if k in val:
            dias.append((d, val[k], "validado", None))
        elif k in obs:
            dias.append((d, obs[k][0], "observación", obs[k][1]))
        d += timedelta(days=1)
    out = {"invierno": invierno(y), "desde": ini.isoformat(), "n": len(dias)}
    if not dias:
        return out
    hasta = dias[-1][0]
    out["hasta"] = hasta.isoformat()
    out["hasta_validado"] = max((x[0] for x in dias if x[2] == "validado"), default=None)
    if out["hasta_validado"]:
        out["hasta_validado"] = out["hasta_validado"].isoformat()
    huecos = (hasta - ini).days + 1 - len(dias)
    out["huecos"] = huecos
    hel = [x for x in dias if x[1] <= 0]
    out["dias_helada"] = len(hel)
    mn = min(dias, key=lambda x: x[1])
    out["minima"] = {"f": mn[0].isoformat(), "t": mn[1], "fuente": mn[2]}
    if hel:
        p = hel[0]
        out["primera"] = {"f": p[0].isoformat(), "t": p[1], "fuente": p[2], "otra_estacion": p[3]}
        if clima.get("primera") is not None:
            out["primera"]["frente_normal"] = indice(p[0]) - clima["primera"]
    # qué parte de los inviernos normales ya había tenido helada a estas alturas
    if clima.get("primeras_idx") is not None and clima.get("n"):
        i = indice(hasta)
        out["normal_ya"] = sum(1 for x in clima["primeras_idx"] if x <= i) / clima["n"]
    return out


def calcular(c: tuple) -> dict | None:
    slug, ciudad, prov, pslug, pnombre, ide, est, ine, nota = c
    val = serie_validada(ide)
    if not val:
        log(f"  {ciudad}: sin serie diaria ({ide})")
        return None
    obs_ide = serie_observada(ide)
    inv = inviernos(val)
    clima = climatologia(inv, val)
    if clima["tipo"] == "sin_serie":
        log(f"  {ciudad}: solo {clima['n']} inviernos válidos en 1991-2020, no se publica")
        return None
    return {
        "slug": slug, "ciudad": ciudad, "prov": prov, "prov_slug": pslug, "provincia": pnombre,
        "estacion": {"id": ide, "nombre": est, "nota": nota, "alias_obs": OBS_ALIAS.get(ide)},
        "clima": clima, "records": records(inv, val), "cambio": cambio(inv, clima),
        "otono": este_otono(val, obs_ide, clima), "prevision": prevision(prov, ine),
        "inviernos": {invierno(y): v for y, v in sorted(inv.items())},
        "_inv": inv,
    }


# ------------------------------------------------------------------------------------------------------------ textos
def frase_cuando(x: dict) -> str:
    c, ciudad = x["clima"], x["ciudad"]
    if c["tipo"] == "frecuente":
        return (f"En {ciudad} la primera helada llega, en un año normal, hacia el {dia_mes(c['primera'])}, y la última, "
                f"hacia el {dia_mes(c['ultima'])}. Hiela {entero(c['dias'])} días al año.")
    if c["tipo"] == "irregular":
        return (f"En {ciudad} no hiela todos los inviernos: heló en {c['con_helada']} de los {c['n']} inviernos de "
                f"1991 a 2021, de media {num(c['dias'])} días al año. Cuando hiela, la primera helada suele llegar "
                f"hacia el {dia_mes(c['primera'])}.")
    if c["con_helada"] == 0:
        return (f"En {ciudad} no ha helado ni un solo día en los {c['n']} inviernos de 1991 a 2021: la temperatura no "
                f"ha bajado de 0 °C en la estación de AEMET.")
    return (f"En {ciudad} la helada es rara: en los {c['n']} inviernos de 1991 a 2021 heló en {c['con_helada']}, "
            f"de media {num(c['dias'])} días al año.")


def frase_cambio(x: dict) -> str | None:
    cm, ciudad = x["cambio"], x["ciudad"]
    td = cm.get("dias_tendencia") or {}
    sig = td.get("t") is not None and abs(td["t"]) >= 2
    partes = []
    if cm.get("dias"):
        a, b = cm["dias"]["t1"], cm["dias"]["t2"]
        if round(a) == round(b):
            partes.append(f"Hiela prácticamente los mismos días que hace cincuenta años: {entero(a)} al año en 1971-1990 "
                          f"y {entero(b)} en 2006-2025.")
        else:
            verbo = "menos" if b < a else "más"
            frase = (f"En 1971-1990 helaba {entero(a)} días al año; en 2006-2025, {entero(b)}: "
                     f"{entero(abs(a - b))} días {verbo}.")
            frase += (" La tendencia de toda la serie confirma el cambio." if sig else
                      " Pero la tendencia de toda la serie no es estadísticamente significativa: puede ser variabilidad.")
            partes.append(frase)
    elif td.get("n") and td["n"] >= 35 and td.get("por_decada") is not None:
        if sig:
            v = abs(td["por_decada"])
            partes.append(f"Desde {invierno(td['desde'])}, hiela {num(v)} días {'menos' if td['por_decada'] < 0 else 'más'} "
                          f"por década.")
        else:
            partes.append(f"Desde {invierno(td['desde'])} no hay un cambio claro en el número de días de helada.")
    if cm.get("primera"):
        a, b = cm["primera"]["t1"], cm["primera"]["t2"]
        tp = cm.get("primera_tendencia") or {}
        d = round(b - a)
        if abs(d) >= 3 and tp.get("t") is not None and abs(tp["t"]) >= 2:
            partes.append(f"La primera helada llega {abs(d)} días {'más tarde' if d > 0 else 'antes'} que en 1971-1990: "
                          f"entonces, hacia el {dia_mes(a)}; ahora, hacia el {dia_mes(b)}.")
        else:
            partes.append(f"La fecha de la primera helada no ha cambiado de forma clara: hacia el {dia_mes(a)} en "
                          f"1971-1990 y hacia el {dia_mes(b)} en 2006-2025.")
        a, b = cm["ultima"]["t1"], cm["ultima"]["t2"]
        tu = cm.get("ultima_tendencia") or {}
        d = round(b - a)
        if abs(d) >= 3 and tu.get("t") is not None and abs(tu["t"]) >= 2:
            partes.append(f"Y la última se adelanta: {abs(d)} días {'antes' if d < 0 else 'después'} "
                          f"(del {dia_mes(a)} al {dia_mes(b)}).")
    if not partes:
        return None
    return " ".join(partes)


def frase_otono(x: dict) -> str:
    o, c, ciudad = x["otono"], x["clima"], x["ciudad"]
    if not o.get("hasta"):
        return f"Todavía no hay datos de este invierno para {ciudad}."
    if o.get("primera"):
        p = o["primera"]
        f = date.fromisoformat(p["f"])
        s = f"Ya ha helado: la primera helada de este otoño en {ciudad} fue el {fecha_larga(f, False)}, con {grados(p['t'])}"
        fn = p.get("frente_normal")
        if fn is not None and c["tipo"] == "frecuente":
            fn = round(fn)
            s += (", el mismo día que en un año normal" if fn == 0 else
                  f", {abs(fn)} días {'antes' if fn < 0 else 'después'} de lo normal")
        s += "."
        if p["fuente"] == "observación":
            s += " Es un dato de la observación horaria, pendiente de que AEMET lo valide."
        if o["dias_helada"] > 1:
            s += f" Lleva {o['dias_helada']} días de helada."
        return s
    hasta = date.fromisoformat(o["hasta"])
    s = (f"Aún no ha helado este otoño en {ciudad}: la mínima más baja ha sido de {grados(o['minima']['t'])}, el "
         f"{fecha_larga(date.fromisoformat(o['minima']['f']), False)}.")
    if c["tipo"] == "frecuente" and c.get("primera") is not None:
        if indice(hasta) < c["primera"]:
            s += f" Es lo normal: la primera helada suele llegar hacia el {dia_mes(c['primera'])}."
        else:
            ya = o.get("normal_ya")
            s += f" En un año normal la primera llega hacia el {dia_mes(c['primera'])}"
            if ya is not None:
                s += f": en {round(ya * 10)} de cada 10 inviernos ya había helado a estas alturas"
            s += "."
    return s


# ----------------------------------------------------------------------------------------------------------- gráficos
def svg_temporada(x: dict) -> str:
    """Barras verticales: de la primera a la última helada de cada invierno."""
    inv = x["_inv"]
    ys = sorted(inv)
    c = x["clima"]
    W, H, L, R, T, B = 720, 340, 70, 12, 14, 34
    # eje vertical: del día con la helada más temprana al de la más tardía de toda la serie, con margen
    idx = [indice(date.fromisoformat(v["primera"])) for v in inv.values() if v["primera"]] + \
          [indice(date.fromisoformat(v["ultima"])) for v in inv.values() if v["ultima"]]
    o = x["otono"]
    if o.get("primera"):
        idx.append(indice(date.fromisoformat(o["primera"]["f"])))
    lo = max(0, min(idx) - 10)
    hi = min(364, max(idx) + 10)
    # marcas del eje: el día 1 de cada mes dentro del rango
    marcas = []
    for m in [9, 10, 11, 12, 1, 2, 3, 4, 5, 6, 7]:
        i = indice(date(2021 if m >= 8 else 2022, m, 1))
        if lo <= i <= hi:
            marcas.append((i, MESES[m - 1][:3]))
    n = (HOY.year if HOY.month >= 8 else HOY.year - 1) - ys[0] + 1
    paso = (W - L - R) / n
    Y = lambda i: T + (H - T - B) * (i - lo) / (hi - lo)
    s = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-labelledby="cghel-g1" class="cghel-svg">'
         f'<title id="cghel-g1">Primera y última helada de cada invierno en {esc(x["ciudad"])}, desde {invierno(ys[0])}</title>']
    for i, lab in marcas:
        s.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(i):.1f}" y2="{Y(i):.1f}" stroke="#ece6de"/>'
                 f'<text x="{L - 8}" y="{Y(i) + 4:.1f}" font-size="13" text-anchor="end" fill="#7a6a58">1 {lab}</text>')
    if c.get("primera") is not None:
        for key, lab in (("primera", "primera"), ("ultima", "última")):
            yy = Y(c[key])
            s.append(f'<line x1="{L}" x2="{W - R}" y1="{yy:.1f}" y2="{yy:.1f}" stroke="#1d1408" stroke-dasharray="4 3" '
                     f'stroke-width="1"/>')
    for k, y in enumerate(range(ys[0], ys[0] + n)):
        v = inv.get(y)
        cx = L + (k + 0.5) * paso
        w = max(2.0, paso * 0.62)
        if v and v["primera"]:
            a, b = Y(indice(date.fromisoformat(v["primera"]))), Y(indice(date.fromisoformat(v["ultima"])))
            col = "#5b8fc7" if NORMAL[0] <= y <= NORMAL[1] else "#8fb3da"
            s.append(f'<rect x="{cx - w / 2:.1f}" y="{a:.1f}" width="{w:.1f}" height="{max(2, b - a):.1f}" rx="1" '
                     f'fill="{col}"><title>{invierno(y)}: de {esc(dia_mes(indice(date.fromisoformat(v["primera"]))))} '
                     f'a {esc(dia_mes(indice(date.fromisoformat(v["ultima"]))))}, {v["dias"]} días de helada</title></rect>')
        if y == ys[0] + n - 1 and o.get("primera"):
            a = Y(indice(date.fromisoformat(o["primera"]["f"])))
            s.append(f'<circle cx="{cx:.1f}" cy="{a:.1f}" r="5" fill="#cc2200"><title>Este otoño: primera helada el '
                     f'{esc(fecha_larga(date.fromisoformat(o["primera"]["f"]), False))}</title></circle>')
    # años en el eje horizontal
    for y in range(ys[0], ys[0] + n):
        if y % 10 == 0 or y == ys[0]:
            k = y - ys[0]
            if y == ys[0] and (10 - y % 10) % 10 < 6 and y % 10:
                continue
            s.append(f'<text x="{L + (k + 0.5) * paso:.1f}" y="{H - B + 18}" font-size="13" text-anchor="middle" '
                     f'fill="#7a6a58">{y}</text>')
    if c.get("primera") is not None:
        s.append(f'<text x="{W - R - 4}" y="{Y(c["primera"]) - 5:.1f}" font-size="12.5" text-anchor="end" fill="#1d1408" '
                 f'stroke="#fff" stroke-width="4" paint-order="stroke">primera, año normal: {esc(dia_mes(c["primera"]))}</text>')
        s.append(f'<text x="{W - R - 4}" y="{Y(c["ultima"]) + 15:.1f}" font-size="12.5" text-anchor="end" fill="#1d1408" '
                 f'stroke="#fff" stroke-width="4" paint-order="stroke">última, año normal: {esc(dia_mes(c["ultima"]))}</text>')
    s.append("</svg>")
    return "".join(s)


def svg_minimas(x: dict) -> str:
    """Barras: la noche más fría de cada invierno, con la línea de 0 °C."""
    inv = x["_inv"]
    ys = sorted(inv)
    W, H, L, R, T, B = 720, 300, 52, 12, 14, 34
    vals = [v["minima"] for v in inv.values()]
    lo = math.floor(min(min(vals), 0) - 1)
    hi = math.ceil(max(vals) + 1)
    n = (HOY.year if HOY.month >= 8 else HOY.year - 1) - ys[0]
    paso = (W - L - R) / max(1, n)
    Y = lambda t: T + (H - T - B) * (hi - t) / (hi - lo)
    s = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-labelledby="cghel-g2" class="cghel-svg">'
         f'<title id="cghel-g2">La noche más fría de cada invierno en {esc(x["ciudad"])}, desde {invierno(ys[0])}</title>']
    paso_t = 2 if hi - lo <= 14 else 4
    t = lo + (-lo) % paso_t
    while t <= hi:
        trazo = ' stroke="#1d1408" stroke-dasharray="4 3"' if t == 0 else ' stroke="#ece6de"'
        s.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(t):.1f}" y2="{Y(t):.1f}"{trazo}/><text x="{L - 8}" y="{Y(t) + 4:.1f}" '
                 f'font-size="13" text-anchor="end" fill="#7a6a58">{num(t, 0)} °C</text>')
        t += paso_t
    base = Y(max(lo, min(hi, 0)))
    for k, y in enumerate(range(ys[0], ys[0] + n)):
        v = inv.get(y)
        if not v:
            continue
        cx = L + (k + 0.5) * paso
        w = max(2.0, paso * 0.62)
        yy = Y(v["minima"])
        col = "#5b8fc7" if v["minima"] <= 0 else "#d9a48a"
        top, h = (min(yy, base), abs(yy - base))
        s.append(f'<rect x="{cx - w / 2:.1f}" y="{top:.1f}" width="{w:.1f}" height="{max(1.5, h):.1f}" fill="{col}">'
                 f'<title>{invierno(y)}: {esc(grados(v["minima"]))} el {esc(fecha_larga(date.fromisoformat(v["minima_f"])))}'
                 f'</title></rect>')
    for y in range(ys[0], ys[0] + n):
        if y % 10 == 0 or y == ys[0]:
            k = y - ys[0]
            if y == ys[0] and (10 - y % 10) % 10 < 6 and y % 10:
                continue
            s.append(f'<text x="{L + (k + 0.5) * paso:.1f}" y="{H - B + 18}" font-size="13" text-anchor="middle" '
                     f'fill="#7a6a58">{y}</text>')
    s.append("</svg>")
    return "".join(s)


# ------------------------------------------------------------------------------------------------------------ páginas
CSS = """<style>
.cghel{max-width:860px;margin:0 auto;padding:30px 0 10px;font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:#1d1408}
.cghel a{color:#cc4400}
.cghel-migas{font-size:13px;color:#b0a08c;margin:0 0 16px}.cghel-migas a{color:#7a6a58;text-decoration:none}.cghel-migas span{margin:0 5px}
.cghel .kicker{font-size:12.5px;text-transform:uppercase;letter-spacing:.08em;color:#2f6db0;font-weight:700;margin:0 0 10px}
.cghel h1{font-size:40px;line-height:1.14;letter-spacing:-.022em;margin:0 0 16px;font-weight:800;color:#1d1408}
.cghel .lede{font-size:18.5px;line-height:1.6;color:#3b2f22;margin:0 0 22px}
.cghel h2{font-size:26px;line-height:1.22;letter-spacing:-.012em;margin:40px 0 12px;font-weight:800}
.cghel h3{font-size:18px;margin:22px 0 6px;font-weight:700}
.cghel-cifras{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:0 0 8px}
.cghel-cifra{background:#f3f7fc;border:1px solid #d7e3f1;border-radius:12px;padding:14px 16px}
.cghel-cifra b{display:block;font-size:26px;line-height:1.12;font-weight:800;color:#1f5a99}
.cghel-cifra span{display:block;margin-top:6px;font-size:14px;line-height:1.4;color:#4a3f33}
.cghel-cifra small{display:block;margin-top:4px;font-size:12px;color:#8a7a68}
.cghel-svg{width:100%;height:auto;display:block;font-family:inherit}
.cghel figure{margin:18px 0 8px}.cghel figcaption{font-size:13.5px;color:#7a6a58;margin-top:6px}
.cghel-ley{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:13.5px;color:#5a4a38;margin:8px 0 0}
.cghel-ley i{display:inline-block;width:14px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
.cghel ul.cghel-rec{list-style:none;padding:0;margin:8px 0}.cghel ul.cghel-rec li{display:flex;justify-content:space-between;gap:16px;border-bottom:1px solid #ece6de;padding:9px 0}
.cghel ul.cghel-rec li b{text-align:right}
.cghel-tabla{width:100%;border-collapse:collapse;font-size:15px;margin:10px 0}
.cghel-tabla th,.cghel-tabla td{border-bottom:1px solid #ece6de;padding:8px 6px;text-align:left;vertical-align:top}
.cghel-tabla th{background:#f7f3ee;font-size:13.5px}
.cghel-nota{font-size:14px;color:#6b5d4d}
.cghel-metodo{background:#faf7f3;border:1px solid #ece6de;border-radius:12px;padding:16px 18px;font-size:14.5px;margin:36px 0 10px}
.cg-ssr-slot{visibility:hidden;font-size:0;line-height:0}
.cg-ssr-slot .cghel-hoy{visibility:visible;font-size:16px;line-height:1.6}
.cghel-hoy{background:#eef4fb;border:1px solid #cfdff0;border-left:6px solid #2f6db0;border-radius:14px;padding:18px 22px 14px;margin:26px 0 8px;color:#1d1408}
.cghel-hoy h2{margin:0 0 8px;font-size:23px}.cghel-hoy h3{margin:16px 0 6px;font-size:17px}
.cghel-hoy p{margin:0 0 10px}.cghel-hoy .cghel-estado{font-size:17.5px}
.cghel-hoy table{width:100%;border-collapse:collapse;font-size:15px;background:#fff;border-radius:8px}
.cghel-hoy th,.cghel-hoy td{border-bottom:1px solid #dfe8f2;padding:7px 10px;text-align:left}
.cghel-hoy .cghel-si{color:#1f5a99;font-weight:700}.cghel-hoy .cghel-casi{color:#5a4a38}
.cghel-hoy .cghel-pie{font-size:13px;color:#5f6f80;margin:10px 0 0}
@media(max-width:520px){.cghel{padding:20px 18px 0}.cghel h1{font-size:29px}.cghel .lede{font-size:16.5px}.cghel h2{font-size:22px}
.cghel-cifra b{font-size:23px}.cghel-hoy{padding:16px 16px 12px}.cghel-svgw{overflow-x:auto;direction:rtl}.cghel-svgw svg{min-width:560px;direction:ltr}}
</style>"""


def faq_jsonld(preguntas: list) -> str:
    d = {"@context": "https://schema.org", "@type": "FAQPage",
         "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
                        for q, a in preguntas]}
    return '<script type="application/ld+json">' + json.dumps(d, ensure_ascii=False) + "</script>"


def url_ciudad(x: dict) -> str:
    return f"{WEB}/heladas/{x['slug']}/"


def nota_estacion(x: dict) -> str:
    e = x["estacion"]
    if e["nota"] == "afueras":
        return (f"Los datos son de la estación de AEMET de {e['nombre']}, a las afueras: en el centro de la ciudad, "
                f"con más edificios y asfalto, suele helar menos.")
    if e["nota"] == "igeldo":
        return (f"Los datos son de la estación de AEMET del monte Igeldo, por encima de la ciudad y junto al mar: en "
                f"los barrios bajos y del interior puede helar más.")
    return f"Los datos son de la estación de AEMET de {e['nombre']}."


def preguntas(x: dict) -> list:
    c, r, ciudad = x["clima"], x["records"], x["ciudad"]
    q = []
    if c["tipo"] == "frecuente":
        q.append((f"¿Cuándo es la primera helada en {ciudad}?",
                  f"En un año normal, hacia el {dia_mes(c['primera'])}. En 8 de cada 10 inviernos llega entre el "
                  f"{dia_mes(c['primera_p10'])} y el {dia_mes(c['primera_p90'])} (estación de AEMET de "
                  f"{x['estacion']['nombre']}, inviernos de 1991-92 a 2020-21)."))
        q.append((f"¿Cuándo es la última helada en {ciudad}?",
                  f"Hacia el {dia_mes(c['ultima'])}. En 9 de cada 10 inviernos ya no hiela después del "
                  f"{dia_mes(c['ultima_p90'])}, una fecha útil para plantar sin riesgo de helada."))
        q.append((f"¿Cuántos días hiela al año en {ciudad}?",
                  f"De media, {entero(c['dias'])} días al año con una mínima de 0 °C o menos (1991-2021)."))
    elif c["tipo"] == "irregular":
        q.append((f"¿Hiela en {ciudad}?",
                  f"Algunos inviernos sí: heló en {c['con_helada']} de los {c['n']} inviernos de 1991 a 2021, de media "
                  f"{num(c['dias'])} días al año. Cuando hiela, la primera suele llegar hacia el {dia_mes(c['primera'])}."))
        q.append((f"¿Cuándo hiela en {ciudad}?",
                  f"Las heladas, cuando llegan, caen sobre todo entre el {dia_mes(c['primera_p10'])} y el "
                  f"{dia_mes(c['ultima_p90'])}."))
    else:
        if c["con_helada"] == 0:
            q.append((f"¿Hiela en {ciudad}?",
                      f"No. En los {c['n']} inviernos de 1991 a 2021 la estación de AEMET no bajó de 0 °C ni un solo día."))
        else:
            q.append((f"¿Hiela en {ciudad}?",
                      f"Muy pocas veces: heló en {c['con_helada']} de los {c['n']} inviernos de 1991 a 2021."))
    if r.get("minima"):
        q.append((f"¿Cuál es la temperatura más baja registrada en {ciudad}?",
                  f"{grados(r['minima']['t'])}, el {fecha_larga(date.fromisoformat(r['minima']['f']))}, en la estación "
                  f"de AEMET de {x['estacion']['nombre']} (serie diaria desde {r['desde']})."))
    return q


def html_ciudad(x: dict, hub_url: str) -> str:
    c, r, ciudad, e = x["clima"], x["records"], x["ciudad"], x["estacion"]
    tipo = c["tipo"]
    if tipo == "frecuente":
        h1 = f"Heladas en {ciudad}: cuándo llega la primera y cuándo la última"
    else:
        h1 = f"¿Hiela en {ciudad}? Las heladas, año a año"
    out = [CSS, '<div class="cghel">',
           f'<div class="cghel-migas"><a href="/">Inicio</a> <span>&rsaquo;</span> <a href="{hub_url}">Heladas</a> '
           f'<span>&rsaquo;</span> {esc(ciudad)}</div>',
           '<p class="kicker">Observatorio climático · Heladas</p>',
           f"<h1>{esc(h1)}</h1>",
           f'<p class="lede">{esc(frase_cuando(x))} {esc(nota_estacion(x))}</p>']
    # cifras
    cif = []
    if tipo == "frecuente":
        cif.append((dia_mes(c["primera"]), "primera helada, en un año normal", "mediana 1991-2021"))
        cif.append((dia_mes(c["ultima"]), "última helada de la primavera", "mediana 1991-2021"))
        cif.append((f"{entero(c['dias'])} días", "de helada al año", "media 1991-2021"))
        if c.get("libre"):
            cif.append((f"{entero(c['libre'])} días", "seguidos sin helar, de la primavera al otoño", "mediana 1991-2021"))
    else:
        cif.append((f"{c['con_helada']} de {c['n']}", "inviernos con alguna helada", "1991-92 a 2020-21"))
        cif.append((num(c["dias"]) + " días", "de helada al año, de media", "1991-2021"))
        if r.get("ultima_helada"):
            cif.append((fecha_larga(date.fromisoformat(r["ultima_helada"])), "la última vez que heló", "dato validado"))
        if r.get("minima"):
            cif.append((grados(r["minima"]["t"]), "temperatura más baja registrada",
                        fecha_larga(date.fromisoformat(r["minima"]["f"]))))
    out.append('<div class="cghel-cifras">' + "".join(
        f'<div class="cghel-cifra"><b>{esc(a)}</b><span>{esc(b)}</span><small>{esc(s)}</small></div>' for a, b, s in cif)
        + "</div>")
    out.append(f'<div class="cg-ssr-slot">{ANCLA}</div>')
    # cuándo hiela
    if tipo == "irregular":
        out.append(f"<h2>¿Cuándo hiela en {esc(ciudad)}?</h2>")
        out.append(f"<p>Cuando hiela, la primera helada suele llegar hacia el {esc(dia_mes(c['primera']))} y la última hacia "
                   f"el {esc(dia_mes(c['ultima']))}. Pero muchos inviernos pasan sin ninguna: en los {c['n']} de 1991 a "
                   f"2021 heló en {c['con_helada']}. El gráfico muestra la noche más fría de cada invierno: por debajo de la "
                   f"línea de 0 °C, heló.</p>")
        out.append('<figure><div class="cghel-svgw">' + svg_minimas(x) + "</div>"
                   f'<figcaption>La temperatura más baja de cada invierno, de agosto a julio. Fuente: AEMET, estación de '
                   f'{esc(e["nombre"])}.</figcaption></figure>')
    elif tipo == "frecuente":
        out.append(f"<h2>¿Cuándo hiela en {esc(ciudad)}?</h2>")
        if tipo == "frecuente":
            out.append(f"<p>En 8 de cada 10 inviernos la primera helada llega entre el {esc(dia_mes(c['primera_p10']))} y el "
                       f"{esc(dia_mes(c['primera_p90']))}, y la última cae entre el {esc(dia_mes(c['ultima_p10']))} y el "
                       f"{esc(dia_mes(c['ultima_p90']))}. Si vas a plantar en el huerto o en el balcón, la fecha que importa "
                       f"es la segunda: en 9 de cada 10 inviernos ya no ha vuelto a helar después del "
                       f"<b>{esc(dia_mes(c['ultima_p90']))}</b>.</p>")
        out.append('<figure><div class="cghel-svgw">' + svg_temporada(x) + "</div>"
                   '<div class="cghel-ley"><span><i style="background:#5b8fc7"></i>De la primera a la última helada de cada '
                   'invierno (1991-2021)</span><span><i style="background:#8fb3da"></i>Otros años</span>'
                   + ('<span><i style="background:#cc2200;border-radius:50%"></i>Este otoño</span>' if x["otono"].get("primera") else "")
                   + '<span>Discontinuas: fechas de un año normal</span></div>'
                   f'<figcaption>Cada barra es un invierno, de agosto a julio. Sin barra: no heló o faltan datos. Fuente: AEMET, '
                   f'estación de {esc(e["nombre"])}.</figcaption></figure>')
    else:
        out.append(f"<h2>¿Cuánto frío hace en {esc(ciudad)} en invierno?</h2>")
        med = c.get("mediana_minima")
        out.append(f"<p>La noche más fría de un invierno normal se queda en {esc(grados(med))}. El gráfico muestra la mínima más "
                   f"baja de cada invierno: por debajo de la línea de 0 °C, heló.</p>")
        out.append('<figure><div class="cghel-svgw">' + svg_minimas(x) + "</div>"
                   f'<figcaption>La temperatura más baja de cada invierno, de agosto a julio. Fuente: AEMET, estación de '
                   f'{esc(e["nombre"])}.</figcaption></figure>')
    # cambio
    fc = frase_cambio(x)
    if fc:
        out.append(f"<h2>¿Hiela menos que antes en {esc(ciudad)}?</h2><p>{esc(fc)}</p>")
        if tipo in ("frecuente", "irregular") and r.get("desde") and r["desde"] > 1971:
            out.append(f'<p class="cghel-nota">La serie diaria de esta estación empieza en {r["desde"]}.</p>')
    # récords
    out.append(f"<h2>Récords de helada en {esc(ciudad)}</h2><ul class=\"cghel-rec\">")
    if r.get("mas_temprana"):
        m = r["mas_temprana"]
        out.append(f"<li><span>La primera helada más temprana</span><b>{esc(fecha_larga(date.fromisoformat(m['f'])))} · "
                   f"{esc(grados(m['t']))}</b></li>")
        m = r["mas_tardia"]
        out.append(f"<li><span>La última helada más tardía</span><b>{esc(fecha_larga(date.fromisoformat(m['f'])))} · "
                   f"{esc(grados(m['t']))}</b></li>")
        m = r["mas_dias"]
        out.append(f"<li><span>El invierno con más heladas</span><b>{esc(m['invierno'])} · {m['dias']} días</b></li>")
    if r.get("minima"):
        out.append(f"<li><span>La temperatura más baja</span><b>{esc(grados(r['minima']['t']))} · "
                   f"{esc(fecha_larga(date.fromisoformat(r['minima']['f'])))}</b></li>")
    out.append(f"<li><span>Serie diaria de la estación</span><b>desde {r['desde']}</b></li></ul>")
    # preguntas
    q = preguntas(x)
    out.append('<h2>Preguntas frecuentes</h2>')
    for a, b in q:
        out.append(f"<h3>{esc(a)}</h3><p>{esc(b)}</p>")
    # método
    out.append(
        '<div class="cghel-metodo"><p><b>Cómo se calcula.</b> Un día de helada es un día con una temperatura mínima de 0 °C '
        f'o menos en la estación de AEMET de {esc(e["nombre"])} (indicativo {esc(e["id"])}), con los valores diarios '
        'validados que publica AEMET OpenData. Cada invierno va del 1 de agosto al 31 de julio y solo cuenta si tiene datos '
        'de al menos el 95 % de los días. «En un año normal» es la mediana de los inviernos de 1991-92 a 2020-21. Los cambios '
        'comparan 1971-1990 con 2006-2025 y solo se dan por buenos si la tendencia de toda la serie es estadísticamente '
        'significativa. Una estación puede haber cambiado de sitio o de entorno a lo largo de los años, y eso también mueve '
        f'las cifras. Los datos de todos los inviernos se pueden <a href="https://davidbebow.github.io/temperaturas-mar-espana/heladas/{esc(x["slug"])}.csv">descargar en CSV</a> '
        '(licencia CC BY 4.0, citando a calentamientoglobal.es y a AEMET).</p>'
        f'<p>Más: <a href="{hub_url}">las heladas en todas las capitales</a> · '
        f'<a href="/el-tiempo/{esc(x["prov_slug"])}/">el tiempo en la provincia de {esc(x["provincia"])}</a> · '
        f'<a href="/cambio-climatico-en-{esc(x["prov_slug"])}/">el cambio climático en {esc(x["provincia"])}</a> · '
        '<a href="/metodologia/">metodología</a></p></div>')
    out.append("</div>")
    out.append(faq_jsonld(q))
    return "<!-- wp:html -->\n" + "\n".join(out) + "\n<!-- /wp:html -->"


def tabla_prevision(x: dict) -> str:
    p = x["prevision"]
    if not p["dias"]:
        return ""
    filas = []
    for dd in p["dias"][:7]:
        f = date.fromisoformat(dd["f"])
        t = dd["tn"]
        if t <= 0:
            et = '<span class="cghel-si">Helada</span>'
        elif t <= 2:
            et = '<span class="cghel-casi">Cerca de 0 °C</span>'
        else:
            et = ""
        nombre = "hoy" if f == HOY else ("mañana" if f == HOY + timedelta(days=1) else dia_semana(f))
        filas.append(f"<tr><td>{esc(nombre.capitalize())}</td><td>{esc(grados(t))}</td><td>{et}</td></tr>")
    hel = [d for d in p["dias"][:7] if d["tn"] <= 0]
    if hel:
        f = date.fromisoformat(hel[0]["f"])
        intro = (f"AEMET prevé helada en {esc(x['ciudad'])} el {esc(dia_semana(f))}, con {esc(grados(hel[0]['tn']))}"
                 + (f", y {len(hel) - 1} día{'s' if len(hel) > 2 else ''} más esta semana" if len(hel) > 1 else "") + ".")
    else:
        mn = min(p["dias"][:7], key=lambda d: d["tn"])
        intro = (f"AEMET no prevé heladas en los próximos días: la mínima más baja sería de {esc(grados(mn['tn']))}, el "
                 f"{esc(dia_semana(date.fromisoformat(mn['f'])))}.")
    return (f"<h3>Previsión de mínimas</h3><p>{intro}</p><table><thead><tr><th>Día</th><th>Mínima</th><th></th></tr>"
            f"</thead><tbody>{''.join(filas)}</tbody></table>"
            f'<p class="cghel-pie">Predicción de AEMET para el municipio de {esc(p["municipio"] or x["ciudad"])}.'
            + (" La estación de las afueras suele quedar más fría que el pronóstico de la ciudad."
               if x["estacion"]["nota"] == "afueras" else "") + "</p>")


def ssr_ciudad(x: dict) -> str:
    o = x["otono"]
    partes = [f'<section class="cghel-hoy"><h2>Este otoño en {esc(x["ciudad"])}</h2>',
              f'<p class="cghel-estado">{esc(frase_otono(x))}</p>']
    if o.get("hasta"):
        hv = o.get("hasta_validado")
        h = date.fromisoformat(o["hasta"])
        nota = f"Datos de la estación hasta el {fecha_larga(h, False)}"
        if hv and hv < o["hasta"]:
            nota += (f"; desde el {fecha_larga(date.fromisoformat(hv) + timedelta(days=1), False)}, de la observación horaria, "
                     f"pendiente de validar")
        partes.append(f'<p class="cghel-pie">{esc(nota)}.</p>')
    partes.append(tabla_prevision(x))
    partes.append(f'<p class="cghel-pie">Actualizado el {esc(fecha_larga(AHORA.astimezone(TZ).date()))} a las '
                  f'{AHORA.astimezone(TZ):%H:%M}.</p></section>')
    return "".join(partes)


def metas_ciudad(x: dict) -> dict:
    c, ciudad = x["clima"], x["ciudad"]
    if c["tipo"] == "frecuente":
        t = f"Primera helada en {ciudad}: cuándo llega y cuántos días hiela"
        d = (f"En {ciudad} la primera helada llega hacia el {dia_mes(c['primera'])} y la última hacia el "
             f"{dia_mes(c['ultima'])}. Hiela {entero(c['dias'])} días al año. Mira si ya ha helado y la previsión.")
    elif c["tipo"] == "irregular":
        t = f"¿Hiela en {ciudad}? Heladas, fechas y récords"
        d = (f"En {ciudad} heló en {c['con_helada']} de los {c['n']} inviernos de 1991 a 2021, {num(c['dias'])} días al "
             f"año de media. Cuándo hiela, el récord de frío y si se esperan heladas esta semana.")
    else:
        t = f"¿Hiela en {ciudad}? Lo que dicen {c['n']} inviernos de datos"
        d = ((f"En {ciudad} no ha helado ni un día en los {c['n']} inviernos de 1991 a 2021. " if c["con_helada"] == 0 else
              f"En {ciudad} heló en {c['con_helada']} de {c['n']} inviernos. ")
             + "El récord de frío, la noche más fría de cada invierno y la previsión.")
    return {"rank_math_title": t, "rank_math_description": d[:300]}


def jsonld_ciudad(x: dict) -> str:
    c = x["clima"]
    vm = [{"@type": "PropertyValue", "name": "Días de helada al año (media 1991-2021)", "value": round(c["dias"], 1),
           "unitText": "días"}]
    if c.get("primera") is not None:
        vm.append({"@type": "PropertyValue", "name": "Fecha típica de la primera helada (mediana 1991-2021)",
                   "value": dia_mes(c["primera"])})
        vm.append({"@type": "PropertyValue", "name": "Fecha típica de la última helada (mediana 1991-2021)",
                   "value": dia_mes(c["ultima"])})
    d = {"@context": "https://schema.org", "@type": "Dataset",
         "name": f"Heladas en {x['ciudad']}: primera y última helada de cada invierno",
         "description": (f"Primera y última helada, días de helada y mínima más baja de cada invierno en la estación de "
                         f"AEMET de {x['estacion']['nombre']}, con la climatología 1991-2021 y la previsión de mínimas."),
         "url": url_ciudad(x), "license": "https://creativecommons.org/licenses/by/4.0/",
         "creator": {"@type": "Organization", "name": "calentamientoglobal.es", "url": WEB + "/"},
         "temporalCoverage": f"{x['records']['desde']}/..",
         "spatialCoverage": {"@type": "Place", "name": f"{x['ciudad']}, España"},
         "variableMeasured": vm,
         "distribution": [{"@type": "DataDownload", "encodingFormat": "text/csv",
                           "contentUrl": f"https://davidbebow.github.io/temperaturas-mar-espana/heladas/{x['slug']}.csv"}],
         "sourceOrganization": {"@type": "Organization", "name": "AEMET", "url": "https://opendata.aemet.es/"}}
    return json.dumps(d, ensure_ascii=False)


def html_hub(xs: list) -> str:
    frec = sorted([x for x in xs if x["clima"]["tipo"] == "frecuente"], key=lambda x: x["clima"]["primera"])
    irr = sorted([x for x in xs if x["clima"]["tipo"] == "irregular"], key=lambda x: -x["clima"]["dias"])
    rara = sorted([x for x in xs if x["clima"]["tipo"] == "rara"], key=lambda x: -x["clima"]["dias"])
    prim = frec[0]
    nunca = [x["ciudad"] for x in rara if x["clima"]["con_helada"] == 0]
    out = [CSS, '<div class="cghel">',
           '<div class="cghel-migas"><a href="/">Inicio</a> <span>&rsaquo;</span> Heladas</div>',
           '<p class="kicker">Observatorio climático · Heladas</p>',
           "<h1>Heladas en España: cuándo llega la primera helada a cada ciudad</h1>",
           f'<p class="lede">La primera helada llega antes a {esc(prim["ciudad"])}, hacia el {esc(dia_mes(prim["clima"]["primera"]))}, '
           f'y a {esc(frec[1]["ciudad"])} y {esc(frec[2]["ciudad"])} pocos días después. En buena parte de la costa casi nunca '
           f'hiela{": en " + esc(_lista(nunca)) + " no ha helado ni un día desde 1991" if nunca else ""}. Aquí '
           f'tienes la fecha típica de la primera y la última helada en {len(xs)} capitales, con los datos de AEMET, si ya ha '
           f'helado este otoño y si se esperan heladas esta semana.</p>',
           f'<div class="cg-ssr-slot">{ANCLA}</div>',
           "<h2>La primera y la última helada, ciudad a ciudad</h2>",
           '<p>Fechas de un año normal (mediana de los inviernos de 1991-92 a 2020-21) en la estación de AEMET de cada ciudad. '
           'Pulsa en la ciudad para ver su historia, sus récords y la previsión.</p>',
           '<table class="cghel-tabla"><thead><tr><th>Ciudad</th><th>Primera helada</th><th>Última helada</th>'
           '<th>Días de helada al año</th></tr></thead><tbody>']
    for x in frec:
        c = x["clima"]
        out.append(f'<tr><td><a href="/heladas/{esc(x["slug"])}/">{esc(x["ciudad"])}</a></td><td>{esc(dia_mes(c["primera"]))}</td>'
                   f'<td>{esc(dia_mes(c["ultima"]))}</td><td>{entero(c["dias"])}</td></tr>')
    for x in irr:
        c = x["clima"]
        out.append(f'<tr><td><a href="/heladas/{esc(x["slug"])}/">{esc(x["ciudad"])}</a></td>'
                   f'<td colspan="2">no todos los inviernos: heló en {c["con_helada"]} de {c["n"]}</td><td>{num(c["dias"])}</td></tr>')
    for x in rara:
        c = x["clima"]
        txt = "nunca desde 1991" if c["con_helada"] == 0 else f"casi nunca: heló en {c['con_helada']} de {c['n']} inviernos"
        out.append(f'<tr><td><a href="/heladas/{esc(x["slug"])}/">{esc(x["ciudad"])}</a></td><td colspan="2">{esc(txt)}</td>'
                   f'<td>{num(c["dias"])}</td></tr>')
    out.append("</tbody></table>")
    out.append('<p class="cghel-nota">Muchas estaciones están en aeropuertos o bases aéreas, a las afueras: en el centro de las '
               'ciudades suele helar algo menos. Faltan las capitales cuya estación de AEMET no tiene todavía una serie diaria '
               'larga en el observatorio; se añadirán solas cuando la tenga.</p>')
    # cambio
    bajan = []
    for x in xs:
        d = x["cambio"].get("dias")
        td = x["cambio"].get("dias_tendencia") or {}
        if d and td.get("t") is not None and td["t"] <= -2 and d["t1"] - d["t2"] >= 3:
            bajan.append((d["t1"] - d["t2"], x))
    bajan.sort(key=lambda z: -z[0])
    if bajan:
        out.append("<h2>¿Hiela menos que antes?</h2>")
        out.append(f"<p>En {len(bajan)} de las {len(xs)} ciudades hiela hoy claramente menos que hace cincuenta años, con una "
                   f"tendencia estadísticamente significativa. Donde más ha bajado:</p><ul>")
        for dlt, x in bajan[:6]:
            d = x["cambio"]["dias"]
            out.append(f'<li><a href="/heladas/{esc(x["slug"])}/">{esc(x["ciudad"])}</a>: de {entero(d["t1"])} días de helada al '
                       f'año en 1971-1990 a {entero(d["t2"])} en 2006-2025.</li>')
        out.append("</ul>")
    q = [("¿Dónde llega antes la primera helada en España?",
          f"Entre las capitales, a {prim['ciudad']}, hacia el {dia_mes(prim['clima']['primera'])} en un año normal; después, "
          f"{frec[1]['ciudad']} ({dia_mes(frec[1]['clima']['primera'])}) y {frec[2]['ciudad']} "
          f"({dia_mes(frec[2]['clima']['primera'])})."),
         ("¿Qué se considera una helada?",
          "Un día en que la temperatura mínima baja a 0 °C o menos. Es la definición que usa AEMET para contar los días de "
          "helada, medida a 1,5 metros del suelo; en el suelo y en las zonas bajas puede helar con el termómetro algo por encima "
          "de 0 °C.")]
    if nunca:
        q.append(("¿En qué ciudades no hiela nunca?",
                  f"En {_lista(nunca)} no ha helado ni un solo día en los inviernos de 1991 a 2021, según las estaciones de AEMET."))
    tarde = max(frec, key=lambda x: x["clima"]["ultima"])
    pronto = min(frec, key=lambda x: x["clima"]["ultima"])
    q.append(("¿Cuándo es la última helada en España?",
              f"Depende mucho de la ciudad: en {tarde['ciudad']} la última helada llega hacia el "
              f"{dia_mes(tarde['clima']['ultima'])}, y en {pronto['ciudad']}, hacia el {dia_mes(pronto['clima']['ultima'])}."))
    out.append("<h2>Preguntas frecuentes</h2>")
    for a, b in q:
        out.append(f"<h3>{esc(a)}</h3><p>{esc(b)}</p>")
    out.append('<div class="cghel-metodo"><p><b>Cómo se calcula.</b> Un día de helada es un día con una temperatura mínima de '
               '0 °C o menos en la estación de AEMET, con los valores diarios validados de AEMET OpenData. Cada invierno va del 1 '
               'de agosto al 31 de julio. «En un año normal» es la mediana de los inviernos de 1991-92 a 2020-21. Lo de este otoño '
               'se actualiza varias veces al día con los datos validados, la observación horaria y la predicción de AEMET. Datos en '
               '<a href="https://davidbebow.github.io/temperaturas-mar-espana/heladas/index.json">JSON</a> (CC BY 4.0).</p>'
               '<p>Más: <a href="/el-tiempo/">el tiempo en España, municipio a municipio</a> · '
               '<a href="/records-de-temperatura/">récords de temperatura</a> · '
               '<a href="/cambio-climatico-por-provincias/">cambio climático por provincias</a></p></div>')
    out.append("</div>")
    out.append(faq_jsonld(q))
    return "<!-- wp:html -->\n" + "\n".join(out) + "\n<!-- /wp:html -->"


def _lista(xs: list) -> str:
    xs = list(xs)
    if len(xs) <= 1:
        return "".join(xs)
    return ", ".join(xs[:-1]) + " y " + xs[-1]


def ssr_hub(xs: list) -> str:
    ya = [x for x in xs if x["otono"].get("primera")]
    ya.sort(key=lambda x: x["otono"]["primera"]["f"])
    prev = []
    for x in xs:
        hel = [d for d in x["prevision"]["dias"][:7] if d["tn"] <= 0]
        if hel:
            prev.append((min(d["tn"] for d in hel), x, hel))
    prev.sort(key=lambda z: z[0])
    p = ['<section class="cghel-hoy"><h2>Este otoño</h2>']
    if ya:
        p.append(f'<p class="cghel-estado">Ya ha helado en {len(ya)} de las {len(xs)} capitales.</p><ul>')
        for x in ya:
            f = x["otono"]["primera"]
            p.append(f'<li><a href="/heladas/{esc(x["slug"])}/">{esc(x["ciudad"])}</a>: el '
                     f'{esc(fecha_larga(date.fromisoformat(f["f"]), False))}, con {esc(grados(f["t"]))}'
                     + (" (observación horaria, pendiente de validar)" if f["fuente"] == "observación" else "") + "</li>")
        p.append("</ul>")
    else:
        p.append('<p class="cghel-estado">Todavía no ha helado este otoño en ninguna capital.</p>')
    if prev:
        p.append(f"<h3>Heladas previstas esta semana</h3><p>AEMET prevé mínimas de 0 °C o menos en {len(prev)} capitales:</p><ul>")
        for t, x, hel in prev:
            p.append(f'<li><a href="/heladas/{esc(x["slug"])}/">{esc(x["ciudad"])}</a>: hasta {esc(grados(t))} '
                     f'({esc(_lista([dia_semana(date.fromisoformat(d["f"])) for d in hel]))})</li>')
        p.append("</ul>")
    else:
        p.append("<h3>Heladas previstas esta semana</h3><p>AEMET no prevé mínimas de 0 °C o menos en ninguna capital en los "
                 "próximos días.</p>")
    p.append(f'<p class="cghel-pie">Actualizado el {esc(fecha_larga(AHORA.astimezone(TZ).date()))} a las '
             f'{AHORA.astimezone(TZ):%H:%M}. Datos de las estaciones de AEMET y predicción municipal de AEMET.</p></section>')
    return "".join(p)


# ----------------------------------------------------------------------------------------------------------- salidas
def guardar_datos(xs: list) -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    idx = {"generado": AHORA.isoformat().replace("+00:00", "Z"), "fuente": "AEMET OpenData (valores diarios validados, "
           "observación horaria y predicción municipal) · cálculo de calentamientoglobal.es",
           "licencia": "CC BY 4.0", "definicion": "helada: temperatura mínima de 0 °C o menos en la estación",
           "normal": "inviernos de 1991-92 a 2020-21 (del 1 de agosto al 31 de julio)", "ciudades": []}
    for x in xs:
        c = x["clima"]
        fila = {"slug": x["slug"], "ciudad": x["ciudad"], "provincia": x["provincia"], "estacion": x["estacion"]["id"],
                "estacion_nombre": x["estacion"]["nombre"], "tipo": c["tipo"], "dias_helada_al_anio": round(c["dias"], 1),
                "inviernos_con_helada": c["con_helada"], "inviernos": c["n"],
                "primera_helada": dia_mes(c["primera"]) if c.get("primera") is not None else None,
                "ultima_helada": dia_mes(c["ultima"]) if c.get("ultima") is not None else None,
                "otono": {k: v for k, v in x["otono"].items()}, "url": url_ciudad(x)}
        idx["ciudades"].append(fila)
        det = {k: v for k, v in x.items() if not k.startswith("_")}
        det["clima"] = {k: v for k, v in c.items() if k != "primeras_idx"}
        for k in ("primera", "primera_p10", "primera_p90", "ultima", "ultima_p10", "ultima_p90"):
            if det["clima"].get(k) is not None:
                det["clima"][k + "_fecha"] = dia_mes(det["clima"][k])
        det["generado"] = idx["generado"]
        escribir(SALIDA / f"{x['slug']}.json", json.dumps(det, ensure_ascii=False, indent=1, default=str))
        filas = ["invierno,cobertura,dias_helada,primera_helada,minima_primera,ultima_helada,minima_ultima,minima_invierno,"
                 "fecha_minima"]
        for y, v in sorted(x["_inv"].items()):
            filas.append(",".join(str(z if z is not None else "") for z in (
                invierno(y), v["cobertura"], v["dias"], v["primera"], v["primera_t"], v["ultima"], v["ultima_t"], v["minima"],
                v["minima_f"])))
        escribir(SALIDA / f"{x['slug']}.csv", "\n".join(filas) + "\n")
    # index.json lleva la hora: se reescribe siempre (el workflow solo hace commit si cambia algo más que la hora)
    escribir(SALIDA / "index.json", json.dumps(idx, ensure_ascii=False, indent=1, default=str))


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
                "User-Agent": "calentamientoglobal.es/heladas"})
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


def publicar(xs: list, forzar: bool) -> None:
    usuario, clave = os.environ.get("WP_USER"), os.environ.get("WP_APP_PASSWORD")
    if not usuario or not clave:
        log("Faltan WP_USER / WP_APP_PASSWORD: no se publica")
        sys.exit(1)
    wp = WP(usuario, clave)
    reg = leer_json(PUBLICADO, {})
    errores = 0

    def subir(clave_reg: str, padre: int, slug: str, titulo: str, contenido: str, ssr: str, jsonld: str, metas: dict):
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
        hc, hs = h(titulo + contenido + json.dumps(metas, sort_keys=True) + jsonld), h(ssr)
        datos = {}
        if forzar or not pid or r.get("hc") != hc:
            datos.update({"title": titulo, "content": contenido, "status": "publish", "parent": padre, "slug": slug,
                          "template": PLANTILLA, "comment_status": "closed", "ping_status": "closed"})
            meta = {"cg_ssr_anchor": ANCLA, "cg_ssr_jsonld": jsonld}
            meta.update(metas)
            datos["meta"] = meta
        if forzar or not pid or r.get("hs") != hs or datos:
            datos.setdefault("meta", {})["cg_ssr_html"] = ssr
        if not datos:
            return pid
        try:
            if pid:
                res = wp.pedir("POST", f"/pages/{pid}", datos)
            else:
                res = wp.pedir("POST", "/pages", datos)
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
        reg[clave_reg] = {"id": pid, "hc": hc if "content" in datos else r.get("hc"), "hs": hs,
                          "link": res.get("link"), "actualizado": AHORA.isoformat()}
        log(f"  {slug}: {'contenido y bloque' if 'content' in datos else 'bloque del día'} → {res.get('link')}")
        return pid

    hub_id = subir("_hub", 0, "heladas", "Heladas en España: cuándo llega la primera helada a cada ciudad", html_hub(xs),
                   ssr_hub(xs), json.dumps({"@context": "https://schema.org", "@type": "Dataset",
                                            "name": "Heladas en las capitales de España",
                                            "description": "Fecha típica de la primera y la última helada y días de helada al "
                                                           "año en las capitales de provincia, con datos diarios de AEMET.",
                                            "url": WEB + "/heladas/", "license": "https://creativecommons.org/licenses/by/4.0/",
                                            "creator": {"@type": "Organization", "name": "calentamientoglobal.es",
                                                        "url": WEB + "/"}}, ensure_ascii=False),
                   {"rank_math_title": "Primera helada en España: cuándo hiela en cada ciudad",
                    "rank_math_description": "Cuándo llega la primera helada y cuándo la última en cada capital, cuántos días "
                                             "hiela al año, dónde ha helado ya este otoño y dónde se esperan heladas."})
    if not hub_id:
        log("No se pudo crear la página /heladas/")
        sys.exit(1)
    for x in xs:
        subir(x["slug"], hub_id, x["slug"], ("Heladas en " if x["clima"]["tipo"] == "frecuente" else "¿Hiela en ")
              + x["ciudad"] + ("" if x["clima"]["tipo"] == "frecuente" else "?"),
              html_ciudad(x, "/heladas/"), ssr_ciudad(x), jsonld_ciudad(x), metas_ciudad(x))
    escribir(PUBLICADO, json.dumps(reg, ensure_ascii=False, indent=1, sort_keys=True))
    if errores:
        log(f"{errores} páginas con error")
        sys.exit(1)


# ---------------------------------------------------------------------------------------------------------- principal
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--publicar", action="store_true")
    ap.add_argument("--forzar", action="store_true")
    ap.add_argument("--vista", default="")
    a = ap.parse_args()
    xs = []
    for c in CIUDADES:
        x = calcular(c)
        if x:
            xs.append(x)
            cl = x["clima"]
            log(f"{x['ciudad']}: {cl['tipo']}, {cl['con_helada']}/{cl['n']} inviernos con helada, "
                f"{num(cl['dias'])} días/año" + (f", primera {dia_mes(cl['primera'])}" if cl.get('primera') is not None else ""))
    if len(xs) < 30:
        log(f"Solo {len(xs)} ciudades con datos: algo va mal, no se sigue")
        sys.exit(1)
    guardar_datos(xs)
    if a.vista:
        d = Path(a.vista)
        d.mkdir(parents=True, exist_ok=True)
        (d / "heladas.html").write_text(html_hub(xs).replace(ANCLA, ssr_hub(xs)), encoding="utf-8")
        for x in xs:
            (d / f"{x['slug']}.html").write_text(html_ciudad(x, "/heladas/").replace(ANCLA, ssr_ciudad(x)), encoding="utf-8")
            (d / f"{x['slug']}.metas.json").write_text(json.dumps(metas_ciudad(x), ensure_ascii=False), encoding="utf-8")
    if a.publicar:
        publicar(xs, a.forzar)


if __name__ == "__main__":
    main()
