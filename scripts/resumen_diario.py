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
    "murcia": {
        "nombre": "Región de Murcia",
        "provincias": ["Murcia"],
        "incendios_claves": ["murcia"],
        "mar": "med",
    },
    "andalucia": {
        "nombre": "Andalucía",
        "provincias": ["Almería", "Cádiz", "Córdoba", "Granada", "Huelva", "Jaén", "Málaga", "Sevilla"],
        "incendios_claves": ["andalucia"],
        "mar": "med",
    },
    "comunidad-valenciana": {
        "nombre": "Comunitat Valenciana",
        "provincias": ["Alicante", "Castellón", "Valencia"],
        "incendios_claves": ["valencia"],
        "mar": "med",
    },
    "galicia": {
        "nombre": "Galicia",
        "provincias": ["A Coruña", "Lugo", "Ourense", "Pontevedra"],
        "incendios_claves": ["galicia"],
        "mar": "atl",
    },
}


def norm(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower()


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
    firma = foto_firma(fetch("firma_climatica.json"))
    mar = foto_mar(fetch("oceano.json"))

    foto = {"fecha": hoy, "comunidades": {}, "mar": mar}
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
