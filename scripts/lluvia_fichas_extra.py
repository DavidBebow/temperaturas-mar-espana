#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lluvia_fichas_extra.py · lo que hace volver a una ficha de lluvia: el ano hidrologico al dia,
el ultimo episodio frente a la historia, el mes, el calendario, los records y el chaparron.

Version 1.0.0 (22-10-2026) · calentamientoglobal.es

REGLA DE SIEMPRE: numerador y denominador del mismo pluviometro de AEMET. Nunca punto contra
rejilla (desviaba la mediana un 19 %). Ninguna frase de "desde" si la serie tiene huecos en
medio: solo se dice "no llovia tanto desde X" cuando todos los anos entre X y hoy estan medidos.

ENTRADAS (repo publico)
  archivo/lluvia_diaria/<anio>.json.gz   diarios validados de AEMET (lluvia_diaria_crudo.py)
  archivo/aemet_diario/<id>.csv.gz       series largas de 109 estaciones (desde 1920-1960)
  historico_pluviometrico.json           dias pluviometricos (07-07 UTC) con mascara de horas
  historico_estaciones.json              dias locales con mascara de horas (respaldo)
  docs/municipios_mapa.json              las 999 fichas: nombre, ruta, coordenadas
  docs/lluvias_municipios.json           pluviometro de "Lluvia hoy" de cada ficha (+ ids)
  docs/otonio_municipios.json            pluviometro con referencia de cada ficha
SALIDAS
  docs/lluvia_extra/<cod_provincia>.json lo que pinta el plugin cg-lluvia-plus
  docs/lluvia_extra/resumen.json         fecha, avance de la descarga y cifras por provincia
  archivo/lluvia_extra/intensidad.json   el chaparron mas fuerte de cada dia y estacion
"""
import csv
import gzip
import io
import json
import math
import os
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

VERSION = "1.0.1"
RAIZ = Path(__file__).resolve().parent.parent
DIARIA = RAIZ / "archivo" / "lluvia_diaria"
LARGAS = RAIZ / "archivo" / "aemet_diario"
PLUVIO = RAIZ / "historico_pluviometrico.json"
HIST = RAIZ / "historico_estaciones.json"
MAPA = RAIZ / "docs" / "municipios_mapa.json"
LLUVIA = RAIZ / "docs" / "lluvias_municipios.json"
OTONIO = RAIZ / "docs" / "otonio_municipios.json"
SALIDA = RAIZ / "docs" / "lluvia_extra"
INTENS = RAIZ / "archivo" / "lluvia_extra" / "intensidad.json"
BASE_AEMET = "https://opendata.aemet.es/opendata/api"

ORIGEN = date(1991, 1, 1)       # dia 0 de las series del crudo
NORMAL = (1991, 2020)           # anos hidrologicos que empiezan el 1-10 de 1991 ... 2020
ANIOS_MIN = 20                  # para llamarlo "normal 1991-2020"
ANIOS_MIN_RESPALDO = 15         # si no, media de todos los anos medidos, diciendo cuales
HUECOS = 3                      # dias sin dato que se le perdonan a una ventana
LLUVIOSO = 1.0                  # mm: dia de lluvia (convenio de AEMET y de la OMM)
VECINOS_KM = 35.0
VECINOS_N = 15                  # el plugin enseña hasta 7, sin repetir pluviómetro
FRESCURA = 6                    # dias: una serie que no llega a hoy menos esto no da "al dia"
MIN_MUNICIPIOS = int(os.environ.get("CG_MIN_MUNICIPIOS", "300"))
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def leer_json(p, defecto=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return defecto


def km_entre(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def r1(x):
    return None if x is None else round(x + 0.0, 1)


def pctl(vals, q):
    v = sorted(vals)
    if not v:
        return None
    k = (len(v) - 1) * q
    f = math.floor(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


def zona(idema):
    """Las estaciones de Canarias empiezan por C."""
    return "Atlantic/Canary" if str(idema).startswith("C") else "Europe/Madrid"


def hora_local(dt_utc, idema):
    if ZoneInfo is None:
        return dt_utc + timedelta(hours=1)
    return dt_utc.astimezone(ZoneInfo(zona(idema)))


def etiqueta_hidro(a):
    return "%d-%02d" % (a, (a + 1) % 100)


# ------------------------------------------------------------ series

class Serie:
    """Lluvia diaria de una estacion: lista indexada por dias desde `ini`.
    `fuente[i]`: 'v' validado, 'p' dia pluviometrico aun sin validar, 'h' dia local."""

    def __init__(self, ini, valores, fuente):
        self.ini = ini
        self.v = valores
        self.f = fuente

    def idx(self, d):
        return (d - self.ini).days

    def get(self, d):
        i = self.idx(d)
        if 0 <= i < len(self.v):
            return self.v[i]
        return None

    def fin(self):
        return self.ini + timedelta(days=len(self.v) - 1)


def cargar_crudo(estaciones):
    """{idema: {indice_desde_ORIGEN: mm}} solo de las estaciones pedidas."""
    out = {e: {} for e in estaciones}
    anios = sorted(int(p.name.split(".")[0]) for p in DIARIA.glob("*.json.gz") if p.name[:4].isdigit())
    for a in anios:
        try:
            with gzip.open(DIARIA / ("%d.json.gz" % a), "rt", encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:  # noqa: BLE001
            log("  %d ilegible: %s" % (a, e))
            continue
        base = (date(a, 1, 1) - ORIGEN).days
        for e in estaciones:
            lst = d["est"].get(e)
            if not lst:
                continue
            dst = out[e]
            for i, x in enumerate(lst):
                if x is not None:
                    dst[base + i] = x
    log("Crudo: %d anos (%s-%s)" % (len(anios), anios[0] if anios else "-", anios[-1] if anios else "-"))
    return out, anios


def cargar_larga(idema):
    p = LARGAS / ("%s.csv.gz" % idema)
    if not p.exists():
        return None
    out = {}
    try:
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                v = r.get("prec")
                if v in (None, ""):
                    continue
                try:
                    out[date.fromisoformat(r["fecha"])] = float(v)
                except ValueError:
                    continue
    except Exception as e:  # noqa: BLE001
        log("  serie larga %s ilegible: %s" % (idema, e))
        return None
    return out or None


def popcount(m):
    return bin(int(m)).count("1")


def construir_serie(idema, crudo_e, larga, pluvio, hist, hoy):
    """Une validado (crudo + serie larga) y, detras, los dias pluviometricos aun sin validar.
    Devuelve (Serie, info) o (None, None)."""
    vals = {}
    if larga:
        for d, x in larga.items():
            vals[d] = (x, "v")
    for i, x in crudo_e.items():
        vals[ORIGEN + timedelta(days=i)] = (x, "v")
    if not vals:
        return None, None
    ultimo_val = max(vals)
    info = {"validado_hasta": ultimo_val.isoformat()}

    # Cola: dias pluviometricos completos despues del ultimo validado, y el de hoy a medias.
    cola = {}
    d = ultimo_val + timedelta(days=1)
    parcial = None
    while d <= hoy:
        k = d.isoformat()
        x = (pluvio.get(k) or {}).get(idema)
        if not x:
            break
        horas = popcount(x[1])
        if horas >= 24:
            cola[d] = (float(x[0]), "p")
        else:
            # Solo el ultimo dia puede ir a medias; uno a medias en medio corta la cola.
            if d == max((date.fromisoformat(z) for z in pluvio), default=d):
                parcial = (d, float(x[0]), horas)
            break
        d += timedelta(days=1)
    # Nunca se sustituye un dia validado. Sin dias pluviometricos que empalmen (07-07 UTC, la
    # misma convencion que los validados), la serie se queda en el ultimo dia validado: se dice
    # "hasta el dia X" en vez de mezclar dias locales con dias pluviometricos.
    usado = "pluviometrico"
    for g, z in cola.items():
        vals[g] = z
    if parcial:
        vals[parcial[0]] = (parcial[1], "p" if usado == "pluviometrico" else "h")
    ini = min(vals)
    fin = max(vals)
    n = (fin - ini).days + 1
    v, f = [None] * n, [None] * n
    for d, (x, src) in vals.items():
        i = (d - ini).days
        v[i] = x
        f[i] = src
    s = Serie(ini, v, f)
    if parcial:
        info["parcial"] = {"fecha": parcial[0].isoformat(), "horas": parcial[2], "conv": usado}
    info["hasta"] = fin.isoformat()
    info["cola"] = usado
    return s, info


# --------------------------------------------------------- utilidades

def completo(s, d0, n, huecos=HUECOS):
    """Faltan como mucho `huecos` dias en [d0, d0+n)."""
    falta = 0
    for k in range(n):
        if s.get(d0 + timedelta(days=k)) is None:
            falta += 1
            if falta > huecos:
                return False
    return True


def faltas_acum(s, d0, n):
    """Dias sin dato acumulados en [d0, d0+k] para cada k."""
    out, falta = [], 0
    i0 = s.idx(d0)
    for k in range(n):
        i = i0 + k
        if not (0 <= i < len(s.v)) or s.v[i] is None:
            falta += 1
        out.append(falta)
    return out


def media_por_dia_hidro(s):
    """Lluvia media de cada dia del ano hidrologico (0 = 1 de octubre), para rellenar huecos."""
    suma, cuenta = [0.0] * 366, [0] * 366
    for i, x in enumerate(s.v):
        if x is None or s.f[i] != "v":
            continue
        d = s.ini + timedelta(days=i)
        a = d.year if d.month >= 10 else d.year - 1
        k = (d - date(a, 10, 1)).days
        suma[k] += x
        cuenta[k] += 1
    return [suma[k] / cuenta[k] if cuenta[k] else 0.0 for k in range(366)]


def acumulado(s, d0, n, relleno, k0=0):
    tot, out = 0.0, []
    for k in range(n):
        x = s.get(d0 + timedelta(days=k))
        tot += x if x is not None else relleno[(k0 + k) % 366]
        out.append(tot)
    return out


def anios_completos_naturales(s, hoy):
    """Anos naturales con >= 350 dias medidos (el actual: con todo lo que lleva menos 10)."""
    por = {}
    for i, x in enumerate(s.v):
        if x is not None:
            y = (s.ini + timedelta(days=i)).year
            por[y] = por.get(y, 0) + 1
    ok = set()
    for y, n in por.items():
        need = 350 if y < hoy.year else max(0, (hoy - date(y, 1, 1)).days - 10)
        if n >= need:
            ok.add(y)
    return ok


def tramo_continuo(ok, hoy):
    """Primer ano del tramo de anos completos que llega sin cortes hasta hoy."""
    y = hoy.year
    if y not in ok:
        return None
    while (y - 1) in ok:
        y -= 1
    return y


def fecha_larga(d):
    return "%d de %s de %d" % (d.day, MESES[d.month - 1], d.year)


# ------------------------------------------------------------- bloques

def bloque_anio(s, hoy_info, relleno):
    """Ano hidrologico al dia contra el mismo tramo de cada ano del mismo pluviometro."""
    fin = s.fin()
    hy = date(fin.year if fin.month >= 10 else fin.year - 1, 10, 1)
    par = hoy_info.get("parcial")
    frac = 1.0
    ultimo_entero = fin
    if par and par["fecha"] == fin.isoformat():
        frac = par["horas"] / 24.0
        ultimo_entero = fin - timedelta(days=1)
    n_ent = (ultimo_entero - hy).days + 1           # dias enteros desde el 1 de octubre
    if n_ent < 0:
        return None
    # este ano
    if n_ent and not completo(s, hy, n_ent):
        return None
    k0 = 0
    act = acumulado(s, hy, n_ent, relleno) if n_ent else []
    mm_act = (act[-1] if act else 0.0) + ((s.get(fin) or 0.0) if frac < 1.0 else 0.0)
    if frac >= 1.0 and n_ent == 0:
        mm_act = 0.0
    # anos anteriores, mismo tramo
    anios, parciales = {}, {}
    largo = n_ent + (1 if frac < 1 else 0)
    for a in range(s.ini.year, hy.year):
        d0 = date(a, 10, 1)
        if d0 < s.ini:
            continue
        if not completo(s, d0, largo):
            # Ano con huecos: no entra en la comparacion, pero su suma parcial es una cota
            # inferior. Si ya supera a lo que se quiere afirmar, la afirmacion no vale.
            vals_p = [s.get(d0 + timedelta(days=k)) for k in range(largo)]
            if any(x is not None for x in vals_p):
                parciales[a] = sum(x for x in vals_p if x is not None)
            continue
        c = acumulado(s, d0, n_ent + 1, relleno, k0)
        base = c[n_ent - 1] if n_ent else 0.0
        dia = c[n_ent] - base
        anios[a] = base + dia * (frac if frac < 1 else 0.0)
    norm = [x for a, x in anios.items() if NORMAL[0] <= a <= NORMAL[1]]
    if len(norm) >= ANIOS_MIN:
        conj = {a: x for a, x in anios.items() if NORMAL[0] <= a <= NORMAL[1]}
        periodo = "%d-%d" % NORMAL
    elif len(anios) >= ANIOS_MIN_RESPALDO:
        conj = dict(anios)
        periodo = "%d-%d" % (min(conj), max(conj))
    else:
        return None
    vals = list(conj.values())
    normal = sum(vals) / len(vals)
    todos = dict(anios)
    todos[hy.year] = mm_act
    orden = sorted(todos.items(), key=lambda t: -t[1])
    puesto = [a for a, _ in orden].index(hy.year) + 1
    pasados = {a: x for a, x in anios.items()}
    mas_ll = max(pasados.items(), key=lambda t: t[1])
    mas_se = min(pasados.items(), key=lambda t: t[1])
    inc_superan = sum(1 for x in parciales.values() if x >= mm_act)
    mas_ll_dudoso = any(x > mas_ll[1] for x in parciales.values())

    # curvas (muestras cada 7 dias) para el grafico
    paso = 7
    muestras = list(range(0, 365, paso)) + [364]
    banda = {"i": [], "p20": [], "med": [], "p80": []}
    curvas_anio, faltas = {}, {}
    for a in conj:
        d0 = date(a, 10, 1)
        curvas_anio[a] = acumulado(s, d0, 365, relleno)
        faltas[a] = faltas_acum(s, d0, 365)
    for i in muestras:
        vs = []
        for a in conj:
            if faltas[a][i] <= HUECOS:
                vs.append(curvas_anio[a][i])
        if len(vs) < (ANIOS_MIN if periodo == "%d-%d" % NORMAL else ANIOS_MIN_RESPALDO):
            break
        banda["i"].append(i)
        banda["p20"].append(r1(pctl(vs, 0.2)))
        banda["med"].append(r1(sum(vs) / len(vs)))
        banda["p80"].append(r1(pctl(vs, 0.8)))
    total_normal = None
    llenos = [curvas_anio[a][364] for a in conj if faltas[a][364] <= 5]
    if len(llenos) >= (ANIOS_MIN if periodo == "%d-%d" % NORMAL else ANIOS_MIN_RESPALDO):
        total_normal = sum(llenos) / len(llenos)
    ant = None
    a_ant = hy.year - 1
    d_ant = date(a_ant, 10, 1)
    if d_ant >= s.ini:
        c_ant = acumulado(s, d_ant, 365, relleno)
        f_ant = faltas_acum(s, d_ant, 365)
        ant_i = []
        for i in muestras:
            if f_ant[i] <= HUECOS:
                ant_i.append(r1(c_ant[i]))
            else:
                break
        ant = ant_i
    act_curva = [r1(x) for x in act]
    if frac < 1.0:
        act_curva.append(r1(mm_act))
    return {
        "desde": hy.isoformat(),
        "etiqueta": etiqueta_hidro(hy.year),
        "dias": n_ent,
        "frac": round(frac, 3),
        "mm": r1(mm_act),
        "normal": r1(normal),
        "pct": int(round(mm_act / normal * 100)) if normal > 0.5 else None,
        "p20": r1(pctl(vals, 0.2)),
        "p80": r1(pctl(vals, 0.8)),
        "periodo": periodo,
        "n_normal": len(vals),
        "puesto": puesto,
        "de": len(todos),
        "desde_anio": min(todos),
        "mas_lluvioso": {"anio": etiqueta_hidro(mas_ll[0]), "mm": r1(mas_ll[1]), "dudoso": mas_ll_dudoso},
        "mas_seco": {"anio": etiqueta_hidro(mas_se[0]), "mm": r1(mas_se[1])},
        "incompletos": len(parciales),
        "incompletos_superan": inc_superan,
        "anterior": r1(anios.get(a_ant)),
        "total_normal": r1(total_normal),
        "curva": {"paso": paso, "banda": banda, "act": act_curva, "ant": ant},
    }


def bloque_mes(s, hoy_info, relleno_dia):
    fin = s.fin()
    par = hoy_info.get("parcial")
    frac = 1.0
    ultimo_entero = fin
    if par and par["fecha"] == fin.isoformat():
        frac = par["horas"] / 24.0
        ultimo_entero = fin - timedelta(days=1)
    m0 = date(fin.year, fin.month, 1)
    n_ent = (ultimo_entero - m0).days + 1
    if n_ent < 0:
        return None
    if n_ent and not completo(s, m0, n_ent, 2):
        return None
    mm_act = sum(s.get(m0 + timedelta(days=k)) or 0.0 for k in range(max(n_ent, 0)))
    if frac < 1.0:
        mm_act += s.get(fin) or 0.0
    dias_mes = ((m0.replace(day=28) + timedelta(days=4)).replace(day=1) - m0).days
    hasta, total, parcial_inc = {}, {}, {}
    for a in range(s.ini.year, fin.year):
        d0 = date(a, fin.month, 1)
        if d0 < s.ini:
            continue
        dm = ((d0.replace(day=28) + timedelta(days=4)).replace(day=1) - d0).days
        if not completo(s, d0, dm, 2):
            vv = [s.get(d0 + timedelta(days=k)) for k in range(dm)]
            if any(x is not None for x in vv):
                parcial_inc[a] = sum(x for x in vv if x is not None)
            continue
        vals = [s.get(d0 + timedelta(days=k)) for k in range(dm)]
        vals = [x if x is not None else 0.0 for x in vals]
        base = sum(vals[:n_ent])
        if frac < 1.0 and n_ent < dm:
            base += vals[n_ent] * frac
        hasta[a] = base
        total[a] = sum(vals)
    norm = [a for a in hasta if NORMAL[0] <= a <= NORMAL[1]]
    if len(norm) >= ANIOS_MIN:
        conj, periodo = norm, "%d-%d" % NORMAL
    elif len(hasta) >= ANIOS_MIN_RESPALDO:
        conj = list(hasta)
        periodo = "%d-%d" % (min(conj), max(conj))
    else:
        return None
    nh = sum(hasta[a] for a in conj) / len(conj)
    tots = [total[a] for a in conj]
    mx = max(total.items(), key=lambda t: t[1])
    return {"mes": MESES[fin.month - 1], "dias": n_ent, "frac": round(frac, 3), "dias_mes": dias_mes,
            "mm": r1(mm_act), "normal": r1(nh), "pct": int(round(mm_act / nh * 100)) if nh > 0.5 else None,
            "normal_mes": r1(sum(tots) / len(tots)), "p20_mes": r1(pctl(tots, 0.2)), "p80_mes": r1(pctl(tots, 0.8)),
            "periodo": periodo, "n_normal": len(conj),
            "mas_lluvioso": {"anio": mx[0], "mm": r1(mx[1]), "dudoso": any(x > mx[1] for x in parcial_inc.values())},
            "supera": sum(1 for a in total if total[a] < mm_act), "de": len(total), "desde_anio": min(total),
            "incompletos": len(parcial_inc), "incompletos_superan": sum(1 for x in parcial_inc.values() if x >= mm_act)}


def episodios(s, desde_i=0, hasta_i=None):
    """Lista de episodios (i_ini, i_fin, total, max, i_max): dias de >= 1 mm separados por
    como mucho un dia sin ese milimetro. Un dato que falta corta el episodio."""
    out = []
    hasta_i = len(s.v) - 1 if hasta_i is None else hasta_i
    i = desde_i
    while i <= hasta_i:
        x = s.v[i]
        if x is None or x < LLUVIOSO:
            i += 1
            continue
        ini = fin = i
        j = i + 1
        while j <= hasta_i:
            y = s.v[j]
            if y is None:
                break
            if y >= LLUVIOSO:
                fin = j
                j += 1
                continue
            # un dia flojo en medio se perdona si el siguiente vuelve a llover
            if j + 1 <= hasta_i and s.v[j + 1] is not None and s.v[j + 1] >= LLUVIOSO:
                j += 1
                continue
            break
        tramo = s.v[ini:fin + 1]
        tot = sum(z for z in tramo if z is not None)
        mx = max(tramo)
        out.append((ini, fin, tot, mx, ini + tramo.index(mx)))
        i = fin + 1
    return out


def bloque_episodio(s, info, hoy):
    """El ultimo episodio de los ultimos 30 dias y cuando cayo por ultima vez algo asi."""
    n = len(s.v)
    desde = max(0, n - 31)
    eps = episodios(s, max(0, desde - 10))
    eps = [e for e in eps if e[1] >= desde]
    if not eps:
        return None
    # El protagonista: el episodio mas grande de las dos ultimas semanas; si no hubo
    # ninguno, el mas reciente del mes. Un chispeo de hoy no tapa el temporal de anteayer.
    recientes = [e for e in eps if e[1] >= n - 15]
    principal = max(recientes, key=lambda e: e[2]) if recientes else eps[-1]
    if eps[-1][1] >= n - 3 and eps[-1][2] >= 5.0:
        principal = eps[-1]          # lo que esta cayendo (o acaba de caer) va primero
    ultimo = eps[-1]
    ini, fin, tot, mx, imx = principal
    d_ini = s.ini + timedelta(days=ini)
    d_fin = s.ini + timedelta(days=fin)
    d_mx = s.ini + timedelta(days=imx)
    par = info.get("parcial")
    en_curso = (hoy - d_fin).days <= 1        # contra hoy, no contra el final de la serie
    out = {"ini": d_ini.isoformat(), "fin": d_fin.isoformat(), "dias": fin - ini + 1,
           "mm": r1(tot), "max": r1(mx), "max_fecha": d_mx.isoformat(), "en_curso": en_curso,
           "provisional": any(s.f[k] != "v" for k in range(ini, fin + 1)),
           "incluye_hoy": bool(par and par["fecha"] == d_fin.isoformat())}
    if ultimo is not principal:
        out["despues"] = {"ini": (s.ini + timedelta(days=ultimo[0])).isoformat(),
                          "fin": (s.ini + timedelta(days=ultimo[1])).isoformat(), "mm": r1(ultimo[2])}
    # Historia: solo con anos completos y seguidos hasta hoy.
    ok = anios_completos_naturales(s, hoy)
    y0 = tramo_continuo(ok, hoy)
    if y0 is None:
        return out
    i0 = max(0, (date(y0, 1, 1) - s.ini).days)
    previos = [e for e in episodios(s, i0, ini - 2) if e[1] < ini - 1]
    mayor = [e for e in previos if e[2] >= tot]
    if mayor:
        e = mayor[-1]
        out["desde"] = {"fecha": (s.ini + timedelta(days=e[0])).isoformat(), "mm": r1(e[2]),
                        "dias": e[1] - e[0] + 1}
    elif hoy.year - y0 >= 10:
        out["mayor_desde"] = y0
    # El dia mas fuerte del episodio contra cada dia anterior.
    dias_mas = [k for k in range(i0, ini) if s.v[k] is not None and s.v[k] >= mx]
    if dias_mas:
        k = dias_mas[-1]
        out["max_desde"] = {"fecha": (s.ini + timedelta(days=k)).isoformat(), "mm": r1(s.v[k])}
    elif hoy.year - y0 >= 10:
        out["max_mayor_desde"] = y0
    out["historia_desde"] = y0
    return out


def bloque_records(s, hoy, relleno):
    ok = anios_completos_naturales(s, hoy)
    completos = sorted(y for y in ok if y < hoy.year)
    if len(completos) < 20:
        return None
    primero = s.ini.year
    # tres mayores aguaceros (dias distintos), de lo validado y de lo de estos dias
    dias = [(x, i) for i, x in enumerate(s.v) if x is not None]
    dias.sort(key=lambda t: -t[0])
    top = []
    for x, i in dias[:3]:
        d = s.ini + timedelta(days=i)
        top.append({"mm": r1(x), "fecha": d.isoformat(), "provisional": s.f[i] != "v"})
    # percentil 95 de los dias de lluvia
    lluviosos = [x for x in s.v if x is not None and x >= LLUVIOSO]
    p95 = pctl(lluviosos, 0.95)
    # anos hidrologicos completos
    tot_h, inc_h = {}, {}
    for a in range(primero, hoy.year):
        d0 = date(a, 10, 1)
        if d0 < s.ini or d0 + timedelta(days=364) > s.fin():
            continue
        if not completo(s, d0, 365, 5):
            vv = [s.get(d0 + timedelta(days=k)) for k in range(365)]
            inc_h[a] = sum(x for x in vv if x is not None)
            continue
        tot_h[a] = acumulado(s, d0, 365, relleno)[-1]
    # mes mas lluvioso
    meses = {}
    for i, x in enumerate(s.v):
        d = s.ini + timedelta(days=i)
        k = (d.year, d.month)
        m = meses.setdefault(k, [0.0, 0])
        if x is not None:
            m[0] += x
            m[1] += 1
    mes_max, inc_mes = None, []
    for (y, mo), (t, c) in meses.items():
        dm = ((date(y, mo, 28) + timedelta(days=4)).replace(day=1) - date(y, mo, 1)).days
        if c < dm - 1:
            inc_mes.append(t)
            continue
        if mes_max is None or t > mes_max[2]:
            mes_max = (y, mo, t)
    if mes_max and any(t > mes_max[2] for t in inc_mes):
        mes_max = None       # un mes con huecos ya suma mas: no se puede dar el record
    # racha seca mas larga (dias seguidos con dato y por debajo de 1 mm)
    mejor, cur, cur_ini, mejor_ini = 0, 0, None, None
    for i, x in enumerate(s.v):
        if x is not None and x < LLUVIOSO:
            if cur == 0:
                cur_ini = i
            cur += 1
            if cur > mejor:
                mejor, mejor_ini = cur, cur_ini
        else:
            cur = 0
    racha_actual = cur
    if s.f[-1] is not None and s.f[-1] != "v" and s.v[-1] is not None and s.v[-1] < LLUVIOSO and cur:
        racha_actual = cur - 1          # el dia de hoy va a medias: no cuenta todavia
    # dias de lluvia en un ano corriente (anos naturales completos del periodo normal o todos)
    por_anio = {}
    for i, x in enumerate(s.v):
        y = (s.ini + timedelta(days=i)).year
        if y in ok and y < hoy.year and x is not None and x >= LLUVIOSO:
            por_anio[y] = por_anio.get(y, 0) + 1
    ns = [por_anio.get(y, 0) for y in completos if NORMAL[0] <= y <= NORMAL[1]]
    dias_periodo = "media 1991-2020"
    if len(ns) < ANIOS_MIN:
        ns = [por_anio.get(y, 0) for y in completos]
        dias_periodo = "media de %d años" % len(ns)
    out = {"desde": primero, "anios": len(completos), "top": top,
           "p95": r1(p95) if p95 is not None else None,
           "dias_lluvia": int(round(sum(ns) / len(ns))) if ns else None, "dias_periodo": dias_periodo,
           "racha_max": {"dias": mejor, "ini": (s.ini + timedelta(days=mejor_ini)).isoformat()} if mejor_ini is not None else None,
           "racha_actual": racha_actual}
    if tot_h:
        a_ll = max(tot_h.items(), key=lambda t: t[1])
        a_se = min(tot_h.items(), key=lambda t: t[1])
        out["hidro_lluvioso"] = {"anio": etiqueta_hidro(a_ll[0]), "mm": r1(a_ll[1]),
                                 "dudoso": any(x > a_ll[1] for x in inc_h.values())}
        out["hidro_seco"] = {"anio": etiqueta_hidro(a_se[0]), "mm": r1(a_se[1])}
        out["hidro_n"] = len(tot_h)
    if mes_max:
        out["mes_max"] = {"mes": "%s de %d" % (MESES[mes_max[1] - 1], mes_max[0]), "mm": r1(mes_max[2])}
    return out


def bloque_calendario(s):
    fin = s.fin()
    ini = fin - timedelta(days=364)
    vals = [r1(s.get(ini + timedelta(days=k))) for k in range(365)]
    return {"ini": ini.isoformat(), "v": vals}


# ------------------------------------------------------------ intensidad

def intensidad(clave, estaciones_obs):
    """Lluvia de la hora mas fuerte de cada dia (local) y estacion. AEMET da las ultimas 24 h,
    asi que con una pasada cada hora no se pierde ninguna."""
    estado = leer_json(INTENS, {}) or {}
    dias = estado.setdefault("dias", {})
    if clave:
        try:
            meta = json.loads(urllib.request.urlopen(urllib.request.Request(
                BASE_AEMET + "/observacion/convencional/todas/",
                headers={"api_key": clave, "Accept": "application/json"}), timeout=90).read().decode("utf-8"))
            filas = json.loads(urllib.request.urlopen(meta["datos"], timeout=120).read().decode("ISO-8859-15"))
            n = 0
            for r in filas:
                e = r.get("idema")
                p = r.get("prec")
                if e not in estaciones_obs or p is None:
                    continue
                try:
                    p = float(p)
                    t = datetime.strptime(str(r["fint"])[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
                except (ValueError, KeyError, TypeError):
                    continue
                if not (0 <= p < 400):
                    continue
                # la lluvia de la hora que termina en fint
                loc = hora_local(t - timedelta(minutes=1), e)
                k = loc.date().isoformat()
                cur = dias.setdefault(k, {}).get(e)
                if cur is None or p > cur[0]:
                    dias[k][e] = [round(p, 1), loc.hour]
                n += 1
            log("Intensidad: %d filas horarias leidas" % n)
        except Exception as ex:  # noqa: BLE001
            log("Intensidad: AEMET no responde (%s). Sigo con lo guardado." % ex)
    for k in sorted(dias)[:-8]:
        del dias[k]
    INTENS.parent.mkdir(parents=True, exist_ok=True)
    estado["generado"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(INTENS, "w", encoding="utf-8") as f:
        json.dump(estado, f, separators=(",", ":"))
    return dias


# ------------------------------------------------------------------ main

def main():
    clave = os.environ.get("AEMET_API_KEY", "").strip()
    mapa = leer_json(MAPA)
    lluvia = leer_json(LLUVIA)
    otonio = leer_json(OTONIO, {}) or {}
    if not mapa or not lluvia:
        sys.exit("Faltan municipios_mapa.json o lluvias_municipios.json")
    c = {k: i for i, k in enumerate(mapa["campos"])}
    provs = mapa.get("provincias", [])
    fichas = {}
    for r in mapa["municipios"]:
        fichas[r[c["ine"]]] = {"n": r[c["nombre"]], "ruta": r[c["ruta"]], "lat": r[c["lat"]], "lon": r[c["lon"]],
                               "prov": provs[r[c["prov"]]] if r[c["prov"]] is not None and r[c["prov"]] < len(provs) else None}
    ids = lluvia.get("ids", {})
    est_obs, est_cli = {}, {}
    for ine in fichas:
        m = lluvia.get("municipios", {}).get(ine) or {}
        e = ids.get(m.get("est"))
        if e:
            est_obs[ine] = e
        o = (otonio.get("municipios") or {}).get(ine) or {}
        if o.get("est"):
            est_cli[ine] = o["est"]
        elif e:
            est_cli[ine] = e
    estaciones = sorted(set(est_obs.values()) | set(est_cli.values()))
    log("Fichas: %d · estaciones: %d (obs %d, clima %d)" % (len(fichas), len(estaciones),
                                                            len(set(est_obs.values())), len(set(est_cli.values()))))
    estado_dl = leer_json(DIARIA / "estado.json", {}) or {}
    inv = estado_dl.get("inventario", {})
    crudo, anios = cargar_crudo(estaciones)
    pluvio = leer_json(PLUVIO, {}) or {}
    hist = leer_json(HIST, {}) or {}
    hoy = datetime.now(timezone.utc).date()

    series, infos = {}, {}
    for e in estaciones:
        s, info = construir_serie(e, crudo.get(e, {}), cargar_larga(e), pluvio, hist, hoy)
        if s is not None:
            series[e] = s
            infos[e] = info
    log("Series montadas: %d" % len(series))
    dias_int = intensidad(clave, set(est_obs.values()))
    hoy_loc = datetime.now(ZoneInfo("Europe/Madrid")).date() if ZoneInfo else hoy
    k_hoy, k_ayer = hoy_loc.isoformat(), (hoy_loc - timedelta(days=1)).isoformat()

    cache = {}

    def calc(e):
        if e in cache:
            return cache[e]
        s = series.get(e)
        if s is None:
            cache[e] = None
            return None
        rel = media_por_dia_hidro(s)
        out = {}
        fresca = (hoy - s.fin()).days <= FRESCURA
        tareas = [("records", lambda: bloque_records(s, hoy, rel))]
        if fresca:
            tareas = [("anio", lambda: bloque_anio(s, infos[e], rel)),
                      ("mes", lambda: bloque_mes(s, infos[e], rel))] + tareas
        for nombre, fn in tareas:
            try:
                b = fn()
                if b:
                    out[nombre] = b
            except Exception as ex:  # noqa: BLE001
                log("  %s %s: %s" % (e, nombre, ex))
        cache[e] = out
        return out

    cache_obs = {}

    def calc_obs(e):
        if e in cache_obs:
            return cache_obs[e]
        s = series.get(e)
        out = {}
        if s is not None and (hoy - s.fin()).days <= FRESCURA:
            try:
                b = bloque_episodio(s, infos[e], hoy)
                if b:
                    out["episodio"] = b
            except Exception as ex:  # noqa: BLE001
                log("  %s episodio: %s" % (e, ex))
            out["calendario"] = bloque_calendario(s)
            out["hasta"] = infos[e].get("hasta")
            if infos[e].get("parcial"):
                out["parcial"] = infos[e]["parcial"]
        cache_obs[e] = out
        return out

    por_prov = {}
    n_anio = n_ep = n_rec = 0
    for ine, f in sorted(fichas.items()):
        fila = {"n": f["n"], "ruta": f["ruta"]}
        ec = est_cli.get(ine)
        eo = est_obs.get(ine)
        if ec:
            cl = calc(ec) or {}
            fila.update(cl)
            meta_e = inv.get(ec) or {}
            fila["est"] = {"id": ec, "n": meta_e.get("nom") or ec}
            if meta_e.get("lat") is not None and f["lat"] is not None:
                fila["est"]["km"] = r1(km_entre(f["lat"], f["lon"], meta_e["lat"], meta_e["lon"]))
            if ec in infos:
                fila["est"]["hasta"] = infos[ec].get("hasta")
                fila["est"]["validado"] = infos[ec].get("validado_hasta")
        if eo:
            ob = calc_obs(eo)
            fila.update(ob)
            meta_o = inv.get(eo) or {}
            fila["obs"] = {"id": eo, "n": meta_o.get("nom") or eo}
            it = {}
            for k, etq in ((k_hoy, "hoy"), (k_ayer, "ayer")):
                x = (dias_int.get(k) or {}).get(eo)
                if x:
                    it[etq] = {"mm": x[0], "h": x[1]}
            if it:
                fila["intensidad"] = it
        # vecinos con ficha
        vec = []
        if f["lat"] is not None:
            for j, g in fichas.items():
                if j == ine or g["lat"] is None:
                    continue
                if abs(g["lat"] - f["lat"]) > 0.4 or abs(g["lon"] - f["lon"]) > 0.5:
                    continue
                dkm = km_entre(f["lat"], f["lon"], g["lat"], g["lon"])
                if dkm <= VECINOS_KM:
                    vec.append((dkm, j))
        fila["vecinos"] = [[j, r1(dkm)] for dkm, j in sorted(vec)[:VECINOS_N]]
        n_anio += "anio" in fila
        n_ep += "episodio" in fila
        n_rec += "records" in fila
        por_prov.setdefault(ine[:2], {})[ine] = fila

    if n_anio + n_ep < MIN_MUNICIPIOS:
        sys.exit("Solo %d fichas con ano y %d con episodio: algo va mal. No publico." % (n_anio, n_ep))
    SALIDA.mkdir(parents=True, exist_ok=True)
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    resumen = {"version": VERSION, "generado": gen, "descarga": estado_dl.get("avance"),
               "descarga_completa": bool(estado_dl.get("completo")),
               "fuente": "AEMET OpenData: valores climatológicos diarios y observación horaria",
               "fichas": len(fichas), "con_anio": n_anio, "con_episodio": n_ep, "con_records": n_rec,
               "provincias": {}}
    for cod, filas in sorted(por_prov.items()):
        out = {"version": VERSION, "generado": gen, "provincia": cod, "municipios": filas}
        tmp = SALIDA / (cod + ".json.tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, SALIDA / (cod + ".json"))
        pcts = [x["anio"]["pct"] for x in filas.values() if x.get("anio") and x["anio"].get("pct") is not None]
        una = next(iter(filas.values()))
        resumen["provincias"][cod] = {"slug": una["ruta"].split("/")[0],
                                      "nombre": fichas[next(iter(filas))]["prov"],
                                      "fichas": len(filas), "con_anio": len(pcts),
                                      "pct_mediana": int(round(pctl(pcts, 0.5))) if pcts else None,
                                      "por_encima": sum(1 for p in pcts if p >= 100)}
    with open(SALIDA / "resumen.json", "w", encoding="utf-8") as fh:
        json.dump(resumen, fh, ensure_ascii=False, separators=(",", ":"))
    log("✓ %d provincias · año %d · episodio %d · records %d" % (len(por_prov), n_anio, n_ep, n_rec))
    for ine in ("28079", "46250", "03063", "30030", "08019", "41091", "03102"):
        p = por_prov.get(ine[:2], {}).get(ine)
        if not p:
            continue
        a, ep, rc = p.get("anio"), p.get("episodio"), p.get("records")
        log("  %s %-10s año %s · ep %s · rec %s" % (
            ine, p["n"][:10],
            a and "%s mm / %s (%s %%, %s de %s)" % (a["mm"], a["normal"], a["pct"], a["puesto"], a["de"]),
            ep and "%s→%s %s mm desde %s" % (ep["ini"], ep["fin"], ep["mm"], ep.get("desde") or ep.get("mayor_desde")),
            rc and "%s · top %s" % (rc["desde"], rc["top"][0])))


if __name__ == "__main__":
    main()
