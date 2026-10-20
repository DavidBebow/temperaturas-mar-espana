#!/usr/bin/env python3
"""Lo que dicen las series diarias largas de AEMET · calentamientoglobal.es

Lee archivo/aemet_diario/<indicativo>.csv.gz (valores climatológicos diarios de AEMET, bajados por
series_diarias_aemet.py) y escribe en docs/prensa/analisis/:

  verano.json, verano_anual.csv
      Cuánto dura el verano en cada estación y cómo ha cambiado.
      · «Temperatura de verano» de la estación: la que su curva media de 1961-1990 (temperatura media diaria, suavizada
        31 días) supera exactamente 92 días al año, lo que dura el verano meteorológico (junio, julio y agosto). Si la
        estación no tiene 20 años de 1961-1990, se usa 1981-2010 y así se dice.
      · Cada año, el verano empieza el primer día (desde el 1 de marzo) en que la media de 7 días de la temperatura media
        alcanza la temperatura de verano y acaba el último día (hasta el 15 de diciembre) en que la alcanza.
      · Años válidos: del 1 de abril al 30 de noviembre, al menos el 95 % de los días con dato y ningún hueco de más de
        7 días seguidos. 2026, igual, hasta el último día validado.
      · Control de saltos de medida (traslados, cambios de sensor): el cambio de la estación se compara con el del
        reanálisis ERA5 en la capital de su provincia (archivo/era5). Si la estación gana más de 15 días por encima del
        reanálisis, o cambia en sentido contrario, se descarta. El reanálisis no se publica nunca.

  danas.json, danas.csv
      Cuánta lluvia cae con una DANA y cómo ha cambiado, 1961-1990 frente a 1996-2025.
      · Días con DANA: los del catálogo del observatorio (docs/dana/catalogo.json, detector propio en 500 hPa con el
        reanálisis NCEP/NCAR, centro de la baja entre 32,5-45° N y 15° O-7,5° E) y el día siguiente a cada uno. Es un
        análisis, no una medida, y así se dice; la lluvia sí es la medida en la estación.
      · Años válidos: al menos 330 días con dato de lluvia. Cada periodo, al menos 20 años válidos.
      · Prueba de permutación (5.000 barajadas de los años) para saber si el cambio de la parte de la lluvia del año que
        llega con una DANA es más que azar.

Solo biblioteca estándar. Uso: python scripts/analisis_series.py
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import math
import random
import re
import statistics as st
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIARIO = RAIZ / "archivo" / "aemet_diario"
ERA5 = RAIZ / "archivo" / "era5"
SALIDA = RAIZ / "docs" / "prensa" / "analisis"
VERSION = "1.0.0"

BASES = ((1961, 1990), (1981, 2010))
RECIENTE = (2011, 2025)
LIMITE_CONTROL = 10   # días que una estación puede ganar por encima del reanálisis antes de descartarla
P_DANA = ((1961, 1990), (1996, 2025))
FUENTE = "AEMET OpenData (valores climatológicos diarios de la estación); cálculo de calentamientoglobal.es"
FUENTE_DANA = ("Lluvia: AEMET OpenData (valores climatológicos diarios). Días con DANA: catálogo de calentamientoglobal.es "
               "(detector propio en 500 hPa con el reanálisis NCEP/NCAR)")


# ============================================================================ lectura
def leer_json(p, defecto=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return defecto


def num(x):
    try:
        return float(x) if x not in ("", None) else None
    except ValueError:
        return None


def serie_diaria(ide):
    """{fecha: (tmax, tmin, tmed, prec)} con solo lo que AEMET midió."""
    out = {}
    with gzip.open(DIARIO / f"{ide}.csv.gz", "rt", encoding="utf-8") as g:
        for r in csv.DictReader(g):
            tx, tn, tm, p = num(r["tmax"]), num(r["tmin"]), num(r["tmed"]), num(r["prec"])
            if tm is None and tx is not None and tn is not None:
                tm = (tx + tn) / 2  # es la definición de AEMET para la media diaria
            out[date.fromisoformat(r["fecha"])] = (tx, tn, tm, p)
    return out


def serie_era5(cod):
    f = ERA5 / cod / "hasta_2025_era5.csv.gz"
    if not f.exists():
        f = ERA5 / cod / "hasta_2025.csv.gz"
    if not f.exists():
        return {}
    out = {}
    with gzip.open(f, "rt", encoding="utf-8") as g:
        for r in csv.DictReader(g):
            tx, tn = num(r.get("tmax")), num(r.get("tmin"))
            if tx is not None and tn is not None:
                out[date.fromisoformat(r["fecha"])] = (tx, tn, (tx + tn) / 2, num(r.get("lluvia")))
    return out


def metadatos():
    base = (leer_json(RAIZ / "docs" / "records" / "baseline.json", {}) or {}).get("estaciones") or {}
    rec = leer_json(RAIZ / "docs" / "records" / "hoy.json", {}) or {}
    bonito = {e["id"]: e.get("n") for e in rec.get("estaciones") or [] if e.get("id") and e.get("n")}
    ciudad = {}
    src = (RAIZ / "scripts" / "obtener_temperaturas_nocturnas.py").read_text(encoding="utf-8")
    for m in re.finditer(r'"nombre":\s*"([^"]+)".*?"idema":\s*"([^"]+)"', src):
        ciudad[m.group(2)] = m.group(1)
    return base, bonito, ciudad


def nombre_bonito(ide, crudo, bonito):
    n = bonito.get(ide) or crudo or ide
    if n.isupper():
        n = n.title()
    n = re.sub(r"/\s+", "/", n).strip()
    n = re.sub(r"(?<=\S) (De|Del|La|El|Los|Las)\b", lambda m: " " + m.group(1).lower(), n)
    n = re.sub(r",(?=\S)", ", ", n)
    # «Sevilla Aeropuerto» → «Sevilla (aeropuerto)»; «Madrid, Retiro» → «Madrid (Retiro)»
    n = re.sub(r"^(.+?),?\s+(Aeropuerto|Base Aérea)$", lambda m: f"{m.group(1)} ({m.group(2).lower()})", n)
    n = re.sub(r"^(Madrid), (Retiro)$", r"\1 (\2)", n)
    return n


# ============================================================================ verano
def _suave(s, d0, d1, k=7, hasta=None):
    """Media móvil centrada de k días de la temperatura media; solo ventanas completas (las k fechas dentro de los datos,
    sin pasar de «hasta») y con al menos k-2 días con dato. Al final de la serie no se calculan medias cojas."""
    out = {}
    h = k // 2
    tope = (hasta or d1) - timedelta(h)
    d = d0
    while d <= min(d1, tope):
        v = [s[x][2] for x in (d + timedelta(i) for i in range(-h, h + 1)) if x in s and s[x][2] is not None]
        if len(v) >= k - 2:
            out[d] = sum(v) / len(v)
        d += timedelta(1)
    return out


def _anio_valido(s, a, hasta=None):
    d0, d1 = date(a, 4, 1), min(date(a, 11, 30), hasta or date(a, 11, 30))
    if d1 <= d0:
        return False
    n = (d1 - d0).days + 1
    con, hueco, peor = 0, 0, 0
    for i in range(n):
        x = s.get(d0 + timedelta(i))
        if x and x[2] is not None:
            con += 1
            hueco = 0
        else:
            hueco += 1
            peor = max(peor, hueco)
    return con >= 0.95 * n and peor <= 7


def _umbral(s, b0, b1):
    """Temperatura que la curva media de b0-b1 (suavizada 31 días) supera exactamente 92 días."""
    acc = {}
    for d, x in s.items():
        if b0 <= d.year <= b1 and x[2] is not None and not (d.month == 2 and d.day == 29):
            acc.setdefault((d.month, d.day), []).append(x[2])
    dias = [(m, dd) for m in range(1, 13) for dd in range(1, 32) if (m, dd) in acc]
    if len(dias) < 365 or min(len(v) for v in acc.values()) < 15:
        return None
    cl = [st.mean(acc[k]) for k in dias]
    n = len(cl)
    sm = [st.mean(cl[(i + j) % n] for j in range(-15, 16)) for i in range(n)]
    orden = sorted(sm, reverse=True)
    return (orden[91] + orden[92]) / 2


def _verano(s, a, T, hasta=None):
    """Días de verano del año a (media de 7 días ≥ T, del 1 de marzo al 15 de diciembre) e inicio y final: el primer y el
    último tramo de al menos 5 días seguidos a ese nivel (un día suelto de calor en abril no adelanta el verano)."""
    d1 = min(date(a, 12, 15), hasta) if hasta else date(a, 12, 15)
    sm = _suave(s, date(a, 3, 1), d1, hasta=hasta)
    if not sm:
        return None
    sobre = sorted(d for d, v in sm.items() if v >= T)
    tramos, ini = [], None
    for i, d in enumerate(sobre):
        if ini is None:
            ini = d
        if i == len(sobre) - 1 or (sobre[i + 1] - d).days > 1:
            tramos.append((ini, d))
            ini = None
    largos = [t for t in tramos if (t[1] - t[0]).days + 1 >= 5]
    if not largos:
        return None
    ini, fin = largos[0][0], largos[-1][1]
    ultimo = max(sm)
    return {"ini": ini, "fin": fin, "dur": (fin - ini).days + 1, "dias": len(sobre), "ultimo": ultimo,
            "sigue": fin == ultimo, "bajo_desde_fin": (ultimo - fin).days, "sobre": sobre}


def _doy_medio(fechas):
    """Fecha media (día del año) de una lista de fechas, como «5 de junio»."""
    m = round(st.mean(f.timetuple().tm_yday for f in fechas))
    return (date(2001, 1, 1) + timedelta(m - 1)).strftime("%m-%d")


def _pendiente(xs, ys):
    mx, my = st.mean(xs), st.mean(ys)
    den = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den if den else 0.0


def analizar_verano(s, era5=None):
    base = None
    for b0, b1 in BASES:
        validos = [a for a in range(b0, b1 + 1) if _anio_valido(s, a)]
        if len(validos) >= 20:
            T = _umbral(s, b0, b1)
            if T is not None:
                base = (b0, b1, T)
                break
    if not base:
        return None
    b0, b1, T = base
    ult = max(d for d, x in s.items() if x[2] is not None)
    anios = {}
    for a in range(min(s).year, ult.year + 1):
        es_2026 = a == ult.year and ult < date(a, 12, 15)
        if es_2026:
            if not _anio_valido(s, a, hasta=ult):
                continue
            v = _verano(s, a, T, hasta=ult)
        else:
            if not _anio_valido(s, a):
                continue
            v = _verano(s, a, T)
        if v:
            anios[a] = v
    pb = [a for a in range(b0, b1 + 1) if a in anios]
    pr = [a for a in range(RECIENTE[0], RECIENTE[1] + 1) if a in anios]
    if len(pb) < 20 or len(pr) < 12:
        return None
    cerrados = sorted(a for a in anios if a <= RECIENTE[1])
    res = {
        "base": f"{b0}-{b1}", "umbral": round(T, 1), "n_base": len(pb), "n_reciente": len(pr),
        "base_dias": st.mean(anios[a]["dias"] for a in pb), "rec_dias": st.mean(anios[a]["dias"] for a in pr),
        "base_dur": st.mean(anios[a]["dur"] for a in pb), "rec_dur": st.mean(anios[a]["dur"] for a in pr),
        "base_ini": _doy_medio([anios[a]["ini"] for a in pb]), "base_fin": _doy_medio([anios[a]["fin"] for a in pb]),
        "rec_ini": _doy_medio([anios[a]["ini"] for a in pr]), "rec_fin": _doy_medio([anios[a]["fin"] for a in pr]),
        "desde": cerrados[0], "n_anios": len(cerrados), "huecos": (RECIENTE[1] - cerrados[0] + 1) - len(cerrados),
        "tendencia_decada": _pendiente(cerrados, [anios[a]["dias"] for a in cerrados]) * 10 if len(cerrados) >= 30 else None,
        "anios": anios, "ultimo_dato": ult,
    }
    res["dif"] = res["rec_dias"] - res["base_dias"]
    # inicio y fin, en días de adelanto y de retraso (sin redondear)
    doy = lambda per, k: st.mean(anios[a][k].timetuple().tm_yday for a in per)  # noqa: E731
    res["adelanto"] = doy(pb, "ini") - doy(pr, "ini")
    res["retraso"] = doy(pr, "fin") - doy(pb, "fin")
    # el año en curso: solo lo que ya es seguro. «Sigue» si el último tramo llega al último día calculable; «terminado» tras
    # 7 días seguidos por debajo; entre medias no se dice ni una cosa ni otra. Sus días de verano son un mínimo.
    a = ult.year
    if a in anios and ult < date(a, 12, 15):
        v = anios[a]
        prev = [anios[x]["dias"] for x in cerrados]
        res["actual"] = {"anio": a, "ini": v["ini"], "fin": v["fin"], "dias": v["dias"], "dur": v["dur"],
                         "sigue": v["sigue"], "terminado": v["bajo_desde_fin"] >= 7, "calculable_hasta": v["ultimo"], "datos_hasta": ult,
                         "mas_dias": v["dias"] > max(prev), "max_prev": max(prev),
                         "max_prev_anios": sorted(x for x in cerrados if anios[x]["dias"] == max(prev)),
                         "supera_media_reciente": v["dias"] > res["rec_dias"],
                         # día (de la media de 7 días) en que el año pasó el máximo anterior: sirve para saber si el récord es reciente
                         "fecha_supera": v["sobre"][max(prev)] if v["dias"] > max(prev) else None}
    # control de saltos con el reanálisis (no se publica)
    res["control"] = None
    if era5:
        Te = _umbral(era5, b0, b1)
        if Te is not None:
            ae = {x: _verano(era5, x, Te) for x in set(pb) | set(pr) if _anio_valido(era5, x)}
            eb = [ae[x]["dias"] for x in pb if ae.get(x)]
            er = [ae[x]["dias"] for x in pr if ae.get(x)]
            if len(eb) >= 15 and len(er) >= 10:
                de = st.mean(er) - st.mean(eb)
                res["control"] = round(de, 1)
    res["homogenea"] = res["control"] is not None and (res["dif"] - res["control"] <= LIMITE_CONTROL) and (res["dif"] * res["control"] >= 0 or abs(res["dif"]) < 5)
    return res


# ============================================================================ danas
def dias_catalogo():
    """Media de días con DANA (solo los del catálogo) entre diciembre y mayo y en otoño, por periodo."""
    cat = leer_json(RAIZ / "docs" / "dana" / "catalogo.json", {}) or {}
    dias = {date.fromisoformat(x) for lista in (cat.get("anios") or {}).values() for e in lista for x in e.get("dias_esp") or []}
    out = {}
    for p0, p1 in P_DANA:
        n = p1 - p0 + 1
        out[f"{p0}-{p1}"] = {"dic_may": sum(1 for d in dias if (p0 <= d.year <= p1 and d.month <= 5) or (p0 - 1 <= d.year <= p1 - 1 and d.month == 12)) / n,
                             "otono": sum(1 for d in dias if p0 <= d.year <= p1 and d.month in (9, 10, 11)) / n}
    return out


def dias_dana():
    cat = leer_json(RAIZ / "docs" / "dana" / "catalogo.json", {}) or {}
    d = set()
    for lista in (cat.get("anios") or {}).values():
        for e in lista:
            for x in e.get("dias_esp") or []:
                d.add(date.fromisoformat(x))
    return d | {x + timedelta(1) for x in d}, cat.get("ncep_ultimo")


def analizar_danas(s, W):
    por_anio = {}
    for d, x in s.items():
        if x[3] is not None:
            por_anio.setdefault(d.year, []).append((d, x[3]))
    validos = {a: v for a, v in por_anio.items() if len(v) >= 330 and a <= P_DANA[1][1]}
    per = []
    for p0, p1 in P_DANA:
        aa = [a for a in range(p0, p1 + 1) if a in validos]
        if len(aa) < 20:
            return None
        per.append(aa)

    lluvia = {d: x[3] for d, x in s.items() if x[3] is not None}

    def dic_may(a):
        """Diciembre del año anterior y enero-mayo del año a: el invierno y la primavera de un mismo «año de lluvias»."""
        d, out = date(a - 1, 12, 1), 0.0
        while d <= date(a, 5, 31):
            if d in W and d in lluvia:
                out += lluvia[d]
            d += timedelta(1)
        return out

    def dias_w(a, meses, anterior_dic=False):
        d0 = date(a - 1, 12, 1) if anterior_dic else date(a, 1, 1)
        d1 = date(a, 5, 31) if anterior_dic else date(a, 12, 31)
        n, d = 0, d0
        while d <= d1:
            if d in W and (d.month in meses):
                n += 1
            d += timedelta(1)
        return n

    def metr(aa):
        tot = [sum(m for _, m in validos[a]) for a in aa]
        dan = [sum(m for d, m in validos[a] if d in W) for a in aa]
        oto = [sum(m for d, m in validos[a] if d in W and d.month in (9, 10, 11)) for a in aa]
        inv = [dic_may(a) for a in aa]
        n_inv = sum(dias_w(a, (12, 1, 2, 3, 4, 5), anterior_dic=True) for a in aa)
        n_oto = sum(dias_w(a, (9, 10, 11)) for a in aa)
        hum = [m for a in aa for d, m in validos[a] if d in W and m >= 1]
        n50 = sum(1 for a in aa for d, m in validos[a] if d in W and m >= 50)
        n50t = sum(1 for a in aa for d, m in validos[a] if m >= 50)
        mx = max(((m, d) for a in aa for d, m in validos[a] if d in W), default=(0.0, None))
        return {"anios": len(aa), "anual": st.mean(tot), "dana": st.mean(dan), "pct": 100 * sum(dan) / sum(tot) if sum(tot) else None,
                "otono": st.mean(oto), "dic_may": st.mean(inv), "dias_lluvia": len(hum) / len(aa), "intensidad": st.mean(hum) if hum else None,
                "dias_w_dic_may": n_inv / len(aa), "dias_w_otono": n_oto / len(aa),
                "por_dia_dic_may": sum(inv) / n_inv if n_inv else None, "por_dia_otono": sum(oto) / n_oto if n_oto else None,
                "d50_decada": n50 / len(aa) * 10, "d50_todos_decada": n50t / len(aa) * 10,
                "pct_d50": 100 * n50 / n50t if n50t else None, "max": round(mx[0], 1), "max_fecha": mx[1].isoformat() if mx[1] else None,
                "_shares": [(dn / t if t else 0.0) for dn, t in zip(dan, tot)]}
    a, b = metr(per[0]), metr(per[1])
    # permutación: ¿la parte de la lluvia del año que llega con DANA ha cambiado más que por azar?
    x, y = a.pop("_shares"), b.pop("_shares")
    obs = st.mean(y) - st.mean(x)
    todo = x + y
    rnd = random.Random(20261020)
    n_ext = 0
    for _ in range(5000):
        rnd.shuffle(todo)
        if abs(st.mean(todo[len(x):]) - st.mean(todo[:len(x)])) >= abs(obs) - 1e-12:
            n_ext += 1
    return {"p1": a, "p2": b, "p_pct": round((n_ext + 1) / 5001, 3)}


# ============================================================================ gráficos (nombres fijos: los enlaza el plugin)
TINTA, GRIS, RAYA, CALOR, MED, LLUVIA, LL_CLARO = "#16130F", "#5E574E", "#E3DED5", "#C4461A", "#E3A487", "#1F5FA8", "#8FB0DA"
FUENTE_SVG = "Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
MESES_C = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def _t(x, y, s, size=12, color=GRIS, anchor="start", weight=400):
    s = str(s).replace("&", "&amp;").replace("<", "&lt;")
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{color}" text-anchor="{anchor}" font-weight="{weight}" '
            f'font-family="{FUENTE_SVG}">{s}</text>')


def _svg(w, h, aria, cuerpo):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-label="{aria}">'
            f'<rect width="{w}" height="{h}" fill="#FFFFFF"></rect>' + "".join(cuerpo) + "</svg>")


def norm_txt(s):
    import unicodedata
    return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower())


def _doy(md):
    return (date(2001, int(md[:2]), int(md[3:5])) - date(2001, 1, 1)).days


def svg_verano(x):
    """Cada año, una raya del primer al último día de verano; en color, el año en curso."""
    serie = x["serie"]
    d0, d1 = _doy("04-15"), _doy("11-15")
    W, ml, mr, mt, fila = 640, 44, 16, 34, 4.2
    Hh = int(mt + fila * len(serie) + 34)
    X = lambda d: ml + (min(max(d, d0), d1) - d0) / (d1 - d0) * (W - ml - mr)  # noqa: E731
    s = []
    for md, et in (("05-01", "1 may"), ("06-01", "1 jun"), ("07-01", "1 jul"), ("08-01", "1 ago"), ("09-01", "1 sep"), ("10-01", "1 oct"), ("11-01", "1 nov")):
        s.append(f'<line x1="{X(_doy(md)):.1f}" x2="{X(_doy(md)):.1f}" y1="{mt - 4}" y2="{Hh - 26}" stroke="{RAYA}" stroke-width="1"></line>')
        s.append(_t(X(_doy(md)), Hh - 10, et, 11, GRIS, "middle"))
    ultimo = serie[-1][0]
    for i, (a, ini, fin, dur) in enumerate(serie):
        y = mt + i * fila
        color = CALOR if (a == ultimo and a >= 2026) else (MED if a >= 2011 else "#E9C9B8" if a >= 1991 else "#D9D3CA")
        s.append(f'<rect x="{X(_doy(ini)):.1f}" y="{y:.1f}" width="{max(1.0, X(_doy(fin)) - X(_doy(ini))):.1f}" height="{fila - 0.8:.1f}" fill="{color}"></rect>')
        if i == 0 or a // 10 != serie[i - 1][0] // 10:  # el primer año de cada década con dato
            s.append(_t(ml - 6, y + 4, str(a), 10, GRIS, "end"))
    for k in ("base_ini", "base_fin"):
        xx = X(_doy(x[k]))
        s.append(f'<line x1="{xx:.1f}" x2="{xx:.1f}" y1="{mt - 6}" y2="{mt + fila * len(serie)}" stroke="{TINTA}" stroke-width="1.2" stroke-dasharray="3 3"></line>')
    s.append(_t(X(_doy(x["base_ini"])) - 4, mt - 10, f"inicio medio {x['base']}", 10.5, TINTA, "end"))
    s.append(_t(X(_doy(x["base_fin"])) + 4, mt - 10, f"fin medio {x['base']}", 10.5, TINTA, "start"))
    if ultimo >= 2026:
        s.append(_t(X(_doy(serie[-1][2])) + 6, mt + fila * (len(serie) - 1) + 5, str(ultimo), 11, CALOR, "start", 700))
    return _svg(W, Hh, f"Duración del verano cada año en {x['nombre']}", s)


def svg_verano_espana(filas):
    """Pesas: duración media del verano en la referencia y en 2011-2025, una fila por provincia."""
    filas = sorted(filas, key=lambda x: -(dias_enteros(x["rec_dias"]) - dias_enteros(x["base_dias"])))
    for x in filas:
        x["etiqueta"] = x["nombre"] if norm_txt(x["provincia"]) in norm_txt(x["nombre"]) else f"{x['provincia']} · {x['nombre']}"
    ml = int(min(300, 30 + 6.8 * max(len(x["etiqueta"]) for x in filas)))
    W, fila, mr, mt = 720, 24, 60, 36
    Hh = mt + fila * len(filas) + 30
    lo = min(min(x["base_dias"], x["rec_dias"]) for x in filas)
    hi = max(max(x["base_dias"], x["rec_dias"]) for x in filas)
    lo, hi = (int(lo) // 10) * 10, (int(hi) // 10 + 1) * 10
    X = lambda v: ml + (v - lo) / (hi - lo) * (W - ml - mr)  # noqa: E731
    s = [f'<circle cx="{ml + 6}" cy="14" r="5" fill="#B9B1A6"></circle>', _t(ml + 16, 18, "referencia (1961-1990 o 1981-2010)", 11.5, GRIS),
         f'<circle cx="{ml + 260}" cy="14" r="5" fill="{CALOR}"></circle>', _t(ml + 270, 18, "2011-2025", 11.5, GRIS)]
    for t in range(lo, hi + 1, 10):
        s.append(f'<line x1="{X(t):.1f}" x2="{X(t):.1f}" y1="{mt - 6}" y2="{Hh - 26}" stroke="{RAYA}"></line>')
        s.append(_t(X(t), Hh - 10, f"{t} días" if t == lo else str(t), 11, GRIS, "middle"))
    for i, x in enumerate(filas):
        y = mt + i * fila + 10
        s.append(_t(ml - 10, y + 4, x["etiqueta"] + ("*" if x["base"] != "1961-1990" else ""), 12, TINTA, "end"))
        s.append(f'<line x1="{X(x["base_dias"]):.1f}" x2="{X(x["rec_dias"]):.1f}" y1="{y}" y2="{y}" stroke="{MED}" stroke-width="3"></line>')
        s.append(f'<circle cx="{X(x["base_dias"]):.1f}" cy="{y}" r="5" fill="#B9B1A6"></circle>')
        s.append(f'<circle cx="{X(x["rec_dias"]):.1f}" cy="{y}" r="5.5" fill="{CALOR}"></circle>')
        s.append(_t(X(x["rec_dias"]) + 9, y + 4, f"+{dias_enteros(x['rec_dias']) - dias_enteros(x['base_dias'])}", 11.5, TINTA, "start", 700))
    return _svg(W, Hh, "Días de verano al año, antes y ahora, provincia a provincia", s)


def svg_danas(x):
    """Lluvia con DANA al año por estación del año, 1961-1990 frente a 1996-2025."""
    a, b = x["p1"], x["p2"]
    cats = [("Dic-may", a["dic_may"], b["dic_may"]), ("Jun-ago", a["dana"] - a["otono"] - a["dic_may"], b["dana"] - b["otono"] - b["dic_may"]),
            ("Sep-nov", a["otono"], b["otono"])]
    W, Hh, ml, mr, mt, mb = 560, 260, 44, 16, 36, 34
    mx = max(max(c[1], c[2]) for c in cats) or 1
    tope = max(10, math.ceil(mx * 1.15 / 10) * 10)
    Y = lambda v: mt + (1 - v / tope) * (Hh - mt - mb)  # noqa: E731
    bw = (W - ml - mr) / len(cats)
    s = [f'<rect x="{ml}" y="8" width="12" height="12" fill="{LL_CLARO}"></rect>', _t(ml + 18, 18, "1961-1990", 12, GRIS),
         f'<rect x="{ml + 110}" y="8" width="12" height="12" fill="{LLUVIA}"></rect>', _t(ml + 128, 18, "1996-2025", 12, GRIS)]
    for t in range(0, tope + 1, max(10, tope // 4 // 10 * 10)):
        s.append(f'<line x1="{ml}" x2="{W - mr}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="{RAYA}"></line>')
        s.append(_t(ml - 6, Y(t) + 4, str(t), 11, GRIS, "end"))
    for i, (et, v1, v2) in enumerate(cats):
        x0 = ml + i * bw + 14
        w = (bw - 36) / 2
        s.append(f'<rect x="{x0:.1f}" y="{Y(v1):.1f}" width="{w:.1f}" height="{max(0.0, Y(0) - Y(v1)):.1f}" fill="{LL_CLARO}"></rect>')
        s.append(f'<rect x="{x0 + w + 6:.1f}" y="{Y(v2):.1f}" width="{w:.1f}" height="{max(0.0, Y(0) - Y(v2)):.1f}" fill="{LLUVIA}"></rect>')
        s.append(_t(x0 + w / 2, Y(v1) - 5, f"{round(v1)}", 11, GRIS, "middle"))
        s.append(_t(x0 + w + 6 + w / 2, Y(v2) - 5, f"{round(v2)}", 11, TINTA, "middle", 700))
        s.append(_t(x0 + w + 3, Hh - mb + 18, et, 12, GRIS, "middle"))
    return _svg(W, Hh, f"Lluvia con DANA al año en {x['nombre']} (mm)", s)


def escribir_graficos(ver, prov_v, dan, prov_d):
    g = SALIDA / "graficos"
    g.mkdir(parents=True, exist_ok=True)
    escritos = set()

    def poner(nombre, svg):
        escritos.add(nombre)
        f = g / nombre
        if not f.exists() or f.read_text(encoding="utf-8") != svg:
            f.write_text(svg, encoding="utf-8")
    PROVN = {}
    try:
        sys.path.insert(0, str(RAIZ / "scripts"))
        import hallazgos_prensa as H  # noqa: E402
        PROVN = {c: v[0] for c, v in H.PROVINCIAS.items()}
    except Exception:  # noqa: BLE001
        pass
    for cod, ide in prov_v.items():
        poner(f"verano-{cod}.svg", svg_verano(ver[ide]))
    for cod, ide in prov_d.items():
        poner(f"danas-{cod}.svg", svg_danas(dan[ide]))
    filas = [dict(ver[i], provincia=PROVN.get(c, c)) for c, i in prov_v.items()]
    if filas:
        poner("verano-espana.svg", svg_verano_espana(filas))
    for f in g.glob("*.svg"):
        if f.name not in escritos:
            f.unlink()


# ============================================================================ principal
def dias_enteros(x):
    from decimal import ROUND_HALF_UP, Decimal
    return int(Decimal(str(float(x))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def r1(x):
    return None if x is None else round(x, 1)


def main():
    SALIDA.mkdir(parents=True, exist_ok=True)
    estado = (leer_json(DIARIO / "estado.json", {}) or {}).get("estaciones") or {}
    base, bonito, ciudad = metadatos()
    W, ncep_ultimo = dias_dana()
    ver, dan, filas_v, filas_d = {}, {}, [], []
    for ide, e in estado.items():
        if not e.get("completa") or not (DIARIO / f"{ide}.csv.gz").exists():
            continue
        meta = base.get(ide) or {}
        cod = meta.get("cod")
        if not cod:
            continue
        s = serie_diaria(ide)
        nom = nombre_bonito(ide, meta.get("nombre") or e.get("nombre"), bonito)
        comun = {"nombre": nom, "cod": cod, "capital": ide in ciudad, "lat": meta.get("lat"), "lon": meta.get("lon"), "alt": meta.get("alt"),
                 "primer_dia": e.get("primer_dia"), "ultimo_dia": e.get("ultimo_dia")}
        try:
            v = analizar_verano(s, serie_era5(cod))
        except Exception as ex:  # noqa: BLE001
            print(f"verano {ide}: {ex}", file=sys.stderr)
            v = None
        if v:
            act = v.get("actual")
            ver[ide] = dict(comun, base=v["base"], umbral=v["umbral"], n_base=v["n_base"], n_reciente=v["n_reciente"],
                            base_dias=r1(v["base_dias"]), rec_dias=r1(v["rec_dias"]), dif=r1(v["dif"]),
                            base_dur=r1(v["base_dur"]), rec_dur=r1(v["rec_dur"]),
                            base_ini=v["base_ini"], base_fin=v["base_fin"], rec_ini=v["rec_ini"], rec_fin=v["rec_fin"],
                            adelanto=r1(v["adelanto"]), retraso=r1(v["retraso"]),
                            desde=v["desde"], n_anios=v["n_anios"], huecos=v["huecos"], tendencia_decada=r1(v["tendencia_decada"]),
                            homogenea=v["homogenea"], ultimo_dato=v["ultimo_dato"].isoformat(),
                            actual=({k: (x.isoformat() if isinstance(x, date) else x) for k, x in act.items()} if act else None),
                            serie=[[a, x["ini"].strftime("%m-%d"), x["fin"].strftime("%m-%d"), x["dur"]] for a, x in sorted(v["anios"].items())])
            for a, x in sorted(v["anios"].items()):
                    filas_v.append([ide, nom, cod, a, x["ini"].isoformat(), x["fin"].isoformat(), x["dias"], x["dur"], v["umbral"], v["base"]])
        try:
            d = analizar_danas(s, W)
        except Exception as ex:  # noqa: BLE001
            print(f"danas {ide}: {ex}", file=sys.stderr)
            d = None
        if d:
            dan[ide] = dict(comun, p1={k: (r1(x) if isinstance(x, float) else x) for k, x in d["p1"].items()},
                            p2={k: (r1(x) if isinstance(x, float) else x) for k, x in d["p2"].items()}, p_pct=d["p_pct"])
            for per, k in (("1961-1990", "p1"), ("1996-2025", "p2")):
                q = d[k]
                filas_d.append([ide, nom, cod, per, q["anios"], r1(q["anual"]), r1(q["dana"]), r1(q["pct"]), r1(q["otono"]), r1(q["dic_may"]),
                                r1(q["intensidad"]), r1(q["d50_decada"]), q["max"], q["max_fecha"]])
        print(f"{ide:6} {nom[:26]:26} verano {'ok' if v else '--'}{'' if not v else (' +' + str(r1(v['dif'])) + ' d' + ('' if v['homogenea'] else ' (descartada)'))}"
              f" · danas {'ok' if d else '--'}")

    # una estación por provincia: la capital si vale; si no, la de serie más larga; siempre la base 1961-1990 antes que 1981-2010
    def elegir(dic, valida):
        out = {}
        for ide, x in dic.items():
            if not valida(x):
                continue
            clave = (x.get("base", "1961-1990") == "1961-1990", x["capital"], -int((x.get("primer_dia") or "9999")[:4]))
            if x["cod"] not in out or clave > out[x["cod"]][0]:
                out[x["cod"]] = (clave, ide)
        return {c: v[1] for c, v in sorted(out.items())}

    prov_v = elegir(ver, lambda x: x["homogenea"])
    prov_d = elegir(dan, lambda x: True)
    ahora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    vale = [ver[i] for i in prov_v.values()]
    resumen_v = {"estaciones": len(vale), "con_base_1961": sum(1 for x in vale if x["base"] == "1961-1990"),
                 "mediana_dif": r1(st.median([x["dif"] for x in vale if x["base"] == "1961-1990"])) if any(x["base"] == "1961-1990" for x in vale) else None,
                 "descartadas": sorted(i for i, x in ver.items() if not x["homogenea"])}
    doc_v = {"version": VERSION, "generado": ahora, "fuente": FUENTE,
             "definicion": "Días de verano: los días del año en que la media de siete días de la temperatura media de la estación alcanza su «temperatura de "
                           "verano», el nivel que en 1961-1990 se superaba unos 92 días al año (lo que duran junio, julio y agosto). El verano empieza con el "
                           "primer tramo de al menos cinco días seguidos a ese nivel y acaba con el último. Si la estación no tiene 20 años válidos en "
                           "1961-1990, la referencia es 1981-2010.",
             "metodo": "Temperatura media diaria de AEMET ((máxima + mínima) / 2), media móvil centrada de 7 días con al menos 5 días con dato y sin pasar "
                       "del último dato validado. Años "
                       "válidos: del 1 de abril al 30 de noviembre, al menos el 95 % de días con dato y ningún hueco de más de 7 días. Medias de la "
                       f"referencia (al menos 20 años válidos) y de 2011-2025 (al menos 12). Solo se publican estaciones cuyo cambio no supera en más de "
                       f"{LIMITE_CONTROL} días el del reanálisis ERA5 en la capital de su provincia ni va en sentido contrario (filtro de traslados y "
                       "cambios de sensor; el reanálisis no se publica). Año en curso: «sigue» si el último tramo llega al último día calculable; "
                       "«terminado» tras 7 días seguidos por debajo; sus días de verano son un mínimo.",
             "limites": ["Es la temperatura de una estación, no de toda la provincia; una estación que se ha quedado dentro de la ciudad puede calentarse "
                         "también por la urbanización.", "El año en curso llega hasta el último dato validado por AEMET (unos 4 días de retraso)."],
             "resumen": resumen_v, "provincias": prov_v, "estaciones": ver}
    resumen_d = {"estaciones": len(prov_d), "catalogo": {k: {kk: r1(vv) for kk, vv in v.items()} for k, v in dias_catalogo().items()}}
    doc_d = {"version": VERSION, "generado": ahora, "fuente": FUENTE_DANA, "periodos": ["1961-1990", "1996-2025"],
             "definicion": "Lluvia con DANA: la que cae un día con DANA del catálogo del observatorio o el día siguiente. El catálogo marca los días con una "
                           "baja aislada en 500 hPa (criterios de Nieto et al. 2005, duración de 2 días o más) centrada entre 32,5-45° N y 15° O-7,5° E.",
             "metodo": "Lluvia diaria medida por AEMET en la estación. Años con al menos 330 días con dato; cada periodo, al menos 20 años. «pct»: parte de "
                       "la lluvia del año que llega con DANA (suma de los años del periodo). «p_pct»: prueba de permutación (5.000 barajadas) del cambio "
                       "de esa parte; por debajo de 0,1 el cambio es difícil de explicar por azar.",
             "limites": ["Los días con DANA salen de un reanálisis (NCEP/NCAR), no de una medida: el catálogo es del observatorio.",
                         f"El catálogo cambia de fuente en 2026 (análisis de ECMWF desde el {ncep_ultimo or '18 de marzo de 2026'}): 2026 no entra en las comparaciones.",
                         "Una DANA en esa caja no siempre está encima de la estación: es la lluvia que cae mientras hay una DANA en el entorno de la Península."],
             "resumen": resumen_d, "provincias": prov_d, "estaciones": dan}
    try:
        escribir_graficos(ver, prov_v, dan, prov_d)
    except Exception as ex:  # noqa: BLE001
        print(f"gráficos: {ex}", file=sys.stderr)
    doc_v["estado_descarga"] = {"completas": sum(1 for e in estado.values() if e.get("completa")), "total": len(estado)}
    for nombre, doc in (("verano.json", doc_v), ("danas.json", doc_d)):
        # si solo cambiaría la hora de generación, no se reescribe (corre cada media hora con la sala de prensa)
        viejo = leer_json(SALIDA / nombre, {}) or {}
        if {k: v for k, v in viejo.items() if k != "generado"} == json.loads(json.dumps({k: v for k, v in doc.items() if k != "generado"})):
            continue
        (SALIDA / nombre).write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    def csv_si_cambia(nombre, cab, filas):
        b = io.StringIO()
        w = csv.writer(b, lineterminator="\n")
        w.writerow(cab)
        w.writerows(filas)
        f = SALIDA / nombre
        if not f.exists() or f.read_text(encoding="utf-8") != b.getvalue():
            f.write_text(b.getvalue(), encoding="utf-8")
    csv_si_cambia("verano_anual.csv", ["indicativo", "estacion", "provincia_ine", "anio", "inicio_verano", "fin_verano", "dias_de_verano",
                                       "dias_entre_inicio_y_fin", "temperatura_verano_c", "referencia"], filas_v)
    csv_si_cambia("danas.csv", ["indicativo", "estacion", "provincia_ine", "periodo", "anios", "lluvia_anual_mm", "lluvia_con_dana_mm", "pct_lluvia_con_dana",
                                "lluvia_con_dana_otono_mm", "lluvia_con_dana_dic_may_mm", "mm_por_dia_de_lluvia_con_dana", "dias_50mm_con_dana_por_decada",
                                "max_diario_con_dana_mm", "fecha_max"], filas_d)
    print(f"verano: {len(ver)} estaciones, {len(prov_v)} provincias · danas: {len(dan)} estaciones, {len(prov_d)} provincias")
    return 0


if __name__ == "__main__":
    sys.exit(main())
