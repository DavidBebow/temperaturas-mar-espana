"""Compuestos y temporadas (bloque C del plan de atribución, 7-11-2026).

Dos cosas, ambas solo con ficheros del repositorio y sin APIs:

1. COMPUESTOS · lo que pasa cuando se juntan dos cosas. Cuatro reglas, cada una con sus umbrales como constantes:
   sequia_calida, mar_y_dana, nieve_y_embalses, noches_tropicales_en_sequia.
2. TEMPORADAS · cuándo empiezan y terminan las cosas ahora, 1961-1990 frente a 1996-2025, con las series diarias validadas
   de AEMET (archivo/aemet_diario/): verano_largo (primer y último día de 30 °C o más), ultima_helada (última mínima ≤ 0 °C
   entre enero y junio), primer_dia_25 (primer día de 25 °C o más) y temporada_tropical (primera y última noche ≥ 20 °C y total).

Salidas (todas las lee el sistema; nada se calcula en el navegador):
  docs/temporadas/<slug>.json y docs/temporadas/index.json   (para que mañana entren en las páginas de provincia)
  docs/prensa/analisis/compuestos.json                       (reglas, estado de cada una y hallazgos para el detector)

Se ejecuta como paso de hallazgos-prensa.yml, justo antes de hallazgos_prensa.py:  python scripts/sala/compuestos_temporadas.py
Lo importa scripts/sala/analisis.py (historias() devuelve las historias de «Análisis»).

Reglas de método (las mismas que la atribución): solo se afirma cambio con serie validada, ≥ 25 años válidos en cada clima,
homogeneidad «ok» (docs/tu-capital/<slug>.json, vía docs/huella/<slug>.json) y |t| ≥ 2; si no, sale «sin cambio significativo».
«Récord de la serie» exige ≥ 30 años válidos. Redondeo único: se calcula sin redondear y se publica a una décima.
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import json
import math
import statistics as st
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
DOCS = RAIZ / "docs"
HUELLA = DOCS / "huella"
DIARIO = RAIZ / "archivo" / "aemet_diario"
TEMP = DOCS / "temporadas"
SALIDA = DOCS / "prensa" / "analisis" / "compuestos.json"

ANTES, AHORA = (1961, 1990), (1996, 2025)
MIN_ANIOS = 25          # años válidos por clima
MIN_SERIE = 30          # años válidos de la serie para hablar de récord
VALIDO = 0.90           # un año vale si tiene ≥ 90 % de los días de su ventana
T_SIGNIF = 2.0
LICENCIA = "CC BY 4.0 · cálculo propio de calentamientoglobal.es con datos validados de AEMET"
FUENTE_D = "AEMET OpenData (valores climatológicos diarios validados); cálculo de calentamientoglobal.es"

# ---- umbrales de los compuestos (constantes, citados en cada frase de método) ----
SEQ_NIVEL_MIN = 2            # sequía moderada o peor
SEQ_ANOM_MIN = 1.5           # °C de anomalía de la media del mes frente a 1996-2025
MAR_ANOM_MIN = 1.5           # °C de anomalía del Mediterráneo occidental
MAR_DIAS_DANA = 5            # DANA prevista en los próximos 5 días
NIEVE_FRAC_MAX = 0.5         # nieve acumulada < 50 % de lo normal a la fecha
EMB_PUNTOS_MIN = 10.0        # embalses ≥ 10 puntos por debajo de su media de 10 años
NIEVE_MESES = (12, 1, 2, 3, 4)
TROP_NOCHES_MIN = 5          # noches tropicales en los últimos 7 días
TROP_MESES = (6, 7, 8, 9)

MESES = ["", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
_BISIESTO = dt.date(2001, 1, 1).toordinal() - 1   # año no bisiesto de referencia para «día del año»


def f1(x) -> str:
    return f"{x:.1f}".replace(".", ",")


def dd(x) -> str:
    """Días enteros, mitad hacia arriba."""
    return str(int(math.floor(x + 0.5)))


def leer(p, defecto=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return defecto


def doy(fecha: dt.date) -> int:
    m, d = fecha.month, min(fecha.day, 28) if fecha.month == 2 else fecha.day
    return dt.date(2001, m, d).toordinal() - _BISIESTO


def fecha_doy(n: float) -> dt.date:
    return dt.date.fromordinal(_BISIESTO + int(round(n)))


def md(n: float) -> str:
    f = fecha_doy(n)
    return f"{f.day} de {MESES[f.month]}"


def larga(iso: str) -> str:
    f = dt.date.fromisoformat(iso[:10])
    return f"{f.day} de {MESES[f.month]} de {f.year}"


# ============================================================================ series diarias
def serie(ind: str):
    """{fecha: (tmax, tmin)} validados; None donde no hay valor."""
    p = DIARIO / f"{ind}.csv.gz"
    if not p.exists():
        return {}
    out = {}
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                fe = dt.date.fromisoformat(r["fecha"])
            except Exception:
                continue

            def num(v):
                try:
                    return float(v) if v not in ("", None) else None
                except ValueError:
                    return None
            out[fe] = (num(r.get("tmax")), num(r.get("tmin")))
    return out


# (clave, ventana inicio (m,d), fin (m,d), variable 0=tmax 1=tmin, umbral, sentido)
METRICAS = {
    "verano_largo": dict(ini=(3, 1), fin=(11, 30), v=0, cond=lambda x: x >= 30.0, umbral="30 °C", var="máxima"),
    "ultima_helada": dict(ini=(1, 1), fin=(6, 30), v=1, cond=lambda x: x <= 0.0, umbral="0 °C", var="mínima"),
    "primer_dia_25": dict(ini=(1, 1), fin=(7, 31), v=0, cond=lambda x: x >= 25.0, umbral="25 °C", var="máxima"),
    "temporada_tropical": dict(ini=(4, 1), fin=(11, 30), v=1, cond=lambda x: x >= 20.0, umbral="20 °C", var="mínima"),
}


CAMPOS = {"verano_largo": ("ini", "fin", "n", "dur"), "ultima_helada": ("fin",), "primer_dia_25": ("ini",), "temporada_tropical": ("ini", "fin", "n")}


def anio_metrica(S, anio, cfg, hasta=None):
    """Valores de un año o None si no es válido. Dict con ini, fin (día del año), n, dur, y las fechas reales.
    «hasta»: último día con dato (para 2026: la ventana se corta ahí)."""
    a, b = dt.date(anio, *cfg["ini"]), dt.date(anio, *cfg["fin"])
    if hasta is not None and hasta < b:
        b = hasta
    if b < a:
        return None
    dias = (b - a).days + 1
    con, evs = 0, []
    d = a
    while d <= b:
        x = S.get(d)
        if x is not None and x[cfg["v"]] is not None:
            con += 1
            if cfg["cond"](x[cfg["v"]]):
                evs.append(d)
        d += dt.timedelta(days=1)
    if con < VALIDO * dias:
        return None
    if not evs:
        return {"hay": False, "cobertura": con / dias}
    return {"hay": True, "ini": evs[0], "fin": evs[-1], "n": len(evs), "dur": (evs[-1] - evs[0]).days + 1, "cobertura": con / dias}


def welch(a, b):
    if len(a) < 2 or len(b) < 2:
        return None
    va, vb = st.variance(a), st.variance(b)
    se = math.sqrt(va / len(a) + vb / len(b))
    return (st.mean(b) - st.mean(a)) / se if se > 0 else None


def estadistica(vals_antes, vals_ahora):
    if len(vals_antes) < MIN_ANIOS or len(vals_ahora) < MIN_ANIOS:
        return None
    t = welch(vals_antes, vals_ahora)
    return {"antes": st.mean(vals_antes), "ahora": st.mean(vals_ahora), "cambio": st.mean(vals_ahora) - st.mean(vals_antes),
            "t": t, "significativo": t is not None and abs(t) >= T_SIGNIF, "n_antes": len(vals_antes), "n_ahora": len(vals_ahora)}


def estaciones():
    """Estaciones de AEMET con atribución: las de docs/huella/<slug>.json con tipo_fuente «aemet» y homogeneidad «ok»
    o «sin control» (esta última, con citabilidad media). Las demás no entran: ERA5 no se usa en temporadas."""
    out = []
    for p in sorted(HUELLA.glob("*.json")):
        if p.name in ("index.json", "antes_raro.json"):
            continue
        d = leer(p, {})
        if d.get("tipo_fuente") != "aemet" or not d.get("indicativo"):
            continue
        out.append(d)
    return out


def temporadas_estacion(h):
    S = serie(h["indicativo"])
    if not S:
        return None
    ultimo = max(S)
    anio = ultimo.year
    res = {"slug": h["slug"], "capital": h["capital"], "provincia": h["provincia"], "cod": h["cod"], "estacion": h["estacion"],
           "indicativo": h["indicativo"], "fuente": FUENTE_D, "citabilidad": h.get("citabilidad", "media"),
           "homogeneidad": h.get("homogeneidad"), "climas": {"antes": list(ANTES), "ahora": list(AHORA)},
           "ultimo_dato": ultimo.isoformat(), "anio": anio, "metricas": {}}
    for k, cfg in METRICAS.items():
        por = {}
        for y in range(ANTES[0], anio):
            v = anio_metrica(S, y, cfg)
            if v and v["hay"]:
                por[y] = v
        pa = [por[y] for y in range(ANTES[0], ANTES[1] + 1) if y in por]
        pn = [por[y] for y in range(AHORA[0], AHORA[1] + 1) if y in por]
        m = {"anios_validos_serie": len(por), "serie_desde": min(por) if por else None}
        for c in CAMPOS[k]:
            def val(x):
                return doy(x[c]) if c in ("ini", "fin") else x[c]
            m[c] = estadistica([val(x) for x in pa], [val(x) for x in pn])
        # 2026 (año en curso): la ventana se corta en el último día con dato
        a26 = anio_metrica(S, anio, cfg, hasta=ultimo)
        actual = None
        if a26 and a26["hay"]:
            fin_v = dt.date(anio, *cfg["fin"])
            cerrado = ultimo >= fin_v or (k in ("verano_largo", "temporada_tropical") and ultimo >= dt.date(anio, 10, 15)
                                          and (ultimo - a26["fin"]).days >= 14)
            if k in ("ultima_helada",):
                cerrado = ultimo >= fin_v
            if k == "primer_dia_25":
                cerrado = True   # el primer día ya ocurrió: no cambia
            actual = {"anio": anio, "ini": a26["ini"].isoformat(), "fin": a26["fin"].isoformat(), "n": a26["n"], "dur": a26["dur"],
                      "cerrado": bool(cerrado), "datos_hasta": ultimo.isoformat(), "cobertura": round(a26["cobertura"], 3)}
            # extremos de la serie (solo con ≥ 30 años válidos): cada uno se mira en su sentido
            if len(por) >= MIN_SERIE:
                ext = {}

                def comp(c, sentido, firme_si_abierto):
                    xs = [(doy(v[c]) if c in ("ini", "fin") else v[c]) for v in por.values()]
                    x = doy(a26[c]) if c in ("ini", "fin") else a26[c]
                    mejor = min(xs) if sentido == "min" else max(xs)
                    bate = (x <= mejor) if sentido == "min" else (x >= mejor)
                    if bate and (cerrado or firme_si_abierto):
                        ext[c] = {"sentido": sentido, "valor": x, "previo": mejor, "empate": x == mejor,
                                  "firme": bool(cerrado or firme_si_abierto)}
                if k == "verano_largo":
                    comp("ini", "min", True)       # el primer día ya ocurrió
                    comp("dur", "max", True)       # la duración solo crece
                    comp("n", "max", True)
                elif k == "temporada_tropical":
                    comp("ini", "min", True)
                    comp("n", "max", True)
                    comp("fin", "max", False)
                elif k == "ultima_helada":
                    comp("fin", "min", False)      # última helada más temprana: solo si la ventana ya cerró
                elif k == "primer_dia_25":
                    comp("ini", "min", True)
                if ext:
                    actual["extremos"] = ext
        m["actual"] = actual
        res["metricas"][k] = m
    return res


# ============================================================================ compuestos
def _peor(*cits):
    orden = {"alta": 2, "media": 1, "contexto": 0}
    return min(cits, key=lambda c: orden.get(c, 1))


def _serie_dana(hoy):
    """DANA en curso (el catálogo trae un episodio que acaba en el último día con dato) o prevista (docs/dana/prevision.json,
    campo «sistemas»: bajas aisladas que ve el modelo en la caja de España). Devuelve (en_curso, prevista, detalle)."""
    t = leer(DOCS / "dana" / "temporada.json", {}) or {}
    ult = t.get("ultimo_dato")
    en_curso = False
    for e in t.get("episodios_anio") or []:
        if ult and e.get("fin") and e["fin"] >= ult:
            en_curso = True
    pv = leer(DOCS / "dana" / "prevision.json", {}) or {}
    sistemas = pv.get("sistemas") or []
    lim = (hoy + dt.timedelta(days=MAR_DIAS_DANA)).isoformat()
    prox = []
    for s in sistemas:
        ini = None
        if isinstance(s, dict):
            ini = s.get("ini") or s.get("inicio") or s.get("desde") or s.get("fecha")
        if ini is None or str(ini)[:10] <= lim:
            prox.append(s)
    return en_curso, bool(prox), {"ultimo_dato": ult, "run": pv.get("run"), "sistemas": len(sistemas)}


def compuestos(hoy: dt.date):
    out = {"fecha": hoy.isoformat(), "reglas": {}, "hallazgos": []}
    idx = leer(DOCS / "sequia" / "index.json", {}) or {}
    prov_seq = {x["slug"]: x for x in idx.get("provincias", [])}
    hall = out["hallazgos"]

    # ---- 1. sequía cálida ----
    miembros = []
    for slug, pv in prov_seq.items():
        if pv.get("nivel") is None or not (SEQ_NIVEL_MIN <= pv["nivel"] <= 4):
            continue
        h = leer(HUELLA / f"{slug}.json", {}) or {}
        mm = ((h.get("mes") or {}).get("media")) or {}
        ref = (h.get("mes") or {}).get("referencia") or {}
        if not mm or "valor" not in mm or "media_ahora" not in mm:
            continue
        anom = mm["valor"] - mm["media_ahora"]
        if anom >= SEQ_ANOM_MIN:
            sq = leer(DOCS / "sequia" / f"{slug}.json", {}) or {}
            cit_seq = "alta" if str(sq.get("fuente_serie", "")).startswith("AEMET") else "media"
            miembros.append({"slug": slug, "provincia": pv["provincia"], "cod": h.get("cod"), "nivel": pv["nivel"], "nivel_texto": pv["nivel_texto"],
                             "mes": ref.get("mes_nombre"), "tipo_mes": ref.get("tipo"), "hasta": ref.get("hasta"), "media": mm["valor"],
                             "media_ahora": mm["media_ahora"], "media_antes": mm.get("media_antes"), "anomalia": anom,
                             "PR": mm.get("PR"), "pr_min": mm.get("pr_min"), "pr_max": mm.get("pr_max"), "significativo": bool(mm.get("significativo")),
                             "spi12": pv.get("spi12"), "hidro_pct": pv.get("hidro_pct"), "fuente_t": h.get("tipo_fuente"),
                             "citabilidad": _peor(h.get("citabilidad", "media"), cit_seq)})
    miembros.sort(key=lambda m: -m["anomalia"])
    out["reglas"]["sequia_calida"] = {"cumple": bool(miembros), "provincias": [m["slug"] for m in miembros],
                                      "umbrales": {"nivel_min": SEQ_NIVEL_MIN, "anomalia_min_c": SEQ_ANOM_MIN},
                                      "metodo": f"Provincia con nivel de sequía {SEQ_NIVEL_MIN} o más en el Monitor (SPI a 6 y 12 meses de la estación de su capital) y la media del mes en curso "
                                                f"(o del último mes cerrado, si el en curso lleva menos de 10 días) al menos {f1(SEQ_ANOM_MIN)} °C por encima de la media de ese mes en 1996-2025 en la misma serie.",
                                      "miembros": miembros}
    for m in miembros:
        pr = (f"; es {cp(m['PR'])} veces más probable que en 1961-1990 (intervalo {cp(m['pr_min'])}-{cp(m['pr_max'])})" if m["significativo"] and (m["PR"] or 0) > 1
              else "; el cociente de probabilidad frente a 1961-1990 no es significativo")
        hall.append({"serie": "compuestos", "tipo": "compuesto", "indicador": "sequia_calida", "territorio": m["provincia"], "provincia": m["provincia"],
                     "ambito": "provincial", "fecha_dato": (m["hasta"] or hoy.isoformat()), "provisional": m["tipo_mes"] == "en_curso",
                     "titular": f"Sequía cálida en {m['provincia']}: {m['nivel_texto'].lower()} y {f1(m['anomalia'])} °C más que lo normal en {m['mes']}",
                     "dato": (f"{m['provincia']} está en «{m['nivel_texto'].lower()}» en el Monitor de sequía (SPI-12 de {f1(m['spi12'])}) y {mes_hasta(m)} "
                              f"es de {f1(m['media'])} °C, {f1(m['anomalia'])} °C por encima de la media de ese mes en 1996-2025{pr}."),
                     "contexto": ["Menos lluvia y más calor es la combinación que seca más deprisa el suelo y los embalses."],
                     "metodo": out["reglas"]["sequia_calida"]["metodo"],
                     "limites": ["SPI calculado por calentamientoglobal.es, no es el índice oficial de MITECO",
                                 "La anomalía es de una estación (la de la capital), no de toda la provincia"]
                     + (["Temperatura de la celda ERA5 de la capital: reanálisis, no medida"] if m["fuente_t"] == "era5" else []),
                     "citabilidad": m["citabilidad"], "exclusivo": True, "fuente": "AEMET, ERA5 (Copernicus/ECMWF) y cálculo propio de calentamientoglobal.es",
                     "serie_desde": "1961", "pagina": f"https://calentamientoglobal.es/sequia/{m['slug']}/"})
    if len(miembros) >= 3:
        nombres = [m["provincia"] for m in miembros]
        lista = ", ".join(nombres[:-1]) + " y " + nombres[-1]
        media_anom = st.mean(m["anomalia"] for m in miembros)
        hall.append({"serie": "compuestos", "tipo": "compuesto", "indicador": "sequia_calida_varias", "territorio": "España", "ambito": "nacional",
                     "fecha_dato": max((m["hasta"] or hoy.isoformat()) for m in miembros), "provisional": any(m["tipo_mes"] == "en_curso" for m in miembros),
                     "titular": f"Sequía cálida en {len(miembros)} provincias: sequía moderada o peor y hasta {f1(miembros[0]['anomalia'])} °C más que lo normal",
                     "dato": f"Con sequía moderada o peor y el mes al menos {f1(SEQ_ANOM_MIN)} °C por encima de lo normal: {lista}. Anomalía media, {f1(media_anom)} °C.",
                     "contexto": ["Cada provincia se mide con la estación de su capital."], "metodo": out["reglas"]["sequia_calida"]["metodo"],
                     "limites": ["SPI calculado por calentamientoglobal.es, no es el índice oficial de MITECO"],
                     "citabilidad": _peor(*[m["citabilidad"] for m in miembros]), "exclusivo": True,
                     "fuente": "AEMET, ERA5 (Copernicus/ECMWF) y cálculo propio de calentamientoglobal.es", "serie_desde": "1961",
                     "pagina": "https://calentamientoglobal.es/sequia/", "miembros_slug": [m["slug"] for m in miembros]})

    # ---- 2. mar y DANA ----
    M = leer(DOCS / "dana" / "mediterraneo.json", {}) or {}
    en_curso, prevista, det = _serie_dana(hoy)
    mar_ok = bool(M) and (M.get("anomalia") is not None and (M["anomalia"] >= MAR_ANOM_MIN or M.get("puesto_para_la_fecha") == 1))
    cumple = bool(mar_ok and (en_curso or prevista))
    out["reglas"]["mar_y_dana"] = {"cumple": cumple, "mar_anomalia": M.get("anomalia"), "mar_ultimo": M.get("ultimo"), "mar_sst": M.get("sst"),
                                   "mar_puesto": M.get("puesto_para_la_fecha"), "mar_de": M.get("de"), "dana_en_curso": en_curso, "dana_prevista": prevista,
                                   "dana": det, "umbrales": {"anomalia_min_c": MAR_ANOM_MIN, "dias_prevision": MAR_DIAS_DANA},
                                   "metodo": f"Mediterráneo occidental español (NOAA OISST) con la temperatura del mar al menos {f1(MAR_ANOM_MIN)} °C por encima de lo normal, o en récord para la fecha, "
                                             f"y una DANA en curso en el catálogo del observatorio o prevista en los próximos {MAR_DIAS_DANA} días en la previsión de ECMWF a 500 hPa."}
    if cumple:
        quien = "hay una DANA en curso" if en_curso else f"el modelo europeo prevé una DANA en los próximos {MAR_DIAS_DANA} días"
        hall.append({"serie": "compuestos", "tipo": "compuesto", "indicador": "mar_y_dana", "territorio": "España", "ambito": "nacional",
                     "fecha_dato": M["ultimo"], "provisional": False,
                     "titular": f"El Mediterráneo está {f1(M['anomalia'])} °C por encima de lo normal y {quien}: una DANA sobre un mar así tiene más vapor disponible",
                     "dato": (f"El {larga(M['ultimo'])} la temperatura del Mediterráneo occidental era de {f1(M['sst'])} °C, {f1(M['anomalia'])} °C por encima de la media de la fecha "
                              f"(puesto {M.get('puesto_para_la_fecha')} de {M.get('de')} desde 1981), y {quien}."),
                     "contexto": ["Más vapor disponible no significa más lluvia: depende de dónde se sitúe la DANA."],
                     "metodo": out["reglas"]["mar_y_dana"]["metodo"],
                     "limites": ["No predice lluvias ni su cantidad", "La previsión de DANA es del modelo de ECMWF, no un aviso oficial de AEMET"],
                     "citabilidad": "media" if prevista and not en_curso else "alta", "exclusivo": True,
                     "fuente": "NOAA OISST v2.1 y ECMWF IFS (datos abiertos), cálculo propio de calentamientoglobal.es", "serie_desde": "1981",
                     "pagina": "https://calentamientoglobal.es/dana/"})

    # ---- 3. nieve y embalses (dic-abr) ----
    ns = []
    if hoy.month in NIEVE_MESES:
        for slug in prov_seq:
            n = ((leer(DOCS / "nieve" / f"{slug}.json", {}) or {}).get("monte") or {}).get("temporada") or {}
            e = leer(DOCS / "embalses" / f"{slug}.json", {}) or {}
            if not n or not e or not n.get("normal") or n.get("acum") is None or e.get("pct_media") is None or e.get("pct_media_10a") is None:
                continue
            frac = n["acum"] / n["normal"]
            dif = e["pct_media"] - e["pct_media_10a"]
            if frac < NIEVE_FRAC_MAX and dif <= -EMB_PUNTOS_MIN:
                ns.append({"slug": slug, "provincia": prov_seq[slug]["provincia"], "acum": n["acum"], "normal": n["normal"], "frac": frac,
                           "emb": e["pct_media"], "emb10": e["pct_media_10a"], "dif": dif, "boletin": e.get("boletin_fecha")})
    out["reglas"]["nieve_y_embalses"] = {"cumple": bool(ns), "en_temporada": hoy.month in NIEVE_MESES, "provincias": [x["slug"] for x in ns],
                                         "umbrales": {"nieve_frac_max": NIEVE_FRAC_MAX, "embalses_puntos_min": EMB_PUNTOS_MIN},
                                         "metodo": f"De diciembre a abril, provincia con la nieve acumulada en el monte de referencia por debajo del {dd(NIEVE_FRAC_MAX * 100)} % de lo normal a la fecha "
                                                   f"(ERA5, 1991-2020) y los embalses al menos {dd(EMB_PUNTOS_MIN)} puntos por debajo de su media de los últimos 10 años (MITECO)."}
    for x in ns:
        hall.append({"serie": "compuestos", "tipo": "compuesto", "indicador": "nieve_y_embalses", "territorio": x["provincia"], "provincia": x["provincia"],
                     "ambito": "provincial", "fecha_dato": x["boletin"] or hoy.isoformat(), "provisional": False,
                     "titular": f"Poca nieve y embalses bajos en {x['provincia']}: mala señal para la primavera",
                     "dato": (f"La nieve acumulada este invierno es el {dd(x['frac'] * 100)} % de lo normal a la fecha y los embalses están al {f1(x['emb'])} %, "
                              f"{f1(-x['dif'])} puntos por debajo de su media de 10 años ({f1(x['emb10'])} %)."),
                     "contexto": ["La nieve de la montaña alimenta los embalses en primavera."], "metodo": out["reglas"]["nieve_y_embalses"]["metodo"],
                     "limites": ["La nieve es de reanálisis ERA5 en un monte de referencia, no de una estación", "No predice la primavera: indica menos reserva en la montaña"],
                     "citabilidad": "media", "exclusivo": True, "fuente": "ERA5 (Copernicus/ECMWF) y MITECO (Boletín Hidrológico), cálculo propio de calentamientoglobal.es",
                     "serie_desde": "1991", "pagina": f"https://calentamientoglobal.es/nieve/{x['slug']}/"})

    # ---- 4. noches tropicales en sequía (jun-sep) ----
    nt = []
    if hoy.month in TROP_MESES:
        for h in estaciones():
            pv = prov_seq.get(h["slug"])
            if not pv or (pv.get("nivel") or 0) < SEQ_NIVEL_MIN or pv["nivel"] > 4:
                continue
            S = serie(h["indicativo"])
            if not S:
                continue
            ult = max(S)
            ven = [ult - dt.timedelta(days=i) for i in range(7)]
            con = [S.get(d) for d in ven if S.get(d) and S[d][1] is not None]
            if len(con) >= 6 and sum(1 for x in con if x[1] >= 20.0) >= TROP_NOCHES_MIN:
                nt.append({"slug": h["slug"], "capital": h["capital"], "provincia": h["provincia"], "n": sum(1 for x in con if x[1] >= 20.0),
                           "hasta": ult.isoformat(), "nivel": pv["nivel_texto"], "cit": h.get("citabilidad", "media")})
    out["reglas"]["noches_tropicales_en_sequia"] = {"cumple": bool(nt), "en_temporada": hoy.month in TROP_MESES, "provincias": [x["slug"] for x in nt],
                                                    "umbrales": {"noches_min": TROP_NOCHES_MIN, "nivel_min": SEQ_NIVEL_MIN},
                                                    "metodo": f"De junio a septiembre, capital con al menos {TROP_NOCHES_MIN} noches tropicales (mínima de 20 °C o más) en los últimos 7 días con dato validado "
                                                              f"y sequía moderada o peor en su provincia."}
    for x in nt:
        hall.append({"serie": "compuestos", "tipo": "compuesto", "indicador": "noches_tropicales_sequia", "territorio": x["capital"], "provincia": x["provincia"],
                     "ambito": "provincial", "fecha_dato": x["hasta"], "provisional": False,
                     "titular": f"{x['n']} noches tropicales en una semana en {x['capital']}, con la provincia en {x['nivel'].lower()}",
                     "dato": f"En los siete días hasta el {larga(x['hasta'])}, {x['n']} noches con mínima de 20 °C o más en la estación de {x['capital']} (AEMET).",
                     "contexto": ["Las noches calurosas con suelo seco aumentan el riesgo de incendio y la demanda de agua."],
                     "metodo": out["reglas"]["noches_tropicales_en_sequia"]["metodo"], "limites": ["SPI calculado por calentamientoglobal.es, no es el índice oficial de MITECO"],
                     "citabilidad": x["cit"], "exclusivo": True, "fuente": FUENTE_D, "serie_desde": "1961", "pagina": f"https://calentamientoglobal.es/sequia/{x['slug']}/"})
    return out


def mes_hasta(m):
    """«la media de octubre de 2026» (mes cerrado) o «la media de noviembre de 2026 hasta el 8 de noviembre de 2026» (en curso)."""
    return f"la media de {m['mes']}" + (f" hasta el {larga(m['hasta'])}" if m["tipo_mes"] == "en_curso" else "")


def cp(v):
    v = float(v)
    return str(int(round(v))) if v >= 10 else f1(v)


# ============================================================================ temporadas: hallazgos
ETIQ = {
    "verano_largo": {"ini": "primer día de 30 °C o más", "dur": "duración del verano (de primer a último día de 30 °C o más)", "n": "días de 30 °C o más", "fin": "último día de 30 °C o más"},
    "ultima_helada": {"fin": "última helada (mínima de 0 °C o menos entre enero y junio)"},
    "primer_dia_25": {"ini": "primer día de 25 °C o más"},
    "temporada_tropical": {"ini": "primera noche tropical", "fin": "última noche tropical", "n": "noches tropicales"},
}


# Titular nacional cuando ≥ 3 estaciones cuentan lo mismo (lo compone hallazgos_prensa.py con sus valores y los de «dato»).
AGREGADO = {
    "verano_largo_n": "{n} estaciones de AEMET superan en {anio} su récord de días de 30 °C o más",
    "verano_largo_dur": "{n} estaciones de AEMET tienen en {anio} el verano más largo de su serie (del primer al último día de 30 °C o más)",
    "verano_largo_ini": "{n} estaciones de AEMET tuvieron en {anio} el primer día de 30 °C o más más temprano de su serie",
    "verano_largo_fin": "{n} estaciones de AEMET tuvieron en {anio} el último día de 30 °C o más más tardío de su serie",
    "ultima_helada_fin": "{n} estaciones de AEMET tuvieron en {anio} la última helada más temprana de su serie",
    "primer_dia_25_ini": "{n} estaciones de AEMET tuvieron en {anio} el primer día de 25 °C o más más temprano de su serie",
    "temporada_tropical_n": "{n} estaciones de AEMET superan en {anio} su récord de noches tropicales",
    "temporada_tropical_ini": "{n} estaciones de AEMET tuvieron en {anio} la primera noche tropical más temprana de su serie",
    "temporada_tropical_fin": "{n} estaciones de AEMET tuvieron en {anio} la última noche tropical más tardía de su serie",
}


def hallazgos_temporadas(T, hoy):
    out = []
    for e in T:
        for k, m in e["metricas"].items():
            a = m.get("actual")
            if not a or not a.get("extremos"):
                continue
            for c, x in a["extremos"].items():
                if c in ("ini", "fin"):
                    val, prev = md(x["valor"]), md(x["previo"])
                else:
                    val, prev = dd(x["valor"]), dd(x["previo"])
                if c in ("ini", "fin"):
                    fecha = a["ini"] if c == "ini" else a["fin"]
                else:
                    fecha = a["datos_hasta"]
                emp = "iguala" if x["empate"] else "bate"
                nombre = ETIQ[k][c]
                if c in ("n", "dur"):
                    frase = f"{e['anio']} {emp} el máximo de su serie en {nombre}: {val}, frente a {prev} del máximo anterior"
                else:
                    frase = f"{e['anio']} {emp} el récord de su serie: {nombre} el {val}, frente al {prev} del anterior"
                est = ("cerrada" if a["cerrado"] else "aún abierta")
                out.append({"serie": "temporadas", "tipo": "temporada", "indicador": f"{k}_{c}", "territorio": e["capital"], "provincia": e["provincia"],
                            "valor": val, "previo": prev, "empate": x["empate"], "agregado": AGREGADO[f"{k}_{c}"],
                            "ambito": "provincial", "fecha_dato": fecha[:10] if c in ("ini", "fin") else a["datos_hasta"],
                            "provisional": not a["cerrado"],
                            "titular": f"{e['capital']}: {frase[:1].lower() + frase[1:]}",
                            "dato": f"{frase}, con datos validados de AEMET hasta el {larga(a['datos_hasta'])} (serie desde {m['serie_desde']}; temporada {est}).",
                            "contexto": [f"Serie de la estación de AEMET de {e['estacion']}, con {m['anios_validos_serie']} años válidos."],
                            "metodo": f"Se mira cada año por separado entre el {METRICAS[k]['ini'][1]}/{METRICAS[k]['ini'][0]} y el {METRICAS[k]['fin'][1]}/{METRICAS[k]['fin'][0]} con la {METRICAS[k]['var']} diaria "
                                      f"validada (umbral {METRICAS[k]['umbral']}); solo cuentan años con al menos {dd(VALIDO * 100)} % de días con dato.",
                            "limites": ["Datos validados de AEMET con 10-20 días de retraso" + ("; la temporada sigue abierta, la cifra puede subir" if not a["cerrado"] else ""),
                                        "Una estación mide un punto, no toda la provincia"],
                            "citabilidad": e["citabilidad"] if m["anios_validos_serie"] >= MIN_SERIE else "media", "exclusivo": True, "fuente": FUENTE_D,
                            "serie_desde": str(m["serie_desde"]), "pagina": f"https://calentamientoglobal.es/el-tiempo/{e['slug']}/"})
    return out


# ============================================================================ historias de «Análisis»
# Las pinta scripts/sala/analisis.py (generar → historias(R, D)); leen los JSON que escribe main(), no recalculan nada.
SECCION = "analisis"
PAG_TIEMPO = "https://calentamientoglobal.es/el-tiempo/"
PAG_SEQ = "https://calentamientoglobal.es/sequia/"
PAG_DANA = "https://calentamientoglobal.es/dana/"
EN_TEMPORADA = {"temporada_tropical": ((7, 1), (12, 15)), "ultima_helada": ((3, 1), (7, 15)), "primer_dia_25": ((3, 1), (7, 31))}
CFG_H = {
    "temporada_tropical": dict(campo="n", kicker="Análisis · las noches tropicales", tono="calor", puntos=62, pagina=PAG_TIEMPO,
                               tit_red="Las noches tropicales se multiplican: de {a} al año en 1961-1990 a {b} en 1996-2025 en {lugar}",
                               nombre="noches con una mínima de 20 °C o más"),
    "ultima_helada": dict(campo="fin", kicker="Análisis · la última helada", tono="frio", puntos=52, pagina=PAG_TIEMPO,
                          tit_red="La última helada de la primavera llega {d} días antes en {lugar}: el {b} de media en 1996-2025, frente al {a} en 1961-1990",
                          nombre="última mínima de 0 °C o menos entre enero y junio"),
    "primer_dia_25": dict(campo="ini", kicker="Análisis · el primer día de 25 °C", tono="calor", puntos=52, pagina=PAG_TIEMPO,
                          tit_red="El primer día de 25 °C llega {d} días antes en {lugar}: el {b} de media en 1996-2025, frente al {a} en 1961-1990",
                          nombre="primer día con máxima de 25 °C o más"),
}


def _dia_o_num(campo, v):
    return md(v) if campo in ("ini", "fin") else dd(v)


def _estaciones_temporada():
    out = []
    for p in sorted(TEMP.glob("*.json")):
        if p.name != "index.json":
            out.append(leer(p, {}))
    return [e for e in out if e.get("metricas")]


def _h_temporada(R, clave, hoy):
    ini, fin = EN_TEMPORADA[clave]
    if not dt.date(hoy.year, *ini) <= hoy <= dt.date(hoy.year, *fin):
        return []
    cfg = CFG_H[clave]
    campo = cfg["campo"]
    est = []
    for e in _estaciones_temporada():
        m = (e["metricas"].get(clave) or {}).get(campo)
        if m and m.get("t") is not None:
            est.append((e, m))
    sig = [(e, m) for e, m in est if m["significativo"]]
    if len(est) < 3 or not sig:
        return []
    sig.sort(key=lambda x: -abs(x[1]["cambio"]))
    lider, ml = sig[0]
    es_fecha = campo in ("ini", "fin")
    cambios = sorted(abs(m["cambio"]) for _, m in sig)
    mediana = st.median(cambios)
    unidad = "días" if es_fecha else "noches"
    lugar = lambda e: e["capital"] if R.H._norm(R.nprov(e["cod"])) in R.H._norm(e["capital"]) else f"{e['capital']} ({R.nprov(e['cod'])})"  # noqa: E731
    f = lambda m_, k: _dia_o_num(campo, m_[k])  # noqa: E731
    cuantas = f"En las {len(est)} estaciones de AEMET con serie larga analizadas, todas" if len(sig) == len(est) else f"En {len(sig)} de las {len(est)} estaciones de AEMET con serie larga analizadas"
    hechos = [R.hecho("t_red", f"{cuantas} tienen un cambio significativo (t ≥ 2) entre 1961-1990 y 1996-2025 en {cfg['nombre']}: "
                               f"entre {dd(cambios[0])} y {dd(cambios[-1])} {unidad}, con una mediana de {dd(mediana)}.", FUENTE_D,
                      [str(len(sig)), str(len(est)), "2", "1961", "1990", "1996", "2025", dd(cambios[0]), dd(cambios[-1]), dd(mediana)]),
              R.hecho("t_lider", f"En {lugar(lider)}, {cfg['nombre']}: {f(ml, 'antes')} de media en 1961-1990 y {f(ml, 'ahora')} en 1996-2025, {dd(abs(ml['cambio']))} {unidad} "
                                 f"{'antes' if (es_fecha and ml['cambio'] < 0) else ('después' if es_fecha else ('más' if ml['cambio'] > 0 else 'menos'))}.",
                      FUENTE_D, [f(ml, "antes"), f(ml, "ahora"), dd(abs(ml["cambio"])), "1961", "1990", "1996", "2025"], lugar=lider["capital"])]
    recs = []
    for e, m in est:
        a = (e["metricas"][clave].get("actual") or {})
        if campo in (a.get("extremos") or {}):
            recs.append((e, a["extremos"][campo]))
    if recs:
        u = "" if es_fecha else " noches"
        partes = [f"{lugar(e)} ({_dia_o_num(campo, x['valor'])}{u}, antes {_dia_o_num(campo, x['previo'])})" for e, x in recs]
        hechos.append(R.hecho("t_2026", f"Con los datos validados por AEMET, {hoy.year} bate o iguala el extremo de su serie en {len(recs)} estaciones: {R.lista_y(partes)}.", FUENTE_D,
                              [str(hoy.year), str(len(recs))] + [_dia_o_num(campo, x["valor"]) for _, x in recs] + [_dia_o_num(campo, x["previo"]) for _, x in recs],
                              superlativo=True, record=True))
    hechos.append(R.hecho("t_ctrl", "Solo entran estaciones con al menos 25 años válidos en cada clima y homogeneidad comprobada; ERA5 no se usa. Una estación mide un punto: "
                                    "su ciudad pudo cambiar a su alrededor.", FUENTE_D, ["25"]))
    d = dd(abs(ml["cambio"]))
    tit = cfg["tit_red"].format(a=f(ml, "antes"), b=f(ml, "ahora"), d=d, lugar=lugar(lider))
    pl = {"titular": tit, "subtitulo": hechos[0]["dice"], "entradilla": hechos[1]["dice"],
          "cuerpo": [x["dice"] for x in hechos[2:]], "claves": [x["dice"] for x in hechos[:3]]}
    cifras = [{"n": f"{dd(cambios[0])} a {dd(cambios[-1])}", "l": f"{unidad} de cambio en {len(sig)} estaciones con cambio significativo (AEMET, 1961-1990 → 1996-2025)", "tono": cfg["tono"]}]
    hid = f"{R.HOY.isoformat()}-{clave}"
    h = R.historia(clave, hid, cfg["kicker"], cfg["tono"], cfg["puntos"], hechos, pl, cifras, FUENTE_D,
                   "Cada año se mira por separado con la serie diaria validada de AEMET; medias de 1961-1990 y 1996-2025 con al menos 25 años válidos cada una; "
                   "cambio significativo con |t| ≥ 2 (Welch).",
                   ["Datos validados de AEMET con 10-20 días de retraso.", "Una estación mide un punto, no toda la provincia.", "ERA5 no se usa en este análisis."], cfg["pagina"])
    h["seccion"] = SECCION
    for e, m in est:
        a = (e["metricas"][clave].get("actual") or {})
        hv = [R.hecho("tp", f"En la estación de AEMET de {e['capital']}, {cfg['nombre']}: {f(m, 'antes')} de media en 1961-1990 y {f(m, 'ahora')} en 1996-2025"
                            + (f" ({dd(abs(m['cambio']))} {unidad} {'antes' if m['cambio'] < 0 else 'después'})." if es_fecha else f" ({'+' if m['cambio'] > 0 else '−'}{dd(abs(m['cambio']))} {unidad})."),
                      FUENTE_D, [f(m, "antes"), f(m, "ahora"), dd(abs(m["cambio"])), "1961", "1990", "1996", "2025"], lugar=e["capital"]),
              R.hecho("tp_sig", ("El cambio es estadísticamente significativo (t ≥ 2)." if m["significativo"] else "El cambio no es estadísticamente significativo (|t| < 2)."), FUENTE_D, ["2"])]
        if a:
            ex = (a.get("extremos") or {}).get(campo)
            v = _dia_o_num(campo, doy(dt.date.fromisoformat(a["fin"] if campo == "fin" else a["ini"]))) if es_fecha else dd(a["n"] if campo == "n" else a["dur"])
            hv.append(R.hecho("tp_2026", f"En {a['anio']}, con datos validados hasta el {larga(a['datos_hasta'])}: {v}" + (" (récord de su serie)." if ex else "."), FUENTE_D,
                              [str(a["anio"]), larga(a["datos_hasta"]), v], lugar=e["capital"], superlativo=bool(ex), record=bool(ex)))
        sub = hv[1]["dice"]
        plv = {"titular": f"{e['capital']}: " + (f"{cfg['nombre']}, {dd(abs(m['cambio']))} {unidad} {'antes' if m['cambio'] < 0 else 'después'} que en 1961-1990" if es_fecha
                                                else f"{dd(m['ahora'])} {unidad} al año, frente a {dd(m['antes'])} en 1961-1990"),
               "subtitulo": sub, "entradilla": hv[0]["dice"], "cuerpo": [x["dice"] for x in hv[2:]] or [hv[1]["dice"]], "claves": [x["dice"] for x in hv[:3]]}
        h["provincias"][e["cod"]] = {"provincia": R.nprov(e["cod"]), "slug": R.PROV[e["cod"]][1], "hechos": hv, "plantilla": plv,
                                     "cifras": [{"n": f"{f(m, 'antes')} → {f(m, 'ahora')}", "l": f"{cfg['nombre']} en {e['capital']}, 1961-1990 → 1996-2025", "tono": cfg["tono"]}],
                                     "puntos": round(min(66.0, cfg["puntos"] + min(abs(m["t"]), 8)), 1)}
    return [h]


def _h_compuestos(R, hoy):
    C = leer(SALIDA, {}) or {}
    reglas = C.get("reglas") or {}
    if not reglas:
        return []
    out = []
    hoy_txt = larga(hoy.isoformat())
    sc = reglas.get("sequia_calida") or {}
    if sc.get("cumple"):
        ms = sc["miembros"]
        top = ms[0]
        nom = [m["provincia"] for m in ms]
        hechos = [R.hecho("sc_n", f"En {len(ms)} provincias el Monitor de sequía marca sequía moderada o peor y la media del mes en curso está al menos {f1(SEQ_ANOM_MIN)} °C por encima de la media de ese mes en 1996-2025: "
                                  f"{R.lista_y(nom)}.", "Monitor de sequía y atribución de calentamientoglobal.es", [str(len(ms)), f1(SEQ_ANOM_MIN), "1996", "2025"] + nom),
                  R.hecho("sc_top", f"La mayor anomalía es la de {top['provincia']}: {f1(top['media'])} °C de media en {top['mes']}, {f1(top['anomalia'])} °C más que la media de ese mes en 1996-2025, "
                                    f"con la provincia en «{top['nivel_texto'].lower()}».", "Monitor de sequía y atribución de calentamientoglobal.es",
                          [f1(top["media"]), f1(top["anomalia"]), "1996", "2025"], lugar=top["provincia"], superlativo=True),
                  R.hecho("sc_met", sc["metodo"], "Monitor de sequía y atribución de calentamientoglobal.es", [str(SEQ_NIVEL_MIN), f1(SEQ_ANOM_MIN), "1996", "2025", "10"])]
        tit = (f"Sequía cálida en {len(ms)} provincias: sequía moderada o peor y hasta {f1(top['anomalia'])} °C más que lo normal" if len(ms) > 1
               else f"Sequía cálida en {top['provincia']}: sequía moderada o peor y {f1(top['anomalia'])} °C más que lo normal")
        pl = {"titular": tit, "subtitulo": hechos[1]["dice"], "entradilla": hechos[0]["dice"], "cuerpo": [hechos[2]["dice"]], "claves": [x["dice"] for x in hechos[:2]]}
        h = R.historia("sequia_calida", f"{R.HOY.isoformat()}-sequia-calida", "Análisis · sequía cálida", "calor", 64, hechos, pl,
                       [{"n": str(len(ms)), "l": "provincias con sequía moderada o peor y el mes al menos 1,5 °C más cálido", "tono": "calor"}],
                       "Monitor de sequía (SPI-6/12 de AEMET) y atribución de calentamientoglobal.es", sc["metodo"],
                       ["SPI calculado por calentamientoglobal.es, no es el índice oficial de MITECO.", "La anomalía es de la estación de la capital, no de toda la provincia."], PAG_SEQ)
        h["seccion"] = SECCION
        for m in ms:
            if not m.get("cod") or m["cod"] not in R.PROV:
                continue
            pr = (f" Es {cp(m['PR'])} veces más probable que en 1961-1990 (intervalo {cp(m['pr_min'])}-{cp(m['pr_max'])})." if m["significativo"] and (m["PR"] or 0) > 1
                  else " Frente a 1961-1990, el cambio de probabilidad no es significativo.")
            hv = [R.hecho("scp", f"{m['provincia']} está en «{m['nivel_texto'].lower()}» en el Monitor de sequía y {mes_hasta(m)} es de {f1(m['media'])} °C, "
                                 f"{f1(m['anomalia'])} °C por encima de la media de ese mes en 1996-2025.", "Monitor de sequía y atribución de calentamientoglobal.es",
                          [m["provincia"], m["mes"], larga(m["hasta"]), f1(m["media"]), f1(m["anomalia"]), "1996", "2025"], lugar=m["provincia"]),
                  R.hecho("scp_pr", pr.strip(), "Atribución de calentamientoglobal.es", [cp(m["PR"]) if m["PR"] else "", cp(m["pr_min"]) if m["pr_min"] else "", cp(m["pr_max"]) if m["pr_max"] else "", "1961", "1990"])]
            h["provincias"][m["cod"]] = {"provincia": R.nprov(m["cod"]), "slug": R.PROV[m["cod"]][1], "hechos": hv,
                                         "plantilla": {"titular": f"Sequía cálida en {m['provincia']}: {m['nivel_texto'].lower()} y {f1(m['anomalia'])} °C más que lo normal en {m['mes']}",
                                                       "subtitulo": hv[1]["dice"], "entradilla": hv[0]["dice"], "cuerpo": [hv[1]["dice"]], "claves": [hv[0]["dice"]]},
                                         "cifras": [{"n": f"+{f1(m['anomalia'])} °C", "l": f"sobre la media de {m['mes']} en 1996-2025", "tono": "calor"}], "puntos": 62.0}
        out.append(h)
    md_ = reglas.get("mar_y_dana") or {}
    if md_.get("cumple"):
        quien = "una DANA en curso" if md_["dana_en_curso"] else f"una DANA prevista en los próximos {MAR_DIAS_DANA} días"
        hechos = [R.hecho("md_mar", f"El {larga(md_['mar_ultimo'])} el Mediterráneo occidental estaba a {f1(md_['mar_sst'])} °C, {f1(md_['mar_anomalia'])} °C por encima de lo normal de la fecha.",
                          "NOAA OISST v2.1; cálculo de calentamientoglobal.es", [larga(md_["mar_ultimo"]), f1(md_["mar_sst"]), f1(md_["mar_anomalia"])]),
                  R.hecho("md_dana", f"Coincide con {quien}.", "Catálogo de DANAs y previsión de ECMWF; cálculo de calentamientoglobal.es", [str(MAR_DIAS_DANA)]),
                  R.hecho("md_met", md_["metodo"], "NOAA OISST y ECMWF", [f1(MAR_ANOM_MIN), str(MAR_DIAS_DANA)])]
        pl = {"titular": f"El mar está {f1(md_['mar_anomalia'])} °C por encima de lo normal y hay {quien}: una DANA sobre un mar así tiene más vapor disponible",
              "subtitulo": hechos[0]["dice"], "entradilla": hechos[1]["dice"], "cuerpo": [hechos[2]["dice"], "No es una previsión de lluvia."], "claves": [x["dice"] for x in hechos[:2]]}
        h = R.historia("mar_y_dana", f"{R.HOY.isoformat()}-mar-y-dana", "Análisis · mar caliente y DANA", "lluvia", 60, hechos, pl,
                       [{"n": f"+{f1(md_['mar_anomalia'])} °C", "l": "Mediterráneo occidental sobre lo normal de la fecha", "tono": "calor"}], "NOAA OISST y ECMWF", md_["metodo"],
                       ["No predice lluvias ni su cantidad.", "La previsión de DANA es del modelo de ECMWF, no un aviso de AEMET."], PAG_DANA)
        h["seccion"] = SECCION
        out.append(h)
    for clave, titulo_r in (("nieve_y_embalses", "Poca nieve y embalses bajos"), ("noches_tropicales_en_sequia", "Noches tropicales en sequía")):
        r = reglas.get(clave) or {}
        if r.get("cumple") and r.get("provincias"):
            hs = [x for x in C.get("hallazgos", []) if x.get("indicador") in (clave, "noches_tropicales_sequia")]
            if not hs:
                continue
            hechos = [R.hecho(f"{clave}_{i}", x["dato"], x["fuente"], []) for i, x in enumerate(hs)]
            pl = {"titular": hs[0]["titular"] if len(hs) == 1 else f"{titulo_r} en {len(hs)} provincias", "subtitulo": hechos[0]["dice"], "entradilla": hechos[0]["dice"],
                  "cuerpo": [x["dice"] for x in hechos[1:]], "claves": [x["dice"] for x in hechos[:3]]}
            h = R.historia(clave, f"{R.HOY.isoformat()}-{clave}", f"Análisis · {titulo_r.lower()}", "lluvia", 58, hechos, pl, [], FUENTE_D, r["metodo"], hs[0]["limites"], hs[0]["pagina"])
            h["seccion"] = SECCION
            out.append(h)
    if not out:
        # Hoy no se cumple ninguna regla: la historia lo dice (con lo que pasa en cada una)
        mar = reglas.get("mar_y_dana") or {}
        sc = reglas.get("sequia_calida") or {}
        hechos = [R.hecho("cz_sc", f"El {hoy_txt} ninguna provincia está a la vez en sequía moderada o peor y con el mes al menos {f1(SEQ_ANOM_MIN)} °C por encima de lo normal.", "Monitor de sequía y atribución de calentamientoglobal.es",
                          [hoy_txt, f1(SEQ_ANOM_MIN)])]
        if mar.get("mar_anomalia") is not None:
            hechos.append(R.hecho("cz_mar", f"El Mediterráneo occidental estaba el {larga(mar['mar_ultimo'])} a {f1(mar['mar_anomalia'])} °C de lo normal, sin una DANA en curso ni prevista en los próximos {MAR_DIAS_DANA} días.",
                                  "NOAA OISST y ECMWF", [larga(mar["mar_ultimo"]), f1(mar["mar_anomalia"]), str(MAR_DIAS_DANA)]))
        pl = {"titular": f"Ninguna noticia compuesta el {hoy_txt}: no coinciden sequía, calor, mar caliente y DANA", "subtitulo": hechos[0]["dice"], "entradilla": hechos[0]["dice"],
              "cuerpo": [x["dice"] for x in hechos[1:]], "claves": [x["dice"] for x in hechos]}
        h = R.historia("compuestos_hoy", f"{R.HOY.isoformat()}-compuestos-hoy", "Análisis · cuando se juntan dos cosas", "calor", 20, hechos, pl, [], "Monitor de sequía, NOAA OISST y ECMWF",
                       "Cuatro reglas con umbrales fijos (sequía cálida, mar y DANA, nieve y embalses, noches tropicales en sequía); la historia sale cuando alguna se cumple.", [], PAG_SEQ)
        h["seccion"] = SECCION
        out.append(h)
    return out


def historias(R, D):
    out = _h_compuestos(R, R.HOY)
    for clave in EN_TEMPORADA:
        out += _h_temporada(R, clave, R.HOY)
    return out


# ============================================================================ puente con el detector
_EXTRAS = ("valor", "previo", "empate", "agregado", "miembros_slug")


def _anadir(H, h, indicador):
    """H.anadir() con un id único por indicador (el del detector sale de serie-tipo-territorio-fecha y chocaría entre indicadores)."""
    n0 = len(H.hallazgos)
    H.anadir(h)
    if len(H.hallazgos) > n0:
        x = H.hallazgos[-1]
        x["id"] = f"{x['id']}-{indicador.replace('_', '-')}"
        return x
    return None


def al_detector(H):
    """Lo llama hallazgos_prensa.compuestos(): lee docs/prensa/analisis/compuestos.json, puntúa cada hallazgo con H.anadir() y, cuando ≥ 3
    estaciones o provincias cuentan lo mismo, añade una noticia nacional que los agrupa (los individuales pasan a «locales»)."""
    C = H.leer(SALIDA)
    if (C.get("fecha") or "") < (H.HOY - dt.timedelta(days=2)).isoformat():
        H.errores.append("compuestos: compuestos.json de hace más de 2 días; se ignora")
        return
    nacionales, por_ind = [], {}
    for it in C.get("hallazgos", []):
        if it.get("miembros_slug") is not None:
            nacionales.append(it)
            continue
        x = _anadir(H, {k: v for k, v in it.items() if k not in _EXTRAS}, it["indicador"])
        if x:
            por_ind.setdefault(it["indicador"], []).append((it, x))
    # sequía cálida en varias provincias: la nacional enlaza a las provinciales
    for it in nacionales:
        ids = [h["id"] for _, h in por_ind.get("sequia_calida", [])]
        _anadir(H, {**{k: v for k, v in it.items() if k not in _EXTRAS}, "miembros": ids}, it["indicador"])
    # temporadas: ≥ 3 estaciones con el mismo extremo en el mismo año
    for ind, lista in por_ind.items():
        if not lista or lista[0][0].get("serie") != "temporadas" or len(lista) < 3:
            continue
        plantilla = lista[0][0].get("agregado")
        if not plantilla:
            continue
        anio = H.HOY.year
        lista.sort(key=lambda x: x[0]["territorio"])
        p = lista[0][0]
        _anadir(H, {"serie": "temporadas", "tipo": "temporada", "indicador": ind + "_nacional", "territorio": "España", "ambito": "nacional",
                  "fecha_dato": max(x[0]["fecha_dato"] for x in lista), "provisional": any(x[0].get("provisional") for x in lista),
                  "titular": plantilla.format(n=len(lista), anio=anio),
                  "dato": "; ".join(f"{x[0]['territorio']} {x[0]['valor']} (anterior {x[0]['previo']})" for x in lista) + ".",
                  "contexto": [f"Cada estación se compara con su propia serie diaria validada de AEMET (al menos {MIN_SERIE} años)."],
                  "metodo": p["metodo"], "limites": p["limites"] + ["No es un recuento de toda la red: en otras estaciones de AEMET pudo pasar lo mismo."],
                  "citabilidad": _peor(*[x[0]["citabilidad"] for x in lista]), "exclusivo": True, "fuente": FUENTE_D, "serie_desde": p["serie_desde"],
                  "pagina": "https://calentamientoglobal.es/el-tiempo/", "miembros": [x[1]["id"] for x in lista]}, ind + "_nacional")


# ============================================================================ salida
def calcular(hoy=None):
    hoy = hoy or dt.date.today()
    T = []
    for h in estaciones():
        try:
            r = temporadas_estacion(h)
        except Exception as ex:   # noqa: BLE001
            print(f"temporadas {h.get('slug')}: {type(ex).__name__}: {ex}", file=sys.stderr)
            r = None
        if r:
            T.append(r)
    C = compuestos(hoy)
    C["hallazgos"] += hallazgos_temporadas(T, hoy)
    return T, C


def _plano(o):
    if isinstance(o, dict):
        return {k: _plano(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_plano(v) for v in o]
    if isinstance(o, float):
        return round(o, 3)
    return o


def escribir(T, C, hoy):
    TEMP.mkdir(parents=True, exist_ok=True)
    generado = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    resumen = []
    for e in T:
        e2 = dict(e, generado=generado, licencia=LICENCIA)
        (TEMP / f"{e['slug']}.json").write_text(json.dumps(_plano(e2), ensure_ascii=False, indent=1), encoding="utf-8")
        fila = {"slug": e["slug"], "capital": e["capital"], "provincia": e["provincia"], "ultimo_dato": e["ultimo_dato"], "citabilidad": e["citabilidad"]}
        for k, m in e["metricas"].items():
            fila[k] = {c: (round(v["cambio"], 1) if v else None) for c, v in m.items() if c in ("ini", "fin", "n", "dur")}
            fila[k + "_t"] = {c: (round(v["t"], 2) if v and v.get("t") is not None else None) for c, v in m.items() if c in ("ini", "fin", "n", "dur")}
        resumen.append(fila)
    (TEMP / "index.json").write_text(json.dumps({"generado": generado, "climas": {"antes": list(ANTES), "ahora": list(AHORA)}, "licencia": LICENCIA,
                                                 "n_estaciones": len(T), "estaciones": resumen}, ensure_ascii=False, indent=1), encoding="utf-8")
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(_plano(dict(C, generado=generado)), ensure_ascii=False, indent=1), encoding="utf-8")


def tabla(T):
    print(f"{'capital':24s} {'métrica':20s} {'campo':5s} {'antes':>9s} {'ahora':>9s} {'cambio':>7s} {'t':>6s}  sig")
    for e in T:
        for k, m in e["metricas"].items():
            for c in CAMPOS[k]:
                v = m.get(c)
                if not v or v.get("t") is None:
                    continue
                f = (lambda x: md(x)) if c in ("ini", "fin") else (lambda x: f1(x))
                print(f"{e['capital'][:24]:24s} {k:20s} {c:5s} {f(v['antes']):>9s} {f(v['ahora']):>9s} {v['cambio']:7.1f} {v['t']:6.2f}  {'sí' if v['significativo'] else 'no'}")


def main():
    hoy = dt.date.today()
    T, C = calcular(hoy)
    escribir(T, C, hoy)
    print(f"temporadas: {len(T)} estaciones · compuestos: " + ", ".join(f"{k}={'sí' if r['cumple'] else 'no'}" for k, r in C["reglas"].items())
          + f" · hallazgos {len(C['hallazgos'])}")
    if "--tabla" in sys.argv:
        tabla(T)
    return 0


if __name__ == "__main__":
    sys.exit(main())
