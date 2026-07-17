#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
resumen_diario.py — Foto diaria por comunidad para el Resumen Semanal.

Lee los JSON que ya publican tus herramientas (incendios, firma climática,
olas de calor marinas) y guarda una foto compacta del día en
docs/resumen_semanal/diario/YYYY-MM-DD.json

Se ejecuta 1 vez al día desde GitHub Actions. Si una fuente falla, se omite
esa sección sin romper el resto.
"""
import json
import os
import sys
import unicodedata
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

BASE = "https://davidbebow.github.io/temperaturas-mar-espana/"
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "resumen_semanal", "diario")

# ── Comunidades piloto ────────────────────────────────────────────────────────
# Para añadir una comunidad: añade una entrada con sus provincias (tal como
# aparecen en firma_climatica.json) y las palabras clave con las que aparece
# en incendios.json. "mar": "med" | "atl" | None.
COMUNIDADES = {
    "andalucia": {"nombre": "Andalucía",
        "provincias": ["Almería", "Cádiz", "Córdoba", "Granada", "Huelva", "Jaén", "Málaga", "Sevilla"],
        "incendios_claves": ["andalucia"], "mar": "med"},
    "aragon": {"nombre": "Aragón",
        "provincias": ["Huesca", "Teruel", "Zaragoza"],
        "incendios_claves": ["aragon"], "mar": None},
    "asturias": {"nombre": "Principado de Asturias",
        "provincias": ["Asturias"],
        "incendios_claves": ["asturias"], "mar": "atl"},
    "baleares": {"nombre": "Illes Balears",
        "provincias": ["Illes Balears"],
        "incendios_claves": ["balear", "illes"], "mar": "med"},
    "canarias": {"nombre": "Canarias",
        "provincias": ["Santa Cruz de Tenerife", "Las Palmas"],
        "incendios_claves": ["canaria"], "mar": "atl"},
    "cantabria": {"nombre": "Cantabria",
        "provincias": ["Cantabria"],
        "incendios_claves": ["cantabria"], "mar": "atl"},
    "castilla-la-mancha": {"nombre": "Castilla-La Mancha",
        "provincias": ["Albacete", "Ciudad Real", "Cuenca", "Guadalajara", "Toledo"],
        "incendios_claves": ["mancha"], "mar": None},
    "castilla-y-leon": {"nombre": "Castilla y León",
        "provincias": ["Ávila", "Burgos", "León", "Palencia", "Salamanca", "Segovia", "Soria", "Valladolid", "Zamora"],
        "incendios_claves": ["castilla y leon", "castilla-y-leon", "castilla_y_leon", "castilla leon", "castilla-leon"], "mar": None},
    "cataluna": {"nombre": "Cataluña",
        "provincias": ["Barcelona", "Girona", "Lleida", "Tarragona"],
        "incendios_claves": ["catalu"], "mar": "med"},
    "ceuta": {"nombre": "Ceuta",
        "provincias": ["Ceuta"],
        "incendios_claves": ["ceuta"], "mar": "med"},
    "comunidad-valenciana": {"nombre": "Comunitat Valenciana",
        "provincias": ["Alicante", "Castellón", "Valencia"],
        "incendios_claves": ["valencia"], "mar": "med"},
    "extremadura": {"nombre": "Extremadura",
        "provincias": ["Badajoz", "Cáceres"],
        "incendios_claves": ["extremadura"], "mar": None},
    "galicia": {"nombre": "Galicia",
        "provincias": ["A Coruña", "Lugo", "Ourense", "Pontevedra"],
        "incendios_claves": ["galicia"], "mar": "atl"},
    "la-rioja": {"nombre": "La Rioja",
        "provincias": ["La Rioja"],
        "incendios_claves": ["rioja"], "mar": None},
    "madrid": {"nombre": "Comunidad de Madrid",
        "provincias": ["Madrid"],
        "incendios_claves": ["madrid"], "mar": None},
    "melilla": {"nombre": "Melilla",
        "provincias": ["Melilla"],
        "incendios_claves": ["melilla"], "mar": "med"},
    "murcia": {"nombre": "Región de Murcia",
        "provincias": ["Murcia"],
        "incendios_claves": ["murcia"], "mar": "med"},
    "navarra": {"nombre": "Navarra",
        "provincias": ["Navarra"],
        "incendios_claves": ["navarra"], "mar": None},
    "pais-vasco": {"nombre": "País Vasco",
        "provincias": ["Álava", "Bizkaia", "Gipuzkoa"],
        "incendios_claves": ["vasco", "euskadi"], "mar": "atl"},
}


# ── Provincias (nivel de suscripción del email) ──────────────────────────────
# Clave = campo "provincia" de firma_climatica.json. mar: "med" | "atl" | None.
PROVINCIAS = {
    "Almería": ("andalucia", "med"), "Cádiz": ("andalucia", "atl"), "Córdoba": ("andalucia", None),
    "Granada": ("andalucia", "med"), "Huelva": ("andalucia", "atl"), "Jaén": ("andalucia", None),
    "Málaga": ("andalucia", "med"), "Sevilla": ("andalucia", None),
    "Huesca": ("aragon", None), "Teruel": ("aragon", None), "Zaragoza": ("aragon", None),
    "Asturias": ("asturias", "atl"),
    "Illes Balears": ("baleares", "med"),
    "Santa Cruz de Tenerife": ("canarias", "atl"), "Las Palmas": ("canarias", "atl"),
    "Cantabria": ("cantabria", "atl"),
    "Albacete": ("castilla-la-mancha", None), "Ciudad Real": ("castilla-la-mancha", None),
    "Cuenca": ("castilla-la-mancha", None), "Guadalajara": ("castilla-la-mancha", None),
    "Toledo": ("castilla-la-mancha", None),
    "Ávila": ("castilla-y-leon", None), "Burgos": ("castilla-y-leon", None), "León": ("castilla-y-leon", None),
    "Palencia": ("castilla-y-leon", None), "Salamanca": ("castilla-y-leon", None),
    "Segovia": ("castilla-y-leon", None), "Soria": ("castilla-y-leon", None),
    "Valladolid": ("castilla-y-leon", None), "Zamora": ("castilla-y-leon", None),
    "Barcelona": ("cataluna", "med"), "Girona": ("cataluna", "med"),
    "Lleida": ("cataluna", None), "Tarragona": ("cataluna", "med"),
    "Ceuta": ("ceuta", "med"),
    "Alicante": ("comunidad-valenciana", "med"), "Castellón": ("comunidad-valenciana", "med"),
    "Valencia": ("comunidad-valenciana", "med"),
    "Badajoz": ("extremadura", None), "Cáceres": ("extremadura", None),
    "A Coruña": ("galicia", "atl"), "Lugo": ("galicia", "atl"),
    "Ourense": ("galicia", None), "Pontevedra": ("galicia", "atl"),
    "La Rioja": ("la-rioja", None),
    "Madrid": ("madrid", None),
    "Melilla": ("melilla", "med"),
    "Murcia": ("murcia", "med"),
    "Navarra": ("navarra", None),
    "Álava": ("pais-vasco", None), "Bizkaia": ("pais-vasco", "atl"), "Gipuzkoa": ("pais-vasco", "atl"),
}


def norm(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower()


def slug_prov(nombre):
    """'Santa Cruz de Tenerife' -> 'santa-cruz-de-tenerife' (debe coincidir con el plugin)."""
    return norm(nombre).replace(" ", "-")


def fetch(nombre):
    # 1º: archivo local del propio repo (en Actions el repo ya está clonado
    # y estos JSON viven en docs/ — sin red, sin 404 posibles).
    local = os.path.join(os.path.dirname(__file__), "..", "docs", nombre)
    if os.path.exists(local):
        try:
            with open(local, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[aviso] {nombre} local ilegible: {e}", file=sys.stderr)
    # 2º: respaldo por HTTP (GitHub Pages), con user-agent de navegador.
    url = BASE + nombre
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (resumen-semanal calentamientoglobal.es)"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except Exception as e:
        print(f"[aviso] no se pudo leer {nombre} (local ni web): {e}", file=sys.stderr)
        return None


def foto_incendios(data):
    """Devuelve {slug: {focos, frp}} a partir de incendios.json."""
    out = {}
    if not data or not isinstance(data.get("comunidades"), list):
        return out
    for slug, cfg in COMUNIDADES.items():
        for c in data["comunidades"]:
            etiqueta = norm(c.get("id", "")) + " " + norm(c.get("nombre", ""))
            if any(k in etiqueta for k in cfg["incendios_claves"]):
                out[slug] = {
                    "focos": int(c.get("focos_activos") or c.get("focos") or 0),
                    "frp": round(float(c.get("frp") or c.get("frp_total") or 0), 1),
                }
                break
    return out


def foto_firma(data):
    """Devuelve {slug: {tmax, ciudad, ifc, pr, delta}} con la capital más
    llamativa del día (mayor IFC y, a igualdad, mayor tmax)."""
    out = {}
    if not data or not isinstance(data.get("ciudades"), list):
        return out
    for slug, cfg in COMUNIDADES.items():
        provincias = set(cfg["provincias"])
        candidatas = [c for c in data["ciudades"] if c.get("provincia") in provincias]
        if not candidatas:
            continue
        top = max(candidatas, key=lambda c: (c.get("ifc", 0), c.get("tmax", 0)))
        tmax_top = max(candidatas, key=lambda c: c.get("tmax", 0))
        out[slug] = {
            "ifc": top.get("ifc"),
            "ifc_ciudad": top.get("nombre"),
            "pr": top.get("pr"),
            "delta": top.get("delta"),
            "tmax": tmax_top.get("tmax"),
            "tmax_ciudad": tmax_top.get("nombre"),
        }
    return out


def foto_provincias(data):
    """Devuelve {slug_provincia: {capital, tmax, ifc, pr, delta}} desde firma_climatica.json."""
    out = {}
    if not data or not isinstance(data.get("ciudades"), list):
        return out
    for c in data["ciudades"]:
        prov = c.get("provincia")
        if prov in PROVINCIAS:
            out[slug_prov(prov)] = {
                "capital": c.get("nombre"),
                "tmax": c.get("tmax"),
                "ifc": c.get("ifc"),
                "pr": c.get("pr"),
                "delta": c.get("delta"),
            }
    return out


def foto_mar(data):
    """Devuelve {"med": {...}, "atl": {...}} desde oceano.json (cuencas)."""
    out = {}
    if not data or not isinstance(data.get("cuencas"), list):
        return out
    for c in data["cuencas"]:
        ident = norm(c.get("id", ""))
        clave = "med" if "mediterraneo" in ident else ("atl" if "atlantico" in ident else None)
        if clave and clave not in out:
            out[clave] = {
                "anomalia": c.get("anomalia"),
                "categoria": c.get("categoria"),
                "racha": c.get("racha"),
                "nombre": c.get("nombre"),
            }
    return out


def main():
    hoy = datetime.now(ZoneInfo("Europe/Madrid")).date().isoformat()
    incendios = foto_incendios(fetch("incendios.json"))
    datos_firma = fetch("firma_climatica.json")
    firma = foto_firma(datos_firma)
    mar = foto_mar(fetch("oceano.json"))

    foto = {"fecha": hoy, "comunidades": {}, "provincias": foto_provincias(datos_firma), "mar": mar}
    for slug in COMUNIDADES:
        foto["comunidades"][slug] = {
            "incendios": incendios.get(slug),
            "firma": firma.get(slug),
        }

    os.makedirs(OUT_DIR, exist_ok=True)
    ruta = os.path.join(OUT_DIR, hoy + ".json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(foto, f, ensure_ascii=False, indent=1)
    print("Foto diaria guardada:", ruta)


if __name__ == "__main__":
    main()
