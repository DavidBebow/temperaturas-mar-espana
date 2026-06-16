#!/usr/bin/env python3
"""
desastres_recopilar_eventos.py
------------------------------
Consolida y valida la lista de eventos del contador de desastres.

Repo 'temperaturas-mar-espana': los datos viven en la carpeta docs/.

Entrada principal: docs/desastres_eventos.json
Entrada opcional:  docs/desastres_consorcio.csv  (exportacion de la Estadistica de
                   Riesgos Extraordinarios del Consorcio, si la descargas).
Salida:            docs/desastres_eventos_norm.json

Funciona aunque lo lances desde cualquier carpeta: localiza solo la carpeta docs/.
Solo libreria estandar de Python 3 (no hay que instalar nada).
"""
import csv
import json
import os
import sys

ENTRADA = "desastres_eventos.json"
SALIDA = "desastres_eventos_norm.json"
CSV_OPCIONAL = "desastres_consorcio.csv"

TIPOS_VALIDOS = {
    "inundacion", "sequia", "temporal_invernal", "temporal_costero",
    "ola_de_calor", "incendio", "viento", "otro",
}
CAPAS_VALIDAS = {"asegurado_ccs", "asegurado_seguro", "estimado_total"}


def localizar_docs():
    """Busca la carpeta que contiene desastres_eventos.json en varias ubicaciones
    razonables, para que el script funcione sin importar desde donde se lance."""
    aqui = os.path.dirname(os.path.abspath(__file__))
    candidatas = [
        os.path.join(os.path.dirname(aqui), "docs"),  # repo/scripts -> repo/docs (lo normal)
        os.path.join(os.getcwd(), "docs"),            # <cwd>/docs
        os.getcwd(),                                  # el propio cwd
        aqui,                                         # junto al script
        os.path.dirname(aqui),                        # carpeta padre del script
    ]
    for c in candidatas:
        if os.path.isfile(os.path.join(c, ENTRADA)):
            return c
    # No encontrado: mensaje claro
    print("ERROR: no encuentro el archivo de entrada '" + ENTRADA + "'.", file=sys.stderr)
    print("Lo he buscado en estas carpetas:", file=sys.stderr)
    for c in candidatas:
        print("   - " + c, file=sys.stderr)
    print("\nSolucion: asegurate de que '" + ENTRADA + "' esta subido dentro de la", file=sys.stderr)
    print("carpeta 'docs/' del repositorio, junto a contador-desastres.html.", file=sys.stderr)
    sys.exit(1)


def validar(ev, idx):
    errores = []
    for campo in ("id", "anio", "tipo", "coste_meur", "capa"):
        if campo not in ev:
            errores.append("falta '" + campo + "'")
    if ev.get("tipo") not in TIPOS_VALIDOS:
        errores.append("tipo no valido: " + str(ev.get("tipo")) + " (validos: " + ", ".join(sorted(TIPOS_VALIDOS)) + ")")
    if ev.get("capa") not in CAPAS_VALIDAS:
        errores.append("capa no valida: " + str(ev.get("capa")) + " (validas: " + ", ".join(sorted(CAPAS_VALIDAS)) + ")")
    try:
        float(ev.get("coste_meur"))
        int(ev.get("anio"))
    except (TypeError, ValueError):
        errores.append("anio/coste_meur no numericos")
    if errores:
        raise ValueError("Evento #" + str(idx) + " (" + str(ev.get("id", "sin-id")) + "): " + "; ".join(errores))


def cargar_csv_consorcio(docs):
    """Lee desastres_consorcio.csv si existe. Cabecera esperada:
    id,anio,fecha,nombre,tipo,ambito,coste_meur,capa,consolidado,fuente,url
    'ambito' separado por '|'."""
    ruta = os.path.join(docs, CSV_OPCIONAL)
    if not os.path.isfile(ruta):
        return []
    eventos = []
    try:
        with open(ruta, "r", encoding="utf-8-sig") as f:
            for n, fila in enumerate(csv.DictReader(f), start=2):
                fila["anio"] = int(fila["anio"])
                fila["coste_meur"] = float(str(fila["coste_meur"]).replace(",", "."))
                fila["ambito"] = [a.strip() for a in str(fila.get("ambito", "")).split("|") if a.strip()]
                fila["consolidado"] = str(fila.get("consolidado", "")).strip().lower() in ("1", "true", "si", "sí")
                eventos.append(fila)
    except Exception as e:
        print("ERROR leyendo " + CSV_OPCIONAL + " (fila ~" + str(n) + "): " + str(e), file=sys.stderr)
        sys.exit(1)
    print("  + " + str(len(eventos)) + " eventos leidos de " + CSV_OPCIONAL)
    return eventos


def main():
    docs = localizar_docs()
    ruta_entrada = os.path.join(docs, ENTRADA)
    try:
        with open(ruta_entrada, "r", encoding="utf-8") as f:
            base = json.load(f)
    except json.JSONDecodeError as e:
        print("ERROR: '" + ENTRADA + "' tiene un error de formato JSON: " + str(e), file=sys.stderr)
        print("Revisa que no falten comas o comillas. Puedes validarlo en https://jsonlint.com", file=sys.stderr)
        sys.exit(1)

    eventos = list(base.get("eventos", []))
    if not eventos:
        print("AVISO: la lista 'eventos' de " + ENTRADA + " esta vacia.", file=sys.stderr)
    eventos += cargar_csv_consorcio(docs)

    # dedup por id (gana el ultimo)
    por_id = {}
    for ev in eventos:
        if "id" not in ev:
            raise ValueError("Hay un evento sin 'id' en " + ENTRADA)
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
    ruta_salida = os.path.join(docs, SALIDA)
    with open(ruta_salida, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)
    print("OK -> docs/" + SALIDA + " (" + str(len(eventos)) + " eventos validados)")


if __name__ == "__main__":
    try:
        main()
    except ValueError as e:
        print("ERROR de validacion:", e, file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print("ERROR inesperado:", type(e).__name__, "-", e, file=sys.stderr)
        sys.exit(1)
