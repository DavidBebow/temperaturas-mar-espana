#!/usr/bin/env python3
"""
desastres_agregar.py
--------------------
Agrega los eventos por anio y tipo, calcula acumulados y coste por habitante,
y genera los JSON que consume la web. Adaptado al repo (datos en docs/).

Entrada:
  docs/desastres_eventos_norm.json
  docs/desastres_series_eea.json

Salida:
  docs/desastres_anual.json
  docs/desastres_meta.json

Solo libreria estandar.
"""
import json
import os
import sys
from datetime import date

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(BASE, "docs")


def cargar(nombre):
    with open(os.path.join(DOCS, nombre), "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    doc = cargar("desastres_eventos_norm.json")
    eea = cargar("desastres_series_eea.json")
    eventos = doc["eventos"]

    anios, tipos = {}, set()
    for ev in eventos:
        a, t = int(ev["anio"]), ev["tipo"]
        tipos.add(t)
        coste = ev.get("coste_meur_const", ev["coste_meur"])
        anios.setdefault(a, {})
        anios[a][t] = round(anios[a].get(t, 0) + coste, 1)

    anual = [{"anio": a, "tipos": anios[a], "total_meur": round(sum(anios[a].values()), 1)}
             for a in sorted(anios)]

    suma_eventos = round(sum(f["total_meur"] for f in anual), 1)
    acum_eea = eea.get("acumulado_total_meur", {}).get("valor_meur", 0)
    poblacion = eea.get("poblacion_ref", 48000000)
    acumulado_total = max(acum_eea, suma_eventos)
    por_habitante = round(acumulado_total * 1_000_000 / poblacion)

    with open(os.path.join(DOCS, "desastres_anual.json"), "w", encoding="utf-8") as f:
        json.dump({"_meta": {"unidad": "millones_euros_constantes", "tipos": sorted(tipos)},
                   "anios": anual}, f, ensure_ascii=False, indent=2)

    meta = {
        "actualizado": date.today().isoformat(),
        "acumulado_total_meur": acumulado_total,
        "acumulado_periodo": eea.get("acumulado_total_meur", {}).get("periodo", ""),
        "coste_por_habitante_eur": por_habitante,
        "poblacion_ref": poblacion,
        "suma_eventos_documentados_meur": suma_eventos,
        "n_eventos": len(eventos),
        "fuente_acumulado": "European Environment Agency (perdidas economicas 1980-2023)",
    }
    with open(os.path.join(DOCS, "desastres_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print("OK -> docs/desastres_anual.json y docs/desastres_meta.json")
    print(f"   acumulado: {acumulado_total:,.0f} M€  |  {por_habitante:,} €/hab  |  {len(eventos)} eventos")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ERROR:", e, file=sys.stderr)
        sys.exit(1)
