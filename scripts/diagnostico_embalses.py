import requests
import json

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "es-ES,es;q=0.9",
    "Referer": "https://www.miteco.gob.es/",
}

ENDPOINTS = [
    # MITECO API directa
    "https://www.miteco.gob.es/api/embalses",
    "https://www.miteco.gob.es/api/embalses/semanas",
    "https://www.miteco.gob.es/api/embalses/ultima-semana",
    "https://www.miteco.gob.es/api/hidrologia/embalses",
    "https://www.miteco.gob.es/api/v1/embalses",
    "https://www.miteco.gob.es/estadisticas/embalses/api",
    "https://www.miteco.gob.es/estadisticas/embalses/GetSemanas",
    "https://www.miteco.gob.es/estadisticas/embalses/GetDatos",
    # CHS Segura
    "https://www.chsegura.es/saih/datos/embalses.json",
    "https://www.chsegura.es/saih/api/embalses",
    "https://chs1.hduce.es/saih_chsr/api/embalses",
    "https://chs1.hduce.es/saih_chsr/datos/embalses",
    # MITECO descarga directa
    "https://www.miteco.gob.es/content/dam/miterd/docs/hidrologia/semanas/embalses.json",
    "https://www.miteco.gob.es/content/dam/miterd/docs/hidrologia/embalses.csv",
    # datos.gob.es
    "https://datos.gob.es/apidata/catalog/dataset/embalses",
    "https://datos.gob.es/api/action/package_search?q=embalses+segura",
    # SIH MITECO
    "https://sih.mapa.gob.es/api/embalses",
    "https://sih.mapa.gob.es/sih/v1/embalses",
    # CEDEX
    "https://www.cedex.es/api/embalses",
    # SAIH nacional
    "https://www.saih.es/api/embalses",
]

print("Probando endpoints...\n")
for url in ENDPOINTS:
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        preview = r.text[:120].replace('\n', ' ').strip()
        print(f"[{r.status_code}] {url}")
        if r.status_code == 200:
            print(f"        → {preview}")
    except Exception as e:
        err = str(e)[:80]
        print(f"[ERR]  {url}")
        print(f"        → {err}")
    print()
