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
  docs/records/hallazgos_estaciones.json  récords de temperatura en las estaciones de AEMET,
                                el mismo día (records_detectar.py, clima-scripts): citabilidad alta

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
AYER = (HOY - timedelta(days=1)).isoformat()
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
    "record_absoluto": 100, "record_mes": 92, "primera_vez_desde": 90, "record_fecha": 80, "puesto_extremo": 75,
    "racha": 65, "anomalia_fuerte": 55, "percentil_extremo": 50, "contexto": 30,
    # lluvia medida por AEMET: la del día anterior completo y la del día en curso hasta la última hora cerrada
    "lluvia_dia": 85, "lluvia_en_curso": 90,
}
AMBITO_F = {"nacional": 1.0, "regional": 0.9, "provincial": 0.8, "local": 0.7, "global": 0.85}

# Vida útil de un hallazgo según la cadencia de su serie (días desde fecha_dato).
# Pasado ese plazo ya no es noticia: no entra en la cola, solo queda en el historial.
VIDA = {"capitales": 9, "mediterraneo": 7, "danas": 30, "dias32": 45, "embalses": 10, "caudal": 4,
        "oceano": 10, "temperatura_global": 20, "lluvia": 1, "estaciones": 6}

hallazgos: list[dict] = []
descartes: list[dict] = []
errores: list[str] = []
ENVIVO: dict = {}   # cifras verificadas para la franja «en vivo» de /prensa/ (prensa/envivo.json)
RETIRAR: set = set()  # ids que el verificador de récords de estaciones ha descartado: fuera del historial


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
    edad = dias_desde(h["fecha_dato"])
    vida = VIDA.get(h["serie"], 10)
    if edad > vida:
        descartar(h["serie"], h["territorio"], f"dato de hace {edad} días: caducado para esta serie (vida {vida} días)", h.get("titular", ""))
        return
    frescura = max(0.35, 1 - 0.07 * max(0, edad - 1))  # -7 %/día a partir del 2.º
    h["edad_dias"] = edad
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


def miles(v) -> str:
    """Entero con punto de millar: 32398.0 → 32.398"""
    try:
        return f"{int(round(float(v))):,}".replace(",", ".")
    except (TypeError, ValueError):
        return str(v)


# ----------------------------------------------------------------------------
# Regla de publicación (17-10-2026): una cifra de ciudad solo sale si la ha medido AEMET
# ----------------------------------------------------------------------------
# La auditoría del 17-10-2026 cotejó el reanálisis con las estaciones de AEMET: la celda
# puede diferir varios grados de la ciudad (Málaga, 13-10-2026: 19,9 °C en el análisis,
# 16,0 °C en la estación). Por eso todo récord de una capital se contrasta con la estación
# de AEMET de esa ciudad (docs/temperaturas_nocturnas.json, 2-4 días de retraso):
#   · AEMET publica el dato y coincide (±1 °C) → sale, con la cifra de AEMET en el titular
#   · AEMET publica el dato y no coincide        → se descarta
#   · AEMET aún no lo ha publicado               → queda en revisión (no se publica)
# Las cifras de lluvia y los recuentos de días (≥ 32 °C, rachas) de una celda no tienen
# contraste posible con lo que hay en el repositorio: quedan siempre en revisión.
AEMET_TOL = 1.0      # °C de diferencia máxima entre la estación de AEMET y el reanálisis
AEMET_KM = 20        # distancia máxima entre la capital y la estación de AEMET
_AEMET = None


def _aemet_estaciones():
    global _AEMET
    if _AEMET is None:
        _AEMET = {}
        try:
            caps = {c["provincia"]: c for c in leer(DOCS / "viento.json")["capitales"]}
            ciudades = leer(DOCS / "temperaturas_nocturnas.json")["ciudades"]
        except Exception as e:
            errores.append(f"aemet: {e}")
            return _AEMET
        import math
        for cod, (prov, _slug) in PROVINCIAS.items():
            c = caps.get(prov)
            if not c:
                continue
            mejor, dm = None, 1e9
            for x in ciudades:
                if x.get("lat") is None:
                    continue
                p1, p2 = math.radians(c["lat"]), math.radians(x["lat"])
                dp, dl = p2 - p1, math.radians(x["lon"] - c["lon"])
                d = 2 * 6371 * math.asin(math.sqrt(math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2))
                if d < dm:
                    mejor, dm = x, d
            if mejor and dm <= AEMET_KM:
                hist = {k: v for k, v in (mejor.get("historico") or {}).items() if k[:2] == "20" and isinstance(v, dict)}
                _AEMET[cod] = {"nombre": mejor["nombre"], "km": round(dm, 1), "historico": hist,
                               "ultimo": max(hist) if hist else None}
    return _AEMET


def cod_de_provincia(nombre: str) -> str | None:
    for cod, (nom, _s) in PROVINCIAS.items():
        if nom == nombre:
            return cod
    return None


def confirmar_con_aemet(h: dict):
    """Aplica la regla de publicación a un hallazgo de capital. Devuelve False si hay que descartarlo."""
    if h.get("serie") != "capitales":
        return True
    ind = h.get("indicador", "")
    if h.get("ambito") == "nacional":
        # agregados del análisis IFS («N capitales tuvieron ayer…»): sin contraste estación a estación
        if ind.startswith("ayer_"):
            h["limites"] = h["limites"] + ["COMPROBAR: agregado del análisis meteorológico sin contraste con las estaciones de AEMET; no se publica."]
        return True
    if ind not in ("tmax", "tmin_alta", "tmin_baja"):
        h["limites"] = h["limites"] + ["COMPROBAR: cifra del reanálisis en la celda de la capital, sin contraste con la estación o el pluviómetro de AEMET; no se publica como dato de la ciudad."]
        return True
    cod = cod_de_provincia(h.get("provincia", ""))
    est = _aemet_estaciones().get(cod or "")
    if not est:
        h["limites"] = h["limites"] + ["COMPROBAR: el observatorio no tiene una estación de AEMET de referencia a menos de 20 km de esta capital."]
        return True
    campo = "tmax" if ind == "tmax" else "tmin"
    a = (est["historico"].get(h["fecha_dato"]) or {}).get(campo)
    if a is None:
        h["limites"] = h["limites"] + [f"COMPROBAR: pendiente de que AEMET publique el dato de la estación de {est['nombre']} (llega con 2-4 días de retraso)."]
        return True
    valores = [v for v in (h.get("valor"), h.get("valor_corregido")) if v is not None]
    dif = min(abs(a - v) for v in valores) if valores else 99
    if dif > AEMET_TOL:
        descartar("capitales", h["territorio"], f"AEMET midió {f1(a)} °C en {est['nombre']} el {fecha_dia(h['fecha_dato'])}; el reanálisis daba "
                  f"{f1(valores[0]) if valores else '—'} °C: la celda no representa la ciudad ese día", h["titular"])
        return False
    cap, desde, dia = h["territorio"], h["serie_desde"], fecha_dia(h["fecha_dato"])
    era5 = h.get("valor_corregido") if h.get("valor_corregido") is not None else h.get("valor")
    if ind == "tmax":
        h["titular"] = f"{cap} registró el {dia} una máxima de {f1(a)} °C, la más alta para esa fecha en la serie que empieza en {desde}"
    elif ind == "tmin_alta":
        h["titular"] = f"{cap} registró el {dia} una mínima de {f1(a)} °C, la más alta para esa fecha en la serie que empieza en {desde}"
    else:
        h["titular"] = f"{cap} registró el {dia} una mínima de {f1(a)} °C, la más baja para esa fecha en la serie que empieza en {desde}"
    h["dato"] = (f"AEMET, estación de {est['nombre']}: {f1(a)} °C · reanálisis ERA5 en la celda de {cap}: {f1(era5)} °C"
                 + (f" · récord anterior de la serie para la fecha: {h['record_anterior_txt']}" if h.get("record_anterior_txt") else ""))
    h["limites"] = [l for l in h["limites"] if "AEMET" not in l and "COMPROBAR" not in l] + [
        "La cifra es la medida por AEMET en su estación. El carácter de récord sale de la serie diaria del reanálisis ERA5 "
        f"desde {desde} (celda de ~25 km), contrastada ese día con la estación (diferencia {f1(dif)} °C).",
    ]
    h["aemet"] = {"estacion": est["nombre"], "valor": a, "diferencia": round(dif, 1)}
    h["valor"] = a
    return True


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
        "limites": ["Reanálisis en una celda de ~25 km, no la estación oficial de AEMET: la cifra de AEMET puede diferir.",
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
            anadir({**base, "tipo": "record_fecha", "fecha_dato": f, "indicador": "tmax", "valor": tx[i],
                    "titular": f"{cap} marcó el {fecha_dia(f)} su máxima más alta para esa fecha desde {desde}: {f1(tx[i])} °C",
                    "dato": f"{f1(tx[i])} °C · normal para la fecha {f1(ntx[i])} °C",
                    "contexto": [f"Serie de {n_anios} años ({desde}-{ultimo[:4]}).",
                                 f"Normal 1991-2020 para ese día: {f1(ntx[i])} °C (+{f1(tx[i] - ntx[i])} °C)."]})
        if r[7] == anio and tn[i] is not None and abs(tn[i] - r[6]) < 0.051:
            anadir({**base, "tipo": "record_fecha", "fecha_dato": f, "indicador": "tmin_alta", "valor": tn[i],
                    "titular": f"{cap} tuvo el {fecha_dia(f)} la noche más cálida para esa fecha desde {desde}: mínima de {f1(tn[i])} °C",
                    "dato": f"mínima {f1(tn[i])} °C · normal {f1(ntn[i])} °C",
                    "contexto": [f"Serie de {n_anios} años.", f"Normal 1991-2020 para ese día: {f1(ntn[i])} °C."]})
        if r[3] == anio and tn[i] is not None and abs(tn[i] - r[2]) < 0.051:
            anadir({**base, "tipo": "record_fecha", "fecha_dato": f, "indicador": "tmin_baja", "valor": tn[i],
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
# 1b · Capitales, los días que ERA5 aún no ha consolidado · Open-Meteo (IFS)
# ----------------------------------------------------------------------------
# El archivo de capitales se detiene donde ERA5 es definitivo (~6 días atrás).
# Para que la sala de prensa tenga el dato de AYER, se piden a Open-Meteo los días
# que faltan con el análisis IFS del ECMWF (9 km). El IFS no es ERA5 (25 km): en
# cada capital tiene un sesgo sistemático (p. ej. mínimas 1-2 °C más frías en la
# costa), así que se calibra con los 21 días en que ambos existen y solo se declara
# récord si el valor IFS Y el valor corregido superan el récord con margen.
# Se marcan como provisionales; ERA5 los confirma o desmiente a los seis días.
OPEN_METEO = "https://archive-api.open-meteo.com/v1/archive"
IFS_SOLAPE = 21      # días de solape IFS/ERA5 para calibrar
IFS_MARGEN = 0.3     # °C por encima del récord que se exigen al valor corregido
IFS_MAX_SESGO = 3.0  # si el sesgo medio supera esto, la celda no es comparable: se salta


def capitales_ayer():
    import urllib.request
    import urllib.parse
    try:
        coords = {c["provincia"]: (c["lat"], c["lon"]) for c in leer(DOCS / "viento.json")["capitales"]}
    except Exception as e:
        errores.append(f"capitales_ayer: sin coordenadas ({e})")
        return
    archivos = []
    for fp in sorted(glob.glob(str(DOCS / "archivo" / "[0-9][0-9].json"))):
        try:
            a = leer(Path(fp))
        except Exception:
            continue
        prov = PROVINCIAS.get(a["cod"], (None, None))[0]
        if prov in coords:
            archivos.append((a, prov, coords[prov]))
    if not archivos:
        return
    ultimo_era5 = max(a["ultimo"] for a, _, _ in archivos)
    fin = (HOY - timedelta(days=1)).isoformat()
    if ultimo_era5 >= fin:
        return
    inicio = (date.fromisoformat(ultimo_era5) - timedelta(days=IFS_SOLAPE - 1)).isoformat()
    q = urllib.parse.urlencode({
        "latitude": ",".join(f"{c[0]:.4f}" for _, _, c in archivos),
        "longitude": ",".join(f"{c[1]:.4f}" for _, _, c in archivos),
        "start_date": inicio, "end_date": fin, "timezone": "Europe/Madrid",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum", "models": "ecmwf_ifs",
    })
    try:
        with urllib.request.urlopen(f"{OPEN_METEO}?{q}", timeout=60) as r:
            res = json.load(r)
    except Exception as e:
        errores.append(f"capitales_ayer: Open-Meteo {e}")
        return
    if isinstance(res, dict):
        res = [res]
    if len(res) != len(archivos):
        errores.append(f"capitales_ayer: Open-Meteo devolvió {len(res)} series para {len(archivos)} capitales")
        return
    ayer_anom = []  # (capital, prov, tx, anom_tx, tn, anom_tn) de AYER, para el ángulo nacional
    for (a, prov, _), r in zip(archivos, res):
        d = r.get("daily") or {}
        fechas, tx, tn, ll = d.get("time", []), d.get("temperature_2m_max", []), d.get("temperature_2m_min", []), d.get("precipitation_sum", [])
        cap, desde, rec = a["capital"], a["desde"][:4], a["records"]
        cod = a["cod"]
        # calibración IFS → ERA5 con los días de solape
        u = a["ult30"]
        idx = {f: i for i, f in enumerate(u["f"])}
        dtx, dtn = [], []
        for i, f in enumerate(fechas):
            j = idx.get(f)
            if j is None or f > a["ultimo"]:
                continue
            if i < len(tx) and tx[i] is not None and u["tx"][j] is not None:
                dtx.append(tx[i] - u["tx"][j])
            if i < len(tn) and tn[i] is not None and u["tn"][j] is not None:
                dtn.append(tn[i] - u["tn"][j])
        if len(dtx) < 10 or len(dtn) < 10:
            descartar("capitales", cap, "sin solape suficiente para calibrar el IFS")
            continue
        sesgo_tx, sesgo_tn = sum(dtx) / len(dtx), sum(dtn) / len(dtn)
        if abs(sesgo_tx) > IFS_MAX_SESGO or abs(sesgo_tn) > IFS_MAX_SESGO:
            descartar("capitales", cap, f"celda IFS no comparable con ERA5 (sesgo máx {f1(sesgo_tx)} / mín {f1(sesgo_tn)} °C)")
            continue
        calib = f"calibrado con {len(dtx)} días de solape: sesgo IFS−ERA5 máximas {'+' if sesgo_tx >= 0 else ''}{f1(sesgo_tx)} °C, mínimas {'+' if sesgo_tn >= 0 else ''}{f1(sesgo_tn)} °C"
        # normal 1991-2020 de los días posteriores a «ultimo»: extrapolación lineal de los últimos 15 días (±0,2 °C en octubre)
        def normal_extrapolada(serie_normal, dias_mas):
            vals = [v for v in serie_normal[-15:] if v is not None]
            if len(vals) < 8:
                return None
            pendiente = (vals[-1] - vals[0]) / (len(vals) - 1)
            return vals[-1] + pendiente * dias_mas
        slug = PROVINCIAS.get(cod, (None, cod))[1]
        base = {
            "serie": "capitales", "fuente": "ECMWF IFS (análisis) vía Open-Meteo, CC BY 4.0; récords sobre ERA5 (Copernicus) 1940-" + ultimo_era5[:4],
            "serie_desde": desde, "territorio": cap, "provincia": prov, "provisional": True,
            "pagina": f"https://calentamientoglobal.es/cambio-climatico-en-{slug}/",
            "metodo": f"Dato del día tomado del análisis IFS del ECMWF (9 km, Open-Meteo) sobre {cap}, corregido del sesgo frente a ERA5 "
                      f"({calib}) y comparado con el récord para esa fecha de la serie ERA5 diaria desde {desde}. Solo cuenta como récord si lo "
                      f"superan tanto el valor IFS como el corregido, con {f1(IFS_MARGEN)} °C de margen.",
            "limites": ["Dato provisional: ERA5 lo consolidará en unos seis días y puede moverlo unas décimas.",
                        "Análisis meteorológico en una celda de ~9 km, no la estación oficial de AEMET: la cifra de AEMET puede diferir."],
            "citabilidad": "media",
        }
        dias = []
        for i, f in enumerate(fechas):
            if f <= a["ultimo"] or f > fin:
                continue
            x, n, p = (tx[i] if i < len(tx) else None), (tn[i] if i < len(tn) else None), (ll[i] if i < len(ll) else None)
            dias.append((f, x, n, p))
            if f == fin:
                k = (date.fromisoformat(f) - date.fromisoformat(a["ultimo"])).days
                ntx_f, ntn_f = normal_extrapolada(u["ntx"], k), normal_extrapolada(u["ntn"], k)
                if x is not None and n is not None and ntx_f is not None and ntn_f is not None:
                    ayer_anom.append((cap, prov, x - sesgo_tx, x - sesgo_tx - ntx_f, n - sesgo_tn, n - sesgo_tn - ntn_f))
            rr = rec.get(f[5:7] + f[8:10])
            if not rr or len(rr) < 10:
                continue
            xc = None if x is None else x - sesgo_tx
            nc = None if n is None else n - sesgo_tn
            ctx = [f"Serie de récords {desde}-{ultimo_era5[:4]} (ERA5); dato del día provisional (análisis IFS)."]

            def lim_extra(margen, umbral=2.0, unidad="°C"):
                # Un récord batido por mucho es la mejor noticia y también el artefacto más probable:
                # pasa a «requiere revisión» hasta que se coteje con AEMET.
                if margen > umbral:
                    return base["limites"] + [f"COMPROBAR antes de enviar: supera el récord anterior en {f1(margen)} {unidad}, demasiado para un análisis; confirmar con la estación de AEMET."]
                return base["limites"]
            if x is not None and x > rr[0] + 0.05 and xc > rr[0] + IFS_MARGEN:
                anadir({**base, "tipo": "record_fecha", "fecha_dato": f, "indicador": "tmax", "valor": x, "valor_corregido": xc,
                        "record_anterior_txt": f"{f1(rr[0])} °C ({rr[1]})",
                        "titular": f"{cap} marcó el {fecha_dia(f)} su máxima más alta para esa fecha desde {desde}: {f1(x)} °C",
                        "dato": f"{f1(x)} °C (corregido a escala ERA5: {f1(xc)} °C) · récord anterior para la fecha {f1(rr[0])} °C ({rr[1]})",
                        "contexto": ctx, "limites": lim_extra(xc - rr[0])})
            if n is not None and n > rr[6] + 0.05 and nc > rr[6] + IFS_MARGEN:
                anadir({**base, "tipo": "record_fecha", "fecha_dato": f, "indicador": "tmin_alta", "valor": n, "valor_corregido": nc,
                        "record_anterior_txt": f"{f1(rr[6])} °C ({rr[7]})",
                        "titular": f"{cap} tuvo el {fecha_dia(f)} la mínima más alta para esa fecha desde {desde}: {f1(n)} °C",
                        "dato": f"mínima {f1(n)} °C (corregida a escala ERA5: {f1(nc)} °C) · récord anterior para la fecha {f1(rr[6])} °C ({rr[7]})",
                        "contexto": ctx, "limites": lim_extra(nc - rr[6])})
            if n is not None and n < rr[2] - 0.05 and nc < rr[2] - IFS_MARGEN:
                anadir({**base, "tipo": "record_fecha", "fecha_dato": f, "indicador": "tmin_baja", "valor": n, "valor_corregido": nc,
                        "record_anterior_txt": f"{f1(rr[2])} °C ({rr[3]})",
                        "titular": f"{cap} registró el {fecha_dia(f)} su mínima más baja para esa fecha desde {desde}: {f1(n)} °C",
                        "dato": f"mínima {f1(n)} °C (corregida a escala ERA5: {f1(nc)} °C) · récord anterior para la fecha {f1(rr[2])} °C ({rr[3]})",
                        "contexto": ctx, "limites": lim_extra(rr[2] - nc)})
            if p is not None and p >= 10 and p > rr[8] * 1.2:
                anadir({**base, "tipo": "record_fecha", "fecha_dato": f, "indicador": "lluvia",
                        "titular": f"{cap} recogió el {fecha_dia(f)} {f1(p)} mm, la mayor lluvia para esa fecha desde {desde}",
                        "dato": f"{f1(p)} mm en un día · récord anterior para la fecha {f1(rr[8])} mm ({rr[9]})",
                        "limites": lim_extra(p / max(rr[8], 1), 2.0, "veces") + ["La lluvia de un análisis es una media de celda: el pluviómetro local puede dar más o menos."]})
        # los días provisionales se guardan en el hallazgo para que el gráfico los pinte
        for h in hallazgos:
            if h["serie"] == "capitales" and h.get("provisional") and h["territorio"] == cap and "prov_dias" not in h:
                h["prov_dias"] = dias

    # --- el ángulo de AYER a escala nacional: cuántas capitales muy por encima / por debajo de lo normal ----
    if len(ayer_anom) >= 40:
        base_n = {"serie": "capitales", "serie_desde": "1940", "territorio": "España", "ambito": "nacional", "provisional": True,
                  "fuente": "ECMWF IFS (análisis) vía Open-Meteo, CC BY 4.0; normal 1991-2020 de ERA5 (Copernicus)",
                  "pagina": "https://calentamientoglobal.es/el-tiempo/",
                  "metodo": "Máxima y mínima de ayer del análisis IFS del ECMWF (9 km) en las 52 capitales, corregidas del sesgo frente a ERA5 "
                            "con 21 días de solape, comparadas con la normal 1991-2020 de cada capital para la fecha (ERA5, extrapolada los "
                            "días que ERA5 aún no cubre).",
                  "limites": ["Dato provisional de un análisis, no de las estaciones de AEMET: la cifra oficial puede diferir en 1-2 °C.",
                              "La normal de los últimos días es una extrapolación lineal (±0,2 °C)."],
                  "citabilidad": "media"}
        for ix, etiqueta, signo in ((3, "máximas", +1), (3, "máximas", -1), (5, "mínimas", +1), (5, "mínimas", -1)):
            # (capital, provincia, valor, anomalía) de ayer, solo las que se desvían ≥ 5 °C en el sentido buscado
            lista = [(t[0], t[1], t[2] if ix == 3 else t[4], t[ix]) for t in ayer_anom if signo * t[ix] >= 5]
            lista.sort(key=lambda t: -signo * t[3])
            if len(lista) >= 10:
                n = len(lista)
                arriba = signo > 0
                nombres = "; ".join(f"{c} {f1(v)} °C ({'+' if an > 0 else ''}{f1(an)})" for c, pr, v, an in lista[:8])
                anadir({**base_n, "tipo": "anomalia_fuerte", "fecha_dato": fin, "indicador": f"ayer_{etiqueta}_{'calor' if arriba else 'frio'}",
                        "titular": f"{n} capitales españolas tuvieron el {fecha_dia(fin)} {etiqueta} de al menos 5 °C {'por encima' if arriba else 'por debajo'} de lo normal para la fecha",
                        "dato": f"{n} de {len(ayer_anom)} capitales · las más extremas: {nombres}",
                        "contexto": [f"Media de la desviación en esas {n} capitales: {'+' if arriba else ''}{f1(sum(t[3] for t in lista) / n)} °C.",
                                     "Normal de referencia: 1991-2020, día a día, en la celda de cada capital."],
                        "miembros_txt": [c for c, _, _, _ in lista]})


# ----------------------------------------------------------------------------
# 2 · Mediterráneo occidental · OISST desde 1981
# ----------------------------------------------------------------------------
def _vecinos(serie: dict, anio: int, mmdd: str, dias: int = 3):
    """Valores de los días vecinos (±dias) de una fecha en un año: para acotar los huecos de la fuente."""
    try:
        c = date(anio, int(mmdd[:2]), int(mmdd[3:5]))
    except ValueError:
        return []
    return [serie[(c + timedelta(days=k)).isoformat()] for k in range(-dias, dias + 1)
            if (c + timedelta(days=k)).isoformat() in serie]


def _puesto_verificado(serie: dict, fecha: str, valor: float, margen: float = 1.0):
    """Puesto del valor entre todos los años de la serie para esa fecha, contando los años en que la
    fuente tiene hueco solo si sus días vecinos quedan claramente por debajo. Devuelve
    (puesto, de, n_huecos) o None si algún hueco no se puede descartar."""
    anio, mmdd = int(fecha[:4]), fecha[5:10]
    primero = 1981 if mmdd >= "09-01" else 1982          # OISST empieza el 1-9-1981
    puesto, de, huecos = 1, 0, 0
    for y in range(primero, anio + 1):
        f = f"{y}-{mmdd}"
        if f in serie:
            de += 1
            if y != anio and serie[f] > valor:
                puesto += 1
            continue
        if y == anio:
            continue
        vec = _vecinos(serie, y, mmdd)
        if not vec or max(vec) >= valor - margen:
            return None
        de += 1
        huecos += 1
    return puesto, de, huecos


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
    from collections import Counter
    por_anio = Counter(f[:4] for f in _huecos_oisst(serie) if f < ultimo)
    grandes = sorted(a for a, n in por_anio.items() if n >= 30)
    sueltos = sorted(a for a, n in por_anio.items() if n < 30)
    lim_huecos = []
    if por_anio:
        tramo = (f"{grandes[0]}-{grandes[-1]}" if len(grandes) > 1 else grandes[0]) if grandes else ""
        txt = (f"muchos días sin dato en {tramo}" if tramo else "") + (" y " if tramo and sueltos else "") + (f"días sueltos en {', '.join(sueltos)}" if sueltos else "")
        lim_huecos = [f"La copia de NOAA OISST descargada tiene {txt}: un año con hueco solo cuenta en el puesto si sus días vecinos quedan claramente "
                      "por debajo; si alguno podría superar el valor, no se publica el puesto."]
    base = {
        "serie": "mediterraneo", "fuente": m["fuente"], "serie_desde": "1981", "territorio": "Mediterráneo occidental",
        "ambito": "nacional", "pagina": "https://calentamientoglobal.es/dana/",
        "metodo": "Temperatura superficial del mar NOAA OISST v2.1 (0,25°), media diaria de la caja 36,5-41,5° N / 1,5° O-5° E "
                  "(de Alborán oriental al mar Balear). Normal 1991-2020 por día del año; puesto para la fecha sobre todos los años desde 1981.",
        "limites": ["Los últimos ~14 días de OISST son la versión preliminar (NRT) y la final puede corregirlos: en esos días un récord o un puesto por menos de 0,1 °C no se da por cierto.",
                    "Media de una caja de mar abierto, no la temperatura de una playa concreta."] + lim_huecos,
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
    # días del año en curso en récord (verificados contra los huecos de la fuente) y racha final
    actual = sorted((f, v) for f, v in serie.items() if int(f[:4]) == anio)

    # Los últimos ~14 días son la versión preliminar de OISST: la final puede corregirlos. Un récord por menos de
    # MARGEN_NRT en esos días no se da como récord (17-10-2026: 24,28 °C frente a 24,25 °C de 2023 salía «récord»).
    MARGEN_NRT = 0.1
    fin_final = (date.fromisoformat(ultimo) - timedelta(days=14)).isoformat()

    def es_record(f, v):
        if f[5:] not in maximo_fecha or v <= maximo_fecha[f[5:]][0]:
            return False
        if f > fin_final and v - maximo_fecha[f[5:]][0] < MARGEN_NRT:
            return False
        pv = _puesto_verificado(serie, f, v, margen=0.5)
        return bool(pv and pv[0] == 1)
    en_record = [(f, v) for f, v in actual if es_record(f, v)]
    racha = 0
    for f, v in reversed(actual):
        if es_record(f, v):
            racha += 1
        else:
            break
    inciertos = sum(1 for f, v in actual if f[5:] in maximo_fecha and v > maximo_fecha[f[5:]][0] and not es_record(f, v))
    ctx_comun = [(f"Al menos {len(en_record)} días de {anio} han sido récord para su fecha en la serie desde 1981; "
                  + (f"otro día supera el récord por un margen que no se puede certificar (dato preliminar o hueco en la fuente)." if inciertos == 1 else
                     f"otros {inciertos} días lo superan por un margen que no se puede certificar (dato preliminar o hueco en la fuente).")
                  if inciertos else f"{len(en_record)} días de {anio} han sido récord para su fecha en la serie desde 1981."),
                 f"Máximo absoluto de la serie: {f2(maximo_abs[0])} °C el {fecha_larga(maximo_abs[1])}.",
                 (f"{f1(sst)} °C es lo normal en esta zona para un {_fecha_equivalente(m, sst)} (media 1991-2020)." if _fecha_equivalente(m, sst) else "")]
    ctx_comun = [c for c in ctx_comun if c]
    rec_prev = maximo_fecha.get(ultimo[5:])
    pv = _puesto_verificado(serie, ultimo, sst)
    if pv is None:
        descartar("mediterraneo", "Mediterráneo occidental", "un año con hueco en la fuente podría superar el valor de hoy: no se publica el puesto", f"{f1(sst)} °C")
        rec_prev = None
    # puesto que no se puede separar de otro año por el margen del dato preliminar
    otros = sorted(((serie[f"{y}{ultimo[4:]}"], y) for y in range(1981, anio) if f"{y}{ultimo[4:]}" in serie), reverse=True)
    peor = 1 + sum(1 for x, _ in otros if x > sst - MARGEN_NRT)
    mejor = 1 + sum(1 for x, _ in otros if x > sst + MARGEN_NRT)
    cerca = [(x, y) for x, y in otros if abs(x - sst) < MARGEN_NRT]
    if rec_prev and pv and mejor != peor:
        if peor <= 3 and pv[1] >= 30:
            palabra = {2: "dos", 3: "tres"}[peor]
            x0, y0 = cerca[0]
            anadir({**base, "tipo": "puesto_extremo", "fecha_dato": ultimo, "indicador": "sst_puesto_fecha",
                    "titular": f"El Mediterráneo español tuvo uno de sus {palabra} {fecha_dia(ultimo)} más cálidos desde 1981: {f1(sst)} °C, {f1(anom)} °C por encima de lo normal",
                    "dato": (f"{f2(sst)} °C · dato preliminar de NOAA: queda a {f2(abs(sst - x0))} °C del de {y0} ({f2(x0)} °C), menos de lo que puede corregirse, "
                             f"así que no se puede decir cuál es más alto · normal 1991-2020 {f2(normal)} °C (+{f2(anom)})"),
                    "contexto": ctx_comun, "puesto": None, "de": pv[1]})
            ENVIVO["mediterraneo"] = {"ultimo": ultimo, "sst": sst, "normal": normal, "anomalia": anom, "puesto": None, "de": None, "fuente": "NOAA OISST v2.1"}
            return
        pv, rec_prev = None, None   # sin puesto certificable: solo cabe la anomalía
    if racha >= 1 and rec_prev:
        titular = (f"El Mediterráneo español encadenaba el {fecha_dia(ultimo)} {racha} días seguidos en récord de temperatura para la fecha: {f2(sst)} °C"
                   if racha >= 3 else
                   f"El Mediterráneo español marcó el {fecha_dia(ultimo)} su temperatura más alta para esa fecha desde 1981: {f2(sst)} °C")
        anadir({**base, "tipo": "racha" if racha >= 3 else "record_fecha", "fecha_dato": ultimo, "indicador": "sst_record_fecha",
                "titular": titular,
                "dato": f"{f2(sst)} °C · récord anterior para la fecha {f2(rec_prev[0])} °C ({rec_prev[1]}) · normal 1991-2020 {f2(normal)} °C (+{f2(anom)})",
                "contexto": ctx_comun, "racha": racha, "puesto": 1, "de": pv[1]})
    elif rec_prev:
        puesto, de = pv[0], pv[1]
        if 2 <= puesto <= 3 and de >= 30:
            ordinal = {2: "segundo", 3: "tercer"}[puesto]
            anadir({**base, "tipo": "puesto_extremo", "fecha_dato": ultimo, "indicador": "sst_puesto_fecha",
                    "titular": f"El Mediterráneo español tuvo su {ordinal} {fecha_dia(ultimo)} más cálido desde 1981: {f1(sst)} °C, {f1(anom)} °C por encima de lo normal",
                    "dato": f"{f2(sst)} °C · puesto {puesto} de {de} años para la fecha · récord {f2(rec_prev[0])} °C ({rec_prev[1]}) · normal 1991-2020 {f2(normal)} °C (+{f2(anom)})",
                    "contexto": ctx_comun, "puesto": puesto, "de": de})
        else:
            descartar("mediterraneo", "Mediterráneo occidental", "no está en récord para la fecha",
                      f"{f1(sst)} °C frente a {f1(rec_prev[0])} °C ({rec_prev[1]}); puesto {puesto} de {de}")
    # anomalía fuerte sin récord ni puesto extremo
    if anom is not None and anom >= 1.5 and racha == 0 and not any(h["indicador"] == "sst_puesto_fecha" for h in hallazgos):
        anadir({**base, "tipo": "anomalia_fuerte", "fecha_dato": ultimo, "indicador": "sst_anomalia",
                "titular": f"El Mediterráneo español estaba el {fecha_dia(ultimo)} {f1(anom)} °C por encima de lo normal para la fecha: {f1(sst)} °C",
                "dato": f"{f1(sst)} °C · normal {f1(normal)} °C · p90 para la fecha {f1(num(m['p90']))} °C",
                "contexto": ([f"Puesto {pv[0]} de {pv[1]} años para la fecha."] if pv else [])})
    # cifra verificada para la franja «en vivo» de la sala de prensa
    ENVIVO["mediterraneo"] = {"ultimo": ultimo, "sst": sst, "normal": normal, "anomalia": anom,
                              "puesto": pv[0] if pv else None, "de": pv[1] if pv else None, "fuente": "NOAA OISST v2.1"}


def _huecos_oisst(serie: dict) -> list[str]:
    """Días sin dato en la serie descargada entre el 1-9-1981 y el último día."""
    if not serie:
        return []
    d, fin, out = date(1981, 9, 1), date.fromisoformat(max(serie)), []
    while d <= fin:
        if d.isoformat() not in serie:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _fecha_equivalente(m: dict, sst: float):
    """A qué día del año corresponde esta temperatura en la climatología, buscando solo en la misma fase del ciclo
    (en otoño, entre el máximo de agosto y hoy). Antes elegía el primer día del año con ese valor: «un 14 de julio»
    cuando el 21 de septiembre tiene la misma normal."""
    try:
        clim = m["clim"] if isinstance(m["clim"], list) else json.loads(m["clim"].replace("'", '"'))
        hoy_md = date.fromisoformat(m["ultimo"]).strftime("%m-%d")
        md_max = max(clim, key=lambda c: c[1])[0]
        md_min = min(clim, key=lambda c: c[1])[0]
        if hoy_md > md_max:                       # fase de enfriamiento: un valor alto es el normal de días anteriores
            cand = [c for c in clim if md_max <= c[0] < hoy_md]
        elif hoy_md > md_min:                     # fase de calentamiento: un valor alto es el normal de días posteriores
            cand = [c for c in clim if hoy_md < c[0] <= md_max]
        else:
            return None
        mejor = min(((abs(c[1] - sst), c[0]) for c in cand), default=None)
        if mejor and mejor[0] <= 0.15:
            mm, dd = mejor[1].split("-")
            return f"{int(dd)} de {MESES[int(mm) - 1]}"
    except Exception:
        pass
    return None


# ----------------------------------------------------------------------------
# 3 · Temporada de DANAs · desde 1958
# ----------------------------------------------------------------------------
# ----------------------------------------------------------------------------
# Lluvia medida por AEMET (estaciones) · ayer completo y hoy hasta la última hora
# ----------------------------------------------------------------------------
# 18-10-2026: la portada abría con datos de hace dos días (el Mediterráneo llega con 1-2 días de retraso y el
# boletín de embalses es semanal). La lluvia de las estaciones de AEMET es lo más fresco y medido que tenemos:
# el día anterior completo y el día en curso hasta la última hora cerrada.
def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


_ALIAS_PROV = {"araba": "01", "arabaalava": "01", "alava": "01", "baleares": "07", "illesbalears": "07",
               "stacruzdetenerife": "38", "santacruzdetenerife": "38", "acoruna": "15", "coruna": "15", "lacoruna": "15",
               "castellon": "12", "castello": "12", "laspalmas": "35", "larioja": "26", "ciudadreal": "13"}


def cod_provincia(nombre) -> str | None:
    n = _norm(nombre)
    for cod, (nom, slug) in PROVINCIAS.items():
        if n in (_norm(nom), slug.replace("-", "")):
            return cod
    return _ALIAS_PROV.get(n)


def _km(a, b) -> float:
    import math
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


_MUNI_IDX = None
_ARTICULO = re.compile(r"(.+),\s*(El|La|Los|Las|L'|Lo|Es|Sa|Ses|Els|Les|O|A|Os|As)$")


def _municipios_ine():
    """(nombre normalizado → [(provincia, lat, lon)], código INE → (lat, lon)) de los ~8.100 municipios."""
    global _MUNI_IDX
    if _MUNI_IDX is None:
        idx, pos = {}, {}
        try:
            items = leer(DOCS / "municipios.json")["items"]
        except Exception:
            items = []
        for m in items:
            code = str(m.get("code") or "")
            if len(code) != 5 or m.get("lat") is None:
                continue
            pos[code] = (m["lat"], m["lon"])
            for v in str(m.get("n") or "").split("/"):
                v = v.strip()
                a = _ARTICULO.fullmatch(v)
                if a:
                    v = a.group(2) + ("" if a.group(2).endswith("'") else " ") + a.group(1)
                    idx.setdefault(_norm(a.group(1)), []).append((code[:2], m["lat"], m["lon"]))  # sin artículo
                if v:
                    idx.setdefault(_norm(v), []).append((code[:2], m["lat"], m["lon"]))
        _MUNI_IDX = (idx, pos)
    return _MUNI_IDX


def _palabras(est: str) -> list:
    return [w for w in re.split(r"[\s/\-,.]+", re.sub(r"\s*\([^)]*\)", " ", est)) if w]


def _provincia_por_toponimo(est: str, cerca_de: list, provs_ref: set) -> str | None:
    """Provincia del municipio cuyo nombre abre el de la estación («Jávea Ayuntamiento» → Xàbia/Jávea), solo si ese
    municipio está a menos de 40 km de los que usan la estación de referencia (descarta homónimos lejanos). Si ningún
    municipio abre el nombre, vale uno que aparezca dentro («Castellón-Almassora» → Almassora), pero entonces la
    provincia tiene que ser también la de alguno de los municipios que usan la estación."""
    idx, _ = _municipios_ine()
    pal = _palabras(est)

    def cercanos(clave):
        cands = idx.get(clave) if len(clave) >= 4 else None
        if not cands:
            return None
        return {c for c, la, lo in cands if any(_km((la, lo), q) <= 40 for q in cerca_de)}

    for n in range(len(pal), 0, -1):
        cerca = cercanos(_norm(" ".join(pal[:n])))
        if cerca is not None:
            return next(iter(cerca)) if len(cerca) == 1 else None
    hallados = set()
    for n in range(len(pal) - 1, 0, -1):
        for i in range(1, len(pal) - n + 1):
            cerca = cercanos(_norm(" ".join(pal[i:i + n])))
            if cerca:
                hallados |= cerca
        if hallados:
            break
    if not hallados and pal and len(_norm(pal[0])) >= 5:
        # «Caravaca Fuentes del Marqués» → Caravaca de la Cruz; «Alhama (comarza)» → Alhama de Murcia
        ini = _norm(pal[0])
        hallados = {c for clave, cands in idx.items() if clave.startswith(ini)
                    for c, la, lo in cands if any(_km((la, lo), q) <= 40 for q in cerca_de)}
    hallados &= provs_ref
    return next(iter(hallados)) if len(hallados) == 1 else None


_GENERICAS = {"aeropuerto", "automatica", "ayuntamiento", "deposito", "observatorio", "centro", "base", "aerea", "puerto",
              "embalse", "presa", "faro", "santa", "maria", "san", "villa", "casa", "obs", "aut", "escuela", "instituto"}


def _provincia_por_inventario(est: str, inv_tokens: list, provs_ref: set) -> str | None:
    """Inventario de AEMET con nombre distinto («Tablada» → «SEVILLA, TABLADA»): las palabras significativas de la
    estación (o, si no, la primera) tienen que estar en el nombre del inventario, y la provincia tiene que ser única y
    la de alguno de los municipios que usan la estación."""
    sig = {_norm(w) for w in _palabras(est)} - {""}
    sig = {w for w in sig if len(w) >= 4 and w not in _GENERICAS}
    if not sig:
        return None
    provs = {c for toks, c in inv_tokens if sig <= toks} & provs_ref
    if not provs:
        prim = next((_norm(w) for w in _palabras(est) if _norm(w) in sig), None)
        provs = {c for toks, c in inv_tokens if prim in toks} & provs_ref
    return next(iter(provs)) if len(provs) == 1 else None


def estaciones_lluvia(L: dict) -> dict:
    """Lluvia por estación de AEMET, con solo los valores que ha medido cada una.

    lluvias_municipios.json va por municipio: cada uno lleva su estación de referencia (est) y, si a esa estación le
    faltan horas, el dato de otra cercana (dia_est, hoy_est) o de la vecina más lluviosa (cerca). El 18-10-2026 el
    registro de Pego traía 26,9 mm «de hoy» que eran de Oliva (Pego solo tenía 5 horas). Aquí se rehace por estación.

    estación → {dia, racha, sem (solo si el día anterior está completo, 24 h; si no, dia_min y dia_h), hoy, hoy_h,
    prov (código INE o None)}.
    La provincia sale del inventario de AEMET (nombre exacto) o del municipio que abre el nombre de la estación; si
    las dos fuentes no coinciden, o no hay ninguna, queda None y la estación no se atribuye a ninguna provincia."""
    try:
        inv = leer(PRENSA / "aemet_inventario.json")
    except Exception:
        inv = {}
    por_nombre: dict = {}
    inv_tokens = []
    for _c, (nom, prov, _alt) in inv.items():
        c = cod_provincia(prov)
        if c:
            por_nombre.setdefault(_norm(nom), set()).add(c)
            inv_tokens.append(({_norm(w) for w in _palabras(nom)}, c))
    _idx, pos = _municipios_ine()
    T: dict = {}

    def reg(e):
        return T.setdefault(e.strip(), {"refs": set()})

    for k, m in (L.get("municipios") or {}).items():
        e = (m.get("est") or "").strip()
        completo = m.get("dia_h") == 24
        if e and not m.get("dia_est") and completo:
            reg(e).update(dia=num(m.get("dia")), racha=m.get("racha"), sem=num(m.get("sem")), sem_dias=m.get("sem_dias"))
        elif e and not m.get("dia_est") and m.get("dia") is not None and m.get("dia_h"):
            reg(e).update(dia_min=num(m.get("dia")), dia_h=m.get("dia_h"))  # le faltan horas: es un mínimo
        if m.get("dia_est") and completo:
            reg(m["dia_est"]).setdefault("dia", num(m.get("dia")))
        he = (m.get("hoy_est") or e).strip()
        if he and m.get("hoy") is not None:
            reg(he).update(hoy=num(m.get("hoy")), hoy_h=m.get("hoy_h"))
        c = m.get("cerca") or {}
        if c.get("est") and c.get("mm") is not None:
            r = reg(c["est"])
            r.setdefault("hoy", num(c["mm"]))
            r.setdefault("hoy_h", c.get("h"))
        for x in (e, m.get("dia_est"), m.get("hoy_est"), c.get("est")):
            if x:
                reg(x)["refs"].add(k)
    out = {}
    for e, r in T.items():
        if not e or re.fullmatch(r"[0-9A-Z]{4,6}", e) or "?" in e:
            continue  # sin nombre (solo indicativo) o nombre dañado: no se puede citar
        cerca_de = [pos[k] for k in r["refs"] if k in pos]
        provs_ref = {k[:2] for k in r["refs"]}
        pi = por_nombre.get(_norm(e))
        p_inv = (next(iter(pi)) if len(pi) == 1 else None) if pi else _provincia_por_inventario(e, inv_tokens, provs_ref)
        p_top = _provincia_por_toponimo(e, cerca_de, provs_ref)
        if p_inv and p_top and p_inv != p_top:
            r["prov"] = None
        else:
            r["prov"] = p_inv or p_top
        out[e] = r
    return out


def _nombre_corto(est: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*$", "", est).strip()


def lluvia_aemet():
    try:
        L = leer(DOCS / "lluvias_municipios.json")
    except Exception as e:
        errores.append(f"lluvia_aemet: {e}")
        return
    est = estaciones_lluvia(L)
    if not est:
        return
    n_mun = len(L.get("municipios") or {})
    fuente = L.get("fuente", "AEMET OpenData · observación convencional")
    base = {"serie": "lluvia", "fuente": fuente, "serie_desde": "", "territorio": "España", "ambito": "nacional",
            "pagina": "https://calentamientoglobal.es/lluvia-hoy-espana/", "citabilidad": "alta", "exclusivo": True}

    def donde(e):
        p = est[e].get("prov")
        return f"{_nombre_corto(e)} ({PROVINCIAS[p][0]})" if p in PROVINCIAS else _nombre_corto(e)

    def alcance(n):
        # Las estaciones del fichero son las de referencia de los municipios del mapa, no toda la red de AEMET.
        return (f"La comparación es entre las {n} estaciones de AEMET que usa de referencia el mapa de lluvia de "
                f"calentamientoglobal.es ({n_mun} municipios); AEMET tiene más estaciones y en alguna pudo llover más.")

    def oficial(e):
        return "" if _nombre_corto(e) == e else f" · nombre en AEMET: «{e}»"

    def lider(filas, mm):
        empate = [x for x in filas[1:] if x[0] == mm]
        return "la cifra más alta" + (f" (empatada con {', '.join(donde(x[1]) for x in empate)})" if empate else "")

    # --- ayer, día completo (24 horas) ---------------------------------------------------
    fecha = L.get("fecha")
    filas = sorted(((r["dia"], e) for e, r in est.items() if r.get("dia") is not None), key=lambda x: (-x[0], x[1]))
    parciales = sorted(((e, r) for e, r in est.items() if (r.get("dia_min") or 0) >= 30), key=lambda kv: -kv[1]["dia_min"])
    if fecha and filas and filas[0][0] >= 30:
        mm, e = filas[0]
        n30 = sum(1 for x in filas if x[0] >= 30)
        tit = f"La estación de AEMET de {donde(e)} recogió {f1(mm)} mm el {fecha_dia(fecha)}"
        if len(filas) > 1 and filas[1][0] >= 30:
            tit += f"; la de {donde(filas[1][1])}, {f1(filas[1][0])} mm"
        anadir({**base, "tipo": "lluvia_dia", "fecha_dato": fecha, "indicador": "lluvia_dia_max",
                "titular": tit,
                "dato": (f"{f1(mm)} mm de 0 a 24 h (hora local) del {fecha_dia(fecha)}, {lider(filas, mm)} de las {len(filas)} "
                         f"estaciones de AEMET con las 24 horas que sigue el mapa · {('1 superó' if n30 == 1 else f'{n30} superaron')} los 30 mm{oficial(e)}"),
                "contexto": ["Las que más: " + " · ".join(f"{donde(x[1])}: {f1(x[0])} mm" for x in filas[:5]) + "."]
                + (["Con horas sin dato en AEMET (la cifra es un mínimo): " + " · ".join(
                    f"{donde(e2)}: al menos {f1(r2['dia_min'])} mm ({r2['dia_h']} de 24 horas)" for e2, r2 in parciales) + "."] if parciales else []),
                "metodo": "Suma de la precipitación horaria que publica AEMET OpenData en cada estación de observación convencional, de 0 a 24 h en hora local. Solo estaciones con las 24 horas.",
                "limites": [alcance(len(filas)),
                            "Lluvia de cada estación: en el resto del término municipal pudo llover más o menos.",
                            "Dato de observación en tiempo real; AEMET lo valida después y puede corregirlo."]})
    # --- hoy, hasta la última hora cerrada en toda la red ----------------------------------
    hoy, corte = L.get("hoy_fecha"), L.get("corte_red")
    if hoy and corte:
        filas_h = sorted(((r["hoy"], e) for e, r in est.items() if r.get("hoy") is not None and r.get("hoy_h") == corte),
                         key=lambda x: (-x[0], x[1]))
        if filas_h and filas_h[0][0] >= 20:
            mm, e = filas_h[0]
            tit = f"La estación de AEMET de {donde(e)} lleva {f1(mm)} mm el {fecha_dia(hoy)} hasta las {int(corte)}:00"
            if len(filas_h) > 1 and filas_h[1][0] >= 20:
                tit += f"; la de {donde(filas_h[1][1])}, {f1(filas_h[1][0])} mm"
            anadir({**base, "tipo": "lluvia_en_curso", "fecha_dato": hoy, "indicador": "lluvia_hoy_max",
                    "titular": tit,
                    "dato": (f"{f1(mm)} mm de 0:00 a {int(corte)}:00 (hora local) del {fecha_dia(hoy)}, {lider(filas_h, mm)} "
                             f"de las {len(filas_h)} estaciones de AEMET que sigue el mapa con todas esas horas{oficial(e)}"),
                    "contexto": ["Las que más: " + " · ".join(f"{donde(x[1])}: {f1(x[0])} mm" for x in filas_h[:5]) + "."],
                    "metodo": "Suma de la precipitación horaria que publica AEMET OpenData en cada estación, desde las 0:00 hasta la última hora cerrada en toda la red. Solo estaciones con todas esas horas.",
                    "limites": ["Día en curso: la cifra sube a medida que entran horas. Citar siempre con la hora («hasta las "
                                f"{int(corte)}:00»).", alcance(len(filas_h)),
                                "Dato de observación en tiempo real; AEMET lo valida después y puede corregirlo."]})
            p = est[e].get("prov")
            ENVIVO["lluvia_hoy"] = {"fecha": hoy, "hasta": int(corte), "estacion": _nombre_corto(e),
                                    "provincia": PROVINCIAS[p][0] if p in PROVINCIAS else None, "mm": mm}
    if fecha and filas:
        mm, e = filas[0]
        p = est[e].get("prov")
        ENVIVO["lluvia_ayer"] = {"fecha": fecha, "estacion": _nombre_corto(e),
                                 "provincia": PROVINCIAS[p][0] if p in PROVINCIAS else None, "mm": mm}



# ----------------------------------------------------------------------------
# Récords de temperatura en las estaciones de AEMET · el mismo día
# Los calcula records_detectar.py (clima-scripts) con la observación horaria de
# toda la red contra la tabla oficial de valores extremos de cada estación, y
# los deja ya redactados en docs/records/hallazgos_estaciones.json. Aquí solo
# entran en la cola con su fuerza, su frescura y su revisión; los que el
# verificador ha descartado (el valor validado por AEMET no bate el récord) se
# retiran también del historial de la sala de prensa.
# ----------------------------------------------------------------------------
def estaciones_aemet():
    try:
        R = leer(DOCS / "records" / "hallazgos_estaciones.json")
    except Exception as e:
        errores.append(f"estaciones_aemet: {e}")
        return
    RETIRAR.update(R.get("retirar") or [])
    for h in R.get("hallazgos") or []:
        if h.get("serie") != "estaciones" or h.get("tipo") not in FUERZA or not h.get("fecha_dato"):
            continue
        anadir(dict(h))
    if R.get("hallazgos"):
        vivos = [h for h in R["hallazgos"] if not any("COMPROBAR" in l for l in h.get("limites", []))
                 and h.get("estado") not in ("sin_validar", "descartado")]
        if vivos:
            ult = max(vivos, key=lambda h: (h.get("fecha_dato") or "", 0 if h.get("provisional") else 1))
            ENVIVO["records_estaciones"] = {"n": len(vivos), "ultimo": ult.get("titular"), "fecha": ult.get("fecha_dato"),
                                            "estado": ult.get("estado"), "pagina": R.get("pagina")}


def avisos_envivo():
    """Franja «en vivo»: cuántas zonas tenían aviso rojo o naranja de AEMET a la hora de la consulta (avisos.json se
    rehace cada 30 minutos). Cada zona cuenta una vez, con su nivel más alto entre los avisos vigentes o anunciados."""
    try:
        A = leer(DOCS / "avisos.json")
    except Exception as e:
        errores.append(f"avisos_envivo: {e}")
        return
    if not A.get("generado"):
        return
    orden = {"amarillo": 1, "naranja": 2, "rojo": 3}
    zonas = {}
    for a in A.get("avisos") or []:
        n = a.get("nivel")
        if n not in orden or not a.get("zona"):
            continue
        k = (a.get("cod"), a["zona"])
        if orden[n] > orden.get(zonas.get(k, {}).get("nivel"), 0):
            zonas[k] = {"zona": a["zona"], "provincia": a.get("provincia"), "nivel": n}
    rojas = sorted((z for z in zonas.values() if z["nivel"] == "rojo"), key=lambda z: (z["provincia"] or "", z["zona"]))
    naranjas = sorted((z for z in zonas.values() if z["nivel"] == "naranja"), key=lambda z: (z["provincia"] or "", z["zona"]))
    ENVIVO["avisos"] = {"consulta": A["generado"], "rojo": len(rojas), "naranja": len(naranjas),
                        "zonas_rojo": [f"{z['zona']} ({z['provincia']})" for z in rojas],
                        "provincias_rojo": sorted({z["provincia"] for z in rojas if z["provincia"]}),
                        "provincias_naranja": sorted({z["provincia"] for z in naranjas if z["provincia"]}),
                        "fuente": A.get("fuente", "AEMET vía MeteoAlarm")}


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
                            f"El año {anio} no ha terminado: la cifra puede subir si hay más días de 32 °C.",
                            "COMPROBAR: el recuento de un punto de reanálisis no coincide con el de la estación de AEMET (auditoría del 17-10-2026); no se publica."]
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
                "titular": f"La reserva de agua de España estaba el {fecha_dia(bol)} al {f1(pct)} %, {f1(abs(pct - p10))} puntos {'por encima' if pct > p10 else 'por debajo'} de su media de diez años para esa semana",
                "dato": f"{f1(pct)} % ({miles(nac['volumen_total_hm3'])} de {miles(nac['capacidad_total_hm3'])} hm³) · hace un año {f1(p1a)} % · media 10 años {f1(p10)} %",
                "contexto": [f"Boletín del {fecha_larga(bol)}."]})
    ENVIVO["embalses"] = {"boletin": bol, "pct": pct, "pct_hace_1a": p1a, "pct_media_10a": p10,
                          "volumen_hm3": num(nac.get("volumen_total_hm3")), "capacidad_hm3": num(nac.get("capacidad_total_hm3")), "fuente": "MITECO"}
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
                    "dato": f"{f1(pct)} % ({miles(e.get('volumen_total_hm3'))} de {miles(e.get('capacidad_total_hm3'))} hm³, {e.get('total_embalses')} embalses) · hace un año {f1(p1a) if p1a is not None else '—'} % · media 10 años {f1(p10)} %"})
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
        if h["ambito"] != "provincial" or h.get("requiere_revision"):
            continue
        clave = None
        if h["serie"] == "dias32" and h["tipo"] == "record_absoluto":
            clave = ("dias32_record", h["fecha_dato"][:4])
        elif h["serie"] == "capitales" and h["tipo"] == "record_fecha":
            clave = ("capitales_" + h["indicador"], h["fecha_dato"])
        elif h["serie"] == "capitales" and h["tipo"] in ("record_absoluto", "puesto_extremo"):
            clave = ("capitales_" + h["indicador"], h["fecha_dato"][:4])
        elif h["serie"] == "estaciones" and h["tipo"] in ("record_absoluto", "record_mes"):
            clave = ("estaciones_" + h["indicador"], h["fecha_dato"])
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
            titular = f"{n} capitales españolas registraron el {fecha_dia(cuando)} la mínima más alta para esa fecha en la serie que empieza en 1940"
            dato = "Medido por AEMET: " + "; ".join(f"{h['territorio']} {f1(h['valor'])} °C" for h in lista)
            tipo = "record_fecha"
        elif clave.startswith("capitales_tmax"):
            titular = f"{n} capitales españolas registraron el {fecha_dia(cuando)} la máxima más alta para esa fecha en la serie que empieza en 1940"
            dato = "Medido por AEMET: " + "; ".join(f"{h['territorio']} {f1(h['valor'])} °C" for h in lista)
            tipo = "record_fecha"
        elif clave.startswith("capitales_tmin_baja"):
            titular = f"{n} capitales españolas registraron el {fecha_dia(cuando)} la mínima más baja para esa fecha en la serie que empieza en 1940"
            dato = "Medido por AEMET: " + "; ".join(f"{h['territorio']} {f1(h['valor'])} °C" for h in lista)
            tipo = "record_fecha"
        elif clave.startswith("estaciones_"):
            mes_txt = MESES[int(cuando[5:7]) - 1]
            hoy_todos = all(h.get("cuando") == "HOY" for h in lista)
            cuando_txt = f"hoy, {fecha_dia(cuando)}," if hoy_todos else f"el {fecha_dia(cuando)}"
            if clave.startswith("estaciones_tmax_record_absoluto"):
                titular = (f"{n} estaciones de AEMET {'ya superan' if hoy_todos else 'registraron'} {cuando_txt} la temperatura más alta de toda su serie")
            elif clave.startswith("estaciones_tmax_record_mes"):
                titular = (f"{n} estaciones de AEMET {'ya superan' if hoy_todos else 'batieron'} {cuando_txt} su récord de temperatura máxima para un mes de {mes_txt}")
            elif clave.startswith("estaciones_tmin_record_absoluto"):
                titular = (f"{n} estaciones de AEMET {'ya han bajado' if hoy_todos else 'registraron'} {cuando_txt} {'de' if hoy_todos else ''} la temperatura más baja de toda su serie").replace("  ", " ")
            else:
                titular = (f"{n} estaciones de AEMET {'ya han bajado' if hoy_todos else 'bajaron'} {cuando_txt} de su récord de temperatura mínima para un mes de {mes_txt}")
            orden = sorted(lista, key=lambda h: (-h["valor"] if "tmax" in clave else h["valor"]))
            dato = "Medido por AEMET: " + "; ".join(f"{h['territorio']} {f1(h['valor'])} °C"
                                                     + (f" (anterior {f1(h['record_anterior']['valor'])} °C, {h['record_anterior'].get('anio')})"
                                                        if h.get("record_anterior") and h["record_anterior"].get("valor") is not None else "") for h in orden)
            tipo = p["tipo"]
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
                "ambito": "nacional", "pagina": p["pagina"] if p["serie"] in ("dias32", "estaciones") else "https://calentamientoglobal.es/el-tiempo/",
                "provisional": any(bool(h.get("provisional")) for h in lista) if p["serie"] == "estaciones" else bool(p.get("provisional")),
                "cuando": ("HOY" if all(h.get("cuando") == "HOY" for h in lista) else "") if p["serie"] == "estaciones" else p.get("cuando"),
                "tipo": tipo, "fecha_dato": p["fecha_dato"], "indicador": clave + "_nacional",
                "titular": titular, "dato": dato,
                "contexto": [f"Territorios: {nombres}.", f"Cada uno comparado contra su propia serie desde {p['serie_desde']}."],
                "metodo": ("Valor del día medido por AEMET en la estación de cada capital; récord para la fecha según la serie diaria del "
                           "reanálisis ERA5 (Copernicus) en la celda de cada capital desde 1940, contrastada ese día con la estación."
                           if p["serie"] == "capitales" else re.sub(r"en la celda de [^,]+,", "en la celda de cada capital,", p["metodo"])),
                "limites": p["limites"] if p["serie"] != "estaciones" else
                [l for l in p["limites"] if not l.startswith("Récord de la estación")] + ["Cada estación se compara con su propia tabla de valores extremos; no es un recuento de toda la red: en otras estaciones de AEMET pudo haber más récords."],
                "citabilidad": p["citabilidad"], "aemet": all(h.get("aemet") for h in lista),
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
        u = {k: list(v) for k, v in a["ult30"].items()}
        for f, x, n, p in h.get("prov_dias", []):
            u["f"].append(f); u["tx"].append(x); u["tn"].append(n); u["ll"].append(p)
            u["ntx"].append(None); u["ntn"].append(None); u["nll"].append(None)
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
            if h.get("prov_dias"):
                ax.axvspan(len(u["f"]) - len(h["prov_dias"]) - 0.5, len(u["f"]) - 0.5, color="#fff3e0", zorder=0, label="provisional (IFS)")
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

    if h["serie"] == "estaciones" and h.get("estacion", {}).get("idema"):
        base = leer(DOCS / "records" / "baseline.json")
        e = (base.get("estaciones") or {}).get(h["estacion"]["idema"])
        if not e:
            return None
        var = h.get("variable", "tmax")
        filas = []
        for i in range(12):
            tx, tn = e["tmax"][i], e["tmin"][i]
            filas.append((MESES[i], tx[0], f"{tx[2]}-{i + 1:02d}-{tx[1]:02d}" if tx[0] is not None and tx[2] and tx[1] else "",
                          tn[0], f"{tn[2]}-{i + 1:02d}-{tn[1]:02d}" if tn[0] is not None and tn[2] and tn[1] else ""))

        def plot(plt, out, h, e=e, var=var):
            fig, ax = plt.subplots(figsize=(11, 5.2), dpi=150)
            vals = [e[var][i][0] for i in range(12)]
            mes_h = int(h["fecha_dato"][5:7]) - 1
            colores = ["#c9c9cc"] * 12
            ax.bar(range(12), [v if v is not None else 0 for v in vals], color=colores)
            ax.bar([mes_h], [h["valor"]], color="#cc2200" if var == "tmax" else "#0066cc", width=0.5)
            ax.set_xticks(range(12)); ax.set_xticklabels([m[:3] for m in MESES])
            ax.axhline(h["valor"], color="#cc2200" if var == "tmax" else "#0066cc", lw=1, ls="--",
                       label=f"{fecha_dia(h['fecha_dato'])}: {f1(h['valor'])} °C")
            _estilo(ax, plt, f"{h['territorio']} · récord de {'máxima' if var == 'tmax' else 'mínima'} de cada mes en la estación de AEMET", h)
            fig.savefig(out, bbox_inches="tight"); plt.close(fig)
        return {"cabecera": ["mes", "record_tmax_C", "fecha_record_tmax", "record_tmin_C", "fecha_record_tmin"], "filas": filas, "plot": plot}

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

    for fn in (capitales, capitales_ayer, lluvia_aemet, estaciones_aemet, avisos_envivo, mediterraneo, danas, dias32, embalses, caudal, planeta):
        try:
            fn()
        except Exception as e:
            errores.append(f"{fn.__name__}: {e}")

    # regla de publicación: contraste con AEMET de todo lo que es cifra de una capital
    conservar = []
    for h in hallazgos:
        if confirmar_con_aemet(h):
            h["requiere_revision"] = any("COMPROBAR" in l for l in h["limites"])
            conservar.append(h)
    hallazgos[:] = [h for h in conservar if h["id"] not in RETIRAR]
    agregar()
    for h in hallazgos:
        if h.get("ambito") == "nacional" and h.get("serie") == "capitales" and not h.get("indicador", "").startswith("ayer_"):
            h["requiere_revision"] = any("COMPROBAR" in l for l in h["limites"])
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
        # lo publicable primero y aparte; lo que espera revisión (p. ej. confirmación de AEMET) no ocupa sitio
        "enviables": [h for h in unicos if h["citabilidad"] in ("alta", "media") and not h["requiere_revision"]][:25],
        "en_revision": [h for h in unicos if h["citabilidad"] in ("alta", "media") and h["requiere_revision"]][:60],
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
    for rid in RETIRAR:
        hist.pop(rid, None)
    for h in salida["enviables"] + [l for l in locales if not l["requiere_revision"]]:
        x = hist.get(h["id"]) or {"id": h["id"], "primera_vez": hoy}
        x.update({"ultima_vez": hoy, "titular": h["titular"], "dato": h["dato"], "fecha_dato": h["fecha_dato"],
                  "serie": h["serie"], "tipo": h["tipo"], "ambito": h["ambito"], "territorio": h["territorio"],
                  "provincia_slug": h.get("provincia_slug"), "citabilidad": h["citabilidad"], "exclusivo": h["exclusivo"],
                  "fuerza": h["fuerza"], "pagina": h.get("pagina"), "dossier": h.get("dossier"),
                  "grafico": h.get("grafico"), "csv": h.get("csv"), "requiere_revision": h["requiere_revision"],
                  "provisional": bool(h.get("provisional"))})
        hist[h["id"]] = x
        x["aemet"] = bool(h.get("aemet"))
    limite = (HOY - timedelta(days=60)).isoformat()

    def sigue_valiendo(x):
        if x.get("requiere_revision") or x.get("serie") == "dias32" or x.get("tipo") == "lluvia_en_curso":
            return False
        if x.get("serie") == "capitales" and not x.get("aemet"):
            return False
        return x["ultima_vez"] >= limite
    lista = sorted((x for x in hist.values() if sigue_valiendo(x)), key=lambda x: (x["fecha_dato"], x["fuerza"]), reverse=True)
    with open(hist_p, "w", encoding="utf-8") as f:
        json.dump({"generado": salida["generado"], "dias": 60, "hallazgos": lista}, f, ensure_ascii=False, indent=1)
    ENVIVO["generado"] = salida["generado"]
    with open(Path(args.salida).parent / "envivo.json", "w", encoding="utf-8") as f:
        json.dump(ENVIVO, f, ensure_ascii=False, indent=1)
    print(f"{len(unicos)} hallazgos · enviables {len(salida['enviables'])} · en revisión {len(salida['en_revision'])} · locales {len(locales)} · contexto {len(salida['contexto'])} · descartes {len(descartes)} · errores {len(errores)}")
    for h in salida["enviables"][:15]:
        print(f"  [{h['fuerza']:5.1f}] {h['citabilidad']:8s} {h['titular']}")
    for e in errores:
        print("  !", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
