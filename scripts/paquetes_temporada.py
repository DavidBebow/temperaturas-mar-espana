#!/usr/bin/env python3
"""
Paquetes de temporada · Observatorio climático (calentamientoglobal.es).

El «Climate Matters» español: cada semana, un paquete con datos por capital desde 1940
sobre la temporada en curso, listo para que un medio lo publique con su ciudad:
titulares, cifras, gráfico por capital, CSV, texto de método y límites.

Series: ERA5 (Copernicus/ECMWF) vía Open-Meteo Archive, celda de cada capital, diario
desde 1940 (las mismas coordenadas y modelo que docs/archivo/NN.json). Se descarga en
cada ejecución (52 peticiones) y se reduce a agregados anuales que sí se guardan.

Escribe (docs/prensa/paquetes/):
  series/NN.json            agregados por año y capital (estaciones, noches, días de calor, heladas, lluvia)
  <paquete>.json            el paquete: hallazgos nacionales, ranking, texto por capital, método
  <paquete>/NN.png|.csv     gráfico (sin el año en curso: estable) y serie por capital
  index.json                paquetes disponibles, cuáles son de temporada ahora, titulares

Nada se envía solo: el paquete propone, David decide.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
import urllib.parse
import urllib.request
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

OPEN_METEO = "https://archive-api.open-meteo.com/v1/archive"
DESDE = 1940
INICIO_TENDENCIA = 1970          # las tendencias se calculan 1970-último año completo (como Climate Central)
NORMAL = (1991, 2020)
FUENTE = "ERA5 (Copernicus/ECMWF) vía Open-Meteo Archive, CC BY 4.0 · cálculo propio de calentamientoglobal.es"
LIMITES_BASE = [
    "Reanálisis ERA5 en la celda (~25 km) de cada capital, no la estación de AEMET: los valores absolutos pueden diferir unas décimas; la tendencia es la robusta.",
    f"Tendencia lineal {INICIO_TENDENCIA}-{HOY.year - 1}; el año en curso no entra en la tendencia.",
]

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
def descargar(lat, lon, reintentos=4):
    q = urllib.parse.urlencode({
        "latitude": f"{lat:.4f}", "longitude": f"{lon:.4f}", "start_date": f"{DESDE}-01-01", "end_date": AYER.isoformat(),
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum", "timezone": "Europe/Madrid", "models": "era5",
    })
    for i in range(reintentos):
        try:
            with urllib.request.urlopen(f"{OPEN_METEO}?{q}", timeout=120) as r:
                return json.load(r)["daily"]
        except Exception as e:  # noqa: BLE001
            if i == reintentos - 1:
                raise
            time.sleep(10 * (i + 1))


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
                        "primera_helada": None, "ultima_helada": None, "primer_30": None, "ultimo_30": None,
                        "est": {k: {"dias": 0, "t": 0.0, "sobre_normal": 0, "ll": 0.0} for k in ESTACIONES}}
        return anios[y]

    for i, f in enumerate(fechas):
        if tx[i] is None or tn[i] is None:
            continue
        y, m = int(f[:4]), int(f[5:7])
        a = A(y)
        a["dias"] += 1
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
        out[y] = {"dias": a["dias"], "completo": a["dias"] >= 360, "t": round(a["t"] / a["dias"], 2) if a["dias"] else None,
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
                "en_curso": {"anio": HOY.year, "t": actual.get("t"), "dias": actual.get("dias"), "sobre_normal": actual.get("sobre_normal")} if actual and actual.get("dias") else None,
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
            ctx.append(f"{art} {etiqueta} de {HOY.year}, hasta ayer ({r['en_curso']['dias']} días): {f1(r['en_curso']['t'])} °C de media, con {r['en_curso']['sobre_normal']} días por encima de lo normal.")
        return tit, dato, ctx

    return {"id": nombre_est, "titulo": f"{ARTICULO[nombre_est]} {etiqueta} se calienta", "ventana": ventana, "unidad": "°C", "etiqueta_serie": f"temperatura media del {etiqueta} (°C)",
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
                "en_curso": {"anio": HOY.year, "v": act.get(clave), "dias": act.get("dias")} if act else None,
                "serie": [(y, v, None) for y, v in zip(xs, ys)]}

    def textos(cap, prov, r):
        tit, dato = titular_fn(cap, r)
        ctx = []
        if r["max"]:
            ctx.append(f"El año con más: {r['max']['anio']} ({int(r['max']['v'])}).")
        if r["en_curso"] and r["en_curso"]["v"] is not None:
            ctx.append(f"En {HOY.year}, hasta ayer: {int(r['en_curso']['v'])}.")
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
        ctx = []
        if r["anios_sin"]:
            ctx.append(f"Años sin el fenómeno: {', '.join(str(y) for y in r['anios_sin'][-8:])}.")
        if r["en_curso"]:
            ctx.append(f"En {HOY.year}: {fecha_dia(r['en_curso'])}.")
        return tit, dato, ctx

    return {"id": id_, "titulo": titulo, "ventana": ventana, "unidad": "día del año", "etiqueta_serie": etiqueta_serie, "calc": calc, "textos": textos,
            "clave_ranking": "delta", "ranking_desc": ranking_desc, "metodo": metodo, "por_que_importa": por_que}


def fecha_desde_doy(d, anio=2025):
    return fecha_dia((date(anio, 1, 1) + timedelta(days=int(round(d)) - 1)).isoformat())


PAQUETES = [
    paquete_estacion("otono"),
    paquete_fecha("primera_helada", "La primera helada llega más tarde", "primera_helada", "día de la primera helada (mínima ≤ 0 °C)", [10, 11, 12],
                  lambda cap, r: (f"La primera helada llega en {cap} {int(abs(r['delta']))} días {'más tarde' if r['delta'] > 0 else 'antes'} que en {INICIO_TENDENCIA}",
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
                     lambda cap, r: (f"{cap} tiene {f1(abs(r['delta']))} días de lluvia intensa (≥ 20 mm) {'más' if r['delta'] > 0 else 'menos'} al año que en {INICIO_TENDENCIA}",
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
def grafico(plt, out: Path, paq: dict, cap: str, r: dict):
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
    ax.text(1, -0.1, "Observatorio climático · calentamientoglobal.es · ERA5 (Copernicus) vía Open-Meteo · CC BY 4.0", transform=ax.transAxes, ha="right", fontsize=9, color="#6e6e73")
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return True


def csv_capital(out: Path, paq: dict, r: dict):
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if paq["id"] in ESTACIONES:
            w.writerow(["anio", "temperatura_media_C", "dias_sobre_normal"])
        elif paq["unidad"] == "día del año":
            w.writerow(["anio", "dia_del_anio", "fecha"])
        else:
            w.writerow(["anio", paq["etiqueta_serie"].replace(" ", "_")])
        for y, v, sn in r["serie"]:
            if paq["id"] in ESTACIONES:
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
    ap.add_argument("--sin-descarga", action="store_true", help="usar los agregados ya guardados en series/")
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
    errores = []
    for cod, (cap, prov, slug) in capitales.items():
        p = PAQ / "series" / f"{cod}.json"
        if args.sin_descarga and p.exists():
            series[cod] = {int(k): v for k, v in leer(p)["anios"].items()}
            continue
        c = coords.get(prov)
        if not c:
            errores.append(f"{cod} {prov}: sin coordenadas")
            continue
        try:
            d = descargar(c["lat"], c["lon"])
            agg = agregar(d)
            series[cod] = agg
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"cod": cod, "capital": cap, "provincia": prov, "lat": c["lat"], "lon": c["lon"], "fuente": FUENTE, "desde": DESDE,
                           "hasta": AYER.isoformat(), "generado": AHORA.strftime("%Y-%m-%dT%H:%M:%SZ"), "anios": agg}, f, ensure_ascii=False)
            time.sleep(0.6)
        except Exception as e:  # noqa: BLE001
            errores.append(f"{cod} {cap}: {type(e).__name__}: {e}")
            if p.exists():
                series[cod] = {int(k): v for k, v in leer(p)["anios"].items()}

    # 2 · paquetes
    plt = None
    if not args.sin_graficos:
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt  # noqa: F811
        except Exception:
            plt = None
    indice = []
    for paq in PAQUETES:
        de_temporada = HOY.month in paq["ventana"]
        filas = []
        for cod, agg in series.items():
            cap, prov, slug = capitales[cod]
            try:
                r = paq["calc"](agg, cap)
            except Exception as e:  # noqa: BLE001
                errores.append(f"{paq['id']} {cap}: {type(e).__name__}: {e}")
                r = None
            if not r:
                continue
            tit, dato, ctx = paq["textos"](cap, prov, r)
            fila = {"cod": cod, "capital": cap, "provincia": prov, "slug": slug, "titular": tit, "dato": dato, "contexto": ctx,
                    **{k: v for k, v in r.items() if k != "serie"}}
            if (de_temporada or args.todos) and plt:
                (PAQ / paq["id"]).mkdir(exist_ok=True)
                if grafico(plt, PAQ / paq["id"] / f"{cod}.png", paq, cap, r):
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
        top = filas[:5]
        u = paq["unidad"]
        if paq["id"] in ESTACIONES:
            et = ESTACIONES[paq["id"]][1]
            hallazgos = [f"{ARTICULO[paq['id']]} {et} se ha calentado en {n_sube} de las {len(filas)} capitales desde {INICIO_TENDENCIA}: {signo(media)} °C de media.",
                         f"Donde más: " + ", ".join(f"{x['capital']} ({signo(x['delta'])} °C)" for x in top) + ".",
                         f"{sum(1 for x in filas if x['delta'] >= 2)} capitales se han calentado 2 °C o más."]
            dsn = [x["dias_sobre_normal_delta"] for x in filas if x.get("dias_sobre_normal_delta") is not None]
            if dsn:
                hallazgos.append(f"De media, cada {et} tiene hoy {int(round(sum(dsn) / len(dsn)))} días más por encima de lo normal que en {INICIO_TENDENCIA}; en {sum(1 for d in dsn if d >= 14)} capitales son dos semanas o más.")
        elif u == "día del año":
            hallazgos = [f"La primera helada llega más tarde en {n_sube} de las {len(filas)} capitales con heladas: {int(round(media))} días de media desde {INICIO_TENDENCIA}.",
                         "Donde más se retrasa: " + ", ".join(f"{x['capital']} ({signo(x['delta'], 0)} días)" for x in top) + "."]
        else:
            if paq["ranking_desc"]:
                hallazgos = [f"{paq['titulo']}: suben en {n_sube} de {len(filas)} capitales; {signo(media, 0)} {u} al año de media desde {INICIO_TENDENCIA}.",
                             "Donde más: " + ", ".join(f"{x['capital']} ({signo(x['delta'], 0)})" for x in top) + "."]
            else:
                hallazgos = [f"{paq['titulo']}: bajan en {n_baja} de {len(filas)} capitales; {signo(media, 0)} {u} al año de media desde {INICIO_TENDENCIA}.",
                             "Donde más: " + ", ".join(f"{x['capital']} ({signo(x['delta'], 0)})" for x in top) + "."]
        salida = {"id": paq["id"], "titulo": paq["titulo"], "generado": AHORA.strftime("%Y-%m-%dT%H:%M:%SZ"), "de_temporada": de_temporada, "ventana": paq["ventana"],
                  "periodo": f"{INICIO_TENDENCIA}-{HOY.year - 1}", "fuente": FUENTE, "metodo": paq["metodo"], "limites": LIMITES_BASE,
                  "por_que_importa": paq["por_que_importa"], "hallazgos": hallazgos, "n_capitales": len(filas), "media_delta": round(media, 2),
                  "unidad": u, "etiqueta_serie": paq["etiqueta_serie"], "capitales": filas,
                  "licencia": "Cálculo propio de CalentamientoGlobal.es · CC BY 4.0 · ERA5 conserva la licencia de Copernicus",
                  "contacto": "contacto@calentamientoglobal.es"}
        with open(PAQ / f"{paq['id']}.json", "w", encoding="utf-8") as f:
            json.dump(salida, f, ensure_ascii=False, indent=1)
        indice.append({"id": paq["id"], "titulo": paq["titulo"], "de_temporada": de_temporada, "ventana": paq["ventana"], "n_capitales": len(filas),
                       "hallazgo": hallazgos[0], "media_delta": round(media, 2), "unidad": u, "con_graficos": bool((de_temporada or args.todos) and plt)})
        print(f"{paq['id']:18s} {'TEMPORADA' if de_temporada else '         '} {len(filas):2d} cap · {hallazgos[0]}")

    with open(PAQ / "index.json", "w", encoding="utf-8") as f:
        json.dump({"generado": AHORA.strftime("%Y-%m-%dT%H:%M:%SZ"), "fecha": HOY.isoformat(), "paquetes": indice, "errores": errores}, f, ensure_ascii=False, indent=1)
    for e in errores:
        print("  !", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
