#!/usr/bin/env python3
"""
desastres_deflactar_ipc.py
--------------------------
Convierte los costes a euros CONSTANTES del anio base usando el IPC del INE.
Adaptado al repo (datos en docs/).

- Usa docs/desastres_ipc.json como indice (media anual, base 2021=100).
- Si hay conexion, intenta REFRESCAR el indice desde el API publico del INE.
- Soporta el campo opcional 'moneda_anio': el año en cuyos euros esta expresado
  el coste. Si no aparece, se usa el año del evento ('anio'). Esto permite mezclar
  cifras nominales (del año del evento) con cifras ya dadas en euros constantes de
  otro año (p.ej. el ranking historico del Consorcio, en euros de 2015).

Entrada: docs/desastres_eventos_norm.json
Salida:  añade 'coste_meur_const' a cada evento y reescribe el archivo.

Solo libreria estandar.
"""
import json
import os
import sys
import urllib.request

ENTRADA = "desastres_eventos_norm.json"
IPC = "desastres_ipc.json"
INE_URL = "https://servicios.ine.es/wstempus/js/ES/DATOS_SERIE/IPC206449?nult=20"


def localizar_docs():
    aqui = os.path.dirname(os.path.abspath(__file__))
    for c in [os.path.join(os.path.dirname(aqui), "docs"),
              os.path.join(os.getcwd(), "docs"), os.getcwd(), aqui, os.path.dirname(aqui)]:
        if os.path.isfile(os.path.join(c, ENTRADA)):
            return c
    print("ERROR: no encuentro '" + ENTRADA + "'. Ejecuta antes desastres_recopilar_eventos.py.", file=sys.stderr)
    sys.exit(1)


def intentar_refrescar_ine(ipc, docs):
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
            with open(os.path.join(docs, IPC), "w", encoding="utf-8") as f:
                json.dump(ipc, f, ensure_ascii=False, indent=2)
            print("  IPC refrescado desde el INE (" + str(len(nuevo)) + " anios)")
    except Exception as e:
        print("  (aviso) no se pudo refrescar el IPC del INE: " + str(e) + ". Se usa el valor local.")
    return ipc


def main(refrescar=True):
    docs = localizar_docs()
    with open(os.path.join(docs, IPC), "r", encoding="utf-8") as f:
        ipc = json.load(f)
    if refrescar:
        ipc = intentar_refrescar_ine(ipc, docs)
    indice = ipc["indice"]
    base_anio = str(ipc["_meta"]["anio_base"])
    if base_anio not in indice:
        raise ValueError("El anio base " + base_anio + " no esta en el indice IPC")
    i_base = float(indice[base_anio])

    ruta = os.path.join(docs, ENTRADA)
    with open(ruta, "r", encoding="utf-8") as f:
        doc = json.load(f)

    sin_ipc = set()
    for ev in doc["eventos"]:
        # año en cuyos euros esta expresado el coste (por defecto, el del evento)
        moneda = str(ev.get("moneda_anio", ev["anio"]))
        if moneda in indice and float(indice[moneda]) > 0:
            ev["coste_meur_const"] = round(ev["coste_meur"] * (i_base / float(indice[moneda])), 1)
        else:
            ev["coste_meur_const"] = ev["coste_meur"]
            sin_ipc.add(moneda)

    doc["_meta"]["anio_base"] = int(base_anio)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)

    if sin_ipc:
        print("  (aviso) sin IPC para estos anios de moneda, se dejan sin deflactar: " + str(sorted(sin_ipc)))
        print("          añade esos anios a " + IPC + " o usa 'moneda_anio' con un año que si este (p.ej. 2015).")
    print("OK -> deflactado a euros constantes " + base_anio + " (" + str(len(doc["eventos"])) + " eventos)")


if __name__ == "__main__":
    try:
        main(refrescar="--sin-red" not in sys.argv)
    except Exception as e:
        print("ERROR:", e, file=sys.stderr)
        sys.exit(1)
