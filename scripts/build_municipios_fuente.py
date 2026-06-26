#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CONSTRUCTOR de scripts/municipios_fuente.csv para "Tu municipio en 2050".

Genera el listado COMPLETO de los ~8.131 municipios de España (nombre + provincia
+ código INE + latitud/longitud) uniendo dos datasets abiertos y oficiales:

  1) Lista autoritativa de municipios (INE, actualizada cada año):
     codeforspain/ds-organizacion-administrativa  ->  data/municipios.csv
     Campos: municipio_id, provincia_id, cmun, dc, nombre
     (nombres oficiales vigentes; es la fuente de la verdad para qué municipios existen)

  2) Coordenadas por municipio (centroide), indexadas por código INE:
     PopulateTools/ine-places  ->  lib/ine/places/data/places.csv
     Campos: id, province_id, name, slug, province_name, region_name, lon, lat

Se unen por código INE (5 dígitos). El nombre y la provincia salen de (1) -vigente-,
las coordenadas de (2). Los pocos municipios sin coordenadas (creados/renombrados
después de 2015) se dejan sin lat/lon: el generador los geocodificará por nombre.

Salida: CSV con cabeceras que el generador reconoce:
    nombre;provincia;codigoine;latitud;longitud

Solo librería estándar. Fuerza IPv4 (como el generador) y prueba varios mirrors.
Uso:  python build_municipios_fuente.py        # escribe scripts/municipios_fuente.csv
Variables de entorno opcionales:  OUT (ruta de salida).
"""
import csv, io, os, sys, socket, urllib.request

# --- Forzar IPv4 (algunos runners fallan con IPv6 hacia estos hosts) ----------
_gai = socket.getaddrinfo
socket.getaddrinfo = lambda h, p, f=0, t=0, pr=0, fl=0: _gai(h, p, socket.AF_INET, t, pr, fl)

OUT = os.environ.get("OUT", "scripts/municipios_fuente.csv")

# Fuentes (con mirrors de respaldo vía jsDelivr por si el raw de GitHub falla)
MUNI_URLS = [
    "https://raw.githubusercontent.com/codeforspain/ds-organizacion-administrativa/master/data/municipios.csv",
    "https://cdn.jsdelivr.net/gh/codeforspain/ds-organizacion-administrativa@master/data/municipios.csv",
]
COORD_URLS = [
    "https://raw.githubusercontent.com/PopulateTools/ine-places/master/lib/ine/places/data/places.csv",
    "https://cdn.jsdelivr.net/gh/PopulateTools/ine-places@master/lib/ine/places/data/places.csv",
]

# Nombre de provincia "amigable" por código INE de provincia (para el buscador).
PROV = {
    "01": "Álava", "02": "Albacete", "03": "Alicante", "04": "Almería",
    "05": "Ávila", "06": "Badajoz", "07": "Illes Balears", "08": "Barcelona",
    "09": "Burgos", "10": "Cáceres", "11": "Cádiz", "12": "Castellón",
    "13": "Ciudad Real", "14": "Córdoba", "15": "A Coruña", "16": "Cuenca",
    "17": "Girona", "18": "Granada", "19": "Guadalajara", "20": "Gipuzkoa",
    "21": "Huelva", "22": "Huesca", "23": "Jaén", "24": "León",
    "25": "Lleida", "26": "La Rioja", "27": "Lugo", "28": "Madrid",
    "29": "Málaga", "30": "Murcia", "31": "Navarra", "32": "Ourense",
    "33": "Asturias", "34": "Palencia", "35": "Las Palmas", "36": "Pontevedra",
    "37": "Salamanca", "38": "Santa Cruz de Tenerife", "39": "Cantabria",
    "40": "Segovia", "41": "Sevilla", "42": "Soria", "43": "Tarragona",
    "44": "Teruel", "45": "Toledo", "46": "Valencia", "47": "Valladolid",
    "48": "Bizkaia", "49": "Zamora", "50": "Zaragoza", "51": "Ceuta",
    "52": "Melilla",
}


def fetch(urls):
    last = None
    for u in urls:
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "clima-municipios/1.0"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read().decode("utf-8-sig", "replace")
        except Exception as e:
            last = e
            print(f"  aviso: fallo al descargar {u}: {e}", file=sys.stderr)
    raise SystemExit(f"No pude descargar ninguna fuente. Último error: {last}")


def parse_municipios(text):
    """codeforspain municipios.csv -> dict {ine5: {'n':nombre, 'prov':codprov2}}"""
    r = csv.DictReader(io.StringIO(text))
    out = {}
    for row in r:
        ine = (row.get("municipio_id") or "").strip()
        nombre = (row.get("nombre") or "").strip()
        prov = (row.get("provincia_id") or "").strip()
        if not ine or not nombre:
            continue
        ine = ine.zfill(5)
        prov = prov.zfill(2)
        out[ine] = {"n": nombre, "prov": prov}
    return out


def parse_coords(text):
    """ine-places places.csv -> dict {ine5: (lat, lon)}"""
    r = csv.DictReader(io.StringIO(text))
    out = {}
    for row in r:
        ine = (row.get("id") or "").strip()
        lat = (row.get("lat") or "").strip()
        lon = (row.get("lon") or "").strip()
        if not ine:
            continue
        ine = ine.zfill(5)
        try:
            out[ine] = (round(float(lat), 5), round(float(lon), 5))
        except (TypeError, ValueError):
            continue
    return out


def main():
    print("Descargando lista oficial de municipios (INE / codeforspain)…")
    munis = parse_municipios(fetch(MUNI_URLS))
    print(f"  municipios: {len(munis)}")

    print("Descargando coordenadas por municipio (ine-places)…")
    coords = parse_coords(fetch(COORD_URLS))
    print(f"  coordenadas disponibles: {len(coords)}")

    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    con = sin = 0
    with open(OUT, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["nombre", "provincia", "codigoine", "latitud", "longitud"])
        for ine in sorted(munis):
            m = munis[ine]
            prov_name = PROV.get(m["prov"], "")
            ll = coords.get(ine)
            if ll:
                w.writerow([m["n"], prov_name, ine, ll[0], ll[1]]); con += 1
            else:
                w.writerow([m["n"], prov_name, ine, "", ""]); sin += 1

    print(f"OK -> {OUT}")
    print(f"   {con + sin} municipios escritos  ·  {con} con coordenadas  ·  {sin} sin (se geocodificarán por nombre)")


if __name__ == "__main__":
    main()
