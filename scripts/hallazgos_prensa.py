#!/usr/bin/env python3
"""
Detector de hallazgos para prensa · Observatorio climático (calentamientoglobal.es).

Recorre las series profundas que ya publica el observatorio y busca lo que es
noticia: récords (absolutos y para la fecha), rachas, «primera vez desde»,
puestos extremos en la serie y anomalías fuertes. No mira el dato del día:
mira el dato del día contra toda la serie.

Series que lee (todas en docs/, generadas por otros workflows):
  docs/archivo/NN.json          52 capitales · ERA5 diario desde 1940
  docs/dana/mediterraneo*.json  Mediterráneo occidental · OISST diario desde 1981
  docs/dana/temporada.json      días con DANA · desde 1958
  docs/dias32.json              días >32 °C por provincia · anual desde 1961
  docs/embalses.json + embalses/*.json   MITECO · boletín semanal
  docs/caudal/hoy.json          GloFAS · percentiles por tramo desde 1997
  docs/oceano.json              olas de calor marinas · NOAA CRW
  docs/temperatura_global.json  ERA5 · Climate Pulse

Escribe:
  docs/prensa/hallazgos.json    la cola editorial: hallazgos ordenados por fuerza,
                                con fuente, método, límites, citabilidad y descartes
  docs/prensa/dossier/<id>.md   dossier por hallazgo (con --dossiers)
  docs/prensa/dossier/<id>.png  gráfico de la serie con el punto de hoy
  docs/prensa/dossier/<id>.csv  la serie, para el periodista

Nada se envía solo: este script propone, David decide.
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import sys
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DOCS = RAIZ / "docs"
PRENSA = DOCS / "prensa"
DOSSIER = PRENSA / "dossier"
HOY = date.today()
AHORA = datetime.now(timezone.utc).replace(microsecond=0)

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]

# Código INE de provincia → (nombre, slug de la ficha /cambio-climatico-en-…/)
PROVINCIAS = {
    "01": ("Álava", "alava"), "02": ("Albacete", "albacete"), "03": ("Alicante", "alicante"),
    "04": ("Almería", "almeria"), "05": ("Ávila", "avila"), "06": ("Badajoz", "badajoz"),
    "07": ("Illes Balears", "baleares"), "08": ("Barcelona", "barcelona"), "09": ("Burgos", "burgos"),
    "10": ("Cáceres", "caceres"), "11": ("Cádiz", "cadiz"), "12": ("Castellón", "castellon"),
    "13": ("Ciudad Real", "ciudad-real"), "14": ("Córdoba", "cordoba"), "15": ("A Coruña", "a-coruna"),
    "16": ("Cuenca", "cuenca"), "17": ("Girona", "girona"), "18": ("Granada", "granada"),
    "19": ("Guadalajara", "guadalajara"), "20": ("Gipuzkoa", "gipuzkoa"), "21": ("Huelva", "huelva"),
    "22": ("Huesca", "huesca"), "23": ("Jaén", "jaen"), "24": ("León", "leon"), "25": ("Lleida", "lleida"),
    "26": ("La Rioja", "la-rioja"), "27": ("Lugo", "lugo"), "28": ("Madrid", "madrid"), "29": ("Málaga", "malaga"),
    "30": ("Murcia", "murcia"), "31": ("Navarra", "navarra"), "32": ("Ourense", "ourense"), "33": ("Asturias", "asturias"),
    "34": ("Palencia", "palencia"), "35": ("Las Palmas", "las-palmas"), "36": ("Pontevedra", "pontevedra"),
    "37": ("Salamanca", "salamanca"), "38": ("Santa Cruz de Tenerife", "santa-cruz-de-tenerife"),
    "39": ("Cantabria", "cantabria"), "40": ("Segovia", "segovia"), "41": ("Sevilla", "sevilla"), "42": ("Soria", "soria"),
    "43": ("Tarragona", "tarragona"), "44": ("Teruel", "teruel"), "45": ("Toledo", "toledo"), "46": ("Valencia", "valencia"),
    "47": ("Valladolid", "valladolid"), "48": ("Bizkaia", "bizkaia"), "49": ("Zamora", "zamora"), "50": ("Zaragoza", "zaragoza"),
    "51": ("Ceuta", "ceuta"), "52": ("Melilla", "melilla"),
}

# Fuerza base por tipo de hallazgo (0-100). Después se modula por ámbito,
# exclusividad y frescura.
FUERZA = {
    "record_absoluto": 100, "primera_vez_desde": 90, "record_fecha": 80, "puesto_extremo": 75,
    "racha": 65, "anomalia_fuerte": 55, "percentil_extremo": 50, "contexto": 30,
}
AMBITO_F = {"nacional": 1.0, "regional": 0.9, "provincial": 0.8, "local": 0.7, "global": 0.85}

hallazgos: list[dict] = []
descartes: list[dict] = []
errores: list[str] = []


# ----------------------------------------------------------------------------
# utilidades
# ----------------------------------------------------------------------------
def leer(p: Path):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def num(v, d=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def f2(v) -> str:
    return f"{float(v):.2f}".replace(".", ",")


def f1(v) -> str:
    """1 decimal con coma decimal, sin ceros tontos: 24,9 · 12 · 0,5"""
    v = float(v)
    s = f"{v:.1f}".replace(".", ",")
    return s[:-2] if s.endswith(",0") else s


def fecha_larga(s: str) -> str:
    d = date.fromisoformat(s[:10])
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def fecha_dia(s: str) -> str:
    d = date.fromisoformat(s[:10])
    return f"{d.day} de {MESES[d.month - 1]}"


def dias_desde(s: str) -> int:
    return (HOY - date.fromisoformat(s[:10])).days


def anadir(h: dict):
    """Completa, puntúa y guarda un hallazgo."""
    h.setdefault("limites", [])
    h.setdefault("contexto", [])
    h.setdefault("exclusivo", True)
    h.setdefault("citabilidad", "media")
    h.setdefault("ambito", "provincial")
    frescura = max(0.5, 1 - 0.04 * max(0, dias_desde(h["fecha_dato"]) - 2))  # -4 %/día a partir del 3.º
    fuerza = FUERZA[h["tipo"]] * AMBITO_F[h["ambito"]] * (1.0 if h["exclusivo"] else 0.7) * frescura
    if h["citabilidad"] == "contexto":
        fuerza *= 0.5
    h["fuerza"] = round(fuerza, 1)
    h["requiere_revision"] = any("COMPROBAR" in l for l in h["limites"])
    # slug de la ficha provincial, para que la sala de prensa de cada provincia
    # encuentre lo suyo sin adivinar nombres
    nombre_prov = h.get("provincia") or (h["territorio"] if h.get("ambito") == "provincial" else None)
    if nombre_prov:
        for cod, (nom, slug) in PROVINCIAS.items():
            if nom == nombre_prov:
                h["provincia_slug"] = slug
                break
    crudo = unicodedata.normalize("NFKD", f"{h['serie']}-{h['tipo']}-{h['territorio']}-{h['fecha_dato']}").encode("ascii", "ignore").decode()
    h["id"] = re.sub(r"[^a-z0-9]+", "-", crudo.lower()).strip("-")
    hallazgos.append(h)


def descartar(serie: str, territorio: str, motivo: str, dato: str = ""):
    descartes.append({"serie": serie, "territorio": territorio, "motivo": motivo, "dato": dato})


# ----------------------------------------------------------------------------
# 1 · Archivo de las capitales · ERA5 desde 1940
# ----------------------------------------------------------------------------
def capitales():
    ficheros = sorted(glob.glob(str(DOCS / "archivo" / "[0-9][0-9].json")))
    for fp in ficheros:
        try:
            _capital(leer(Path(fp)))
        except Exception as e:
            errores.append(f"archivo {Path(fp).name}: {e}")


def _capital(a: dict):
    cod = a["cod"]
    prov, slug = PROVINCIAS.get(cod, (a["capital"], cod))
    cap = a["capital"]
    desde = a["desde"][:4]
    ultimo = a["ultimo"]
    pagina = f"https://calentamientoglobal.es/cambio-climatico-en-{slug}/"
    base = {
        "serie": "capitales", "fuente": a["fuente"], "serie_desde": desde,
        "territorio": cap, "provincia": prov, "pagina": pagina,
        "metodo": f"Reanálisis ERA5 (Copernicus/ECMWF) en la celda de {cap}, serie diaria desde {desde}; "
                  f"récords calculados día del año a día del año sobre toda la serie.",
        "limites": ["Reanálisis en una celda de ~10 km, no la estación oficial de AEMET: la cifra de AEMET puede diferir.",
                    "ERA5 consolida con unos seis días de retraso; los últimos días son preliminares."],
        "citabilidad": "media",
    }
    rec = a["records"]
    u = a["ult30"]
    fechas, tx, tn, ll = u["f"], u["tx"], u["tn"], u["ll"]
    ntx, ntn = u["ntx"], u["ntn"]
    n_anios = int(ultimo[:4]) - int(desde) + 1

    # --- récord para la fecha (últimos 10 días de la serie) ---------------------
    for i in range(max(0, len(fechas) - 10), len(fechas)):
        f = fechas[i]
        mmdd = f[5:7] + f[8:10]
        r = rec.get(mmdd)
        if not r or len(r) < 10:
            continue
        anio = int(f[:4])
        # [txmax, año, tnmin, año, txmin, año, tnmax, año, llmax, año]
        if r[1] == anio and tx[i] is not None and abs(tx[i] - r[0]) < 0.051:
            anadir({**base, "tipo": "record_fecha", "fecha_dato": f, "indicador": "tmax",
                    "titular": f"{cap} marcó el {fecha_dia(f)} su máxima más alta para esa fecha desde {desde}: {f1(tx[i])} °C",
                    "dato": f"{f1(tx[i])} °C · normal para la fecha {f1(ntx[i])} °C",
                    "contexto": [f"Serie de {n_anios} años ({desde}-{ultimo[:4]}).",
                                 f"Normal 1991-2020 para ese día: {f1(ntx[i])} °C (+{f1(tx[i] - ntx[i])} °C)."]})
        if r[7] == anio and tn[i] is not None and abs(tn[i] - r[6]) < 0.051:
            anadir({**base, "tipo": "record_fecha", "fecha_dato": f, "indicador": "tmin_alta",
                    "titular": f"{cap} tuvo el {fecha_dia(f)} la noche más cálida para esa fecha desde {desde}: mínima de {f1(tn[i])} °C",
                    "dato": f"mínima {f1(tn[i])} °C · normal {f1(ntn[i])} °C",
                    "contexto": [f"Serie de {n_anios} años.", f"Normal 1991-2020 para ese día: {f1(ntn[i])} °C."]})
        if r[3] == anio and tn[i] is not None and abs(tn[i] - r[2]) < 0.051:
            anadir({**base, "tipo": "record_fecha", "fecha_dato": f, "indicador": "tmin_baja",
                    "titular": f"{cap} registró el {fecha_dia(f)} su mínima más baja para esa fecha desde {desde}: {f1(tn[i])} °C",
                    "dato": f"mínima {f1(tn[i])} °C · normal {f1(ntn[i])} °C"})
        if r[9] == anio and ll[i] is not None and ll[i] >= 10 and abs(ll[i] - r[8]) < 0.051:
            anadir({**base, "tipo": "record_fecha", "fecha_dato": f, "indicador": "lluvia",
                    "titular": f"{cap} recogió el {fecha_dia(f)} {f1(ll[i])} mm, la mayor lluvia para esa fecha desde {desde}",
                    "dato": f"{f1(ll[i])} mm en un día",
                    "limites": base["limites"] + ["La lluvia de ERA5 es una media de celda: el pluviómetro local puede dar más o menos."]})

    # --- rachas de anomalía (días seguidos ≥ +5 °C / ≤ −5 °C sobre lo normal) --------
    for ind, serie, normal, signo, etiqueta in (
        ("tmax", tx, ntx, +1, "máximas"), ("tmin", tn, ntn, +1, "mínimas"),
        ("tmax", tx, ntx, -1, "máximas"),
    ):
        n = 0
        for i in range(len(fechas) - 1, -1, -1):
            if serie[i] is None or normal[i] is None:
                break
            if signo * (serie[i] - normal[i]) >= 5:
                n += 1
            else:
                break
        if n >= 5:
            med = sum(serie[i] - normal[i] for i in range(len(fechas) - n, len(fechas))) / n
            calor = signo > 0
            anadir({**base, "tipo": "racha", "fecha_dato": ultimo, "indicador": f"racha_{ind}",
                    "titular": f"{cap} encadena {n} días con {etiqueta} {'más de 5 °C por encima' if calor else 'más de 5 °C por debajo'} de lo normal",
                    "dato": f"{n} días seguidos · desviación media {'+' if med > 0 else ''}{f1(med)} °C",
                    "contexto": [f"Del {fecha_dia(fechas[-n])} al {fecha_dia(ultimo)}.",
                                 "Normal de referencia: 1991-2020, día a día."]})

    # --- lluvia: mes, año y otoño frente a toda la serie ---------------------------
    L = a.get("lluvia", {})
    m = L.get("mes", {})
    if m and num(m.get("mm"), 0) >= 25 and num(m.get("pct"), 0) >= 250:
        dia = date.fromisoformat(ultimo).day
        anadir({**base, "tipo": "anomalia_fuerte", "fecha_dato": ultimo, "indicador": "lluvia_mes",
                "titular": f"{cap} ya ha recogido en {dia} días de {MESES[m['m'] - 1]} el {int(round(100 * m['mm'] / m['normal_mes']))} % de la lluvia de todo un {MESES[m['m'] - 1]} normal",
                "dato": f"{f1(m['mm'])} mm hasta el día {dia} · normal hasta hoy {f1(m['normal'])} mm · normal del mes completo {f1(m['normal_mes'])} mm",
                "contexto": [f"{m['pct']} % de lo normal para estas fechas del mes."]})
    for clave, nombre_periodo in (("anio", "año"), ("otonio", "otoño")):
        p = L.get(clave)
        if not p or p.get("puesto_seco") is None:
            continue
        puesto, de = int(p["puesto_seco"]), int(p["de"])
        periodo_txt = (f"lo que va de {p['a']}" if clave == "anio"
                       else f"el otoño hasta el {fecha_dia(p['hasta'])}")
        if puesto <= 3:
            tipo = "record_absoluto" if puesto == 1 else "puesto_extremo"
            anadir({**base, "tipo": tipo, "fecha_dato": ultimo, "indicador": f"lluvia_{clave}_seco",
                    "titular": (f"{cap} vive el {nombre_periodo} más seco desde {desde}: {f1(p['mm'])} mm, el {p['pct']} % de lo normal"
                                if puesto == 1 else
                                f"{cap} vive el {puesto}.º {nombre_periodo} más seco desde {desde}: {f1(p['mm'])} mm, el {p['pct']} % de lo normal"),
                    "dato": f"{f1(p['mm'])} mm en {periodo_txt} · normal {f1(p['normal'])} mm · puesto {puesto} de {de}",
                    "contexto": [f"El más seco de la serie: {p['mas_seco'][0]} con {f1(p['mas_seco'][1])} mm.",
                                 f"El más lluvioso: {p['mas_lluvioso'][0]} con {f1(p['mas_lluvioso'][1])} mm."]})
        elif puesto >= de - 2:
            r = de - puesto + 1
            tipo = "record_absoluto" if r == 1 else "puesto_extremo"
            anadir({**base, "tipo": tipo, "fecha_dato": ultimo, "indicador": f"lluvia_{clave}_humedo",
                    "titular": (f"{cap} vive el {nombre_periodo} más lluvioso desde {desde}: {f1(p['mm'])} mm, el {p['pct']} % de lo normal"
                                if r == 1 else
                                f"{cap} vive el {r}.º {nombre_periodo} más lluvioso desde {desde}: {f1(p['mm'])} mm, el {p['pct']} % de lo normal"),
                    "dato": f"{f1(p['mm'])} mm en {periodo_txt} · normal {f1(p['normal'])} mm · puesto {r} de {de} por lluvia",
                    "contexto": [f"El más lluvioso de la serie: {p['mas_lluvioso'][0]} con {f1(p['mas_lluvioso'][1])} mm."]})

    # --- días de más de 32 °C este año frente a lo normal --------------------------
    c = a.get("cambio", {})
    e = c.get("este_anio", {})
    if e and num(e.get("d32"), 0) >= 15 and num(e.get("d32_normal"), 0) > 0 and e["d32"] / e["d32_normal"] >= 2.5:
        anadir({**base, "tipo": "anomalia_fuerte", "fecha_dato": ultimo, "indicador": "d32_anio",
                "titular": f"{cap} lleva {e['d32']} días de más de 32 °C en {ultimo[:4]}, {f1(e['d32'] / e['d32_normal'])} veces su normal",
                "dato": f"{e['d32']} días · normal 1991-2020: {f1(e['d32_normal'])}",
                "contexto": [f"Media 1951-1980: {c.get('d32_antes')} días al año · media 1996-2025: {c.get('d32_ahora')}."]})


# ----------------------------------------------------------------------------
# 2 · Mediterráneo occidental · OISST desde 1981
# ----------------------------------------------------------------------------
def mediterraneo():
    try:
        m = leer(DOCS / "dana" / "mediterraneo.json")
        h = leer(DOCS / "dana" / "mediterraneo_historico.json")
    except Exception as e:
        errores.append(f"mediterraneo: {e}")
        return
    serie = h["v"]  # {fecha: sst}
    ultimo = m["ultimo"]
    sst, normal, anom = num(m["sst"]), num(m["normal"]), num(m["anomalia"])
    base = {
        "serie": "mediterraneo", "fuente": m["fuente"], "serie_desde": "1981", "territorio": "Mediterráneo occidental",
        "ambito": "nacional", "pagina": "https://calentamientoglobal.es/dana/",
        "metodo": "Temperatura superficial del mar NOAA OISST v2.1 (0,25°), media diaria de la caja 36,5-41,5° N / 1,5° O-5° E "
                  "(de Alborán oriental al mar Balear). Normal 1991-2020 por día del año; récord para la fecha sobre 1981-2025.",
        "limites": ["Los últimos ~14 días de OISST son la versión preliminar (NRT); la final puede variar unas décimas.",
                    "Media de una caja de mar abierto, no la temperatura de una playa concreta."],
        "citabilidad": "alta",
    }
    anio = int(ultimo[:4])
    # máximos históricos por día del año, excluyendo el año en curso
    maximo_fecha: dict[str, tuple[float, int]] = {}
    maximo_abs = (-99.0, "")
    for f, v in serie.items():
        if v > maximo_abs[0]:
            maximo_abs = (v, f)  # máximo de TODA la serie, año en curso incluido
        if int(f[:4]) >= anio:
            continue
        k = f[5:]
        if k not in maximo_fecha or v > maximo_fecha[k][0]:
            maximo_fecha[k] = (v, int(f[:4]))
    # días del año en curso en récord y racha final
    actual = sorted((f, v) for f, v in serie.items() if int(f[:4]) == anio)
    en_record = [(f, v) for f, v in actual if f[5:] in maximo_fecha and v > maximo_fecha[f[5:]][0]]
    racha = 0
    for f, v in reversed(actual):
        if f[5:] in maximo_fecha and v > maximo_fecha[f[5:]][0]:
            racha += 1
        else:
            break
    rec_prev = maximo_fecha.get(ultimo[5:])
    if racha >= 1 and rec_prev:
        margen = sst - rec_prev[0]
        titular = (f"El Mediterráneo español lleva {racha} días seguidos en récord de temperatura para la fecha: {f2(sst)} °C el {fecha_dia(ultimo)}"
                   if racha >= 3 else
                   f"El Mediterráneo español marcó el {fecha_dia(ultimo)} su temperatura más alta para esa fecha desde 1981: {f2(sst)} °C")
        anadir({**base, "tipo": "racha" if racha >= 3 else "record_fecha", "fecha_dato": ultimo, "indicador": "sst_record_fecha",
                "titular": titular,
                "dato": f"{f2(sst)} °C · récord anterior para la fecha {f2(rec_prev[0])} °C ({rec_prev[1]}) · normal 1991-2020 {f2(normal)} °C (+{f2(anom)})",
                "contexto": [f"{len(en_record)} días de {anio} han sido récord para su fecha.",
                             f"Máximo absoluto de la serie: {f2(maximo_abs[0])} °C el {fecha_larga(maximo_abs[1])}.",
                             f"Hoy el mar está como corresponde a un {_fecha_equivalente(m, sst)} normal."],
                "racha": racha})
    elif rec_prev:
        descartar("mediterraneo", "Mediterráneo occidental", "no está en récord para la fecha",
                  f"{f1(sst)} °C frente a {f1(rec_prev[0])} °C ({rec_prev[1]}); puesto {m.get('puesto_para_la_fecha')} de {m.get('de')}")
    # anomalía fuerte sin récord
    if anom is not None and anom >= 2 and racha == 0:
        anadir({**base, "tipo": "anomalia_fuerte", "fecha_dato": ultimo, "indicador": "sst_anomalia",
                "titular": f"El Mediterráneo español está {f1(anom)} °C por encima de lo normal para un {fecha_dia(ultimo)}: {f1(sst)} °C",
                "dato": f"{f1(sst)} °C · normal {f1(normal)} °C · p90 para la fecha {f1(num(m['p90']))} °C",
                "contexto": [f"Puesto {m.get('puesto_para_la_fecha')} de {m.get('de')} años para la fecha."]})


def _fecha_equivalente(m: dict, sst: float) -> str:
    """A qué día del año corresponde esta temperatura en la climatología (enfriamiento de otoño)."""
    try:
        clim = m["clim"] if isinstance(m["clim"], list) else json.loads(m["clim"].replace("'", '"'))
        mejor = min(((abs(c[1] - sst), c[0]) for c in clim if c[0] < date.fromisoformat(m["ultimo"]).strftime("%m-%d")), default=None)
        if mejor:
            mm, dd = mejor[1].split("-")
            return f"{int(dd)} de {MESES[int(mm) - 1]}"
    except Exception:
        pass
    return "día de finales de verano"


# ----------------------------------------------------------------------------
# 3 · Temporada de DANAs · desde 1958
# ----------------------------------------------------------------------------
def danas():
    try:
        t = leer(DOCS / "dana" / "temporada.json")
    except Exception as e:
        errores.append(f"danas: {e}")
        return
    a = t["anio_hasta_hoy"] if isinstance(t["anio_hasta_hoy"], dict) else json.loads(str(t["anio_hasta_hoy"]).replace("'", '"'))
    base = {"serie": "danas", "fuente": t["fuente"], "serie_desde": "1958", "territorio": "España", "ambito": "nacional",
            "pagina": "https://calentamientoglobal.es/dana/", "metodo": t["definicion"],
            "limites": ["Detector propio sobre reanálisis: cuenta días con una baja aislada en 500 hPa, no episodios con daños.",
                        "Desde marzo de 2026 la fuente es el análisis del ECMWF; el empalme con NCEP no está calibrado todavía.",
                        "No contradecir nunca un aviso especial de AEMET con este dato."],
            "citabilidad": "contexto", "exclusivo": True}
    if a.get("puesto") and int(a["puesto"]) <= 5:
        anadir({**base, "tipo": "puesto_extremo", "fecha_dato": t["ultimo_dato"], "indicador": "dias_dana_anio",
                "titular": f"{t['anio']} lleva {a['dias']} días con DANA sobre España, el {a['puesto']}.º año con más desde 1958",
                "dato": f"{a['dias']} días · {a['episodios']} episodios · media 1991-2020 hasta esta fecha: {a['media_1991_2020']}",
                "contexto": [f"Máximo de la serie hasta esta fecha: {a['max'][0]} días en {a['max'][1]}.",
                             f"Tendencia: +{t.get('tendencia_dias_decada')} días por década."]})


# ----------------------------------------------------------------------------
# 4 · Días de más de 32 °C por provincia · desde 1961
# ----------------------------------------------------------------------------
def dias32():
    try:
        d = leer(DOCS / "dias32.json")
    except Exception as e:
        errores.append(f"dias32: {e}")
        return
    anio = int(d["actualizado"][:4])
    for p in d["provincias"]:
        actual = int(num(p["actual"], 0))
        hist = [(int(y), int(n)) for y, n in p["hist"]]
        # El generador etiqueta el año en curso con el último año de la lista
        # (coincide con «actual»): se saca de la serie histórica para no comparar
        # el año consigo mismo.
        etiqueta_en_curso = None
        if hist and hist[-1][1] == actual:
            etiqueta_en_curso = hist[-1][0]
            hist = hist[:-1]
        hist = [(y, n) for y, n in hist if y < anio]
        if not hist or actual < 20:
            continue
        orden = sorted(hist, key=lambda x: -x[1])
        puesto = 1 + sum(1 for _, n in hist if n > actual)
        base = {"serie": "dias32", "fuente": d["fuente"], "serie_desde": str(hist[0][0]), "territorio": p["prov"],
                "pagina": "https://calentamientoglobal.es/cambio-climatico-por-provincias/",
                "metodo": f"Días con máxima ≥ {d.get('umbral', 32)} °C en el punto de referencia de la provincia, ERA5 vía Open-Meteo, "
                          f"contados por año natural desde {hist[0][0]}.",
                "limites": ["Un punto por provincia (reanálisis), no la red de estaciones de AEMET.",
                            f"El año {anio} no ha terminado: la cifra puede subir si hay más días de 32 °C."]
                           + ([f"COMPROBAR antes de enviar: dias32.json etiqueta el año en curso como {etiqueta_en_curso}; confirmar en dias32_generar.py que el conteo es de {anio}."] if etiqueta_en_curso and etiqueta_en_curso != anio else []),
                "citabilidad": "media"}
        if puesto == 1:
            anadir({**base, "tipo": "record_absoluto", "fecha_dato": d["actualizado"][:10], "indicador": "d32",
                    "titular": f"{p['prov']} suma {actual} días de más de 32 °C en {anio}, más que en ningún año desde {hist[0][0]}",
                    "dato": f"{actual} días · anterior máximo {orden[0][1]} ({orden[0][0]}) · media 1991-2020: {f1(num(p['media_9120']))}",
                    "contexto": [f"Media 1961-1990: {f1(num(p['media_6190']))} días; 1991-2020: {f1(num(p['media_9120']))}."]})
        elif puesto <= 3:
            anadir({**base, "tipo": "puesto_extremo", "fecha_dato": d["actualizado"][:10], "indicador": "d32",
                    "titular": f"{p['prov']} suma {actual} días de más de 32 °C en {anio}, el {puesto}.º año con más desde {hist[0][0]}",
                    "dato": f"{actual} días · máximo {orden[0][1]} ({orden[0][0]}) · media 1991-2020: {f1(num(p['media_9120']))}",
                    "contexto": [f"Media 1961-1990: {f1(num(p['media_6190']))} días."]})


# ----------------------------------------------------------------------------
# 5 · Embalses · MITECO (dato oficial, no exclusivo: vale como contexto o con ángulo)
# ----------------------------------------------------------------------------
def embalses():
    try:
        n = leer(DOCS / "embalses.json")
    except Exception as e:
        errores.append(f"embalses: {e}")
        return
    bol = n["boletin_fecha"]
    nac = n["nacional"]
    pct, p1a, p10 = num(nac["pct"]), num(nac["pct_hace_1a"]), num(nac["pct_media_10a"])
    base = {"serie": "embalses", "fuente": n["fuente"], "serie_desde": "1988", "territorio": "España", "ambito": "nacional",
            "pagina": "https://calentamientoglobal.es/embalses-espana/",
            "metodo": "Boletín Hidrológico Semanal del MITECO; media de diez años calculada para la misma semana del año.",
            "limites": ["Dato oficial del MITECO que publica cualquier medio: el valor está en el ángulo (comparación y contexto), no en la cifra."],
            "citabilidad": "alta", "exclusivo": False}
    if pct is not None and p10 is not None and abs(pct - p10) >= 10:
        anadir({**base, "tipo": "anomalia_fuerte", "fecha_dato": bol, "indicador": "reserva_nacional",
                "titular": f"La reserva de agua de España está al {f1(pct)} %, {f1(abs(pct - p10))} puntos {'por encima' if pct > p10 else 'por debajo'} de su media de diez años para esta semana",
                "dato": f"{f1(pct)} % ({nac['volumen_total_hm3']} de {nac['capacidad_total_hm3']} hm³) · hace un año {f1(p1a)} % · media 10 años {f1(p10)} %",
                "contexto": [f"Boletín del {fecha_larga(bol)}."]})
    # provincias: distancia grande a la media de 10 años o a hace un año
    for fp in sorted(glob.glob(str(DOCS / "embalses" / "*.json"))):
        if Path(fp).name in ("diagnostico.json",) or "/fichas/" in fp:
            continue
        try:
            e = leer(Path(fp))
        except Exception:
            continue
        if "provincia" not in e or "pct" not in e:
            continue
        pct, p1a, p10 = num(e["pct"]), num(e.get("pct_hace_1a")), num(e.get("pct_media_10a"))
        if pct is None or p10 is None or int(num(e.get("total_embalses"), 0)) < 2:
            continue
        slug = Path(fp).stem.replace("_", "-").replace("ñ", "n")
        b = {**base, "ambito": "provincial", "territorio": e["provincia"],
             "pagina": f"https://calentamientoglobal.es/embalses-{slug}/"}
        if abs(pct - p10) >= 20:
            anadir({**b, "tipo": "anomalia_fuerte", "fecha_dato": bol, "indicador": "reserva_provincial",
                    "titular": f"Los embalses de {e['provincia']} están al {f1(pct)} %, {f1(abs(pct - p10))} puntos {'por encima' if pct > p10 else 'por debajo'} de su media de diez años",
                    "dato": f"{f1(pct)} % ({e.get('volumen_total_hm3')} de {e.get('capacidad_total_hm3')} hm³, {e.get('total_embalses')} embalses) · hace un año {f1(p1a) if p1a is not None else '—'} % · media 10 años {f1(p10)} %"})
        elif p1a is not None and abs(pct - p1a) >= 25:
            anadir({**b, "tipo": "anomalia_fuerte", "fecha_dato": bol, "indicador": "reserva_provincial_1a",
                    "titular": f"Los embalses de {e['provincia']} tienen {f1(abs(pct - p1a))} puntos {'más' if pct > p1a else 'menos'} de agua que hace un año: {f1(pct)} % frente a {f1(p1a)} %",
                    "dato": f"{f1(pct)} % · hace un año {f1(p1a)} % · media 10 años {f1(p10)} %"})


# ----------------------------------------------------------------------------
# 6 · Caudal de los ríos · GloFAS (modelo: contexto)
# ----------------------------------------------------------------------------
def caudal():
    try:
        h = leer(DOCS / "caudal" / "hoy.json")
        r = leer(DOCS / "caudal" / "red.json")
    except Exception as e:
        errores.append(f"caudal: {e}")
        return
    import base64
    n_dias, n_pts = int(h["n"]), len(h["puntos"])
    b = base64.b64decode(h["pct"])
    hoy_i = int(h["hoy"])
    nombres = {p["id"]: p for p in r["puntos"]}
    # el byte [punto*n_dias + dia] es el percentil (0-100, 255 = sin dato)
    secos = humedos = total = 0
    for p in range(n_pts):
        v = b[p * n_dias + hoy_i] if p * n_dias + hoy_i < len(b) else 255
        if v == 255:
            continue
        total += 1
        secos += v < 10
        humedos += v > 90
    if total == 0:
        return
    res = h.get("resumen", {})
    base = {"serie": "caudal", "fuente": h["fuente"], "serie_desde": "1997", "territorio": "España", "ambito": "nacional",
            "pagina": "https://calentamientoglobal.es/caudal-rios-espana-mapa/",
            "metodo": "Caudal simulado por GloFAS v4 en ~300 tramos, comparado con los percentiles de su época del año (1997-2025).",
            "limites": ["Caudal simulado, no medido: en ríos regulados puede diferir del aforo real.",
                        "Útil para contexto de sequía hidrológica o crecida; no para una cifra de portada."],
            "citabilidad": "contexto"}
    for cond, pct_, tipo_txt in ((humedos / total >= 0.3, humedos, "más agua de la habitual (percentil >90)"),
                                 (secos / total >= 0.3, secos, "muy por debajo de lo habitual (percentil <10)")):
        if cond:
            anadir({**base, "tipo": "percentil_extremo", "fecha_dato": h["emitida"], "indicador": "caudal_red",
                    "titular": f"{int(round(100 * pct_ / total))} % de la red fluvial española lleva {tipo_txt} para la fecha",
                    "dato": f"{pct_} de {total} tramos · cuenca más seca: {res.get('cuenca_seca')} · más húmeda: {res.get('cuenca_humeda')}"})


# ----------------------------------------------------------------------------
# 7 · Olas de calor marinas y temperatura global (contexto)
# ----------------------------------------------------------------------------
def planeta():
    try:
        o = leer(DOCS / "oceano.json")
        g = o["global"] if isinstance(o["global"], dict) else json.loads(str(o["global"]).replace("'", '"'))
        if g.get("racha_dias") and g.get("record_racha") and g["racha_dias"] >= g["record_racha"] and g["racha_dias"] >= 60:
            anadir({"serie": "oceano", "fuente": o["fuente"], "serie_desde": "2025", "territorio": "Océano global", "ambito": "global",
                    "pagina": "https://calentamientoglobal.es/mapa-en-tiempo-real-ola-de-calor-marino/",
                    "tipo": "racha", "fecha_dato": o["fecha"], "indicador": "mhw_racha",
                    "titular": f"El océano lleva {g['racha_dias']} días seguidos con más de la mitad de su superficie en ola de calor marina",
                    "dato": f"{g['pct_en_mhw']} % de la superficie en ola de calor el {fecha_dia(o['fecha'])} · racha {g['racha_dias']} días",
                    "metodo": "NOAA Coral Reef Watch: porcentaje de la superficie oceánica en categoría ≥1 de ola de calor marina.",
                    "limites": ["Serie propia desde abril de 2025: la racha es récord de nuestra serie, no de la historia."],
                    "citabilidad": "contexto", "exclusivo": False})
    except Exception as e:
        errores.append(f"oceano: {e}")
    try:
        t = leer(DOCS / "temperatura_global.json")
        a = t["anyo_en_curso"] if isinstance(t["anyo_en_curso"], dict) else json.loads(str(t["anyo_en_curso"]).replace("'", '"'))
        if a.get("puesto") and int(a["puesto"]) <= 2:
            anadir({"serie": "temperatura_global", "fuente": t["fuente"], "serie_desde": "1940", "territorio": "Planeta", "ambito": "global",
                    "pagina": "https://calentamientoglobal.es/temperatura-del-planeta/",
                    "tipo": "puesto_extremo", "fecha_dato": t["fecha_dato"], "indicador": "tglobal_anio",
                    "titular": f"{a['anyo']} va camino de ser el {a['puesto']}.º año más cálido de la serie: +{f1(a['media_preindustrial'])} °C sobre la era preindustrial",
                    "dato": f"{a['dias']} días · anomalía media +{f1(a['media_preindustrial'])} °C (preindustrial) · {t.get('dias_sobre_15_ultimo_anyo')} días sobre +1,5 °C en el último año",
                    "metodo": "ERA5 (C3S/ECMWF) vía Climate Pulse; anomalía frente a 1850-1900.",
                    "limites": ["Dato de Copernicus que publica todo el mundo: solo sirve como contexto."],
                    "citabilidad": "contexto", "exclusivo": False})
    except Exception as e:
        errores.append(f"temperatura_global: {e}")


# ----------------------------------------------------------------------------
# agregación: si muchos territorios cuentan lo mismo, la noticia es nacional
# ----------------------------------------------------------------------------
def agregar():
    grupos: dict[tuple, list[dict]] = {}
    for h in hallazgos:
        if h["ambito"] != "provincial":
            continue
        clave = None
        if h["serie"] == "dias32" and h["tipo"] == "record_absoluto":
            clave = ("dias32_record", h["fecha_dato"][:4])
        elif h["serie"] == "capitales" and h["tipo"] == "record_fecha":
            clave = ("capitales_" + h["indicador"], h["fecha_dato"])
        elif h["serie"] == "capitales" and h["tipo"] in ("record_absoluto", "puesto_extremo"):
            clave = ("capitales_" + h["indicador"], h["fecha_dato"][:4])
        if clave:
            grupos.setdefault(clave, []).append(h)
    for (clave, cuando), lista in grupos.items():
        if len(lista) < 3:
            continue
        lista.sort(key=lambda h: h["territorio"])
        nombres = ", ".join(h["territorio"] for h in lista[:-1]) + " y " + lista[-1]["territorio"]
        p = lista[0]
        n = len(lista)
        if clave == "dias32_record":
            titular = f"{n} provincias baten en {cuando} su récord de días de más de 32 °C desde 1961"
            dato = "; ".join(f"{h['territorio']} {h['dato'].split(' días')[0]}" for h in sorted(lista, key=lambda h: -int(h["dato"].split(" ")[0])))
            tipo = "record_absoluto"
        elif clave.startswith("capitales_tmin_alta"):
            titular = f"{n} capitales españolas vivieron el {fecha_dia(cuando)} su noche más cálida para esa fecha desde 1940"
            dato = "; ".join(f"{h['territorio']} {h['dato'].split(' °C')[0].replace('mínima ', '')} °C" for h in lista)
            tipo = "record_fecha"
        elif clave.startswith("capitales_tmax"):
            titular = f"{n} capitales españolas marcaron el {fecha_dia(cuando)} su máxima más alta para esa fecha desde 1940"
            dato = "; ".join(f"{h['territorio']} {h['dato'].split(' °C')[0]} °C" for h in lista)
            tipo = "record_fecha"
        elif clave.startswith("capitales_tmin_baja"):
            titular = f"{n} capitales españolas registraron el {fecha_dia(cuando)} su mínima más baja para esa fecha desde 1940"
            dato = "; ".join(f"{h['territorio']} {h['dato'].split(' °C')[0].replace('mínima ', '')} °C" for h in lista)
            tipo = "record_fecha"
        elif clave.startswith("capitales_lluvia_") and clave.endswith("_seco"):
            periodo = "año" if "anio" in clave else "otoño"
            titular = f"{n} capitales viven uno de los tres {periodo}s más secos desde 1940"
            dato = "; ".join(f"{h['territorio']} ({h['dato'].split('·')[-1].strip()})" for h in lista)
            tipo = "puesto_extremo"
        elif clave.startswith("capitales_lluvia_") and clave.endswith("_humedo"):
            periodo = "año" if "anio" in clave else "otoño"
            titular = f"{n} capitales viven uno de los tres {periodo}s más lluviosos desde 1940"
            dato = "; ".join(f"{h['territorio']} ({h['dato'].split('·')[-1].strip()})" for h in lista)
            tipo = "puesto_extremo"
        else:
            continue
        anadir({"serie": p["serie"], "fuente": p["fuente"], "serie_desde": p["serie_desde"], "territorio": "España",
                "ambito": "nacional", "pagina": p["pagina"] if p["serie"] == "dias32" else "https://calentamientoglobal.es/el-tiempo/",
                "tipo": tipo, "fecha_dato": p["fecha_dato"], "indicador": clave + "_nacional",
                "titular": titular, "dato": dato,
                "contexto": [f"Territorios: {nombres}.", f"Cada uno comparado contra su propia serie desde {p['serie_desde']}."],
                "metodo": re.sub(r"en la celda de [^,]+,", "en la celda de cada capital,", p["metodo"]),
                "limites": p["limites"], "citabilidad": p["citabilidad"],
                "miembros": [h["id"] for h in lista]})


# ----------------------------------------------------------------------------
# dossiers
# ----------------------------------------------------------------------------
def dossiers(top: list[dict]):
    DOSSIER.mkdir(parents=True, exist_ok=True)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        plt = None
    for h in top:
        try:
            _dossier(h, plt)
        except Exception as e:
            errores.append(f"dossier {h['id']}: {e}")


def _dossier(h: dict, plt):
    serie = _serie_para(h) if not h.get("miembros") else None
    if serie:
        with open(DOSSIER / f"{h['id']}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(serie["cabecera"])
            w.writerows(serie["filas"])
        h["csv"] = f"prensa/dossier/{h['id']}.csv"
        if plt and serie.get("plot"):
            serie["plot"](plt, DOSSIER / f"{h['id']}.png", h)
            h["grafico"] = f"prensa/dossier/{h['id']}.png"
    md = [f"# {h['titular']}", "",
          f"**Dato:** {h['dato']}  ", f"**Fecha del dato:** {fecha_larga(h['fecha_dato'])}  ",
          f"**Ámbito:** {h['ambito']} · **Territorio:** {h['territorio']}  ",
          f"**Citabilidad:** {h['citabilidad']} · **Exclusivo:** {'sí' if h['exclusivo'] else 'no (dato oficial que publica cualquiera)'}", ""]
    if h.get("contexto"):
        md += ["## Contexto", *[f"- {c}" for c in h["contexto"]], ""]
    if h.get("miembros"):
        por_id = {x["id"]: x for x in hallazgos}
        md += ["## Territorio a territorio", "", "| Territorio | Dato | Dossier local |", "|---|---|---|"]
        for mid in h["miembros"]:
            x = por_id.get(mid)
            if x:
                md.append(f"| {x['territorio']} | {x['dato']} | [{mid}](https://davidbebow.github.io/temperaturas-mar-espana/prensa/dossier/{mid}.md) |")
        md.append("")
    md += ["## Fuente y método", f"- **Fuente:** {h['fuente']}", f"- **Serie desde:** {h['serie_desde']}",
           f"- **Método:** {h['metodo']}", ""]
    if h.get("limites"):
        md += ["## Límites (decirlos antes de que los descubran)", *[f"- {l}" for l in h["limites"]], ""]
    md += ["## Enlaces", f"- Página: {h['pagina']}"]
    if h.get("csv"):
        md.append(f"- Serie (CSV): https://davidbebow.github.io/temperaturas-mar-espana/{h['csv']}")
    if h.get("grafico"):
        md.append(f"- Gráfico: https://davidbebow.github.io/temperaturas-mar-espana/{h['grafico']}")
    md += ["",
           "## Atribución", "Observatorio climático de calentamientoglobal.es, a partir de " + h["fuente"] +
           ". Cálculo propio reutilizable con CC BY 4.0 citando a CalentamientoGlobal.es; los datos de origen conservan la licencia de su organismo.", ""]
    h["dossier"] = f"prensa/dossier/{h['id']}.md"
    (DOSSIER / f"{h['id']}.md").write_text("\n".join(md), encoding="utf-8")


def _serie_para(h: dict) -> dict | None:
    if h["serie"] == "mediterraneo":
        hist = leer(DOCS / "dana" / "mediterraneo_historico.json")["v"]
        m = leer(DOCS / "dana" / "mediterraneo.json")
        anio = int(h["fecha_dato"][:4])
        rec = {}
        for f, v in hist.items():
            if int(f[:4]) < anio:
                k = f[5:]
                if k not in rec or v > rec[k][0]:
                    rec[k] = (v, int(f[:4]))
        filas = [(f, v, rec.get(f[5:], ("", ""))[0], rec.get(f[5:], ("", ""))[1]) for f, v in sorted(hist.items())]

        def plot(plt, out, h):
            clim = m["clim"] if isinstance(m["clim"], list) else json.loads(str(m["clim"]).replace("'", '"'))
            act = [(f, v) for f, v in sorted(hist.items()) if int(f[:4]) == anio]
            fig, ax = plt.subplots(figsize=(11, 5.2), dpi=150)
            xs = list(range(len(clim)))
            ax.fill_between(xs, [c[2] for c in clim], [c[3] for c in clim], color="#cfe3f3", label="p10-p90 (1991-2020)")
            ax.plot(xs, [c[1] for c in clim], color="#6e6e73", lw=1, label="normal 1991-2020")
            rx = [i for i, c in enumerate(clim) if c[0] in rec]
            ax.plot(rx, [rec[clim[i][0]][0] for i in rx], color="#cc2200", lw=1, ls="--", label="récord para la fecha (1981-%d)" % (anio - 1))
            doy = {c[0]: i for i, c in enumerate(clim)}
            ax.plot([doy[f[5:]] for f, _ in act if f[5:] in doy], [v for f, v in act if f[5:] in doy], color="#0071b8", lw=2.2, label=str(anio))
            ax.scatter([doy[h["fecha_dato"][5:]]], [num(m["sst"])], color="#0071b8", zorder=5)
            _estilo(ax, plt, "Temperatura del Mediterráneo occidental español (°C)", h)
            ax.set_xticks([doy[f"{mm:02d}-01"] for mm in range(1, 13)]); ax.set_xticklabels([x[:3] for x in MESES])
            fig.savefig(out, bbox_inches="tight"); plt.close(fig)
        return {"cabecera": ["fecha", "sst_C", "record_previo_para_la_fecha_C", "anio_del_record"], "filas": filas, "plot": plot}

    if h["serie"] == "capitales":
        cod = next((k for k, v in PROVINCIAS.items() if v[0] == h.get("provincia")), None)
        if not cod:
            return None
        a = leer(DOCS / "archivo" / f"{cod}.json")
        u = a["ult30"]
        filas = list(zip(u["f"], u["tx"], u["ntx"], u["tn"], u["ntn"], u["ll"], u["nll"]))

        def plot(plt, out, h):
            fig, ax = plt.subplots(figsize=(11, 5.2), dpi=150)
            xs = list(range(len(u["f"])))
            if h["indicador"].startswith(("lluvia", "racha_tmax", "tmax", "d32")) and "lluvia" not in h["indicador"]:
                ax.plot(xs, u["ntx"], color="#6e6e73", lw=1, label="máxima normal 1991-2020")
                ax.plot(xs, u["tx"], color="#cc2200", lw=2.2, label="máxima")
                ax.plot(xs, u["ntn"], color="#6e6e73", lw=1, ls=":", label="mínima normal")
                ax.plot(xs, u["tn"], color="#0071b8", lw=1.6, label="mínima")
                titulo = f"{h['territorio']} · últimos 30 días (°C)"
            elif "lluvia" in h["indicador"]:
                ax.bar(xs, u["ll"], color="#0071b8", label="lluvia diaria (mm)")
                ax.plot(xs, u["nll"], color="#6e6e73", lw=1, label="normal diaria 1991-2020")
                titulo = f"{h['territorio']} · lluvia de los últimos 30 días (mm)"
            else:
                ax.plot(xs, u["ntn"], color="#6e6e73", lw=1, label="mínima normal 1991-2020")
                ax.plot(xs, u["tn"], color="#cc2200", lw=2.2, label="mínima")
                titulo = f"{h['territorio']} · mínimas de los últimos 30 días (°C)"
            _estilo(ax, plt, titulo, h)
            ax.set_xticks(xs[::5]); ax.set_xticklabels([f[8:10] + "/" + f[5:7] for f in u["f"]][::5])
            fig.savefig(out, bbox_inches="tight"); plt.close(fig)
        return {"cabecera": ["fecha", "tmax", "tmax_normal", "tmin", "tmin_normal", "lluvia_mm", "lluvia_normal_mm"], "filas": filas, "plot": plot}

    if h["serie"] == "dias32":
        d = leer(DOCS / "dias32.json")
        p = next((p for p in d["provincias"] if p["prov"] == h["territorio"]), None)
        if not p:
            return None
        filas = [(int(y), int(n)) for y, n in p["hist"]]

        def plot(plt, out, h):
            fig, ax = plt.subplots(figsize=(11, 5.2), dpi=150)
            ys = [y for y, _ in filas]; ns = [n for _, n in filas]
            ax.bar(ys, ns, color=["#cc2200" if y == int(h["fecha_dato"][:4]) else "#c9c9cc" for y in ys])
            ax.axhline(num(p["media_9120"]), color="#6e6e73", lw=1, ls="--", label="media 1991-2020")
            _estilo(ax, plt, f"{h['territorio']} · días de más de 32 °C por año", h)
            fig.savefig(out, bbox_inches="tight"); plt.close(fig)
        return {"cabecera": ["anio", "dias_mas_32C"], "filas": filas, "plot": plot}

    if h["serie"] == "embalses" and h["ambito"] == "provincial":
        for fp in glob.glob(str(DOCS / "embalses" / "*.json")):
            try:
                e = leer(Path(fp))
            except Exception:
                continue
            if e.get("provincia") == h["territorio"] and e.get("serie"):
                filas = [(s["fecha"], s["pct"]) for s in e["serie"]]

                def plot(plt, out, h, e=e):
                    fig, ax = plt.subplots(figsize=(11, 5.2), dpi=150)
                    ax.plot(range(len(filas)), [p for _, p in filas], color="#0071b8", lw=2)
                    ax.axhline(num(e["pct_media_10a"]), color="#6e6e73", lw=1, ls="--", label="media 10 años")
                    _estilo(ax, plt, f"Embalses de {h['territorio']} · % de capacidad, últimas 104 semanas", h)
                    ax.set_xticks(range(0, len(filas), 13)); ax.set_xticklabels([f[:7] for f, _ in filas][::13], rotation=45)
                    fig.savefig(out, bbox_inches="tight"); plt.close(fig)
                return {"cabecera": ["fecha_boletin", "pct"], "filas": filas, "plot": plot}
    return None


def _estilo(ax, plt, titulo: str, h: dict):
    ax.set_title(titulo, loc="left", fontsize=13, fontweight="bold")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#eeeeee")
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    ax.text(1, -0.14, f"Observatorio climático · calentamientoglobal.es · {h['fuente'][:70]}", transform=ax.transAxes,
            ha="right", fontsize=8, color="#6e6e73")


# ----------------------------------------------------------------------------
# principal
# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dossiers", type=int, default=0, help="generar dossier (md+png+csv) para los N hallazgos más fuertes")
    ap.add_argument("--salida", default=str(PRENSA / "hallazgos.json"))
    args = ap.parse_args()

    for fn in (capitales, mediterraneo, danas, dias32, embalses, caudal, planeta):
        try:
            fn()
        except Exception as e:
            errores.append(f"{fn.__name__}: {e}")

    agregar()
    hallazgos.sort(key=lambda h: -h["fuerza"])
    # un hallazgo por territorio+indicador basta
    vistos, unicos = set(), []
    for h in hallazgos:
        k = (h["territorio"], h["indicador"])
        if k in vistos:
            continue
        vistos.add(k)
        unicos.append(h)

    miembros = {m for h in unicos for m in h.get("miembros", [])}
    locales = [h for h in unicos if h["id"] in miembros]
    unicos = [h for h in unicos if h["id"] not in miembros]

    if args.dossiers:
        dossiers([h for h in unicos if h["citabilidad"] != "contexto"][:args.dossiers])
        dossiers(locales)

    salida = {
        "generado": AHORA.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total": len(unicos),
        "por_citabilidad": {k: sum(1 for h in unicos if h["citabilidad"] == k) for k in ("alta", "media", "contexto")},
        "enviables": [h for h in unicos if h["citabilidad"] in ("alta", "media")][:25],
        "contexto": [h for h in unicos if h["citabilidad"] == "contexto"],
        "locales": locales,
        "descartados": descartes,
        "errores": errores,
        "licencia": "Cálculo propio de CalentamientoGlobal.es · CC BY 4.0 · los datos de origen conservan la licencia de su organismo",
    }
    Path(args.salida).parent.mkdir(parents=True, exist_ok=True)
    with open(args.salida, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=1)

    # Historial: un registro por hallazgo enviable, con la primera y la última vez
    # que apareció. Da memoria a la sala de prensa (60 días) sin repetir entradas.
    hist_p = Path(args.salida).parent / "hallazgos_historial.json"
    hist = {}
    try:
        with open(hist_p, encoding="utf-8") as f:
            for x in json.load(f).get("hallazgos", []):
                hist[x["id"]] = x
    except Exception:
        pass
    hoy = HOY.isoformat()
    for h in salida["enviables"] + locales:
        x = hist.get(h["id"]) or {"id": h["id"], "primera_vez": hoy}
        x.update({"ultima_vez": hoy, "titular": h["titular"], "dato": h["dato"], "fecha_dato": h["fecha_dato"],
                  "serie": h["serie"], "tipo": h["tipo"], "ambito": h["ambito"], "territorio": h["territorio"],
                  "provincia_slug": h.get("provincia_slug"), "citabilidad": h["citabilidad"], "exclusivo": h["exclusivo"],
                  "fuerza": h["fuerza"], "pagina": h.get("pagina"), "dossier": h.get("dossier"),
                  "grafico": h.get("grafico"), "csv": h.get("csv"), "requiere_revision": h["requiere_revision"]})
        hist[h["id"]] = x
    limite = (HOY - timedelta(days=60)).isoformat()
    lista = sorted((x for x in hist.values() if x["ultima_vez"] >= limite), key=lambda x: (x["ultima_vez"], x["fuerza"]), reverse=True)
    with open(hist_p, "w", encoding="utf-8") as f:
        json.dump({"generado": salida["generado"], "dias": 60, "hallazgos": lista}, f, ensure_ascii=False, indent=1)
    print(f"{len(unicos)} hallazgos · enviables {len(salida['enviables'])} · locales {len(locales)} · contexto {len(salida['contexto'])} · descartes {len(descartes)} · errores {len(errores)}")
    for h in salida["enviables"][:15]:
        print(f"  [{h['fuerza']:5.1f}] {h['citabilidad']:8s} {h['titular']}")
    for e in errores:
        print("  !", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
