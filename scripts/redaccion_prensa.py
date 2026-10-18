#!/usr/bin/env python3
"""Redacción de la sala de prensa de calentamientoglobal.es (18-10-2026).

Convierte los datos del observatorio en HISTORIAS publicables, no en cifras sueltas:

  1. Generadores: cada uno mira una parte de los datos (avisos + lluvia + mar, Mediterráneo, lluvia frente a
     sequía, tendencias de temporada, embalses, récords de capitales confirmados por AEMET) y, si hay noticia,
     devuelve una historia con sus HECHOS: frases ya verificadas, cada una con su fuente.
  2. Puntuación: lo raro, lo grande, lo que afecta a más gente y lo que pasa ahora sube.
  3. Redacción: Claude escribe titular, subtítulo, entradilla, cuerpo y claves a partir de los hechos y nada
     más. Un VERIFICADOR comprueba cada cifra, hora, nombre propio y palabra delicada contra los hechos. Si no
     pasa (dos intentos), se publica el texto de plantilla, que se construye con los propios hechos.
  4. Versiones por provincia de cada historia, con sus estaciones, sus avisos y su capital.
  5. Gráfico SVG + CSV por historia (el PNG lo compone el navegador).

Salida en docs/prensa/noticias/: hoy.json (portada), historias/<id>.json (una por historia, URL fija),
graficos/<id>*.svg|csv y archivo.json (60 días). La caché de textos evita llamar a la API si los
hechos no han cambiado.

IA solo gratuita (sin tarjeta, coste cero): GEMINI_API_KEY (Google AI Studio) y/o GROQ_API_KEY. Si se agota el cupo
gratuito, la petición falla y sale la plantilla; sin ninguna clave, todo sale de plantilla. GEMINI_MODELO / GROQ_MODELO
fuerzan un modelo. Topes: REDACCION_MAX_LLAMADAS por pasada (8) y REDACCION_MAX_DIA por día (150), en uso_ia.json.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import statistics as st
import time
import sys
import unicodedata
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hallazgos_prensa as H  # noqa: E402

DOCS = H.DOCS
PRENSA = DOCS / "prensa"
SALIDA = PRENSA / "noticias"
MADRID = ZoneInfo("Europe/Madrid")
AHORA = datetime.now(timezone.utc)
HOY = AHORA.astimezone(MADRID).date()
AYER = HOY - timedelta(days=1)
PROV = H.PROVINCIAS
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MED_COSTA = {"17", "08", "43", "12", "46", "03", "30", "04", "18", "29", "07", "51", "52"}
EFEMERIDES = [  # (fecha, texto corto, texto largo)
    (date(2024, 10, 29), "la DANA de 2024", "la DANA del 29 de octubre de 2024 en la provincia de Valencia"),
]
LOG: list[str] = []


# ============================================================================ formato
def d1(x) -> str:
    """Siempre un decimal, coma decimal: 21,0."""
    return f"{float(x):.1f}".replace(".", ",")


f1 = H.f1  # 24,3 · 39 · 0,5


def miles(n) -> str:
    return f"{int(round(float(n))):,}".replace(",", ".")


def dia(iso, anio=False, semana=True) -> str:
    d = date.fromisoformat(str(iso)[:10])
    s = (f"{DIAS[d.weekday()]} " if semana else "") + f"{d.day} de {MESES[d.month - 1]}"
    return s + (f" de {d.year}" if anio else "")


def hora(iso) -> str:
    """'2026-10-18T09:01+02:00' → '9:01' (la hora que trae el fichero, que ya es la de España)."""
    m = re.search(r"T(\d{2}):(\d{2})", str(iso))
    return f"{int(m.group(1))}:{m.group(2)}" if m else ""


def lista_y(xs) -> str:
    xs = [x for x in xs if x]
    return xs[0] if len(xs) == 1 else (", ".join(xs[:-1]) + " y " + xs[-1] if xs else "")


def sin_tildes(s) -> str:
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()


def slugify(s) -> str:
    return re.sub(r"[^a-z0-9]+", "-", sin_tildes(s).lower()).strip("-")


def plural(n, uno, varios) -> str:
    return f"{n} {uno if n == 1 else varios}"


def leer(p, defecto=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return defecto


def nprov(cod) -> str:
    return PROV[cod][0] if cod in PROV else ""


NUM_PAL = {2: "dos", 3: "tres", 4: "cuatro", 5: "cinco", 6: "seis", 7: "siete", 8: "ocho", 9: "nueve", 10: "diez",
           11: "once", 12: "doce", 13: "trece", 14: "catorce", 15: "quince", 20: "veinte", 30: "treinta"}

_ZONA_COMUN = {"Litoral": "el", "Interior": "el", "Sur": "el", "Norte": "el", "Centro": "el", "Este": "el", "Oeste": "el",
               "Sudeste": "el", "Sureste": "el", "Noroeste": "el", "Nordeste": "el", "Noreste": "el", "Suroeste": "el",
               "Sudoeste": "el", "Campiña": "la", "Vega": "la", "Sierra": "la", "Montaña": "la"}


def zona_txt(z) -> str:
    """'Litoral norte de Alicante' → 'el litoral norte de Alicante'; 'Grazalema' → 'Grazalema'."""
    p = z.split(" ", 1)
    if p[0] in _ZONA_COMUN:
        return f"{_ZONA_COMUN[p[0]]} {p[0].lower()}" + (f" {p[1]}" if len(p) > 1 else "")
    return z


def dia_corto(iso) -> str:
    d = date.fromisoformat(str(iso)[:10])
    return f"{DIAS[d.weekday()]} {d.day}"


def tramo_txt(ini, fin, consulta) -> str:
    """«de las 10:00 del domingo 18 a las 9:59 del lunes 19 de octubre» (el mes, una vez)."""
    c = datetime.fromisoformat(consulta)
    i, f = datetime.fromisoformat(ini), datetime.fromisoformat(fin)
    if i <= c:
        return f"hasta las {hora(fin)} del {dia(fin)}"
    if i.month == f.month:
        return f"de las {hora(ini)} del {dia_corto(ini)} a las {hora(fin)} del {dia(fin)}"
    return f"de las {hora(ini)} del {dia(ini)} a las {hora(fin)} del {dia(fin)}"


# ============================================================================ hechos
def hecho(id_, dice, fuente, valores=(), lugar=None, superlativo=False, record=False, alias=(), nota=None, liga=()):
    """Un hecho es una frase verdadera y comprobada. El redactor solo puede usar lo que dicen los hechos."""
    # liga: cifras que pertenecen a «lugar» (si el texto las usa, el lugar tiene que ir en la misma frase)
    return {"id": id_, "dice": dice, "fuente": fuente, "valores": list(valores), "lugar": lugar,
            "superlativo": superlativo, "record": record, "alias": list(alias), "nota": nota, "liga": list(liga)}


# ============================================================================ datos
class Datos:
    def __init__(self):
        self.L = leer(DOCS / "lluvias_municipios.json", {}) or {}
        self.E = H.estaciones_lluvia(self.L) if self.L.get("municipios") else {}
        self.A = leer(DOCS / "avisos.json", {}) or {}
        self.M = leer(DOCS / "dana" / "mediterraneo.json", {}) or {}
        self.MH = (leer(DOCS / "dana" / "mediterraneo_historico.json", {}) or {}).get("v", {})
        self.EMB = leer(DOCS / "embalses.json", {}) or {}
        self.HALL = leer(PRENSA / "hallazgos.json", {}) or {}
        self.PAQ = leer(PRENSA / "paquetes" / "index.json", {}) or {}
        self.MAPA = leer(SALIDA / "base" / "mapa_espana.json", {}) or {}
        self.corte = self.L.get("corte_red")
        self.consulta = self.A.get("generado")

    def nom(self, e):
        return H._nombre_corto(e)

    def donde(self, e):
        p = self.E[e].get("prov")
        return f"{self.nom(e)} ({nprov(p)})" if p in PROV else self.nom(e)


# ============================================================================ avisos
def avisos_por_zona(D: Datos):
    orden = {"amarillo": 1, "naranja": 2, "rojo": 3}
    z = {}
    for a in D.A.get("avisos") or []:
        if a.get("nivel") not in orden or not a.get("zona"):
            continue
        k = (a.get("cod"), a["zona"])
        r = z.setdefault(k, {"cod": a.get("cod"), "zona": a["zona"], "prov": a.get("provincia"), "nivel": "amarillo", "avisos": []})
        r["avisos"].append(a)
        if orden[a["nivel"]] > orden[r["nivel"]]:
            r["nivel"] = a["nivel"]
    for r in z.values():
        top = [a for a in r["avisos"] if a["nivel"] == r["nivel"]]
        r["tipos"] = sorted({(a.get("tipo") or "").lower() for a in top if a.get("tipo")})
        r["tramos"] = unir_tramos(top)
    return z


def unir_tramos(avs):
    xs = sorted((datetime.fromisoformat(a["inicio"]), datetime.fromisoformat(a["fin"]), a["inicio"], a["fin"])
                for a in avs if a.get("inicio") and a.get("fin"))
    out = []
    for i, f, i_s, f_s in xs:
        if out and (i - out[-1][1]).total_seconds() <= 60:
            if f > out[-1][1]:
                out[-1][1], out[-1][3] = f, f_s
        else:
            out.append([i, f, i_s, f_s])
    return out


# ============================================================================ Mediterráneo
def mediterraneo_resumen(D: Datos):
    if not D.M.get("ultimo") or not D.MH:
        return None
    v = {date.fromisoformat(k): x for k, x in D.MH.items()}
    ult = date.fromisoformat(D.M["ultimo"])
    r = {"ultimo": D.M["ultimo"], "sst": D.M["sst"], "normal": D.M["normal"], "anom": D.M["anomalia"], "zona": D.M.get("zona")}
    falt = [d for d in (date(ult.year, 1, 1) + timedelta(i) for i in range((ult - date(ult.year, 1, 1)).days + 1)) if d not in v]
    excl = {(d.month, d.day) for d in falt}
    ytd = []
    for y in range(1982, ult.year + 1):
        dias_ = [date(y, 1, 1) + timedelta(i) for i in range((date(y, ult.month, ult.day) - date(y, 1, 1)).days + 1)]
        zs = [v.get(d) for d in dias_ if (d.month, d.day) not in excl]
        if None not in zs and zs:
            ytd.append((st.mean(zs), y))
    ytd.sort(reverse=True)
    r["ytd"] = ytd
    r["ytd_puesto"] = next((i + 1 for i, (m, y) in enumerate(ytd) if y == ult.year), None)
    r["faltan"] = [d.isoformat() for d in falt]
    rec, por_mes, dud = 0, {}, []
    for i in range((ult - date(ult.year, 1, 1)).days + 1):
        d = date(ult.year, 1, 1) + timedelta(i)
        x = v.get(d)
        prev = [v.get(date(yy, d.month, d.day)) for yy in range(1982, ult.year) if not (d.month == 2 and d.day == 29)]
        prev = [p for p in prev if p is not None]
        if x is None or not prev or x <= max(prev):
            continue
        if (ult - d).days < 14 and x - max(prev) < 0.1:
            dud.append(d.isoformat())
            continue
        rec += 1
        por_mes[d.month] = por_mes.get(d.month, 0) + 1
    r["records"], r["records_mes"], r["records_dudosos"] = rec, por_mes, dud
    mx = max(D.MH.items(), key=lambda kv: kv[1])
    r["max_abs"] = mx
    r["v"] = v
    return r


# ============================================================================ generadores
def g_episodio(D: Datos, med):
    """Avisos naranja/rojo + lluvia medida + mar caliente + efemérides: la historia de última hora."""
    if not D.consulta or not D.E:
        return None
    zonas = avisos_por_zona(D)
    rojas = [z for z in zonas.values() if z["nivel"] == "rojo"]
    naranjas = [z for z in zonas.values() if z["nivel"] == "naranja"]
    hoy_f, corte = D.L.get("hoy_fecha"), D.corte
    filas_h = sorted(((r["hoy"], e) for e, r in D.E.items() if r.get("hoy") is not None and r.get("hoy_h") == corte), key=lambda x: (-x[0], x[1]))
    filas_a = sorted(((r["dia"], e) for e, r in D.E.items() if r.get("dia") is not None), key=lambda x: (-x[0], x[1]))
    lluvia_fuerte = (filas_h and filas_h[0][0] >= 40) or (filas_a and filas_a[0][0] >= 60)
    if not rojas and len(naranjas) < 4 and not lluvia_fuerte:
        return None
    c = D.consulta
    hechos, cifras = [], []
    fuente_av = D.A.get("fuente", "AEMET vía MeteoAlarm")
    tipos_r = sorted({t for z in rojas for t in z["tipos"]})
    if rojas:
        fir = {tuple((t[2], t[3]) for t in z["tramos"]) for z in rojas}
        if len(fir) == 1 and len(rojas[0]["tramos"]) == 1:
            t = rojas[0]["tramos"][0]
            tr = " " + tramo_txt(t[2], t[3], c)
        else:
            tr = ""
        zt = lista_y([zona_txt(z["zona"]) for z in sorted(rojas, key=lambda z: (sin_tildes(z["prov"] or ""), z["zona"]))])
        hechos.append(hecho("aviso_rojo", f"A las {hora(c)} del {dia(c)}, AEMET tenía emitido un aviso rojo por {lista_y(tipos_r)} en {zt},{tr}.".replace(",.", ".").replace(", .", "."),
                            fuente_av, [hora(c)] + [hora(t[2]) for z in rojas for t in z["tramos"]] + [hora(t[3]) for z in rojas for t in z["tramos"]]))
        if not tr:
            for z in rojas:
                hechos.append(hecho(f"tramo_{slugify(z['zona'])}", f"En {zona_txt(z['zona'])}, el aviso rojo va " + "; ".join(tramo_txt(t[2], t[3], c) for t in z["tramos"]) + ".", fuente_av))
    if naranjas:
        provs = sorted({z["prov"] for z in naranjas if z["prov"]}, key=sin_tildes)
        txt = (f"A esa hora había además otras {len(naranjas)} zonas en aviso naranja" if rojas else
               f"A las {hora(c)} del {dia(c)}, AEMET tenía {len(naranjas)} zonas en aviso naranja") + f", en {lista_y(provs)}."
        if len(naranjas) == 1:
            txt = txt.replace("otras 1 zonas", "otra zona").replace("1 zonas", "una zona")
        hechos.append(hecho("avisos_naranja", txt, fuente_av, [str(len(naranjas)), hora(c)]))
    if filas_h and filas_h[0][0] >= 10:
        mm, e = filas_h[0]
        hechos.append(hecho("lluvia_hoy_1", f"Entre la medianoche y las {corte}:00 del {dia(hoy_f)}, la estación de AEMET de {D.donde(e)} recogió {f1(mm)} mm, "
                            f"la cifra más alta de las {len(filas_h)} estaciones de AEMET que sigue el observatorio con datos de todas esas horas.",
                            "AEMET OpenData", [f"{f1(mm)} mm", f"{corte}:00", str(len(filas_h))], lugar=D.nom(e), superlativo=True, liga=[f"{f1(mm)} mm"]))
        cifras.append({"n": f"{f1(mm)} mm", "l": f"en {D.donde(e)} entre la medianoche y las {corte}:00 del {dia(hoy_f)}", "tono": "lluvia"})
        if len(filas_h) > 1 and filas_h[1][0] >= 10:
            mm2, e2 = filas_h[1]
            hechos.append(hecho("lluvia_hoy_2", f"La segunda cifra más alta a esa hora fue la de {D.donde(e2)}, con {f1(mm2)} mm.", "AEMET OpenData",
                                [f"{f1(mm2)} mm"], lugar=D.nom(e2), superlativo=True, liga=[f"{f1(mm2)} mm"]))
    if filas_a and filas_a[0][0] >= 20:
        mm, e = filas_a[0]
        hechos.append(hecho("lluvia_ayer_1", f"El {dia(D.L['fecha'])}, la estación de AEMET que más recogió fue la de {D.donde(e)}, con {f1(mm)} mm en todo el día.",
                            "AEMET OpenData", [f"{f1(mm)} mm"], lugar=D.nom(e), superlativo=True, liga=[f"{f1(mm)} mm"]))
    mar = False
    if med and med["anom"] >= 1.5 and (date.fromisoformat(med["ultimo"]) >= HOY - timedelta(days=4)):
        mar = True
        hechos.extend(hechos_mar(med, corto=True))
        cifras.insert(0, {"n": f"{d1(med['sst'])} °C", "l": f"el Mediterráneo español el {dia(med['ultimo'])}, {f1(med['anom'])} °C por encima de lo normal para ese día", "tono": "calor"})
        if med.get("records"):
            cifras.insert(1, {"n": f"{med['records']} días", "l": f"de {med['ultimo'][:4]} han batido el récord de temperatura del mar para su fecha", "tono": "calor"})
        if med.get("ytd_puesto") == 1:
            cifras.insert(2, {"n": f"{d1(med['ytd'][0][0])} °C", "l": f"de media entre el 1 de enero y el {dia(med['ultimo'], semana=False)}: la más alta desde 1982", "tono": "calor"})
        hechos.append(hecho("mar_contexto", "Un mar más caliente evapora más agua y aporta más humedad a las tormentas de otoño: es uno de los ingredientes de las "
                            "lluvias torrenciales en el Mediterráneo, aunque por sí solo no las provoca.", "Conocimiento meteorológico general", nota="contexto"))
    for f_ef, corto, largo in EFEMERIDES:
        cumple = date(HOY.year, f_ef.month, f_ef.day)
        faltan = (cumple - HOY).days
        if 0 <= faltan <= 14 and (rojas or naranjas):
            anios = HOY.year - f_ef.year
            ord_ = {1: "primer", 2: "segundo", 3: "tercer", 4: "cuarto", 5: "quinto"}.get(anios, f"{anios}.º")
            hechos.append(hecho("efemeride", f"Faltan {faltan} días para el {ord_} aniversario de {largo}." if faltan else f"Este {dia(cumple)} se cumple el {ord_} aniversario de {largo}.",
                                "Calendario", [str(faltan)], alias=[f"{NUM_PAL.get(faltan, faltan)} días", f"{ord_} aniversario"]))
            if mar and med:
                v24 = med["v"].get(date(f_ef.year, date.fromisoformat(med["ultimo"]).month, date.fromisoformat(med["ultimo"]).day))
                if v24 is not None:
                    hechos.append(hecho("mar_hace", f"El {dia(med['ultimo'], semana=False)} de {f_ef.year}, {(f_ef - date(f_ef.year, date.fromisoformat(med['ultimo']).month, date.fromisoformat(med['ultimo']).day)).days} días antes de {corto}, "
                                        f"el mismo mar estaba a {d1(v24)} °C: {d1(med['sst'] - v24)} °C menos que en {med['ultimo'][:4]} en la misma fecha.",
                                        "NOAA OISST v2.1", [f"{d1(v24)} °C", f"{d1(med['sst'] - v24)} °C"]))
    if rojas:
        prov_r = lista_y(sorted({z["prov"] for z in rojas}, key=sin_tildes))
        zcorta = lista_y([zona_txt(z["zona"]) for z in sorted(rojas, key=lambda z: (sin_tildes(z["prov"] or ""), z["zona"]))])
        tit = f"Aviso rojo por {lista_y(tipos_r)} en {zcorta}" + (f" con el Mediterráneo {f1(med['anom'])} °C más caliente de lo normal" if mar else "")
        kicker = "Última hora · " + ("Lluvia y Mediterráneo" if mar else "Avisos de AEMET")
        puntos = 100 + len(rojas)
        slug_ = f"{HOY.isoformat()}-aviso-rojo-{slugify(prov_r)}"
    elif naranjas:
        tit = f"Aviso naranja en {len(naranjas)} zonas de {lista_y(sorted({z['prov'] for z in naranjas if z['prov']}, key=sin_tildes))}" + (f" con el Mediterráneo {f1(med['anom'])} °C más caliente de lo normal" if mar else "")
        kicker = "Última hora · Avisos de AEMET"
        puntos = 85 + len(naranjas)
        slug_ = f"{HOY.isoformat()}-avisos-naranja"
    else:
        mm, e = filas_h[0] if filas_h and filas_h[0][0] >= 40 else filas_a[0]
        tit = hechos[0]["dice"].split(",")[0]
        kicker = "Última hora · Lluvia"
        puntos = 80
        slug_ = f"{HOY.isoformat()}-lluvia-{slugify(D.nom(e))}"
    sub = [h["dice"] for h in hechos if h["id"] in ("mar_anio", "efemeride")]
    plantilla = {
        "titular": tit,
        "subtitulo": " ".join(sub) if sub else next((h["dice"] for h in hechos if h["id"].startswith("lluvia")), ""),
        "entradilla": " ".join(h["dice"] for h in hechos if h["id"] in ("aviso_rojo", "mar_hoy")) or hechos[0]["dice"],
        "cuerpo": [p for p in [
            " ".join(h["dice"] for h in hechos if h["id"].startswith("lluvia")),
            " ".join(h["dice"] for h in hechos if h["id"] in ("mar_anio", "mar_records", "mar_max")),
            " ".join(h["dice"] for h in hechos if h["id"] in ("mar_hace", "efemeride")),
            " ".join(h["dice"] for h in hechos if h["id"] == "mar_contexto"),
            " ".join(h["dice"] for h in hechos if h["id"].startswith("tramo_") or h["id"] == "avisos_naranja")
            + (" AEMET actualiza los avisos varias veces al día: el estado vigente está en aemet.es." if (rojas or naranjas) else ""),
        ] if p.strip()],
        "claves": [h["dice"] for h in hechos if h["id"] in ("aviso_rojo", "mar_hoy", "mar_records", "lluvia_hoy_1")][:4],
    }
    h = historia("episodio", slug_, kicker, "calor" if mar else "lluvia", puntos, hechos, plantilla, cifras[:4],
                 fuentes="AEMET (avisos vía MeteoAlarm; observación horaria de AEMET OpenData)" + (" y NOAA OISST v2.1" if mar else ""),
                 metodo="Avisos de AEMET consultados a la hora indicada. Lluvia: suma de la precipitación horaria de cada estación de AEMET; solo estaciones con todas las horas del periodo."
                 + (" Mar: media diaria de la caja 36,5-41,5° N y 1,5° O-5° E; normal y rango habitual de 1991-2020." if mar else ""),
                 limites=["Los avisos cambian varias veces al día: comprobar el estado vigente en aemet.es.",
                          "El observatorio sigue las estaciones de AEMET de referencia de los municipios de su mapa de lluvia, no toda la red."]
                 + (["El dato del mar de los últimos 14 días es preliminar."] if mar else []),
                 pagina="https://calentamientoglobal.es/avisos-meteorologicos/")
    h["grafico"] = grafico_mar(med, h["id"]) if mar else grafico_barras_lluvia(D, filas_h, h["id"], f"Lluvia entre la medianoche y las {corte}:00 del {dia(hoy_f)}")
    h["ultima_hora"] = []
    if rojas:
        h["ultima_hora"].append({"hora": hora(c), "texto": f"AEMET: aviso rojo por {lista_y(tipos_r)} en {zcorta}", "tono": "aviso"})
    if filas_h and filas_h[0][0] >= 10:
        h["ultima_hora"].append({"hora": f"{corte}:00", "texto": f"{D.donde(filas_h[0][1])} lleva {f1(filas_h[0][0])} mm desde la medianoche", "tono": "lluvia"})
    if filas_a and filas_a[0][0] >= 20:
        h["ultima_hora"].append({"hora": dia(D.L["fecha"], semana=True).split(" ")[0][:3].capitalize() + " " + str(date.fromisoformat(D.L["fecha"]).day),
                                 "texto": f"{D.donde(filas_a[0][1])} recogió {f1(filas_a[0][0])} mm", "tono": "lluvia"})
    # versiones provinciales: provincias con aviso naranja/rojo o lluvia
    if rojas:
        ctx_nac = hecho("nacional", f"En el conjunto de España, a esa hora había aviso rojo en {zt}" + (f" y aviso naranja en {len(naranjas)} zonas más." if naranjas else "."),
                        fuente_av, [str(len(naranjas))])
    elif naranjas:
        ctx_nac = hecho("nacional", f"En el conjunto de España, a esa hora había {len(naranjas)} zonas en aviso naranja.", fuente_av, [str(len(naranjas))])
    else:
        ctx_nac = next((x for x in hechos if x["id"] == "lluvia_hoy_1"), None)
    for cod in PROV:
        v = version_episodio(D, cod, zonas, filas_h, filas_a, med if mar else None, c, nac_ctx=ctx_nac, hid=h["id"])
        if v:
            h["provincias"][cod] = v
    return h


def hechos_mar(med, corto=False):
    u = med["ultimo"]
    out = [hecho("mar_hoy", f"El Mediterráneo español (de Alborán al mar Balear) estaba a {d1(med['sst'])} °C el {dia(u)}, {f1(med['anom'])} °C por encima de su normal "
                 f"de 1991-2020 para ese día, según los datos de satélite de la NOAA.", "NOAA OISST v2.1", [f"{d1(med['sst'])} °C", f"{f1(med['anom'])} °C", "1991", "2020"])]
    if med.get("ytd_puesto") == 1 and len(med["ytd"]) > 1:
        (m1, y1), (m2, y2) = med["ytd"][0], med["ytd"][1]
        dif = round(m1 - m2, 1)
        dif_txt = "una décima" if dif == 0.1 else f"{d1(dif)} °C"
        out.append(hecho("mar_anio", f"Entre el 1 de enero y el {dia(u, semana=False)}, su temperatura media fue de {d1(m1)} °C, la más alta para ese periodo desde 1982 "
                         f"y {dif_txt} por encima de la de {y2} ({d1(m2)} °C), el anterior máximo.", "NOAA OISST v2.1", [f"{d1(m1)} °C", f"{d1(m2)} °C", "1982", str(y2)],
                         superlativo=True, record=True, alias=["año más cálido", "a estas alturas"]))
    if med.get("records"):
        mm = max(med["records_mes"].items(), key=lambda kv: kv[1])
        out.append(hecho("mar_records", f"En {u[:4]}, {med['records']} días han batido el récord de temperatura del mar para su fecha en la serie que empieza en 1982; "
                         f"{mm[1]} de ellos, en {MESES[mm[0] - 1]}.", "NOAA OISST v2.1", [str(med["records"]), str(mm[1])], record=True))
    fmax, vmax = med["max_abs"]
    if fmax[:4] == u[:4]:
        out.append(hecho("mar_max", f"El {dia(fmax, semana=False)} el agua llegó a {d1(vmax)} °C, el valor más alto de toda la serie.", "NOAA OISST v2.1",
                         [f"{d1(vmax)} °C"], superlativo=True, record=True))
    return out


def version_episodio(D, cod, zonas, filas_h, filas_a, med, c, nac_ctx=None, hid="episodio"):
    mis = [z for z in zonas.values() if z["cod"] == cod and z["nivel"] in ("rojo", "naranja")]
    h_p = [(mm, e) for mm, e in filas_h if D.E[e].get("prov") == cod]
    a_p = [(mm, e) for mm, e in filas_a if D.E[e].get("prov") == cod]
    llueve = (h_p and h_p[0][0] >= 10) or (a_p and a_p[0][0] >= 20)
    if not mis and not llueve:
        return None
    P = nprov(cod)
    hechos, cifras = [], []
    fuente_av = D.A.get("fuente", "AEMET vía MeteoAlarm")
    zs_ord = sorted(mis, key=lambda z: (z["nivel"] != "rojo", z["zona"]))
    raras2 = len(zs_ord) == 2 and any(" y " in z["zona"] or "," in z["zona"] for z in zs_ord)
    if raras2:  # el titular irá con «2 zonas de …» y la entradilla las nombra; aquí, el horario de cada una
        for z in zs_ord:
            hechos.append(hecho(f"aviso_{slugify(z['zona'])}", f"En {zona_txt(z['zona'])}, el aviso {z['nivel']} por {lista_y(z['tipos'])} va "
                                + "; ".join(tramo_txt(t[2], t[3], c) for t in z["tramos"]) + ".", fuente_av))
    elif len(zs_ord) <= 2:
        for i, z in enumerate(zs_ord):
            pre = f"A las {hora(c)} del {dia(c)}, AEMET tenía" if i == 0 else "También tenía"
            hechos.append(hecho(f"aviso_{slugify(z['zona'])}", f"{pre} aviso {z['nivel']} por {lista_y(z['tipos'])} en {zona_txt(z['zona'])}{'' if sin_tildes(P).lower() in sin_tildes(z['zona']).lower() else f' ({P})'}, "
                                + "; ".join(tramo_txt(t[2], t[3], c) for t in z["tramos"]) + ".", fuente_av, [hora(c)]))
    else:
        hechos.append(hecho("avisos_tramos", "Tramos de cada zona: " + "; ".join(f"{zona_txt(z['zona'])}, aviso {z['nivel']} "
                                                                            + " y ".join(tramo_txt(t[2], t[3], c) for t in z["tramos"]) for z in zs_ord) + ".", fuente_av))
        rz = [z for z in zs_ord if z["nivel"] == "rojo"]
        nz = [z for z in zs_ord if z["nivel"] != "rojo"]
        if 0 < len(rz) <= 2:
            zr = lista_y([zona_txt(z["zona"]) for z in rz])
            zr = zr if sin_tildes(P).lower() in sin_tildes(zr).lower() else f"{zr} ({P})"
            otras = "otra zona de la provincia" if len(nz) == 1 else f"otras {len(nz)} zonas de la provincia"
            hechos.insert(0, hecho("avisos_p", f"A las {hora(c)} del {dia(c)}, AEMET tenía aviso rojo por {lista_y(sorted({t for z in rz for t in z['tipos']}))} en {zr} "
                                   f"y aviso naranja en {otras}: {lista_y([zona_txt(z['zona']) for z in nz])}.", fuente_av, [hora(c), str(len(nz))]))
    if h_p and h_p[0][0] >= 1:
        mm, e = h_p[0]
        hechos.append(hecho("lluvia_hoy_p", f"Entre la medianoche y las {D.corte}:00 del {dia(D.L['hoy_fecha'])}, la estación de AEMET de {D.nom(e)} recogió {f1(mm)} mm, "
                            + ("en la única estación de AEMET de la provincia que sigue el observatorio con datos de todas esas horas." if len(h_p) == 1 else
                               f"la cifra más alta de las {len(h_p)} estaciones de AEMET de la provincia que sigue el observatorio con datos de todas esas horas."),
                            "AEMET OpenData", [f"{f1(mm)} mm", str(len(h_p))], lugar=D.nom(e), superlativo=True, liga=[f"{f1(mm)} mm"]))
        cifras.append({"n": f"{f1(mm)} mm", "l": f"en {D.nom(e)} hasta las {D.corte}:00 del {dia(D.L['hoy_fecha'])}", "tono": "lluvia"})
        otras = [f"{D.nom(x)} ({f1(m)} mm)" for m, x in h_p[1:4] if m >= 1]
        if otras:
            hechos.append(hecho("lluvia_hoy_p2", f"{'Le sigue' if len(otras) == 1 else 'Le siguen'} {lista_y(otras)}.", "AEMET OpenData", [f1(m) for m, x in h_p[1:4]]))
    if a_p and a_p[0][0] >= 5:
        mm, e = a_p[0]
        hechos.append(hecho("lluvia_ayer_p", f"El {dia(D.L['fecha'])}, la estación de AEMET de {D.nom(e)} recogió {f1(mm)} mm, la cifra más alta de las {len(a_p)} "
                            f"de la provincia que sigue el observatorio con las 24 horas del día.", "AEMET OpenData", [f"{f1(mm)} mm", str(len(a_p))], lugar=D.nom(e), superlativo=True, liga=[f"{f1(mm)} mm"]))
    if nac_ctx:
        hechos.append(nac_ctx)
    if med and cod in MED_COSTA:
        hechos.extend(hechos_mar(med)[:1])
        cifras.insert(0, {"n": f"{d1(med['sst'])} °C", "l": f"el Mediterráneo español el {dia(med['ultimo'])}, {f1(med['anom'])} °C sobre lo normal", "tono": "calor"})
    rojas = [z for z in mis if z["nivel"] == "rojo"]
    def en_zonas(zs):
        raras = any(" y " in z["zona"] or "," in z["zona"] for z in zs)
        if len(zs) == 1 or (len(zs) == 2 and not raras):
            t = lista_y([zona_txt(z["zona"]) for z in zs])
            return t if P in t else f"{t} ({P})"
        niv = zs[0]["nivel"]
        nombres = [zona_txt(z["zona"]) for z in zs]
        hechos.insert(0, hecho("zonas_n", f"A las {hora(c)} del {dia(c)}, AEMET tenía {len(zs)} zonas de {P} en aviso {niv}: "
                               f"{'; '.join(nombres) if raras else lista_y(nombres)}.", fuente_av, [str(len(zs))]))
        return f"{len(zs)} zonas de {P}"
    if rojas:
        tit = f"Aviso rojo por {lista_y(sorted({t for z in rojas for t in z['tipos']}))} en {en_zonas(rojas)}"
        if med and cod in MED_COSTA:
            tit += f" con el Mediterráneo {f1(med['anom'])} °C más caliente de lo normal"
        nivel = "rojo"
    elif mis:
        tit = f"Aviso naranja por {lista_y(sorted({t for z in mis for t in z['tipos']}))} en {en_zonas(mis)}"
        nivel = "naranja"
    else:
        mm, e = (h_p[0] if h_p and h_p[0][0] >= 10 else a_p[0])
        tit = (f"La estación de AEMET de {D.nom(e)} lleva {f1(mm)} mm el {dia(D.L['hoy_fecha'])} hasta las {D.corte}:00" if h_p and h_p[0][0] >= 10
               else f"La estación de AEMET de {D.nom(e)} recogió {f1(mm)} mm el {dia(D.L['fecha'])}")
        nivel = None
    if tit[:1].islower():
        tit = tit[0].upper() + tit[1:]
    ent = hechos[0]
    grupos = [[h for h in hechos[1:] if h["id"].startswith("aviso")], [h for h in hechos[1:] if h["id"].startswith("lluvia")],
              [h for h in hechos[1:] if not h["id"].startswith(("aviso", "lluvia"))]]
    pl = {"titular": tit, "subtitulo": next((h["dice"] for h in hechos if h["id"] in ("lluvia_hoy_p", "lluvia_ayer_p") and h is not ent), ""),
          "entradilla": ent["dice"], "cuerpo": [" ".join(h["dice"] for h in g) for g in grupos if g], "claves": [h["dice"] for h in hechos[:3]]}
    v = {"provincia": P, "slug": PROV[cod][1], "hechos": hechos, "plantilla": pl, "cifras": cifras[:3], "nivel": nivel,
         "puntos": (100 if nivel == "rojo" else 85 if nivel == "naranja" else 60) + (h_p[0][0] if h_p else 0) / 10}
    if len([1 for m, e in h_p if m >= 1]) >= 2:
        v["grafico"] = grafico_barras_lluvia(D, h_p, f"{hid}-{cod}", f"Lluvia entre la medianoche y las {D.corte}:00 del {dia(D.L['hoy_fecha'])} en {P}", n=8, provincial=True)
    return v


def g_mediterraneo(D: Datos, med, usado):
    if not med or usado:
        return None
    if not (med.get("ytd_puesto") == 1 or med["anom"] >= 2 or med.get("records")):
        return None
    hechos = hechos_mar(med)
    tit = (f"{med['ultimo'][:4]} es el año más cálido del Mediterráneo español a estas alturas desde 1982" if med.get("ytd_puesto") == 1
           else f"El Mediterráneo español, a {d1(med['sst'])} °C: {f1(med['anom'])} °C por encima de lo normal")
    pl = {"titular": tit, "subtitulo": " ".join(h["dice"] for h in hechos[1:3]), "entradilla": hechos[0]["dice"],
          "cuerpo": [h["dice"] for h in hechos[1:]], "claves": [h["dice"] for h in hechos[:3]]}
    cif = [{"n": f"{d1(med['sst'])} °C", "l": f"el {dia(med['ultimo'])}", "tono": "calor"}]
    if med.get("records"):
        cif.append({"n": f"{med['records']} días", "l": "con récord para su fecha este año", "tono": "calor"})
    h = historia("mediterraneo", f"{HOY.isoformat()}-mediterraneo", "Mediterráneo", "calor", 70 + (10 if med.get("ytd_puesto") == 1 else 0), hechos, pl, cif,
                 fuentes="NOAA OISST v2.1", metodo="Media diaria de la temperatura de la superficie del mar en la caja 36,5-41,5° N y 1,5° O-5° E; normal y rango habitual de 1991-2020.",
                 limites=["El dato de los últimos 14 días es preliminar."], pagina="https://calentamientoglobal.es/dana/")
    h["grafico"] = grafico_mar(med, h["id"])
    return h


def g_lluvia_sequia(D: Datos):
    L, E = D.L, D.E
    if not E:
        return None
    tope = max(int(m["racha"]) for m in L["municipios"].values())
    base = {e: r for e, r in E.items() if r.get("racha") is not None and r.get("hoy") is not None and r.get("dia") is not None}
    secas = {e: r for e, r in base.items() if int(r["racha"]) >= 10 and r["hoy"] < 1}
    moj = {e: r for e, r in base.items() if (r["dia"] or 0) >= 1 or (r["hoy"] or 0) >= 1}
    if len(secas) < 20:
        return None
    provs = sorted({nprov(r["prov"]) for r in secas.values() if r.get("prov") in PROV}, key=sin_tildes)
    ciudades = [p for p in provs if p in ("Ceuta", "Melilla")]
    np_ = len(provs) - len(ciudades)
    donde_ = f"{np_} provincias" + (f" y en {lista_y(ciudades)}" if ciudades else "")
    fa, fh = L["fecha"], L["hoy_fecha"]
    hechos = [hecho("secas", f"De las {len(base)} estaciones de AEMET que sigue el observatorio con datos del {dia(fa)} completo y del {dia(fh)}, {len(secas)} no han recogido 1 mm "
                    f"en ninguno de los últimos 10 días, hasta el {dia(fa)} incluido, y el {dia(fh)} tampoco llegan a 1 mm con los datos disponibles.",
                    "AEMET OpenData", [str(len(base)), str(len(secas)), "1 mm", "10 días"], alias=["diez días", "partida en dos"]),
              hecho("secas_prov", f"Hay estaciones así en {donde_}.", "AEMET OpenData", [str(np_)])]
    largas = sorted(((nprov(r["prov"]), D.nom(e)) for e, r in secas.items() if int(r["racha"]) >= tope), key=lambda x: (sin_tildes(x[0]), x[1]))
    if largas:
        por_p = {}
        for p, n in largas:
            por_p.setdefault(p, []).append(n)
        hechos.append(hecho("secas_tope", f"En {len(largas)} de ellas la racha llega a {tope} días o más, el tope de la ventana de cálculo: "
                            + "; ".join(f"{lista_y(ns)} ({p})" for p, ns in por_p.items()) + ".", "AEMET OpenData", [str(len(largas)), f"{tope} días"]))
    capitales = capitales_secas(D, secas)
    if capitales:
        grupos = {}
        for n, r in capitales:
            grupos.setdefault(r, []).append(n)
        hechos.append(hecho("secas_capitales", "En las estaciones de las capitales, " + "; ".join(
            f"{lista_y(ns)} llevan {r} días" if len(ns) > 1 else f"{ns[0]} lleva {r} días" for r, ns in sorted(grupos.items(), reverse=True)) + " sin recoger 1 mm.",
            "AEMET OpenData", [f"{r} días" for r in grupos]))
    hechos.append(hecho("mojadas", f"En el otro lado, {len(moj)} de esas {len(base)} estaciones recogieron 1 mm o más el {dia(fa)} o el {dia(fh)}.", "AEMET OpenData",
                        [str(len(moj)), str(len(base))]))
    partida = len(moj) >= 0.3 * len(base)
    tit = (f"España, partida en dos: {len(secas)} estaciones de AEMET llevan 10 días o más sin recoger 1 mm de lluvia" if partida
           else f"{len(secas)} estaciones de AEMET de {np_} provincias llevan 10 días o más sin recoger 1 mm de lluvia")
    pl = {"titular": tit, "subtitulo": " ".join(h["dice"] for h in hechos if h["id"] in ("secas_prov", "secas_tope")),
          "entradilla": hechos[0]["dice"], "cuerpo": [h["dice"] for h in hechos[1:]], "claves": [h["dice"] for h in hechos[:3]]}
    cif = [{"n": str(len(secas)), "l": "estaciones de AEMET con 10 días o más sin recoger 1 mm", "tono": "calor"},
           {"n": str(np_), "l": "provincias" + (f" y {lista_y(ciudades)}" if ciudades else ""), "tono": "calor"},
           {"n": str(len(moj)), "l": f"estaciones con 1 mm o más el {dia(fa)} o el {dia(fh)}", "tono": "lluvia"}]
    h = historia("lluvia_sequia", f"{HOY.isoformat()}-lluvia-y-sequia", "Lluvia y sequía · 52 provincias", "lluvia", 60 + min(20, len(secas) // 10), hechos, pl, cif,
                 fuentes="AEMET OpenData (observación horaria de las estaciones de referencia del mapa de lluvia de calentamientoglobal.es)",
                 metodo="Racha: días consecutivos, hasta el último día completo, en que la estación recogió menos de 1 mm. Lluvia: suma horaria de cada estación.",
                 limites=[f"La ventana de cálculo es de {tope} días: en las estaciones que llegan a ese tope, la racha real puede ser más larga.",
                          "El observatorio sigue las estaciones de referencia de los municipios de su mapa, no toda la red de AEMET."],
                 pagina="https://calentamientoglobal.es/lluvia-hoy-espana/")
    h["grafico"] = grafico_mapa(D, base, secas, moj, h["id"])
    for cod in PROV:
        v = version_sequia(D, cod, base, secas, tope, fa, fh)
        if v:
            h["provincias"][cod] = v
    return h


def capitales_secas(D, secas):
    paq = leer(PRENSA / "paquetes" / "otono.json", {}) or {}
    caps = {c["cod"]: c["capital"] for c in paq.get("capitales", [])}
    out = []
    for e, r in secas.items():
        cap = caps.get(r.get("prov"))
        if not cap:
            continue
        nombres = [sin_tildes(x).lower() for x in re.split(r"[/]", cap)]
        if any(sin_tildes(D.nom(e)).lower().startswith(n) for n in nombres):
            out.append((D.nom(e), int(r["racha"])))
    return sorted(out, key=lambda x: (-x[1], x[0]))


def version_sequia(D, cod, base, secas, tope, fa, fh):
    mis = {e: r for e, r in base.items() if r.get("prov") == cod}
    if not mis:
        return None
    P = nprov(cod)
    s = sorted(((int(r["racha"]), e) for e, r in secas.items() if r.get("prov") == cod), key=lambda x: (-x[0], x[1]))
    hechos = []
    if s:
        r0, e0 = s[0]
        al = "al menos " if r0 >= tope else ""
        hechos.append(hecho("seca_p", f"La estación de AEMET de {D.nom(e0)} lleva {al}{r0} días seguidos sin recoger 1 mm de lluvia, hasta el {dia(fa)} incluido, "
                            f"y el {dia(fh)} tampoco llega a 1 mm con los datos disponibles.", "AEMET OpenData", [f"{r0} días", "1 mm"], lugar=D.nom(e0)))
        if len(mis) == 1:
            dice_n = f"Es la única estación de AEMET de {P} que sigue el observatorio."
        elif len(s) == len(mis):
            dice_n = f"En {P}, las {len(mis)} estaciones de AEMET que sigue el observatorio llevan 10 días o más sin recoger 1 mm."
        elif len(s) == 1:
            dice_n = f"En {P}, es la única de las {len(mis)} estaciones de AEMET que sigue el observatorio que lleva 10 días o más sin recoger 1 mm."
        else:
            dice_n = f"En {P}, {len(s)} de las {len(mis)} estaciones de AEMET que sigue el observatorio llevan 10 días o más sin recoger 1 mm."
        hechos.append(hecho("seca_p_n", dice_n, "AEMET OpenData", [str(len(s)), str(len(mis))]))
        tit = f"La estación de AEMET de {D.nom(e0)} lleva {al}{r0} días seguidos sin recoger 1 mm de lluvia"
        pts = 40 + r0
    else:
        return None  # sin estaciones secas, la provincia no tiene versión propia: ve la nacional
    hechos.append(hecho("secas_nac", f"En toda España, {len(secas)} de las {len(base)} estaciones de AEMET que sigue el observatorio llevan 10 días o más sin recoger 1 mm.",
                        "AEMET OpenData", [str(len(secas)), str(len(base))], alias=["partida en dos"]))
    pl = {"titular": tit, "subtitulo": hechos[1]["dice"] if len(hechos) > 1 else "", "entradilla": hechos[0]["dice"],
          "cuerpo": [h["dice"] for h in hechos[1:]], "claves": [h["dice"] for h in hechos[:2]]}
    return {"provincia": P, "slug": PROV[cod][1], "hechos": hechos, "plantilla": pl, "puntos": pts,
            "cifras": ([{"n": f"{s[0][0]} días", "l": f"sin 1 mm en {D.nom(s[0][1])}", "tono": "calor"}] if s else [])}


def g_temporada(D: Datos):
    """Paquete de temporada publicable (otoño, invierno, primavera, verano en °C)."""
    out = []
    for p in (D.PAQ.get("paquetes") or []):
        if not (p.get("de_temporada") and p.get("publicable")) or p.get("id") not in ("otono", "invierno", "primavera", "verano"):
            continue
        q = leer(PRENSA / "paquetes" / f"{p['id']}.json", {}) or {}
        if not q.get("publicable") or q.get("unidad") != "°C":
            continue
        est = {"otono": "otoño", "invierno": "invierno", "primavera": "primavera", "verano": "verano"}[q["id"]]
        aemet = sorted([c for c in q["capitales"] if c.get("fuente_fila") == "AEMET" and not c.get("revisar")], key=lambda c: -c["delta"])
        if len(aemet) < 5:
            continue
        media = st.mean(c["delta"] for c in aemet)
        sube = sum(1 for c in q["capitales"] if c["delta"] > 0)
        cap = lambda c: {"Alacant/Alicante": "Alicante"}.get(c["capital"], c["capital"])
        top = aemet[:3]
        hechos = [hecho("temp_aemet", f"El {est} es {f1(media)} °C más cálido que a principios de los setenta, de media, en las {len(aemet)} capitales con estación de AEMET "
                        f"de serie larga y coherente con el reanálisis (tendencia lineal {q['periodo']}).", "AEMET", [f"{f1(media)} °C", str(len(aemet)), q["periodo"]]),
                  hecho("temp_top", "Donde más ha subido: " + lista_y([f"{cap(c)} (+{f1(c['delta'])} °C)" for c in top]) + ".", "AEMET",
                        [f"+{f1(c['delta'])} °C" for c in top], superlativo=True),
                  hecho("temp_era5", f"En las {len(q['capitales'])} capitales, con el reanálisis ERA5, la subida media es de {f1(q['media_delta'])} °C, y el {est} se ha calentado en {sube} de las {len(q['capitales'])}.",
                        "ERA5 (Copernicus/ECMWF)", [f"{f1(q['media_delta'])} °C", str(sube), str(len(q["capitales"]))])]
        for x in q.get("hallazgos", [])[2:3]:
            if "reanálisis" in x:
                hechos.append(hecho("temp_dias", x.rstrip(".") + ".", "ERA5 (Copernicus/ECMWF)"))
        pl = {"titular": f"El {est} es {f1(media)} °C más cálido que a principios de los setenta en las capitales con estación de AEMET de serie larga",
              "subtitulo": " ".join(h["dice"] for h in hechos[1:3]), "entradilla": hechos[0]["dice"], "cuerpo": [h["dice"] for h in hechos[1:]],
              "claves": [h["dice"] for h in hechos[:3]]}
        h = historia("temporada", f"{HOY.isoformat()}-{q['id']}-se-calienta", f"Tendencia · tu capital desde 1970", "calor", 40, hechos, pl,
                     [{"n": f"+{f1(media)} °C", "l": f"el {est} en las {len(aemet)} capitales con estación de AEMET de serie larga", "tono": "calor"}],
                     fuentes=q["fuente"], metodo=q["metodo"], limites=list(q.get("limites") or []), pagina="https://calentamientoglobal.es/prensa/")
        h["grafico"] = grafico_barras_temporada(aemet, h["id"], f"Cuánto ha subido la temperatura media del {est}, {q['periodo']}")
        for c in q["capitales"]:
            if c.get("revisar") or c.get("cod") not in PROV:
                continue
            fuente_c = "AEMET" if c.get("fuente_fila") == "AEMET" else "ERA5 (Copernicus/ECMWF)"
            hc = [hecho("temp_cap", c["titular"].rstrip(".") + ".", fuente_c, [f"{f1(c['delta'])} °C"]),
                  hecho("temp_cap_dato", f"Tendencia {c['dato']}." if not c["dato"].startswith("tendencia") else c["dato"][0].upper() + c["dato"][1:] + ".", fuente_c)]
            for x in c.get("contexto", [])[:2]:
                hc.append(hecho(f"temp_ctx{len(hc)}", x.rstrip(".") + ".", fuente_c, superlativo=True))
            hc.append(hecho("temp_nac", hechos[0]["dice"], "AEMET"))
            v = {"provincia": nprov(c["cod"]), "slug": PROV[c["cod"]][1], "hechos": hc, "puntos": 30 + c["delta"] * 5,
                 "plantilla": {"titular": c["titular"], "subtitulo": hc[1]["dice"], "entradilla": hc[0]["dice"], "cuerpo": [x["dice"] for x in hc[1:]],
                               "claves": [x["dice"] for x in hc[:3]]},
                 "cifras": [{"n": f"+{f1(c['delta'])} °C", "l": f"el {est} en {cap(c)} desde 1970 ({'AEMET' if fuente_c == 'AEMET' else 'reanálisis ERA5'})", "tono": "calor"}]}
            serie = serie_csv(c.get("csv"))
            if serie:
                v["grafico"] = grafico_serie_capital(serie, f"{h['id']}-{c['cod']}", f"Temperatura media del {est} en {cap(c)} ({'estación de AEMET' if fuente_c == 'AEMET' else 'reanálisis ERA5'})", fuente_c)
            h["provincias"][c["cod"]] = v
        out.append(h)
    return out


def serie_csv(ruta):
    if not ruta:
        return None
    p = PRENSA / str(ruta).replace("prensa/", "", 1)
    try:
        with open(p, encoding="utf-8") as f:
            r = list(csv.reader(f))
        return [(int(a), float(b)) for a, b in r[1:] if a and b]
    except Exception:
        return None


def g_embalses(D: Datos):
    n = D.EMB
    if not n.get("boletin_fecha") or not n.get("nacional"):
        return None
    act = (n.get("actualizado") or "")[:10]
    if not act or (HOY - date.fromisoformat(act)).days > 2:
        return None
    nac, bol = n["nacional"], n["boletin_fecha"]
    pct, p10, p1a = nac["pct"], nac["pct_media_10a"], nac["pct_hace_1a"]
    hechos = [hecho("emb_nac", f"La reserva de agua de España estaba al {f1(pct)} % el {dia(bol)}, según el boletín hidrológico semanal del MITECO: "
                    f"{miles(nac['volumen_total_hm3'])} de {miles(nac['capacidad_total_hm3'])} hm³.", "MITECO", [f"{f1(pct)} %", miles(nac["volumen_total_hm3"]), miles(nac["capacidad_total_hm3"])]),
              hecho("emb_media", f"Son {f1(abs(pct - p10))} puntos {'más' if pct > p10 else 'menos'} que la media de los últimos diez años para esa semana ({f1(p10)} %); "
                    f"hace un año estaba al {f1(p1a)} %.", "MITECO", [f1(abs(pct - p10)), f"{f1(p10)} %", f"{f1(p1a)} %"])]
    pl = {"titular": f"La reserva de agua de España, al {f1(pct)} %: {f1(abs(pct - p10))} puntos {'por encima' if pct > p10 else 'por debajo'} de su media de diez años",
          "subtitulo": hechos[1]["dice"], "entradilla": hechos[0]["dice"], "cuerpo": [hechos[1]["dice"]], "claves": [h["dice"] for h in hechos]}
    h = historia("embalses", f"{bol}-embalses", "Agua · boletín del MITECO", "lluvia", 50, hechos, pl,
                 [{"n": f"{f1(pct)} %", "l": f"reserva de agua de España el {dia(bol)}", "tono": "lluvia"}], fuentes=n.get("fuente", "MITECO"),
                 metodo="Boletín Hidrológico Semanal del MITECO; media de diez años para la misma semana.", limites=[], pagina="https://calentamientoglobal.es/embalses-espana/")
    return h


def g_records_capitales(D: Datos):
    out = []
    for x in (D.HALL.get("enviables") or []):
        if x.get("serie") != "capitales" or not x.get("aemet") or x.get("tipo") not in ("record_fecha", "record_absoluto"):
            continue
        if (x.get("fecha_dato") or "") < AYER.isoformat():
            continue
        hechos = [hecho("rec", x["titular"].rstrip(".") + ".", x.get("fuente", "AEMET"), record=True, superlativo=True),
                  hecho("rec_dato", x["dato"].rstrip(".") + ".", x.get("fuente", "AEMET"))] + [hecho(f"rec_c{i}", c.rstrip(".") + ".", x.get("fuente", "AEMET")) for i, c in enumerate(x.get("contexto", [])[:2])]
        pl = {"titular": x["titular"], "subtitulo": x["dato"], "entradilla": hechos[0]["dice"], "cuerpo": [h["dice"] for h in hechos[1:]], "claves": [h["dice"] for h in hechos[:2]]}
        h = historia("record", f"{x['fecha_dato']}-{slugify(x['territorio'])}-{x['indicador']}", "Récord confirmado por AEMET", "calor", 92, hechos, pl, [],
                     fuentes=x.get("fuente", "AEMET"), metodo=x.get("metodo", ""), limites=x.get("limites", []), pagina=x.get("pagina"))
        out.append(h)
    return out


# ============================================================================ récords en las estaciones de AEMET
# Vienen de records_detectar.py (clima-scripts) vía hallazgos_prensa.py: medidos por AEMET en la estación, el mismo
# día, comparados con la tabla oficial de valores extremos de esa estación. Provisionales hasta que el valor diario
# validado de AEMET los confirma (2-4 días); entonces cambia el kicker.
def _hechos_record(x, prefijo="rec"):
    hechos = [hecho(f"{prefijo}", x["titular"].rstrip(".") + ".", x.get("fuente", "AEMET"), lugar=x.get("territorio"), record=True, superlativo=True),
              hecho(f"{prefijo}_dato", x["dato"].rstrip(".") + ".", x.get("fuente", "AEMET"), lugar=x.get("territorio"))]
    hechos += [hecho(f"{prefijo}_c{i}", c.rstrip(".") + ".", x.get("fuente", "AEMET")) for i, c in enumerate(x.get("contexto", [])[:3])]
    if x.get("provisional"):
        hechos.append(hecho(f"{prefijo}_prov", "Es un dato de observación en tiempo real que AEMET valida en 2-4 días; el observatorio lo vuelve a "
                            "comprobar entonces y lo confirma o lo retira.", x.get("fuente", "AEMET")))
    else:
        hechos.append(hecho(f"{prefijo}_conf", "El valor está confirmado con el dato climatológico diario validado por AEMET.", x.get("fuente", "AEMET")))
    return hechos


def _cifras_record(x, tono):
    cif = [{"n": f"{f1(x['valor'])} °C", "l": f"en {x['territorio']} el {dia(x['fecha_dato'], semana=False)}", "tono": tono}]
    ra = x.get("record_anterior") or {}
    if ra.get("valor") is not None:
        cif.append({"n": f"{f1(ra['valor'])} °C", "l": f"récord anterior de la estación{(' (' + str(ra['anio']) + ')') if ra.get('anio') else ''}", "tono": tono})
    return cif


def _version_record(x, nacional=None):
    """Versión provincial: la estación de la provincia, con la noticia nacional como contexto."""
    cod = H.cod_de_provincia(x.get("provincia", ""))
    if not cod:
        return None, None
    tono = "calor" if (x.get("variable") or "tmax") == "tmax" else "lluvia"
    hechos = _hechos_record(x)
    if nacional:
        hechos.append(hecho("rec_nac", nacional["titular"].rstrip(".") + ".", nacional.get("fuente", "AEMET"), record=True, superlativo=True))
    pl = {"titular": x["titular"], "subtitulo": (x.get("contexto") or [x["dato"]])[0], "entradilla": hechos[0]["dice"],
          "cuerpo": [h["dice"] for h in hechos[1:]], "claves": [h["dice"] for h in hechos[:2]]}
    return cod, {"provincia": nprov(cod), "slug": PROV[cod][1], "hechos": hechos, "plantilla": pl,
                 "puntos": 88 if x.get("tipo") == "record_absoluto" else 82, "cifras": _cifras_record(x, tono)}


def g_records_estaciones(D: Datos):
    out = []
    locales = {x["id"]: x for x in (D.HALL.get("locales") or [])}
    desde = (HOY - timedelta(days=2)).isoformat()
    usados = set()
    for x in (D.HALL.get("enviables") or []):
        if x.get("serie") != "estaciones" or x.get("tipo") not in ("record_mes", "record_absoluto") or (x.get("fecha_dato") or "") < desde:
            continue
        prov = bool(x.get("provisional"))
        tono = "calor" if "tmax" in (x.get("indicador") or "tmax") else "lluvia"
        if x.get("ambito") == "nacional":
            miembros = [locales[m] for m in x.get("miembros", []) if m in locales]
            hechos = [hecho("rec", x["titular"].rstrip(".") + ".", x.get("fuente", "AEMET"), record=True, superlativo=True),
                      hecho("rec_dato", x["dato"].rstrip(".") + ".", x.get("fuente", "AEMET"))]
            for i, m in enumerate(miembros):
                hechos.append(hecho(f"rec_m{i}", m["titular"].rstrip(".") + ".", m.get("fuente", "AEMET"), lugar=m.get("territorio"), record=True, superlativo=True))
            hechos += [hecho(f"rec_c{i}", c.rstrip(".") + ".", x.get("fuente", "AEMET")) for i, c in enumerate(x.get("contexto", [])[:2])]
            hechos.append(hecho("rec_prov", "Son datos de observación en tiempo real que AEMET valida en 2-4 días; el observatorio los vuelve a comprobar "
                                "entonces y los confirma o los retira.", x.get("fuente", "AEMET")) if prov else
                          hecho("rec_conf", "Los valores están confirmados con el dato climatológico diario validado por AEMET.", x.get("fuente", "AEMET")))
            pl = {"titular": x["titular"], "subtitulo": x["dato"], "entradilla": hechos[0]["dice"], "cuerpo": [h["dice"] for h in hechos[1:]],
                  "claves": [h["dice"] for h in hechos[:2]]}
            cifras = [{"n": str(len(miembros) or x["titular"].split(" ")[0]), "l": f"estaciones de AEMET con récord el {dia(x['fecha_dato'], semana=False)}", "tono": tono}]
            if miembros:
                top = max(miembros, key=lambda m: m.get("valor", 0)) if tono == "calor" else min(miembros, key=lambda m: m.get("valor", 0))
                cifras.append({"n": f"{f1(top['valor'])} °C", "l": f"en {top['territorio']}", "tono": tono})
            h = historia("record", f"{x['fecha_dato']}-estaciones-{x['indicador']}", "Récords en las estaciones de AEMET" if prov else "Récords confirmados por AEMET",
                         tono, 85 if prov else 97, hechos, pl, cifras, x.get("fuente", "AEMET"), x.get("metodo", ""), x.get("limites", []), x.get("pagina"))
            for m in miembros:
                cod, v = _version_record(m, x)
                if cod and cod in h["provincias"]:
                    # segunda estación de la misma provincia: se suma a la versión existente en vez de pisarla
                    ya = h["provincias"][cod]
                    extra = [f for f in v["hechos"] if f["id"].startswith("rec") and f["id"] not in {g["id"] for g in ya["hechos"]}]
                    for i, f in enumerate(extra):
                        f["id"] = f"{f['id']}_{slugify(m['territorio'])}"
                    ya["hechos"] += extra
                    ya["plantilla"]["cuerpo"] += [f["dice"] for f in extra]
                    ya["cifras"] = (ya.get("cifras") or []) + v["cifras"][:1]
                elif cod:
                    h["provincias"][cod] = v
                    v["grafico"] = grafico_records_estacion(m, f"{h['id']}-{cod}")
                usados.add(m["id"])
            if miembros:
                top = max(miembros, key=lambda m: m.get("valor", 0)) if tono == "calor" else min(miembros, key=lambda m: m.get("valor", 0))
                cod_top = H.cod_de_provincia(top.get("provincia", ""))
                h["grafico"] = (h["provincias"].get(cod_top) or {}).get("grafico") or grafico_records_estacion(top, h["id"])
            if x.get("cuando") == "HOY":
                h["ultima_hora"] = [{"hora": hora(AHORA.astimezone(MADRID).isoformat()), "texto": x["titular"], "tono": tono}]
            out.append(h)
            continue
        if x["id"] in usados:
            continue
        hechos = _hechos_record(x)
        pl = {"titular": x["titular"], "subtitulo": (x.get("contexto") or [x["dato"]])[0], "entradilla": hechos[0]["dice"],
              "cuerpo": [h["dice"] for h in hechos[1:]], "claves": [h["dice"] for h in hechos[:2]]}
        kicker = ("Récord en una estación de AEMET" if prov else "Récord confirmado por AEMET") + (" · dato del día" if x.get("cuando") == "HOY" else "")
        h = historia("record", f"{x['fecha_dato']}-{slugify(x['territorio'])}-{x['indicador']}", kicker, tono,
                     (95 if x.get("tipo") == "record_absoluto" else 90) - (15 if prov else 0), hechos, pl, _cifras_record(x, tono),
                     x.get("fuente", "AEMET"), x.get("metodo", ""), x.get("limites", []), x.get("pagina"))
        h["grafico"] = grafico_records_estacion(x, h["id"])
        cod, v = _version_record(x)
        if cod:
            v["grafico"] = h["grafico"]
            h["provincias"][cod] = v
        if x.get("cuando") == "HOY":
            h["ultima_hora"] = [{"hora": hora(AHORA.astimezone(MADRID).isoformat()), "texto": x["titular"], "tono": tono}]
        out.append(h)
    return out


def historia(tipo, id_, kicker, tono, puntos, hechos, plantilla, cifras, fuentes, metodo, limites, pagina):
    return {"id": id_, "tipo": tipo, "fecha": HOY.isoformat(), "kicker": kicker, "tono": tono, "puntos": round(puntos, 1), "hechos": hechos,
            "plantilla": plantilla, "cifras": cifras, "fuentes": fuentes, "metodo": metodo, "limites": limites, "pagina": pagina, "provincias": {}}


# ============================================================================ gráficos (SVG con datos reales)
CALOR, LLUVIA, TINTA, GRIS, RAYA, BANDA = "#C4461A", "#1F5FA8", "#16130F", "#5E574E", "#E3DED5", "#ECE7DF"
FUENTE = "Public Sans, DejaVu Sans, Arial, sans-serif"


def _t(x, y, s, size=12, color=GRIS, anchor="start", weight=400):
    s = str(s).replace("&", "&amp;").replace("<", "&lt;")
    return f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{color}" text-anchor="{anchor}" font-weight="{weight}" font-family="{FUENTE}">{s}</text>'


def _svg(w, h, aria, cuerpo):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-label="{aria}">'
            f'<rect width="{w}" height="{h}" fill="#FFFFFF"></rect>' + "".join(cuerpo) + "</svg>")


def guardar_grafico(nombre, svg, filas, cabecera, titulo, leyenda, pie):
    g = SALIDA / "graficos"
    g.mkdir(parents=True, exist_ok=True)
    (g / f"{nombre}.svg").write_text(svg, encoding="utf-8")
    # Sin PNG en el repositorio: cada pasada horaria cambiaría cientos de KB de binarios. El plugin convierte el SVG
    # a PNG en el navegador del periodista (botón «Gráfico (PNG)»), con el dato exacto de la versión que está viendo.
    png = None
    with open(g / f"{nombre}.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cabecera)
        w.writerows(filas)
    m = re.search(r'viewBox="0 0 ([0-9.]+) ([0-9.]+)"', svg)
    return {"titulo": titulo, "leyenda": leyenda, "pie": pie, "svg": f"prensa/noticias/graficos/{nombre}.svg", "png": png,
            "ancho": round(float(m.group(1))) if m else None, "alto": round(float(m.group(2))) if m else None,
            "csv": f"prensa/noticias/graficos/{nombre}.csv"}


def grafico_mar(med, nombre):
    W, Hh, ml, mr, mt, mb = 960, 420, 44, 128, 24, 34
    y0, y1 = 13, 30
    X = lambda doy: ml + (doy - 1) / 365 * (W - ml - mr)
    Y = lambda t: mt + (y1 - t) / (y1 - y0) * (Hh - mt - mb)
    M = leer(DOCS / "dana" / "mediterraneo.json", {})
    doy = lambda mmdd: (date(2025, int(mmdd[:2]), int(mmdd[3:])) - date(2025, 1, 1)).days + 1
    clim = sorted((doy(c[0]), c[1], c[2], c[3]) for c in M["clim"] if c[0] != "02-29")
    s = []
    for t in range(14, 31, 4):
        s.append(f'<line x1="{ml}" x2="{W - mr}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="{RAYA}" stroke-width="1"></line>')
        s.append(_t(ml - 8, Y(t) + 4, f"{t} °C" if t == 30 else t, 12, GRIS, "end"))
    for i, m in enumerate(["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]):
        s.append(_t(X((date(2025, i + 1, 1) - date(2025, 1, 1)).days + 1) + 2, Hh - mb + 20, m, 12, GRIS))
    banda = " ".join(f"{X(d):.1f},{Y(p90):.1f}" for d, n, p10, p90 in clim) + " " + " ".join(f"{X(d):.1f},{Y(p10):.1f}" for d, n, p10, p90 in reversed(clim))
    s.append(f'<polygon points="{banda}" fill="{BANDA}"></polygon>')
    s.append(f'<polyline points="{" ".join(f"{X(d):.1f},{Y(n):.1f}" for d, n, a, b in clim)}" fill="none" stroke="#8A8277" stroke-width="1.5" stroke-dasharray="5 4"></polyline>')
    v = med["v"]
    anio = int(med["ultimo"][:4])
    filas = []

    def serie(y, hasta):
        tramos, cur = [], []
        d = date(y, 1, 1)
        while d <= hasta:
            x = v.get(d)
            if d.month == 2 and d.day == 29:
                d += timedelta(days=1)
                continue
            if x is None:
                if cur:
                    tramos.append(cur)
                    cur = []
            else:
                k = (d - date(y, 1, 1)).days + 1 - (1 if y % 4 == 0 and d.month > 2 else 0)
                cur.append((X(k), Y(x)))
                if y == anio:
                    filas.append((d.isoformat(), x, dict((c[0], c[1]) for c in M["clim"]).get(d.strftime("%m-%d"))))
            d += timedelta(days=1)
        if cur:
            tramos.append(cur)
        return tramos
    for tr in serie(anio - 1, date(anio - 1, 12, 31)):
        s.append(f'<polyline points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in tr)}" fill="none" stroke="#A9A196" stroke-width="1.4"></polyline>')
    for tr in serie(anio, date.fromisoformat(med["ultimo"])):
        s.append(f'<polyline points="{" ".join(f"{a:.1f},{b:.1f}" for a, b in tr)}" fill="none" stroke="{CALOR}" stroke-width="2.6" stroke-linejoin="round"></polyline>')
    fmax, vmax = med["max_abs"]
    if fmax[:4] == str(anio):
        dm = date.fromisoformat(fmax)
        xm, ym = X((dm - date(anio, 1, 1)).days + 1), Y(vmax)
        s.append(f'<circle cx="{xm:.1f}" cy="{ym:.1f}" r="4" fill="{CALOR}"></circle>')
        s.append(_t(xm - 10, ym - 4, f"{d1(vmax)} °C el {dm.day} de {MESES[dm.month - 1]}: máximo de la serie", 12.5, TINTA, "end", 600))
    du = date.fromisoformat(med["ultimo"])
    xu, yu = X((du - date(anio, 1, 1)).days + 1), Y(med["sst"])
    s.append(f'<circle cx="{xu:.1f}" cy="{yu:.1f}" r="4.5" fill="{CALOR}" stroke="#fff" stroke-width="1.5"></circle>')
    s.append(_t(xu + 10, yu - 6, f"{d1(med['sst'])} °C", 15, CALOR, "start", 700))
    s.append(_t(xu + 10, yu + 11, f"{du.day} de {MESES[du.month - 1]}", 12, TINTA, "start", 500))
    s.append(_t(xu + 10, yu + 26, f"+{f1(med['anom'])} °C sobre lo normal", 12, GRIS))
    s.append(_t(X(150), Y(27.6), str(anio), 15, CALOR, "start", 700))
    svg = _svg(W, Hh, "Temperatura diaria del Mediterráneo español frente a lo normal de 1991-2020", s)
    return guardar_grafico(nombre, svg, filas, ["fecha", "temperatura_C", "normal_1991_2020_C"], "El Mediterráneo español, día a día",
                           [{"t": "linea", "c": CALOR, "l": str(anio)}, {"t": "linea", "c": "#A9A196", "l": str(anio - 1)},
                            {"t": "discontinua", "c": "#8A8277", "l": "Normal 1991-2020"}, {"t": "banda", "c": BANDA, "l": "Rango habitual (percentiles 10-90)"}],
                           "Temperatura media diaria de la superficie del mar entre Alborán y el mar Balear (36,5-41,5° N, 1,5° O-5° E). Fuente: NOAA OISST v2.1. "
                           "El dato de los últimos 14 días es preliminar. Cálculo: calentamientoglobal.es.")


def grafico_barras_lluvia(D, filas, nombre, titulo, n=10, provincial=False):
    filas = [(mm, e) for mm, e in filas if mm > 0][:n]
    if not filas:
        return None
    etiqueta = (lambda e: D.nom(e)) if provincial else D.donde
    ml = int(min(330, 24 + 7.4 * max(len(etiqueta(e)) for mm, e in filas)))
    W, fila, mr, mt = 640 + max(0, ml - 210), 30, 70, 6
    Hh = mt + fila * len(filas) + 8
    mx = max(mm for mm, e in filas)
    X = lambda v: ml + v / mx * (W - ml - mr)
    s = []
    for i, (mm, e) in enumerate(filas):
        y = mt + i * fila
        s.append(_t(ml - 10, y + 19, etiqueta(e), 13.5, TINTA, "end", 600 if i == 0 else 400))
        s.append(f'<rect x="{ml}" y="{y + 6}" width="{max(2, X(mm) - ml):.1f}" height="18" fill="{LLUVIA if i == 0 else "#8EB1DA"}"></rect>')
        s.append(_t(X(mm) + 6, y + 20, f"{f1(mm)} mm", 13, TINTA, "start", 700 if i == 0 else 500))
    svg = _svg(W, Hh, titulo, s)
    return guardar_grafico(nombre, svg, [(D.nom(e), nprov(D.E[e].get("prov")), mm) for mm, e in filas], ["estacion", "provincia", "mm"], titulo, [],
                           "Estaciones de AEMET que sigue el observatorio, con todas las horas del periodo. Fuente: AEMET OpenData. Cálculo: calentamientoglobal.es.")


def pos_estacion(D, e, r):
    mun = D.MAPA.get("mun", {})
    ne = H._norm(D.nom(e))
    refs = sorted(r.get("refs") or [])
    for k in refs:
        m = (D.L.get("municipios") or {}).get(k, {})
        if k in mun and m.get("n") and any(len(H._norm(x)) >= 4 and ne.startswith(H._norm(x)) for x in str(m["n"]).split("/")):
            return mun[k]
    pts = [mun[k] for k in refs if k in mun]
    if not pts:
        return None
    return [round(st.mean(p[0] for p in pts), 1), round(st.mean(p[1] for p in pts), 1)]


def grafico_mapa(D, base, secas, moj, nombre):
    m = D.MAPA
    if not m.get("fondo"):
        return None
    W, Hh = m["W"], m["H"]
    s = [f'<path d="{m["fondo"]}" fill="#EFEBE4"></path>', f'<path d="{m["fronteras"]}" fill="none" stroke="#FFFFFF" stroke-width="1"></path>',
         f'<path d="{m["canarias"]}" fill="none" stroke="#C9C2B7" stroke-width="1"></path>']
    filas, pts = [], []
    for e, r in base.items():
        p = pos_estacion(D, e, r)
        if not p:
            continue
        clase = "seca" if e in secas else ("lluvia" if e in moj else "nada")
        pts.append((clase, p, (r["dia"] or 0) + (r["hoy"] or 0)))
        filas.append((D.nom(e), nprov(r.get("prov")), clase, r["dia"], r["hoy"], r["racha"]))
    for clase, p, mm in sorted(pts, key=lambda x: {"nada": 0, "lluvia": 1, "seca": 2}[x[0]]):
        if clase == "nada":
            s.append(f'<circle cx="{p[0]}" cy="{p[1]}" r="2.6" fill="#B7AFA3"></circle>')
        elif clase == "lluvia":
            s.append(f'<circle cx="{p[0]}" cy="{p[1]}" r="{2.8 + min(5.0, math.sqrt(mm) * 0.75):.1f}" fill="{LLUVIA}" fill-opacity="0.78"></circle>')
        else:
            s.append(f'<circle cx="{p[0]}" cy="{p[1]}" r="3.6" fill="{CALOR}" stroke="#fff" stroke-width="0.8"></circle>')
    svg = _svg(W, Hh, "Estaciones de AEMET con lluvia frente a estaciones con diez días o más sin recoger 1 mm", s)
    n = {c: sum(1 for x in pts if x[0] == c) for c in ("lluvia", "seca", "nada")}
    return guardar_grafico(nombre, svg, filas, ["estacion", "provincia", "clase", "mm_dia_anterior", "mm_hoy", "dias_sin_1mm"], "Dónde llueve y dónde no",
                           [{"t": "punto", "c": LLUVIA, "l": f"1 mm o más el {dia(D.L['fecha'])} o el {dia(D.L['hoy_fecha'])} ({n['lluvia']})"},
                            {"t": "punto", "c": CALOR, "l": f"10 días o más sin 1 mm ({n['seca']})"}, {"t": "punto", "c": "#B7AFA3", "l": f"Ni una cosa ni otra ({n['nada']})"}],
                           f"Cada punto, una de las {len(pts)} estaciones de AEMET que sigue el observatorio con el día anterior completo y dato de hoy (posición aproximada, en su municipio). "
                           f"Lluvia de hoy, hasta las {D.corte}:00. Fuente: AEMET OpenData.")


def grafico_barras_temporada(filas, nombre, titulo):
    W, fila, ml, mr, mt = 640, 27, 178, 64, 8
    Hh = mt + fila * len(filas) + 30
    mx = max(3.0, math.ceil(max(c["delta"] for c in filas)))
    X = lambda d: ml + d / mx * (W - ml - mr)
    s = []
    for t in range(1, int(mx) + 1):
        s.append(f'<line x1="{X(t):.1f}" x2="{X(t):.1f}" y1="{mt - 4}" y2="{Hh - 26}" stroke="{RAYA}" stroke-width="1"></line>')
        s.append(_t(X(t), Hh - 8, f"+{t} °C", 12, GRIS, "middle"))
    for i, c in enumerate(filas):
        y = mt + i * fila
        nombre_c = {"Alacant/Alicante": "Alicante"}.get(c["capital"], c["capital"])
        dest = i < 3
        s.append(_t(ml - 10, y + 17, nombre_c, 13.5, TINTA, "end", 600 if dest else 400))
        s.append(f'<rect x="{ml}" y="{y + 5}" width="{X(c["delta"]) - ml:.1f}" height="16" fill="{CALOR if dest else "#E3A487"}"></rect>')
        s.append(_t(X(c["delta"]) + 6, y + 17.5, f"+{f1(c['delta'])}", 13, TINTA if dest else GRIS, "start", 700 if dest else 500))
    svg = _svg(W, Hh, titulo, s)
    return guardar_grafico(nombre, svg, [(c["capital"], c["delta"], c.get("estacion")) for c in filas], ["capital", "subida_C", "estacion_AEMET"], titulo, [],
                           "Tendencia lineal de la media estacional en las capitales con estación de AEMET de al menos 40 temporadas completas y coherente con el reanálisis. "
                           "Fuente: AEMET. Cálculo: calentamientoglobal.es.")


def grafico_records_estacion(x, nombre):
    """Barras con el récord de cada mes en la estación (tabla de valores extremos de AEMET) y el valor del día."""
    try:
        base = leer(DOCS / "records" / "baseline.json", {}) or {}
        e = (base.get("estaciones") or {}).get(((x.get("estacion") or {}).get("idema")) or "")
        if not e:
            return None
        var = x.get("variable") or "tmax"
        vals = [(e[var][i][0] if e[var][i][0] is not None else None) for i in range(12)]
        if not any(v is not None for v in vals):
            return None
        mes = int(str(x["fecha_dato"])[5:7]) - 1
        nuevo = float(x["valor"])
        color = CALOR if var == "tmax" else LLUVIA
        W, Hh, ml, mr, mt, mb = 640, 300, 44, 16, 16, 34
        lo = min([v for v in vals if v is not None] + [nuevo]); hi = max([v for v in vals if v is not None] + [nuevo])
        lo, hi = (math.floor(lo / 5) * 5 - (5 if var == "tmin" else 0)), math.ceil(hi / 5) * 5 + (2 if var == "tmax" else 0)
        if hi - lo < 10:
            hi = lo + 10
        Y = lambda v: mt + (hi - v) / (hi - lo) * (Hh - mt - mb)
        bw = (W - ml - mr) / 12
        s = []
        for t in range(int(lo), int(hi) + 1, 5):
            s.append(f'<line x1="{ml}" x2="{W - mr}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="{RAYA}" stroke-width="1"></line>')
            s.append(_t(ml - 6, Y(t) + 4, f"{t}", 11, GRIS, "end"))
        # las máximas crecen desde abajo; las mínimas cuelgan desde arriba, para que el frío más extremo sea la barra más larga
        y0 = Y(lo) if var == "tmax" else Y(hi)
        for i, v in enumerate(vals):
            x0 = ml + i * bw + 4
            s.append(_t(x0 + (bw - 8) / 2, Hh - mb + 16, MESES[i][:3], 11, GRIS, "middle"))
            if v is None:
                continue
            if i == mes:
                # el mes del récord: a la izquierda el récord anterior (gris), a la derecha el nuevo valor (color)
                w2 = (bw - 8) / 2 - 1
                s.append(f'<rect x="{x0:.1f}" y="{min(Y(v), y0):.1f}" width="{w2:.1f}" height="{abs(y0 - Y(v)):.1f}" fill="#D8D1C6"></rect>')
                s.append(f'<rect x="{x0 + w2 + 2:.1f}" y="{min(Y(nuevo), y0):.1f}" width="{w2:.1f}" height="{abs(y0 - Y(nuevo)):.1f}" fill="{color}"></rect>')
                s.append(_t(x0 + (bw - 8) / 2, Y(nuevo) - 6 if var == "tmax" else Y(nuevo) + 14, f"{f1(nuevo)} °C", 12, TINTA, "middle", 700))
            else:
                s.append(f'<rect x="{x0:.1f}" y="{min(Y(v), y0):.1f}" width="{bw - 8:.1f}" height="{abs(y0 - Y(v)):.1f}" fill="#D8D1C6"></rect>')
        if vals[mes] is None:
            x0 = ml + mes * bw + 4
            s.append(f'<rect x="{x0:.1f}" y="{min(Y(nuevo), y0):.1f}" width="{bw - 8:.1f}" height="{abs(y0 - Y(nuevo)):.1f}" fill="{color}"></rect>')
            s.append(_t(x0 + (bw - 8) / 2, Y(nuevo) - 6 if var == "tmax" else Y(nuevo) + 14, f"{f1(nuevo)} °C", 12, TINTA, "middle", 700))
        titulo = f"Récord de {'temperatura máxima' if var == 'tmax' else 'temperatura mínima'} de cada mes en la estación de AEMET de {x.get('territorio', '')}"
        svg = _svg(W, Hh, titulo, s)
        filas = [(MESES[i], vals[i], f"{e[var][i][2]}-{i + 1:02d}-{e[var][i][1]:02d}" if vals[i] is not None and e[var][i][2] and e[var][i][1] else "") for i in range(12)]
        filas.append((f"{MESES[mes]} ({str(x['fecha_dato'])[:4]}, nuevo)", nuevo, str(x["fecha_dato"])))
        return guardar_grafico(nombre, svg, filas, ["mes", "record_C", "fecha_record"], titulo,
                               [{"t": "banda", "c": "#D8D1C6", "l": "récord anterior de cada mes"}, {"t": "banda", "c": color, "l": f"{dia(x['fecha_dato'], semana=False)}"}],
                               "Valores climatológicos extremos de la estación (AEMET OpenData) y observación del día. Cálculo: calentamientoglobal.es.")
    except Exception as e:
        LOG.append(f"grafico_records_estacion {nombre}: {e}")
        return None


def grafico_serie_capital(serie, nombre, titulo, fuente):
    W, Hh, ml, mr, mt, mb = 760, 300, 40, 16, 28, 30
    vals = [t for a, t in serie]
    t0, t1 = math.floor(min(vals) - 0.5), math.ceil(max(vals) + 0.4)
    n = len(serie)
    bw = (W - ml - mr) / n
    Y = lambda t: mt + (t1 - t) / (t1 - t0) * (Hh - mt - mb)
    base10 = st.mean(t for a, t in serie if a < 1980) if any(a < 1980 for a, t in serie) else vals[0]

    def color(t):
        k = max(-1.0, min(1.0, (t - base10) / 2.6))
        c1, c2 = (0xEF, 0xEB, 0xE4), ((0x1F, 0x5F, 0xA8) if k < 0 else (0xC4, 0x46, 0x1A))
        a = 0.25 + 0.75 * abs(k)
        return "#%02X%02X%02X" % tuple(round(c1[j] + (c2[j] - c1[j]) * a) for j in range(3))
    s = []
    for t in range(int(t0), int(t1) + 1):
        s.append(f'<line x1="{ml}" x2="{W - mr}" y1="{Y(t):.1f}" y2="{Y(t):.1f}" stroke="{RAYA}" stroke-width="1"></line>')
        s.append(_t(ml - 6, Y(t) + 4, f"{t} °C" if t == int(t1) else t, 11.5, GRIS, "end"))
    for i, (a, t) in enumerate(serie):
        x = ml + i * bw
        s.append(f'<rect x="{x + 1:.1f}" y="{Y(t):.1f}" width="{bw - 2:.1f}" height="{Hh - mb - Y(t):.1f}" fill="{color(t)}"></rect>')
        if a % 10 == 0:
            s.append(_t(x + bw / 2, Hh - mb + 18, a, 11.5, GRIS, "middle"))
    xs = [a for a, t in serie]
    mxs, mys = st.mean(xs), st.mean(vals)
    b = sum((x - mxs) * (y - mys) for x, y in zip(xs, vals)) / sum((x - mxs) ** 2 for x in xs)
    a0 = mys - b * mxs
    s.append(f'<line x1="{ml + bw / 2:.1f}" y1="{Y(a0 + b * xs[0]):.1f}" x2="{ml + (n - 0.5) * bw:.1f}" y2="{Y(a0 + b * xs[-1]):.1f}" stroke="{TINTA}" stroke-width="1.6" stroke-dasharray="6 4"></line>')
    im = max(range(n), key=lambda i: vals[i])
    s.append(_t(ml + (im + 0.5) * bw, Y(vals[im]) - 8, f"{xs[im]}: {d1(vals[im])} °C", 12, TINTA, "end", 600))
    svg = _svg(W, Hh, titulo, s)
    return guardar_grafico(nombre, svg, serie, ["anio", "temperatura_media_C"], titulo, [],
                           f"Media de la estación, año a año. Línea discontinua: tendencia lineal. Color: diferencia con la media de los años setenta. Fuente: {fuente}. Cálculo: calentamientoglobal.es.")


# ============================================================================ verificador
PALABRAS_NUM = {"dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once", "doce", "trece", "catorce", "quince",
                "dieciséis", "diecisiete", "dieciocho", "diecinueve", "veinte", "treinta", "cuarenta", "cincuenta", "cien", "mil", "doble",
                "triple", "mitad", "décima", "décimas", "centésima", "centésimas", "primer", "segundo", "tercer", "cuarto", "quinto"}
VETADAS = ["nunca", "jamás", "histórico", "histórica", "sin precedentes", "inédito", "inédita", "catastróf", "alarmante", "apocalíp",
           "por culpa", "culpa del cambio", "provocad", "causad", "analizad", "elaborad", "calculad", "mañana", "ayer", "anoche", "pasado mañana", "esta semana", "este mes", "hoy"]
SUPERLATIVOS = ["récord", "el más", "la más", "los más", "las más", "máximo", "mínimo", "la mayor", "el mayor", "la menor", "el menor", "más alta", "más alto"]
NOMBRES_OK = {"AEMET", "NOAA", "MITECO", "ERA5", "Copernicus", "ECMWF", "OpenData", "MeteoAlarm", "DANA", "España", "Mediterráneo", "Observatorio",
              "Según", "Hasta", "Entre", "Desde", "Además", "Las", "Los", "La", "El", "En", "Un", "Una", "De", "Del", "Con", "Por", "Para", "A", "Al",
              "Este", "Esta", "Ese", "Esa", "Le", "Ya", "Son", "Hay", "Sin", "Otras", "Otros", "Fuente", "Alborán", "Balear", "Satélite", "AEMET.",
              "Aviso", "Avisos", "Lluvia", "Mar", "CC", "BY", "Copernicus/ECMWF", "Agencia", "Estatal", "Meteorología", "NOAA."}


def corpus(hechos, extra=""):
    t = " ".join(h["dice"] + " " + " ".join(h.get("alias") or []) + " " + " ".join(h.get("valores") or []) for h in hechos)
    t += " " + extra + " " + " ".join(DIAS) + " " + " ".join(MESES)
    return t


def _nums(t):
    return re.findall(r"\d+(?:[.,]\d+)*", t)


def verificar(texto: dict, hechos: list, extra="") -> list[str]:
    """Comprueba que el texto solo dice lo que dicen los hechos. Devuelve la lista de problemas (vacía = vale)."""
    errores = []
    partes = [texto.get("titular", ""), texto.get("subtitulo", ""), texto.get("entradilla", "")] + list(texto.get("cuerpo") or []) + list(texto.get("claves") or [])
    todo = " ".join(p for p in partes if isinstance(p, str))
    if not texto.get("titular") or not texto.get("entradilla") or not texto.get("cuerpo"):
        errores.append("faltan partes (titular, entradilla o cuerpo)")
    if len(texto.get("titular", "")) > 170:
        errores.append("titular demasiado largo")
    C = corpus(hechos, extra)
    nums_ok = set(_nums(C))
    lugares = {}
    for h in hechos:
        if h.get("lugar"):
            for var in {h["lugar"], H._nombre_corto(h["lugar"])} | ({h["lugar"].split()[0]} if len(h["lugar"].split()[0]) >= 4 else set()):
                lugares.setdefault(var, set()).add(h["lugar"])
    for n in _nums(todo):
        if n not in nums_ok:
            errores.append(f"cifra que no está en los hechos: {n}")
    for hh in re.findall(r"\b\d{1,2}:\d{2}\b", todo):
        if hh not in C:
            errores.append(f"hora que no está en los hechos: {hh}")
    # cifra + unidad: tiene que existir igual en los hechos
    for m in re.finditer(r"(\d+(?:,\d+)?)\s?(°C|mm|%|hm³)", todo):
        par = f"{m.group(1)} {m.group(2)}"
        if par not in C and par.replace(" ", "") not in C:
            errores.append(f"cifra con unidad que no está en los hechos: {par}")
        # si la cifra va ligada a un lugar en los hechos, ese lugar tiene que estar en la misma frase
        # cifra ligada a un lugar: el lugar más cercano en la misma frase tiene que ser el suyo («Jávea, 41,8 mm»)
        dueños = {h["lugar"] for h in hechos if h.get("lugar") and par in (h.get("liga") or [])}
        if dueños:
            cortes = [x.end() for x in re.finditer(r"[.;]\s+(?=[A-ZÁÉÍÓÚÑ¿«])|\n", todo)]
            ini = max([c_ for c_ in cortes if c_ <= m.start()] or [0])
            fin_ = min([c_ for c_ in cortes if c_ > m.end()] or [len(todo)])
            mejor, dist = None, 10 ** 6
            for var, ls in lugares.items():
                for mm_ in re.finditer(re.escape(var), todo[ini:fin_]):
                    pos = ini + mm_.start()
                    if pos < m.start():
                        d_ = m.start() - (pos + len(var))
                    else:  # «41,8 mm en Jávea»: el lugar justo detrás, con «en/de», manda
                        entre = todo[m.end():pos]
                        d_ = 0 if re.fullmatch(r"\s*(?:en|de)\s+(?:la estación de (?:AEMET de )?)?", entre) else (pos - m.end()) + 25
                    if 0 <= d_ < dist:
                        mejor, dist = ls, d_
            if not mejor or not (mejor & dueños):
                errores.append(f"{par} no va con su lugar ({sorted(dueños)[0]})")
    low = todo.lower()
    cl = C.lower()
    for w in PALABRAS_NUM:
        for m in re.finditer(rf"\b{w}\b", low):
            frag = low[m.start():m.start() + 25]
            if not re.search(rf"\b{w}\b", cl):
                errores.append(f"número escrito con letra que no está en los hechos: «{frag.strip()}»")
                break
    for v in VETADAS:
        if re.search(rf"\b{re.escape(v)}", low) and v not in cl:
            errores.append(f"palabra vetada: «{v}»")
    if any(s in low for s in SUPERLATIVOS) and not any(h.get("superlativo") or h.get("record") for h in hechos):
        errores.append("superlativo sin hecho que lo respalde")
    if "récord" in low and not any(h.get("record") for h in hechos):
        errores.append("«récord» sin hecho de récord")
    # nombres propios: palabras con mayúscula que no abren frase
    for m in re.finditer(r"(?<![.!?:¿¡«\"]\s)(?<!^)(?<=\s)([A-ZÁÉÍÓÚÑ][\wáéíóúñü\-/]+)", todo):
        w = m.group(1).strip(".,;:")
        if w and w not in C and w not in NOMBRES_OK:
            errores.append(f"nombre que no está en los hechos: {w}")
    return sorted(set(errores))


# ============================================================================ redacción con Claude
SISTEMA = """Eres redactor de la agencia de noticias de datos climáticos de calentamientoglobal.es. Escribes en español de España para periodistas que publicarán tu nota tal cual o casi.

Reglas que no se rompen nunca:
1. Usa SOLO los hechos que te doy. No añadas cifras, lugares, comparaciones, causas ni contexto que no esté en ellos. Puedes reordenarlos, resumirlos y unirlos.
2. Cada cifra tal y como está escrita en los hechos: mismo redondeo, coma decimal, misma unidad. Escribe las cifras con números, salvo las expresiones que ya vengan con letra en los hechos.
3. Fechas siempre absolutas, como en los hechos («el domingo 18 de octubre»). Prohibido: hoy, ayer, mañana, anoche, esta semana, este mes.
4. Nada de adjetivos dramáticos (histórico, alarmante, sin precedentes, catastrófico). No atribuyas causas al cambio climático. Un superlativo o «récord» solo si el hecho lo dice.
5. Cada cifra de un lugar va con su lugar en la misma frase. Cita la fuente (AEMET, NOAA, MITECO) al menos una vez.
6. Estilo de agencia: frases cortas y concretas, lo más importante primero, voz activa. Nada de relleno.
7. Organismos solo por su sigla, como en los hechos: AEMET, NOAA, MITECO (nunca «Agencia Estatal de Meteorología»). No escribas ningún nombre propio (lugar, estación, organismo, persona) que no aparezca en los hechos.
8. No hagas cálculos ni crees números nuevos: nada de sumas, restas, medias, porcentajes ni redondeos propios. Todas las cantidades en cifras («6 provincias», no «seis provincias»), salvo que el hecho ya las escriba con letra.
9. No escribas la fecha de publicación ni ningún año o día que no esté en los hechos.
10. Palabras prohibidas (un verificador automático rechaza el texto si aparecen): nunca, jamás, histórico, histórica, sin precedentes, inédito, catastrófico, alarmante, apocalíptico, provocado, causado, culpa, analizado, elaborado, calculado, hoy, ayer, mañana, anoche, esta semana, este mes.
11. Los recuentos, rachas, tendencias y medias los calcula el Observatorio climático de calentamientoglobal.es con datos de AEMET, NOAA o MITECO: escribe «con datos de AEMET» o «según los datos de AEMET». Nunca digas que AEMET (u otro organismo) los ha analizado, elaborado o calculado. No cuentes tú elementos de una lista («6 provincias») si el número no está en los hechos.

Devuelve SOLO un JSON válido con estas claves:
{"titular": "máx. 120 caracteres, informativo, con la cifra más fuerte",
 "subtitulo": "1-2 frases que añaden el segundo y tercer dato",
 "entradilla": "2-3 frases: qué, dónde, cuándo y la fuente",
 "cuerpo": ["3-5 párrafos breves"],
 "claves": ["3 frases cortas con los datos esenciales"]}"""


# Solo proveedores con capa gratuita y sin tarjeta: si se agota el cupo, la petición falla (no se cobra) y sale la plantilla.
# Sin ninguna clave, todo sale de plantilla. Coste: cero.
PROVEEDORES = (
    # Gemini: cada modelo tiene su propio cupo gratuito diario (pequeño: unas 20 peticiones en Flash el 18-10-2026);
    # cuando uno se agota se pasa al siguiente. Gemma va sin mensaje de sistema.
    ("Gemini", "GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
     ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemma-4-31b-it", "gemma-4-26b-a4b-it"]),
    ("Groq", "GROQ_API_KEY", "https://api.groq.com/openai/v1/chat/completions",
     ["openai/gpt-oss-120b", "llama-3.3-70b-versatile"]),
)


MODELOS_NO_DISPONIBLES = set()  # en esta pasada (no existe, saturado o límite por minuto)
AGOTADOS_HOY = set()            # cupo gratuito del día agotado; el día de Google acaba a medianoche de California
CUPO_TZ = ZoneInfo("America/Los_Angeles")


def dia_cupo():
    return AHORA.astimezone(CUPO_TZ).date().isoformat()


def proveedores_activos():
    return [p for p in PROVEEDORES if (os.getenv(p[1]) or "").strip()]


def llamar_ia(sistema, usuario, vetados, max_tokens=6000):
    """Devuelve (texto, 'Proveedor · modelo', error). Modelo sin cupo del día → el siguiente; clave mal → el siguiente
    proveedor. Nunca hay cobro: son capas gratuitas sin tarjeta y, sin cupo, la petición simplemente falla."""
    ultimo = "sin clave de IA gratuita"
    for nombre, var, url, modelos in proveedores_activos():
        if nombre in vetados:
            continue
        key = os.getenv(var).strip()
        propio = (os.getenv(var.replace("_API_KEY", "_MODELO")) or "").strip()
        for modelo in [m for m in ([propio] if propio else []) + modelos if m not in MODELOS_NO_DISPONIBLES and m not in AGOTADOS_HOY]:
            razona = modelo.startswith(("gemini", "openai/gpt-oss"))
            sin_sistema = modelo.startswith("gemma")
            estado = "otro"
            for intento in range(3):
                msgs = ([{"role": "user", "content": sistema + "\n\n" + usuario}] if sin_sistema else
                        [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}])
                body = {"model": modelo, "messages": msgs, "max_tokens": max_tokens, "temperature": 0.3}
                if razona:
                    body["reasoning_effort"] = "low"
                req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                             headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
                try:
                    with urllib.request.urlopen(req, timeout=120) as r:
                        d = json.load(r)
                    txt = ((d.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
                    if txt.strip():
                        return txt, f"{nombre} · {modelo}", None
                    ultimo = f"{nombre} {modelo}: respuesta vacía"
                    break
                except urllib.error.HTTPError as e:
                    cuerpo = e.read().decode("utf-8", "ignore")
                    low = cuerpo.lower()
                    ultimo = f"{nombre} {modelo} {e.code} {cuerpo[:200]}"
                    if e.code == 400 and razona and "reasoning" in low:
                        razona = False
                        continue
                    if e.code == 400 and not sin_sistema and ("system" in low or "developer instruction" in low):
                        sin_sistema = True
                        continue
                    if e.code in (401, 403):
                        estado = "clave"
                        break
                    if e.code == 429:
                        if "perday" in low or "per_day" in low or "per day" in low or "daily" in low:
                            estado = "dia"
                            break
                        if intento == 0:
                            m = re.search(r'"retryDelay":\s*"(\d+)', cuerpo)
                            time.sleep(min(int(m.group(1)) if m else int(e.headers.get("Retry-After") or 20), 45))
                            continue
                        estado = "minuto"
                        break
                    if e.code in (400, 404) and any(x in low for x in ("model", "not found", "not_found")):
                        estado = "modelo"
                        break
                    if e.code >= 500 and intento < 2:
                        time.sleep(4 * (intento + 1))
                        continue
                    estado = "saturado" if e.code >= 500 else "otro"
                    break
                except Exception as e:
                    ultimo = f"{nombre} {modelo}: {e}"
                    break
            if estado == "clave":
                vetados.add(nombre)
                LOG.append(f"{nombre}: la clave no vale ({ultimo[:120]})")
                break
            if estado == "dia":
                AGOTADOS_HOY.add(modelo)
                LOG.append(f"{nombre} · {modelo}: cupo gratuito del día agotado")
            elif estado in ("modelo", "saturado", "minuto"):
                MODELOS_NO_DISPONIBLES.add(modelo)
    return None, None, ultimo


def json_de(txt):
    if not txt:
        return None
    m = re.search(r"\{.*\}", txt, re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except Exception:
        return None


class Redactor:
    def __init__(self, cache, max_llamadas):
        self.cache = cache  # hash → texto ya verificado
        self.llamadas = 0
        self.max = max_llamadas
        self.vetados = set()
        self.uso = leer(SALIDA / "uso_ia.json", {}) or {}
        if self.uso.get("fecha") != dia_cupo():  # el día del cupo de Google (medianoche de California)
            self.uso = {"fecha": dia_cupo(), "llamadas": 0, "por_modelo": {}, "agotados": []}
        AGOTADOS_HOY.update(self.uso.get("agotados") or [])
        self.max_dia = int(os.getenv("REDACCION_MAX_DIA", "150"))
        # lo que queda del día se reparte entre las pasadas que faltan (dos por hora), para que no se gaste todo por
        # la mañana: primero las nacionales, luego las provinciales con aviso
        local = AHORA.astimezone(CUPO_TZ)
        quedan = max(1, (24 * 60 - (local.hour * 60 + local.minute)) // 30)
        self.max = min(self.max, max(2, math.ceil((self.max_dia - self.uso["llamadas"]) / quedan)))

    def ia_disponible(self):
        modelos = [m for p in proveedores_activos() if p[0] not in self.vetados for m in p[3]
                   if m not in MODELOS_NO_DISPONIBLES and m not in AGOTADOS_HOY]
        return bool(modelos) and self.llamadas < self.max and self.uso["llamadas"] < self.max_dia

    def redactar(self, hechos, plantilla, encargo, provincial=False, permitir_ia=True):
        clave = hashlib.sha1(json.dumps([[h["id"], h["dice"]] for h in hechos] + [encargo], ensure_ascii=False).encode()).hexdigest()[:16]
        c = self.cache.get(clave)
        if c and not verificar(c["texto"], hechos):
            return c["texto"], {**c["meta"], "cache": True}
        rechazos = []
        if permitir_ia and self.ia_disponible():
            usuario = json.dumps({"encargo": encargo, "fecha_de_publicacion": dia(HOY, anio=True),
                                  "hechos": [{"id": h["id"], "dice": h["dice"], "fuente": h["fuente"]} for h in hechos]}, ensure_ascii=False, indent=1)
            for intento in range(2):
                if not self.ia_disponible():
                    break
                self.llamadas += 1
                self.uso["llamadas"] += 1
                txt, modelo, err = llamar_ia(SISTEMA, usuario + (f"\n\nTu versión anterior no pasó la verificación por esto: {'; '.join(rechazos[-1])}. Corrígelo." if rechazos else ""),
                                             self.vetados)
                if modelo:
                    self.uso["por_modelo"][modelo] = self.uso["por_modelo"].get(modelo, 0) + 1
                if err:
                    rechazos.append([f"IA: {err[:200]}"])
                    break
                t = json_de(txt)
                if not t:
                    rechazos.append(["respuesta sin JSON"])
                    continue
                t = {k: t.get(k) for k in ("titular", "subtitulo", "entradilla", "cuerpo", "claves")}
                if isinstance(t.get("cuerpo"), str):
                    t["cuerpo"] = [t["cuerpo"]]
                errs = verificar(t, hechos)
                if not errs:
                    meta = {"modo": "ia", "modelo": modelo, "verificado": True, "rechazos": rechazos, "hash": clave}
                    self.cache[clave] = {"texto": t, "meta": meta}
                    return t, meta
                rechazos.append(errs)
        # el subtítulo no se repite en el cuerpo (solo se quita texto ya verificado; no se añade nada)
        sub = (plantilla.get("subtitulo") or "").strip()
        if sub:
            cuerpo = list(plantilla.get("cuerpo", []))
            for frase in re.split(r"(?<=\.)\s+(?=[A-ZÁÉÍÓÚÑ¿«])", sub):
                cuerpo = [" ".join(p.replace(frase, " ").split()) for p in cuerpo]
            cuerpo = [p for p in cuerpo if p]
            plantilla = {**plantilla, "cuerpo": cuerpo} if cuerpo else {**plantilla, "subtitulo": ""}
        errs = verificar(plantilla, hechos)
        meta = {"modo": "plantilla", "verificado": not errs, "rechazos": rechazos, "errores_plantilla": errs, "hash": clave}
        if errs:
            LOG.append(f"plantilla con problemas ({encargo[:60]}): {errs}")
        return plantilla, meta


# ============================================================================ principal
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sin-ia", action="store_true", help="no llamar a la API (todo de plantilla)")
    args = ap.parse_args()
    SALIDA.mkdir(parents=True, exist_ok=True)
    (SALIDA / "historias").mkdir(exist_ok=True)
    D = Datos()
    med = mediterraneo_resumen(D)
    hs = []
    ep = g_episodio(D, med)
    if ep:
        hs.append(ep)
    m = g_mediterraneo(D, med, usado=bool(ep and ep["tono"] == "calor"))
    if m:
        hs.append(m)
    for g in (g_lluvia_sequia(D), g_embalses(D)):
        if g:
            hs.append(g)
    hs.extend(g_temporada(D))
    hs.extend(g_records_capitales(D))
    hs.extend(g_records_estaciones(D))
    hs.sort(key=lambda h: -h["puntos"])

    cache = (leer(SALIDA / "cache_redaccion.json", {}) or {})
    R = Redactor(cache, int(os.getenv("REDACCION_MAX_LLAMADAS", "8")))
    ia = not args.sin_ia
    for h in hs:
        h["texto"], h["redaccion"] = R.redactar(h["hechos"], h["plantilla"], f"Noticia nacional · tipo {h['tipo']} · {h['kicker']}", permitir_ia=ia)
    # versiones provinciales: primero las de más peso (avisos); el resto, plantilla
    vers = sorted(((h, cod, v) for h in hs for cod, v in h["provincias"].items()), key=lambda x: -x[2].get("puntos", 0))
    for h, cod, v in vers:
        con_ia = ia and h["tipo"] == "episodio" and v.get("nivel") in ("rojo", "naranja")
        v["texto"], v["redaccion"] = R.redactar(v["hechos"], v["plantilla"], f"Versión para la provincia de {v['provincia']} de la noticia «{h['texto']['titular']}». "
                                                f"Céntrate en {v['provincia']}; lo nacional, solo como contexto.", provincial=True, permitir_ia=con_ia)

    # salida
    ahora = AHORA.strftime("%Y-%m-%dT%H:%M:%SZ")
    resumen, por_prov = [], {}
    def ligera(x):
        """Lo que se publica: el texto final y los hechos (fuente de cada cifra); la plantilla ya no hace falta."""
        x = {k: v for k, v in x.items() if k != "plantilla"}
        x["hechos"] = [{"id": f["id"], "dice": f["dice"], "fuente": f["fuente"]} for f in x.get("hechos", [])]
        return x
    for h in hs:
        h["actualizada"] = ahora
        h["consulta_avisos"], h["corte_lluvia"] = D.consulta, D.corte
        pub = ligera(h)
        pub["provincias"] = {cod: ligera(v) for cod, v in h["provincias"].items()}
        with open(SALIDA / "historias" / f"{h['id']}.json", "w", encoding="utf-8") as f:
            json.dump(pub, f, ensure_ascii=False, separators=(",", ":"))
        resumen.append({"id": h["id"], "tipo": h["tipo"], "kicker": h["kicker"], "tono": h["tono"], "puntos": h["puntos"], "titular": h["texto"]["titular"],
                        "subtitulo": h["texto"].get("subtitulo", ""), "cifras": h["cifras"], "grafico": h.get("grafico"), "redaccion": h["redaccion"].get("modo"),
                        "provincias": sorted(h["provincias"])})
        for cod, v in h["provincias"].items():
            por_prov.setdefault(cod, []).append({"id": h["id"], "tipo": h["tipo"], "kicker": h["kicker"], "tono": h["tono"], "puntos": round(v.get("puntos", 0), 1),
                                                 "titular": v["texto"]["titular"], "subtitulo": v["texto"].get("subtitulo", ""), "cifras": v.get("cifras", []),
                                                 "grafico": v.get("grafico"), "nivel": v.get("nivel")})
    for cod in por_prov:
        por_prov[cod].sort(key=lambda x: -x["puntos"])
    ticker = [x for h in hs for x in h.get("ultima_hora", [])][:5]
    agenda = []
    if D.EMB.get("boletin_fecha"):
        prox = date.fromisoformat(D.EMB["boletin_fecha"]) + timedelta(days=7)
        while prox < HOY:
            prox += timedelta(days=7)
        n = D.EMB["nacional"]
        agenda.append({"fecha": prox.isoformat(), "cuando": dia(prox).capitalize(), "texto": f"Boletín semanal de embalses del MITECO. El del {dia(D.EMB['boletin_fecha'], semana=False)} dejó la reserva en el {f1(n['pct'])} %, "
                       f"{f1(abs(n['pct'] - n['pct_media_10a']))} puntos {'por encima' if n['pct'] > n['pct_media_10a'] else 'por debajo'} de la media de diez años."})
    for f_ef, corto, largo in EFEMERIDES:
        cumple = date(HOY.year, f_ef.month, f_ef.day)
        if 0 <= (cumple - HOY).days <= 30:
            agenda.append({"fecha": cumple.isoformat(), "cuando": dia(cumple).capitalize(), "texto": f"Aniversario de {largo}."})
    agenda.sort(key=lambda x: x["fecha"])
    hoy = {"generado": ahora, "fecha": HOY.isoformat(), "consulta_avisos": D.consulta, "corte_lluvia": D.corte, "llamadas_ia": R.llamadas, "ia": [p[0] for p in proveedores_activos()],
           "portada": [h["id"] for h in hs[:4]], "historias": resumen, "provincias": {cod: {"nombre": nprov(cod), "slug": PROV[cod][1], "historias": v} for cod, v in por_prov.items()},
           "ultima_hora": ticker, "agenda": agenda, "log": LOG[-30:],
           "licencia": "Cálculo y redacción propios de calentamientoglobal.es · CC BY 4.0 · los datos de origen conservan la licencia de su organismo"}
    with open(SALIDA / "hoy.json", "w", encoding="utf-8") as f:
        json.dump(hoy, f, ensure_ascii=False, separators=(",", ":"))
    # archivo de 60 días
    arch = leer(SALIDA / "archivo.json", {"historias": []}) or {"historias": []}
    ids = {h["id"] for h in hs}
    lista = [x for x in arch["historias"] if x["id"] not in ids] + [{"id": h["id"], "fecha": h["fecha"], "tipo": h["tipo"], "titular": h["texto"]["titular"],
                                                                     "provincias": sorted(h["provincias"])} for h in hs]
    lim = (HOY - timedelta(days=60)).isoformat()
    lista = sorted((x for x in lista if x["fecha"] >= lim), key=lambda x: (x["fecha"], x["id"]), reverse=True)
    with open(SALIDA / "archivo.json", "w", encoding="utf-8") as f:
        json.dump({"generado": ahora, "historias": lista}, f, ensure_ascii=False, indent=1)
    # lo que sale del archivo (más de 60 días) se borra: historias y gráficos llevan la fecha delante
    vivos = {x["id"] for x in lista}
    for f in list((SALIDA / "historias").glob("*.json")) + list((SALIDA / "graficos").glob("*")):
        fecha_f = f.name[:10]
        if re.match(r"\d{4}-\d{2}-\d{2}$", fecha_f):
            if fecha_f < lim:
                f.unlink()
        elif f.parent.name == "graficos" or f.stem not in vivos:
            f.unlink()  # nombres antiguos sin fecha
    # caché: solo lo que se ha usado en las últimas pasadas (tope 400)
    R.uso["agotados"] = sorted(AGOTADOS_HOY)
    with open(SALIDA / "uso_ia.json", "w", encoding="utf-8") as f:
        json.dump(R.uso, f, ensure_ascii=False, indent=1)
    with open(SALIDA / "cache_redaccion.json", "w", encoding="utf-8") as f:
        json.dump(dict(list(R.cache.items())[-400:]), f, ensure_ascii=False)
    for h in hs:
        print(f"[{h['puntos']:5.1f}] {h['tipo']:13s} {h['redaccion']['modo']:9s} {'OK ' if h['redaccion'].get('verificado') else 'MAL'} {h['texto']['titular']}")
        if h["redaccion"].get("rechazos"):
            print("        rechazos:", h["redaccion"]["rechazos"])
    print(f"{len(hs)} historias · {sum(len(h['provincias']) for h in hs)} versiones provinciales · {R.llamadas} llamadas a la API")
    for l in LOG:
        print("  !", l)
    return 0


if __name__ == "__main__":
    sys.exit(main())
