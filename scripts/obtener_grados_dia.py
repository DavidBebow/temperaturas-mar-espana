#!/usr/bin/env python3
"""
Grados-día de calefacción (HDD) y refrigeración (CDD) para las 52 capitales de
provincia, guardados en docs/grados-dia.json.

  T media del día  =  (máxima + mínima) / 2
  HDD base 18 °C   ->  suma anual de max(0, 18 - T_media)
  CDD bases 21/24  ->  suma anual de max(0, T_media - base)

Revisión del 18-10-2026 (auditoría de veracidad):
  · Este archivo no se había generado nunca (el workflow solo corría el 15 de
    enero y la API de Open-Meteo no da cupo para 65 años x 52 capitales en una
    pasada). El gráfico pedía los datos en directo desde el navegador, sin
    fijar el modelo: Open-Meteo sirve entonces «best_match», que pasa de ERA5
    al IFS del ECMWF hacia 2017, y la comparación «primera frente a última
    década» mezclaba dos productos.
  · Ahora se calcula con el archivo diario ERA5 de las capitales que ya guarda
    el propio repo (archivo/era5/<cod>/, generado por archivo_capitales.py con
    el modelo ERA5 fijado). No hace ninguna llamada a ninguna API.

Uso (desde la raíz del repo):  python scripts/obtener_grados_dia.py
"""

import csv
import gzip
import io
import json
import sys
from datetime import date
from pathlib import Path

START_YEAR = 1960
HDD_BASE = 18
CDD_BASES = [21, 24]
MIN_DIAS = 350
RAIZ = Path(__file__).resolve().parent.parent
ARCHIVO = RAIZ / "archivo" / "era5"
OUT = RAIZ / "docs" / "grados-dia.json"

# (nombre del selector, código INE de la provincia) — la capital es la de archivo_capitales.py
PROVINCIAS = [
    ("A Coruña", "15"), ("Álava", "01"), ("Albacete", "02"), ("Alicante", "03"), ("Almería", "04"),
    ("Asturias", "33"), ("Ávila", "05"), ("Badajoz", "06"), ("Barcelona", "08"), ("Bizkaia", "48"),
    ("Burgos", "09"), ("Cáceres", "10"), ("Cádiz", "11"), ("Cantabria", "39"), ("Castellón", "12"),
    ("Ciudad Real", "13"), ("Córdoba", "14"), ("Cuenca", "16"), ("Gipuzkoa", "20"), ("Girona", "17"),
    ("Granada", "18"), ("Guadalajara", "19"), ("Huelva", "21"), ("Huesca", "22"), ("Illes Balears", "07"),
    ("Jaén", "23"), ("La Rioja", "26"), ("Las Palmas", "35"), ("León", "24"), ("Lleida", "25"),
    ("Lugo", "27"), ("Madrid", "28"), ("Málaga", "29"), ("Murcia", "30"), ("Navarra", "31"),
    ("Ourense", "32"), ("Palencia", "34"), ("Pontevedra", "36"), ("Salamanca", "37"),
    ("S. C. de Tenerife", "38"), ("Segovia", "40"), ("Sevilla", "41"), ("Soria", "42"),
    ("Tarragona", "43"), ("Teruel", "44"), ("Toledo", "45"), ("Valencia", "46"), ("Valladolid", "47"),
    ("Zamora", "49"), ("Zaragoza", "50"), ("Ceuta", "51"), ("Melilla", "52"),
]


def leer_serie(cod, ultimo_anio):
    """{fecha: (tmax, tmin)} del archivo ERA5 de la capital, hasta ultimo_anio."""
    serie = {}
    d = ARCHIVO / cod
    fuentes = sorted(d.glob("hasta_*_era5.csv.gz")) + sorted(d.glob("[0-9][0-9][0-9][0-9].csv"))
    for f in fuentes:
        if f.suffix == ".gz":
            txt = gzip.open(f, "rt", encoding="utf-8").read()
        else:
            if int(f.stem) > ultimo_anio:
                continue
            txt = f.read_text(encoding="utf-8")
        for r in csv.DictReader(io.StringIO(txt)):
            try:
                serie[r["fecha"]] = (float(r["tmax"]), float(r["tmin"]))
            except (KeyError, TypeError, ValueError):
                pass
    return serie


def grados_dia(serie):
    por_anio = {}
    for f, (tx, tn) in serie.items():
        y = int(f[:4])
        if y < START_YEAR:
            continue
        tm = (tx + tn) / 2
        reg = por_anio.setdefault(y, {"hdd": 0.0, "cdd": {b: 0.0 for b in CDD_BASES}, "dias": 0})
        reg["hdd"] += max(0.0, HDD_BASE - tm)
        for b in CDD_BASES:
            reg["cdd"][b] += max(0.0, tm - b)
        reg["dias"] += 1
    years, hdd, cdd = [], [], {b: [] for b in CDD_BASES}
    for y in sorted(por_anio):
        if por_anio[y]["dias"] < MIN_DIAS:
            continue
        years.append(y)
        hdd.append(round(por_anio[y]["hdd"]))
        for b in CDD_BASES:
            cdd[b].append(round(por_anio[y]["cdd"][b]))
    return years, hdd, cdd


def main():
    ultimo = date.today().year - 1          # último año completo
    salida = {
        "generado": date.today().isoformat(),
        "base_hdd": HDD_BASE,
        "bases_cdd": CDD_BASES,
        "fin": f"{ultimo}-12-31",
        "fuente": "ERA5 (Copernicus/ECMWF), modelo fijo, vía Open-Meteo Archive; archivo diario de las capitales",
        "metodo": "T media = (máxima + mínima) / 2 · HDD base 18 °C · CDD bases 21 y 24 °C · años con 350 días o más",
        "provincias": {},
    }
    faltan = []
    for nombre, cod in PROVINCIAS:
        serie = leer_serie(cod, ultimo)
        years, hdd, cdd = grados_dia(serie)
        if not years:
            faltan.append(nombre)
            continue
        salida["provincias"][nombre] = {"cod": cod, "years": years, "hdd": hdd,
                                        **{f"cdd{b}": cdd[b] for b in CDD_BASES}}
        print(f"{nombre:<18} {years[0]}-{years[-1]} · HDD {hdd[-1]} · CDD21 {cdd[21][-1]}")
    if len(salida["provincias"]) < 40:
        print(f"ERROR: solo {len(salida['provincias'])} provincias; no se escribe nada. Faltan: {faltan}")
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(salida, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"\nGuardado {OUT} · {len(salida['provincias'])} provincias · hasta {ultimo}" +
          (f" · sin serie: {', '.join(faltan)}" if faltan else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
