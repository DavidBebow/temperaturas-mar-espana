#!/usr/bin/env python3
"""
DESERTIFICACIÓN · genera docs/desertificacion.json con datos del World Bank CCKP.
- A prueba de fallos: si CCKP no responde, conserva el JSON anterior (no rompe la web).
- Fuerza IPv4 y reintenta.
Requiere: requests
"""
import os, sys, json, time, socket
import requests

_gai = socket.getaddrinfo
socket.getaddrinfo = lambda h,p,f=0,t=0,pr=0,fl=0: _gai(h,p,socket.AF_INET,t,pr,fl)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
OUT  = os.path.join(DOCS, "desertificacion.json")

# ---- CONFIG (si la 1ª ejecución falla, ajusta estas líneas según el log) -----
BASE = "https://cckpapi.worldbank.org/cckp/v1/"
VAR  = "spei12"                  # SPEI 12 meses (sequía); más negativo = más seco
# (step_id, etiqueta, tipo, ventana, escenario|None)
PERIODS = [
    ("1980s","1980s","obs","1961-1990", None),
    ("1990s","1990s","obs","1971-2000", None),
    ("2000s","2000s","obs","1981-2010", None),
    ("2020s","2020s","obs","1991-2020", None),
    ("2035","2035","proj","2020-2039","ssp370"),
    ("2050","2050","proj","2040-2059","ssp370"),
]
# cifras globales reales (UNCCD 2024) por step
GLOBAL = {"1980s":37.5,"1990s":38.3,"2000s":39.1,"2020s":40.6,"2035":42.5,"2050":44.5}
TIMEOUT, RETRIES = 40, 3

# ISO3 -> nombre EXACTO del país en world-atlas (el que usa el mapa)
ISO = {
 "DZA":"Algeria","NER":"Niger","TCD":"Chad","MLI":"Mali","MRT":"Mauritania","SDN":"Sudan",
 "SSD":"S. Sudan","EGY":"Egypt","LBY":"Libya","MAR":"Morocco","TUN":"Tunisia","ETH":"Ethiopia",
 "SOM":"Somalia","KEN":"Kenya","TZA":"Tanzania","NAM":"Namibia","BWA":"Botswana","ZAF":"South Africa",
 "AGO":"Angola","NGA":"Nigeria","SAU":"Saudi Arabia","YEM":"Yemen","OMN":"Oman","IRN":"Iran",
 "IRQ":"Iraq","SYR":"Syria","AFG":"Afghanistan","PAK":"Pakistan","IND":"India","CHN":"China",
 "MNG":"Mongolia","KAZ":"Kazakhstan","TKM":"Turkmenistan","UZB":"Uzbekistan","AUS":"Australia",
 "USA":"United States of America","MEX":"Mexico","ARG":"Argentina","CHL":"Chile","ESP":"Spain",
 "PRT":"Portugal","ITA":"Italy","GRC":"Greece","TUR":"Turkey","RUS":"Russia","BRA":"Brazil",
 "MDG":"Madagascar","ZWE":"Zimbabwe","MOZ":"Mozambique","SEN":"Senegal","BFA":"Burkina Faso",
 "ERI":"Eritrea","JOR":"Jordan","ISR":"Israel"
}

def url(period, scenario):
    if scenario is None:
        return (f"{BASE}cru-x0.5_climatology_{VAR}_climatology_annual_"
                f"{period}_mean_historical_mean/all?_format=json")
    return (f"{BASE}cmip6-x0.25_climatology_{VAR}_climatology_annual_"
            f"{period}_median_{scenario}_ensemble/all?_format=json")

def fetch(period, scenario):
    u = url(period, scenario)
    for i in range(1, RETRIES+1):
        try:
            r = requests.get(u, timeout=TIMEOUT); r.raise_for_status()
            d = r.json().get("data", {})
            out = {}
            for iso, val in d.items():
                if isinstance(val, dict):
                    val = next(iter(val.values()), None)
                if val is not None:
                    out[iso.upper()] = float(val)
            if out: return out
            raise ValueError("respuesta vacía")
        except Exception as e:
            print(f"   {period}/{scenario or 'hist'} intento {i}/{RETRIES}: {e}", file=sys.stderr)
            time.sleep(4*i)
    return None

def risk(spei):                 # SPEI -> riesgo 0-100 (más seco = más alto)
    return max(0, min(100, round(50 - spei*20)))

def keep_previous(msg):
    print("OMITIDO:", msg, "— se conserva el JSON anterior.", file=sys.stderr)
    sys.exit(0)

def main():
    os.makedirs(DOCS, exist_ok=True)
    print("Descargando desertificación (World Bank CCKP)…")
    periodos, raw = [], {}
    for sid, label, tipo, period, scen in PERIODS:
        data = fetch(period, scen)
        if not data:
            print(f"  (sin datos para {sid}, se omite ese paso)", file=sys.stderr); continue
        raw[sid] = data
        p = {"id":sid,"label":label,"tipo":tipo}
        if scen: p["escenario"] = scen.upper()
        periodos.append(p)
        print(f"  OK {sid}: {len(data)} países")

    if len(periodos) < 2:
        keep_previous("CCKP no devolvió suficientes periodos")

    paises = {}
    for iso, name in ISO.items():
        serie = [risk(raw[p["id"]][iso]) if iso in raw[p["id"]] else None for p in periodos]
        if any(v is not None for v in serie):
            paises[name] = serie

    glob = [{"periodo":p["id"], "drylands_pct":GLOBAL.get(p["id"])} for p in periodos]
    out = {"fuente":"World Bank Climate Change Knowledge Portal (SPEI, escala de riesgo) · Global: UNCCD 2024",
           "indicador":"Riesgo de desertificación / aridez (0-100, a partir de SPEI)",
           "periodos":periodos, "global":glob, "paises":paises}
    json.dump(out, open(OUT,"w",encoding="utf8"), ensure_ascii=False, indent=1)
    print(f"OK  periodos={len(periodos)}  paises={len(paises)}")

if __name__ == "__main__":
    main()
