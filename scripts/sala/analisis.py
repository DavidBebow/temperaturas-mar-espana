"""Análisis: lo que solo sale escudriñando las series largas. Cifras medidas por AEMET y cálculo del observatorio.

Cuatro historias, cada una con su versión provincial cuando el dato es de una estación de la provincia:

1. calor_largo · Los días de 30 °C o más, 1961-1990 frente a 2011-2025, mes a mes, y 2026 (enero-agosto) frente a la
   serie completa de la estación. Fuente: valores mensuales de AEMET (`nt_30`, días con máxima de 30 °C o más) de
   archivo/aemet_mensual/mensuales.json.gz (bajados del API mensualesanuales; meses completos hasta agosto de 2026).
   Solo estaciones con 25 de los 30 años de 1961-1990 y 13 de los 15 de 2011-2025 completos (abril-octubre) y cuya
   subida de la máxima media de junio-septiembre no se separa más de 0,7 °C de la del reanálisis en la capital de su
   provincia: el reanálisis solo filtra estaciones con saltos (traslados, cambios de sensor); no se publica ninguna
   cifra suya.
2. otono_serie · Lo que lleva el otoño en cada pluviómetro de AEMET (docs/otonio_municipios.json, la misma estación)
   frente a todos los otoños de su serie hasta la misma fecha (archivo/otonio/crudo_otonios.json.gz, diarios de AEMET
   1991-2025). Récord húmedo: 2026 hasta la hora del último dato supera el día completo de todos los otoños anteriores
   (≥ 15 con el tramo completo). Récord seco: 2026 queda por debajo de todos los otoños anteriores hasta la víspera
   (≥ 25 otoños). Las dos comparaciones son conservadoras: el dato de 2026 juega siempre con desventaja.
3. torrencial · Días de 100 mm o más en otoño (septiembre-noviembre), 1991-2007 frente a 2009-2025, en las
   estaciones con al menos 33 de los 35 otoños completos (la red crece de 150 a 770 estaciones: contar en todas
   fabricaría una tendencia). Y cuántos de los días de 100 mm o más coincidieron con una DANA del catálogo del
   observatorio.
4. dana_largo · Días con DANA sobre España por mes, 1961-1990 frente a 1996-2025, según el catálogo del observatorio
   (detector propio con el reanálisis NCEP/NCAR). Es un análisis, no una medida en un lugar, y así se dice. 2026 queda
   fuera: desde el 18 de marzo de 2026 el catálogo usa el análisis de ECMWF, sin calibrar con NCEP.
"""
from __future__ import annotations

import collections
import csv
import datetime
import gzip
import io
import json
import math
import re
import statistics as st

SECCION = "analisis"
PAG_CALOR = "https://calentamientoglobal.es/observatorio-climatico/"
PAG_LLUVIA = "https://calentamientoglobal.es/lluvias-en-espana/"
PAG_DANA = "https://calentamientoglobal.es/dana/"

P1, P2 = range(1961, 1991), range(2011, 2026)
MESES_CALOR = (4, 5, 6, 7, 8, 9, 10)
NOMBRE_MES = {4: "abril", 5: "mayo", 6: "junio", 7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre"}
CORTO = {4: "Abr", 5: "May", 6: "Jun", 7: "Jul", 8: "Ago", 9: "Sep", 10: "Oct"}
FUENTE_M = "AEMET OpenData (valores climatológicos mensuales); cálculo del observatorio"
FUENTE_D = "AEMET OpenData (valores climatológicos diarios); cálculo del observatorio"
FUENTE_DANA = "Catálogo de DANAs del observatorio (detector propio con el reanálisis NCEP/NCAR)"
MED = "#E3A487"
MED_LL = "#8FB0DA"


# ============================================================================ ayudas
def _nombre(R, ide, crudo=None):
    rec = getattr(_nombre, "_rec", None)
    if rec is None:
        d = R.leer(R.DOCS / "records" / "hoy.json", {}) or {}
        rec = _nombre._rec = {e["id"]: e.get("n") for e in d.get("estaciones") or [] if e.get("id") and e.get("n")}
    n = rec.get(ide) or crudo or ide
    if n.isupper():
        n = n.title()
    return _limpio(n)


def _limpio(n):
    n = re.sub(r"/\s+", "/", n or "").strip()
    n = re.sub(r"^Sta\.\s*(\w)", lambda m: "Santa " + m.group(1).upper(), n, flags=re.I)
    n = re.sub(r"\((\w)", lambda m: "(" + m.group(1).upper(), n)
    return re.sub(r",(?=\S)", ", ", n)


def _prov(R, nombre_prov):
    c = R.H.cod_provincia(nombre_prov) if nombre_prov else None
    return c if c in R.PROV else None


def _media(xs):
    xs = [x for x in xs if x is not None]
    return st.mean(xs) if xs else None


def _veces(a, b):
    """«X veces»: cociente redondeado hacia abajo a una décima, para que «más de X veces» sea siempre cierto."""
    return math.floor(a / b * 10) / 10 if b else None


def _barras_pares(R, filas, nombre, titulo, pie, etiquetas, c1, c2, l1, l2, unidad=""):
    """Barras agrupadas: dos valores por categoría (antes / ahora)."""
    W, Hh, ml, mr, mt, mb = 640, 290, 40, 16, 34, 34
    mx = max(max(a, b) for _, a, b in filas) or 1
    tope = max(5, math.ceil(mx / 5) * 5)
    Y = lambda v: mt + (1 - v / tope) * (Hh - mt - mb)
    bw = (W - ml - mr) / len(filas)
    s = []
    for t in range(0, tope + 1, max(5, tope // 4 // 5 * 5 or 5)):
        s.append(f'<line x1="{ml}" x2="{W - mr}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="{R.RAYA}" stroke-width="1"></line>')
        s.append(R._t(ml - 6, Y(t) + 4, str(t), 11, R.GRIS, "end"))
    for i, (k, a, b) in enumerate(filas):
        x0 = ml + i * bw + 6
        w = (bw - 16) / 2
        s.append(f'<rect x="{x0:.1f}" y="{Y(a):.1f}" width="{w:.1f}" height="{max(0.0, Y(0) - Y(a)):.1f}" fill="{c1}"></rect>')
        s.append(f'<rect x="{x0 + w + 4:.1f}" y="{Y(b):.1f}" width="{w:.1f}" height="{max(0.0, Y(0) - Y(b)):.1f}" fill="{c2}"></rect>')
        s.append(R._t(x0 + w + 2, Hh - mb + 16, etiquetas[k], 11, R.GRIS, "middle"))
        s.append(R._t(x0 + w + 4 + w / 2, Y(b) - 5, R.f1(b), 10, R.TINTA, "middle", 700))
    s.append(f'<rect x="{ml}" y="8" width="12" height="12" fill="{c1}"></rect>')
    s.append(R._t(ml + 18, 18, l1, 12, R.GRIS))
    s.append(f'<rect x="{ml + 150}" y="8" width="12" height="12" fill="{c2}"></rect>')
    s.append(R._t(ml + 168, 18, l2, 12, R.GRIS))
    svg = R._svg(W, Hh, titulo, s)
    return R.guardar_grafico(nombre, svg, [(etiquetas[k], a, b) for k, a, b in filas], ["categoria", l1, l2], titulo,
                             [{"t": "banda", "c": c1, "l": l1}, {"t": "banda", "c": c2, "l": l2}], pie)


def _barras_serie(R, serie, destacar, nombre, titulo, pie, color, claro, fmt=None):
    """Una barra por año; la del año destacado, en color."""
    fmt = fmt or R.f1
    W, Hh, ml, mr, mt, mb = 640, 260, 44, 12, 22, 30
    mx = max(v for _, v in serie) or 1
    paso = 10 ** max(0, len(str(int(mx))) - 1)
    tope = math.ceil(mx / paso) * paso
    Y = lambda v: mt + (1 - v / tope) * (Hh - mt - mb)
    bw = (W - ml - mr) / len(serie)
    s = []
    for t in (0, tope / 2, tope):
        s.append(f'<line x1="{ml}" x2="{W - mr}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="{R.RAYA}" stroke-width="1"></line>')
        s.append(R._t(ml - 6, Y(t) + 4, fmt(t), 11, R.GRIS, "end"))
    for i, (a, v) in enumerate(serie):
        x0 = ml + i * bw + 1
        dest = a in destacar
        s.append(f'<rect x="{x0:.1f}" y="{Y(v):.1f}" width="{max(1.0, bw - 2):.1f}" height="{max(0.0, Y(0) - Y(v)):.1f}" '
                 f'fill="{color if dest else claro}"></rect>')
        if dest:
            s.append(R._t(x0 + bw / 2, Y(v) - 5, fmt(v), 11, R.TINTA, "middle", 700))
        if i == 0 or i == len(serie) - 1 or (isinstance(a, int) and a % 10 == 0):
            s.append(R._t(x0 + bw / 2, Hh - mb + 16, str(a), 10, R.GRIS, "middle"))
    svg = R._svg(W, Hh, titulo, s)
    return R.guardar_grafico(nombre, svg, list(serie), ["anio", "valor"], titulo, [], pie)


# ============================================================================ 1. calor_largo
def _era5_jjas(R, cod):
    """Media de la máxima de junio-septiembre del reanálisis en la capital, por año (solo para filtrar estaciones)."""
    f = R.DOCS.parent / "archivo" / "era5" / cod / "hasta_2025.csv.gz"
    if not f.exists():
        return {}
    por = collections.defaultdict(list)
    for r in csv.DictReader(io.TextIOWrapper(gzip.open(f), encoding="utf-8")):
        if r.get("tmax") and r["fecha"][5:7] in ("06", "07", "08", "09"):
            por[int(r["fecha"][:4])].append(float(r["tmax"]))
    return {a: st.mean(v) for a, v in por.items() if len(v) >= 120}


def _mensuales(R):
    f = R.DOCS.parent / "archivo" / "aemet_mensual" / "mensuales.json.gz"
    if not f.exists():
        return None
    doc = getattr(_mensuales, "_doc", None)
    if doc is None:
        doc = _mensuales._doc = json.load(gzip.open(f, "rt", encoding="utf-8"))
    return doc


def _calor_estaciones(R):
    doc = _mensuales(R)
    if not doc:
        return [], None, 0
    campos = doc["campos"]
    i30, itx = campos.index("nt_30"), campos.index("tm_max")
    filas = []
    for ide, e in doc["estaciones"].items():
        m = e["meses"]
        cod = _prov(R, e.get("provincia"))
        if not cod:
            continue

        def val(a, mes, i):
            r = m.get(f"{a}-{mes:02d}")
            return r[i] if r else None

        def completos(P):  # años con los 12 meses con dato de días de 30 °C
            return [a for a in P if all(val(a, mes, i30) is not None for mes in range(1, 13))]
        a1, a2 = completos(P1), completos(P2)
        if len(a1) < 25 or len(a2) < 13:
            continue
        # control de homogeneidad con el reanálisis (no se publica)
        def jjas(P):
            xs = [st.mean([val(a, mes, itx) for mes in (6, 7, 8, 9)]) for a in P if all(val(a, mes, itx) is not None for mes in (6, 7, 8, 9))]
            return st.mean(xs) if len(xs) >= 10 else None
        E = _era5_jjas(R, cod)
        s1, s2 = jjas(P1), jjas(P2)
        e1, e2 = _media([E.get(a) for a in P1]), _media([E.get(a) for a in P2])
        if None in (s1, s2, e1, e2) or abs((s2 - s1) - (e2 - e1)) > 0.7:
            continue
        # medias sin redondear: se redondea solo al escribir
        meses = {mes: (st.mean(val(a, mes, i30) for a in a1), st.mean(val(a, mes, i30) for a in a2)) for mes in range(1, 13)}
        t1 = st.mean(sum(val(a, mes, i30) for mes in range(1, 13)) for a in a1)
        t2 = st.mean(sum(val(a, mes, i30) for mes in range(1, 13)) for a in a2)
        # 2026, enero-agosto, frente a todos los años completos desde el principio del archivo (1940)
        def ytd(a):
            vs = [val(a, mes, i30) for mes in range(1, 9)]
            return sum(vs) if all(v is not None for v in vs) else None
        serie = {a: ytd(a) for a in range(1940, 2026) if ytd(a) is not None}
        v26 = ytd(2026)
        rec26 = bool(v26 is not None and len(serie) >= 30 and all(v26 > v for v in serie.values()))
        pmax = max(serie.values()) if serie else None
        filas.append({"ide": ide, "nombre": _nombre(R, ide, e.get("nombre")), "cod": cod, "t1": t1, "t2": t2, "meses": meses,
                      "n1": len(a1), "n2": len(a2), "v26": v26, "rec26": rec26, "n_serie": len(serie),
                      "desde": min(serie) if serie else None, "prev_max": pmax,
                      "prev_anios": sorted(a for a, v in serie.items() if v == pmax) if serie else []})
    return filas, doc.get("descargado"), len(doc["estaciones"])


def _partes_calor(f):
    """Ganancia en la parte temprana (abril-junio) y tardía (septiembre-octubre) del calor, sin redondear."""
    temprano = sum(f["meses"][m][1] - f["meses"][m][0] for m in (4, 5, 6))
    tardio = sum(f["meses"][m][1] - f["meses"][m][0] for m in (9, 10))
    return temprano, tardio


def _coletilla(f):
    temprano, tardio = _partes_calor(f)
    if temprano >= 2 and tardio >= 1:
        return "el calor de verano llega antes y se va más tarde"
    if temprano >= 2:
        return "el calor de verano llega antes"
    if tardio >= 1:
        return "el calor de verano se va más tarde"
    return "más días de calor que en 1961-1990"


def _hechos_estacion_calor(R, f, id_, con_prov=True):
    n = f["nombre"]
    donde = f"{n} ({R.nprov(f['cod'])})" if con_prov else n
    gan = f["t2"] - f["t1"]
    hh = [R.hecho(f"{id_}", f"La estación de AEMET de {donde} registró de media {R.f1(f['t2'])} días al año con máxima de 30 °C o más "
                            f"entre 2011 y 2025, frente a {R.f1(f['t1'])} entre 1961 y 1990: {R.f1(gan)} días más al año.", FUENTE_M,
                  [R.f1(f["t2"]), R.f1(f["t1"]), R.f1(gan), "30 °C", "2011", "2025", "1961", "1990"], lugar=n,
                  liga=[R.f1(f["t2"]), R.f1(f["t1"]), R.f1(gan)])]
    fuera1 = sum(f["meses"][m][0] for m in range(1, 13) if m not in (7, 8))
    fuera2 = sum(f["meses"][m][1] for m in range(1, 13) if m not in (7, 8))
    partes, vals = [], []
    for mes in (5, 6, 9, 10):
        a, b = f["meses"][mes]
        if abs(b - a) >= 1:
            partes.append(f"en {NOMBRE_MES[mes]}, de {R.f1(a)} a {R.f1(b)}")
            vals += [R.f1(a), R.f1(b)]
    if fuera2 - fuera1 >= 1:
        hh.append(R.hecho(f"{id_}_meses", f"Fuera de julio y agosto, esos días pasan de {R.f1(fuera1)} a {R.f1(fuera2)} al año en {n}"
                                          + (": " + R.lista_y(partes) + "." if partes else "."), FUENTE_M,
                          [R.f1(fuera1), R.f1(fuera2)] + vals, lugar=n, liga=[R.f1(fuera1), R.f1(fuera2)]))
        pct_fuera = round(100 * (fuera2 - fuera1) / gan) if gan > 0 else None
        if pct_fuera is not None and 25 <= pct_fuera <= 100:
            hh.append(R.hecho(f"{id_}_pct", f"El {pct_fuera} % de los días de calor ganados en {n} cae fuera de julio y agosto.", FUENTE_M,
                              [f"{pct_fuera} %"], lugar=n))
    baja = [NOMBRE_MES[m] for m in (6, 9, 10) if f["meses"][m][1] - f["meses"][m][0] <= -0.5]
    if baja:
        hh.append(R.hecho(f"{id_}_baja", f"En {n} no todos los meses suben: en {R.lista_y(baja)} hay ahora menos días de 30 °C o más que en 1961-1990.",
                          FUENTE_M, ["30 °C", "1961", "1990"], lugar=n))
    if f["rec26"]:
        desde_t = "desde 1940" if f["desde"] == 1940 else f"de los {f['n_serie'] + 1} años completos de su serie, que empieza en {f['desde']}"
        ant = R.lista_y([str(a) for a in f["prev_anios"]])
        hh.append(R.hecho(f"{id_}_2026", f"Entre enero y agosto de 2026, la estación de AEMET de {donde} sumó {R.f1(f['v26'])} días con máxima "
                                         f"de 30 °C o más, la cifra más alta para esos meses {desde_t}; el máximo anterior era de "
                                         f"{R.f1(f['prev_max'])} días, en {ant}.",
                          FUENTE_M, [R.f1(f["v26"]), str(f["n_serie"] + 1), str(f["desde"]), R.f1(f["prev_max"])] + [str(a) for a in f["prev_anios"]],
                          lugar=n, liga=[R.f1(f["v26"])], superlativo=True, record=True))
    return hh


def g_calor_largo(R, D):
    filas, descargado, n_archivo = _calor_estaciones(R)
    if len(filas) < 3:
        return []
    filas.sort(key=lambda f: -(f["t2"] - f["t1"]))
    recs = [f for f in filas if f["rec26"]]
    # abre la estación que más ha ganado entre las que además baten en 2026 su récord (si hay); después, la que más ha ganado
    lider = recs[0] if recs else filas[0]
    segundo = next(f for f in filas if f is not lider)
    hechos = _hechos_estacion_calor(R, lider, "calor1")
    hechos += _hechos_estacion_calor(R, segundo, "calor2")[:1]
    n = len(filas)
    mas20 = sum(1 for f in filas if f["t2"] - f["t1"] >= 20)
    hechos.append(R.hecho("calor_red", f"El observatorio ha comparado {n} de las {n_archivo} estaciones de AEMET de su archivo mensual: las que tienen al "
                                       f"menos 25 de los 30 años de 1961-1990 y 13 de los 15 de 2011-2025 completos y no muestran saltos grandes de "
                                       f"medida. En todas hay más días de 30 °C o más que en 1961-1990"
                                       + (f", y en {mas20} la subida es de 20 días al año o más." if mas20 else "."),
                          FUENTE_M, [str(n), str(n_archivo), "25", "30", "13", "15", "30 °C", "1961", "1990", "2011", "2025"] + ([str(mas20), "20"] if mas20 else [])))
    if recs:
        nombres = R.lista_y([f"{f['nombre']} ({R.nprov(f['cod'])})" for f in recs])
        hechos.append(R.hecho("calor_2026", f"En {len(recs)} de esas estaciones, 2026 es ya el año con más días de 30 °C o más entre enero y agosto "
                                            f"desde 1940 o desde el principio de su serie si empieza después: {nombres}.", FUENTE_M,
                              [str(len(recs)), "30 °C", "2026", "1940"], superlativo=True, record=True))
    hechos.append(R.hecho("calor_metodo", "Son días con temperatura máxima de 30 °C o más, contados por AEMET en los valores mensuales de cada estación; "
                                         "el cálculo de las medias es del observatorio.", FUENTE_M, ["30 °C"]))
    tit = (f"{lider['nombre']} pasa de {R.f1(lider['t1'])} a {R.f1(lider['t2'])} días al año de 30 °C o más y {segundo['nombre']}, "
           f"de {R.f1(segundo['t1'])} a {R.f1(segundo['t2'])}: {_coletilla(lider)}")
    if len(tit) > 165:
        tit = f"{lider['nombre']} pasa de {R.f1(lider['t1'])} a {R.f1(lider['t2'])} días al año de 30 °C o más desde 1961-1990"
    sub = [h["dice"] for h in hechos if h["id"] in ("calor1_meses", "calor_2026")]
    pl = {"titular": tit, "subtitulo": " ".join(sub), "entradilla": hechos[0]["dice"],
          "cuerpo": [" ".join(h["dice"] for h in hechos if h["id"].startswith("calor1") and h["id"] not in ("calor1", "calor1_meses")),
                     " ".join(h["dice"] for h in hechos if h["id"].startswith("calor2")),
                     " ".join(h["dice"] for h in hechos if h["id"] in ("calor_red", "calor_metodo"))],
          "claves": [hechos[0]["dice"]] + [h["dice"] for h in hechos if h["id"] == "calor1_meses"]}
    pl["cuerpo"] = [c for c in pl["cuerpo"] if c]
    cifras = [{"n": f"+{R.f1(lider['t2'] - lider['t1'])}", "l": f"días al año de 30 °C o más en {lider['nombre']}, 2011-2025 frente a 1961-1990 (AEMET)", "tono": "calor"},
              {"n": f"{R.f1(lider['meses'][6][0])} → {R.f1(lider['meses'][6][1])}", "l": f"días de 30 °C o más en junio en {lider['nombre']}", "tono": "calor"}]
    if recs:
        cifras.append({"n": str(len(recs)), "l": "estaciones con 2026 como el año de más días de 30 °C entre enero y agosto desde 1940 o desde que empieza su serie", "tono": "calor"})
    hid = f"{R.HOY.isoformat()}-calor-30-largo"
    h = R.historia("calor_largo", hid, "Análisis · el calor se estira", "calor", 64 if recs else 58, hechos, pl, cifras, FUENTE_M,
                   "Días con máxima de 30 °C o más (nt_30) de los valores mensuales de AEMET, los 12 meses. Medias de 1961-1990 (al menos 25 años "
                   "completos) y de 2011-2025 (al menos 13). Solo estaciones cuya subida de la máxima media de junio-septiembre no se separa más de "
                   "0,7 °C de la del reanálisis en la capital de su provincia (filtro de saltos de medida; el reanálisis no se publica). El archivo "
                   "mensual empieza en 1940: los récords de 2026 son «desde 1940» aunque la estación sea más antigua.",
                   ["Una estación puede haber cambiado de entorno (urbanización) sin traslado: el filtro solo detecta saltos grandes.",
                    f"Datos mensuales de AEMET bajados el {descargado or 'septiembre de 2026'}: el año 2026 llega hasta agosto."],
                   PAG_CALOR)
    h["seccion"] = SECCION
    meses_g = (4, 5, 6, 7, 8, 9, 10)
    try:
        h["grafico"] = _barras_pares(R, [(m, round(lider["meses"][m][0], 1), round(lider["meses"][m][1], 1)) for m in meses_g], hid,
                                     f"Días de 30 °C o más en {lider['nombre']}, media de cada mes",
                                     f"Estación de AEMET de {lider['nombre']}: media de días con máxima de 30 °C o más en cada mes, 1961-1990 "
                                     "y 2011-2025. Fuente: AEMET OpenData (valores mensuales). Cálculo: calentamientoglobal.es.",
                                     CORTO, MED, R.CALOR, "1961-1990", "2011-2025")
    except Exception as e:  # noqa: BLE001
        R.LOG.append(f"analisis/calor gráfico: {e}")
    nac = hechos[0]
    por_prov = collections.defaultdict(list)
    for f in filas:
        por_prov[f["cod"]].append(f)
    for cod, fs in por_prov.items():
        f = max(fs, key=lambda x: x["t2"] - x["t1"])
        P = R.nprov(cod)
        gan = f["t2"] - f["t1"]
        if gan < 5 and not f["rec26"]:
            continue
        hv = _hechos_estacion_calor(R, f, "calorp", con_prov=False)
        if f is not lider:
            hv.append(nac)
        hv.append(hechos[-1])
        if f["rec26"] and gan >= 5:
            tit_p = (f"{f['nombre']} bate en 2026 su récord de días de 30 °C o más hasta agosto y suma {R.f1(gan)} días "
                     f"de calor más al año que en 1961-1990")
        elif f["rec26"]:
            tit_p = f"{f['nombre']} bate en 2026 su récord de días de 30 °C o más entre enero y agosto: {R.f1(f['v26'])}"
        else:
            tit_p = f"{f['nombre']} pasa de {R.f1(f['t1'])} a {R.f1(f['t2'])} días al año de 30 °C o más: {_coletilla(f)}"
        if len(tit_p) > 165:
            tit_p = f"{f['nombre']} pasa de {R.f1(f['t1'])} a {R.f1(f['t2'])} días al año de 30 °C o más desde 1961-1990"
        ent = next(x for x in hv if x["id"] == ("calorp_2026" if f["rec26"] else "calorp"))
        sub_p = next((x["dice"] for x in hv if x["id"] == "calorp_meses"), "")
        plv = {"titular": tit_p, "subtitulo": sub_p, "entradilla": ent["dice"],
               "cuerpo": [" ".join(x["dice"] for x in hv if x is not ent and x["id"] != "calorp_meses")] or [ent["dice"]],
               "claves": [x["dice"] for x in hv[:3]]}
        v = {"provincia": P, "slug": R.PROV[cod][1], "hechos": hv, "plantilla": plv,
             "cifras": [{"n": f"+{R.f1(gan)}", "l": f"días al año de 30 °C o más en {f['nombre']}, 2011-2025 frente a 1961-1990", "tono": "calor"}]
             + ([{"n": R.f1(f["v26"]), "l": f"días de 30 °C o más en {f['nombre']} entre enero y agosto de 2026, récord desde 1940", "tono": "calor"}] if f["rec26"] else []),
             "puntos": round(min(70.0, 44 + gan / 2 + (8 if f["rec26"] else 0)), 1)}
        try:
            v["grafico"] = _barras_pares(R, [(m, round(f["meses"][m][0], 1), round(f["meses"][m][1], 1)) for m in meses_g], f"{hid}-{cod}",
                                         f"Días de 30 °C o más en {f['nombre']}, media de cada mes",
                                         f"Estación de AEMET de {f['nombre']}: media de días con máxima de 30 °C o más en cada mes, 1961-1990 "
                                         "y 2011-2025. Fuente: AEMET OpenData (valores mensuales). Cálculo: calentamientoglobal.es.",
                                         CORTO, MED, R.CALOR, "1961-1990", "2011-2025")
        except Exception as e:  # noqa: BLE001
            R.LOG.append(f"analisis/calor gráfico {cod}: {e}")
        h["provincias"][cod] = v
    return [h]


# ============================================================================ 2. otono_serie
def _crudo(R):
    c = getattr(_crudo, "_c", None)
    if c is None:
        f = R.DOCS.parent / "archivo" / "otonio" / "crudo_otonios.json.gz"
        c = _crudo._c = json.load(gzip.open(f, "rt", encoding="utf-8")) if f.exists() else {}
    return c


def _acumulado(dias, hasta_idx):
    """Lluvia del 1 de septiembre al día hasta_idx (incluido), o None si faltan más de 2 días."""
    vals = [dias.get(str(i)) for i in range(hasta_idx + 1)]
    if sum(v is None for v in vals) > 2:
        return None
    return round(sum(v for v in vals if v is not None), 1)


def _veces_txt(x):
    v = x.get("veces") or 0
    if v >= 3:
        return "más del triple de lluvia que en"
    if v >= 2:
        return "más del doble de lluvia que en"
    return "más lluvia que en"


def g_otono_serie(R, D):
    O = R.leer(R.DOCS / "otonio_municipios.json", {}) or {}
    c = _crudo(R)
    if not O.get("municipios") or not c.get("datos"):
        return []
    hasta = O.get("hasta")
    dh = datetime.date.fromisoformat(hasta)
    idx = (dh - datetime.date(dh.year, 9, 1)).days
    act = {}
    for m in O["municipios"].values():
        e = m.get("est")
        if e and m.get("mm") is not None and m.get("hasta") == hasta and not m.get("huecos"):
            act.setdefault(e, (m["mm"], m.get("h"), m.get("en")))
    inv = R.leer(R.PRENSA / "aemet_inventario.json", {}) or {}
    humedos, secos = [], []
    for e, (mm, h, nom) in act.items():
        yrs = c["datos"].get(e)
        if not yrs or not inv.get(e):
            continue
        cod = _prov(R, inv[e][1])
        if not cod:
            continue
        hoy_c = {int(a): _acumulado(d, idx) for a, d in yrs.items()}
        hoy_c = {a: v for a, v in hoy_c.items() if v is not None and a < dh.year}
        # un otoño incompleto que ya supera lo de este año también impide el récord
        parcial_max = max((sum(v for i, v in d.items() if v is not None and int(i) <= idx) for a, d in yrs.items()
                           if int(a) < dh.year and int(a) not in hoy_c), default=0)
        vispera = {int(a): _acumulado(d, idx - 1) for a, d in yrs.items()}
        vispera = {a: v for a, v in vispera.items() if v is not None and a < dh.year}
        nombre = _limpio(nom) if nom else _nombre(R, e, inv[e][0])
        if len(hoy_c) >= 15 and mm >= 50 and all(mm > v for v in hoy_c.values()) and mm > parcial_max:
            a_max, v_max = max(hoy_c.items(), key=lambda x: (x[1], x[0]))
            humedos.append({"e": e, "nombre": nombre, "cod": cod, "mm": mm, "h": h, "n": len(hoy_c), "desde": min(hoy_c),
                            "a_max": a_max, "v_max": v_max, "veces": _veces(mm, v_max) if v_max > 0 else None,
                            "serie": sorted(hoy_c.items()) + [(dh.year, mm)]})
        if len(vispera) >= 25 and all(mm < v for v in vispera.values()) and st.median(vispera.values()) >= 20:
            a_min, v_min = min(vispera.items(), key=lambda x: (x[1], -x[0]))
            secos.append({"e": e, "nombre": nombre, "cod": cod, "mm": mm, "h": h, "n": len(vispera), "desde": min(vispera),
                          "a_min": a_min, "v_min": v_min, "mediana": round(st.median(vispera.values()), 1),
                          "serie": sorted(vispera.items()) + [(dh.year, mm)]})
    if not humedos and not secos:
        return []
    humedos.sort(key=lambda x: -(x["veces"] or 0))
    secos.sort(key=lambda x: (x["mm"], -x["n"]))
    fecha_t = R.dia(hasta)
    hechos = []

    def h_humedo(x, id_, con_prov=True):
        donde = f"{x['nombre']} ({R.nprov(x['cod'])})" if con_prov else x["nombre"]
        dice = (f"El pluviómetro de AEMET de {donde} lleva {R.f1(x['mm'])} mm desde el 1 de septiembre, hasta las {x['h']}:00 del {fecha_t}: "
                f"más que en cualquiera de los {x['n']} otoños anteriores con datos completos de esa estación desde {x['desde']}, "
                f"hasta el mismo día.")
        hh = [R.hecho(id_, dice, FUENTE_D, [R.f1(x["mm"]), f"{x['h']}:00", str(x["n"]), str(x["desde"])], lugar=x["nombre"],
                      liga=[R.f1(x["mm"])], superlativo=True, record=True)]
        if x["veces"] and x["veces"] >= 1.2:
            cuanto = ("más del triple de" if x["veces"] >= 3 else "más del doble de" if x["veces"] >= 2 else f"más de {R.f1(x['veces'])} veces")
            hh.append(R.hecho(id_ + "_veces", f"Es {cuanto} lo que llevaba a estas alturas en {x['a_max']}, el otoño más "
                                              f"lluvioso hasta ahora en esas fechas desde {x['desde']}: {R.f1(x['v_max'])} mm.", FUENTE_D,
                              [R.f1(x["veces"]), str(x["a_max"]), R.f1(x["v_max"])], lugar=x["nombre"], liga=[R.f1(x["v_max"])],
                              superlativo=True))
        return hh

    def h_seco(x, id_, con_prov=True):
        donde = f"{x['nombre']} ({R.nprov(x['cod'])})" if con_prov else x["nombre"]
        dice = (f"El pluviómetro de AEMET de {donde} solo lleva {R.f1(x['mm'])} mm desde el 1 de septiembre, hasta las {x['h']}:00 del {fecha_t}: "
                f"menos que en cualquier otoño desde {x['desde']} ({x['n']} con datos completos) ya en la víspera.")
        return [R.hecho(id_, dice, FUENTE_D, [R.f1(x["mm"]), f"{x['h']}:00", str(x["n"]), str(x["desde"])], lugar=x["nombre"],
                        liga=[R.f1(x["mm"])], superlativo=True, record=True),
                R.hecho(id_ + "_antes", f"En {x['nombre']}, el otoño más seco a estas alturas desde {x['desde']} era el de {x['a_min']}, con "
                                        f"{R.f1(x['v_min'])} mm; lo habitual es {R.f1(x['mediana'])} mm (mediana de esos otoños).", FUENTE_D,
                        [str(x["a_min"]), R.f1(x["v_min"]), R.f1(x["mediana"])], lugar=x["nombre"], liga=[R.f1(x["v_min"]), R.f1(x["mediana"])],
                        superlativo=True)]
    if humedos:
        lider = humedos[0]
        hechos += h_humedo(lider, "ot_h1")
        for i, x in enumerate(humedos[1:3], 2):
            hechos += h_humedo(x, f"ot_h{i}")[:1]
    if secos:
        hechos += h_seco(secos[0], "ot_s1")
        if len(secos) > 1:
            otros = R.lista_y([f"{x['nombre']} ({R.nprov(x['cod'])}, {R.f1(x['mm'])} mm)" for x in secos[1:4]])
            hechos.append(R.hecho("ot_s_otros", f"También van por el otoño más seco a estas alturas desde 1991 {otros}.", FUENTE_D,
                                  [R.f1(x["mm"]) for x in secos[1:4]] + [f"{R.f1(x['mm'])} mm" for x in secos[1:4]], superlativo=True))
    n_h, n_s = len(humedos), len(secos)
    hechos.append(R.hecho("ot_cuenta", f"De los pluviómetros de AEMET que sigue el observatorio con al menos 15 otoños completos desde 1991, {n_h} van "
                                       f"por el otoño más lluvioso desde su primer otoño completo hasta el {fecha_t} y {n_s}, con al menos 25 otoños, "
                                       f"por el más seco.", FUENTE_D, [str(n_h), str(n_s), "15", "25", "1991"], superlativo=True))
    if humedos:
        x = humedos[0]
        tit = f"{x['nombre']} lleva este otoño {_veces_txt(x)} cualquier otoño desde {x['desde']} a estas alturas: {R.f1(x['mm'])} litros por metro cuadrado"
        if secos:
            tit += f"; {secos[0]['nombre']}, el más seco desde {secos[0]['desde']}"
    else:
        x = secos[0]
        tit = f"{x['nombre']} vive el otoño más seco a estas alturas desde {x['desde']}: {R.f1(x['mm'])} litros por metro cuadrado desde el 1 de septiembre"
    if len(tit) > 165:
        tit = tit.split(";")[0]
    ent = hechos[0]
    pl = {"titular": tit, "subtitulo": next((h["dice"] for h in hechos if h["id"] in ("ot_h1_veces",)), "") or
                                       next((h["dice"] for h in hechos if h["id"] == "ot_cuenta"), ""),
          "entradilla": ent["dice"],
          "cuerpo": [" ".join(h["dice"] for h in hechos if h["id"].startswith("ot_h") and h is not ent and h["id"] != "ot_h1_veces"),
                     " ".join(h["dice"] for h in hechos if h["id"].startswith("ot_s")),
                     next(h["dice"] for h in hechos if h["id"] == "ot_cuenta")],
          "claves": [h["dice"] for h in hechos[:3]]}
    pl["cuerpo"] = [p for p in pl["cuerpo"] if p]
    cifras = []
    if humedos:
        cifras.append({"n": f"{R.f1(humedos[0]['mm'])} mm", "l": f"en {humedos[0]['nombre']} desde el 1 de septiembre, récord a esta fecha desde {humedos[0]['desde']}", "tono": "lluvia"})
    if secos:
        cifras.append({"n": f"{R.f1(secos[0]['mm'])} mm", "l": f"en {secos[0]['nombre']}, el otoño más seco a esta fecha desde {secos[0]['desde']}", "tono": "calor"})
    cifras.append({"n": f"{n_h} · {n_s}", "l": "pluviómetros con el otoño más lluvioso · más seco a esta fecha desde su primer otoño completo", "tono": "lluvia"})
    hid = f"{R.HOY.isoformat()}-otono-record-serie"
    puntos = 66 if humedos and humedos[0]["veces"] and humedos[0]["veces"] >= 2 else 58
    hh_ = R.historia("otono_serie", hid, "Análisis · el otoño, frente a su historia", "lluvia", puntos, hechos, pl, cifras, FUENTE_D,
                     "Lluvia desde el 1 de septiembre en cada pluviómetro de AEMET (diarios validados y observación horaria de la misma estación), "
                     "frente a los otoños 1991-2025 de esa estación hasta el mismo día (diarios de AEMET). Un otoño cuenta si le faltan como mucho 2 "
                     "días del tramo. Récord húmedo: lo de este año, hasta la última hora con dato, supera el día completo de todos los anteriores. "
                     "Récord seco: queda por debajo de todos los anteriores ya en la víspera. Si un otoño incompleto ya supera lo de este año, "
                     "no hay récord. El archivo diario empieza en 1991: «desde 1991» no quiere decir que la estación no sea más antigua.",
                     ["Muchas estaciones empezaron entre 2005 y 2009: se dice siempre desde qué año hay datos completos.",
                      "La observación horaria de AEMET aún no está validada: la cifra de este año puede cambiar unas décimas."],
                     PAG_LLUVIA)
    hh_["seccion"] = SECCION
    lead = humedos[0] if humedos else secos[0]
    try:
        hh_["grafico"] = _barras_serie(R, lead["serie"], {dh.year}, hid, f"Lluvia del 1 de septiembre al {fecha_t.split(' ', 1)[-1]}, otoño a otoño, en {lead['nombre']}",
                                       f"Pluviómetro de AEMET de {lead['nombre']}: lluvia acumulada desde el 1 de septiembre hasta la misma fecha de cada otoño "
                                       "con datos completos. Fuente: AEMET OpenData. Cálculo: calentamientoglobal.es.",
                                       R.LLUVIA if humedos else R.CALOR, MED_LL if humedos else MED)
    except Exception as e:  # noqa: BLE001
        R.LOG.append(f"analisis/otono gráfico: {e}")
    nac = next(h for h in hechos if h["id"] == "ot_cuenta")
    por_prov = collections.defaultdict(lambda: {"h": [], "s": []})
    for x in humedos:
        por_prov[x["cod"]]["h"].append(x)
    for x in secos:
        por_prov[x["cod"]]["s"].append(x)
    for cod, g in por_prov.items():
        P = R.nprov(cod)
        hv = []
        for i, x in enumerate(g["h"][:3], 1):
            hv += h_humedo(x, f"otp_h{i}", con_prov=False) if i == 1 else h_humedo(x, f"otp_h{i}", con_prov=False)[:1]
        for i, x in enumerate(g["s"][:3], 1):
            hv += h_seco(x, f"otp_s{i}", con_prov=False)
        hv.append(nac)
        x = (g["h"] or g["s"])[0]
        if g["h"]:
            tit_p = f"{x['nombre']} lleva este otoño {_veces_txt(x)} cualquier otoño desde {x['desde']} a estas alturas: {R.f1(x['mm'])} litros por metro cuadrado"
        else:
            tit_p = f"{x['nombre']} vive el otoño más seco a estas alturas desde {x['desde']}: {R.f1(x['mm'])} litros por metro cuadrado"
        plv = {"titular": tit_p, "subtitulo": next((h["dice"] for h in hv if h["id"] in ("otp_h1_veces", "otp_s1_antes")), "") or nac["dice"],
               "entradilla": hv[0]["dice"], "cuerpo": [" ".join(h["dice"] for h in hv[1:] if h["id"] not in ("otp_h1_veces", "otp_s1_antes"))] or [hv[0]["dice"]],
               "claves": [h["dice"] for h in hv[:3]]}
        v = {"provincia": P, "slug": R.PROV[cod][1], "hechos": hv, "plantilla": plv,
             "cifras": [{"n": f"{R.f1(x['mm'])} mm", "l": f"en {x['nombre']} desde el 1 de septiembre, hasta las {x['h']}:00 del {fecha_t}",
                         "tono": "lluvia" if g["h"] else "calor"}],
             "puntos": 64 if g["h"] and x["veces"] and x["veces"] >= 2 else 56}
        try:
            v["grafico"] = _barras_serie(R, x["serie"], {dh.year}, f"{hid}-{cod}",
                                         f"Lluvia del 1 de septiembre al {fecha_t.split(' ', 1)[-1]}, otoño a otoño, en {x['nombre']}",
                                         f"Pluviómetro de AEMET de {x['nombre']}: lluvia acumulada desde el 1 de septiembre hasta la misma fecha de cada "
                                         "otoño con datos completos. Fuente: AEMET OpenData. Cálculo: calentamientoglobal.es.",
                                         R.LLUVIA if g["h"] else R.CALOR, MED_LL if g["h"] else MED)
        except Exception as e:  # noqa: BLE001
            R.LOG.append(f"analisis/otono gráfico {cod}: {e}")
        hh_["provincias"][cod] = v
    return [hh_]


# ============================================================================ 3. torrencial (+ DANAs)
def _dias_dana(R):
    cat = R.leer(R.DOCS / "dana" / "catalogo.json", {}) or {}
    dias = set()
    for a, sis in (cat.get("anios") or {}).items():
        for s in sis:
            dias.update(s.get("dias_esp") or [])
    return dias, cat


def g_torrencial(R, D):
    c = _crudo(R)
    datos = c.get("datos") or {}
    if not datos:
        return []
    inv = R.leer(R.PRENSA / "aemet_inventario.json", {}) or {}

    def completo(e, a):
        d = datos[e].get(str(a))
        return bool(d) and sum(1 for v in d.values() if v is not None) >= 85
    anios = list(range(1991, 2026))
    fijas = [e for e in datos if sum(1 for a in anios if completo(e, a)) >= 33 and _prov(R, (inv.get(e) or [None, None])[1])]
    if len(fijas) < 50:
        return []
    dana, _cat = _dias_dana(R)

    def fecha(a, i):
        return (datetime.date(int(a), 9, 1) + datetime.timedelta(int(i))).isoformat()

    def con_dana(f):
        x = datetime.date.fromisoformat(f)
        return any((x + datetime.timedelta(k)).isoformat() in dana for k in (-1, 0, 1))
    por_anio = {}
    regs = []  # (estación, fecha) con 100 mm o más
    for a in anios:
        d100 = d50 = 0
        tot = fuerte = 0.0
        for e in fijas:
            if not completo(e, a):
                continue
            for i, v in datos[e][str(a)].items():
                if v is None:
                    continue
                tot += v
                if v >= 50:
                    d50 += 1
                    fuerte += v
                if v >= 100:
                    d100 += 1
                    regs.append((e, fecha(a, i)))
        por_anio[a] = {"d100": d100, "d50": d50, "pf": 100 * fuerte / tot if tot else 0}
    A1, A2 = range(1991, 2008), range(2009, 2026)
    m100 = (st.mean(por_anio[a]["d100"] for a in A1), st.mean(por_anio[a]["d100"] for a in A2))
    m50 = (st.mean(por_anio[a]["d50"] for a in A1), st.mean(por_anio[a]["d50"] for a in A2))
    pf = (st.mean(por_anio[a]["pf"] for a in A1), st.mean(por_anio[a]["pf"] for a in A2))
    # por provincia: días distintos (no registros: dos estaciones el mismo día cuentan una vez)
    dias_prov = collections.defaultdict(set)
    est_prov = collections.Counter()
    for e in fijas:
        est_prov[_prov(R, inv[e][1])] += 1
    for e, f in regs:
        dias_prov[_prov(R, inv[e][1])].add(f)
    top = sorted(dias_prov.items(), key=lambda x: (-len(x[1]), x[0]))[:3]
    n_reg = len(regs)
    coin = sum(1 for _, f in regs if con_dana(f))
    pc_coin = round(100 * coin / n_reg) if n_reg else None
    pc_base = round(100 * sum(con_dana(fecha(a, i)) for a in anios for i in range(91)) / (len(anios) * 91))
    red91 = sum(1 for e in datos if completo(e, 1991))
    red25 = sum(1 for e in datos if completo(e, 2025))
    n = len(fijas)
    hechos = [
        R.hecho("tor_dias", f"Las {n} estaciones de AEMET con al menos 33 de los 35 otoños completos entre 1991 y 2025 sumaron entre todas, de media, "
                            f"{R.f1(m100[0])} días con 100 mm o más de lluvia por otoño en 1991-2007 y {R.f1(m100[1])} en 2009-2025.", FUENTE_D,
                [str(n), "33", "35", "1991", "2025", "100 mm", R.f1(m100[0]), R.f1(m100[1]), "2007", "2009"]),
        R.hecho("tor_50", f"En esas estaciones, los días de 50 mm o más pasaron de {R.f1(m50[0])} a {R.f1(m50[1])} por otoño, y la parte de la lluvia del "
                          f"otoño que cae en esos días, del {R.f1(pf[0])} % al {R.f1(pf[1])} % de media.", FUENTE_D,
                [R.f1(m50[0]), R.f1(m50[1]), f"{R.f1(pf[0])} %", f"{R.f1(pf[1])} %", "50 mm"]),
        R.hecho("tor_donde", "Por provincias, los días de otoño con 100 mm o más en alguna de esas estaciones desde 1991 fueron más en "
                             + R.lista_y([f"{R.nprov(p)} ({len(ds)} días, con {est_prov[p]} {'estación' if est_prov[p] == 1 else 'estaciones'})"
                                          for p, ds in top]) + "; cuenta más quien tiene más estaciones de serie completa.", FUENTE_D,
                [str(len(ds)) for _, ds in top] + [str(est_prov[p]) for p, _ in top], superlativo=True),
    ]
    if pc_coin is not None:
        hechos.append(R.hecho("tor_dana", f"De los {n_reg} registros de 100 mm o más en un día de otoño en esas estaciones, el {pc_coin} % coincidió con "
                                          f"una DANA sobre España y su entorno ese día, la víspera o el día siguiente, según el catálogo de DANAs del "
                                          f"observatorio; esos días con DANA son el {pc_base} % de los días de otoño.",
                              FUENTE_D + "; " + FUENTE_DANA, [str(n_reg), f"{pc_coin} %", f"{pc_base} %", "100 mm"]))
    hechos.append(R.hecho("tor_metodo", f"Se cuentan solo estaciones con la serie completa para que la comparación no dependa de la red: en el archivo del "
                                        f"observatorio hay {red91} estaciones de AEMET con el otoño completo en 1991 y {red25} en 2025.", FUENTE_D,
                          [str(red91), "1991", str(red25), "2025"]))
    if abs(m100[1] - m100[0]) < 0.5:
        tit = (f"Los días de 100 litros por metro cuadrado o más en otoño no han aumentado desde 1991 en las {n} estaciones de AEMET con "
               f"serie completa: {R.f1(m100[1])} por otoño entre todas")
    elif m100[1] > m100[0]:
        tit = f"Los días de 100 mm o más en otoño pasan de {R.f1(m100[0])} a {R.f1(m100[1])} por otoño en las {n} estaciones de AEMET con serie completa"
    else:
        tit = f"Los días de 100 mm o más en otoño bajan de {R.f1(m100[0])} a {R.f1(m100[1])} por otoño en las {n} estaciones de AEMET con serie completa"
    pl = {"titular": tit, "subtitulo": next((h["dice"] for h in hechos if h["id"] == "tor_dana"), hechos[1]["dice"]),
          "entradilla": hechos[0]["dice"],
          "cuerpo": [hechos[1]["dice"], next(h["dice"] for h in hechos if h["id"] == "tor_donde"),
                     next(h["dice"] for h in hechos if h["id"] == "tor_metodo")],
          "claves": [hechos[0]["dice"], hechos[1]["dice"]] + [h["dice"] for h in hechos if h["id"] == "tor_dana"]}
    cifras = [{"n": f"{R.f1(m100[0])} → {R.f1(m100[1])}", "l": f"días de 100 mm o más por otoño entre las {n} estaciones de AEMET de serie completa, 1991-2007 → 2009-2025", "tono": "lluvia"}]
    if pc_coin is not None:
        cifras.append({"n": f"{pc_coin} %", "l": f"de esos registros coincidió con una DANA (el {pc_base} % de los días de otoño)", "tono": "lluvia"})
    hid = f"{R.HOY.isoformat()}-lluvia-torrencial-otono"
    h = R.historia("torrencial", hid, "Análisis · lluvia muy fuerte, el dato", "lluvia", 56, hechos, pl, cifras, FUENTE_D,
                   "Lluvia diaria de AEMET (de 07 a 07 UTC) del 1 de septiembre al 30 de noviembre de cada año. Un otoño de una estación cuenta si "
                   "tiene dato en al menos 85 de sus 91 días. Periodos de 17 otoños: 1991-2007 y 2009-2025. La parte de la lluvia en días de 50 mm o "
                   "más es la media de cada otoño. DANAs: catálogo del observatorio (criterios de Nieto et al. 2005 en 500 hPa con el reanálisis "
                   "NCEP/NCAR), caja 32,5-45° N y 15° O-7,5° E, que incluye Portugal, el norte de África y el mar alrededor.",
                   ["35 otoños son pocos para hablar de tendencia climática: el dato dice lo que ha pasado en estas estaciones, no lo que pasará.",
                    "Las estaciones con serie completa son sobre todo las principales (aeropuertos, capitales): pueden faltar los puntos donde más "
                    "llueve, como Turís el 29 de octubre de 2024.",
                    "AEMET llama «torrencial» a la lluvia de más de 60 mm en una hora; aquí se cuentan días de 100 mm o más.",
                    "El catálogo de DANAs sale de un reanálisis, no de una medida."],
                   PAG_LLUVIA)
    h["seccion"] = SECCION
    try:
        h["grafico"] = _barras_serie(R, [(a, por_anio[a]["d100"]) for a in anios], set(), hid,
                                     f"Días de 100 mm o más en otoño en {n} estaciones de AEMET, 1991-2025",
                                     f"Suma de los días con 100 mm o más entre el 1 de septiembre y el 30 de noviembre en las {n} estaciones de AEMET con "
                                     "serie completa. Fuente: AEMET OpenData. Cálculo: calentamientoglobal.es.", R.LLUVIA, R.LLUVIA,
                                     fmt=lambda v: str(int(round(v))))
    except Exception as e:  # noqa: BLE001
        R.LOG.append(f"analisis/torrencial gráfico: {e}")
    nac = hechos[0]
    limite_p = R.hecho("torp_limite", "Solo cuentan las estaciones con la serie completa: los días de 100 mm o más en otras estaciones de la provincia "
                                      "no entran.", FUENTE_D, ["100 mm"])
    for cod, ds in dias_prov.items():
        k = len(ds)
        if k < 3:
            continue
        es = [e for e in fijas if _prov(R, inv[e][1]) == cod]
        P = R.nprov(cod)
        cuenta = collections.Counter(e for e, f in regs if _prov(R, inv[e][1]) == cod)
        mejor, k_mejor = max(cuenta.items(), key=lambda x: (x[1], x[0]))
        nm = _nombre(R, mejor, inv[mejor][0])
        if len(es) > 1:
            hv = [R.hecho("torp", f"En {k} días de otoño desde 1991, alguna de las {len(es)} estaciones de AEMET de {P} con al menos 33 de los 35 "
                                  f"otoños completos entre 1991 y 2025 recogió 100 mm o más; la que más veces, {nm}, con {k_mejor}.", FUENTE_D,
                          [str(k), str(len(es)), "33", "35", "1991", "2025", "100 mm", str(k_mejor)], lugar=nm, liga=[str(k_mejor)], superlativo=True)]
        else:
            hv = [R.hecho("torp", f"La estación de AEMET de {nm}, la única de {P} con al menos 33 de los 35 otoños completos entre 1991 y 2025, "
                                  f"recogió 100 mm o más en {k} días de otoño desde 1991.", FUENTE_D,
                          [str(k), "33", "35", "1991", "2025", "100 mm"], lugar=nm, liga=[str(k)])]
        hv += [limite_p, nac, hechos[1]] + [x for x in hechos if x["id"] == "tor_dana"]
        plv = {"titular": f"{P}: {k} días de otoño con 100 litros por metro cuadrado o más desde 1991 en sus estaciones de AEMET de serie completa",
               "subtitulo": nac["dice"], "entradilla": hv[0]["dice"], "cuerpo": [" ".join(x["dice"] for x in hv[1:] if x is not nac)],
               "claves": [x["dice"] for x in hv[:3]]}
        h["provincias"][cod] = {"provincia": P, "slug": R.PROV[cod][1], "hechos": hv, "plantilla": plv,
                                "cifras": [{"n": str(k), "l": f"días de otoño con 100 mm o más desde 1991 en {P} (estaciones de serie completa)", "tono": "lluvia"}],
                                "puntos": round(min(58.0, 36 + k * 1.5), 1)}
    return [h]


# ============================================================================ 4. dana_largo
def g_dana_largo(R, D):
    dana, cat = _dias_dana(R)
    if not dana:
        return []
    por = collections.Counter((int(d[:4]), int(d[5:7])) for d in dana)
    Q1, Q2, Q3 = range(1961, 1991), range(1996, 2026), range(2011, 2026)

    def media(meses, Q):
        return st.mean(sum(por[(a, m)] for m in meses) for a in Q)
    TODO, OTO, INV, VER = range(1, 13), (9, 10, 11), (12, 1, 2, 3, 4, 5), (7, 8)
    an = (media(TODO, Q1), media(TODO, Q2))
    ot = (media(OTO, Q1), media(OTO, Q2))
    # Diciembre del año anterior + enero-mayo: el mismo «año de lluvias» que usa danas.json (analisis_series.dias_catalogo).
    ip = tuple(st.mean(sum(por[(a, m)] for m in (1, 2, 3, 4, 5)) + por[(a - 1, 12)] for a in Q) for Q in (Q1, Q2))
    ver = (media(VER, Q1), media(VER, Q2))
    an3 = media(TODO, Q3)
    mes = {m: (round(media((m,), Q1), 1), round(media((m,), Q2), 1)) for m in TODO}
    hechos = [
        R.hecho("dana_inv", f"El catálogo de DANAs del observatorio cuenta de media {R.f1(ip[1])} días con una DANA sobre España y su entorno entre "
                            f"diciembre y mayo (diciembre del año anterior) en 1996-2025, frente a {R.f1(ip[0])} en 1961-1990.", FUENTE_DANA,
                [R.f1(ip[1]), R.f1(ip[0]), "1996", "2025", "1961", "1990"]),
        R.hecho("dana_resto", f"En otoño (septiembre a noviembre) pasan de {R.f1(ot[0])} a {R.f1(ot[1])} días, una diferencia pequeña para lo que "
                              f"cambia de un año a otro; en julio y agosto bajan de {R.f1(ver[0])} a {R.f1(ver[1])}.", FUENTE_DANA,
                [R.f1(ot[0]), R.f1(ot[1]), R.f1(ver[0]), R.f1(ver[1])]),
        R.hecho("dana_anual", f"En todo el año, {R.f1(an[1])} días de media en 1996-2025 frente a {R.f1(an[0])} en 1961-1990; la media de 2011-2025 es "
                              f"de {R.f1(an3)}, así que la cifra depende mucho del periodo que se mire.", FUENTE_DANA,
                [R.f1(an[1]), R.f1(an[0]), R.f1(an3), "2011", "2025"]),
        R.hecho("dana_def", "Un día con DANA es un día con una baja aislada en 500 hPa, con los criterios de Nieto et al. (2005) y al menos 2 días de "
                            "duración, centrada entre 32,5° y 45° N y entre 15° O y 7,5° E: la península, Baleares, el sur de Francia, el mar alrededor y "
                            "el norte de África, sin Canarias. El catálogo sale del reanálisis NCEP/NCAR, no de una medida.",
                FUENTE_DANA, ["500 hPa", "2005", "2", "32,5", "45", "15", "7,5"]),
    ]
    tit = (f"Las DANAs sobre España ganan terreno entre diciembre y mayo: {R.f1(ip[1])} días al año en 1996-2025 frente a {R.f1(ip[0])} "
           f"en 1961-1990, según el catálogo del observatorio")
    if len(tit) > 165:
        tit = f"Las DANAs sobre España ganan terreno entre diciembre y mayo: {R.f1(ip[1])} días frente a {R.f1(ip[0])} en 1961-1990"
    pl = {"titular": tit, "subtitulo": hechos[1]["dice"], "entradilla": hechos[0]["dice"], "cuerpo": [hechos[2]["dice"], hechos[3]["dice"]],
          "claves": [h["dice"] for h in hechos[:3]]}
    cifras = [{"n": f"{R.f1(ip[0])} → {R.f1(ip[1])}", "l": "días con DANA entre diciembre y mayo, 1961-1990 → 1996-2025 (catálogo del observatorio)", "tono": "lluvia"},
              {"n": f"{R.f1(ot[0])} → {R.f1(ot[1])}", "l": "en otoño, una diferencia pequeña", "tono": "lluvia"}]
    hid = f"{R.HOY.isoformat()}-danas-largo"
    h = R.historia("dana_largo", hid, "Análisis · las DANAs, en el catálogo", "lluvia", 46, hechos, pl, cifras, FUENTE_DANA,
                   "Detector propio en 500 hPa (Nieto et al. 2005) aplicado al reanálisis diario NCEP/NCAR de 2,5°; medias de 1961-1990 y 1996-2025.",
                   ["Es un análisis con un reanálisis, no una medida: el número de días depende del método.",
                    "Antes de 1979 el reanálisis tiene menos observaciones de satélite; 2026 no entra (desde el 18 de marzo el catálogo usa el "
                    "análisis de ECMWF, sin calibrar con NCEP).",
                    "Un día con DANA en la caja no significa que haya llovido en España."],
                   PAG_DANA)
    h["seccion"] = SECCION
    try:
        et = {m: ["", "Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"][m] for m in TODO}
        h["grafico"] = _barras_pares(R, [(m, *mes[m]) for m in TODO], hid, "Días con DANA sobre España y su entorno, media de cada mes",
                                     "Catálogo de DANAs del observatorio con el reanálisis NCEP/NCAR: media de días con DANA en la caja 32,5-45° N y "
                                     "15° O-7,5° E en cada mes, 1961-1990 y 1996-2025. Cálculo: calentamientoglobal.es.", et, MED_LL, R.LLUVIA,
                                     "1961-1990", "1996-2025")
    except Exception as e:  # noqa: BLE001
        R.LOG.append(f"analisis/dana gráfico: {e}")
    return [h]



# ============================================================================ 5. verano_largo (series diarias)
# docs/prensa/analisis/verano.json lo escribe scripts/analisis_series.py con las series diarias largas de AEMET.
MESES_L = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
PAG_ANALISIS = "https://calentamientoglobal.es/prensa/analisis/"


def _dd(x):
    """Días enteros, redondeo a la mitad hacia arriba (33,5 → 34)."""
    from decimal import ROUND_HALF_UP, Decimal
    return int(Decimal(str(float(x))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _fecha_md(md):
    """'06-02' → '2 de junio'."""
    m, d = int(md[:2]), int(md[3:5])
    return f"{d} de {MESES_L[m - 1]}"


def _fecha_iso(iso):
    d = datetime.date.fromisoformat(iso[:10])
    return f"{d.day} de {MESES_L[d.month - 1]}"


def _grafico_verano(R, x, nombre):
    """Cada año, una raya del primer al último día de verano; en color, 2026. Líneas: inicio y fin medios de la referencia."""
    serie = x.get("serie") or []
    if len(serie) < 20:
        return None
    doy = lambda md: (datetime.date(2001, int(md[:2]), int(md[3:5])) - datetime.date(2001, 1, 1)).days  # noqa: E731
    d0, d1 = doy("04-15"), doy("11-15")
    W, ml, mr, mt, fila = 640, 44, 16, 34, 4.2
    Hh = int(mt + fila * len(serie) + 34)
    X = lambda d: ml + (min(max(d, d0), d1) - d0) / (d1 - d0) * (W - ml - mr)  # noqa: E731
    s = []
    for md, et in (("05-01", "1 may"), ("06-01", "1 jun"), ("07-01", "1 jul"), ("08-01", "1 ago"), ("09-01", "1 sep"), ("10-01", "1 oct"), ("11-01", "1 nov")):
        s.append(f'<line x1="{X(doy(md)):.1f}" x2="{X(doy(md)):.1f}" y1="{mt - 4}" y2="{Hh - 26}" stroke="{R.RAYA}" stroke-width="1"></line>')
        s.append(R._t(X(doy(md)), Hh - 10, et, 11, R.GRIS, "middle"))
    for i, (a, ini, fin, dur) in enumerate(serie):
        y = mt + i * fila
        dest = a == serie[-1][0] and a >= 2026
        color = R.CALOR if dest else (MED if a >= 2011 else "#E9C9B8" if a >= 1991 else "#D9D3CA")
        s.append(f'<rect x="{X(doy(ini)):.1f}" y="{y:.1f}" width="{max(1.0, X(doy(fin)) - X(doy(ini))):.1f}" height="{fila - 0.8:.1f}" fill="{color}"></rect>')
        if i == 0 or a % 10 == 0:
            s.append(R._t(ml - 6, y + 4, str(a), 10, R.GRIS, "end"))
    for k in ("base_ini", "base_fin"):
        xx = X(doy(x[k]))
        s.append(f'<line x1="{xx:.1f}" x2="{xx:.1f}" y1="{mt - 6}" y2="{mt + fila * len(serie)}" stroke="{R.TINTA}" stroke-width="1.2" stroke-dasharray="3 3"></line>')
    s.append(R._t(X(doy(x["base_ini"])), mt - 10, f"inicio medio {x['base']}", 10.5, R.TINTA, "end"))
    s.append(R._t(X(doy(x["base_fin"])), mt - 10, f"fin medio {x['base']}", 10.5, R.TINTA, "start"))
    a26 = serie[-1]
    if a26[0] >= 2026:
        s.append(R._t(X(doy(a26[2])) + 6, mt + fila * (len(serie) - 1) + 5, str(a26[0]), 11, R.CALOR, "start", 700))
    svg = R._svg(W, Hh, f"Duración del verano cada año en {x['nombre']}", s)
    return R.guardar_grafico(nombre, svg, [(a, ini, fin, dur) for a, ini, fin, dur in serie], ["anio", "inicio", "fin", "dias"],
                             f"El verano de cada año en {x['nombre']}, del primer al último día", [
                                 {"t": "banda", "c": "#D9D3CA", "l": "hasta 1990"}, {"t": "banda", "c": "#E9C9B8", "l": "1991-2010"},
                                 {"t": "banda", "c": MED, "l": "2011-2025"}, {"t": "banda", "c": R.CALOR, "l": "2026"}],
                             f"Estación de AEMET de {x['nombre']}. Verano: del primer al último día del año en que la media de 7 días de la temperatura "
                             f"media alcanza {R.f1(x['umbral'])} °C, lo que en {x['base']} solo se alcanzaba 92 días al año. Fuente: AEMET OpenData "
                             "(valores diarios). Cálculo: calentamientoglobal.es.")


def _lugar(R, x):
    """«València» o «Lorca (Murcia)»: la provincia solo si el nombre no la dice ya."""
    return x["nombre"] if R.H._norm(R.nprov(x["cod"])) in R.H._norm(x["nombre"]) else f"{x['nombre']} ({R.nprov(x['cod'])})"


def _hechos_verano(R, x, id_, con_prov=True):
    n = x["nombre"]
    donde = _lugar(R, x) if con_prov else n
    b, bd, rd = x["base"], _dd(x["base_dias"]), _dd(x["rec_dias"])
    dif = rd - bd
    hh = [R.hecho(id_, f"En la estación de AEMET de {donde}, el verano sumaba de media {bd} días al año en {b} y {rd} en 2011-2025: {dif} días más.",
                  FUENTE_D, [str(bd), str(rd), str(dif), b[:4], b[5:], "2011", "2025"], lugar=n, liga=[str(bd), str(rd), str(dif)]),
          R.hecho(f"{id_}_fechas", f"De media, en 2011-2025 empezaba el {_fecha_md(x['rec_ini'])} y acababa el {_fecha_md(x['rec_fin'])}; en {b}, "
                                   f"del {_fecha_md(x['base_ini'])} al {_fecha_md(x['base_fin'])}.", FUENTE_D,
                  [_fecha_md(x["rec_ini"]), _fecha_md(x["rec_fin"]), _fecha_md(x["base_ini"]), _fecha_md(x["base_fin"]), b[:4], b[5:]], lugar=n),
          R.hecho(f"{id_}_def", f"El observatorio cuenta como días de verano los del año en que la media de siete días de la temperatura media de la estación "
                                f"alcanza {R.f1(x['umbral'])} °C, un nivel que en {b} se superaba unos 92 días al año, lo que duran junio, julio y agosto; "
                                "el verano empieza con el primer tramo de al menos cinco días seguidos a ese nivel y acaba con el último.",
                  FUENTE_D, [R.f1(x["umbral"]) + " °C", "92", b[:4], b[5:]], lugar=n)]
    a = x.get("actual")
    if a:
        hasta = _fecha_iso(a["datos_hasta"])
        if a.get("mas_dias"):
            ant = R.lista_y([str(z) for z in a["max_prev_anios"]])
            t = (f"Con los datos validados por AEMET hasta el {hasta}, {a['anio']} suma ya {a['dias']} días de verano en {n}: más que cualquier año "
                 f"completo desde {x['desde']} (el máximo anterior eran {a['max_prev']}, en {ant}{'; la serie tiene años sin dato' if x.get('huecos') else ''}).")
            vals = [hasta, str(a["dias"]), str(x["desde"]), str(a["max_prev"])] + [str(z) for z in a["max_prev_anios"]]
        elif a.get("supera_media_reciente"):
            t = (f"Con los datos validados por AEMET hasta el {hasta}, {a['anio']} suma ya {a['dias']} días de verano en {n}, frente a {rd} de media "
                 f"en 2011-2025 y {bd} en {b}.")
            vals = [hasta, str(a["dias"]), str(rd), str(bd)]
        else:
            t, vals = None, []
        if t:
            if a.get("terminado"):
                t += f" Empezó el {_fecha_iso(a['ini'])} y acabó el {_fecha_iso(a['fin'])}."
                vals += [_fecha_iso(a["ini"]), _fecha_iso(a["fin"])]
            elif a.get("sigue"):
                t += f" Empezó el {_fecha_iso(a['ini'])} y el {_fecha_iso(a['calculable_hasta'])}, último día que se puede calcular, aún seguía."
                vals += [_fecha_iso(a["ini"]), _fecha_iso(a["calculable_hasta"])]
            hh.append(R.hecho(f"{id_}_2026", t, FUENTE_D, vals, lugar=n, superlativo=bool(a.get("mas_dias")), record=bool(a.get("mas_dias"))))
    return hh


def g_verano_largo(R, D):
    V = R.leer(R.DOCS / "prensa" / "analisis" / "verano.json", {}) or {}
    est = V.get("estaciones") or {}
    filas = [dict(est[i], id=i) for i in (V.get("provincias") or {}).values() if i in est]
    con61 = [x for x in filas if x["base"] == "1961-1990"]
    if len(con61) < 3:
        return []
    dif = lambda x: _dd(x["rec_dias"]) - _dd(x["base_dias"])  # noqa: E731
    con61.sort(key=lambda x: -dif(x))
    difs = sorted(dif(x) for x in con61)
    med = st.median(difs)
    med_t = str(int(med)) if med == int(med) else R.f1(med)
    recs = sorted((x for x in filas if (x.get("actual") or {}).get("mas_dias")), key=lambda x: x["desde"])
    recs_largos = [x for x in recs if x["desde"] <= 1960]
    hechos = [R.hecho("ver_red", f"En las {len(con61)} estaciones de AEMET con al menos 20 años de datos en 1961-1990 que ha analizado el observatorio, el verano "
                                 f"suma ahora entre {difs[0]} y {difs[-1]} días más al año que entonces (2011-2025 frente a 1961-1990); la mediana, {med_t} días.",
                      FUENTE_D, [str(len(con61)), "20", "1961", "1990", str(difs[0]), str(difs[-1]), med_t, "2011", "2025"])]
    lider = con61[0]
    hechos += _hechos_verano(R, lider, "ver1")
    if recs:
        partes = [f"{_lugar(R, x)}, desde {x['desde']}" for x in recs]
        con26 = sum(1 for x in filas if (x.get("actual") or {}).get("dias"))
        hechos.append(R.hecho("ver_2026", f"Con los datos validados por AEMET hasta mediados de octubre, 2026 ya es el año con más días de verano de su serie en "
                                          f"{len(recs)} de las {con26} estaciones analizadas con dato de 2026: {R.lista_y(partes)}.", FUENTE_D,
                              [str(len(recs)), str(con26), "2026"] + [str(x["desde"]) for x in recs], superlativo=True, record=True))
    hechos.append(R.hecho("ver_ctrl", "Solo entran estaciones cuyo cambio no se separa del que da el reanálisis en la capital de su provincia (filtro de "
                                      "traslados y cambios de sensor); una estación también puede calentarse porque la ciudad ha crecido a su alrededor.",
                          FUENTE_D, []))
    if recs_largos:
        nombres = R.lista_y([f"{x['nombre'].split(' (')[0]} desde {x['desde']}" for x in recs_largos[:2]])
        tit = f"El verano suma entre {difs[0]} y {difs[-1]} días más que en 1961-1990, y 2026 ya es el año con más días de verano en {nombres}"
    else:
        tit = f"El verano suma entre {difs[0]} y {difs[-1]} días más al año que en 1961-1990 en las grandes series de AEMET: empieza antes y acaba más tarde"
    if len(tit) > 165:
        tit = f"El verano suma entre {difs[0]} y {difs[-1]} días más al año que en 1961-1990 en las grandes series de AEMET"
    pl = {"titular": tit,
          "subtitulo": next((h["dice"] for h in hechos if h["id"] == "ver_2026"), next(h["dice"] for h in hechos if h["id"] == "ver1_fechas")),
          "entradilla": hechos[0]["dice"],
          "cuerpo": [" ".join(h["dice"] for h in hechos if h["id"] in ("ver1", "ver1_fechas", "ver1_2026")),
                     " ".join(h["dice"] for h in hechos if h["id"] in ("ver1_def", "ver_ctrl"))],
          "claves": [hechos[0]["dice"]] + [h["dice"] for h in hechos if h["id"] in ("ver_2026", "ver1")]}
    cifras = [{"n": f"{difs[0]} a {difs[-1]}", "l": f"días más de verano al año en las {len(con61)} estaciones con serie desde 1961-1990 (AEMET)", "tono": "calor"},
              {"n": f"+{dif(lider)} días", "l": f"en {lider['nombre']}: {_dd(lider['base_dias'])} → {_dd(lider['rec_dias'])}", "tono": "calor"}]
    if recs:
        cifras.append({"n": str(len(recs)), "l": "estaciones donde 2026 ya es el año con más días de verano de su serie", "tono": "calor"})
    hid = f"{R.HOY.isoformat()}-verano-largo"
    h = R.historia("verano_largo", hid, "Análisis · el verano se estira", "calor", 66, hechos, pl, cifras, FUENTE_D,
                   V.get("definicion", "") + " " + V.get("metodo", ""), V.get("limites", []), PAG_ANALISIS)
    h["seccion"] = SECCION
    try:
        h["grafico"] = _grafico_verano(R, (recs_largos or [lider])[0], hid)
    except Exception as e:  # noqa: BLE001
        R.LOG.append(f"analisis/verano gráfico: {e}")
    red = hechos[0]
    for x in filas:
        cod = x["cod"]
        hv = _hechos_verano(R, x, "verp", con_prov=False)
        if x["base"] == "1961-1990":
            hv.append(red)
        hv.append(next(h for h in hechos if h["id"] == "ver_ctrl"))
        d = dif(x)
        a = x.get("actual") or {}
        if a.get("mas_dias"):
            tit_p = f"2026 ya es el año con más días de verano en {x['nombre']} desde {x['desde']}: {a['dias']}, con datos validados hasta el {_fecha_iso(a['datos_hasta'])}"
        else:
            tit_p = (f"El verano en {x['nombre']} suma {d} días más al año que en {x['base']}: empieza el {_fecha_md(x['rec_ini'])} y acaba el "
                     f"{_fecha_md(x['rec_fin'])}, de media")
        ent = hv[0]
        sub = next((z["dice"] for z in hv if z["id"] == "verp_2026"), hv[1]["dice"])
        plv = {"titular": tit_p, "subtitulo": sub, "entradilla": ent["dice"],
               "cuerpo": [" ".join(z["dice"] for z in hv[1:] if z["dice"] != sub)], "claves": [z["dice"] for z in hv[:3]]}
        v = {"provincia": R.nprov(cod), "slug": R.PROV[cod][1], "hechos": hv, "plantilla": plv,
             "cifras": [{"n": f"+{d} días", "l": f"de verano al año en {x['nombre']}, 2011-2025 frente a {x['base']}", "tono": "calor"},
                        {"n": f"{_fecha_md(x['base_ini'])} → {_fecha_md(x['rec_ini'])}", "l": "inicio medio del verano", "tono": "calor"}]
             + ([{"n": f"{a['dias']} días", "l": f"de verano en 2026 (datos hasta el {_fecha_iso(a['datos_hasta'])})" + (", récord de su serie" if a.get("mas_dias") else ""),
                  "tono": "calor"}] if a.get("dias") else []),
             "puntos": round(min(70.0, 50 + d / 3 + (8 if a.get("mas_dias") else 0)), 1)}
        try:
            v["grafico"] = _grafico_verano(R, x, f"{hid}-{cod}")
        except Exception as e:  # noqa: BLE001
            R.LOG.append(f"analisis/verano gráfico {cod}: {e}")
        h["provincias"][cod] = v
    return [h]


# ============================================================================ 6. danas_lluvia (series diarias + catálogo)
def g_danas_lluvia(R, D):
    Dn = R.leer(R.DOCS / "prensa" / "analisis" / "danas.json", {}) or {}
    est = Dn.get("estaciones") or {}
    filas = [dict(est[i], id=i) for i in (Dn.get("provincias") or {}).values() if i in est]
    cat = ((Dn.get("resumen") or {}).get("catalogo") or {})
    c1, c2 = cat.get("1961-1990") or {}, cat.get("1996-2025") or {}
    if len(filas) < 5 or not c1 or not c2:
        return []
    n = len(filas)
    FD = Dn.get("fuente", FUENTE_DANA)
    cambia = lambda a, b: (b - a) / a if a else 0.0  # noqa: E731
    sube_inv = [x for x in filas if cambia(x["p1"]["dic_may"], x["p2"]["dic_may"]) >= 0.05]
    baja_oto = [x for x in filas if cambia(x["p1"]["otono"], x["p2"]["otono"]) <= -0.05]
    de_n = lambda k: f"las {n}" if k == n else f"{k} de las {n}"  # noqa: E731
    r0 = lambda v: str(_dd(v))  # noqa: E731
    hechos = [
        R.hecho("dl_cat", f"El catálogo de DANAs del observatorio cuenta de media {R.f1(c2['dic_may'])} días con DANA al año entre diciembre y mayo en 1996-2025, "
                          f"frente a {R.f1(c1['dic_may'])} en 1961-1990; en otoño, {R.f1(c2['otono'])} frente a {R.f1(c1['otono'])}.", FD,
                [R.f1(c2["dic_may"]), R.f1(c1["dic_may"]), R.f1(c2["otono"]), R.f1(c1["otono"]), "1996", "2025", "1961", "1990"]),
        R.hecho("dl_inv", f"Entre diciembre y mayo cae más lluvia en días con DANA que en 1961-1990 en {de_n(len(sube_inv))} estaciones de AEMET con serie diaria "
                          "larga que ha analizado el observatorio, sobre todo porque hay más días con DANA: la lluvia por día de DANA sube en unas y baja en otras.",
                FD, [str(len(sube_inv)), str(n), "1961", "1990"]),
        R.hecho("dl_oto", f"En otoño, con algo más de días con DANA, la lluvia que dejan es menor que en 1961-1990 en {de_n(len(baja_oto))} estaciones.",
                FD, [str(len(baja_oto)), str(n), "1961", "1990"]),
        R.hecho("dl_lim", "Las estaciones comparten los mismos días de DANA y el cambio no es concluyente estadísticamente. Lluvia con DANA es la que mide AEMET "
                          "en la estación el día que hay una DANA sobre la península o su entorno, según el catálogo del observatorio (un reanálisis, no una "
                          "medida), o el día siguiente.", FD, []),
    ]
    tit = (f"Más días de DANA en invierno y primavera y menos lluvia con DANA en otoño: {n} series de AEMET y el catálogo de DANAs del observatorio, "
           "1961-1990 frente a 1996-2025")
    pl = {"titular": tit, "subtitulo": hechos[2]["dice"], "entradilla": hechos[0]["dice"] + " " + hechos[1]["dice"],
          "cuerpo": [hechos[3]["dice"]], "claves": [h["dice"] for h in hechos[:3]]}
    cifras = [{"n": f"{R.f1(c1['dic_may'])} → {R.f1(c2['dic_may'])}", "l": "días con DANA al año entre diciembre y mayo, 1961-1990 → 1996-2025 (catálogo del observatorio)", "tono": "lluvia"},
              {"n": f"{len(baja_oto)} de {n}", "l": "estaciones con menos lluvia con DANA en otoño", "tono": "lluvia"}]
    hid = f"{R.HOY.isoformat()}-danas-lluvia"
    h = R.historia("danas_lluvia", hid, "Análisis · lo que dejan las DANAs", "lluvia", 52, hechos, pl, cifras, FD,
                   Dn.get("definicion", "") + " " + Dn.get("metodo", ""), Dn.get("limites", []), PAG_ANALISIS)
    h["seccion"] = SECCION
    et = {"oto": "Sep-nov", "inv": "Dic-may", "ver": "Jun-ago"}

    def graf(x, nombre):
        ver1 = max(0.0, x["p1"]["dana"] - x["p1"]["otono"] - x["p1"]["dic_may"])
        ver2 = max(0.0, x["p2"]["dana"] - x["p2"]["otono"] - x["p2"]["dic_may"])
        return _barras_pares(R, [("inv", round(x["p1"]["dic_may"], 1), round(x["p2"]["dic_may"], 1)), ("ver", round(ver1, 1), round(ver2, 1)),
                                 ("oto", round(x["p1"]["otono"], 1), round(x["p2"]["otono"], 1))], nombre,
                             f"Lluvia con DANA en {x['nombre']}, mm al año",
                             f"Estación de AEMET de {x['nombre']}: lluvia media al año en los días con DANA (y el siguiente). Días con DANA: catálogo del "
                             "observatorio (reanálisis NCEP/NCAR). Fuente: AEMET OpenData. Cálculo: calentamientoglobal.es.",
                             et, MED_LL, R.LLUVIA, "1961-1990", "1996-2025", "mm")
    try:
        h["grafico"] = graf(max(filas, key=lambda x: x["p2"]["dic_may"] - x["p1"]["dic_may"]), hid)
    except Exception as e:  # noqa: BLE001
        R.LOG.append(f"analisis/danas gráfico: {e}")
    for x in filas:
        cod = x["cod"]
        a, b = x["p1"], x["p2"]
        nn = x["nombre"]
        oto_t = (f"de {r0(a['otono'])} mm a {r0(b['otono'])} mm" if abs(cambia(a["otono"], b["otono"])) >= 0.05 else f"apenas cambia ({r0(b['otono'])} mm)")
        hv = [R.hecho("dlp", f"En la estación de AEMET de {nn}, la lluvia que cae con una DANA entre diciembre y mayo pasa de {r0(a['dic_may'])} mm al año "
                             f"en 1961-1990 a {r0(b['dic_may'])} mm en 1996-2025, y la de otoño, {oto_t}.", FD,
                      [r0(a["dic_may"]) + " mm", r0(b["dic_may"]) + " mm", r0(a["otono"]) + " mm", r0(b["otono"]) + " mm", "1961", "1990", "1996", "2025"],
                      lugar=nn, liga=[r0(a["dic_may"]), r0(b["dic_may"]), r0(a["otono"]), r0(b["otono"])]),
              R.hecho("dlp_dia", f"Por cada día con DANA (o el siguiente) entre diciembre y mayo caen de media {R.f1(b['por_dia_dic_may'])} mm en {nn}, frente a "
                                 f"{R.f1(a['por_dia_dic_may'])} en 1961-1990; en otoño, {R.f1(b['por_dia_otono'])} frente a {R.f1(a['por_dia_otono'])}.", FD,
                      [R.f1(b["por_dia_dic_may"]), R.f1(a["por_dia_dic_may"]), R.f1(b["por_dia_otono"]), R.f1(a["por_dia_otono"])], lugar=nn),
              R.hecho("dlp_max", f"El día con DANA más lluvioso de 1996-2025 en {nn} dejó {R.f1(b['max'])} mm ({_fecha_iso(b['max_fecha'])} de {b['max_fecha'][:4]}); "
                                 f"el de 1961-1990, {R.f1(a['max'])} mm ({_fecha_iso(a['max_fecha'])} de {a['max_fecha'][:4]}).", FD,
                      [R.f1(b["max"]), R.f1(a["max"]), b["max_fecha"][:4], a["max_fecha"][:4]], lugar=nn)] + [hechos[0], hechos[3]]
        tit_p = (f"Las DANAs dejan en {nn} {r0(b['dic_may'])} mm al año entre diciembre y mayo, frente a {r0(a['dic_may'])} en 1961-1990"
                 + (f"; en otoño, {r0(b['otono'])} frente a {r0(a['otono'])}" if abs(cambia(a["otono"], b["otono"])) >= 0.05 else ""))
        plv = {"titular": tit_p, "subtitulo": hv[1]["dice"], "entradilla": hv[0]["dice"], "cuerpo": [hv[2]["dice"], hechos[0]["dice"] + " " + hechos[3]["dice"]],
               "claves": [z["dice"] for z in hv[:3]]}
        v = {"provincia": R.nprov(cod), "slug": R.PROV[cod][1], "hechos": hv, "plantilla": plv,
             "cifras": [{"n": f"{r0(a['dic_may'])} → {r0(b['dic_may'])} mm", "l": f"lluvia con DANA entre diciembre y mayo en {nn}", "tono": "lluvia"},
                        {"n": f"{r0(a['otono'])} → {r0(b['otono'])} mm", "l": "en otoño", "tono": "lluvia"}],
             "puntos": 50.0}
        try:
            v["grafico"] = graf(x, f"{hid}-{cod}")
        except Exception as e:  # noqa: BLE001
            R.LOG.append(f"analisis/danas gráfico {cod}: {e}")
        h["provincias"][cod] = v
    return [h]


def generar(R, D):
    out = []
    for g in (g_verano_largo, g_danas_lluvia, g_otono_serie, g_torrencial, g_dana_largo):
        try:
            out.extend(g(R, D) or [])
        except Exception as e:  # noqa: BLE001
            R.LOG.append(f"analisis/{g.__name__}: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
    return out
