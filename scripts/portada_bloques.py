#!/usr/bin/env python3
"""
Bloques B-F de la portada diaria de la sala de prensa (26-11-2026).

Decisión de David (26-11): los cinco criterios dejan de decidir si hay portada y pasan a ser un sello. La página abre todos los
días con contenido, en seis bloques, y ninguno sale vacío:
  A dato_del_dia      (en portada_prensa.py: usa la mesa, mesa_redaccion.puntuar)
  B carreras          año en curso, estación en curso y rachas vivas, calculadas sobre archivo/aemet_diario/*.csv.gz
  C tal_dia_como_hoy  máxima más alta, mínima más baja y día más lluvioso de la fecha de hoy en cada capital con ≥ 40 años
  D espana_ayer       seis cifras (máxima y mínima de la red, mayor lluvia, embalses, Mediterráneo, avisos)
  E provincias        52 portadas, cada una con titular propio
  F lo_que_viene      previsión a 1-5 días contra la normal 1991-2020 y agenda de datos

Reglas de rigor del 25-11 (no se tocan): «el más…» solo con primer puesto y sin empate; récord solo con serie de estación de AEMET de
≥ 40 años; reanálisis dicho en el titular y sin umbrales absolutos; nada de «histórico». Sin APIs de pago, sin red: solo ficheros del
repositorio. Todo el texto, en español de España y sin adjetivos.
"""
from __future__ import annotations

import json
import math
import re
import statistics
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

import mesa_redaccion as M

RAIZ = M.RAIZ
MIN_ANIOS = 40
MESES = M.MESES

# (código, slug, nombre) de las 52 provincias, igual que el plugin (cod_por_slug)
PROVINCIAS = [
    ("01", "alava", "Álava"), ("02", "albacete", "Albacete"), ("03", "alicante", "Alicante"), ("04", "almeria", "Almería"),
    ("05", "avila", "Ávila"), ("06", "badajoz", "Badajoz"), ("07", "baleares", "Illes Balears"), ("08", "barcelona", "Barcelona"),
    ("09", "burgos", "Burgos"), ("10", "caceres", "Cáceres"), ("11", "cadiz", "Cádiz"), ("12", "castellon", "Castellón"),
    ("13", "ciudad-real", "Ciudad Real"), ("14", "cordoba", "Córdoba"), ("15", "a-coruna", "A Coruña"), ("16", "cuenca", "Cuenca"),
    ("17", "girona", "Girona"), ("18", "granada", "Granada"), ("19", "guadalajara", "Guadalajara"), ("20", "gipuzkoa", "Gipuzkoa"),
    ("21", "huelva", "Huelva"), ("22", "huesca", "Huesca"), ("23", "jaen", "Jaén"), ("24", "leon", "León"), ("25", "lleida", "Lleida"),
    ("26", "la-rioja", "La Rioja"), ("27", "lugo", "Lugo"), ("28", "madrid", "Madrid"), ("29", "malaga", "Málaga"),
    ("30", "murcia", "Murcia"), ("31", "navarra", "Navarra"), ("32", "ourense", "Ourense"), ("33", "asturias", "Asturias"),
    ("34", "palencia", "Palencia"), ("35", "las-palmas", "Las Palmas"), ("36", "pontevedra", "Pontevedra"), ("37", "salamanca", "Salamanca"),
    ("38", "santa-cruz-de-tenerife", "Santa Cruz de Tenerife"), ("39", "cantabria", "Cantabria"), ("40", "segovia", "Segovia"),
    ("41", "sevilla", "Sevilla"), ("42", "soria", "Soria"), ("43", "tarragona", "Tarragona"), ("44", "teruel", "Teruel"),
    ("45", "toledo", "Toledo"), ("46", "valencia", "Valencia"), ("47", "valladolid", "Valladolid"), ("48", "bizkaia", "Bizkaia"),
    ("49", "zamora", "Zamora"), ("50", "zaragoza", "Zaragoza"), ("51", "ceuta", "Ceuta"), ("52", "melilla", "Melilla"),
]


# ----------------------------------------------------------------------------- utilidades
def leer_json(p: Path, defecto=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return defecto


def f1(x, d=1) -> str:
    return f"{x:.{d}f}".replace(".", ",")


def fecha_es(d: date) -> str:
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def _fe(iso) -> str:
    """'2026-11-24' → '24 de noviembre de 2026'; lo que no sea una fecha ISO se devuelve tal cual."""
    try:
        return fecha_es(date.fromisoformat(str(iso)[:10]))
    except (TypeError, ValueError):
        return str(iso)


def dia_mes_es(d: date) -> str:
    return f"{d.day} de {MESES[d.month - 1]}"


def _norm(s) -> str:
    return M._norm(s)


def ordinal_f(n: int) -> str:
    return f"{n}.ª"


# ----------------------------------------------------------------------------- series
def capitales(raiz: Path = RAIZ) -> dict:
    """{cod: (indicativo, ciudad, estación)} de las capitales con estación en la propia ciudad (balance_mensual.ESTACIONES)."""
    return M.estaciones_capital(raiz)


def n_anios_serie(serie: dict) -> int:
    return len({d.year for d in serie})


def ultima_fecha(serie: dict) -> date | None:
    return max(serie) if serie else None


def anios_con_dato_fecha(serie: dict, dia: date, ventana: int = 0) -> list[tuple[int, tuple]]:
    """Valores (año, (tmax, tmin, prec)) de la serie para el mismo mes y día de años anteriores; con ventana > 0, también ±ventana días
    (el 29 de febrero no existe en tres de cada cuatro años)."""
    out = []
    for y in range(min(d.year for d in serie), dia.year):
        for k in range(-ventana, ventana + 1):
            try:
                d = date(y, dia.month, dia.day) + timedelta(days=k)
            except ValueError:
                continue
            v = serie.get(d)
            if v:
                out.append((y, v))
    return out


# ============================================================================ B · carreras
def _tramo(serie: dict, ini: date, fin: date, idx: int, min_frac: float = 0.95):
    """(media o suma, n_dias_con_dato) del tramo ini..fin, o None si hay menos del 95 % de días con dato."""
    n = (fin - ini).days + 1
    vals = []
    d = ini
    while d <= fin:
        v = serie.get(d)
        if v and v[idx] is not None:
            vals.append(v[idx])
        d += timedelta(days=1)
    if n <= 0 or len(vals) < min_frac * n:
        return None
    return (sum(vals) if idx == 2 else sum(vals) / len(vals)), len(vals)


def _desplazar(ini: date, per: str, y: int) -> tuple[date, date]:
    i2 = ini.replace(year=y)
    return i2, M.fin_periodo(i2, per)


def _vy(t):
    return (t[1], t[0])


def analiza_periodo(serie: dict, ini: date, hasta: date, per: str, idx: int) -> dict | None:
    """Estado de un periodo en curso (año o estación) en una estación: valor de lo que va, puesto frente al mismo tramo de años
    anteriores, récord del tramo y del periodo completo, y qué hace falta en lo que queda para acabar primero."""
    fin = M.fin_periodo(ini, per)
    cur = _tramo(serie, ini, hasta, idx)
    if cur is None:
        return None
    total = (fin - ini).days + 1
    trans = (hasta - ini).days + 1
    resto_dias = max(0, total - trans)
    anios = sorted({d.year for d in serie})
    parc, full, resto_norm = {}, {}, []
    for y in anios:
        if y >= ini.year:
            continue
        try:
            i2, f2 = _desplazar(ini, per, y)
            h2 = hasta.replace(year=y + (hasta.year - ini.year))
        except ValueError:
            continue
        p = _tramo(serie, i2, h2, idx)
        t = _tramo(serie, i2, f2, idx)
        if p is None or t is None:
            continue
        parc[y], full[y] = p[0], t[0]
        if 1991 <= y <= 2020 and resto_dias:
            r = _tramo(serie, h2 + timedelta(days=1), f2, idx)
            if r is not None:
                resto_norm.append(r[0])
    if idx == 2 and trans >= 30:        # 30 días o más con 0,0 mm exactos: casi siempre un hueco codificado como cero
        parc = {y: v for y, v in parc.items() if v > 0}
        full = {y: v for y, v in full.items() if y in parc}
    if len(parc) < MIN_ANIOS - 1:
        return None
    r = 2 if idx == 2 else 2
    v_act = round(cur[0], 1 if idx == 2 else r)
    pv = {y: round(v, 1 if idx == 2 else r) for y, v in parc.items()}
    por_encima = sum(1 for v in pv.values() if v > v_act)
    empate_alto = any(v == v_act for v in pv.values())
    por_debajo = sum(1 for v in pv.values() if v < v_act)
    return {"valor": v_act, "n_anios": len(parc) + 1, "hasta": str(hasta), "resto_dias": resto_dias, "total_dias": total,
            "puesto_alto": por_encima + 1, "empate_alto": empate_alto, "puesto_bajo": por_debajo + 1,
            "alto": _vy(max(pv.items(), key=lambda x: x[1])), "bajo": _vy(min(pv.items(), key=lambda x: x[1])),
            "full_alto": _vy(max(full.items(), key=lambda x: x[1])), "full_bajo": _vy(min(full.items(), key=lambda x: x[1])),
            "resto_normal": (sum(resto_norm) / len(resto_norm)) if resto_norm else None,
            "resto_min": min(resto_norm) if resto_norm else None, "resto_max": max(resto_norm) if resto_norm else None}


def _frase_calor(ciu: str, a: dict, nombre_per: str) -> tuple[str, dict]:
    """Frase por plantilla de una carrera de calor (media de máximas) en una capital."""
    n = a["n_anios"]
    rec_v, rec_y = a["alto"]
    primera = a["puesto_alto"] == 1 and not a["empate_alto"]
    if primera:
        cab = f"{ciu} va primera de su serie de {n} años en {nombre_per}, hasta el {fecha_es(date.fromisoformat(a['hasta']))}: media de máximas de {f1(a['valor'])} °C (el anterior, {f1(rec_v)} °C en {rec_y})."
    elif a["empate_alto"] and a["puesto_alto"] == 1:
        cab = f"{ciu} iguala en {nombre_per} la media de máximas de {rec_y} ({f1(rec_v)} °C) en una serie de {n} años."
    else:
        cab = f"{ciu} va {ordinal_f(a['puesto_alto'])} de su serie de {n} años en {nombre_per}: media de máximas de {f1(a['valor'])} °C (la mayor, {f1(rec_v)} °C en {rec_y})."
    rd, tot = a["resto_dias"], a["total_dias"]
    extra = {"dias_que_quedan": rd}
    if rd <= 0:
        return cab + " El periodo está cerrado en el dato validado.", extra
    R, Ry = a["full_alto"]
    trans = tot - rd
    x = (R * tot - a["valor"] * trans) / rd
    extra["necesita"] = round(x, 2)
    extra["normal_resto"] = None if a["resto_normal"] is None else round(a["resto_normal"], 2)
    nor = "" if a["resto_normal"] is None else f" La media de ese tramo en 1991-2020 es {f1(a['resto_normal'])} °C."
    if a["resto_min"] is not None and x <= a["resto_min"]:
        extra["estado"] = "asegurado"
        return cab + f" Quedan {rd} días: acaba primera con la media de máximas de ese tramo que se quiera de las {n} de la serie (la más baja, {f1(a['resto_min'])} °C).{nor}", extra
    if a["resto_max"] is not None and x > a["resto_max"]:
        extra["estado"] = "inalcanzable"
        return cab + f" Quedan {rd} días y necesitaría {f1(x)} °C de media de máximas, más que en ningún año de la serie en ese tramo.{nor}", extra
    extra["estado"] = "abierto"
    return cab + f" Quedan {rd} días: le basta con que no bajen de {f1(x)} °C de media de máximas para acabar primera.{nor}", extra


def _frase_lluvia(ciu: str, a: dict, nombre_per: str, cola: str) -> tuple[str, dict]:
    n = a["n_anios"]
    rd = a["resto_dias"]
    extra = {"dias_que_quedan": rd}
    if cola == "lluvioso":
        rec_v, rec_y = a["alto"]
        primera = a["puesto_alto"] == 1 and not a["empate_alto"]
        cab = (f"{ciu} lleva {f1(a['valor'])} l/m² en {nombre_per}, la mayor cantidad de su serie de {n} años (la anterior, {f1(rec_v)} l/m² en {rec_y})."
               if primera else
               f"{ciu} lleva {f1(a['valor'])} l/m² en {nombre_per}, {ordinal_f(a['puesto_alto'])} de su serie de {n} años (la mayor, {f1(rec_v)} l/m² en {rec_y}).")
        if rd > 0:
            R, Ry = a["full_alto"]
            falta = R - a["valor"]
            extra["necesita"] = round(max(0.0, falta), 1)
            cab += (f" Quedan {rd} días: necesita {f1(falta)} l/m² más para igualar el total del periodo completo de {Ry} ({f1(R)} l/m²)."
                    if falta > 0 else f" Quedan {rd} días y ya supera el total del periodo completo de {Ry}.")
        return cab, extra
    rec_v, rec_y = a["bajo"]
    primera = a["puesto_bajo"] == 1
    cab = (f"{ciu} lleva {f1(a['valor'])} l/m² en {nombre_per}, la menor cantidad de su serie de {n} años (la anterior, {f1(rec_v)} l/m² en {rec_y})."
           if primera else
           f"{ciu} lleva {f1(a['valor'])} l/m² en {nombre_per}, {ordinal_f(a['puesto_bajo'])} más baja de su serie de {n} años (la menor, {f1(rec_v)} l/m² en {rec_y}).")
    if rd > 0:
        R, Ry = a["full_bajo"]
        margen = R - a["valor"]
        extra["necesita"] = round(margen, 1)
        cab += (f" Quedan {rd} días: para acabar con el total más bajo de la serie ({f1(R)} l/m² en {Ry}) no puede sumar más de {f1(margen)} l/m²."
                if margen > 0 else f" Quedan {rd} días y ya supera el total más bajo de la serie ({f1(R)} l/m² en {Ry}).")
    return cab, extra


def _poblacion_ciudad(c: str) -> int:
    return M.poblacion(c) or 0


def _cuatro(items: list[dict]) -> list[dict]:
    """La de serie más larga y las tres más pobladas (sin repetir)."""
    if not items:
        return []
    largo = max(items, key=lambda x: x["n_anios"])
    por_pob = sorted(items, key=lambda x: -_poblacion_ciudad(x["ciudad"]))
    out = [largo]
    for x in por_pob:
        if x not in out and len(out) < 4:
            out.append(x)
    return out


def carrera_periodo(hasta: date, per: str, raiz: Path = RAIZ) -> list[dict]:
    """Carreras del año en curso (per='anio') o de la estación en curso (per='estacion'): calor y, en la estación, también lluvia/sequedad."""
    ini = M.inicio_periodo(hasta, per)
    nombre = f"lo que va de {ini.year}" if per == "anio" else f"lo que va de {M.ESTACION_TXT[ini.month]} (desde el {dia_mes_es(ini)})"
    resultados = []
    est = capitales(raiz)
    calor, lluvia = [], []
    for cod, (ind, ciu, _e) in est.items():
        s = M.serie_diaria(ind, raiz)
        if not s:
            continue
        h_est = min(hasta, ultima_fecha(s))
        if (hasta - h_est).days > 20:
            continue
        ac = analiza_periodo(s, ini, h_est, per, 0)
        if ac:
            ac.update({"ciudad": ciu, "indicativo": ind, "cod": cod})
            calor.append(ac)
        if per == "estacion":
            al = analiza_periodo(s, ini, h_est, per, 2)
            if al:
                al.update({"ciudad": ciu, "indicativo": ind, "cod": cod})
                lluvia.append(al)
    if calor:
        primeras = [a for a in calor if a["puesto_alto"] == 1 and not a["empate_alto"]]
        base = primeras or calor
        det = []
        for a in _cuatro(base):
            frase, extra = _frase_calor(a["ciudad"], a, nombre)
            det.append({"ciudad": a["ciudad"], "frase": frase, "n_anios": a["n_anios"], "valor": a["valor"], "puesto": a["puesto_alto"],
                        "record": a["alto"][0], "anio_record": a["alto"][1], **extra})
        cab = det[0]
        titulo = (f"{len(primeras)} de {len(calor)} capitales van primeras en {nombre} (media de máximas, serie de AEMET de 40 años o más)"
                  if primeras else f"Ninguna de las {len(calor)} capitales con serie de AEMET de 40 años o más va primera en {nombre} (media de máximas)")
        resultados.append({"id": f"carrera-{per}-calor", "tipo": "carrera", "variable": "calor", "periodo": per, "titulo": titulo,
                           "frase": cab["frase"], "valor_hoy": cab["valor"], "record": cab["record"], "anio_record": cab["anio_record"],
                           "falta": None if cab["valor"] >= cab["record"] else round(cab["record"] - cab["valor"], 2), "unidad": "°C",
                           "n_anios": cab["n_anios"], "n_primeras": len(primeras), "total": len(calor), "dato_hasta": max(a["hasta"] for a in calor),
                           "progreso": round(len(primeras) / len(calor), 3), "detalle": det})
    if lluvia:
        mas = [a for a in lluvia if a["puesto_alto"] == 1 and not a["empate_alto"]]
        seco = [a for a in lluvia if a["puesto_bajo"] == 1]
        cola = "lluvioso" if len(mas) >= len(seco) and mas else ("seco" if seco else ("lluvioso" if min(a["puesto_alto"] for a in lluvia) <= min(a["puesto_bajo"] for a in lluvia) else "seco"))
        grupo = mas if cola == "lluvioso" and mas else (seco if cola == "seco" and seco else lluvia)
        key = (lambda a: a["puesto_alto"]) if cola == "lluvioso" else (lambda a: a["puesto_bajo"])
        grupo = sorted(grupo, key=key) if grupo is lluvia else grupo
        det = []
        for a in _cuatro(grupo):
            frase, extra = _frase_lluvia(a["ciudad"], a, nombre, cola)
            det.append({"ciudad": a["ciudad"], "frase": frase, "n_anios": a["n_anios"], "valor": a["valor"],
                        "puesto": a["puesto_alto"] if cola == "lluvioso" else a["puesto_bajo"],
                        "record": (a["alto"] if cola == "lluvioso" else a["bajo"])[0], "anio_record": (a["alto"] if cola == "lluvioso" else a["bajo"])[1], **extra})
        n1 = len(mas) if cola == "lluvioso" else len(seco)
        adj = "más lluvia" if cola == "lluvioso" else "menos lluvia"
        titulo = (f"{n1} de {len(lluvia)} capitales llevan {adj} que en ningún año de su serie en {nombre}" if n1
                  else f"Ninguna de las {len(lluvia)} capitales con serie de AEMET de 40 años o más lleva el extremo de lluvia en {nombre}")
        cab = det[0]
        base = cab["record"]
        resultados.append({"id": f"carrera-{per}-{'lluvia' if cola == 'lluvioso' else 'sequedad'}", "tipo": "carrera",
                           "variable": "lluvia" if cola == "lluvioso" else "sequedad", "periodo": per, "titulo": titulo, "frase": cab["frase"],
                           "valor_hoy": cab["valor"], "record": base, "anio_record": cab["anio_record"],
                           "falta": round(abs(base - cab["valor"]), 1), "unidad": "l/m²", "n_anios": cab["n_anios"], "n_primeras": n1,
                           "total": len(lluvia), "dato_hasta": max(a["hasta"] for a in lluvia),
                           "progreso": round(min(1.0, (cab["valor"] / base) if cola == "lluvioso" and base else (base / cab["valor"] if cab["valor"] else 1.0)), 3),
                           "detalle": det})
    return resultados


def carrera_mes(hasta: date, raiz: Path = RAIZ) -> dict:
    """{cod: análisis} de lo que va de mes (media de máximas) en cada capital con ≥ 40 años, para el bloque de provincias."""
    out = {}
    for cod, (ind, ciu, _e) in capitales(raiz).items():
        s = M.serie_diaria(ind, raiz)
        if not s:
            continue
        h_est = min(hasta, ultima_fecha(s))
        if (hasta - h_est).days > 20 or h_est.day < 5:
            continue
        a = analiza_periodo(s, h_est.replace(day=1), h_est, "mes", 0)
        if a:
            a.update({"ciudad": ciu, "indicativo": ind, "cod": cod, "mes": h_est.month})
            out[cod] = a
    return out


def _rachas_serie(serie: dict, pred) -> list[tuple[date, int]]:
    """[(fecha de fin, longitud)] de cada racha de días seguidos que cumplen pred; un día sin dato la corta."""
    out, n, prev = [], 0, None
    for d in sorted(serie):
        v = serie[d]
        ok = pred(v)
        if ok is None or (prev and (d - prev).days > 1):
            if n:
                out.append((prev, n))
            n = 0
        if ok:
            n += 1
        else:
            if n:
                out.append((prev, n))
            n = 0
        prev = d
    if n:
        out.append((prev, n))
    return out


RACHAS = {
    "seca": {"pred": lambda v: None if v[2] is None else v[2] < 1, "min": 10, "txt": "días seguidos sin un día de lluvia de 1 l/m²"},
    "tropical": {"pred": lambda v: None if v[1] is None else v[1] >= 20, "min": 5, "txt": "noches tropicales seguidas (mínima de 20 °C o más)"},
    "helada": {"pred": lambda v: None if v[1] is None else v[1] <= 0, "min": 3, "txt": "días seguidos de helada (mínima de 0 °C o menos)"},
}


def rachas_vivas(hasta: date, raiz: Path = RAIZ, estaciones=None) -> list[dict]:
    """Rachas en curso en el 10 % superior de las de su serie (≥ 40 años de AEMET), con el récord de la serie y cuánto falta. Una por tipo."""
    estaciones = estaciones or M.estaciones_archivo(raiz)
    mejores = {}
    for ind, (_i, nombre, _e) in estaciones.items():
        s = M.serie_diaria(ind, raiz)
        if not s or n_anios_serie(s) < MIN_ANIOS:
            continue
        ult = ultima_fecha(s)
        if (hasta - ult).days > 3:
            continue
        for tipo, cfg in RACHAS.items():
            runs = _rachas_serie(s, cfg["pred"])
            if not runs or runs[-1][0] != ult:
                continue
            n_viva = runs[-1][1]
            previas = runs[:-1]
            if not previas or n_viva < cfg["min"]:
                continue
            largos = sorted(l for _, l in runs)
            q90 = largos[int(0.9 * (len(largos) - 1))]
            if n_viva < q90:
                continue
            rec_fin, rec = max(previas, key=lambda x: x[1])
            prog = min(1.0, n_viva / rec)
            c = {"tipo": tipo, "ind": ind, "nombre": nombre, "n": n_viva, "rec": rec, "anio_rec": rec_fin.year, "ult": ult,
                 "n_anios": n_anios_serie(s), "prog": prog, "supera": n_viva > rec, "iguala": n_viva == rec}
            if tipo not in mejores or (c["prog"], c["n"]) > (mejores[tipo]["prog"], mejores[tipo]["n"]):
                mejores[tipo] = c
    out = []
    for tipo, c in mejores.items():
        txt = RACHAS[tipo]["txt"]
        if c["supera"]:
            fin = f"supera el récord de su serie ({c['rec']} días, en {c['anio_rec']})"
        elif c["iguala"]:
            fin = f"iguala el récord de su serie ({c['rec']} días, en {c['anio_rec']})"
        else:
            fin = f"el récord de su serie es {c['rec']}, en {c['anio_rec']}; faltan {c['rec'] - c['n']}"
        out.append({"id": f"carrera-racha-{tipo}-{c['ind']}", "tipo": "carrera", "variable": f"racha_{tipo}", "periodo": "racha",
                    "titulo": f"{c['nombre']}: día {c['n']} de {txt}", "frase": f"{c['nombre']}: día {c['n']}; {fin}. Serie de AEMET de {c['n_anios']} años.",
                    "valor_hoy": c["n"], "record": c["rec"], "anio_record": c["anio_rec"], "falta": max(0, c["rec"] - c["n"]), "unidad": "días",
                    "n_anios": c["n_anios"], "dato_hasta": str(c["ult"]), "progreso": round(c["prog"], 3), "detalle": []})
    return sorted(out, key=lambda x: -x["progreso"])


def bloque_carreras(hasta: date, raiz: Path = RAIZ) -> dict:
    avisos, piezas = [], []
    for per in ("anio", "estacion"):
        try:
            piezas += carrera_periodo(hasta, per, raiz)
        except Exception as e:  # noqa: BLE001
            avisos.append(f"carreras {per}: {type(e).__name__}: {str(e)[:100]}")
    try:
        piezas += rachas_vivas(hasta, raiz)[:3]
    except Exception as e:  # noqa: BLE001
        avisos.append(f"rachas: {type(e).__name__}: {str(e)[:100]}")
    return {"dato_hasta": str(hasta), "piezas": piezas[:6], "avisos": avisos}


# ============================================================================ C · tal día como hoy
_OBS = {}


def obs_tiempo_real(raiz: Path = RAIZ) -> dict:
    if raiz not in _OBS:
        _OBS[raiz] = (leer_json(raiz / "docs" / "records" / "obs_dias.json", {}) or {}).get("dias", {})
    return _OBS[raiz]


def tal_dia(dia: date, raiz: Path = RAIZ, ayer_tr: bool = True) -> dict:
    """Máxima más alta, mínima más baja y día más lluvioso de un día como hoy en cada capital con serie de ≥ 40 años."""
    filas = []
    ventana = 1 if (dia.month, dia.day) == (2, 29) else 0
    for cod, (ind, ciu, est) in capitales(raiz).items():
        s = M.serie_diaria(ind, raiz)
        vals = anios_con_dato_fecha(s, dia, ventana)
        anios = {y for y, _ in vals}
        if not vals:
            continue
        tx = [(v[0], y) for y, v in vals if v[0] is not None]
        tn = [(v[1], y) for y, v in vals if v[1] is not None]
        pr = [(v[2], y) for y, v in vals if v[2] is not None]
        if not (tx and tn and pr):
            continue
        fila = {"cod": cod, "ciudad": ciu, "estacion": est, "indicativo": ind, "n_anios": len(anios),
                "valida": len(anios) >= MIN_ANIOS, "ventana": bool(ventana),
                "tmax": {"valor": max(tx)[0], "anio": max(tx)[1]}, "tmin": {"valor": min(tn)[0], "anio": min(tn)[1]},
                "lluvia": {"valor": max(pr)[0], "anio": max(pr)[1]}}
        # cuánto se sale cada extremo de lo habitual de ese día (para elegir el más llamativo)
        z = []
        for clave, serie_v, signo in (("tmax", tx, 1), ("tmin", tn, -1), ("lluvia", pr, 1)):
            xs = [v for v, _ in serie_v]
            sd = statistics.pstdev(xs) if len(xs) > 2 else 0
            if sd > 0:
                ext = max(xs) if signo == 1 else min(xs)
                z.append((abs(ext - statistics.mean(xs)) / sd, clave))
        fila["extremo"] = max(z) if z else (0.0, "tmax")
        filas.append(fila)
    return {"fecha": str(dia), "filas": filas}


def _texto_tal_dia(f: dict, var: str, dia: date) -> str:
    fd = dia_mes_es(dia).replace(f"{dia.day} de", f"{dia.day} de")
    if var == "tmax":
        q, v = "la máxima más alta", f"{f1(f['tmax']['valor'])} °C"
    elif var == "tmin":
        q, v = "la mínima más baja", f"{f1(f['tmin']['valor'])} °C"
    else:
        q, v = "el día más lluvioso registrado", f"{f1(f['lluvia']['valor'])} l/m²"
    anio = f[var]["anio"]
    nota = " (ventana de tres días, 28 de febrero a 1 de marzo)" if f["ventana"] else ""
    return (f"{f['ciudad']}: {q} registrada en un {fd} fue {v}, en {anio}; serie de {f['n_anios']} años de la estación de AEMET de {f['estacion']}{nota}.")


def _comparar_ayer(f: dict, dia: date, raiz: Path) -> dict | None:
    """Si hay dato de ayer en tiempo real (AEMET, sin validar) para la estación, cómo quedó frente al récord de ese día. Marcado provisional."""
    ayer = dia - timedelta(days=1)
    obs = obs_tiempo_real(raiz).get(str(ayer), {}).get(f["indicativo"])
    if not obs or obs.get("tx") is None:
        return None
    s = M.serie_diaria(f["indicativo"], raiz)
    vals = anios_con_dato_fecha(s, ayer, 1 if (ayer.month, ayer.day) == (2, 29) else 0)
    tx = [(v[0], y) for y, v in vals if v[0] is not None]
    if len(tx) < MIN_ANIOS - 1:
        return None
    rec, ry = max(tx)
    dif = obs["tx"] - rec
    if dif > 0:
        txt = f"Ayer, {dia_mes_es(ayer)}, la estación registró {f1(obs['tx'])} °C de máxima, por encima del récord de {f1(rec)} °C de {ry}."
    elif dif == 0:
        txt = f"Ayer, {dia_mes_es(ayer)}, la estación registró {f1(obs['tx'])} °C de máxima, igual que el récord de {ry}."
    else:
        txt = f"Ayer, {dia_mes_es(ayer)}, la estación registró {f1(obs['tx'])} °C de máxima, {f1(-dif)} °C por debajo del récord de {f1(rec)} °C de {ry}."
    return {"fecha": str(ayer), "tmax": obs["tx"], "record": rec, "anio_record": ry, "texto": txt + " Dato de tiempo real, sin validar.", "estado": "provisional"}


def bloque_tal_dia(dia: date, raiz: Path = RAIZ, hasta: date | None = None) -> dict:
    t = tal_dia(dia, raiz)
    filas = t["filas"]
    validas = [f for f in filas if f["valida"]] or sorted(filas, key=lambda f: -f["n_anios"])[:1]
    portada = []
    if validas:
        largo = max(validas, key=lambda f: f["n_anios"])
        extremo = max(validas, key=lambda f: f["extremo"][0])
        poblada = max(validas, key=lambda f: _poblacion_ciudad(f["ciudad"]))
        for rol, f in (("serie más larga", largo), ("valor más extremo", extremo), ("más poblada", poblada)):
            var = extremo["extremo"][1] if f is extremo else ("tmax" if dia.month in (5, 6, 7, 8, 9) else "tmin")
            if f is extremo:
                var = f["extremo"][1]
            item = {"rol": rol, "ciudad": f["ciudad"], "variable": var, "valor": f[var]["valor"], "anio": f[var]["anio"], "n_anios": f["n_anios"],
                    "texto": _texto_tal_dia(f, var, dia), "indicativo": f["indicativo"]}
            ayer = _comparar_ayer(f, dia, raiz)
            if ayer:
                item["ayer_tiempo_real"] = ayer
            if not any(p["ciudad"] == item["ciudad"] and p["variable"] == item["variable"] for p in portada):
                portada.append(item)
    return {"fecha": str(dia), "dato_hasta": str(hasta) if hasta else None, "portada": portada,
            "por_capital": {f["cod"]: {k: f[k] for k in ("ciudad", "estacion", "n_anios", "valida", "tmax", "tmin", "lluvia", "ventana")} for f in filas},
            "nota": "Récords de las series diarias validadas de AEMET de las capitales con estación en la propia ciudad y 40 años o más." if filas else "Sin series."}


# ============================================================================ D · España ayer
def _nombre_est(ind: str, raiz: Path) -> str:
    inv = leer_json(raiz / "docs" / "prensa" / "aemet_inventario.json", {}) or {}
    v = inv.get(ind)
    if not v:
        return ind
    return f"{v[0].title()} ({v[1].title()})"


def bloque_espana(hoy: date, raiz: Path = RAIZ, previo: dict | None = None) -> dict:
    """Seis cifras. Si una fuente falla se muestra la última cifra guardada con su fecha (estado «ultima»), no se quita la casilla."""
    ayer = hoy - timedelta(days=1)
    cifras, prev = {}, {c["id"]: c for c in ((previo or {}).get("cifras") or [])}
    envivo = leer_json(raiz / "docs" / "prensa" / "envivo.json", {}) or {}

    def poner(ident, etiqueta, fn):
        try:
            c = fn()
        except Exception:  # noqa: BLE001
            c = None
        if c:
            c.update({"id": ident, "etiqueta": etiqueta, "estado": "ok"})
        elif ident in prev:
            c = dict(prev[ident])
            c["estado"] = "ultima"
        else:
            c = {"id": ident, "etiqueta": etiqueta, "valor": "sin dato", "texto": f"{etiqueta}: la fuente no ha devuelto dato todavía.", "fecha_dato": None, "estado": "sin_dato"}
        cifras[ident] = c

    def red_temp(clave, signo, etiqueta):
        dias = obs_tiempo_real(raiz)
        d = str(ayer) if str(ayer) in dias else (sorted(dias)[-2] if len(dias) > 1 else None)
        if not d:
            return None
        filas = [(v[clave], ind) for ind, v in dias[d].items() if v.get(clave) is not None]
        if not filas:
            return None
        val, ind = (max if signo > 0 else min)(filas)
        nom = _nombre_est(ind, raiz)
        return {"valor": f"{f1(val)} °C", "texto": f"{etiqueta}: {f1(val)} °C en {nom}, el {fecha_es(date.fromisoformat(d))}.", "fecha_dato": d,
                "fuente": "AEMET, observación de tiempo real (sin validar)", "estacion": nom}

    def lluvia():
        import gzip
        d = leer_json(raiz / "archivo" / "lluvia_diaria" / "estado.json", {}) or {}
        with gzip.open(raiz / "archivo" / "lluvia_diaria" / f"{ayer.year}.json.gz", "rt", encoding="utf-8") as f:
            est = json.load(f)["est"]
        i = ayer.timetuple().tm_yday - 1
        filas = [(v[i], k) for k, v in est.items() if len(v) > i and v[i] is not None]
        if not filas:
            return None
        val, ind = max(filas)
        nom = _nombre_est(ind, raiz)
        return {"valor": f"{f1(val)} l/m²", "texto": f"Mayor lluvia en 24 horas: {f1(val)} l/m² en {nom}, el {fecha_es(ayer)}.", "fecha_dato": str(ayer),
                "fuente": "AEMET, lluvia diaria por estación", "estacion": nom}

    def embalses():
        e = envivo.get("embalses") or leer_json(raiz / "docs" / "embalses_nacional.json", {}).get("nacional")
        if not e:
            return None
        dif = round(e["pct"] - e["pct_media_10a"], 1)
        rel = "por encima" if dif > 0 else ("por debajo" if dif < 0 else "igual que")
        cola = f"{f1(abs(dif))} puntos {rel} de la media de los últimos 10 años" if dif else "igual que la media de los últimos 10 años"
        b = e.get("boletin") or leer_json(raiz / "docs" / "embalses_nacional.json", {}).get("boletin_fecha")
        return {"valor": f"{f1(e['pct'])} %", "texto": f"Reserva de embalses: {f1(e['pct'])} % de la capacidad, {cola}.", "fecha_dato": b, "fuente": "MITECO, boletín hidrológico semanal"}

    def mediterraneo():
        m = envivo.get("mediterraneo")
        if not m:
            return None
        an = m["anomalia"]
        return {"valor": f"{'+' if an > 0 else ''}{f1(an)} °C", "texto": f"Mediterráneo: {f1(m['sst'])} °C, {f1(abs(an))} °C {'por encima' if an > 0 else 'por debajo'} de lo normal para la fecha.",
                "fecha_dato": m["ultimo"], "fuente": m.get("fuente", "NOAA OISST")}

    def avisos():
        a = leer_json(raiz / "docs" / "avisos.json", {}) or {}
        n = a.get("por_nivel")
        if not n:
            return None
        return {"valor": f"{a.get('total', sum(n.values()))} avisos",
                "texto": f"Avisos activos de AEMET: {n.get('rojo', 0)} rojos, {n.get('naranja', 0)} naranjas y {n.get('amarillo', 0)} amarillos.",
                "fecha_dato": str(a.get("generado", ""))[:10] or None, "fuente": a.get("fuente", "AEMET")}

    poner("tmax_red", "Máxima de la red de AEMET", lambda: red_temp("tx", 1, "Máxima de la red de AEMET"))
    poner("tmin_red", "Mínima de la red de AEMET", lambda: red_temp("tn", -1, "Mínima de la red de AEMET"))
    poner("lluvia_24h", "Mayor lluvia en 24 horas", lluvia)
    poner("embalses", "Reserva de embalses", embalses)
    poner("mediterraneo", "Anomalía del Mediterráneo", mediterraneo)
    poner("avisos", "Avisos activos", avisos)
    orden = ["tmax_red", "tmin_red", "lluvia_24h", "embalses", "mediterraneo", "avisos"]
    lista = [cifras[k] for k in orden]
    fechas = [c["fecha_dato"] for c in lista if c.get("fecha_dato")]
    return {"dato_hasta": max(fechas) if fechas else None, "cifras": lista}


# ============================================================================ E · provincias
def _cap_de_territorio(territorio: str, cap_por_cod: dict) -> str | None:
    n = _norm(territorio)
    for cod, ciu in cap_por_cod.items():
        if n and (_norm(ciu) == n or n.startswith(_norm(ciu)) or _norm(ciu).startswith(n)):
            return cod
    return None


def _cifras_sequia(d: dict) -> list[dict]:
    out = []
    dd = d.get("dias") or {}
    if dd.get("sin_lluvia") is not None:
        out.append({"n": f"{dd['sin_lluvia']} días", "l": f"sin un día de lluvia de 1 l/m² en la estación de {d.get('capital')} (hasta el {_fe(dd.get('hasta'))})", "tono": "seco", "dato_hasta": dd.get("hasta")})
    h = d.get("hidro") or {}
    if h.get("pct") is not None:
        out.append({"n": f"{h['pct']} %", "l": f"de la lluvia normal del año hidrológico en curso, del {_fe(h.get('inicio'))} al {_fe(h.get('hasta'))}", "tono": "lluvia", "dato_hasta": h.get("hasta")})
    spi = (d.get("spi") or {}).get("12")
    if spi and spi.get("valor") is not None:
        out.append({"n": f1(spi["valor"], 2), "l": f"índice SPI a 12 meses ({d.get('nivel_texto', '').lower()})", "tono": "seco", "dato_hasta": d.get("ultimo_mes_cerrado")})
    return out


def bloque_provincias(hoy: date, hasta: date, mesa_cands: list[dict], tal: dict, carr_mes: dict, raiz: Path = RAIZ) -> dict:
    """52 portadas. Orden de elección: hallazgo provincial de la mesa → puesto de lo que va de mes en la serie de su capital →
    racha sin lluvia → sequía → embalses → huella climática del día → tal día como hoy de su capital → respaldo."""
    cap_por_cod = {cod: v[1] for cod, v in capitales(raiz).items()}
    por_prov = {}
    for c in mesa_cands:
        terr = c.get("territorio") or (c.get("_orig") or {}).get("territorio") or ""
        cod = None
        if c.get("provincia_slug"):
            cod = next((p[0] for p in PROVINCIAS if p[1] == c["provincia_slug"]), None)
        cod = cod or _cap_de_territorio(terr, cap_por_cod)
        if cod and c.get("ambito") != "nacional" and c.get("puntuacion"):
            por_prov.setdefault(cod, []).append(c)
    salida = {}
    for cod, slug, nombre in PROVINCIAS:
        cifras, cand = [], []
        seq = leer_json(raiz / "docs" / "sequia" / f"{slug}.json")
        emb = leer_json(raiz / "docs" / "embalses" / f"{slug}.json")
        hue = leer_json(raiz / "docs" / "huella" / f"{slug}.json")
        # 1 · hallazgo provincial de la mesa
        mejores = sorted(por_prov.get(cod, []), key=lambda c: -c["puntuacion"]["puntos"])
        if mejores:
            c = mejores[0]
            cand.append({"sello": "dato_del_dia", "titular": c["titular"], "entradilla": c.get("entradilla") or "", "fuente": c.get("fuente") or "AEMET y cálculo propio",
                         "dato_hasta": c.get("fecha_dato"), "origen": "mesa"})
        # 2 · puesto de lo que va de mes en la serie de la capital
        cm = (carr_mes or {}).get(cod)
        if cm:
            adj = "más cálido" if cm["puesto_alto"] <= cm["puesto_bajo"] else "más frío"
            p = cm["puesto_alto"] if adj == "más cálido" else cm["puesto_bajo"]
            tit = (f"{cm['ciudad']}: lo que va de {MESES[cm["mes"] - 1]}, el {adj} en {cm['n_anios']} años de serie de AEMET ({f1(cm['valor'])} °C de media de máximas)"
                   if (p == 1 and not cm["empate_alto"]) else
                   f"{cm['ciudad']}: lo que va de {MESES[cm['mes'] - 1]} ocupa el puesto {p} de {cm['n_anios']} {'por calor' if adj == 'más cálido' else 'por frío'} en la serie de AEMET ({f1(cm['valor'])} °C de media de máximas)")
            if min(cm["puesto_alto"], cm["puesto_bajo"]) <= 10:
              cand.append({"sello": "dato_del_dia", "titular": tit, "entradilla": f"Media de las máximas del 1 al {date.fromisoformat(cm['hasta']).day} de {MESES[cm['mes'] - 1]} frente al mismo tramo de los años anteriores. Dato validado de AEMET hasta el {fecha_es(date.fromisoformat(cm['hasta']))}.",
                         "fuente": "AEMET, series diarias validadas", "dato_hasta": cm["hasta"], "origen": "capital_mes"})
            cifras.append({"n": f"{p}.º de {cm['n_anios']}", "l": f"puesto de lo que va de {MESES[cm['mes'] - 1]} por {'calor' if adj == 'más cálido' else 'frío'} en la serie de {cm['ciudad']}", "tono": "calor", "dato_hasta": cm["hasta"]})
        # 3-4 · racha sin lluvia y sequía
        if seq:
            dd = seq.get("dias") or {}
            if (dd.get("sin_lluvia") or 0) >= 10:
                puesto = dd.get("racha_puesto")
                rm = dd.get("racha_max_hist") or {}
                extra = f"; el máximo de su serie es de {rm.get('dias')} días, en {rm.get('anio')}" if rm.get("dias") else ""
                cand.append({"sello": "dato_del_dia", "titular": f"{seq.get('capital', nombre)} lleva {dd['sin_lluvia']} días seguidos sin un día de lluvia de 1 l/m²{extra}",
                             "entradilla": f"Estación de AEMET de {seq.get('estacion', seq.get('capital'))}, dato hasta el {_fe(dd.get('hasta'))}. Serie desde {dd.get('racha_desde')}.",
                             "fuente": "AEMET (precipitación) y cálculo propio", "dato_hasta": dd.get("hasta"), "origen": "racha"})
            try:
                nivel = int(seq.get("nivel") or 0)
            except (TypeError, ValueError):
                nivel = 0
            tx = seq.get("textos") or {}
            if nivel >= 1 and tx.get("titular"):
                cand.append({"sello": "dato_del_dia", "titular": tx["titular"], "entradilla": tx.get("resumen", ""), "fuente": seq.get("fuente", "AEMET y MITECO"),
                             "dato_hasta": seq.get("ultimo_dia_dato") or seq.get("ultimo_mes_cerrado"), "origen": "sequia"})
            cifras += _cifras_sequia(seq)
        # 5 · embalses
        if emb and emb.get("pct_media_10a") is not None and (seq or {}).get("embalses", {}).get("pct") is not None:
            pct = seq["embalses"]["pct"]
        elif emb:
            pct = (emb.get("pct") or (seq or {}).get("embalses", {}).get("pct"))
        else:
            pct = None
        if emb and pct is not None and emb.get("pct_media_10a") is not None:
            dif = round(pct - emb["pct_media_10a"], 1)
            rel = f"{f1(abs(dif))} puntos {'por encima' if dif > 0 else 'por debajo'} de la media de 10 años" if dif else "igual que la media de 10 años"
            cand.append({"sello": "dato_del_dia", "titular": f"Los embalses de {nombre} están al {f1(pct)} %, {rel}", "entradilla": f"Boletín hidrológico del {_fe(emb.get('boletin_fecha'))}; hace un año, {f1(emb.get('pct_hace_1a', 0))} %.",
                         "fuente": "MITECO, boletín hidrológico semanal", "dato_hasta": emb.get("boletin_fecha"), "origen": "embalses"})
            cifras.append({"n": f"{f1(pct)} %", "l": f"de la capacidad de los embalses de {nombre}, {rel}", "tono": "agua", "dato_hasta": emb.get("boletin_fecha")})
        # 6 · huella del día (reanálisis: dicho en el titular, sin umbral absoluto)
        mes = ((hue or {}).get("hoy") or {}).get("mes", {}) or {}
        media = mes.get("media") if isinstance(mes, dict) else None
        if hue and media and (media.get("PR") or 0) >= 1.5:
            cand.append({"sello": "dato_del_dia", "titular": f"{hue.get('capital', nombre)}: según el reanálisis ERA5, lo que va de {MESES[hoy.month - 1]} es {f1(media['PR'], 0)} veces más probable que en 1961-1990",
                         "entradilla": media.get("frase", ""), "fuente": hue.get("fuente", "Reanálisis ERA5"), "dato_hasta": (hue.get("fecha_dato")), "origen": "huella"})
            cifras.append({"n": f"{f1(media['PR'], 0)}×", "l": "veces más probable que en 1961-1990 (reanálisis ERA5)", "tono": "calor", "dato_hasta": hue.get("fecha_dato")})
        # 7 · tal día como hoy de su capital
        td = (tal.get("por_capital") or {}).get(cod)
        tal_prov = None
        if td and td["valida"]:
            tal_prov = {"ciudad": td["ciudad"], "n_anios": td["n_anios"], "tmax": td["tmax"], "tmin": td["tmin"], "lluvia": td["lluvia"], "fecha": tal.get("fecha")}
            d = date.fromisoformat(tal["fecha"])
            cand.append({"sello": "dato_del_dia", "titular": f"{td['ciudad']}: la máxima más alta registrada en un {dia_mes_es(d)} fue {f1(td['tmax']['valor'])} °C, en {td['tmax']['anio']}",
                         "entradilla": f"La mínima más baja para un {dia_mes_es(d)} fue {f1(td['tmin']['valor'])} °C ({td['tmin']['anio']}) y el día más lluvioso, {f1(td['lluvia']['valor'])} l/m² ({td['lluvia']['anio']}). Serie de {td['n_anios']} años de AEMET.",
                         "fuente": "AEMET, series diarias validadas", "dato_hasta": str(hasta), "origen": "tal_dia"})
        # respaldo final: nunca sin titular
        if not cand:
            cand.append({"sello": "dato_del_dia", "titular": f"{nombre}: datos climáticos de la provincia, con series de AEMET y comparación",
                         "entradilla": "La sala de prensa de la provincia reúne las cifras vigentes, las series y la forma de citarlas.", "fuente": "Observatorio climático de calentamientoglobal.es",
                         "dato_hasta": None, "origen": "respaldo"})
        cab = cand[0]
        vistas = set()
        cf = []
        for c in cifras:
            if c["l"] not in vistas:
                vistas.add(c["l"])
                cf.append(c)
        if len(cf) < 3 and td:
            cf.append({"n": f"{f1(td['tmax']['valor'])} °C", "l": f"máxima más alta registrada en un {dia_mes_es(date.fromisoformat(tal['fecha']))} en {td['ciudad']}", "tono": "calor", "dato_hasta": str(hasta)})
        salida[slug] = {"cod": cod, "slug": slug, "nombre": nombre, "dato_del_dia": cab, "otras": cand[1:3], "cifras": cf[:5],
                        "tal_dia": tal_prov, "tal_dia_nota": None if tal_prov else "Sin estación de AEMET de 40 años o más en la propia capital."}
    return {"dato_hasta": str(hasta), "n": len(salida), "por_slug": salida}


# ============================================================================ F · lo que viene
def _capital_municipio(prov: dict, ciu: str) -> tuple[str, dict] | None:
    n = _norm(ciu)
    for k, m in (prov.get("municipios") or {}).items():
        if _norm(m.get("n")) == n:
            return k, m
    return None


def prevision(hoy: date, raiz: Path = RAIZ) -> dict:
    """Capitales cuya máxima o mínima prevista a 1-5 días se desvía más de lo normal de 1991-2020 y lluvia prevista destacada."""
    desv, lluv, emitida = [], [], None
    for cod, (ind, ciu, est) in capitales(raiz).items():
        p = leer_json(raiz / "docs" / "prediccion" / f"{cod}.json")
        if not p:
            continue
        hit = _capital_municipio(p, ciu)
        if not hit:
            continue
        k, m = hit
        dias = [x for x in ((m.get("d") or {}).get("dias") or []) if x.get("f") and date.fromisoformat(x["f"]) > hoy][:5]
        emitida = emitida or (m.get("d") or {}).get("elab")
        mejor = None
        for x in dias:
            for var, real, nor, etq in (("tx", "tx", "nx", "máxima"), ("tn", "tn", "nn", "mínima")):
                if x.get(real) is not None and x.get(nor) is not None:
                    dv = x[real] - x[nor]
                    if mejor is None or abs(dv) > abs(mejor["desv"]):
                        mejor = {"ciudad": ciu, "fecha": x["f"], "variable": etq, "prevista": x[real], "normal": x[nor], "desv": round(dv, 1)}
        if mejor and abs(mejor["desv"]) >= 4:
            desv.append(mejor)
        mo = leer_json(raiz / "docs" / "modelos" / f"{cod}.json")
        mm = ((mo or {}).get("municipios") or {}).get(k) or {}
        tot = []
        for modelo in ("ecmwf", "icon", "gfs", "arpege"):
            ll = (mm.get(modelo) or {}).get("ll")
            if ll and (mm[modelo].get("f") and date.fromisoformat(mm[modelo]["f"]) > hoy - timedelta(days=1)):
                off = (date.fromisoformat(mm[modelo]["f"]) - (hoy + timedelta(days=1))).days
                seg = ll[max(0, -off):][:5] if off <= 0 else ll[:max(0, 5 - off)]
                tot.append(sum(v for v in seg if v is not None))
        if tot and statistics.median(tot) >= 15:
            lluv.append({"ciudad": ciu, "mm_5_dias": round(statistics.median(tot), 1), "modelos": len(tot)})
    desv.sort(key=lambda x: -abs(x["desv"]))
    lluv.sort(key=lambda x: -x["mm_5_dias"])
    textos = []
    for x in desv[:4]:
        d = date.fromisoformat(x["fecha"])
        lado = "por encima" if x["desv"] > 0 else "por debajo"
        textos.append(f"{x['ciudad']}: la {x['variable']} prevista para el {dia_mes_es(d)} es de {f1(x['prevista'], 0)} °C, {f1(abs(x['desv']))} °C {lado} de la normal de 1991-2020 ({f1(x['normal'], 0)} °C).")
    for x in lluv[:3]:
        textos.append(f"{x['ciudad']}: lluvia prevista de {f1(x['mm_5_dias'])} l/m² en los próximos 5 días (mediana de {x['modelos']} modelos).")
    if not textos:
        textos.append("Ninguna capital con estación de referencia tiene prevista a 1-5 días una máxima o mínima a 4 °C o más de su normal de 1991-2020, ni una lluvia de 15 l/m² o más.")
    return {"etiqueta": "previsión", "emitida": emitida, "umbral_grados": 4, "umbral_lluvia_mm": 15, "desviaciones": desv[:4], "lluvia": lluv[:3], "textos": textos,
            "fuente": "AEMET (predicción por municipios), ECMWF, DWD, Météo-France y NOAA (vía Open-Meteo); normal 1991-2020 de AEMET"}


def agenda(hoy: date) -> list[dict]:
    """Próximas fechas fijas calculadas (sin consultar ninguna fuente)."""
    out = []
    mart = hoy + timedelta(days=(1 - hoy.weekday()) % 7)
    out.append({"fecha": str(mart), "tipo": "embalses", "texto": "Parte semanal de embalses del MITECO (los martes)."})
    prox_mes = (hoy.replace(day=1) + timedelta(days=32)).replace(day=1)
    out.append({"fecha": str(prox_mes), "tipo": "balance", "texto": f"Balance mensual de {MESES[(prox_mes.month - 2) % 12]}: se publica el día 1."})
    cierre = prox_mes + timedelta(days=7)
    out.append({"fecha": str(cierre), "tipo": "cierre_mes", "texto": f"Cierre de {MESES[(prox_mes.month - 2) % 12]} con dato validado de AEMET: hacia el día 8."})
    for anio in (hoy.year, hoy.year + 1):
        for mes, dia, nombre in ((2, None, "invierno"), (5, 31, "primavera"), (8, 31, "verano"), (11, 30, "otoño")):
            fin = date(anio, mes, 28) + timedelta(days=4) if dia is None else date(anio, mes, dia)
            if dia is None:
                fin = (date(anio, 3, 1) - timedelta(days=1))
            if fin >= hoy:
                out.append({"fecha": str(fin), "tipo": "estacion", "texto": f"Cierre del {nombre} (el dato validado llega unos 8 días después)."})
                break
        else:
            continue
        break
    h = date(hoy.year if hoy < date(hoy.year, 10, 1) else hoy.year + 1, 10, 1)
    out.append({"fecha": str(h), "tipo": "hidrologico", "texto": "Cambio de año hidrológico: empieza el 1 de octubre."})
    return sorted(out, key=lambda x: x["fecha"])[:5]


def bloque_viene(hoy: date, raiz: Path = RAIZ) -> dict:
    avisos = []
    try:
        pv = prevision(hoy, raiz)
    except Exception as e:  # noqa: BLE001
        pv = {"etiqueta": "previsión", "textos": ["La previsión no se ha podido calcular en esta pasada."], "desviaciones": [], "lluvia": [], "emitida": None}
        avisos.append(f"previsión: {type(e).__name__}: {str(e)[:100]}")
    return {"dato_hasta": str(hoy), "prevision": pv, "agenda": agenda(hoy), "avisos": avisos}
