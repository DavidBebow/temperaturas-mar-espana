#!/usr/bin/env python3
"""
Paquetes de temporada · Observatorio climático (calentamientoglobal.es).

El «Climate Matters» español: cada semana, un paquete con datos por capital desde 1940
sobre la temporada en curso, listo para que un medio lo publique con su ciudad:
titulares, cifras, gráfico por capital, CSV, texto de método y límites.

Series: ERA5 (Copernicus/ECMWF) vía Open-Meteo Archive, celda de cada capital, diario
desde 1940. No descarga nada: lee la serie que el workflow «Actualizar archivo de las
capitales» mantiene en archivo/era5/NN/ (hasta_2025_era5.csv.gz + AAAA.csv), la misma
que alimenta docs/archivo/NN.json, y la reduce a agregados anuales.

Escribe (docs/prensa/paquetes/):
  series/NN.json            agregados por año y capital (estaciones, noches, días de calor, heladas, lluvia)
  <paquete>.json            el paquete: hallazgos nacionales, ranking, texto por capital, método
  <paquete>/NN.png|.csv     gráfico (sin el año en curso: estable) y serie por capital
  index.json                paquetes disponibles, cuáles son de temporada ahora, titulares

Auditoría del 17-10-2026 (v2): el reanálisis en una celda no reproduce bien los umbrales de una
ciudad. Contrastado con las estaciones de AEMET (2017-2025), la celda da a Granada 60 noches
tropicales al año frente a 10 en la estación, y a Burgos 33 días de helada frente a 69. Por eso:
  · los paquetes de umbral sobre ERA5 (noches tropicales, primera helada, días de 30 °C, heladas,
    lluvia intensa) se siguen calculando pero NO se publican (publicable: false);
  · en los paquetes de estación (otoño, invierno…), cada capital con estación de AEMET de serie
    larga (aemet_estaciones_largas.json, valores mensuales oficiales) publica la cifra de AEMET;
    las demás, la del reanálisis, dicho en el titular;
  · las heladas salen de AEMET (días con mínima ≤ 0 °C de los valores mensuales), no de ERA5.
Los titulares no empiezan por la fecha de referencia: primero el sitio y la cifra.

Nada se envía solo: el paquete propone, David decide.
"""
from __future__ import annotations

import argparse
import csv
import glob
import gzip
import json
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DOCS = RAIZ / "docs"
PAQ = DOCS / "prensa" / "paquetes"
HOY = date.today()
AYER = HOY - timedelta(days=1)
AHORA = datetime.now(timezone.utc).replace(microsecond=0)

sys.path.insert(0, str(RAIZ / "scripts"))
from hallazgos_prensa import PROVINCIAS, MESES, f1, fecha_larga, fecha_dia  # noqa: E402

ERA5_DIR = RAIZ / "archivo" / "era5"
DESDE = 1940
INICIO_TENDENCIA = 1970          # las tendencias se calculan 1970-último año completo (como Climate Central)
NORMAL = (1991, 2020)
FUENTE = "ERA5 (Copernicus/ECMWF) vía Open-Meteo Archive, CC BY 4.0 · cálculo propio de calentamientoglobal.es"
LIMITES_BASE = [
    "Reanálisis ERA5 en la celda (~25 km) de cada capital, no la estación de AEMET: los valores absolutos pueden diferir unas décimas; la tendencia es la robusta.",
    "ERA5 se consolida con unos seis días de retraso: el dato «en curso» llega hasta el último día disponible, no hasta ayer.",
    f"Tendencia lineal {INICIO_TENDENCIA}-{HOY.year - 1}; el año en curso no entra en la tendencia.",
]

AEMET_LARGAS = PAQ / "aemet_estaciones_largas.json"   # mensuales oficiales de AEMET, una estación por capital
MIN_ANIOS_AEMET = 40                                  # años completos exigidos dentro de 1970-último

# Qué paquetes se publican y, si no, por qué (lo lee la sala de prensa)
NO_PUBLICABLE = {
    "primera_helada": "Fecha de la primera helada en la celda del reanálisis: la celda hiela mucho menos que la estación de AEMET (Burgos: 33 días de helada al año frente a 69). Pendiente de rehacer con datos diarios de AEMET.",
    "noches_tropicales": "Noches tropicales en la celda del reanálisis: difieren de la estación de AEMET hasta seis veces (Granada: 60 al año frente a 10). Pendiente de rehacer con datos diarios de AEMET.",
    "dias_30": "Días de 30 °C en la celda del reanálisis: difieren de la estación de AEMET (Almería: 4 al año frente a 72).",
    "heladas": "Días de helada en la celda del reanálisis: se publica en su lugar el paquete de heladas con los datos de AEMET.",
    "lluvia_extrema": "Días de lluvia intensa en la celda del reanálisis: una media de celda no representa el chubasco local y la tendencia nacional no es clara.",
}

ESTACIONES = {
    "primavera": ([3, 4, 5], "primavera"), "verano": ([6, 7, 8], "verano"),
    "otono": ([9, 10, 11], "otoño"), "invierno": ([12, 1, 2], "invierno"),
}
ARTICULO = {"primavera": "La", "verano": "El", "otono": "El", "invierno": "El"}


# ----------------------------------------------------------------------------
# utilidades
# ----------------------------------------------------------------------------
def leer(p: Path):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def tendencia(xs, ys):
    """Pendiente por año, ordenada en el origen y r² de la recta de mínimos cuadrados."""
    pares = [(x, y) for x, y in zip(xs, ys) if y is not None]
    n = len(pares)
    if n < 10:
        return None
    mx = sum(x for x, _ in pares) / n
    my = sum(y for _, y in pares) / n
    sxx = sum((x - mx) ** 2 for x, _ in pares)
    sxy = sum((x - mx) * (y - my) for x, y in pares)
    syy = sum((y - my) ** 2 for _, y in pares)
    if sxx == 0:
        return None
    b = sxy / sxx
    a = my - b * mx
    r2 = (sxy * sxy) / (sxx * syy) if syy > 0 else 0.0
    return {"pendiente": b, "origen": a, "r2": r2, "n": n}


def signo(v, dec=1):
    return ("+" if v >= 0 else "−") + f1(abs(round(v, dec)))


def ordinal(n: int) -> str:
    return f"{n}.º"


# ----------------------------------------------------------------------------
# descarga y agregados por año
# ----------------------------------------------------------------------------
def cargar_serie(cod: str) -> dict | None:
    """Serie diaria de la capital desde archivo/era5/NN/: el histórico comprimido (modelo era5)
    más los CSV anuales posteriores. Devuelve el mismo formato que el 'daily' de Open-Meteo."""
    d = ERA5_DIR / cod
    hist = d / "hasta_2025_era5.csv.gz"
    if not hist.exists():
        hist = d / "hasta_2025.csv.gz"
    if not hist.exists():
        return None
    filas = {}
    with gzip.open(hist, "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            filas[r["fecha"]] = r
    for p in sorted(glob.glob(str(d / "[12][0-9][0-9][0-9].csv"))):
        with open(p, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                filas[r["fecha"]] = r

    def num(v):
        try:
            return float(v) if v not in ("", None) else None
        except ValueError:
            return None

    fechas = sorted(filas)
    return {"time": fechas, "temperature_2m_max": [num(filas[f]["tmax"]) for f in fechas],
            "temperature_2m_min": [num(filas[f]["tmin"]) for f in fechas], "precipitation_sum": [num(filas[f]["lluvia"]) for f in fechas]}


def normales_doy(fechas, tmed):
    """Normal 1991-2020 por día del año (1-366), suavizada ±7 días."""
    acum = {}
    for f, v in zip(fechas, tmed):
        if v is None:
            continue
        y = int(f[:4])
        if NORMAL[0] <= y <= NORMAL[1]:
            d = date.fromisoformat(f).timetuple().tm_yday
            acum.setdefault(d, []).append(v)
    bruto = {d: sum(v) / len(v) for d, v in acum.items()}
    suave = {}
    for d in range(1, 367):
        vals = [bruto[((d - 1 + k) % 366) + 1] for k in range(-7, 8) if ((d - 1 + k) % 366) + 1 in bruto]
        suave[d] = sum(vals) / len(vals) if vals else None
    return suave


def agregar(d: dict) -> dict:
    """De la serie diaria a agregados por año (y por estación)."""
    fechas, tx, tn, pp = d["time"], d["temperature_2m_max"], d["temperature_2m_min"], d["precipitation_sum"]
    tmed = [None if (a is None or b is None) else (a + b) / 2 for a, b in zip(tx, tn)]
    normal = normales_doy(fechas, tmed)
    anios: dict[int, dict] = {}

    def A(y):
        if y not in anios:
            anios[y] = {"dias": 0, "t": 0.0, "nt20": 0, "nt25": 0, "d30": 0, "d35": 0, "helada": 0, "ll": 0.0, "ll20": 0, "llmax": 0.0,
                        "primera_helada": None, "ultima_helada": None, "primer_30": None, "ultimo_30": None, "hasta": None,
                        "est": {k: {"dias": 0, "t": 0.0, "sobre_normal": 0, "ll": 0.0} for k in ESTACIONES}}
        return anios[y]

    for i, f in enumerate(fechas):
        if tx[i] is None or tn[i] is None:
            continue
        y, m = int(f[:4]), int(f[5:7])
        a = A(y)
        a["dias"] += 1
        a["hasta"] = f
        a["t"] += tmed[i]
        p = pp[i] or 0.0
        a["ll"] += p
        a["llmax"] = max(a["llmax"], p)
        if p >= 20:
            a["ll20"] += 1
        if tn[i] >= 20:
            a["nt20"] += 1
        if tn[i] >= 25:
            a["nt25"] += 1
        if tx[i] >= 30:
            a["d30"] += 1
            if a["primer_30"] is None:
                a["primer_30"] = f
            a["ultimo_30"] = f
        if tx[i] >= 35:
            a["d35"] += 1
        if tn[i] <= 0:
            a["helada"] += 1
            # primera helada del otoño-invierno (a partir del 1 de julio) y última de la primavera (antes del 1 de julio)
            if m >= 7 and a["primera_helada"] is None:
                a["primera_helada"] = f
            if m < 7:
                a["ultima_helada"] = f
        # estación (el invierno de diciembre se asigna al año siguiente: invierno 2026 = dic 2025 + ene-feb 2026)
        for k, (meses, _) in ESTACIONES.items():
            if m in meses:
                ya = A(y + 1) if (k == "invierno" and m == 12) else a
                e = ya["est"][k]
                e["dias"] += 1
                e["t"] += tmed[i]
                e["ll"] += p
                doy = date.fromisoformat(f).timetuple().tm_yday
                if normal.get(doy) is not None and tmed[i] > normal[doy]:
                    e["sobre_normal"] += 1
    # medias
    out = {}
    for y, a in sorted(anios.items()):
        est = {}
        for k, e in a["est"].items():
            completo = e["dias"] >= 85
            est[k] = {"t": round(e["t"] / e["dias"], 2) if e["dias"] else None, "sobre_normal": e["sobre_normal"], "ll": round(e["ll"], 1),
                      "dias": e["dias"], "completo": completo}
        out[y] = {"dias": a["dias"], "completo": a["dias"] >= 360, "hasta": a["hasta"], "t": round(a["t"] / a["dias"], 2) if a["dias"] else None,
                  "nt20": a["nt20"], "nt25": a["nt25"], "d30": a["d30"], "d35": a["d35"], "helada": a["helada"],
                  "ll": round(a["ll"], 1), "ll20": a["ll20"], "llmax": round(a["llmax"], 1),
                  "primera_helada": a["primera_helada"], "ultima_helada": a["ultima_helada"],
                  "primer_30": a["primer_30"], "ultimo_30": a["ultimo_30"], "est": est}
    return out


# ----------------------------------------------------------------------------
# paquetes
# ----------------------------------------------------------------------------
def doy(f):
    return date.fromisoformat(f).timetuple().tm_yday if f else None


def serie_anual(agg: dict, clave, desde=INICIO_TENDENCIA, hasta=None, solo_completos=True):
    hasta = hasta or (HOY.year - 1)
    xs, ys = [], []
    for y in range(desde, hasta + 1):
        a = agg.get(y) or agg.get(str(y))
        if not a:
            continue
        if solo_completos and not a["completo"]:
            continue
        v = clave(a)
        xs.append(y)
        ys.append(v)
    return xs, ys


def paquete_estacion(nombre_est: str):
    meses, etiqueta = ESTACIONES[nombre_est]
    if nombre_est == "otono":
        ventana = [9, 10, 11, 12]
    elif nombre_est == "invierno":
        ventana = [12, 1, 2, 3]
    elif nombre_est == "primavera":
        ventana = [3, 4, 5, 6]
    else:
        ventana = [6, 7, 8, 9]
    # el invierno "del año Y" termina en feb de Y; su último año completo es HOY.year si ya pasó febrero
    ult = HOY.year - 1
    if nombre_est == "invierno" and HOY.month >= 3:
        ult = HOY.year
    elif nombre_est == "primavera" and HOY.month >= 6:
        ult = HOY.year
    elif nombre_est == "verano" and HOY.month >= 9:
        ult = HOY.year
    elif nombre_est == "otono" and HOY.month == 12:
        ult = HOY.year

    def calc(agg, cap):
        xs, ys = serie_anual(agg, lambda a: a["est"][nombre_est]["t"] if a["est"][nombre_est]["completo"] else None, hasta=ult, solo_completos=False)
        xs2, ys2 = serie_anual(agg, lambda a: a["est"][nombre_est]["sobre_normal"] if a["est"][nombre_est]["completo"] else None, hasta=ult, solo_completos=False)
        t = tendencia(xs, ys)
        t2 = tendencia(xs2, ys2)
        if not t:
            return None
        n_anios = ult - INICIO_TENDENCIA
        delta = t["pendiente"] * n_anios
        delta_sn = t2["pendiente"] * n_anios if t2 else None
        # el año en curso, si la estación ya ha empezado
        actual = (agg.get(HOY.year) or {}).get("est", {}).get(nombre_est)
        ult_dato = (agg.get(HOY.year) or {}).get("hasta")
        ultimos = [y for y, v in zip(xs, ys) if v is not None][-10:]
        media_ult10 = sum(v for y, v in zip(xs, ys) if y in ultimos) / max(1, len(ultimos))
        ini = [v for y, v in zip(xs, ys) if INICIO_TENDENCIA <= y < INICIO_TENDENCIA + 10 and v is not None]
        media_ini = sum(ini) / max(1, len(ini))
        # ranking del último completo
        orden = sorted([(v, y) for y, v in zip(xs, ys) if v is not None], reverse=True)
        puesto_ult = next((i + 1 for i, (v, y) in enumerate(orden) if y == ult), None)
        return {"delta": round(delta, 2), "pendiente_decada": round(t["pendiente"] * 10, 2), "r2": round(t["r2"], 2),
                "dias_sobre_normal_delta": round(delta_sn, 1) if delta_sn is not None else None,
                "media_1970s": round(media_ini, 2), "media_ult10": round(media_ult10, 2),
                "mas_calido": {"anio": orden[0][1], "t": round(orden[0][0], 2)} if orden else None,
                "mas_frio": {"anio": orden[-1][1], "t": round(orden[-1][0], 2)} if orden else None,
                "ultimo": {"anio": ult, "t": (agg.get(ult) or {}).get("est", {}).get(nombre_est, {}).get("t"), "puesto": puesto_ult, "de": len(orden)},
                "en_curso": {"anio": HOY.year, "t": actual.get("t"), "dias": actual.get("dias"), "sobre_normal": actual.get("sobre_normal"), "hasta": ult_dato} if actual and actual.get("dias") else None,
                "serie": [(y, v, sn) for y, v, sn in zip(xs, ys, ys2)]}

    def textos(cap, prov, r):
        d = r["delta"]
        art = ARTICULO[nombre_est]
        fem = art == "La"
        tit = f"{art} {etiqueta} se ha calentado {f1(abs(d))} °C en {cap} desde {INICIO_TENDENCIA}" if d > 0 else f"{art} {etiqueta} en {cap} no se ha calentado desde {INICIO_TENDENCIA} ({signo(d)} °C)"
        dato = f"tendencia {signo(d)} °C entre {INICIO_TENDENCIA} y {ult} ({signo(r['pendiente_decada'])} °C por década) · media {INICIO_TENDENCIA}-{INICIO_TENDENCIA + 9}: {f1(r['media_1970s'])} °C · últimos diez: {f1(r['media_ult10'])} °C"
        ctx = []
        if r["dias_sobre_normal_delta"] is not None and r["dias_sobre_normal_delta"] > 0:
            ctx.append(f"Hoy hay {int(round(r['dias_sobre_normal_delta']))} días más de {etiqueta} por encima de lo normal que en {INICIO_TENDENCIA}.")
        if r["mas_calido"]:
            ctx.append(f"{art} {etiqueta} más cálid{'a' if fem else 'o'} de la serie: {r['mas_calido']['anio']} ({f1(r['mas_calido']['t'])} °C); {'la' if fem else 'el'} más frí{'a' if fem else 'o'}: {r['mas_frio']['anio']} ({f1(r['mas_frio']['t'])} °C).")
        if r["ultimo"]["puesto"]:
            ctx.append(f"{art} {etiqueta} de {ult} fue {'la' if fem else 'el'} {ordinal(r['ultimo']['puesto'])} más cálid{'a' if fem else 'o'} de {r['ultimo']['de']} desde {INICIO_TENDENCIA}.")
        if r["en_curso"] and r["en_curso"]["t"] is not None:
            ctx.append(f"{art} {etiqueta} de {HOY.year}, hasta el {fecha_dia(r['en_curso']['hasta']) if r['en_curso'].get('hasta') else 'último dato'} ({r['en_curso']['dias']} días): {f1(r['en_curso']['t'])} °C de media, con {r['en_curso']['sobre_normal']} días por encima de lo normal.")
        return tit, dato, ctx

    return {"id": nombre_est, "titulo": f"{ARTICULO[nombre_est]} {etiqueta} se calienta", "ventana": ventana, "unidad": "°C", "etiqueta_serie": f"temperatura media del {etiqueta} (°C)", "ult": ult,
            "calc": calc, "textos": textos, "clave_ranking": "delta", "ranking_desc": True,
            "metodo": f"Temperatura media diaria ((máxima + mínima)/2) de ERA5 en la celda de cada capital, promediada por {etiqueta} meteorológico ({', '.join(MESES[m - 1] for m in meses)}); "
                      f"tendencia lineal {INICIO_TENDENCIA}-{ult}. «Días por encima de lo normal»: días con media superior a la normal 1991-2020 de ese día del año (suavizada ±7 días).",
            "por_que_importa": {"otono": "Un otoño más cálido alarga la temporada de incendios y de alergias, retrasa las primeras lluvias útiles, prolonga la demanda de refrigeración y reduce el enfriamiento del mar que frena las DANA.",
                                "verano": "Veranos más cálidos elevan la mortalidad por calor, la demanda eléctrica, el estrés hídrico y el riesgo de incendio.",
                                "invierno": "Inviernos más suaves reducen la nieve y la reserva hídrica de primavera, alteran plagas y cultivos y adelantan la floración.",
                                "primavera": "Primaveras más cálidas adelantan la floración y el polen, alargan la temporada de riego y funden antes la nieve."}[nombre_est]}


def paquete_contador(id_, titulo, clave, etiqueta_serie, unidad, ventana, titular_fn, metodo, por_que, ranking_desc=True, minimo_media=None):
    def calc(agg, cap):
        xs, ys = serie_anual(agg, lambda a: a[clave])
        t = tendencia(xs, ys)
        if not t:
            return None
        n_anios = (HOY.year - 1) - INICIO_TENDENCIA
        vals_ini = [v for y, v in zip(xs, ys) if y < INICIO_TENDENCIA + 10]
        vals_fin = [v for y, v in zip(xs, ys) if y > HOY.year - 11]
        m_ini = sum(vals_ini) / max(1, len(vals_ini))
        m_fin = sum(vals_fin) / max(1, len(vals_fin))
        if minimo_media is not None and max(m_ini, m_fin) < minimo_media:
            return None
        orden = sorted([(v, y) for y, v in zip(xs, ys)], reverse=True)
        act = (agg.get(HOY.year) or {})
        return {"delta": round(t["pendiente"] * n_anios, 1), "pendiente_decada": round(t["pendiente"] * 10, 2), "r2": round(t["r2"], 2),
                "media_1970s": round(m_ini, 1), "media_ult10": round(m_fin, 1),
                "max": {"anio": orden[0][1], "v": orden[0][0]} if orden else None,
                "en_curso": {"anio": HOY.year, "v": act.get(clave), "dias": act.get("dias"), "hasta": act.get("hasta")} if act else None,
                "serie": [(y, v, None) for y, v in zip(xs, ys)]}

    def textos(cap, prov, r):
        tit, dato = titular_fn(cap, r)
        if abs(r["delta"]) < 1:
            tit = f"{cap}: sin cambio apreciable en {etiqueta_serie} desde {INICIO_TENDENCIA}"
        ctx = []
        if r["max"]:
            ctx.append(f"El año con más: {r['max']['anio']} ({int(r['max']['v'])}).")
        if r["en_curso"] and r["en_curso"]["v"] is not None:
            ctx.append(f"En {HOY.year}, hasta el {fecha_dia(r['en_curso']['hasta']) if r['en_curso'].get('hasta') else 'último dato'}: {int(r['en_curso']['v'])}.")
        ctx.append(f"Media {INICIO_TENDENCIA}-{INICIO_TENDENCIA + 9}: {f1(r['media_1970s'])} al año; últimos diez años: {f1(r['media_ult10'])}.")
        return tit, dato, ctx

    return {"id": id_, "titulo": titulo, "ventana": ventana, "unidad": unidad, "etiqueta_serie": etiqueta_serie, "calc": calc, "textos": textos,
            "clave_ranking": "delta", "ranking_desc": ranking_desc, "metodo": metodo, "por_que_importa": por_que}


def paquete_fecha(id_, titulo, clave, etiqueta_serie, ventana, titular_fn, metodo, por_que, minimo_anios=0.8, ranking_desc=True):
    """Paquetes de fecha (primera helada, último día de 30 °C…): la serie es el día del año."""
    def calc(agg, cap):
        xs, ys = serie_anual(agg, lambda a: doy(a[clave]))
        presentes = [v for v in ys if v is not None]
        if len(presentes) < minimo_anios * len(ys) or len(presentes) < 20:
            return None
        t = tendencia(xs, ys)
        if not t:
            return None
        n_anios = (HOY.year - 1) - INICIO_TENDENCIA
        vals_ini = [v for y, v in zip(xs, ys) if y < INICIO_TENDENCIA + 10 and v is not None]
        vals_fin = [v for y, v in zip(xs, ys) if y > HOY.year - 11 and v is not None]
        m_ini = sum(vals_ini) / max(1, len(vals_ini))
        m_fin = sum(vals_fin) / max(1, len(vals_fin))
        sin = [y for y, v in zip(xs, ys) if v is None]
        act = (agg.get(HOY.year) or {}).get(clave)
        return {"delta": round(t["pendiente"] * n_anios, 1), "pendiente_decada": round(t["pendiente"] * 10, 1), "r2": round(t["r2"], 2),
                "media_1970s": round(m_ini), "media_ult10": round(m_fin), "anios_sin": sin, "en_curso": act,
                "serie": [(y, v, None) for y, v in zip(xs, ys)]}

    def textos(cap, prov, r):
        tit, dato = titular_fn(cap, r)
        if abs(r["delta"]) < 3:
            tit = f"{titulo.split(' llega')[0]} en {cap} llega en fechas parecidas a las de {INICIO_TENDENCIA} ({signo(r['delta'], 0)} días)"
        ctx = []
        if r["anios_sin"]:
            ctx.append(f"Años sin el fenómeno: {', '.join(str(y) for y in r['anios_sin'][-8:])}.")
        if r["en_curso"]:
            ctx.append(f"En {HOY.year}: {fecha_dia(r['en_curso'])}.")
        return tit, dato, ctx

    return {"id": id_, "titulo": titulo, "ventana": ventana, "unidad": "día del año", "etiqueta_serie": etiqueta_serie, "calc": calc, "textos": textos,
            "clave_ranking": "delta", "ranking_desc": ranking_desc, "metodo": metodo, "por_que_importa": por_que}



# ----------------------------------------------------------------------------
# AEMET: estaciones de serie larga (valores mensuales oficiales)
# ----------------------------------------------------------------------------
PLURAL = {"otono": "otoños", "verano": "veranos", "invierno": "inviernos", "primavera": "primaveras"}


def cargar_aemet() -> dict:
    try:
        return leer(AEMET_LARGAS)["estaciones"]
    except Exception:
        return {}


NOMBRE_ESTACION = {"STA.CRUZ DE TENERIFE": "Santa Cruz de Tenerife", "ALACANT/ALICANTE": "Alicante", "VALÈNCIA": "València",
                   "MADRID, RETIRO": "Madrid-Retiro", "LEÓN, VIRGEN DEL CAMINO": "León-Virgen del Camino",
                   "HUESCA, AEROPUERTO": "Huesca aeropuerto", "LOGROÑO, AEROPUERTO": "Logroño aeropuerto", "ZARAGOZA, AEROPUERTO": "Zaragoza aeropuerto"}


def nombre_estacion(e: dict) -> str:
    """«BURGOS AEROPUERTO» → «Burgos aeropuerto»"""
    n = (e.get("estacion") or "").strip()
    if n in NOMBRE_ESTACION:
        return NOMBRE_ESTACION[n]
    t = n.lower().title()
    for a, b in ((" De ", " de "), (" Del ", " del "), ("Aeropuerto", "aeropuerto"), (" La ", " la ")):
        t = t.replace(a, b)
    return t


def calc_estacion_aemet(est: dict, nombre_est: str, ult: int):
    """Mismo cálculo que el de ERA5, sobre la media estacional de la estación de AEMET."""
    anios = est.get("anios") or {}
    xs, ys = [], []
    for y in range(INICIO_TENDENCIA, ult + 1):
        v = (anios.get(str(y)) or {}).get(nombre_est)
        if v is not None:
            xs.append(y)
            ys.append(float(v))
    if len(xs) < MIN_ANIOS_AEMET or xs[0] > INICIO_TENDENCIA + 3:
        return None
    t = tendencia(xs, ys)
    if not t:
        return None
    # el cambio se mide en el periodo que de verdad cubre la serie (Ourense empieza en 1972: antes se extrapolaba a 1970)
    n_anios = ult - xs[0]
    ini = [v for y, v in zip(xs, ys) if y < INICIO_TENDENCIA + 10]
    fin = [v for y, v in zip(xs, ys) if y > ult - 10]
    orden = sorted(zip(ys, xs), reverse=True)
    puesto_ult = next((i + 1 for i, (v, y) in enumerate(orden) if y == ult), None)
    return {"delta": round(t["pendiente"] * n_anios, 2), "pendiente_decada": round(t["pendiente"] * 10, 2), "r2": round(t["r2"], 2),
            "media_1970s": round(sum(ini) / max(1, len(ini)), 2), "media_ult10": round(sum(fin) / max(1, len(fin)), 2),
            "mas_calido": {"anio": orden[0][1], "t": round(orden[0][0], 2)}, "mas_frio": {"anio": orden[-1][1], "t": round(orden[-1][0], 2)},
            "ultimo": {"anio": ult, "t": (anios.get(str(ult)) or {}).get(nombre_est), "puesto": puesto_ult, "de": len(orden)},
            "anios_con_dato": len(xs), "primer_anio": xs[0],
            "serie": [(y, v, None) for y, v in zip(xs, ys)]}


def titular_estacion(cap: str, cod: str, nombre_est: str, d: float, fuente: str) -> str:
    """Tres construcciones que rotan por provincia para que la portada no repita la misma frase.
    Ninguna empieza por la fecha: primero el sitio y la cifra."""
    etiqueta = ESTACIONES[nombre_est][1]
    art = ARTICULO[nombre_est]
    fem = art == "La"
    o = "a" if fem else "o"
    pl = PLURAL[nombre_est]
    seg = ", según AEMET" if fuente == "AEMET" else ", según el reanálisis ERA5"
    if abs(d) < 0.25:
        return f"{art} {etiqueta} de {cap} apenas ha cambiado desde principios de los setenta ({signo(d)} °C){seg}"
    if d < 0:
        return f"{art} {etiqueta} de {cap} es hoy {f1(abs(d))} °C más fresc{o} que a principios de los setenta{seg}"
    k = int(cod) % 3
    if k == 0:
        return f"{art} {etiqueta} es hoy {f1(d)} °C más cálid{o} en {cap} que a principios de los setenta{seg}"
    if k == 1:
        return f"{cap} tiene {pl} {f1(d)} °C más cálid{o}s que a principios de los setenta{seg}"
    return f"{pl.capitalize()} {f1(d)} °C más cálid{o}s: así ha cambiado {art.lower()} {etiqueta} en {cap} en medio siglo{seg}"


def paquete_heladas_aemet():
    """Días de helada al año en las estaciones de AEMET de serie larga (nt_00 de los valores mensuales)."""
    ult = HOY.year - 1

    def filas(aemet: dict, capitales: dict):
        out = []
        for cod, est in sorted(aemet.items()):
            if cod not in capitales:
                continue
            anios = est.get("anios") or {}
            xs, ys = [], []
            for y in range(INICIO_TENDENCIA, ult + 1):
                v = (anios.get(str(y)) or {}).get("helada")
                if v is not None:
                    xs.append(y)
                    ys.append(int(v))
            if len(xs) < MIN_ANIOS_AEMET or xs[0] > INICIO_TENDENCIA + 3:
                continue
            ini = [v for y, v in zip(xs, ys) if y < INICIO_TENDENCIA + 10]
            fin = [v for y, v in zip(xs, ys) if y > ult - 10]
            m_ini, m_fin = sum(ini) / max(1, len(ini)), sum(fin) / max(1, len(fin))
            if max(m_ini, m_fin) < 5:
                continue
            t = tendencia(xs, ys)
            if not t:
                continue
            cap, prov, slug = capitales[cod]
            delta = round(t["pendiente"] * (ult - xs[0]), 1)
            ne = nombre_estacion(est)
            # Auditoría 17-10-2026 (verificación independiente): Córdoba salía con «7 días de helada menos» cuando
            # la media de los setenta (14,1) y la de los últimos diez años (13,4) apenas cambian (r² = 0,04).
            # La tendencia solo se publica si explica algo (r² ≥ 0,1) y cuadra con las medias por década.
            dif_medias = m_fin - m_ini
            solida = t["r2"] >= 0.1 and dif_medias * delta > 0 and abs(dif_medias) >= 0.5 * abs(delta)
            if delta <= -1:
                n = int(round(abs(delta)))
                tit = (f"{cap} tiene hoy {n} días de helada menos al año que a principios de los setenta, según AEMET" if int(cod) % 2 == 0 else
                       f"La helada pierde terreno en {cap}: {n} días menos al año que a principios de los setenta, según AEMET")
            elif delta >= 3:
                tit = f"{cap} hiela hoy {int(round(delta))} días más al año que a principios de los setenta, según AEMET"
            else:
                tit = f"{cap} hiela casi lo mismo que a principios de los setenta ({signo(delta, 0)} días al año), según AEMET"
            orden = sorted(zip(ys, xs))
            out.append({"cod": cod, "capital": cap, "provincia": prov, "slug": slug, "titular": tit,
                        "dato": f"de {f1(m_ini)} días de helada al año en los setenta a {f1(m_fin)} en los últimos diez · tendencia {signo(delta, 0)} días ({signo(t['pendiente'] * 10)} por década) · estación de AEMET {ne}",
                        "contexto": [f"El año con menos heladas de la serie: {orden[0][1]} ({orden[0][0]} días); con más: {orden[-1][1]} ({orden[-1][0]} días).",
                                     f"{len(xs)} años con dato completo entre {xs[0]} y {xs[-1]}."],
                        "delta": delta, "pendiente_decada": round(t["pendiente"] * 10, 2), "r2": round(t["r2"], 2),
                        "media_1970s": round(m_ini, 1), "media_ult10": round(m_fin, 1), "fuente_fila": "AEMET", "estacion": ne,
                        "indicativo": est.get("indicativo"), "serie": [(y, v, None) for y, v in zip(xs, ys)],
                        **({} if solida else {"discrepa": f"La tendencia de {cap} no se sostiene: r² {t['r2']:.2f}, medias por década {f1(m_ini)} → {f1(m_fin)} días frente a una tendencia de {signo(delta, 0)}"})})
        return out

    return {"id": "heladas_aemet", "titulo": "La helada pierde terreno", "ventana": [10, 11, 12, 1, 2, 3], "unidad": "días",
            "etiqueta_serie": "días de helada al año (mínima ≤ 0 °C)", "filas": filas, "clave_ranking": "delta", "ranking_desc": False,
            "fuente": "AEMET · valores climatológicos mensuales de la estación (días con mínima ≤ 0 °C)",
            "metodo": f"Suma anual de los días con temperatura mínima ≤ 0 °C que publica AEMET en los valores mensuales de la estación de referencia de cada capital; "
                      f"tendencia lineal {INICIO_TENDENCIA}-{ult}. Solo estaciones con al menos {MIN_ANIOS_AEMET} años completos y capitales con 5 o más heladas al año.",
            "por_que_importa": "Menos heladas alteran el reposo invernal de los frutales, alargan la temporada de plagas y reducen la reserva de nieve y de agua de primavera.",
            "limites": ["Una estación por capital (en muchos casos el aeropuerto, a las afueras): no es la ciudad entera.",
                        f"Tendencia lineal {INICIO_TENDENCIA}-{ult}; el año en curso no entra.",
                        "Solo las capitales cuya estación de AEMET tiene serie larga descargada en el observatorio (21 de 52)."]}

def fecha_desde_doy(d, anio=2025):
    return fecha_dia((date(anio, 1, 1) + timedelta(days=int(round(d)) - 1)).isoformat())


PAQUETES = [
    paquete_estacion("otono"),
    paquete_fecha("primera_helada", "La primera helada llega más tarde", "primera_helada", "día de la primera helada (mínima ≤ 0 °C)", [10, 11, 12],
                  lambda cap, r: (f"La primera helada llega en {cap} {int(round(abs(r['delta'])))} días {'más tarde' if r['delta'] > 0 else 'antes'} que en {INICIO_TENDENCIA}",
                                  f"de media, hacia el {fecha_desde_doy(r['media_1970s'])} en los años 70 y hacia el {fecha_desde_doy(r['media_ult10'])} en los últimos diez · tendencia {signo(r['delta'], 0)} días ({signo(r['pendiente_decada'])} por década)"),
                  "Primer día a partir del 1 de julio con mínima ≤ 0 °C en la celda ERA5 de la capital; tendencia lineal sobre el día del año. Solo capitales con helada en al menos el 80 % de los años.",
                  "Una primera helada más tardía alarga la temporada de cultivo y de plagas, retrasa el fin del polen y desplaza el calendario agrícola."),
    paquete_contador("noches_tropicales", "Más noches tropicales", "nt20", "noches con mínima ≥ 20 °C al año", "noches", [6, 7, 8, 9, 10],
                     lambda cap, r: (f"{cap} tiene {int(abs(r['delta']))} noches tropicales más al año que en {INICIO_TENDENCIA}" if r["delta"] > 0 else f"{cap} no ha ganado noches tropicales desde {INICIO_TENDENCIA}",
                                     f"de {f1(r['media_1970s'])} noches al año en los 70 a {f1(r['media_ult10'])} en los últimos diez · tendencia {signo(r['delta'], 0)} ({signo(r['pendiente_decada'])} por década)"),
                     "Noches con mínima ≥ 20 °C por año natural en la celda ERA5 de la capital; tendencia lineal.",
                     "Las noches tropicales impiden el descanso y la recuperación del cuerpo: son el principal factor de mortalidad por calor en las ciudades.", minimo_media=5),
    paquete_contador("dias_30", "Más días de 30 °C", "d30", "días con máxima ≥ 30 °C al año", "días", [5, 6, 7, 8, 9],
                     lambda cap, r: (f"{cap} suma {int(abs(r['delta']))} días de 30 °C más al año que en {INICIO_TENDENCIA}" if r["delta"] > 0 else f"{cap} no ha ganado días de 30 °C desde {INICIO_TENDENCIA}",
                                     f"de {f1(r['media_1970s'])} días al año en los 70 a {f1(r['media_ult10'])} en los últimos diez · tendencia {signo(r['delta'], 0)} ({signo(r['pendiente_decada'])} por década)"),
                     "Días con máxima ≥ 30 °C por año natural en la celda ERA5 de la capital; tendencia lineal.",
                     "Más días de calor alargan la temporada de riesgo para la salud, el consumo eléctrico y el estrés de cultivos y bosques.", minimo_media=5),
    paquete_contador("heladas", "Menos días de helada", "helada", "días con mínima ≤ 0 °C al año", "días", [11, 12, 1, 2, 3],
                     lambda cap, r: (f"{cap} tiene {int(abs(r['delta']))} días de helada menos al año que en {INICIO_TENDENCIA}" if r["delta"] < 0 else f"{cap} no ha perdido días de helada desde {INICIO_TENDENCIA}",
                                     f"de {f1(r['media_1970s'])} días al año en los 70 a {f1(r['media_ult10'])} en los últimos diez · tendencia {signo(r['delta'], 0)} ({signo(r['pendiente_decada'])} por década)"),
                     "Días con mínima ≤ 0 °C por año natural en la celda ERA5 de la capital; tendencia lineal.",
                     "Menos heladas alteran el reposo invernal de los frutales, favorecen plagas y reducen la reserva de nieve.", ranking_desc=False, minimo_media=5),
    paquete_contador("lluvia_extrema", "Lluvia más concentrada", "ll20", "días con 20 mm o más al año", "días", [9, 10, 11, 12, 1, 2, 3, 4],
                     lambda cap, r: (f"{cap} tiene {f1(abs(r['delta']))} {'día' if abs(r['delta']) == 1 else 'días'} de lluvia intensa (≥ 20 mm) {'más' if r['delta'] > 0 else 'menos'} al año que en {INICIO_TENDENCIA}",
                                     f"de {f1(r['media_1970s'])} días al año en los 70 a {f1(r['media_ult10'])} en los últimos diez · tendencia {signo(r['delta'])} ({signo(r['pendiente_decada'])} por década)"),
                     "Días con precipitación ≥ 20 mm por año natural en la celda ERA5 de la capital; tendencia lineal. La lluvia de ERA5 es una media de celda: subestima los chubascos locales.",
                     "La lluvia que cae en pocos días intensos erosiona, inunda y se aprovecha peor que la misma cantidad repartida.", minimo_media=1),
    paquete_estacion("verano"),
    paquete_estacion("invierno"),
    paquete_estacion("primavera"),
]


# ----------------------------------------------------------------------------
# gráfico y csv por capital
# ----------------------------------------------------------------------------
def grafico(plt, out: Path, paq: dict, cap: str, r: dict, fuente_txt: str = "ERA5 (Copernicus) vía Open-Meteo"):
    serie = [(y, v) for y, v, _ in r["serie"] if v is not None]
    if len(serie) < 10:
        return False
    xs = [y for y, _ in serie]
    ys = [v for _, v in serie]
    t = tendencia(xs, ys)
    fig, ax = plt.subplots(figsize=(12, 6.75), dpi=100)
    fig.patch.set_facecolor("#ffffff")
    if paq["unidad"] == "día del año":
        ax.plot(xs, ys, color="#0071b8", lw=1.6, marker="o", ms=3)
        import matplotlib.ticker as mt
        ax.yaxis.set_major_formatter(mt.FuncFormatter(lambda v, _: fecha_desde_doy(v) if 1 <= v <= 366 else ""))
    elif paq["unidad"] == "°C":
        media = sum(ys) / len(ys)
        ax.bar(xs, [v - media for v in ys], bottom=media, color=["#cc4416" if v >= media else "#0071b8" for v in ys], width=0.8)
        ax.axhline(media, color="#6e6e73", lw=0.8)
    else:
        ax.bar(xs, ys, color="#cc4416" if paq["ranking_desc"] else "#0071b8", width=0.8)
    if t:
        ax.plot([xs[0], xs[-1]], [t["origen"] + t["pendiente"] * xs[0], t["origen"] + t["pendiente"] * xs[-1]], color="#1d1408", lw=2, ls="--",
                label=f"tendencia: {signo(r['delta'], 1 if paq['unidad'] == '°C' else 0)} {paq['unidad'] if paq['unidad'] != 'día del año' else 'días'} desde {INICIO_TENDENCIA}")
    ax.set_title(f"{cap} · {paq['etiqueta_serie']}", loc="left", fontsize=15, fontweight="bold", color="#1d1408")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#eeeeee")
    ax.legend(frameon=False, fontsize=10, loc="upper left")
    ax.text(1, -0.1, f"Observatorio climático · calentamientoglobal.es · {fuente_txt} · CC BY 4.0", transform=ax.transAxes, ha="right", fontsize=9, color="#6e6e73")
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return True


def csv_capital(out: Path, paq: dict, r: dict):
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if paq["id"] in ESTACIONES and r.get("fuente_fila") == "AEMET":
            w.writerow(["anio", "temperatura_media_C_AEMET"])
        elif paq["id"] in ESTACIONES:
            w.writerow(["anio", "temperatura_media_C", "dias_sobre_normal"])
        elif paq["unidad"] == "día del año":
            w.writerow(["anio", "dia_del_anio", "fecha"])
        else:
            w.writerow(["anio", paq["etiqueta_serie"].replace(" ", "_")])
        for y, v, sn in r["serie"]:
            if paq["id"] in ESTACIONES and r.get("fuente_fila") == "AEMET":
                w.writerow([y, v])
            elif paq["id"] in ESTACIONES:
                w.writerow([y, v, sn])
            elif paq["unidad"] == "día del año":
                w.writerow([y, v, (date(y, 1, 1) + timedelta(days=int(v) - 1)).isoformat() if v else ""])
            else:
                w.writerow([y, v])


# ----------------------------------------------------------------------------
# principal
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo", help="código de provincia para probar")
    ap.add_argument("--sin-graficos", action="store_true")
    ap.add_argument("--todos", action="store_true", help="gráficos de todos los paquetes, no solo los de temporada")
    args = ap.parse_args()

    PAQ.mkdir(parents=True, exist_ok=True)
    (PAQ / "series").mkdir(exist_ok=True)
    coords = {c["provincia"]: c for c in leer(DOCS / "viento.json")["capitales"]}
    capitales = {}
    for cod, (prov, slug) in sorted(PROVINCIAS.items()):
        if args.solo and cod != args.solo:
            continue
        try:
            cap = leer(DOCS / "archivo" / f"{cod}.json")["capital"]
        except Exception:
            cap = prov
        capitales[cod] = (cap, prov, slug)

    # 1 · series → agregados
    series = {}
    hasta = {}
    errores = []
    for cod, (cap, prov, slug) in capitales.items():
        p = PAQ / "series" / f"{cod}.json"
        try:
            d = cargar_serie(cod)
            if d is None:
                raise FileNotFoundError(f"archivo/era5/{cod}: sin serie")
            agg = agregar(d)
            series[cod] = agg
            hasta[cod] = d["time"][-1]
            c = coords.get(prov, {})
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"cod": cod, "capital": cap, "provincia": prov, "lat": c.get("lat"), "lon": c.get("lon"), "fuente": FUENTE, "desde": DESDE,
                           "hasta": d["time"][-1], "generado": AHORA.strftime("%Y-%m-%dT%H:%M:%SZ"), "anios": agg}, f, ensure_ascii=False)
            print(f"{cap}: {len(d['time'])} días ({d['time'][0]} → {d['time'][-1]}) → {len(agg)} años", flush=True)
        except Exception as e:  # noqa: BLE001
            errores.append(f"{cod} {cap}: {type(e).__name__}: {e}")
            if p.exists():
                series[cod] = {int(k): v for k, v in leer(p)["anios"].items()}
                hasta[cod] = leer(p).get("hasta")

    # 2 · paquetes
    plt = None
    if not args.sin_graficos:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt  # noqa: F811
        except Exception:
            plt = None
    aemet = cargar_aemet()
    if not aemet:
        errores.append("aemet_estaciones_largas.json: no se pudo leer; los paquetes de estación salen solo con ERA5")
    # Auditoría 17-10-2026 (segunda pasada): las series de estación de AEMET no están homogeneizadas. Ciudad Real
    # salta unos 2 °C entre 1979 y 1981 (cambio de emplazamiento) y daba «+3,1 °C en otoño» frente a +2,1 °C del
    # reanálisis. Comprobación cruzada: si la tendencia de la estación y la de la celda ERA5 que la cubre se separan
    # más de TOL_HOMOG en una estación del año, esa fila no se publica; si se separan en dos o más estaciones del año,
    # la estación entera se considera no homogénea y tampoco cuenta para las heladas.
    TOL_HOMOG = 0.7
    discrepa: dict[str, dict] = {}
    for paq in PAQUETES:
        if paq["id"] not in ESTACIONES:
            continue
        for cod, agg in series.items():
            if cod not in aemet:
                continue
            try:
                r_e = paq["calc"](agg, capitales[cod][0])
                r_a = calc_estacion_aemet(aemet[cod], paq["id"], paq["ult"])
            except Exception:  # noqa: BLE001
                continue
            if r_e and r_a and abs(r_a["delta"] - r_e["delta"]) > TOL_HOMOG:
                discrepa.setdefault(cod, {})[paq["id"]] = round(r_a["delta"] - r_e["delta"], 2)
    no_homogeneas = {cod for cod, d in discrepa.items() if len(d) >= 2}
    indice = []
    for paq in PAQUETES + [paquete_heladas_aemet()]:
        de_temporada = HOY.month in paq["ventana"]
        publicable = paq["id"] not in NO_PUBLICABLE
        es_estacion = paq["id"] in ESTACIONES
        filas = []
        if "filas" in paq:                       # paquete que sale entero de AEMET
            for fila in paq["filas"](aemet, capitales):
                r = fila
                if (de_temporada or args.todos) and plt:
                    (PAQ / paq["id"]).mkdir(exist_ok=True)
                    if grafico(plt, PAQ / paq["id"] / f"{fila['cod']}.png", paq, fila["capital"], r, f"AEMET, estación {fila['estacion']}"):
                        fila["grafico"] = f"prensa/paquetes/{paq['id']}/{fila['cod']}.png"
                    csv_capital(PAQ / paq["id"] / f"{fila['cod']}.csv", paq, r)
                    fila["csv"] = f"prensa/paquetes/{paq['id']}/{fila['cod']}.csv"
                fila.pop("serie", None)
                if fila["cod"] in no_homogeneas:
                    fila["discrepa"] = (f"La estación de AEMET de {fila['capital']} no cuadra con el reanálisis en "
                                        f"{len(discrepa[fila['cod']])} estaciones del año (posible cambio de emplazamiento)")
                filas.append(fila)
        else:
            for cod, agg in series.items():
                cap, prov, slug = capitales[cod]
                try:
                    r = paq["calc"](agg, cap)
                except Exception as e:  # noqa: BLE001
                    errores.append(f"{paq['id']} {cap}: {type(e).__name__}: {e}")
                    r = None
                if not r:
                    continue
                fuente_graf = "ERA5 (Copernicus) vía Open-Meteo"
                if es_estacion:
                    ra = calc_estacion_aemet(aemet[cod], paq["id"], paq["ult"]) if cod in aemet else None
                    era5 = {k: r[k] for k in ("delta", "pendiente_decada", "media_1970s", "media_ult10", "dias_sobre_normal_delta")}
                    if ra:
                        ne = nombre_estacion(aemet[cod])
                        r = {**ra, "en_curso": r.get("en_curso"), "dias_sobre_normal_delta": r.get("dias_sobre_normal_delta"),
                             "fuente_fila": "AEMET", "estacion": ne, "indicativo": aemet[cod].get("indicativo"), "era5": era5}
                        fuente_graf = f"AEMET, estación {ne}"
                    else:
                        r = {**r, "fuente_fila": "ERA5", "era5": era5}
                    tit = titular_estacion(cap, cod, paq["id"], r["delta"], r["fuente_fila"])
                    et = ESTACIONES[paq["id"]][1]
                    art = ARTICULO[paq["id"]]
                    fem = art == "La"
                    o = "a" if fem else "o"
                    dato = (f"tendencia {signo(r['delta'])} °C entre {r.get('primer_anio') or INICIO_TENDENCIA} y {paq['ult']} ({signo(r['pendiente_decada'])} °C por década) · "
                            f"media de los años setenta {f1(r['media_1970s'])} °C · últimos diez {f1(r['media_ult10'])} °C · "
                            + (f"estación de AEMET {r['estacion']}" if r["fuente_fila"] == "AEMET" else "reanálisis ERA5 en la celda de la capital"))
                    ctx = []
                    if r.get("mas_calido"):
                        ctx.append(f"{art} {et} más cálid{o} de la serie: {r['mas_calido']['anio']} ({f1(r['mas_calido']['t'])} °C); {'la' if fem else 'el'} más frí{o}: {r['mas_frio']['anio']} ({f1(r['mas_frio']['t'])} °C).")
                    if r.get("ultimo", {}).get("puesto"):
                        ctx.append(f"{art} {et} de {paq['ult']} fue {'la' if fem else 'el'} {ordinal(r['ultimo']['puesto'])} más cálid{o} de los {r['ultimo']['de']} con dato desde {INICIO_TENDENCIA}.")
                    if r["fuente_fila"] == "AEMET":
                        ctx.append(f"En la celda del reanálisis ERA5 que cubre {cap} la tendencia es {signo(era5['delta'])} °C: la cifra de la estación es la que vale para la ciudad.")
                    fila = {"cod": cod, "capital": cap, "provincia": prov, "slug": slug, "titular": tit, "dato": dato, "contexto": ctx,
                            **{k: v for k, v in r.items() if k != "serie"}}
                    if r["fuente_fila"] == "AEMET" and not (r.get("r2", 1) >= 0.1 and (r["media_ult10"] - r["media_1970s"]) * r["delta"] > 0):
                        fila["discrepa"] = f"La tendencia de la estación no se sostiene (r² {r.get('r2', 0):.2f} o no cuadra con las medias por década)"
                    if r["fuente_fila"] == "AEMET" and (cod in no_homogeneas or abs(r["delta"] - era5["delta"]) > TOL_HOMOG):
                        fila["discrepa"] = (f"La estación de AEMET ({signo(r['delta'])} °C) y la celda del reanálisis ({signo(era5['delta'])} °C) "
                                            f"se separan {f1(abs(r['delta'] - era5['delta']))} °C" + (" y no cuadran en otras estaciones del año" if cod in no_homogeneas else "")
                                            + ": posible cambio de emplazamiento de la estación")
                else:
                    tit, dato, ctx = paq["textos"](cap, prov, r)
                    fila = {"cod": cod, "capital": cap, "provincia": prov, "slug": slug, "titular": tit, "dato": dato, "contexto": ctx,
                            "fuente_fila": "ERA5", **{k: v for k, v in r.items() if k != "serie"}}
                if (de_temporada or args.todos) and plt and publicable:
                    (PAQ / paq["id"]).mkdir(exist_ok=True)
                    if grafico(plt, PAQ / paq["id"] / f"{cod}.png", paq, cap, r, fuente_graf):
                        fila["grafico"] = f"prensa/paquetes/{paq['id']}/{cod}.png"
                    csv_capital(PAQ / paq["id"] / f"{cod}.csv", paq, r)
                    fila["csv"] = f"prensa/paquetes/{paq['id']}/{cod}.csv"
                filas.append(fila)
        if not filas:
            continue
        filas.sort(key=lambda x: x[paq["clave_ranking"]], reverse=paq["ranking_desc"])
        deltas = [x["delta"] for x in filas]
        media = sum(deltas) / len(deltas)
        n_sube = sum(1 for d in deltas if d > 0)
        n_baja = sum(1 for d in deltas if d < 0)
        u = paq["unidad"]
        mediana = sorted(deltas)[len(deltas) // 2]
        for x in filas:
            # una celda de reanálisis que cambia mucho más que el resto se marca para cotejar
            celda_rara = bool(u == "°C" and x.get("fuente_fila") != "AEMET" and mediana > 0 and x["delta"] > 1.6 * mediana)
            x["revisar"] = celda_rara or bool(x.get("discrepa"))
            x["limites"] = (([f"COMPROBAR con la estación de AEMET: la celda ERA5 de {x['capital']} muestra un cambio muy superior al del resto de capitales ({signo(x['delta'])} °C frente a una mediana de {signo(mediana)} °C); puede estar afectada por la orografía."] if celda_rara else [])
                            + ([f"COMPROBAR: {x['discrepa']}. No se publica hasta revisar el historial de la estación."] if x.get("discrepa") else []))
        # lo que se publica: filas sin nada que revisar
        aemet_filas = [x for x in filas if x.get("fuente_fila") == "AEMET" and not x["revisar"]]
        donde_mas = sorted(aemet_filas, key=lambda x: x["delta"], reverse=paq["ranking_desc"])[:5]
        if paq["id"] == "heladas_aemet":
            deltas = [x["delta"] for x in aemet_filas] or deltas
            media = sum(deltas) / len(deltas)
            n_baja = sum(1 for d in deltas if d < 0)
        if es_estacion:
            et = ESTACIONES[paq["id"]][1]
            art = ARTICULO[paq["id"]]
            o = "a" if art == "La" else "o"
            m_era5 = sum(x["era5"]["delta"] for x in filas) / len(filas)
            m_aemet = sum(x["delta"] for x in aemet_filas) / len(aemet_filas) if aemet_filas else None
            n_sube_e = sum(1 for x in filas if x["era5"]["delta"] > 0)
            hallazgos = [f"{art} {et} es hoy {f1(m_era5)} °C más cálid{o} que a principios de los setenta en las capitales de provincia españolas, según el reanálisis ERA5",
                         (f"Las {len(aemet_filas)} capitales con estación de AEMET de serie larga y coherente con el reanálisis: {signo(m_aemet)} °C de media; "
                          f"las 52 en el reanálisis ERA5: {signo(m_era5)} °C. Sube en {n_sube_e} de las {len(filas)} capitales." if m_aemet is not None else
                          f"Sube en {n_sube_e} de las {len(filas)} capitales (reanálisis ERA5).")]
            dsn = [x["dias_sobre_normal_delta"] for x in filas if x.get("dias_sobre_normal_delta") is not None]
            if dsn:
                hallazgos.append(f"En el reanálisis, cada {et} tiene hoy {int(round(sum(dsn) / len(dsn)))} días más por encima de lo normal que a principios de los setenta.")
            media = m_era5
        elif paq["id"] == "heladas_aemet":
            hallazgos = [f"La helada pierde terreno: {n_baja} de las {len(aemet_filas)} capitales con estación de AEMET de serie larga y homogénea hielan hoy menos que a principios de los setenta",
                         f"De media, {f1(abs(media))} días de helada menos al año (estaciones de AEMET, tendencia {INICIO_TENDENCIA}-{HOY.year - 1})."]
        elif u == "día del año":
            hallazgos = [f"La primera helada llega {int(round(media))} días más tarde de media en {n_sube} de las {len(filas)} capitales con heladas (reanálisis)."]
        else:
            hallazgos = [f"{paq['titulo']}: cambio medio {signo(media)} {u} al año en {len(filas)} capitales (reanálisis)."]
        salida = {"id": paq["id"], "titulo": paq["titulo"], "generado": AHORA.strftime("%Y-%m-%dT%H:%M:%SZ"), "de_temporada": de_temporada, "ventana": paq["ventana"],
                  "publicable": publicable, "motivo_no_publicable": NO_PUBLICABLE.get(paq["id"]),
                  "periodo": f"{INICIO_TENDENCIA}-{HOY.year - 1}",
                  "fuente": paq.get("fuente") or ("AEMET (estaciones de serie larga, valores mensuales) y ERA5 (Copernicus/ECMWF) vía Open-Meteo, CC BY 4.0 · cálculo propio de calentamientoglobal.es" if es_estacion else FUENTE),
                  "metodo": (paq["metodo"] + (f" Las capitales con estación de AEMET de serie larga (al menos {MIN_ANIOS_AEMET} {et}s completos desde {INICIO_TENDENCIA}) "
                                               f"usan la media estacional de los valores mensuales oficiales de AEMET; el resto, el reanálisis." if es_estacion else "")),
                  "limites": paq.get("limites") or LIMITES_BASE,
                  "por_que_importa": paq["por_que_importa"], "hallazgos": hallazgos, "n_capitales": len(filas), "n_aemet": len(aemet_filas),
                  "media_delta": round(media, 2), "mediana_delta": round(mediana, 2), "n_revisar": sum(1 for x in filas if x["revisar"]),
                  "donde_mas": [{"cod": x["cod"], "capital": x["capital"], "slug": x["slug"], "delta": x["delta"], "estacion": x.get("estacion")} for x in donde_mas],
                  "unidad": u, "etiqueta_serie": paq["etiqueta_serie"], "capitales": filas,
                  "licencia": "Cálculo propio de CalentamientoGlobal.es · CC BY 4.0 · los datos de origen (AEMET, Copernicus) conservan su licencia",
                  "contacto": "contacto@calentamientoglobal.es"}
        with open(PAQ / f"{paq['id']}.json", "w", encoding="utf-8") as f:
            json.dump(salida, f, ensure_ascii=False, indent=1)
        indice.append({"id": paq["id"], "titulo": paq["titulo"], "de_temporada": de_temporada, "publicable": publicable, "ventana": paq["ventana"],
                       "n_capitales": len(filas), "n_aemet": len(aemet_filas), "hallazgo": hallazgos[0], "media_delta": round(media, 2), "unidad": u,
                       "con_graficos": bool((de_temporada or args.todos) and plt and publicable)})
        print(f"{paq['id']:18s} {'TEMPORADA' if de_temporada else '         '} {'PUBLICA' if publicable else 'interno'} {len(filas):2d} cap ({len(aemet_filas)} AEMET) · {hallazgos[0]}")

    with open(PAQ / "index.json", "w", encoding="utf-8") as f:
        json.dump({"generado": AHORA.strftime("%Y-%m-%dT%H:%M:%SZ"), "fecha": HOY.isoformat(), "paquetes": indice, "errores": errores}, f, ensure_ascii=False, indent=1)
    for e in errores:
        print("  !", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
