#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Climatología de focos de fuego en la Amazonía (2003 → año pasado)

Descarga los ficheros anuales del satélite de referencia que publica el INPE
para América del Sur y calcula, con la MISMA definición de Amazonía que usa
obtener_amazonia_fuego.py, la media de focos por mes y por día del año. Ese
fichero es el que convierte «hoy ha habido 3.100 focos» en «hoy ha habido un
40 % más de focos que la media de las dos últimas décadas para esta fecha»,
que es la frase que se puede citar.

Es pesado (23 ficheros comprimidos, del orden de cientos de MB en total) y no
tiene ningún sentido ejecutarlo a diario: se lanza a mano o una vez al año,
cuando el INPE cierra el año anterior.

    python amazonia_fuego_climatologia.py --desde 2003 --hasta 2025

Salida: docs/amazonia/fuego_climatologia.json
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import zipfile
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from obtener_amazonia_fuego import (  # noqa: E402  (reutilizamos la definición)
    SATELITE_REFERENCIA,
    clasifica,
)

RAIZ = Path(__file__).resolve().parent.parent
SALIDA = RAIZ / "docs" / "amazonia" / "fuego_climatologia.json"
BASE = ("https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/"
        "anual/AMS_sat_ref/focos_ams_ref_{anio}.zip")
TIEMPO_ESPERA = 900


def log(msg: str) -> None:
    print(f"[clima-fuego] {msg}", flush=True)


def procesar_anio(anio: int) -> tuple[dict[int, int], dict[str, int], dict[str, int]]:
    """Devuelve (focos por mes, focos por día-del-año, focos por país)."""
    url = BASE.format(anio=anio)
    log(f"descargando {url}")
    r = requests.get(url, timeout=TIEMPO_ESPERA)
    r.raise_for_status()

    por_mes: dict[int, int] = defaultdict(int)
    por_dia: dict[str, int] = defaultdict(int)
    por_pais: dict[str, int] = defaultdict(int)

    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for nombre in z.namelist():
            if not nombre.lower().endswith(".csv"):
                continue
            with z.open(nombre) as fh:
                texto = io.TextIOWrapper(fh, encoding="utf-8", errors="replace")
                lector = csv.DictReader(texto)
                for fila in lector:
                    sat = (fila.get("satelite") or "").strip()
                    # los ficheros 'sat_ref' ya vienen filtrados, pero por si acaso
                    if sat and sat != SATELITE_REFERENCIA:
                        continue
                    if clasifica(fila.get("pais", ""), fila.get("estado", ""),
                                 fila.get("bioma", "")) != "amazonia":
                        continue
                    # los anuarios del satélite de referencia traen otro esquema
                    # que los ficheros diarios: la fecha se llama 'data_pas' y no
                    # hay columna 'satelite' (ya vienen filtrados)
                    fecha_txt = (fila.get("data_hora_gmt") or fila.get("data_pas") or "")[:10]
                    try:
                        f = date.fromisoformat(fecha_txt)
                    except ValueError:
                        continue
                    por_mes[f.month] += 1
                    por_dia[f"{f.month:02d}-{f.day:02d}"] += 1
                    por_pais[(fila.get("pais") or "").strip()] += 1
    total = sum(por_mes.values())
    if total == 0:
        # esto ya pasó una vez: el anuario usa 'data_pas' donde el fichero diario
        # usa 'data_hora_gmt', y el script publicó una climatología de ceros sin
        # quejarse. Un año sin un solo foco amazónico es un fallo, no un dato.
        raise RuntimeError(
            f"{anio}: 0 focos amazónicos — revisar si ha cambiado el esquema del fichero"
        )
    log(f"  {anio}: {total:,} focos amazónicos")
    return dict(por_mes), dict(por_dia), dict(por_pais)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", type=int, default=2003)
    ap.add_argument("--hasta", type=int, default=date.today().year - 1)
    args = ap.parse_args()

    anios = list(range(args.desde, args.hasta + 1))
    acum_mes: dict[int, list[int]] = defaultdict(list)
    acum_dia: dict[str, list[int]] = defaultdict(list)
    acum_pais: dict[str, list[int]] = defaultdict(list)
    fallidos = []

    for anio in anios:
        try:
            mes, dia, pais = procesar_anio(anio)
        except Exception as exc:  # noqa: BLE001
            log(f"AVISO: {anio} falló ({exc})")
            fallidos.append(anio)
            continue
        for m in range(1, 13):
            acum_mes[m].append(mes.get(m, 0))
        for k, v in dia.items():
            acum_dia[k].append(v)
        for k, v in pais.items():
            acum_pais[k].append(v)

    validos = len(anios) - len(fallidos)
    if validos < 5:
        raise RuntimeError(f"solo {validos} años válidos: no merece la pena publicar la media")

    dias_mes = {1: 31, 2: 28.25, 3: 31, 4: 30, 5: 31, 6: 30,
                7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}

    salida = {
        "generada": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "periodo": f"{args.desde}-{args.hasta}",
        "anios_validos": validos,
        "anios_fallidos": fallidos,
        "satelite_referencia": SATELITE_REFERENCIA,
        "definicion": "misma clasificación de Amazonía que obtener_amazonia_fuego.py",
        "meses": {
            str(m): {
                "media": round(sum(v) / len(v), 1),
                "minimo": min(v),
                "maximo": max(v),
                "media_diaria": round(sum(v) / len(v) / dias_mes[m], 1),
            }
            for m, v in sorted(acum_mes.items()) if v
        },
        "por_dia_del_anio": {
            k: round(sum(v) / validos, 2) for k, v in sorted(acum_dia.items())
        },
        "media_anual_por_pais": {
            k: round(sum(v) / validos, 1)
            for k, v in sorted(acum_pais.items(), key=lambda x: -sum(x[1]))
        },
    }

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(salida, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"escrito {SALIDA} con {validos} años")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        log(f"FALLO: {exc}")
        sys.exit(1)
