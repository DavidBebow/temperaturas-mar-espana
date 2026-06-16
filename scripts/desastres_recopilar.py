#!/usr/bin/env python3
"""
desastres_recopilar_eventos.py
------------------------------
Consolida y valida la lista de eventos del contador de desastres.

Adaptado al repo 'temperaturas-mar-espana': los datos viven en docs/.

Entrada principal: docs/desastres_eventos.json
Entrada opcional:  docs/desastres_consorcio.csv  (exportacion de la Estadistica de
                   Riesgos Extraordinarios del Consorcio, si la descargas).

Salida: docs/desastres_eventos_norm.json  (lista normalizada y validada que
        consumen desastres_deflactar_ipc.py y desastres_agregar.py).

Solo libreria estandar de Python 3.
"""
import csv
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(BASE, "docs")

TIPOS_VALIDOS = {
    "inundacion", "sequia", "temporal_invernal", "temporal_costero",
    "ola_de_calor", "incendio", "viento", "otro",
}
CAPAS_VALIDAS = {"asegurado_ccs", "asegurado_seguro", "estimado_total"}


def cargar_json(nombre):
    with open(os.path.join(DOCS, nombre), "r", encoding="utf-8") as f:
        return json.load(f)


def validar(ev, idx):
    errores = []
    for campo in ("id", "anio", "tipo", "coste_meur", "capa"):
        if campo not in ev:
            errores.append(f"falta '{campo}'")
    if ev.get("tipo") not in TIPOS_VALIDOS:
        errores.append(f"tipo no valido: {ev.get('tipo')}")
    if ev.get("capa") not in CAPAS_VALIDAS:
        errores.append(f"capa no valida: {ev.get('capa')}")
    try:
        float(ev.get("coste_meur"))
        int(ev.get("anio"))
    except (TypeError, ValueError):
        errores.append("anio/coste_meur no numericos")
    if errores:
        raise ValueError(f"Evento #{idx} ({ev.get('id','sin-id')}): " + "; ".join(errores))


def cargar_csv_consorcio():
    """Lee docs/desastres_consorcio.csv si existe. Cabecera esperada:
    id,anio,fecha,nombre,tipo,ambito,coste_meur,capa,consolidado,fuente,url
    'ambito' separado por '|'. Devuelve lista de eventos."""
    ruta = os.path.join(DOCS, "desastres_consorcio.csv")
    if not os.path.exists(ruta):
        return []
    eventos = []
    with open(ruta, "r", encoding="utf-8-sig") as f:
        for fila in csv.DictReader(f):
            fila["anio"] = int(fila["anio"])
            fila["coste_meur"] = float(fila["coste_meur"])
            fila["ambito"] = [a.strip() for a in fila.get("ambito", "").split("|") if a.strip()]
            fila["consolidado"] = str(fila.get("consolidado", "")).lower() in ("1", "true", "si", "sí")
            eventos.append(fila)
    print(f"  + {len(eventos)} eventos leidos de desastres_consorcio.csv")
    return eventos


def main():
    base = cargar_json("desastres_eventos.json")
    eventos = list(base.get("eventos", []))
    eventos += cargar_csv_consorcio()

    por_id = {}
    for ev in eventos:
        por_id[ev["id"]] = ev
    eventos = list(por_id.values())

    for i, ev in enumerate(eventos):
        validar(ev, i)

    eventos.sort(key=lambda e: (e["anio"], e.get("fecha", "")))
    salida = {
        "_meta": {
            "n_eventos": len(eventos),
            "umbral_meur": base.get("_meta", {}).get("umbral_meur", 100),
        },
        "eventos": eventos,
    }
    ruta = os.path.join(DOCS, "desastres_eventos_norm.json")
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)
    print(f"OK -> docs/desastres_eventos_norm.json ({len(eventos)} eventos validados)")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERROR:", e, file=sys.stderr)
        sys.exit(1)
