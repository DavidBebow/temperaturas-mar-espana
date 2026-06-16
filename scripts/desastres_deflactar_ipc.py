#!/usr/bin/env python3
"""
desastres_deflactar_ipc.py
--------------------------
Convierte los costes en euros CORRIENTES a euros CONSTANTES del anio base
usando el IPC general del INE. Adaptado al repo (datos en docs/).

- Usa docs/desastres_ipc.json como indice (media anual, base 2021=100).
- Si hay conexion, intenta REFRESCAR el indice desde el API publico del INE
  (sin clave) y reescribe docs/desastres_ipc.json. Si falla, sigue con el local.

Entrada: docs/desastres_eventos_norm.json
Salida:  añade 'coste_meur_const' a cada evento y reescribe el archivo.

Solo libreria estandar.
"""
import json
import os
import sys
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(BASE, "docs")

# Serie IPC general nacional, indice media anual (INE). Endpoint sin clave.
INE_URL = "https://servicios.ine.es/wstempus/js/ES/DATOS_SERIE/IPC206449?nult=20"


def cargar_ipc():
    with open(os.path.join(DOCS, "desastres_ipc.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def intentar_refrescar_ine(ipc):
    try:
        req = urllib.request.Request(INE_URL, headers={"User-Agent": "calentamientoglobal-bot"})
        with urllib.request.urlopen(req, timeout=15) as r:
            datos = json.loads(r.read().decode("utf-8"))
        nuevo = {}
        for d in datos.get("Data", []):
            anio, val = d.get("Anyo"), d.get("Valor")
            if anio and val:
                nuevo[str(anio)] = round(float(val), 3)
        if nuevo:
            ipc["indice"].update(nuevo)
            ipc["_meta"]["actualizado_ine"] = True
            with open(os.path.join(DOCS, "desastres_ipc.json"), "w", encoding="utf-8") as f:
                json.dump(ipc, f, ensure_ascii=False, indent=2)
            print(f"  IPC refrescado desde el INE ({len(nuevo)} anios)")
    except Exception as e:
        print(f"  (aviso) no se pudo refrescar el IPC del INE: {e}. Se usa el valor local.")
    return ipc


def main(refrescar=True):
    ipc = cargar_ipc()
    if refrescar:
        ipc = intentar_refrescar_ine(ipc)
    indice = ipc["indice"]
    base_anio = str(ipc["_meta"]["anio_base"])
    if base_anio not in indice:
        raise ValueError(f"El anio base {base_anio} no esta en el indice IPC")
    i_base = float(indice[base_anio])

    ruta = os.path.join(DOCS, "desastres_eventos_norm.json")
    with open(ruta, "r", encoding="utf-8") as f:
        doc = json.load(f)

    sin_ipc = set()
    for ev in doc["eventos"]:
        a = str(ev["anio"])
        if a in indice and float(indice[a]) > 0:
            ev["coste_meur_const"] = round(ev["coste_meur"] * (i_base / float(indice[a])), 1)
        else:
            ev["coste_meur_const"] = ev["coste_meur"]
            sin_ipc.add(a)

    doc["_meta"]["anio_base"] = int(base_anio)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)

    if sin_ipc:
        print(f"  (aviso) anios sin IPC, se dejan en corrientes: {sorted(sin_ipc)}")
    print(f"OK -> deflactado a euros constantes {base_anio} ({len(doc['eventos'])} eventos)")


if __name__ == "__main__":
    try:
        main(refrescar="--sin-red" not in sys.argv)
    except Exception as e:
        print("ERROR:", e, file=sys.stderr)
        sys.exit(1)
