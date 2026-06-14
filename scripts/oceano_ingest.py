#!/usr/bin/env python3
"""
OCÉANO · Paso 1 de 3
Descarga la categoría de ola de calor marina del día desde NOAA Coral Reef Watch.
"""
import io, os, sys, json, time, datetime, socket
import numpy as np
import requests
import xarray as xr

# GitHub Actions a veces se cuelga al conectar por IPv6 con servidores académicos
# (PacIOOS, NOAA). Forzamos IPv4 para que la conexión sea rápida y fiable.
_gai = socket.getaddrinfo
def _ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
    return _gai(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = _ipv4_only

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from oceano_basins import BASINS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
GRID = os.path.join(ROOT, "_grid_oceano.npz")

PACIOOS    = "https://pae-paha.pacioos.hawaii.edu/erddap/griddap"
COASTWATCH = "https://coastwatch.pfeg.noaa.gov/erddap/griddap"
STRIDE = 10                       # 0,05° * 10 = 0,5°
CONNECT_T, READ_T, RETRIES = 20, 150, 3

def get_bytes(url):
    last = None
    for i in range(1, RETRIES + 1):
        try:
            r = requests.get(url, timeout=(CONNECT_T, READ_T)); r.raise_for_status()
            return r.content
        except Exception as e:                       # noqa
            last = e; print(f"    intento {i}/{RETRIES}: {e}", file=sys.stderr); time.sleep(5 * i)
    raise RuntimeError(last)

def open_da(content, var):
    for eng in ("scipy", "netcdf4", "h5netcdf"):
        try:
            return xr.open_dataset(io.BytesIO(content), engine=eng)[var].squeeze()
        except Exception:                            # noqa
            pass
    return xr.open_dataset(io.BytesIO(content))[var].squeeze()

def grid_of(da):
    lats = da["latitude"].values.astype(float)
    lons = da["longitude"].values.astype(float)
    return np.array(da.values, dtype=float), lats, lons

def fecha_of(da):
    try:
        return str(np.datetime_as_string(da["time"].values, unit="D"))
    except Exception:                                # noqa
        return datetime.date.today().isoformat()

def url(base, ds, var):
    return f"{base}/{ds}.nc?{var}[(last)][0:{STRIDE}:last][0:{STRIDE}:last]"

# ---- Fuente 1: PacIOOS (categoría oficial) ----------------------------------
def fetch_pacioos():
    print("  Fuente 1: PacIOOS · mhw_5km/heatwave_category")
    da = open_da(get_bytes(url(PACIOOS, "mhw_5km", "heatwave_category")), "heatwave_category")
    cat, lats, lons = grid_of(da)
    cat = np.nan_to_num(cat, nan=-1.0)
    anom = None
    try:
        ad = open_da(get_bytes(url(PACIOOS, "dhw_5km", "sea_surface_temperature_anomaly")),
                     "sea_surface_temperature_anomaly")
        ag, _, _ = grid_of(ad)
        if ag.shape == cat.shape:
            anom = ag
    except Exception as e:                            # noqa
        print(f"    (anomalía PacIOOS no disponible: {e})", file=sys.stderr)
    return cat, lats, lons, anom, fecha_of(da)

# ---- Fuente 2: NOAA CoastWatch (respaldo: categoría desde anomalía) ----------
def fetch_coastwatch():
    print("  Fuente 2 (respaldo): NOAA CoastWatch · NOAA_DHW/CRW_SSTANOMALY")
    da = open_da(get_bytes(url(COASTWATCH, "NOAA_DHW", "CRW_SSTANOMALY")), "CRW_SSTANOMALY")
    a, lats, lons = grid_of(da)
    ocean = ~np.isnan(a)
    cat = np.full(a.shape, -1.0); cat[ocean] = 0
    cat[a >= 1] = 1; cat[a >= 2] = 2; cat[a >= 3] = 3; cat[a >= 4] = 4
    anom = np.where(ocean, a, np.nan)
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
    print("Descargando categoría de ola de calor marina (NOAA CRW)…")
    cat = lats = lons = anom = fecha = None
    for src in (fetch_pacioos, fetch_coastwatch):
        try:
            cat, lats, lons, anom, fecha = src()
            break
        except Exception as e:                       # noqa
            print(f"  fuente falló: {e}", file=sys.stderr)
    if cat is None:
        print("OMITIDO: ninguna fuente respondió hoy. Se conserva el dato anterior.",
              file=sys.stderr)
        sys.exit(0)                                  # no rompe el workflow

    cat, lons2 = to_180(cat, lons)
    if anom is not None:
        anom, _ = to_180(anom, lons)
    lons = lons2

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

    out = {"fecha": fecha,
           "fuente": "NOAA Coral Reef Watch (ERDDAP)",
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
