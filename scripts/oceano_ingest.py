#!/usr/bin/env python3
"""
OCÉANO · Paso 1 de 3
Descarga la categoría de ola de calor marina del día desde NOAA Coral Reef Watch
(Marine Heatwave Watch 5 km) vía ERDDAP y, si es posible, la anomalía SST.

Salidas:
  docs/oceano.json     -> global + cuencas (las rachas las añade oceano_streaks.py)
  _grid_oceano.npz     -> rejilla intermedia para oceano_render.py (NO se commitea)

Las rutas se calculan respecto a la raíz del repo, así que funciona ejecutando
`python scripts/oceano_ingest.py` desde la raíz (como en GitHub Actions).

Requiere: xarray, netCDF4, numpy, requests
"""
import io, os, sys, json, time
import numpy as np
import requests
import xarray as xr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from oceano_basins import BASINS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
GRID = os.path.join(ROOT, "_grid_oceano.npz")

ERDDAP = "https://pae-paha.pacioos.hawaii.edu/erddap/griddap"
DATASET_MHW = "mhw_5km"          # heatwave_category (0..5)
DATASET_ANOM = "dhw_5km"         # sea_surface_temperature_anomaly (best-effort)
STRIDE = 10                      # 0,05° * 10 = 0,5°
TIMEOUT = 90
RETRIES = 3

def fetch_nc(dataset, var, stride=STRIDE):
    url = f"{ERDDAP}/{dataset}.nc?{var}[(last)][0:{stride}:last][0:{stride}:last]"
    last = None
    for i in range(1, RETRIES + 1):
        try:
            r = requests.get(url, timeout=TIMEOUT); r.raise_for_status()
            return xr.open_dataset(io.BytesIO(r.content))[var].squeeze()
        except Exception as e:                       # noqa
            last = e; print(f"  intento {i}/{RETRIES}: {e}", file=sys.stderr); time.sleep(5 * i)
    raise RuntimeError(f"No se pudo descargar {dataset}:{var} -> {last}")

def lon180(x): return ((x + 180) % 360) - 180

def bmask(LAT, LON, lo0, lo1, la0, la1):
    span = (lo1 - lo0) % 360 or 360
    return (((LON - lo0) % 360) <= span) & (LAT >= la0) & (LAT <= la1)

def main():
    os.makedirs(DOCS, exist_ok=True)
    print("Descargando categoría de ola de calor marina (NOAA CRW)…")
    cat_da = fetch_nc(DATASET_MHW, "heatwave_category")
    lats = cat_da["latitude"].values.astype(float)
    lons = lon180(cat_da["longitude"].values.astype(float))
    cat = np.nan_to_num(cat_da.values, nan=-1).astype(float)

    anom = None
    try:
        anom = fetch_nc(DATASET_ANOM, "sea_surface_temperature_anomaly").values.astype(float)
    except Exception as e:                            # noqa
        print(f"  (anomalía no disponible: {e})", file=sys.stderr)

    LON, LAT = np.meshgrid(lons, lats)
    ocean = cat >= 0
    pct = round(100 * ((cat >= 1) & ocean).sum() / max(ocean.sum(), 1), 1)
    anom_med = round(float(np.nanmean(anom[ocean])), 2) if anom is not None else None

    cuencas = []
    for bid, (name, lo0, lo1, la0, la1) in BASINS.items():
        m = bmask(LAT, LON, lo0, lo1, la0, la1) & ocean
        if m.sum() == 0:
            continue
        categoria = int(np.clip(round(float(np.percentile(cat[m], 80))), 0, 5))
        a = round(float(np.nanpercentile(anom[m], 80)), 1) if anom is not None else None
        cuencas.append({"id": bid, "nombre": name, "bbox": [lo0, lo1, la0, la1],
                        "categoria": categoria, "anomalia": a,
                        "pct_cuenca": round(100 * (cat[m] >= 1).sum() / m.sum(), 1)})

    fecha = str(np.datetime_as_string(cat_da["time"].values, unit="D"))
    out = {"fecha": fecha,
           "fuente": "NOAA Coral Reef Watch · Marine Heatwave Watch 5km (ERDDAP)",
           "global": {"pct_en_mhw": pct, "anomalia_media": anom_med,
                      "racha_dias": None, "record_racha": None},
           "cuencas": sorted(cuencas, key=lambda x: -x["categoria"]),
           "capa_png": "oceano_hoy.png"}
    with open(os.path.join(DOCS, "oceano.json"), "w", encoding="utf8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    np.savez_compressed(GRID, cat=cat,
                        anom=(anom if anom is not None else np.zeros_like(cat)),
                        lats=lats, lons=lons)
    print(f"OK  fecha={fecha}  pct_global={pct}%  cuencas={len(cuencas)}")

if __name__ == "__main__":
    main()
