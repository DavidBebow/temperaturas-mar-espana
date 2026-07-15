#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FIRMA CLIMÁTICA · Cálculo diario
================================
Para cada capital: obtiene la Tmax del día, la compara con las distribuciones
del clima "de antes" (1951–1980) y "actual" (1996–2025) y calcula:

  · PR  — razón de probabilidades entre ambos climas
  · IFC — Índice de Firma Climática: clip(round(log2(PR)), −5, +5)
  · ΔT  — grados añadidos por quantile mapping

Salidas:
  docs/firma_climatica.json   (el dato del día, para la web y la API pública)
  docs/firma_historico.json   (histórico diario por capital, para rachas y récords)

Uso:
  python scripts/firma_diaria.py                  # hoy (previsión Open-Meteo)
  python scripts/firma_diaria.py --fecha 2022-07-14   # una fecha pasada (archivo ERA5)
"""

import glob
import json
import math
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import date, datetime, timedelta
from statistics import NormalDist

# ----------------------------- Configuración --------------------------------

RUTA_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
RUTA_REPO = os.path.dirname(RUTA_SCRIPTS)
RUTA_CLIM = os.path.join(RUTA_REPO, "docs", "firma_clim")
RUTA_SALIDA = os.path.join(RUTA_REPO, "docs", "firma_climatica.json")
RUTA_HISTORICO = os.path.join(RUTA_REPO, "docs", "firma_historico.json")

IFC_MAX = 5
PR_TOPE = 100.0        # por encima, reportamos "PR > 100"
PROB_SUELO = 1e-6      # evita divisiones por cero en colas extremas
LOTE = 26              # capitales por llamada a la API de previsión

# past_days=3: además de la previsión de hoy, trae los 3 días anteriores ya
# observados (análisis meteorológico), con los que CONSOLIDAMOS el histórico.
DIAS_CONSOLIDACION = 3
API_PREVISION = ("https://api.open-meteo.com/v1/forecast"
                 "?latitude={lats}&longitude={lons}"
                 "&daily=temperature_2m_max&timezone=Europe%2FMadrid"
                 "&forecast_days=1&past_days=" + str(DIAS_CONSOLIDACION))
API_ARCHIVO = ("https://archive-api.open-meteo.com/v1/archive"
               "?latitude={lats}&longitude={lons}"
               "&start_date={f}&end_date={f}"
               "&daily=temperature_2m_max&timezone=Europe%2FMadrid")

# ------------------------ Matemática de la firma -----------------------------
# Distribución = {"n": int, "m": media, "s": desv, "q": [percentiles]}
# junto a la rejilla de probabilidades REJILLA (en %) de la climatología.

# En el centro de la distribución usamos los percentiles empíricos (fieles al
# clima real); en las colas (fuera de p2.5–p97.5), donde el muestreo es ruidoso,
# usamos la cola gaussiana ajustada a la muestra. Método documentado.
COLA_BAJA, COLA_ALTA = 2.5, 97.5


def _limites_empiricos(dist, rejilla):
    i_lo = rejilla.index(COLA_BAJA)
    i_hi = rejilla.index(COLA_ALTA)
    return i_lo, i_hi


def cdf(x, dist, rejilla):
    """P(T ≤ x): percentiles empíricos en el centro, cola normal en los extremos."""
    q, m, s = dist["q"], dist["m"], dist["s"]
    if s <= 0:
        return 0.5
    i_lo, i_hi = _limites_empiricos(dist, rejilla)
    if x < q[i_lo] or x > q[i_hi]:
        nd = NormalDist(m, s)
        return min(max(nd.cdf(x), PROB_SUELO), 1 - PROB_SUELO)
    for i in range(i_lo, i_hi):
        if q[i] <= x <= q[i + 1]:
            p0, p1 = rejilla[i] / 100.0, rejilla[i + 1] / 100.0
            if q[i + 1] == q[i]:
                return p1
            frac = (x - q[i]) / (q[i + 1] - q[i])
            return p0 + frac * (p1 - p0)
    return 0.5  # inalcanzable


def cuantil(p, dist, rejilla):
    """Inversa de la CDF: empírica en el centro, cola normal en los extremos."""
    q, m, s = dist["q"], dist["m"], dist["s"]
    if s <= 0:
        return m
    if p < COLA_BAJA / 100.0 or p > COLA_ALTA / 100.0:
        return NormalDist(m, s).inv_cdf(min(max(p, PROB_SUELO), 1 - PROB_SUELO))
    i_lo, i_hi = _limites_empiricos(dist, rejilla)
    for i in range(i_lo, i_hi):
        p0, p1 = rejilla[i] / 100.0, rejilla[i + 1] / 100.0
        if p0 <= p <= p1:
            frac = 0.0 if p1 == p0 else (p - p0) / (p1 - p0)
            return q[i] + frac * (q[i + 1] - q[i])
    return q[i_hi]


def firma(tmax, dia_clim, rejilla):
    """
    Calcula PR, IFC, ΔT y percentil actual para una Tmax observada.

    Lado cálido (tmax ≥ mediana actual): PR = P(T≥t | ahora) / P(T≥t | antes)
      → IFC positivo si el calentamiento hace el día más probable.
    Lado frío  (tmax < mediana actual):  PR = P(T≤t | ahora) / P(T≤t | antes)
      → IFC negativo: el calentamiento hace el día frío MENOS probable.
    """
    antes, ahora = dia_clim["antes"], dia_clim["ahora"]
    p_ahora_cdf = cdf(tmax, ahora, rejilla)
    mediana_ahora = cuantil(0.5, ahora, rejilla)

    if tmax >= mediana_ahora:  # lado cálido
        p_ahora = max(1 - p_ahora_cdf, PROB_SUELO)
        p_antes = max(1 - cdf(tmax, antes, rejilla), PROB_SUELO)
        lado = "calor"
    else:                      # lado frío
        p_ahora = max(p_ahora_cdf, PROB_SUELO)
        p_antes = max(cdf(tmax, antes, rejilla), PROB_SUELO)
        lado = "frio"

    # En días fríos PR<1 → log2 negativo: el signo del índice sale solo.
    pr = p_ahora / p_antes
    ifc = max(-IFC_MAX, min(IFC_MAX, round(math.log2(pr))))

    # Grados añadidos: un día igual de raro en el clima de antes
    delta = tmax - cuantil(p_ahora_cdf, antes, rejilla)

    return {
        "pr": round(min(pr, PR_TOPE), 1),
        "pr_tope": pr > PR_TOPE,
        "ifc": ifc,
        "delta": round(delta, 1),
        "percentil": round(p_ahora_cdf * 100, 1),
        "lado": lado,
    }

# ----------------------------- Datos del día ---------------------------------

def descargar_json(url, intentos=4, espera=10):
    for i in range(intentos):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            if i == intentos - 1:
                raise
            print(f"  · reintento {i + 1} ({e})", flush=True)
            time.sleep(espera)


def tmax_del_dia(capitales, fecha):
    """
    Tmax por slug para la fecha objetivo.
    Hoy → API de previsión (que además trae los últimos DIAS_CONSOLIDACION días
    ya observados: se devuelven en `pasados` para consolidar el histórico).
    Fecha pasada → archivo ERA5.
    Devuelve: (resultado {slug: tmax}, pasados {fecha_iso: {slug: tmax}})
    """
    resultado, pasados = {}, {}
    for i in range(0, len(capitales), LOTE):
        lote = capitales[i:i + LOTE]
        lats = ",".join(str(c["lat"]) for c in lote)
        lons = ",".join(str(c["lon"]) for c in lote)
        if fecha == date.today():
            url = API_PREVISION.format(lats=lats, lons=lons)
        else:
            url = API_ARCHIVO.format(lats=lats, lons=lons, f=fecha.isoformat())
        datos = descargar_json(url)
        if isinstance(datos, dict):
            datos = [datos]  # la API devuelve objeto si solo hay una localización
        for cap, d in zip(lote, datos):
            dias = d["daily"]["time"]
            valores = d["daily"]["temperature_2m_max"]
            for f, t in zip(dias, valores):
                if f == fecha.isoformat():
                    resultado[cap["slug"]] = t
                elif t is not None:
                    pasados.setdefault(f, {})[cap["slug"]] = t
    return resultado, pasados


def consolidar_historico(historico, pasados, climatologias):
    """
    Recalcula la firma de los días recientes con la Tmax YA OBSERVADA y
    sobreescribe el histórico: las rachas y récords se apoyan siempre en
    datos consolidados, no en la previsión de aquella mañana.
    """
    consolidados = 0
    for fecha_iso, tmax_por_slug in sorted(pasados.items()):
        clave_dia = date.fromisoformat(fecha_iso).strftime("%m-%d")
        dia_hist = {}
        for slug, t in tmax_por_slug.items():
            clim = climatologias.get(slug)
            if clim is None:
                continue
            dia_clim = clim["dias"].get(clave_dia) or clim["dias"].get("02-28")
            if dia_clim is None:
                continue
            r = firma(t, dia_clim, clim["rejilla"])
            dia_hist[slug] = [r["ifc"], r["delta"], round(t, 1)]
        if dia_hist:
            historico[fecha_iso] = dia_hist
            consolidados += 1
    return consolidados

# ----------------------------- Histórico y rachas ----------------------------

def cargar_historico():
    if os.path.exists(RUTA_HISTORICO):
        with open(RUTA_HISTORICO, encoding="utf-8") as f:
            return json.load(f)
    return {}


def racha_actual(historico, slug, fecha, umbral=3):
    """Días consecutivos (terminando en `fecha`) con IFC ≥ umbral."""
    racha = 0
    d = fecha
    while True:
        dia = historico.get(d.isoformat(), {}).get(slug)
        if not dia or dia[0] < umbral:
            break
        racha += 1
        d -= timedelta(days=1)
    return racha

# ----------------------------- Main ------------------------------------------

def main():
    fecha = date.today()
    if "--fecha" in sys.argv:
        fecha = date.fromisoformat(sys.argv[sys.argv.index("--fecha") + 1])

    # 1) Climatologías
    climatologias = {}
    for ruta in sorted(glob.glob(os.path.join(RUTA_CLIM, "*.json"))):
        with open(ruta, encoding="utf-8") as f:
            c = json.load(f)
        climatologias[c["slug"]] = c
    if not climatologias:
        sys.exit("No hay climatologías en docs/firma_clim/ — ejecuta antes firma_precalcular.py")
    print(f"{len(climatologias)} climatologías cargadas · fecha objetivo: {fecha}", flush=True)

    capitales = [{"slug": c["slug"], "nombre": c["nombre"], "provincia": c["provincia"],
                  "lat": c["lat"], "lon": c["lon"]} for c in climatologias.values()]

    # 2) Tmax del día (+ días recientes ya observados si fecha == hoy)
    tmax, pasados = tmax_del_dia(capitales, fecha)

    # 3) Consolidar el histórico con los datos observados
    historico = cargar_historico()
    n_cons = consolidar_historico(historico, pasados, climatologias)
    if n_cons:
        print(f"{n_cons} días recientes consolidados con dato observado", flush=True)

    # 4) Firma por capital
    clave_dia = fecha.strftime("%m-%d")  # el 29-02 usa 28-02 como respaldo
    ciudades = []
    for cap in capitales:
        clim = climatologias[cap["slug"]]
        dia_clim = clim["dias"].get(clave_dia) or clim["dias"].get("02-28")
        t = tmax.get(cap["slug"])
        if t is None or dia_clim is None:
            continue
        r = firma(t, dia_clim, clim["rejilla"])
        ciudades.append({
            "slug": cap["slug"], "nombre": cap["nombre"], "provincia": cap["provincia"],
            "lat": cap["lat"], "lon": cap["lon"], "tmax": round(t, 1), **r,
        })

    # 5) Histórico y rachas
    historico[fecha.isoformat()] = {
        c["slug"]: [c["ifc"], c["delta"], c["tmax"]] for c in ciudades
    }
    for c in ciudades:
        c["racha_ifc3"] = racha_actual(historico, c["slug"], fecha)

    # 6) Resumen nacional
    ciudades.sort(key=lambda c: (-c["ifc"], -c["delta"]))
    n_senal = sum(1 for c in ciudades if c["ifc"] >= 3)
    resumen = {
        "capital_max": ciudades[0]["nombre"] if ciudades else None,
        "ifc_max": ciudades[0]["ifc"] if ciudades else None,
        "delta_max": max((c["delta"] for c in ciudades), default=None),
        "capitales_ifc3": n_senal,
        "ifc_medio": round(sum(c["ifc"] for c in ciudades) / len(ciudades), 2) if ciudades else None,
        "alerta_prensa": n_senal >= 10 or any(c["ifc"] >= 4 for c in ciudades),
    }

    salida = {
        "fecha": fecha.isoformat(),
        "generado_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metodo": "Índice de desplazamiento climático observado (1951–1980 vs 1996–2025, ERA5)",
        "licencia": "CC-BY 4.0 · cita: calentamientoglobal.es",
        "resumen": resumen,
        "ciudades": ciudades,
    }

    with open(RUTA_SALIDA, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, separators=(",", ":"))
    with open(RUTA_HISTORICO, "w", encoding="utf-8") as f:
        json.dump(historico, f, ensure_ascii=False, separators=(",", ":"))

    print(f"OK · {len(ciudades)} capitales · máx: {resumen['capital_max']} "
          f"IFC {resumen['ifc_max']:+d} · {n_senal} capitales con IFC ≥ +3", flush=True)


if __name__ == "__main__":
    main()
