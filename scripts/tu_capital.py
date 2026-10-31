#!/usr/bin/env python3
"""«Tu capital, año a año»: serie larga de temperatura media anual de cada capital con estación AEMET.

Para cada capital con serie larga (47; las 5 de SIN_SERIE no tienen) calcula, solo con valores de AEMET que ya
están en el repositorio (nada de APIs, nada de claves):
  · la media anual de cada año con los 12 meses válidos (Historia.mensual de balance_mensual.py);
  · la normal 1991-2020 y la anomalía de cada año;
  · la tendencia (mínimos cuadrados, t >= 2) y un control de homogeneidad frente a ERA5;
  · cómo va el año en curso con los diarios validados y una estimación de cómo acabará (regresión, 90 %);
  · el ranking de años, los textos y los ficheros descargables.

Escribe docs/tu-capital/:
  <slug>.json · <slug>.csv · <slug>.png (1600x900) · <slug>-franjas.png (1600x400)
  index.json · nacional.json     (patrocinio.json lo escribe una persona: aquí solo se lee)

Uso: python scripts/tu_capital.py [--solo slug,slug] [--sin-png]
Variables: TUCAPITAL_HOY=AAAA-MM-DD (ensayos).
Licencia de los datos publicados: CC BY 4.0 (la información de partida es de AEMET).
"""
from __future__ import annotations

import argparse
import calendar
import json
import math
import os
import sys
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from balance_mensual import (  # noqa: E402  (se reutiliza, no se copia)
    ARCH, DOCS, ESTACIONES, INICIO_TENDENCIA, MIN_NORMAL, MIN_TENDENCIA, NORMAL, PROVINCIA, SIN_SERIE,
    Historia, f1, r1, tendencia,
)

SALIDA = DOCS / "tu-capital"
ERA5 = ARCH / "era5"
PAGINA = "https://calentamientoglobal.es/cambio-climatico-en-{slug}/"
PAGES = "https://davidbebow.github.io/temperaturas-mar-espana/tu-capital/"
FUENTE = "AEMET (valores climatológicos mensuales y diarios validados de cada estación) · cálculo propio de calentamientoglobal.es"
LICENCIA = "CC BY 4.0"

HOY = date.fromisoformat(os.environ["TUCAPITAL_HOY"]) if os.environ.get("TUCAPITAL_HOY") else datetime.now(timezone.utc).date()
ANIO_CIERRE = HOY.year - 1          # último año cerrado
ANIO_ENCURSO = HOY.year

PRIMER_ANIO_BUSQUEDA = 1900
MIN_ANIOS_PUBLICAR = 30             # años válidos para publicar la capital
VENTANA_INICIO = (30, 25)           # 25 años válidos en los 30 siguientes al primer año
T_SIGNIFICATIVA = 2.0
MIN_DIAS_ENCURSO = 240
MIN_FRAC_ENCURSO = 0.80
MIN_ANIOS_NORMAL_PARCIAL = 24
COBERTURA_DIAS = 0.90
MIN_ANIOS_REGRESION = 20
UMBRAL_SALTO = 0.5                  # °C: salto entre décadas (o entre bloques de 15 años) en estación − ERA5
MIN_ANIOS_DECADA = 5
MIN_DIAS_ERA5 = 350
MIN_ANIOS_ERA5 = 20
MARGEN_RECORD = 0.2

# código INE de provincia → slug de la página de WordPress (sin «cambio-climatico-en-»)
SLUG = {
    "01": "alava", "02": "albacete", "03": "alicante", "04": "almeria", "05": "avila", "06": "badajoz",
    "07": "baleares", "08": "barcelona", "09": "burgos", "10": "caceres", "11": "cadiz", "12": "castellon",
    "13": "ciudad-real", "14": "cordoba", "15": "a-coruna", "16": "cuenca", "17": "girona", "18": "granada",
    "20": "gipuzkoa", "21": "huelva", "22": "huesca", "23": "jaen", "24": "leon", "25": "lleida",
    "26": "la-rioja", "27": "lugo", "28": "madrid", "29": "malaga", "30": "murcia", "31": "navarra",
    "32": "ourense", "35": "las-palmas", "36": "pontevedra", "37": "salamanca", "38": "santa-cruz-de-tenerife",
    "40": "segovia", "41": "sevilla", "42": "soria", "43": "tarragona", "44": "teruel", "45": "toledo",
    "46": "valencia", "47": "valladolid", "48": "bizkaia", "49": "zamora", "50": "zaragoza", "52": "melilla",
}
assert set(SLUG) == set(ESTACIONES), "el mapa cod → slug debe cubrir exactamente ESTACIONES"

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]

# Franjas de calentamiento: azul-rojo divergente, 8 tonos por lado (paleta de las franjas de Ed Hawkins)
PALETA = ["#08306b", "#08519c", "#2171b5", "#4292c6", "#6baed6", "#9ecae1", "#c6dbef", "#deebf7",
          "#fee0d2", "#fcbba1", "#fc9272", "#fb6a4a", "#ef3b2c", "#cb181d", "#a50f15", "#67000d"]
FONDO, TEXTO, SEC, ACENTO, DEST, HONDO, HUECO = "#0c2133", "#e8f1f8", "#9fb6c8", "#bfe6ff", "#ff7a45", "#163a55", "#2a4a63"


def log(m: str):
    print(m, flush=True)


# ----------------------------------------------------------------------------
# utilidades
# ----------------------------------------------------------------------------
def media(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else None


def cuantil(xs: list[float], q: float) -> float:
    """Cuantil por interpolación lineal (sin suponer normalidad)."""
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    pos = q * (len(s) - 1)
    i = int(math.floor(pos))
    j = min(i + 1, len(s) - 1)
    return s[i] + (s[j] - s[i]) * (pos - i)


def fecha_larga(d: date) -> str:
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def palabras(t: str) -> int:
    return len(t.split())


def deca_txt(d: int) -> str:
    return str(d % 100) if d < 2000 else str(d)


def leer_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def escribir_json(p: Path, obj, indent=None):
    """Escribe solo si cambia algo distinto de «generado» (así el workflow no hace commit por nada)."""
    p.parent.mkdir(parents=True, exist_ok=True)
    prev = leer_json(p)
    if isinstance(prev, dict) and isinstance(obj, dict):
        a = {k: v for k, v in prev.items() if k != "generado"}
        b = {k: v for k, v in obj.items() if k != "generado"}
        if a == b:
            obj = dict(obj)
            obj["generado"] = prev.get("generado", obj.get("generado"))
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=indent, separators=(",", ":") if indent is None else None) + "\n",
                 encoding="utf-8")


def color_franja(a: float, escala: float) -> str:
    i = int(math.floor((a + escala) / (2 * escala) * 16))
    return PALETA[min(max(i, 0), 15)]


# ----------------------------------------------------------------------------
# serie anual
# ----------------------------------------------------------------------------
def serie_anual(hist: Historia, ide: str) -> dict[int, dict]:
    out = {}
    for anio in range(PRIMER_ANIO_BUSQUEDA, ANIO_CIERRE + 1):
        tms, txs, tns, ps = [], [], [], []
        ok = True
        for mes in range(1, 13):
            m = hist.mensual(ide, anio, mes)
            if not m or m.get("tm") is None or m.get("tx") is None or m.get("tn") is None:
                ok = False
                break
            tms.append(m["tm"])
            txs.append(m["tx"])
            tns.append(m["tn"])
            ps.append(m.get("p"))
        if not ok:
            continue
        out[anio] = {"tm": sum(tms) / 12, "tx": sum(txs) / 12, "tn": sum(tns) / 12,
                     "p": sum(ps) if all(p is not None for p in ps) else None}
    return out


def inicio_serie(validos: list[int]) -> int | None:
    """Primer año válido seguido de al menos 25 años válidos en los 30 siguientes."""
    vs = set(validos)
    for y in sorted(validos):
        if sum(1 for k in range(y + 1, y + VENTANA_INICIO[0] + 1) if k in vs) >= VENTANA_INICIO[1]:
            return y
    return None


# ----------------------------------------------------------------------------
# homogeneidad frente a ERA5
# ----------------------------------------------------------------------------
def era5_anual(cod: str) -> dict[int, float] | None:
    import csv
    import gzip
    import io
    carpeta = ERA5 / cod
    fich = sorted(carpeta.glob("hasta_*_era5.csv.gz")) if carpeta.exists() else []
    if not fich:
        return None
    acum: dict[int, list[float]] = {}
    with gzip.open(fich[-1]) as fh:
        for r in csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8")):
            try:
                tx, tn = float(r["tmax"]), float(r["tmin"])
            except (ValueError, KeyError, TypeError):
                continue
            acum.setdefault(int(r["fecha"][:4]), []).append((tx + tn) / 2)
    return {y: sum(v) / len(v) for y, v in acum.items() if len(v) >= MIN_DIAS_ERA5}


def homogeneidad(cod: str, serie: dict[int, dict]) -> dict:
    era = era5_anual(cod)
    if era is None:
        return {"estado": "sin control", "salto_decada": None, "era5_disponible": False, "diferencia_media": None,
                "anios_comparados": 0, "por_decada": {}, "motivo": "no hay fichero ERA5 de la provincia"}
    dif = {y: (s["tx"] + s["tn"]) / 2 - era[y] for y, s in serie.items() if y in era}
    if len(dif) < MIN_ANIOS_ERA5:
        return {"estado": "sin control", "salto_decada": None, "era5_disponible": True,
                "diferencia_media": r2(media(dif.values())) if dif else None, "anios_comparados": len(dif),
                "por_decada": {}, "motivo": f"solo {len(dif)} años en común con ERA5 (mínimo {MIN_ANIOS_ERA5})"}
    por = {}
    for y, d in dif.items():
        por.setdefault(y // 10 * 10, []).append(d)
    dec = {k: sum(v) / len(v) for k, v in por.items() if len(v) >= MIN_ANIOS_DECADA}
    salto, mayor = None, 0.0
    ks = sorted(dec)
    for a, b in zip(ks, ks[1:]):
        if b - a != 10:
            continue
        c = abs(dec[b] - dec[a])
        if c > UMBRAL_SALTO and c > mayor:
            salto, mayor = b, c
    motivo = None
    if salto is not None:
        motivo = f"la diferencia estación − ERA5 cambia {mayor:.2f} °C entre la década de {salto - 10} y la de {salto}"
    # últimos 15 años frente a los 15 anteriores
    ult = [d for y, d in dif.items() if ANIO_CIERRE - 14 <= y <= ANIO_CIERRE]
    ant = [d for y, d in dif.items() if ANIO_CIERRE - 29 <= y <= ANIO_CIERRE - 15]
    if len(ult) >= 10 and len(ant) >= 10:
        c = abs(sum(ult) / len(ult) - sum(ant) / len(ant))
        if c > UMBRAL_SALTO and salto is None:
            salto = (ANIO_CIERRE - 14) // 10 * 10
            motivo = f"la diferencia estación − ERA5 de los últimos 15 años cambia {c:.2f} °C frente a los 15 anteriores"
    return {"estado": "dudosa" if salto is not None else "ok", "salto_decada": salto, "era5_disponible": True,
            "diferencia_media": r2(media(dif.values())), "anios_comparados": len(dif),
            "por_decada": {str(k): r2(v) for k, v in sorted(dec.items())}, "motivo": motivo}


def r2(v):
    return None if v is None else round(float(v), 2)


# ----------------------------------------------------------------------------
# el año en curso
# ----------------------------------------------------------------------------
def en_curso(hist: Historia, ide: str, serie: dict[int, dict], normal_tm: float) -> dict | None:
    dias = hist.diarios.get(ide) or {}
    validos = {}
    for k, r in dias.items():
        if k.startswith(f"{ANIO_ENCURSO}-") and r[0] is not None and r[1] is not None:
            validos[k] = (r[0] + r[1]) / 2
    if not validos:
        return None
    ultimo = max(validos)
    hasta = date.fromisoformat(ultimo)
    transcurridos = hasta.timetuple().tm_yday
    n = len(validos)
    if n < MIN_DIAS_ENCURSO or n < MIN_FRAC_ENCURSO * transcurridos:
        return None
    conjunto = sorted((int(k[5:7]), int(k[8:10])) for k in validos)

    def parcial(anio: int):
        xs = []
        for m, d in conjunto:
            r = dias.get(f"{anio}-{m:02d}-{d:02d}")
            if r and r[0] is not None and r[1] is not None:
                xs.append((r[0] + r[1]) / 2)
        if len(xs) < COBERTURA_DIAS * len(conjunto):
            return None
        return sum(xs) / len(xs)

    p_normal = {y: parcial(y) for y in range(NORMAL[0], NORMAL[1] + 1)}
    p_normal = {y: v for y, v in p_normal.items() if v is not None}
    if len(p_normal) < MIN_ANIOS_NORMAL_PARCIAL:
        return None
    ref = sum(p_normal.values()) / len(p_normal)
    anom = sum(validos.values()) / n - ref
    out = {"anio": ANIO_ENCURSO, "hasta": ultimo, "dias": n, "anomalia": r1(anom), "estimacion_tm": None,
           "estimacion_min": None, "estimacion_max": None, "puesto_si_acaba_asi": None, "seria_record": None,
           "n_anios_regresion": 0}
    pares = []
    for y, s in serie.items():
        if y < NORMAL[0]:
            continue
        p = parcial(y)
        if p is not None:
            pares.append((p - ref, s["tm"] - normal_tm))
    out["n_anios_regresion"] = len(pares)
    if len(pares) < MIN_ANIOS_REGRESION:
        return out
    mx, my = media(x for x, _ in pares), media(y for _, y in pares)
    sxx = sum((x - mx) ** 2 for x, _ in pares)
    if sxx == 0:
        return out
    b = sum((x - mx) * (y - my) for x, y in pares) / sxx
    a = my - b * mx
    res = [y - (a + b * x) for x, y in pares]
    pred = a + b * anom
    est = normal_tm + pred
    emin, emax = normal_tm + pred + cuantil(res, 0.05), normal_tm + pred + cuantil(res, 0.95)
    out["estimacion_tm"], out["estimacion_min"], out["estimacion_max"] = r1(est), r1(emin), r1(emax)
    cerrados = [r1(s["tm"]) for s in serie.values()]
    out["puesto_si_acaba_asi"] = 1 + sum(1 for v in cerrados if v > r1(est))
    out["seria_record"] = bool(cerrados) and (r1(emin) - max(cerrados) >= MARGEN_RECORD - 1e-9)
    return out


# ----------------------------------------------------------------------------
# una capital
# ----------------------------------------------------------------------------
def calcular_capital(hist: Historia, cod: str) -> dict:
    ide, ciudad, estacion, tipo = ESTACIONES[cod]
    slug = SLUG[cod]
    bruta = serie_anual(hist, ide)
    ini = inicio_serie(sorted(bruta))
    res = {"cod": cod, "slug": slug, "ciudad": ciudad, "provincia": PROVINCIA[cod], "estacion": estacion,
           "indicativo": ide, "tipo": tipo}
    if ini is None:
        res["no_publicada"] = "ningún año válido va seguido de 25 años válidos en los 30 siguientes"
        return res
    serie = {y: v for y, v in bruta.items() if y >= ini}
    if len(serie) < MIN_ANIOS_PUBLICAR:
        res["no_publicada"] = f"solo {len(serie)} años válidos desde {ini} (mínimo {MIN_ANIOS_PUBLICAR})"
        return res
    fin = max(serie)
    huecos = [y for y in range(ini, fin + 1) if y not in serie]
    en_normal = [serie[y]["tm"] for y in range(NORMAL[0], NORMAL[1] + 1) if y in serie]
    if len(en_normal) < MIN_NORMAL:
        res["no_publicada"] = f"solo {len(en_normal)} años válidos en {NORMAL[0]}-{NORMAL[1]} (mínimo {MIN_NORMAL})"
        return res
    normal = sum(en_normal) / len(en_normal)
    res.update({"inicio": ini, "fin": fin, "anios_validos": len(serie), "huecos": huecos,
                "normal_tm": r1(normal), "anios_normal": len(en_normal), "_normal": normal, "_serie": serie})

    # tendencia
    desde = max(INICIO_TENDENCIA, ini)
    pares = [(y, s["tm"]) for y, s in serie.items() if y >= desde]
    tend = {"desde": desde, "pendiente_decada": None, "calentamiento": None, "t": None, "significativa": False,
            "calculada": False, "afirmada": False, "anios": len(pares)}
    if len(pares) >= MIN_TENDENCIA:
        t = tendencia(pares)
        if t and t.get("t") is not None:
            tend.update({"pendiente_decada": r1(t["pendiente"] * 10), "calentamiento": r1(t["pendiente"] * (fin - desde)),
                         "t": round(t["t"], 2), "significativa": t["t"] >= T_SIGNIFICATIVA, "calculada": True})
    homo = homogeneidad(cod, serie)
    tend["afirmada"] = bool(tend["significativa"] and homo["estado"] != "dudosa")
    res["tendencia"], res["homogeneidad"] = tend, homo

    # anomalías (diferencias entre cifras ya redondeadas)
    rn = r1(normal)
    res["serie"] = [{"anio": y, "tm": r1(s["tm"]), "tx": r1(s["tx"]), "tn": r1(s["tn"]),
                     "anomalia": r1(r1(s["tm"]) - rn), "p": None if s["p"] is None else r1(s["p"])}
                    for y, s in sorted(serie.items())]

    # ranking
    orden = sorted(res["serie"], key=lambda f: (-f["tm"], -serie[f["anio"]]["tm"]))
    cuenta = {}
    for f in res["serie"]:
        cuenta[f["tm"]] = cuenta.get(f["tm"], 0) + 1

    def fila(f, puesto):
        return {"puesto": puesto, "anio": f["anio"], "tm": f["tm"], "empate": cuenta[f["tm"]] > 1}

    def con_puestos(lista):
        out, previo, pp = [], None, 0
        for i, f in enumerate(lista, 1):
            if f["tm"] != previo:
                pp, previo = i, f["tm"]
            out.append(fila(f, pp))
        return out

    res["top10"] = con_puestos(orden)[:10]
    frios = sorted(res["serie"], key=lambda f: (f["tm"], serie[f["anio"]]["tm"]))
    res["top3_frios"] = con_puestos(frios)[:3]
    mc = res["top10"][0]
    res["mas_calido"] = {"anio": mc["anio"], "tm": mc["tm"], "empate": mc["empate"],
                         "anios": [f["anio"] for f in res["serie"] if f["tm"] == mc["tm"]]}
    res["calidos_desde_2000"] = sum(1 for f in res["top10"] if f["anio"] >= 2000)
    res["empate_en_el_corte"] = len(orden) > 10 and orden[10]["tm"] == orden[9]["tm"]
    a = [s["tm"] for y, s in serie.items() if 2016 <= y <= 2025]
    b = [s["tm"] for y, s in serie.items() if 1961 <= y <= 1990]
    # 2016-2025 solo tiene 10 años: se exigen 8; 1961-1990, 25 de 30
    res["media_2016_2025"] = r1(sum(a) / len(a)) if len(a) >= 8 and len(b) >= 25 else None
    res["media_1961_1990"] = r1(sum(b) / len(b)) if len(a) >= 8 and len(b) >= 25 else None

    res["en_curso"] = en_curso(hist, ide, serie, normal)
    return res


# ----------------------------------------------------------------------------
# textos
# ----------------------------------------------------------------------------
def donde(c: dict) -> str:
    if c["tipo"] == "referencia":
        return f"en el {c['estacion']} (estación de referencia de {c['ciudad']})"
    return f"en la estación de {c['ciudad']}"


def signo_txt(v: float) -> str:
    if v == 0:
        return "en la normal"
    return f"{f1(abs(v))} °C {'por encima' if v > 0 else 'por debajo'} de la normal"


def frase_tendencia(c: dict) -> str:
    t, h = c["tendencia"], c["homogeneidad"]
    if h["estado"] == "dudosa":
        return f"La serie tiene un salto hacia los años {deca_txt(h['salto_decada'])} que puede deberse a un cambio en la estación; no damos tendencia."
    if not t["calculada"]:
        return f"Con {t['anios']} años desde {t['desde']} no calculamos tendencia (mínimo {MIN_TENDENCIA})."
    if not t["significativa"]:
        return "La tendencia no es estadísticamente significativa."
    return f"La serie se ha calentado {f1(t['calentamiento'])} °C desde {t['desde']} (tendencia significativa)."


def textos_capital(c: dict) -> dict:
    mc, ec = c["mas_calido"], c["en_curso"]
    empate = ""
    if mc["empate"]:
        otros = [str(a) for a in mc["anios"]]
        anios_txt = " y ".join([", ".join(otros[:-1]), otros[-1]]) if len(otros) > 2 else " y ".join(otros)
        s1 = f"Entre {c['inicio']} y {c['fin']}, los años más cálidos {donde(c)} fueron {anios_txt} (empatados, {f1(mc['tm'])} °C de media)."
    else:
        s1 = f"Entre {c['inicio']} y {c['fin']}, el año más cálido {donde(c)} fue {mc['anio']} ({f1(mc['tm'])} °C de media)."
    k = c["calidos_desde_2000"]
    s2 = ("Los 10 años más cálidos son todos de 2000 en adelante." if k == 10 else
          "Ninguno de los 10 años más cálidos es de 2000 en adelante." if k == 0 else
          f"{k} de los 10 años más cálidos son de 2000 en adelante.")
    s3 = frase_tendencia(c)
    s4 = ""
    if ec:
        s4 = f"Hasta el {fecha_larga(date.fromisoformat(ec['hasta']))}, {ec['anio']} va {signo_txt(ec['anomalia'])} 1991-2020."
    fuente = "Fuente: AEMET."
    # entre 30 y 45 palabras: se prueba de lo más completo a lo más corto
    candidatos = [[s1, s2, s3, s4, fuente], [s1, s3, s4, fuente], [s1, s2, s3, fuente], [s1, s3, fuente], [s1, s4, fuente]]
    resumen = None
    for cand in candidatos:
        t = " ".join(x for x in cand if x)
        if 30 <= palabras(t) <= 45:
            resumen = t
            break
    if resumen is None:
        t = " ".join(x for x in [s1, s3, fuente] if x)
        resumen = t
    metodo = (f"Media de los 12 meses de cada año con valores de AEMET {donde(c)}; anomalía frente a la normal "
              f"{NORMAL[0]}-{NORMAL[1]} ({c['anios_normal']} años válidos). Tendencia por mínimos cuadrados desde {c['tendencia']['desde']}, "
              f"solo si t ≥ 2 y sin salto frente a ERA5. Estimación del año en curso por regresión con intervalo del 90 %. "
              f"Franjas al estilo de las de Ed Hawkins.")
    return {"titular": f"El clima de {c['ciudad']}, año a año desde {c['inicio']}", "resumen": resumen, "metodo_corto": metodo}


# ----------------------------------------------------------------------------
# salidas: JSON, CSV, PNG
# ----------------------------------------------------------------------------
def json_capital(c: dict, escala: float, generado: str) -> dict:
    slug = c["slug"]
    base = PAGES + slug
    out = {k: c[k] for k in ("cod", "provincia", "ciudad", "estacion", "indicativo", "tipo", "slug", "inicio", "fin",
                              "anios_validos", "huecos", "normal_tm", "anios_normal")}
    out["escala_franjas"] = escala
    for k in ("serie", "top10", "top3_frios", "mas_calido", "calidos_desde_2000", "empate_en_el_corte",
              "media_2016_2025", "media_1961_1990", "tendencia", "homogeneidad"):
        out[k] = c[k]
    out["en_curso"] = c["en_curso"]
    out["textos"] = c["textos"]
    out["generado"] = generado
    out["fuente"] = FUENTE
    out["licencia"] = LICENCIA
    out["urls"] = {"pagina": PAGINA.format(slug=slug), "json": base + ".json", "csv": base + ".csv", "png": base + ".png",
                   "franjas_png": base + "-franjas.png", "embed": PAGES + f"embed.html?p={slug}"}
    return out


def escribir_csv(c: dict, p: Path):
    lin = [f"# Fuente: AEMET, cálculo de calentamientoglobal.es, {LICENCIA}, {PAGINA.format(slug=c['slug'])}", "anio,tm,tx,tn,anomalia,p"]
    for f in c["serie"]:
        lin.append(",".join(["" if v is None else str(v) for v in (f["anio"], f["tm"], f["tx"], f["tn"], f["anomalia"], f["p"])]))
    p.write_text("\n".join(lin) + "\n", encoding="utf-8")


def logo_patrocinio(slug: str, pat: dict):
    ent = pat.get(slug) if isinstance(pat, dict) else None
    if not ent or not ent.get("logo_url"):
        return None
    try:
        import io

        from PIL import Image
        req = urllib.request.Request(ent["logo_url"], headers={"User-Agent": "calentamientoglobal.es/tu-capital"})
        with urllib.request.urlopen(req, timeout=30) as r:
            im = Image.open(io.BytesIO(r.read())).convert("RGBA")
        im.thumbnail((260, 70))
        import numpy as np
        return np.asarray(im)
    except Exception as e:  # el logotipo nunca debe tumbar la pasada
        log(f"   aviso: logotipo de {slug} no disponible ({e})")
        return None


def pie(c: dict) -> str:
    return f"calentamientoglobal.es/cambio-climatico-en-{c['slug']}/ · datos AEMET · {LICENCIA} · {c['ciudad']}, {c['inicio']}-{c['fin']}"


def dibujar(c: dict, escala: float, carpeta: Path, pat: dict):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    plt.rcParams["font.family"] = "DejaVu Sans"
    logo = logo_patrocinio(c["slug"], pat)
    serie = c["serie"]

    def poner_logo(fig, w, h):
        if logo is not None:
            fig.figimage(logo, xo=w - logo.shape[1] - 24, yo=10, zorder=10)

    # --- franjas 1600x400
    fig = plt.figure(figsize=(16, 4), dpi=100, facecolor=FONDO)
    ax = fig.add_axes([0.0, 0.22, 1.0, 0.62])
    ax.set_xlim(c["inicio"] - 0.5, c["fin"] + 0.5)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.add_patch(Rectangle((c["inicio"] - 0.5, 0), c["fin"] - c["inicio"] + 1, 1, color=HUECO, lw=0))
    for f in serie:
        ax.add_patch(Rectangle((f["anio"] - 0.5, 0), 1, 1, color=color_franja(f["anomalia"], escala), lw=0))
    fig.text(0.015, 0.92, c["textos"]["titular"], color=TEXTO, fontsize=19, fontweight="bold", va="center")
    fig.text(0.015, 0.165, str(c["inicio"]), color=TEXTO, fontsize=13, va="center")
    fig.text(0.985, 0.165, str(c["fin"]), color=TEXTO, fontsize=13, va="center", ha="right")
    fig.text(0.5, 0.165, f"Cada franja es un año · azul: más fresco, rojo: más cálido que la normal {NORMAL[0]}-{NORMAL[1]} · escala ±{f1(escala)} °C",
             color=SEC, fontsize=11, va="center", ha="center")
    fig.text(0.015, 0.05, pie(c), color=SEC, fontsize=11, va="center")
    poner_logo(fig, 1600, 400)
    fig.savefig(carpeta / f"{c['slug']}-franjas.png", dpi=100, facecolor=FONDO)
    plt.close(fig)

    # --- gráfico anual 1600x900
    fig = plt.figure(figsize=(16, 9), dpi=100, facecolor=FONDO)
    ax = fig.add_axes([0.065, 0.14, 0.915, 0.70], facecolor=FONDO)
    xs, ys = [], []
    previo = None
    for f in serie:
        if previo is not None and f["anio"] - previo > 1:
            xs.append(float("nan"))
            ys.append(float("nan"))
        xs.append(f["anio"])
        ys.append(f["tm"])
        previo = f["anio"]
    ax.axvspan(NORMAL[0] - 0.5, NORMAL[1] + 0.5, color=HONDO, alpha=0.55, lw=0, label=f"Normal {NORMAL[0]}-{NORMAL[1]}")
    ax.axhline(c["normal_tm"], color=ACENTO, lw=1.2, ls="--", alpha=0.8)
    ax.plot(xs, ys, color=SEC, lw=1.1, zorder=3)
    ax.scatter([f["anio"] for f in serie], [f["tm"] for f in serie], s=26, c=ACENTO, zorder=4, label="Media anual")
    t = c["tendencia"]
    if t["afirmada"]:
        pares = [(f["anio"], f["tm"]) for f in serie if f["anio"] >= t["desde"]]
        n = len(pares)
        mx, my = sum(x for x, _ in pares) / n, sum(y for _, y in pares) / n
        b = sum((x - mx) * (y - my) for x, y in pares) / sum((x - mx) ** 2 for x, _ in pares)
        a = my - b * mx
        ax.plot([t["desde"], c["fin"]], [a + b * t["desde"], a + b * c["fin"]], color="#fc9272", lw=2.4, zorder=5,
                label=f"Tendencia desde {t['desde']}: +{f1(t['calentamiento'])} °C")
    ec = c["en_curso"]
    x_max = c["fin"] + 1.5
    if ec and ec["estimacion_tm"] is not None:
        ax.errorbar([ec["anio"]], [ec["estimacion_tm"]], yerr=[[ec["estimacion_tm"] - ec["estimacion_min"]], [ec["estimacion_max"] - ec["estimacion_tm"]]],
                    fmt="o", color=DEST, ecolor=DEST, elinewidth=2.2, capsize=6, ms=11, zorder=6,
                    label=f"{ec['anio']}, si acaba así: {f1(ec['estimacion_tm'])} °C ({f1(ec['estimacion_min'])}-{f1(ec['estimacion_max'])})")
        x_max = ec["anio"] + 1.5
    ax.set_xlim(c["inicio"] - 1.5, x_max)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(SEC)
    ax.tick_params(colors=TEXTO, labelsize=13)
    ax.grid(axis="y", color=SEC, alpha=0.15, lw=0.8)
    ax.set_ylabel("Temperatura media anual (°C)", color=TEXTO, fontsize=14)
    leg = ax.legend(loc="upper left", frameon=False, fontsize=13, labelcolor=TEXTO)
    for tx in leg.get_texts():
        tx.set_color(TEXTO)
    fig.text(0.065, 0.945, c["textos"]["titular"], color=TEXTO, fontsize=26, fontweight="bold", va="center")
    sub = f"Estación: {c['estacion']}" + (" (estación de referencia de la provincia)" if c["tipo"] == "referencia" else "") + \
          f" · normal {NORMAL[0]}-{NORMAL[1]}: {f1(c['normal_tm'])} °C"
    fig.text(0.065, 0.895, sub, color=SEC, fontsize=14, va="center")
    fig.text(0.065, 0.045, pie(c), color=SEC, fontsize=13, va="center")
    poner_logo(fig, 1600, 900)
    fig.savefig(carpeta / f"{c['slug']}.png", dpi=100, facecolor=FONDO)
    plt.close(fig)


# ----------------------------------------------------------------------------
# nacional
# ----------------------------------------------------------------------------
def nota_nacional(caps: list[dict], generado_fecha: date) -> dict:
    desde70 = [c for c in caps if c["tendencia"]["afirmada"] and c["tendencia"]["desde"] == INICIO_TENDENCIA]
    posibles70 = [c for c in caps if c["tendencia"]["calculada"] and c["tendencia"]["desde"] == INICIO_TENDENCIA]
    medio = r1(sum(c["tendencia"]["calentamiento"] for c in desde70) / len(desde70)) if desde70 else None
    top = sorted(desde70, key=lambda c: -c["tendencia"]["calentamiento"])[:10]
    n2020 = sum(1 for c in caps if c["mas_calido"]["anio"] >= 2020 or any(a >= 2020 for a in c["mas_calido"]["anios"]))
    ecs = [c for c in caps if c["en_curso"] and c["en_curso"]["estimacion_tm"] is not None]
    n_rec = sum(1 for c in ecs if c["en_curso"]["seria_record"])
    n_top5 = sum(1 for c in ecs if c["en_curso"]["puesto_si_acaba_asi"] <= 5)
    hastas = sorted(c["en_curso"]["hasta"] for c in caps if c["en_curso"])
    datos = {
        "n_publicadas": len(caps),
        "n_serie_desde_1970": len(posibles70),
        "n_significativas_desde_1970": len(desde70),
        "calentamiento_medio_desde_1970": medio,
        "top10_calentamiento": [{"slug": c["slug"], "ciudad": c["ciudad"], "calentamiento": c["tendencia"]["calentamiento"]} for c in top],
        "n_mas_calido_2020_o_despues": n2020,
        "n_con_estimacion_encurso": len(ecs),
        "n_camino_de_record": n_rec,
        "n_camino_de_top5": n_top5,
        "encurso_hasta_min": hastas[0] if hastas else None,
        "encurso_hasta_max": hastas[-1] if hastas else None,
    }
    if medio is None:
        datos["texto"] = None
        return datos
    nom = ", ".join(f"{c['ciudad']} ({f1(c['tendencia']['calentamiento'])} °C)" for c in top[:5])
    t = f"Las capitales que más se han calentado desde {INICIO_TENDENCIA}. "
    t += (f"De las {len(posibles70)} capitales con serie de AEMET suficiente desde {INICIO_TENDENCIA}, {len(desde70)} se han calentado de forma "
          f"estadísticamente significativa, una media de {f1(medio)} °C entre {INICIO_TENDENCIA} y {ANIO_CIERRE}. "
          f"Las que más: {nom}. ")
    t += f"En {n2020} de las {len(caps)} capitales publicadas, el año más cálido de su serie es de 2020 o posterior. "
    if ecs:
        d1, d2 = date.fromisoformat(hastas[0]), date.fromisoformat(hastas[-1])
        rango = f"entre el {d1.day} y el {fecha_larga(d2)}" if (d1.month, d1.year) == (d2.month, d2.year) else f"entre el {fecha_larga(d1)} y el {fecha_larga(d2)}"
        t += (f"Con los diarios validados hasta fechas {rango} (según la estación), {n_rec} capitales van camino de su año más cálido "
              f"y {n_top5} de uno de sus cinco más cálidos. ")
    t += ("Método: media de los 12 meses de cada año con datos oficiales de AEMET, tendencia por mínimos cuadrados con t ≥ 2 y control de "
          "homogeneidad frente a ERA5; las series que empiezan después de 1970 no entran en esta cifra.")
    datos["texto"] = {"titular": f"Las capitales que más se han calentado desde {INICIO_TENDENCIA}", "nota": t, "palabras": palabras(t)}
    return datos


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo", default="", help="slugs separados por comas (pruebas)")
    ap.add_argument("--sin-png", action="store_true")
    args = ap.parse_args()
    solo = {s for s in args.solo.split(",") if s}

    SALIDA.mkdir(parents=True, exist_ok=True)
    pat_p = SALIDA / "patrocinio.json"
    if not pat_p.exists():
        pat_p.write_text("{}\n", encoding="utf-8")
    pat = leer_json(pat_p) or {}

    hist = Historia()
    caps, no_pub = [], []
    for cod in sorted(ESTACIONES):
        if cod in SIN_SERIE or (solo and SLUG[cod] not in solo):
            continue
        c = calcular_capital(hist, cod)
        if c.get("no_publicada"):
            no_pub.append({"slug": c["slug"], "ciudad": c["ciudad"], "motivo": c["no_publicada"]})
            log(f"NO publicada: {c['ciudad']}: {c['no_publicada']}")
            continue
        caps.append(c)
    if not caps:
        log("Nada que publicar.")
        return

    maxabs = max(abs(f["anomalia"]) for c in caps for f in c["serie"])
    escala = math.ceil(maxabs / 0.5) * 0.5
    generado = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for c in caps:
        c["textos"] = textos_capital(c)
        js = json_capital(c, escala, generado)
        escribir_json(SALIDA / f"{c['slug']}.json", js)
        escribir_csv(c, SALIDA / f"{c['slug']}.csv")
        if not args.sin_png:
            dibujar(c, escala, SALIDA, pat)

    idx = {
        "generado": generado, "escala_franjas": escala, "paleta_franjas": PALETA, "fuente": FUENTE, "licencia": LICENCIA,
        "capitales": [{
            "slug": c["slug"], "ciudad": c["ciudad"], "provincia": c["provincia"], "inicio": c["inicio"],
            "mas_calido": {"anio": c["mas_calido"]["anio"], "tm": c["mas_calido"]["tm"], "empate": c["mas_calido"]["empate"]},
            "calentamiento": c["tendencia"]["calentamiento"] if c["tendencia"]["afirmada"] else None,
            "significativa": c["tendencia"]["significativa"], "homogeneidad": c["homogeneidad"]["estado"],
            "estimacion_tm": c["en_curso"]["estimacion_tm"] if c["en_curso"] else None,
            "puesto_si_acaba_asi": c["en_curso"]["puesto_si_acaba_asi"] if c["en_curso"] else None,
        } for c in caps],
        "sin_serie": [{"cod": k, "provincia": PROVINCIA[k], "texto": v} for k, v in sorted(SIN_SERIE.items())],
        "no_publicadas": no_pub,
    }
    if not solo:
        escribir_json(SALIDA / "index.json", idx, indent=1)
        nac = nota_nacional(caps, HOY)
        nac["generado"] = generado
        escribir_json(SALIDA / "nacional.json", nac, indent=1)

    # tabla de control
    log(f"\nEscala de franjas: ±{escala} °C · capitales publicadas: {len(caps)} · no publicadas: {len(no_pub)}")
    log(f"{'ciudad':24s} {'ini':>4s} {'años':>4s} {'huec':>4s} {'normal':>6s} {'cálido':>7s} {'calent':>6s} {'t':>5s} {'homog':>10s} {'2026 (min-max) puesto':>26s}")
    for c in caps:
        t, h, ec = c["tendencia"], c["homogeneidad"], c["en_curso"]
        est = "—" if not ec or ec["estimacion_tm"] is None else f"{ec['estimacion_tm']} ({ec['estimacion_min']}-{ec['estimacion_max']}) #{ec['puesto_si_acaba_asi']}{'*' if ec['seria_record'] else ''}"
        log(f"{c['ciudad']:24s} {c['inicio']:4d} {c['anios_validos']:4d} {len(c['huecos']):4d} {c['normal_tm']:6.1f} "
            f"{c['mas_calido']['anio']:4d}/{c['mas_calido']['tm']:<4} {str(t['calentamiento']) if t['afirmada'] else '·':>6s} "
            f"{str(t['t']) if t['t'] is not None else '·':>5s} {h['estado'] + (' ' + str(h['salto_decada']) if h['salto_decada'] else ''):>10s} {est:>26s}")


if __name__ == "__main__":
    main()
