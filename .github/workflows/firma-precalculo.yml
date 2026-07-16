#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FIRMA CLIMÁTICA · Precálculo de climatologías
=============================================
Descarga la serie diaria de temperatura máxima (ERA5, vía Open-Meteo Archive)
para las 52 capitales de provincia y construye, para cada día del calendario,
la distribución del clima "de antes" (1951–1980) y del clima "actual" (1996–2025).

Salida: docs/firma_clim/<slug>.json  (una climatología por capital)

Se ejecuta UNA VEZ (y se repite una vez al año para incorporar el año cerrado).
Uso:  python scripts/firma_precalcular.py [--solo slug1,slug2]
"""

import csv
import json
import math
import os
import statistics
import sys
import time
import urllib.request
import urllib.error
from datetime import date, timedelta

# ----------------------------- Configuración --------------------------------

RUTA_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
RUTA_REPO = os.path.dirname(RUTA_SCRIPTS)
RUTA_CAPITALES = os.path.join(RUTA_SCRIPTS, "firma_capitales.csv")
RUTA_SALIDA = os.path.join(RUTA_REPO, "docs", "firma_clim")

INICIO_DESCARGA = "1940-01-01"   # ERA5 empieza en 1940
FIN_DESCARGA = "2025-12-31"      # último año natural cerrado

PERIODO_ANTES = (1951, 1980)     # el clima "de antes"
PERIODO_AHORA = (1996, 2025)     # el clima "actual"
VENTANA_DIAS = 10                # ±10 días alrededor de cada día del calendario

# Rejilla de percentiles que guardamos por distribución (para interpolar CDF)
REJILLA = [1, 2.5, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50,
           55, 60, 65, 70, 75, 80, 85, 90, 95, 97.5, 99, 99.5]

LOTE = 5                         # capitales por petición (menos peticiones = menos 429)
API_ARCHIVO = ("https://archive-api.open-meteo.com/v1/archive"
               "?latitude={lats}&longitude={lons}"
               "&start_date={ini}&end_date={fin}"
               "&daily=temperature_2m_max&timezone=Europe%2FMadrid")

# ----------------------------- Utilidades -----------------------------------

def leer_capitales(ruta):
    with open(ruta, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def descargar_json(url, intentos=8):
    """
    Descarga con reintentos y espera creciente. El 429 (límite de tasa de la API
    gratuita) recibe esperas largas: 30, 60, 120, 240s… hasta que la API se libera.
    """
    for i in range(intentos):
        try:
            with urllib.request.urlopen(url, timeout=180) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if i == intentos - 1:
                raise
            espera = 30 * (2 ** i) if e.code == 429 else 15
            espera = min(espera, 600)
            print(f"    · reintento {i + 1} (HTTP {e.code}) — espero {espera}s", flush=True)
            time.sleep(espera)
        except (urllib.error.URLError, TimeoutError) as e:
            if i == intentos - 1:
                raise
            print(f"    · reintento {i + 1} ({e}) — espero 15s", flush=True)
            time.sleep(15)


def percentil(muestra_ordenada, p):
    """Percentil con interpolación lineal (equivalente a numpy 'linear')."""
    n = len(muestra_ordenada)
    if n == 0:
        return None
    k = (n - 1) * p / 100.0
    f = math.floor(k)
    c = min(f + 1, n - 1)
    if f == c:
        return muestra_ordenada[int(k)]
    return muestra_ordenada[f] + (muestra_ordenada[c] - muestra_ordenada[f]) * (k - f)


def doy_ref(d):
    """Día del año 1..366 sobre calendario de referencia bisiesto (año 2000)."""
    return (date(2000, d.month, d.day) - date(2000, 1, 1)).days + 1


def resumen_distribucion(valores):
    """Estadísticos + rejilla de percentiles de una muestra."""
    v = sorted(valores)
    return {
        "n": len(v),
        "m": round(statistics.fmean(v), 2),
        "s": round(statistics.stdev(v), 2) if len(v) > 1 else 0.0,
        "q": [round(percentil(v, p), 2) for p in REJILLA],
    }

# ----------------------------- Núcleo ----------------------------------------

def construir_climatologia(serie):
    """
    serie: dict {date -> tmax}. Devuelve {"MM-DD": {"antes": {...}, "ahora": {...}}}
    Para cada día del calendario, junta las observaciones de la ventana ±10 días
    de todos los años de cada periodo (~630 observaciones por clima).
    """
    # Reparte cada observación en los días del calendario a cuya ventana pertenece
    cubos = {}  # (doy, periodo) -> [valores]
    for d, t in serie.items():
        if t is None:
            continue
        if PERIODO_ANTES[0] <= d.year <= PERIODO_ANTES[1]:
            periodo = "antes"
        elif PERIODO_AHORA[0] <= d.year <= PERIODO_AHORA[1]:
            periodo = "ahora"
        else:
            continue
        dr = doy_ref(d)
        for delta in range(-VENTANA_DIAS, VENTANA_DIAS + 1):
            objetivo = (dr - 1 + delta) % 366 + 1  # circular 1..366
            cubos.setdefault((objetivo, periodo), []).append(t)

    dias = {}
    base = date(2000, 1, 1)
    for doy in range(1, 367):
        clave = (base + timedelta(days=doy - 1)).strftime("%m-%d")
        antes = cubos.get((doy, "antes"), [])
        ahora = cubos.get((doy, "ahora"), [])
        if len(antes) < 100 or len(ahora) < 100:
            continue  # seguridad: nunca debería ocurrir con ERA5 completo
        dias[clave] = {"antes": resumen_distribucion(antes),
                       "ahora": resumen_distribucion(ahora)}
    return dias


def descargar_lote(lote):
    """
    Descarga la serie de varias capitales en UNA sola petición (la API acepta
    coordenadas separadas por comas y devuelve una lista de resultados en orden).
    Devuelve {slug: {date: tmax}}.
    """
    lats = ",".join(str(c["lat"]) for c in lote)
    lons = ",".join(str(c["lon"]) for c in lote)
    url = API_ARCHIVO.format(lats=lats, lons=lons,
                             ini=INICIO_DESCARGA, fin=FIN_DESCARGA)
    datos = descargar_json(url)
    if isinstance(datos, dict):
        datos = [datos]  # la API devuelve objeto si el lote es de una sola capital
    series = {}
    for cap, d in zip(lote, datos):
        fechas = d["daily"]["time"]
        tmax = d["daily"]["temperature_2m_max"]
        series[cap["slug"]] = {date.fromisoformat(f): t for f, t in zip(fechas, tmax)}
    return series


def montar_climatologia(cap, serie):
    n_validos = sum(1 for t in serie.values() if t is not None)
    dias = construir_climatologia(serie)
    return n_validos, {
        "slug": cap["slug"],
        "nombre": cap["nombre"],
        "provincia": cap["provincia"],
        "lat": float(cap["lat"]),
        "lon": float(cap["lon"]),
        "fuente": "ERA5 via Open-Meteo Archive",
        "periodos": {"antes": list(PERIODO_ANTES), "ahora": list(PERIODO_AHORA)},
        "ventana_dias": VENTANA_DIAS,
        "rejilla": REJILLA,
        "generado": date.today().isoformat(),
        "dias": dias,
    }

# ----------------------------- Main ------------------------------------------

def main():
    solo = None
    if "--solo" in sys.argv:
        solo = set(sys.argv[sys.argv.index("--solo") + 1].split(","))

    capitales = leer_capitales(RUTA_CAPITALES)
    os.makedirs(RUTA_SALIDA, exist_ok=True)
    rehacer = "--rehacer" in sys.argv  # fuerza recálculo aunque ya exista el JSON

    # Solo las capitales pendientes (permite reanudar tras un corte)
    pendientes = []
    for cap in capitales:
        if solo and cap["slug"] not in solo:
            continue
        destino = os.path.join(RUTA_SALIDA, f"{cap['slug']}.json")
        if os.path.exists(destino) and not rehacer:
            print(f"· {cap['nombre']} ya existe, se salta", flush=True)
            continue
        pendientes.append(cap)

    print(f"{len(pendientes)} capitales pendientes · lotes de {LOTE}", flush=True)

    hechas = 0
    for inicio in range(0, len(pendientes), LOTE):
        lote = pendientes[inicio:inicio + LOTE]
        nombres = ", ".join(c["nombre"] for c in lote)
        print(f"[lote {inicio // LOTE + 1}] {nombres}", flush=True)
        series = descargar_lote(lote)
        for cap in lote:
            destino = os.path.join(RUTA_SALIDA, f"{cap['slug']}.json")
            n_validos, clim = montar_climatologia(cap, series[cap["slug"]])
            with open(destino, "w", encoding="utf-8") as f:
                json.dump(clim, f, ensure_ascii=False, separators=(",", ":"))
            hechas += 1
            print(f"    · {cap['nombre']}: {n_validos} días → "
                  f"{os.path.basename(destino)} ({len(clim['dias'])} días de calendario)",
                  flush=True)
        time.sleep(8)  # pausa entre lotes: cortesía con la API

    print(f"Precálculo terminado · {hechas} capitales nuevas.")


if __name__ == "__main__":
    main()
