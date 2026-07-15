#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FIRMA CLIMÁTICA · Test del algoritmo con clima sintético
========================================================
No necesita internet. Dos niveles de verificación:

  A) MUESTRA IDEAL (determinista): distribuciones construidas con los cuantiles
     exactos de una normal → los resultados deben clavar los valores analíticos.
  B) MUESTRA ALEATORIA (630 obs, como la real): se comprueban signos, rangos
     amplios y monotonía — la varianza de muestreo es legítima y esperada.

Uso:  python scripts/firma_test.py
"""

import random
import sys
import os
from statistics import NormalDist

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from firma_diaria import firma, cdf, cuantil  # noqa: E402
from firma_precalcular import resumen_distribucion, REJILLA  # noqa: E402

N = 630  # observaciones por clima (30 años × ventana de 21 días)
fallos = []


def check(cond, msg):
    if not cond:
        fallos.append(msg)


def clima_ideal(media, sigma):
    """Muestra estratificada perfecta: percentiles empíricos = teóricos."""
    nd = NormalDist(media, sigma)
    return resumen_distribucion([nd.inv_cdf((i + 0.5) / N) for i in range(N)])


def clima_aleatorio(media, sigma, seed):
    rng = random.Random(seed)
    return resumen_distribucion([rng.gauss(media, sigma) for _ in range(N)])


def caso(nombre, tmax, dia_clim, esperado):
    r = firma(tmax, dia_clim, REJILLA)
    print(f"  {nombre}: Tmax={tmax:.1f} → IFC {r['ifc']:+d} · PR {r['pr']}"
          f"{'+' if r['pr_tope'] else ''} · ΔT {r['delta']:+.1f} °C"
          f" · percentil {r['percentil']} · [{esperado}]")
    return r


# ============ A) MUESTRA IDEAL — aserciones estrictas =========================
print("\nA · Muestra ideal · clima +2 °C (m=32→34, σ=4). Valores analíticos exactos.")
dia = {"antes": clima_ideal(32.0, 4.0), "ahora": clima_ideal(34.0, 4.0)}

# P(≥34|ahora)=0.5 ; P(≥34|antes)=1−Φ(0.5)=0.3085 → PR=1.62 → IFC +1 ; ΔT=+2
r = caso("Día normal de ahora   ", 34.0, dia, "PR 1.62 · IFC +1 · ΔT +2.0")
check(r["ifc"] == 1, f"A1: IFC {r['ifc']} ≠ +1")
check(1.5 <= r["pr"] <= 1.75, f"A1: PR {r['pr']} ≠ 1.62")
check(1.8 <= r["delta"] <= 2.2, f"A1: ΔT {r['delta']} ≠ +2.0")

# P(≥42|ahora)=1−Φ(2)=0.02275 ; P(≥42|antes)=1−Φ(2.5)=0.00621 → PR=3.66 → IFC +2
r = caso("Día extremo (m+2σ)    ", 42.0, dia, "PR 3.66 · IFC +2 · ΔT +2.0")
check(r["ifc"] == 2, f"A2: IFC {r['ifc']} ≠ +2")
check(3.2 <= r["pr"] <= 4.1, f"A2: PR {r['pr']} ≠ 3.66")
check(1.8 <= r["delta"] <= 2.2, f"A2: ΔT {r['delta']} ≠ +2.0")

# P(≥46|ahora)=1−Φ(3)=0.00135 ; P(≥46|antes)=1−Φ(3.5)=2.33e−4 → PR=5.80 → IFC +3
r = caso("Día excepcional (m+3σ)", 46.0, dia, "PR 5.80 · IFC +3 · ΔT +2.0")
check(r["ifc"] == 3, f"A3: IFC {r['ifc']} ≠ +3")
check(5.0 <= r["pr"] <= 6.6, f"A3: PR {r['pr']} ≠ 5.80")

# Día frío: P(≤24|ahora)=Φ(−2.5)=0.0062 ; P(≤24|antes)=Φ(−2)=0.0228 → PR=0.27 → IFC −2
r = caso("Día frío (antes−2σ)   ", 24.0, dia, "PR 0.27 · IFC −2 · ΔT +2.0")
check(r["ifc"] == -2, f"A4: IFC {r['ifc']} ≠ −2")
check(r["lado"] == "frio", "A4: lado ≠ frio")

# Sin cambio climático → todo neutro incluso en el extremo
print("\nA' · Muestra ideal · SIN cambio (m=32 en ambos climas)")
dia0 = {"antes": clima_ideal(32.0, 4.0), "ahora": clima_ideal(32.0, 4.0)}
r = caso("Día normal            ", 32.0, dia0, "PR 1.0 · IFC 0 · ΔT 0")
check(r["ifc"] == 0 and abs(r["delta"]) < 0.15, "A'1: señal falsa sin cambio")
r = caso("Día muy cálido (m+2.5σ)", 42.0, dia0, "PR 1.0 · IFC 0 · ΔT 0")
check(r["ifc"] == 0 and abs(r["delta"]) < 0.15, "A'2: señal falsa en extremo sin cambio")

# Coherencia CDF↔cuantil
for p in (0.05, 0.1, 0.5, 0.9, 0.95, 0.99):
    x = cuantil(p, dia["ahora"], REJILLA)
    check(abs(cdf(x, dia["ahora"], REJILLA) - p) < 0.02, f"CDF∘cuantil({p}) desviado")
print("\nCoherencia CDF↔cuantil: comprobada en 6 puntos")

# ============ B) MUESTRA ALEATORIA — signos, rangos y monotonía ===============
print("\nB · Muestra aleatoria (630 obs, varianza de muestreo real)")
dia_r = {"antes": clima_aleatorio(32.0, 4.0, seed=1),
         "ahora": clima_aleatorio(34.0, 4.0, seed=2)}
prev_pr = 0.0
for t in (34.0, 38.0, 42.0, 46.0):
    r = caso(f"Tmax {t}              ", t, dia_r, "PR creciente, IFC ≥ +1")
    check(r["ifc"] >= 1, f"B: IFC {r['ifc']} < +1 con clima desplazado (T={t})")
    check(r["pr"] >= prev_pr - 0.01, f"B: PR no monótono en T={t}")
    prev_pr = r["pr"]
r = caso("Día frío 24 °C         ", 24.0, dia_r, "IFC ≤ −1")
check(r["ifc"] <= -1, "B: día frío sin IFC negativo")

# ============ Resultado =======================================================
if fallos:
    print("\n✗ FALLOS:\n  - " + "\n  - ".join(fallos))
    sys.exit(1)
print("\n✓ Todos los casos pasan. El algoritmo clava los valores analíticos.")
