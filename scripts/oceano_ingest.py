#!/usr/bin/env python3
"""OCÉANO · Paso 1 de 3 — descarga datos de ola de calor marina (NOAA)."""
import io, os, sys, json, time, datetime, socket
import numpy as np
import requests
import xarray as xr

# Forzar IPv4 (evita cuelgues de conexión en GitHub Actions)
_gai = socket.getaddrinfo
def _ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
    return _gai(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = _ipv4_only

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from oceano_basins import BASINS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
GRID = os.path.join(ROOT, "_grid_oceano.npz")

STRIDE = 10
CONNECT_T, READ_T, RETRIES = 25, 180, 3

SOURCES = [
    ("NOAA CoastWatch", "https://coastwatch.pfeg.noaa.gov/erddap/griddap",
     "NOAA_DHW", "CRW_SSTANOMALY", "anom"),
    ("PacIOOS", "https://pae-paha.pacioos.hawaii.edu/erddap/griddap",
     "mhw_5km", "heatwave_category", "cat"),
]

def get_bytes(url):
    last = None
    for i in range(1, RETRIES + 1):
        try:
            r = requests.get(url, timeout=(CONNECT_T, READ_T)); r.raise_for_status()
            return r.content
        except Exception as e:
            last = e; print(f"      intento {i}/{RETRIES}: {e}", file=sys.stderr); time.sleep(5 * i)
    raise RuntimeError(last)

def open_da(content, var):
    for eng in ("scipy", "netcdf4", "h5netcdf"):
        try:
            return xr.open_dataset(io.BytesIO(content), engine=eng)[var].squeeze()
        except Exception:
            pass
    return xr.open_dataset(io.BytesIO(content))[var].squeeze()

def grid_of(da):
    return (np.array(da.values, dtype=float),
            da["latitude"].values.astype(float),
            da["longitude"].values.astype(float))

def fecha_of(da):
    try:
        return str(np.datetime_as_string(da["time"].values, unit="D"))
    except Exception:
        return datetime.date.today().isoformat()

def cat_from_anom(a):
    ocean = ~np.isnan(a)
    cat = np.full(a.shape, -1.0); cat[ocean] = 0
    cat[a >= 1] = 1; cat[a >= 2] = 2; cat[a >= 3] = 3; cat[a >= 4] = 4
    return cat, np.where(ocean, a, np.nan)

def fetch(name, base, ds, var, kind):
    url = f"{base}/{ds}.nc?{var}[(last)][0:{STRIDE}:last][0:{STRIDE}:last]"
    print(f"  Probando {name}: {base}")
    da = open_da(get_bytes(url), var)
    vals, lats, lons = grid_of(da)
    if kind == "anom":
        cat, anom = cat_from_anom(vals)
    else:
        cat = np.nan_to_num(vals, nan=-1.0); anom = None
    print(f"  OK {name} respondio")
    return cat, lats, lons, anom, fecha_of(da)

def lon180(x): return ((x + 180) % 360) - 180
def to_180(grid, lons):
    l = lon180(lons); order = np.argsort(l)
    return grid[:, order], l[order]
def bmask(LAT, LON, lo0, lo1, la0, la1):
    span = (lo1 - lo0) % 360 or 360
    return (((LON - lo0) % 360) <= span) & (LAT >= la0) & (LAT <= la1)

def main():
    os.makedirs(DOCS, exist_ok=True)
    print("Descargando ola de calor marina (NOAA)...")
    cat = lats = lons = anom = fecha = None
    for name, base, ds, var, kind in SOURCES:
        try:
            cat, lats, lons, anom, fecha = fetch(name, base, ds, var, kind)
            break
        except Exception as e:
            print(f"  fuente {name} fallo: {e}", file=sys.stderr)
    if cat is None:
        print("OMITIDO: ninguna fuente respondio hoy. Se conserva el dato anterior.", file=sys.stderr)
        sys.exit(0)

    cat, lons = to_180(cat, lons)
    if anom is not None:
        anom, _ = to_180(anom, lons)

    LON, LAT = np.meshgrid(lons, lats)
    ocean = cat >= 0
    pct = round(100 * ((cat >= 1) & ocean).sum() / max(ocean.sum(), 1), 1)
    anom_med = round(float(np.nanmean(anom[ocean])), 2) if anom is not None else None

    cuencas = []
    for bid, (nm, lo0, lo1, la0, la1) in BASINS.items():
        m = bmask(LAT, LON, lo0, lo1, la0, la1) & ocean
        if m.sum() == 0:
            continue
        categoria = int(np.clip(round(float(np.percentile(cat[m], 80))), 0, 5))
        av = round(float(np.nanpercentile(anom[m], 80)), 1) if anom is not None else None
        cuencas.append({"id": bid, "nombre": nm, "bbox": [lo0, lo1, la0, la1],
                        "categoria": categoria, "anomalia": av,
                        "pct_cuenca": round(100 * (cat[m] >= 1).sum() / m.sum(), 1)})

    out = {"fecha": fecha, "fuente": "NOAA Coral Reef Watch (ERDDAP)",
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
