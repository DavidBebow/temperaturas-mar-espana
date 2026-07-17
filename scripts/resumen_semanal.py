#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
resumen_semanal.py — Compone el mensaje semanal de WhatsApp por comunidad.

Lee las fotos diarias de docs/resumen_semanal/diario/ (últimos 7 días),
agrega los datos por comunidad y genera:

  docs/resumen_semanal/ultima_semana.json   ← lo lee el panel de copiado
  docs/resumen_semanal/semanas/<YYYY-Www>/<comunidad>.txt

El texto usa el formato de WhatsApp (*negrita*, _cursiva_) para pegarlo
directamente en cada canal.
"""
import glob
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from resumen_diario import COMUNIDADES  # misma configuración de comunidades

DIR_BASE = os.path.join(os.path.dirname(__file__), "..", "docs", "resumen_semanal")
DIR_DIARIO = os.path.join(DIR_BASE, "diario")

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

URL_OBS = "https://calentamientoglobal.es/observatorio-climatico/"
URL_FIRMA = "https://calentamientoglobal.es/firma-climatica/"
URL_INCENDIOS = "https://calentamientoglobal.es/calentamientoglobal-es-incendios-forestales-espana-tiempo-real/"


def fecha_bonita(iso):
    d = datetime.fromisoformat(iso)
    return f"{DIAS[d.weekday()]} {d.day}"


def cargar_semana(hoy):
    """Fotos de los últimos 7 días (incluido hoy si existe)."""
    fotos = []
    for i in range(7):
        dia = (hoy - timedelta(days=i)).isoformat()
        ruta = os.path.join(DIR_DIARIO, dia + ".json")
        if os.path.exists(ruta):
            with open(ruta, encoding="utf-8") as f:
                fotos.append(json.load(f))
    return sorted(fotos, key=lambda x: x["fecha"])


def agregar(fotos, slug):
    """Agrega la semana para una comunidad."""
    a = {"focos_total": 0, "focos_max": 0, "focos_max_dia": None, "dias_con_fuego": 0,
         "tmax": None, "tmax_ciudad": None, "tmax_dia": None,
         "ifc_max": None, "ifc_ciudad": None, "ifc_dia": None, "pr": None, "delta": None,
         "dias_ifc3": 0, "dias_con_datos": 0}
    for f in fotos:
        c = (f.get("comunidades") or {}).get(slug) or {}
        inc, fir = c.get("incendios"), c.get("firma")
        if inc or fir:
            a["dias_con_datos"] += 1
        if inc:
            focos = inc.get("focos", 0)
            a["focos_total"] += focos
            if focos > 0:
                a["dias_con_fuego"] += 1
            if focos > a["focos_max"]:
                a["focos_max"], a["focos_max_dia"] = focos, f["fecha"]
        if fir:
            if fir.get("tmax") is not None and (a["tmax"] is None or fir["tmax"] > a["tmax"]):
                a["tmax"], a["tmax_ciudad"], a["tmax_dia"] = fir["tmax"], fir.get("tmax_ciudad"), f["fecha"]
            ifc = fir.get("ifc")
            if ifc is not None:
                if a["ifc_max"] is None or ifc > a["ifc_max"]:
                    a["ifc_max"], a["ifc_ciudad"], a["ifc_dia"] = ifc, fir.get("ifc_ciudad"), f["fecha"]
                    a["pr"], a["delta"] = fir.get("pr"), fir.get("delta")
                if ifc >= 3:
                    a["dias_ifc3"] += 1
    return a


def agregar_mar(fotos, clave):
    ultimo = None
    for f in fotos:
        m = (f.get("mar") or {}).get(clave)
        if m:
            ultimo = m
    return ultimo


def componer(slug, cfg, a, mar, inicio, fin):
    """Texto WhatsApp para una comunidad."""
    lineas = []
    lineas.append(f"*🌍 El clima de la semana en {cfg['nombre']}*")
    lineas.append(f"_Semana del {inicio.day} al {fin.day} de {MESES[fin.month-1]} · calentamientoglobal.es_")
    lineas.append("")

    # Calor / firma climática
    if a["tmax"] is not None:
        linea = f"🌡️ *Calor:* máxima de la semana, *{a['tmax']:.1f} °C* en {a['tmax_ciudad']} ({fecha_bonita(a['tmax_dia'])})."
        if a["pr"] and a["pr"] >= 2:
            linea += f" El cambio climático hizo ese calor *{a['pr']:.0f}× más probable*."
        lineas.append(linea)
        if a["dias_ifc3"] > 0:
            lineas.append(f"🔬 *Firma climática:* {a['dias_ifc3']} día(s) con huella clara del cambio climático (índice ≥3) — máximo en {a['ifc_ciudad']}, con *+{a['delta']:.1f} °C* añadidos al día. {URL_FIRMA}")
    # Incendios
    if a["focos_total"] > 0:
        lineas.append(f"🔥 *Incendios:* {a['focos_total']} focos detectados por satélite en {a['dias_con_fuego']} día(s); pico de {a['focos_max']} focos el {fecha_bonita(a['focos_max_dia'])}. Mapa en directo: {URL_INCENDIOS}")
    elif a["dias_con_datos"] > 0:
        lineas.append("🔥 *Incendios:* ✓ sin focos detectados por satélite esta semana.")
    # Mar
    if mar and cfg.get("mar"):
        nombre_mar = mar.get("nombre") or ("el Mediterráneo" if cfg["mar"] == "med" else "el Atlántico")
        if (mar.get("anomalia") or 0) >= 1:
            lineas.append(f"🌊 *Mar:* {nombre_mar} sigue en ola de calor marina: anomalía de *+{mar['anomalia']:.1f} °C*, {mar.get('racha', '?')} días seguidos.")
    lineas.append("")
    lineas.append(f"📊 Todos los datos, en directo: {URL_OBS}")
    lineas.append("_Fuentes: NASA FIRMS, Copernicus/ERA5, NOAA · Observatorio Climático de calentamientoglobal.es_")
    return "\n".join(lineas)


def lineas_una_linea(a, mar, cfg):
    """Versión de una sola línea por sección, para la plantilla de la
    WhatsApp Cloud API (los parámetros no admiten saltos de línea) y para
    el asunto/cuerpo del email. Nunca devuelve cadenas vacías."""
    if a["tmax"] is not None:
        calor = f"Máxima de la semana: {a['tmax']:.1f} °C en {a['tmax_ciudad']} ({fecha_bonita(a['tmax_dia'])})"
        if a["pr"] and a["pr"] >= 2:
            calor += f". El cambio climático hizo ese calor {a['pr']:.0f}× más probable"
        calor += "."
    else:
        calor = "Sin datos de calor destacables esta semana."
    if a["focos_total"] > 0:
        incendios = (f"{a['focos_total']} focos detectados por satélite en {a['dias_con_fuego']} día(s); "
                     f"pico de {a['focos_max']} el {fecha_bonita(a['focos_max_dia'])}.")
    elif a["dias_con_datos"] > 0:
        incendios = "Sin focos detectados por satélite esta semana."
    else:
        incendios = "Sin datos de incendios esta semana."
    if mar and cfg.get("mar") and (mar.get("anomalia") or 0) >= 1:
        nombre_mar = mar.get("nombre") or ("el Mediterráneo" if cfg["mar"] == "med" else "el Atlántico")
        linea_mar = f"{nombre_mar} en ola de calor marina: +{mar['anomalia']:.1f} °C, {mar.get('racha', '?')} días seguidos."
    else:
        linea_mar = "Sin ola de calor marina destacable."
    limpiar = lambda s: " ".join(str(s).split())  # sin saltos de línea ni dobles espacios
    return {"calor": limpiar(calor), "incendios": limpiar(incendios), "mar": limpiar(linea_mar)}


def main():
    hoy = datetime.now(ZoneInfo("Europe/Madrid")).date()
    fotos = cargar_semana(hoy)
    if not fotos:
        raise SystemExit("No hay fotos diarias en " + DIR_DIARIO)

    inicio = datetime.fromisoformat(fotos[0]["fecha"]).date()
    fin = datetime.fromisoformat(fotos[-1]["fecha"]).date()
    etiqueta = f"{fin.isocalendar().year}-W{fin.isocalendar().week:02d}"
    dir_semana = os.path.join(DIR_BASE, "semanas", etiqueta)
    os.makedirs(dir_semana, exist_ok=True)

    resultado = {"generado": datetime.now(ZoneInfo("Europe/Madrid")).isoformat(timespec="minutes"),
                 "semana": {"inicio": inicio.isoformat(), "fin": fin.isoformat(), "etiqueta": etiqueta},
                 "dias_con_datos": len(fotos),
                 "comunidades": {}}

    for slug, cfg in COMUNIDADES.items():
        a = agregar(fotos, slug)
        mar = agregar_mar(fotos, cfg.get("mar")) if cfg.get("mar") else None
        texto = componer(slug, cfg, a, mar, inicio, fin)
        resultado["comunidades"][slug] = {"nombre": cfg["nombre"], "texto": texto,
                                          "lineas": lineas_una_linea(a, mar, cfg),
                                          "semana_legible": f"Semana del {inicio.day} al {fin.day} de {MESES[fin.month-1]}",
                                          "agregado": a}
        with open(os.path.join(dir_semana, slug + ".txt"), "w", encoding="utf-8") as f:
            f.write(texto)

    with open(os.path.join(DIR_BASE, "ultima_semana.json"), "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=1)
    print(f"Resumen semanal {etiqueta} generado ({len(fotos)} días, {len(COMUNIDADES)} comunidades).")


if __name__ == "__main__":
    main()
