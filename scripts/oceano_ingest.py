#!/usr/bin/env python3
"""
OCÉANO · Paso 1 de 3
Descarga la categoría de ola de calor marina del día desde NOAA Coral Reef Watch
(Marine Heatwave Watch 5 km) vía ERDDAP y, si es posible, la anomalía SST.

Pide los datos en formato JSON de ERDDAP y los parsea con numpy: así NO hace falta
xarray/netCDF4/scipy (que daban problemas de backend en el runner).

Salidas:
  docs/oceano.json     -> global + cuencas (las rachas las añade oceano_streaks.py)
  _grid_oceano.npz     -> rejilla intermedia para oceano_render.py (NO se commitea)

Requiere: numpy, requests
"""
import os, sys, json, time
import numpy as np
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from oceano_basins import BASINS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
GRID = os.path.join(ROOT, "_grid_oceano.npz")

ERDDAP = "https://pae-paha.pacioos.hawaii.edu/erddap/griddap"
DATASET_MHW = "mhw_5km"          # heatwave_category (0..5)
DATASET_ANOM = "dhw_5km"         # sea_surface_temperature_anomaly (best-effort)
STRIDE = 10                      # 0,05° * 10 = 0,5°
TIMEOUT = 120
RETRIES = 3

def fetch_grid(dataset, var, stride=STRIDE):
    """Pide var[(last)] con stride y devuelve (grid[lat,lon], lats_asc, lons)."""
    url = f"{ERDDAP}/{dataset}.json?{var}[(last)][0:{stride}:last][0:{stride}:last]"
    last = None
    for i in range(1, RETRIES + 1):
        try:
            r = requests.get(url, timeout=TIMEOUT); r.raise_for_status()
            tab = r.json()["table"]
            cols = tab["columnNames"]; rows = tab["rows"]
            ai, oi, vi = cols.index("latitude"), cols.index("longitude"), cols.index(var)
            arr = np.array(rows, dtype=object)
            lat = arr[:, ai].astype(float)
            lon = arr[:, oi].astype(float)
            val = np.array([np.nan if v is None else float(v) for v in arr[:, vi]])
            lats = np.unique(lat); lons = np.unique(lon)
            grid = np.full((lats.size, lons.size), np.nan)
            grid[np.searchsorted(lats, lat), np.searchsorted(lons, lon)] = val
            return grid, lats, lons
        except Exception as e:                       # noqa
            last = e; print(f"  intento {i}/{RETRIES}: {e}", file=sys.stderr); time.sleep(5 * i)
    raise RuntimeError(f"No se pudo descargar {dataset}:{var} -> {last}")

def lon180(x): return ((x + 180) % 360) - 180

def to_180(grid, lons):
    """Reordena columnas a longitudes -180..180 ascendentes."""
    l = lon180(lons); order = np.argsort(l)
    return grid[:, order], l[order]

def bmask(LAT, LON, lo0, lo1, la0, la1):
    span = (lo1 - lo0) % 360 or 360
    return (((LON - lo0) % 360) <= span) & (LAT >= la0) & (LAT <= la1)

def main():
    os.makedirs(DOCS, exist_ok=True)
    print("Descargando categoría de ola de calor marina (NOAA CRW)…")
    cat, lats, lons = fetch_grid(DATASET_MHW, "heatwave_category")
    cat, lons = to_180(cat, lons)
    cat = np.nan_to_num(cat, nan=-1.0)               # -1 = tierra/sin dato

    anom = None
    try:
        a, alat, alon = fetch_grid(DATASET_ANOM, "sea_surface_temperature_anomaly")
        a, _ = to_180(a, alon)
        if a.shape == cat.shape:
            anom = a
        else:
            print("  (anomalía con malla distinta, se omite)", file=sys.stderr)
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
        av = round(float(np.nanpercentile(anom[m], 80)), 1) if anom is not None else None
        cuencas.append({"id": bid, "nombre": name, "bbox": [lo0, lo1, la0, la1],
                        "categoria": categoria, "anomalia": av,
                        "pct_cuenca": round(100 * (cat[m] >= 1).sum() / m.sum(), 1)})

    import datetime
    fecha = datetime.date.today().isoformat()        # fecha del dato más reciente publicado
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
