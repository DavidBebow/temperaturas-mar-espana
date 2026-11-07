#!/usr/bin/env python3
"""Atribución probabilística por capital: periodo de retorno antes/ahora, cociente de probabilidad e índice de huella.

Para cada una de las 52 capitales calcula, con el último día disponible, cuánto más (o menos) probable es lo observado
hoy en el clima de AHORA (1996-2025) que en el de ANTES (1961-1990): periodo de retorno en cada clima, cociente de
probabilidad (PR) con su intervalo del 90 % y el «índice de huella climática» de −5 a +5.

Salidas (todo en docs/huella/):
  <slug>.json            una capital: hoy (tmax, tmin, tmed), mes, últimos 30 días, textos
  index.json             resumen de las 52 capitales y cifras nacionales
  historico/<AAAA-MM>.json  índice diario de todas las capitales
  graf/<slug>.svg        últimos 30 días como columnas coloreadas por nivel
  antes_raro.json        días y meses de los últimos días con PR ≥ 3 y T_antes ≥ 10 años (lo lee hallazgos_prensa.py)
  metodo.md              método completo (se escribe desde las constantes de este fichero)
  cache/ajustes.json.gz  ajustes por (estación, variable, día del calendario, clima)

Fuentes: estaciones de AEMET (valores diarios validados, archivo/aemet_diario/) cuando tienen ≥ 25 años válidos en
cada clima y homogeneidad «ok» o sin control; en las demás capitales, el reanálisis ERA5 de archivo/era5/<cod>/ con
citabilidad media y la fuente dicha en cada texto.

Uso:  python scripts/sala/atribucion.py [--hoy AAAA-MM-DD] [--solo slug,slug] [--sin-historico] [--sin-cache]
API para el detector:  from sala import atribucion; atribucion.rareza_capital(cod, "2026-10-15", "tmax", 30.1, "era5")
"""
from __future__ import annotations

import argparse
import calendar
import csv
import gzip
import hashlib
import json
import math
import sys
import time
import zlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import warnings

import numpy as np
from scipy.special import gamma as gamma_fn, kolmogorov, ndtr
from scipy.stats import gamma as gamma_dist, genextreme

warnings.filterwarnings("ignore", category=RuntimeWarning)

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))
from balance_mensual import ARCH, DOCS, ESTACIONES, PROVINCIA, r1  # noqa: E402
from tu_capital import SLUG as SLUG47  # noqa: E402

SALIDA = DOCS / "huella"
CACHE_RUTA = SALIDA / "cache" / "ajustes.json.gz"

# ----------------------------------------------------------------------------
# constantes del método (todas se publican en metodo.md)
# ----------------------------------------------------------------------------
ANTES = (1961, 1990)
AHORA = (1996, 2025)
Y0 = 1961                      # primer año de las matrices
VENTANA = 15                   # ±15 días del calendario alrededor del día D
MIN_DIAS_VENTANA = 28          # año válido para una ventana de 31 días: ≥ 90 % de los días
COBERTURA = 0.90               # año válido de la estación: ≥ 90 % de los días del año
MIN_ANIOS = 25                 # años válidos exigidos en cada clima
UMBRAL_KS = 0.01               # si p < 0,01 el ajuste normal se rechaza y se usa la distribución empírica suavizada
P_COLA = 99.5                  # más allá de este percentil del clima de ahora, la cola normal subestima: GEV
NBOOT = 200                    # remuestreos de años para el intervalo del 90 % del PR
GEV_FORMA_MAX = 0.2            # forma de la GEV acotada a ±0,2 (con ≤ 30 máximos anuales, una forma libre da colas absurdas)
T_MAX = 1000                   # periodos de retorno por encima de 1.000 años no se distinguen: se acotan
PR_UMBRALES = (1.5, 2.0, 3.0, 4.0, 5.0)    # niveles 1 a 5 (y −1 a −5 invertidos)
ANTES_RARO_PR = 3.0
ANTES_RARO_T = 10.0            # años
FUERZA_PR_TOPE = 5.0           # la fuerza de un hallazgo con rareza significativa se multiplica por min(PR, 5)/2 (si PR > 1)
DIAS_ULTIMOS = 30
DIAS_ANTES_RARO = 10
MIN_DIAS_MES = 10
ERA5_CONSOLIDA_DIAS = 6        # ERA5 consolida con unos seis días de retraso: antes de eso, dato provisional
FRAC_NACIONAL = 0.80           # nunca «de España» con menos del 80 % de las capitales con dato
LICENCIA = "CC BY 4.0"
FUENTE_AEMET = "AEMET (valores diarios validados de la estación) · cálculo propio de calentamientoglobal.es"
FUENTE_ERA5 = ("Reanálisis ERA5 (Copernicus/ECMWF) en la celda de la capital · cálculo propio de calentamientoglobal.es "
               "(no es una estación de AEMET)")

NIVEL_TEXTO = {
    5: "Nivel +5: un día así es hoy al menos cinco veces más probable que en 1961-1990 por el calentamiento",
    4: "Nivel +4: un día así es hoy al menos cuatro veces más probable que en 1961-1990 por el calentamiento",
    3: "Nivel +3: un día así es hoy al menos tres veces más probable que en 1961-1990 por el calentamiento",
    2: "Nivel +2: un día así es hoy al menos el doble de probable que en 1961-1990 por el calentamiento",
    1: "Nivel +1: un día así es hoy al menos 1,5 veces más probable que en 1961-1990 por el calentamiento",
    0: "Nivel 0: dentro de lo que ya era normal",
    -1: "Nivel −1: un frío así era antes al menos 1,5 veces más probable que ahora",
    -2: "Nivel −2: un frío así era antes el doble de probable que ahora",
    -3: "Nivel −3: un frío así era antes al menos tres veces más probable que ahora",
    -4: "Nivel −4: un frío así era antes al menos cuatro veces más probable que ahora",
    -5: "Nivel −5: un frío así era antes al menos cinco veces más probable que ahora",
}
NIVEL_COLOR = {5: "#8b1a1a", 4: "#b8321c", 3: "#e0552b", 2: "#f0a04b", 1: "#f2d27a", 0: "#9fb6c8", -1: "#9fb6c8",
               -2: "#8fb8e8", -3: "#6694ca", -4: "#3d70ac", -5: "#1f4e8c"}
METODO_CORTO = ("Compara la probabilidad del valor observado en el clima de 1961-1990 y en el de 1996-2025 de la misma serie "
                "(ventana de ±15 días, ajuste normal y GEV en la cola, intervalo del 90 % por remuestreo de años); el índice "
                "sale del cociente de probabilidad con los umbrales 1,5 · 2 · 3 · 4 · 5.")
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre",
         "diciembre"]

CAPITAL_SIN_ESTACION = {"19": "Guadalajara", "33": "Oviedo", "34": "Palencia", "39": "Santander", "51": "Ceuta"}
SLUG_EXTRA = {"19": "guadalajara", "33": "asturias", "34": "palencia", "39": "cantabria", "51": "ceuta"}
SLUGS = {**SLUG47, **SLUG_EXTRA}

CUM = [0, 31, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335, 366]   # calendario bisiesto: el 29-F tiene su casilla
FILAS_ANTES = np.arange(ANTES[0] - Y0, ANTES[1] - Y0 + 1)
FILAS_AHORA = np.arange(AHORA[0] - Y0, AHORA[1] - Y0 + 1)
PMIN_DIA = 1.0 / (31.0 * T_MAX)
PMIN_ANIO = 1.0 / T_MAX


def log(m: str):
    print(time.strftime("%H:%M:%S ") + m, flush=True)


def doy(m: int, d: int) -> int:
    return CUM[m - 1] + d - 1


# ----------------------------------------------------------------------------
# formato
# ----------------------------------------------------------------------------
def fnum(v, dec=1) -> str:
    s = f"{r1(v):.1f}" if dec == 1 else f"{v:.{dec}f}"
    return s.replace(".", ",")


def pub_ratio(v):
    """Cociente de probabilidad o periodo de retorno: una décima; por encima de 10, sin decimales."""
    v = float(v)
    if not math.isfinite(v):
        return None
    return r1(v) if v < 10 else int(round(v))


PR_TOPE_PUB = 1000.0           # un cociente por encima de 1.000 se publica como «más de 1.000»


def pub_pr(v):
    return pub_ratio(min(float(v), PR_TOPE_PUB))


def fratio(v, tope: bool = False) -> str:
    if tope and float(v) >= PR_TOPE_PUB:
        return "más de 1.000"
    p = pub_ratio(v)
    if p is None:
        return "—"
    return f"{p:,}".replace(",", ".") if isinstance(p, int) else fnum(p)


def fecha_larga(d: date) -> str:
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def frase_T(T: float, tope: bool = False) -> str:
    if tope:
        return "menos de una vez cada 1.000 años"
    if T >= 1.05:
        return f"una vez cada {fratio(T)} años"
    if T >= 0.95:
        return "una vez al año"
    return f"unas {fratio(1.0 / T)} veces al año"


# ----------------------------------------------------------------------------
# lectura de series
# ----------------------------------------------------------------------------
def _f(s: str) -> float:
    try:
        return float(s)
    except (TypeError, ValueError):
        return math.nan


class Serie:
    """Una capital: tres matrices (año × 366 casillas de calendario) de tmax, tmin y lluvia, y la fuente."""

    def __init__(self, cod: str, fuente: str, ny: int, motivo: str = ""):
        self.cod = cod
        self.slug = SLUGS[cod]
        self.capital = ESTACIONES[cod][1] if cod in ESTACIONES else CAPITAL_SIN_ESTACION[cod]
        self.provincia = PROVINCIA[cod]
        self.fuente = fuente                     # 'aemet' | 'era5'
        self.motivo = motivo
        self.ny = ny
        self.indicativo = ESTACIONES[cod][0] if (fuente == "aemet") else None
        self.estacion = ESTACIONES[cod][2] if (fuente == "aemet") else f"reanálisis ERA5 en la celda de {self.capital}"
        self.homog = "ok"
        self.citabilidad = "media"
        self.cache = {}                          # var -> clima -> {'n','m','s','p'} (listas de 366)
        self.sucio = False
        self._ext = {}
        nan = np.full((ny, 366), np.nan)
        self.mat = {"tmax": nan.copy(), "tmin": nan.copy(), "prec": nan.copy()}
        self.ultima = None

    # -- carga -------------------------------------------------------------
    def _cargar_filas(self, filas):
        TX, TN, PR = self.mat["tmax"], self.mat["tmin"], self.mat["prec"]
        for f, tx, tn, p in filas:
            y = int(f[:4]) - Y0
            if y < 0 or y >= self.ny:
                continue
            c = CUM[int(f[5:7]) - 1] + int(f[8:10]) - 1
            TX[y, c], TN[y, c], PR[y, c] = tx, tn, p

    def finalizar(self):
        self.mat["tmed"] = (self.mat["tmax"] + self.mat["tmin"]) / 2.0
        ok = ~np.isnan(self.mat["tmed"])
        if ok.any():
            ys, cs = np.nonzero(ok)
            orden = ys * 366 + cs
            k = int(np.argmax(orden))
            self.ultima = date(Y0 + int(ys[k]), 1, 1) + timedelta(days=0)
            # fecha real a partir de (año, casilla): se busca el mes y el día de la casilla
            c = int(cs[k])
            m = next(i for i in range(12) if CUM[i] <= c < CUM[i + 1])
            self.ultima = date(Y0 + int(ys[k]), m + 1, c - CUM[m] + 1)

    # -- ventanas ------------------------------------------------------------
    def ext(self, var):
        if var not in self._ext:
            A = self.mat[var]
            nan = np.full((1, 366), np.nan)
            self._ext[var] = np.hstack([np.vstack([nan, A[:-1]]), A, np.vstack([A[1:], nan])])
        return self._ext[var]

    def ventana(self, var, d, filas):
        E = self.ext(var)
        return E[filas, 366 + d - VENTANA: 366 + d + VENTANA + 1]

    def liberar(self):
        self._ext = {}

    # -- ajustes (con caché) --------------------------------------------------
    def firma(self) -> str:
        h = hashlib.sha1()
        for var in ("tmax", "tmin"):
            for filas in (FILAS_ANTES, FILAS_AHORA):
                h.update(np.nan_to_num(self.mat[var][filas], nan=-999.0).tobytes())
        h.update(f"{ANTES}{AHORA}{VENTANA}{MIN_DIAS_VENTANA}{self.fuente}".encode())
        return h.hexdigest()[:16]

    def fit(self, var, d, clima):
        c = self.cache.get(var, {}).get(clima)
        if c is not None and c["n"][d] is not None:
            return {"n": c["n"][d], "mean": c["m"][d], "sd": c["s"][d], "ksp": c["p"][d]}
        W = self.ventana(var, d, FILAS_ANTES if clima == "antes" else FILAS_AHORA)
        r = ajustar(W)
        if r is None:
            return None
        c = self.cache.setdefault(var, {}).setdefault(clima, {k: [None] * 366 for k in ("n", "m", "s", "p")})
        c["n"][d], c["m"][d], c["s"][d], c["p"][d] = r["n"], r["mean"], r["sd"], r["ksp"]
        self.sucio = True
        return r

    def precalcular(self):
        for var in ("tmax", "tmin", "tmed"):
            for clima in ("antes", "ahora"):
                for d in range(366):
                    self.fit(var, d, clima)


def estadisticas_anio(W):
    m = ~np.isnan(W)
    n = m.sum(1)
    Z = np.where(m, W, 0.0)
    return m, n, Z.sum(1), (Z * Z).sum(1), n >= MIN_DIAS_VENTANA


def ks_normal(v, mean, sd):
    """Kolmogorov-Smirnov frente a la normal ajustada (p asintótico)."""
    x = np.sort(v)
    n = len(x)
    F = ndtr((x - mean) / sd)
    D = max(float(np.max(np.arange(1, n + 1) / n - F)), float(np.max(F - np.arange(0, n) / n)))
    return float(kolmogorov(D * math.sqrt(n)))


def ajustar(W):
    m, n, s, q, ok = estadisticas_anio(W)
    if ok.sum() < MIN_ANIOS:
        return None
    N = float(n[ok].sum())
    S, Q = float(s[ok].sum()), float(q[ok].sum())
    mean = S / N
    var = max((Q - S * S / N) / (N - 1), 1e-12)
    sd = math.sqrt(var)
    v = W[ok][m[ok]]
    return {"n": int(ok.sum()), "mean": mean, "sd": sd, "ksp": ks_normal(v, mean, sd)}


def silverman(v):
    sd = float(np.std(v, ddof=1))
    iqr = float(np.subtract(*np.percentile(v, [75, 25])))
    s = min(sd, iqr / 1.34) if iqr > 0 else sd
    return 0.9 * max(s, 1e-6) * len(v) ** (-0.2)


# ----------------------------------------------------------------------------
# probabilidades
# ----------------------------------------------------------------------------
def _rng(*claves):
    return np.random.default_rng(zlib.crc32("|".join(str(c) for c in claves).encode()))


def _prob_ventana(W, fit, x, sgn, rng, emp):
    """P(X ≥ x) (sgn=+1) o P(X ≤ x) (sgn=−1) en una ventana de varios años; punto + NBOOT remuestreos de años."""
    m, n, s, q, ok = estadisticas_anio(W)
    iv = np.flatnonzero(ok)
    idx = rng.integers(0, len(iv), size=(NBOOT, len(iv)))
    if not emp:
        p = float(ndtr(-sgn * (x - fit["mean"]) / fit["sd"]))
        N = n[iv][idx].sum(1).astype(float)
        S = s[iv][idx].sum(1)
        Q = q[iv][idx].sum(1)
        mu = S / N
        sd = np.sqrt(np.maximum((Q - S * S / N) / (N - 1), 1e-12))
        pb = ndtr(-sgn * (x - mu) / sd)
        return p, pb, "normal"
    v = W[ok][m[ok]]
    h = silverman(v)
    p = float(np.mean(ndtr(sgn * (v - x) / h)))
    ty = np.where(m[iv], ndtr(sgn * (W[iv] - x) / h), 0.0).sum(1)
    pb = ty[idx].sum(1) / n[iv][idx].sum(1).astype(float)
    return p, pb, "empírica"


def _resultado(pb, pa, pbb, pab, lado, metodo, x, anual, extra=None):
    pmin = PMIN_ANIO if anual else PMIN_DIA
    pb, pa = max(pb, pmin), max(pa, pmin)
    PR = pa / pb
    prb = np.maximum(pab, 1e-12) / np.maximum(pbb, 1e-12)
    lo, hi = np.nanpercentile(prb, 5), np.nanpercentile(prb, 95)
    esc = 1.0 if anual else 31.0
    Tb, Ta = 1.0 / (pb * esc), 1.0 / (pa * esc)
    r = {"valor": float(x), "lado": lado, "metodo": metodo, "p_antes": pb, "p_ahora": pa, "T_antes": min(Tb, T_MAX),
         "T_ahora": min(Ta, T_MAX), "T_tope": bool(Tb >= T_MAX or Ta >= T_MAX), "PR": PR, "pr_min": float(lo),
         "pr_max": float(hi), "significativo": bool(not (lo <= 1.0 <= hi))}
    if extra:
        r.update(extra)
    return r


# -- GEV por L-momentos (Hosking, Wallis y Wood 1985); la distribución es scipy.stats.genextreme ----------------
def _gev_lmom(V):
    V = np.sort(V, axis=1)
    n = V.shape[1]
    j = np.arange(1, n + 1)
    b0 = V.mean(1)
    b1 = (V * ((j - 1) / (n - 1))).mean(1)
    b2 = (V * ((j - 1) * (j - 2) / ((n - 1) * (n - 2)))).mean(1)
    l1, l2, l3 = b0, 2 * b1 - b0, 6 * b2 - 6 * b1 + b0
    with np.errstate(all="ignore"):
        t3 = l3 / l2
        c = 2.0 / (3.0 + t3) - math.log(2) / math.log(3)
        k = 7.8590 * c + 2.9554 * c * c
        k = np.clip(k, -GEV_FORMA_MAX, GEV_FORMA_MAX)
        g = gamma_fn(1 + k)
        alpha = l2 * k / ((1 - 2.0 ** (-k)) * g)
        xi = l1 + alpha * (g - 1) / k
        gum = np.abs(k) < 1e-6
        alpha = np.where(gum, l2 / math.log(2), alpha)
        xi = np.where(gum, l1 - 0.5772156649 * alpha, xi)
        bad = ~((alpha > 0) & np.isfinite(k) & np.isfinite(xi))
    k = np.where(bad, np.nan, k)
    return xi, alpha, k


def _gev_sf(x, xi, alpha, k):
    with np.errstate(all="ignore"):
        return genextreme.sf(x, c=k, loc=xi, scale=alpha)


def _extremos_mes(S, var, mes, filas, maximo):
    A = S.mat[var][filas][:, CUM[mes - 1]: CUM[mes]]
    m = ~np.isnan(A)
    ndias = (CUM[mes] - CUM[mes - 1]) - (1 if mes == 2 else 0)
    ok = m.sum(1) >= COBERTURA * ndias
    A = np.where(m, A, np.nan if maximo else np.nan)
    with np.errstate(all="ignore"):
        e = np.nanmax(A, axis=1) if maximo else np.nanmin(A, axis=1)
    return e[ok]


def _analizar_gev(S, var, f, x, lado, rng):
    maximo = lado == "calido"
    vb = _extremos_mes(S, var, f.month, FILAS_ANTES, maximo)
    va = _extremos_mes(S, var, f.month, FILAS_AHORA, maximo)
    if len(vb) < MIN_ANIOS or len(va) < MIN_ANIOS:
        return None
    sg = 1.0 if maximo else -1.0
    vb, va, xx = sg * vb, sg * va, sg * x
    ps = []
    boots = []
    for v in (vb, va):
        xi, al, k = _gev_lmom(v[None, :])
        if not np.isfinite(k[0]):
            return None
        ps.append(float(_gev_sf(xx, xi[0], al[0], k[0])))
        idx = rng.integers(0, len(v), size=(NBOOT, len(v)))
        xi, al, k = _gev_lmom(v[idx])
        b = _gev_sf(xx, xi, al, k)
        if np.isfinite(b).mean() < 0.7:
            return None
        boots.append(np.where(np.isfinite(b), b, np.nanmedian(b)))
    return _resultado(ps[0], ps[1], boots[0], boots[1], lado, "GEV", x, True,
                      {"nota": "cola extrema: estimación del extremo anual del mes (GEV por L-momentos)"})


def analizar_dia(S: Serie, var: str, f: date, x: float):
    """Periodo de retorno antes/ahora y PR del valor x de la variable var en el día f. None si la serie no alcanza."""
    if x is None or not math.isfinite(x):
        return None
    d = doy(f.month, f.day)
    fb, fa = S.fit(var, d, "antes"), S.fit(var, d, "ahora")
    if fb is None or fa is None:
        return None
    lado = "calido" if x >= fb["mean"] else "frio"
    sgn = 1 if lado == "calido" else -1
    Wb, Wa = S.ventana(var, d, FILAS_ANTES), S.ventana(var, d, FILAS_AHORA)
    rng = _rng(S.slug, S.fuente, var, f.isoformat())
    va = Wa[~np.isnan(Wa)]
    corte = np.percentile(va, P_COLA if sgn > 0 else 100 - P_COLA)
    if (sgn > 0 and x > corte) or (sgn < 0 and x < corte):
        r = _analizar_gev(S, var, f, x, lado, rng)
        if r is not None:
            r["n_antes"], r["n_ahora"] = fb["n"], fa["n"]
            return r
    # los dos climas con el mismo modelo: si el normal se rechaza en uno, empírica en ambos (si no, el cociente mezclaría modelos)
    emp = fb["ksp"] < UMBRAL_KS or fa["ksp"] < UMBRAL_KS
    pb, pbb, mb = _prob_ventana(Wb, fb, x, sgn, rng, emp)
    pa, pab, ma = _prob_ventana(Wa, fa, x, sgn, rng, emp)
    r = _resultado(pb, pa, pbb, pab, lado, mb, x, False)
    r["n_antes"], r["n_ahora"] = fb["n"], fa["n"]
    return r


# -- mensuales -----------------------------------------------------------------------
def _valores_mes(S, var, mes, k, filas, suma):
    A = S.mat[var][filas][:, CUM[mes - 1]: CUM[mes - 1] + k]
    m = ~np.isnan(A)
    esperado = np.array([min(k, calendar.monthrange(Y0 + int(y), mes)[1]) for y in filas])
    ok = m.sum(1) >= COBERTURA * esperado
    with np.errstate(all="ignore"):
        v = np.nansum(A, axis=1) if suma else np.nanmean(A, axis=1)
    return v[ok]


def _gamma0_fit(v):
    q = float(np.mean(v <= 0))
    pos = v[v > 0]
    if len(pos) < 5:
        return q, None, None
    a, _, sc = gamma_dist.fit(pos, floc=0)
    return q, a, sc


def _gamma0_p(x, par, lado):
    q, a, sc = par
    if a is None:
        return math.nan
    H = q if x <= 0 else q + (1 - q) * float(gamma_dist.cdf(x, a, 0, sc))
    return H if lado == "seco" else 1.0 - H


def analizar_muestras(vb, va, x, tipo, rng):
    """Mes: x frente a las 25-30 observaciones anuales de cada clima. tipo 'normal' (media) o 'gamma0' (lluvia, McKee)."""
    if len(vb) < MIN_ANIOS or len(va) < MIN_ANIOS:
        return None
    if tipo == "normal":
        lado = "calido" if x >= vb.mean() else "frio"
        sgn = 1 if lado == "calido" else -1
        ps, bs = [], []
        emp = any(ks_normal(v, float(v.mean()), float(v.std(ddof=1))) < UMBRAL_KS for v in (vb, va))
        for v in (vb, va):
            mean, sd = float(v.mean()), float(v.std(ddof=1))
            idx = rng.integers(0, len(v), size=(NBOOT, len(v)))
            if emp:
                h = silverman(v)
                ps.append(float(np.mean(ndtr(sgn * (v - x) / h))))
                bs.append(np.mean(ndtr(sgn * (v[idx] - x) / h), axis=1))
            else:
                ps.append(float(ndtr(-sgn * (x - mean) / sd)))
                R = v[idx]
                bs.append(ndtr(-sgn * (x - R.mean(1)) / np.maximum(R.std(1, ddof=1), 1e-9)))
        r = _resultado(ps[0], ps[1], bs[0], bs[1], lado, "empírica" if emp else "normal", x, True)
    else:
        lado = "humedo" if x >= vb.mean() else "seco"
        ps, bs = [], []
        for v in (vb, va):
            par = _gamma0_fit(v)
            ps.append(_gamma0_p(x, par, lado))
            idx = rng.integers(0, len(v), size=(NBOOT, len(v)))
            b = []
            for i in range(NBOOT):
                try:
                    b.append(_gamma0_p(x, _gamma0_fit(v[idx[i]]), lado))
                except Exception:
                    b.append(math.nan)
            bs.append(np.array(b))
        if not all(math.isfinite(p) for p in ps):
            return None
        bs = [np.where(np.isfinite(b), b, np.nanmedian(b)) for b in bs]
        r = _resultado(ps[0], ps[1], bs[0], bs[1], lado, "gamma con ceros (McKee)", x, True)
    r["media_antes"], r["media_ahora"] = float(vb.mean()), float(va.mean())
    r["n_antes"], r["n_ahora"] = len(vb), len(va)
    return r


# ----------------------------------------------------------------------------
# índice de huella
# ----------------------------------------------------------------------------
def nivel_de(r) -> int:
    if r is None or not r["significativo"]:
        return 0
    PR = r["PR"]
    if r["lado"] == "calido" and PR >= PR_UMBRALES[0]:
        return sum(1 for u in PR_UMBRALES if PR >= u)
    if r["lado"] == "frio" and PR < 1.0 and 1.0 / PR >= PR_UMBRALES[0]:
        return -sum(1 for u in PR_UMBRALES if 1.0 / PR >= u)
    return 0


def publicar(r, con_p=False):
    if r is None:
        return None
    o = {"valor": r1(r["valor"]), "lado": r["lado"], "metodo": r["metodo"], "T_antes": pub_ratio(r["T_antes"]),
         "T_ahora": pub_ratio(r["T_ahora"]), "T_tope": r["T_tope"], "PR": pub_pr(r["PR"]),
         "pr_min": pub_pr(r["pr_min"]), "pr_max": pub_pr(r["pr_max"]), "significativo": r["significativo"],
         "nivel": nivel_de(r)}
    if con_p:
        o["p_antes"] = float(f"{r['p_antes']:.6g}")
        o["p_ahora"] = float(f"{r['p_ahora']:.6g}")
        o["anios_antes"], o["anios_ahora"] = r.get("n_antes"), r.get("n_ahora")
    if r.get("nota"):
        o["nota"] = r["nota"]
    return o


def frase_rareza(r, que="día", sujeto="un día así") -> str:
    """«Un día así ocurría una vez cada 32 años en 1961-1990 y ahora una vez cada 4: es 8 veces más probable (intervalo 5-13)»."""
    Tb, Ta = frase_T(r["T_antes"], r["T_antes"] >= T_MAX), frase_T(r["T_ahora"], r["T_ahora"] >= T_MAX)
    pr, lo, hi = r["PR"], r["pr_min"], r["pr_max"]
    if pr >= 1:
        comp, inter = f"es {fratio(pr, True)} veces más probable", f"{fratio(lo, True)}-{fratio(hi, True)}"
    else:
        comp, inter = f"es {fratio(1 / pr, True)} veces menos probable", f"{fratio(1 / hi, True)}-{fratio(1 / lo, True)}"
    if r["significativo"]:
        cierre = f"{comp} (intervalo {inter})"
    else:
        cierre = f"{comp}, pero la diferencia no es significativa (el intervalo del 90 % incluye 1)"
    if r["T_antes"] >= T_MAX:
        cierre += "; con tan pocos casos en 1961-1990 el cociente es un mínimo"
    return f"{sujeto.capitalize()} ocurría {Tb} en 1961-1990 y ahora {Ta}: {cierre}."


# ----------------------------------------------------------------------------
# carga de las 52 capitales
# ----------------------------------------------------------------------------
def _leer_aemet(S: Serie, ide: str):
    filas = []
    with gzip.open(ARCH / "aemet_diario" / f"{ide}.csv.gz", "rt", encoding="utf-8") as fh:
        r = csv.reader(fh)
        cab = next(r)
        i = {c: cab.index(c) for c in ("fecha", "tmax", "tmin", "prec")}
        for row in r:
            filas.append((row[i["fecha"]], _f(row[i["tmax"]]), _f(row[i["tmin"]]), _f(row[i["prec"]])))
    S._cargar_filas(filas)


def _leer_era5(S: Serie, cod: str):
    filas = []
    base = ARCH / "era5" / cod
    for ruta, gz in ((base / "hasta_2025.csv.gz", True), (base / "2026.csv", False)):
        if not ruta.exists():
            continue
        fh = gzip.open(ruta, "rt", encoding="utf-8") if gz else open(ruta, encoding="utf-8")
        with fh:
            r = csv.reader(fh)
            cab = next(r)
            i = {c: cab.index(c) for c in ("fecha", "tmax", "tmin", "lluvia")}
            for row in r:
                filas.append((row[i["fecha"]], _f(row[i["tmax"]]), _f(row[i["tmin"]]), _f(row[i["lluvia"]])))
    S._cargar_filas(filas)


def _anios_validos(S: Serie, filas) -> int:
    ok = (~np.isnan(S.mat["tmax"][filas]) & ~np.isnan(S.mat["tmin"][filas])).sum(1)
    dias = np.array([366 if calendar.isleap(Y0 + int(y)) else 365 for y in filas])
    return int((ok >= COBERTURA * dias).sum())


def homogeneidad(cod: str) -> str:
    slug = SLUGS[cod]
    try:
        d = json.loads((DOCS / "tu-capital" / f"{slug}.json").read_text(encoding="utf-8"))
        return str(d["homogeneidad"]["estado"])
    except Exception:
        return "sin control"


def cargar_serie(cod: str, hoy: date, fuente_forzada: str | None = None) -> Serie:
    ny = max(hoy.year, 2026) - Y0 + 1
    motivo = ""
    if fuente_forzada != "era5" and cod in ESTACIONES:
        ruta = ARCH / "aemet_diario" / f"{ESTACIONES[cod][0]}.csv.gz"
        if ruta.exists():
            S = Serie(cod, "aemet", ny)
            _leer_aemet(S, ESTACIONES[cod][0])
            na, nh = _anios_validos(S, FILAS_ANTES), _anios_validos(S, FILAS_AHORA)
            hom = homogeneidad(cod)
            if na >= MIN_ANIOS and nh >= MIN_ANIOS and hom != "dudosa":
                S.homog = hom
                S.citabilidad = "alta" if hom == "ok" else "media"
                S.finalizar()
                return S
            motivo = (f"homogeneidad dudosa en la estación de AEMET ({ESTACIONES[cod][2]})" if hom == "dudosa"
                      else f"estación de AEMET con serie corta: {na} años válidos en {ANTES[0]}-{ANTES[1]} "
                           f"y {nh} en {AHORA[0]}-{AHORA[1]} (mínimo {MIN_ANIOS})")
            if fuente_forzada == "aemet":
                S.finalizar()
                return S
    elif cod not in ESTACIONES:
        motivo = "sin estación de AEMET con serie larga en la capital"
    if fuente_forzada == "aemet":
        raise KeyError(cod)
    S = Serie(cod, "era5", ny, motivo)
    _leer_era5(S, cod)
    S.homog = "no aplica (reanálisis)"
    S.citabilidad = "media"
    S.finalizar()
    return S


# ----------------------------------------------------------------------------
# caché de ajustes
# ----------------------------------------------------------------------------
def leer_cache() -> dict:
    try:
        with gzip.open(CACHE_RUTA, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def aplicar_cache(S: Serie, cache: dict):
    e = cache.get("series", {}).get(S.slug)
    if e and e.get("firma") == S.firma() and e.get("fuente") == S.fuente:
        S.cache = e["ajustes"]


def guardar_cache(series: list[Serie], cache: dict):
    out = cache if cache else {}
    out["climas"] = {"antes": list(ANTES), "ahora": list(AHORA), "ventana": VENTANA}
    out.setdefault("series", {})
    for S in series:
        if S.sucio or S.slug not in out["series"]:
            out["series"][S.slug] = {"firma": S.firma(), "fuente": S.fuente, "ajustes": _redondear_cache(S.cache)}
    CACHE_RUTA.parent.mkdir(parents=True, exist_ok=True)
    nuevo = json.dumps(out, separators=(",", ":"), ensure_ascii=False)
    if CACHE_RUTA.exists():
        try:
            with gzip.open(CACHE_RUTA, "rt", encoding="utf-8") as fh:
                if fh.read() == nuevo:
                    return
        except Exception:
            pass
    with gzip.GzipFile(str(CACHE_RUTA), "wb", mtime=0) as fh:
        fh.write(nuevo.encode("utf-8"))


def _redondear_cache(c):
    return {v: {cl: {"n": d["n"], "m": [None if x is None else round(x, 4) for x in d["m"]],
                     "s": [None if x is None else round(x, 4) for x in d["s"]],
                     "p": [None if x is None else round(x, 5) for x in d["p"]]} for cl, d in cl_.items()}
            for v, cl_ in c.items()}


# ----------------------------------------------------------------------------
# una capital
# ----------------------------------------------------------------------------
def _valor_dia(S: Serie, var: str, f: date):
    y = f.year - Y0
    if y < 0 or y >= S.ny:
        return None
    x = S.mat[var][y, doy(f.month, f.day)]
    return None if np.isnan(x) else float(x)


def indice_dia(S: Serie, f: date, memo: dict):
    k = (S.slug, f)
    if k not in memo:
        x = _valor_dia(S, "tmed", f)
        r = analizar_dia(S, "tmed", f, x) if x is not None else None
        memo[k] = (nivel_de(r) if r is not None else None, r)
    return memo[k]


def mes_referencia(f: date):
    """(año, mes, días contados, ¿cerrado?) del mes que se analiza según el último día con dato."""
    ult = calendar.monthrange(f.year, f.month)[1]
    if f.day >= MIN_DIAS_MES or f.day == ult:
        return f.year, f.month, f.day, f.day == ult
    a, m = (f.year - 1, 12) if f.month == 1 else (f.year, f.month - 1)
    n = calendar.monthrange(a, m)[1]
    return a, m, n, True


def bloque_mes(S: Serie, f: date):
    a, m, k, cerrado = mes_referencia(f)
    out = {"referencia": {"mes": f"{a}-{m:02d}", "mes_nombre": f"{MESES[m - 1]} de {a}", "dias": k,
                          "tipo": "cerrado" if cerrado else "en_curso",
                          "desde": date(a, m, 1).isoformat(), "hasta": date(a, m, k).isoformat()}}
    y = a - Y0
    for clave, var, suma, tipo in (("media", "tmed", False, "normal"), ("lluvia", "prec", True, "gamma0")):
        A = S.mat[var][y, CUM[m - 1]: CUM[m - 1] + k]
        valid = int((~np.isnan(A)).sum())
        if valid < COBERTURA * k:
            out[clave] = None
            continue
        x = float(np.nansum(A) if suma else np.nanmean(A))
        vb, va = (_valores_mes(S, var, m, k, fl, suma) for fl in (FILAS_ANTES, FILAS_AHORA))
        r = analizar_muestras(vb, va, x, tipo, _rng(S.slug, S.fuente, clave, a, m, k))
        o = publicar(r, True)
        if o:
            o["media_antes"], o["media_ahora"] = r1(r["media_antes"]), r1(r["media_ahora"])
            o["unidad"] = "°C" if clave == "media" else "mm"
            o["frase"] = frase_rareza(r, "mes", "un mes así" if clave == "media" else
                                      ("un mes así de húmedo" if r["lado"] == "humedo" else "un mes así de seco"))
        out[clave] = o
    return out


def lugar_txt(S: Serie) -> str:
    return f"la estación de AEMET de {S.estacion}" if S.fuente == "aemet" else f"la celda de {S.capital} del reanálisis ERA5"


def frase_hoy(S: Serie, f: date, r, nivel: int) -> str:
    base = f"El {fecha_larga(f)} la temperatura media en {lugar_txt(S)} fue de {fnum(r['valor'])} °C. "
    return base + frase_rareza(r) + " " + NIVEL_TEXTO[nivel] + "."


def procesar(S: Serie, hoy: date, memo: dict, completo: bool = True):
    f = S.ultima
    if f is None:
        return None
    hoyb = {}
    for var in ("tmax", "tmin", "tmed"):
        x = _valor_dia(S, var, f)
        r = analizar_dia(S, var, f, x)
        hoyb[var] = publicar(r, True)
        if var == "tmed":
            rt = r
    nivel = nivel_de(rt)
    hoyb["indice"] = nivel
    hoyb["nivel_texto"] = NIVEL_TEXTO[nivel]
    ult30 = []
    for i in range(DIAS_ULTIMOS - 1, -1, -1):
        d = f - timedelta(days=i)
        ind, _ = indice_dia(S, d, memo)
        ult30.append({"fecha": d.isoformat(), "indice": ind})
    prov = (hoy - f).days <= ERA5_CONSOLIDA_DIAS if S.fuente == "era5" else False
    ind30 = [u["indice"] for u in ult30 if u["indice"] is not None]
    base_txt = (f"Basado en la temperatura media del {fecha_larga(f)} en {lugar_txt(S)}; "
                f"{('dato provisional (ERA5 aún sin consolidar)' if prov else 'dato consolidado') if S.fuente == 'era5' else 'dato validado'}.")
    o = {"slug": S.slug, "cod": S.cod, "capital": S.capital, "provincia": S.provincia, "estacion": S.estacion,
         "indicativo": S.indicativo, "fuente": FUENTE_AEMET if S.fuente == "aemet" else FUENTE_ERA5,
         "tipo_fuente": S.fuente, "homogeneidad": S.homog, "citabilidad": S.citabilidad,
         "motivo_fuente": S.motivo or None,
         "climas": {"antes": list(ANTES), "ahora": list(AHORA)}, "fecha_dato": f.isoformat(), "provisional": prov,
         "hoy": hoyb, "mes": None,
         "ultimos_30": ult30,
         "resumen_30": {"dias_3_o_mas": sum(1 for v in ind30 if v >= 3), "dias_negativos": sum(1 for v in ind30 if v < 0),
                        "dias_con_dato": len(ind30), "media_indice": r1(sum(ind30) / len(ind30)) if ind30 else None},
         "textos": {"frase_hoy": frase_hoy(S, f, rt, nivel) if rt else None, "base": base_txt,
                    "metodo_corto": METODO_CORTO},
         "licencia": LICENCIA}
    if completo:
        mes = bloque_mes(S, f)
        o["mes"] = mes
    return o, rt


# ----------------------------------------------------------------------------
# antes era raro
# ----------------------------------------------------------------------------
def candidatos_antes_raro(S: Serie, f: date, memo_var: dict, o_mes) -> list[dict]:
    out = []
    for i in range(DIAS_ANTES_RARO):
        d = f - timedelta(days=i)
        for var, ind_calido in (("tmax", "tmax"), ("tmin", "tmin_alta"), ("tmed", "tmed_alta")):
            x = _valor_dia(S, var, d)
            if x is None:
                continue
            k = (S.slug, var, d)
            if k not in memo_var:
                memo_var[k] = analizar_dia(S, var, d, x)
            r = memo_var[k]
            if r and r["lado"] == "calido" and r["significativo"] and r["PR"] >= ANTES_RARO_PR and r["T_antes"] >= ANTES_RARO_T:
                out.append(_cand(S, d, ind_calido, "dia", r))
    if o_mes and o_mes.get("media") and o_mes["media"]["lado"] == "calido":
        m = o_mes["media"]
        if m["significativo"] and m["PR"] >= ANTES_RARO_PR and m["T_antes"] >= ANTES_RARO_T:
            out.append({"slug": S.slug, "cod": S.cod, "capital": S.capital, "provincia": S.provincia,
                        "fecha": o_mes["referencia"]["hasta"], "indicador": "mes_media_alta", "ambito_tiempo": "mes",
                        "mes": o_mes["referencia"]["mes_nombre"], "valor": m["valor"], "rareza": {
                            k: m[k] for k in ("T_antes", "T_ahora", "PR", "pr_min", "pr_max", "significativo", "metodo")},
                        "frase": m["frase"], "estacion": S.estacion, "fuente": FUENTE_AEMET if S.fuente == "aemet" else FUENTE_ERA5,
                        "tipo_fuente": S.fuente, "citabilidad": S.citabilidad, "provisional": False,
                        "cierre_mes": o_mes["referencia"]["tipo"]})
    return out


def _cand(S, d, ind, ambito, r):
    prov = S.fuente == "era5" and (date.today() - d).days <= ERA5_CONSOLIDA_DIAS
    return {"slug": S.slug, "cod": S.cod, "capital": S.capital, "provincia": S.provincia, "fecha": d.isoformat(),
            "indicador": ind, "ambito_tiempo": ambito, "valor": r1(r["valor"]),
            "rareza": {"T_antes": pub_ratio(r["T_antes"]), "T_ahora": pub_ratio(r["T_ahora"]), "PR": pub_pr(r["PR"]),
                       "pr_min": pub_pr(r["pr_min"]), "pr_max": pub_pr(r["pr_max"]), "significativo": r["significativo"],
                       "metodo": r["metodo"], "climas": [f"{ANTES[0]}-{ANTES[1]}", f"{AHORA[0]}-{AHORA[1]}"]},
            "frase": frase_rareza(r, "día", "un día así"), "estacion": S.estacion,
            "fuente": FUENTE_AEMET if S.fuente == "aemet" else FUENTE_ERA5, "tipo_fuente": S.fuente,
            "citabilidad": S.citabilidad, "provisional": bool(prov)}


# ----------------------------------------------------------------------------
# salida
# ----------------------------------------------------------------------------
def _sin_generado(o):
    if isinstance(o, dict):
        return {k: _sin_generado(v) for k, v in o.items() if k != "generado"}
    if isinstance(o, list):
        return [_sin_generado(v) for v in o]
    return o


def escribir_json(ruta: Path, obj) -> bool:
    """Escribe solo si cambia algo (sin contar «generado»): así el repositorio no se llena de commits idénticos."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if ruta.exists():
        try:
            if _sin_generado(json.loads(ruta.read_text(encoding="utf-8"))) == _sin_generado(obj):
                return False
        except Exception:
            pass
    ruta.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return True


def escribir_texto(ruta: Path, txt: str):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if ruta.exists() and ruta.read_text(encoding="utf-8") == txt:
        return
    ruta.write_text(txt, encoding="utf-8")


def svg_30(ult30: list[dict]) -> str:
    W, H, n = 1600, 300, len(ult30)
    paso = W / n
    ancho = paso - 8
    partes = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
              f'preserveAspectRatio="none" role="img" aria-label="Índice de huella climática de los últimos {n} días">']
    for i, u in enumerate(ult30):
        x = i * paso + 4
        if u["indice"] is None:
            partes.append(f'<rect x="{x:.1f}" y="{H - 6}" width="{ancho:.1f}" height="6" rx="3" fill="#9fb6c8" fill-opacity=".35"/>')
            continue
        v = u["indice"]
        h = 24 + 48 * abs(v)
        partes.append(f'<rect x="{x:.1f}" y="{H - h}" width="{ancho:.1f}" height="{h}" rx="5" fill="{NIVEL_COLOR[v]}">'
                      f'<title>{u["fecha"]}: {v:+d}</title></rect>')
    partes.append("</svg>\n")
    return "\n".join(partes)


def texto_metodo() -> str:
    niv = "\n".join(f"| {n:+d} | {NIVEL_COLOR[n]} | {NIVEL_TEXTO[n]} |" for n in range(5, -6, -1))
    return f"""# Huella climática del día · método

Índice de −5 a +5 que dice cuánto más (o menos) probable es la temperatura de un día en el clima de hoy que en el de
hace unas décadas. Lo calcula calentamientoglobal.es para las 52 capitales de provincia. Datos: AEMET y ERA5
(Copernicus/ECMWF). Licencia {LICENCIA}.

## Dos climas

- ANTES = {ANTES[0]}-{ANTES[1]} · AHORA = {AHORA[0]}-{AHORA[1]}. El día de hoy no entra en ninguno de los dos.

## Qué estaciones entran

- Estación de AEMET con valores diarios validados: ≥ {MIN_ANIOS} años válidos en cada clima (año válido = ≥ {int(COBERTURA * 100)} % de
  los días con máxima y mínima) y homogeneidad «ok» en el control de /cambio-climatico-en-<provincia>/. Si falta el control
  («sin control»), la capital entra con citabilidad media. Con homogeneidad «dudosa» no entra: su salto de serie se
  confundiría con cambio climático.
- Las capitales cuya estación no cumple (serie corta, homogeneidad dudosa o sin estación larga) usan el reanálisis ERA5 en
  la celda de la capital, con citabilidad media y la fuente dicha en cada texto. ERA5 anterior a 1979 es una
  retroextensión preliminar: limita el clima de ANTES en esas capitales.

## Variables diarias (tmax, tmin, tmed = (tmax + tmin)/2)

1. Para el día D, la ventana de cada clima son los ±{VENTANA} días del calendario alrededor de D en cada año (≈ 900 valores por
   clima). Un año cuenta si tiene ≥ {MIN_DIAS_VENTANA} de los 31 días; hacen falta ≥ {MIN_ANIOS} años.
2. Ajuste normal (media y desviación) a cada ventana. Se comprueba con Kolmogorov-Smirnov (p asintótico); si p < {UMBRAL_KS}
   se usa la distribución empírica con suavizado por kernel gaussiano de ancho de Silverman.
   Para que el cociente compare lo comparable, si el normal se rechaza en uno de los dos climas se usa la empírica en los dos.
3. Para el valor observado x: si x ≥ media del clima de antes, lado cálido, p = P(X ≥ x); si no, lado frío, p = P(X ≤ x),
   en cada clima. Periodo de retorno T = 1 / (31 · p) años (31 días de ventana por año).
4. Cociente de probabilidad PR = p_ahora / p_antes. Intervalo del 90 %: {NBOOT} remuestreos de años de cada clima, cuantiles 5 y 95. Si el
   intervalo incluye 1, la diferencia no es significativa.
5. Cola: si x queda más allá del percentil {P_COLA} del clima de ahora, la cola normal subestima. Entonces se usa una
   GEV (scipy.stats.genextreme, parámetros por L-momentos) sobre los máximos anuales (o mínimos, en el lado frío) del
   mes de D en cada clima; T y PR son entonces los del extremo anual del mes (T = 1/p en años).
6. Probabilidades por debajo de 1/{T_MAX} años (1/(31·{T_MAX}) por día) se acotan: por encima de {T_MAX} años no se distingue.

## Variables mensuales

Media del mes (normal, mismo KS) y lluvia del mes (gamma ajustada por máxima verosimilitud a los meses con lluvia, con la
mezcla de ceros de McKee, como en el Monitor de sequía; la función de sequia.py no se importa porque está atada a su
estructura de datos y se copia el ajuste). Mes en curso: media hasta el último día con dato frente a los mismos días de
cada año de los dos climas (≥ {MIN_DIAS_MES} días con dato); si el mes empieza, el último mes cerrado. T = 1/p años.

## Índice de huella (de −5 a +5), con la temperatura media del día

Solo se asigna nivel distinto de 0 si el PR es significativo. Lado cálido: +1 PR ≥ {PR_UMBRALES[0]}, +2 ≥ {PR_UMBRALES[1]:.0f},
+3 ≥ {PR_UMBRALES[2]:.0f}, +4 ≥ {PR_UMBRALES[3]:.0f}, +5 ≥ {PR_UMBRALES[4]:.0f}. Lado frío: los mismos umbrales sobre 1/PR (el frío se ha
vuelto menos probable). Si no, 0.

| Nivel | Color | Texto |
|---|---|---|
{niv}

## Límites

- Compara dos climas observados; no atribuye un día concreto a una causa. «Por el calentamiento» resume que la diferencia
  entre los dos climas es el calentamiento observado.
- Un día no es una muestra independiente: la ventana de ±{VENTANA} días mezcla días vecinos que se parecen. El intervalo
  remuestrea años enteros para respetarlo.
- El dato del último día es validado en las estaciones de AEMET (con 10-20 días de retraso) y preliminar en ERA5 durante
  los primeros {ERA5_CONSOLIDA_DIAS} días.
- Cada capital tiene su último día con dato: el resumen nacional usa el día más reciente con dato en ≥ {int(FRAC_NACIONAL * 100)} % de
  las capitales, y nunca habla «de España» por debajo de ese porcentaje.

## Cómo citar

calentamientoglobal.es, Huella climática del día, <capital>, <fecha del dato>, datos AEMET/ERA5, cálculo propio, {LICENCIA}.
"""


# ----------------------------------------------------------------------------
# API para el detector de hallazgos
# ----------------------------------------------------------------------------
_SERIES_API: dict = {}


def rareza_capital(cod: str, fecha, var: str, valor: float, fuente: str = "era5"):
    """Rareza de un valor diario de una capital: dict publicable (T, PR, intervalo, frase) o None si no hay serie.
    fuente 'era5': la serie de reanálisis de la capital (la de los hallazgos de «capitales»); 'aemet': su estación, si entra."""
    try:
        f = date.fromisoformat(str(fecha)[:10])
        clave = (cod, fuente)
        if clave not in _SERIES_API:
            try:
                _SERIES_API[clave] = cargar_serie(cod, date.today(), fuente_forzada=fuente)
            except KeyError:
                _SERIES_API[clave] = None
        S = _SERIES_API[clave]
        if S is None:
            return None
        r = analizar_dia(S, var, f, float(valor))
        if r is None:
            return None
        o = publicar(r)
        o["climas"] = [f"{ANTES[0]}-{ANTES[1]}", f"{AHORA[0]}-{AHORA[1]}"]
        o["frase"] = frase_rareza(r, "día", "un día así" if var != "tmin" else "una noche así")
        o["fuente_serie"] = "ERA5" if S.fuente == "era5" else "AEMET"
        o["PR_num"], o["T_antes_num"] = float(r["PR"]), float(r["T_antes"])
        return o
    except Exception:
        return None


# ----------------------------------------------------------------------------
# principal
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hoy", default=None)
    ap.add_argument("--solo", default=None)
    ap.add_argument("--sin-historico", action="store_true")
    ap.add_argument("--sin-cache", action="store_true")
    ap.add_argument("--tabla", action="store_true", help="imprime la tabla por capital")
    a = ap.parse_args()
    hoy = date.fromisoformat(a.hoy) if a.hoy else date.today()
    t0 = time.time()
    cache = {} if a.sin_cache else leer_cache()
    cods = sorted(SLUGS)
    if a.solo:
        pedidas = set(a.solo.split(","))
        cods = [c for c in cods if SLUGS[c] in pedidas]
    series, salidas, memo, memo_var = [], {}, {}, {}
    antes_raro = []
    generado = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    for cod in cods:
        S = cargar_serie(cod, hoy)
        aplicar_cache(S, cache)
        if S.ultima is None:
            log(f"{S.slug}: sin datos")
            continue
        if not S.cache:
            S.precalcular()
        res = procesar(S, hoy, memo)
        if res is None:
            continue
        o, rt = res
        o["generado"] = generado
        salidas[S.slug] = (S, o, rt)
        antes_raro += candidatos_antes_raro(S, S.ultima, memo_var, o["mes"])
        series.append(S)
        log(f"{S.slug:24s} {S.fuente:5s} {S.citabilidad:5s} {S.ultima} índice {o['hoy']['indice']:+d}")
        # históricos: se calculan ahora, con la serie en memoria
        if not a.sin_historico:
            _historico_serie(S, hoy, memo)
        S.liberar()
    # --- salidas por capital
    for slug, (S, o, rt) in salidas.items():
        escribir_json(SALIDA / f"{slug}.json", o)
        escribir_texto(SALIDA / "graf" / f"{slug}.svg", svg_30(o["ultimos_30"]))
    index = construir_index(salidas, memo, generado)
    escribir_json(SALIDA / "index.json", index)
    antes_raro.sort(key=lambda c: -c["rareza"]["PR"] if isinstance(c["rareza"]["PR"], (int, float)) else 0)
    escribir_json(SALIDA / "antes_raro.json", {"generado": generado, "criterio": f"PR ≥ {ANTES_RARO_PR:g} con intervalo del 90 % "
                  f"que no incluye 1 y T_antes ≥ {ANTES_RARO_T:g} años, lado cálido, últimos {DIAS_ANTES_RARO} días con dato",
                  "candidatos": antes_raro, "licencia": LICENCIA})
    escribir_texto(SALIDA / "metodo.md", texto_metodo())
    if not a.solo and not a.sin_cache:
        guardar_cache(series, cache)
    if not a.sin_historico:
        _escribir_historico(generado)
    log(f"Hecho en {time.time() - t0:.0f} s · {len(salidas)} capitales · {len(antes_raro)} candidatos «antes era raro»")
    if a.tabla:
        tabla(salidas)


_HIST: dict = {}   # 'AAAA-MM' -> {fecha: {slug: nivel}}


def _historico_serie(S: Serie, hoy: date, memo: dict):
    """Índice diario de la capital en los meses que toca recalcular: el actual y el anterior, y los que falten desde enero."""
    fin = S.ultima
    desde = date(hoy.year, 1, 1)
    d = desde
    while d <= fin:
        ym = f"{d.year}-{d.month:02d}"
        ruta = SALIDA / "historico" / f"{ym}.json"
        reciente = (fin - d).days <= 62
        if reciente or not ruta.exists():
            ind, _ = indice_dia(S, d, memo)
            _HIST.setdefault(ym, {}).setdefault(d.isoformat(), {})[S.slug] = ind
        d += timedelta(days=1)


def _escribir_historico(generado: str):
    for ym, dias in sorted(_HIST.items()):
        ruta = SALIDA / "historico" / f"{ym}.json"
        previo = {}
        if ruta.exists():
            try:
                previo = json.loads(ruta.read_text(encoding="utf-8")).get("dias", {})
            except Exception:
                previo = {}
        for f, v in dias.items():
            previo.setdefault(f, {}).update(v)
        escribir_json(ruta, {"mes": ym, "variable": "tmed", "escala": "indice de huella −5..+5 (null = sin dato)",
                             "dias": dict(sorted(previo.items())), "generado": generado, "licencia": LICENCIA})


def construir_index(salidas: dict, memo: dict, generado: str) -> dict:
    n_tot = len(SLUGS)
    # día de referencia nacional: el más reciente con dato de tmed en ≥ 80 % de las capitales
    cuenta: dict = {}
    for slug, (S, o, rt) in salidas.items():
        for u in o["ultimos_30"]:
            if u["indice"] is not None:
                cuenta[u["fecha"]] = cuenta.get(u["fecha"], 0) + 1
    ref = None
    for f in sorted(cuenta, reverse=True):
        if cuenta[f] >= FRAC_NACIONAL * n_tot:
            ref = f
            break
    caps = []
    for slug, (S, o, rt) in salidas.items():
        ind_ref = None
        if ref:
            for u in o["ultimos_30"]:
                if u["fecha"] == ref:
                    ind_ref = u["indice"]
        caps.append({"slug": slug, "capital": S.capital, "provincia": S.provincia, "cod": S.cod,
                     "indice": o["hoy"]["indice"], "PR_tmed": o["hoy"]["tmed"]["PR"] if o["hoy"]["tmed"] else None,
                     "fecha_dato": o["fecha_dato"], "provisional": o["provisional"], "citabilidad": o["citabilidad"],
                     "tipo_fuente": S.fuente, "indice_ref": ind_ref})
    caps.sort(key=lambda c: (-(c["indice"] if c["indice"] is not None else -9), c["slug"]))
    con_ref = [c["indice_ref"] for c in caps if c["indice_ref"] is not None]
    out = {"generado": generado, "n_capitales": n_tot, "n_con_dato": len(caps), "fecha_referencia": ref,
           "n_con_dato_ref": len(con_ref), "n_3_o_mas": sum(1 for v in con_ref if v >= 3),
           "n_4_o_mas": sum(1 for v in con_ref if v >= 4), "n_negativos": sum(1 for v in con_ref if v < 0),
           "media_indice": r1(sum(con_ref) / len(con_ref)) if con_ref else None,
           "n_estaciones_aemet": sum(1 for c in caps if c["tipo_fuente"] == "aemet"),
           "n_era5": sum(1 for c in caps if c["tipo_fuente"] == "era5"),
           "capitales": caps, "climas": {"antes": list(ANTES), "ahora": list(AHORA)}, "licencia": LICENCIA}
    if ref and len(con_ref) >= FRAC_NACIONAL * n_tot:
        out["frase_nacional"] = (f"El {fecha_larga(date.fromisoformat(ref))}, {out['n_3_o_mas']} de {len(con_ref)} capitales españolas "
                                 f"tenían una temperatura media con nivel de huella +3 o más: un día así es al menos tres veces más "
                                 f"probable que en {ANTES[0]}-{ANTES[1]}.")
    else:
        out["frase_nacional"] = None
    out["metodo_corto"] = METODO_CORTO
    return out


def tabla(salidas: dict):
    print(f"{'capital':22s} {'fuente':6s} {'cit':5s} {'homog':11s} {'fecha':10s} idx  tmed  PR (int)       T antes/ahora   mes")
    for slug, (S, o, rt) in sorted(salidas.items()):
        t = o["hoy"]["tmed"] or {}
        m = (o.get("mes") or {}).get("media") or {}
        print(f"{S.capital:22s} {S.fuente:6s} {S.citabilidad:5s} {S.homog[:11]:11s} {o['fecha_dato']} {o['hoy']['indice']:+d}  "
              f"{t.get('valor')}  {t.get('PR')} ({t.get('pr_min')}-{t.get('pr_max')})  {t.get('T_antes')}/{t.get('T_ahora')}  "
              f"mes {m.get('valor')} PR {m.get('PR')} ({m.get('pr_min')}-{m.get('pr_max')})")


if __name__ == "__main__":
    main()
