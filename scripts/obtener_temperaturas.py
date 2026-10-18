"""
Temperatura del mar en 23 puntos del litoral español.

Revisión del 18-10-2026 (auditoría de veracidad). Antes:
  · el dato salía de Open-Meteo Marine (modelo) y en 9 de los 23 puntos la
    celda estaba en tierra: Málaga, Almería, Cartagena, Valencia, Tenerife,
    Fuerteventura, Lanzarote, Ceuta y Melilla salían sin dato;
  · la «media histórica del mes» era una tabla escrita a mano sin fuente, y
    con ella se calculaban la anomalía y las rachas;
  · el «mismo día del año anterior» se pedía a un servicio que no tiene
    temperatura del mar y casi siempre volvía vacío.
Ahora todo sale de un mismo producto oficial y documentado:

  NOAA OISST v2.1 (Optimum Interpolation SST, satélite + boyas + barcos,
  rejilla de 0,25°), servido por los ERDDAP de la NOAA:
    · dato reciente: versión preliminar (NRT, uno o dos días de retraso);
    · serie consolidada: versión definitiva (unas dos semanas de retraso);
    · normal 1991-2020 de cada día del año, calculada aquí con la serie
      definitiva completa (copia íntegra en upwell, sin huecos) y una
      ventana centrada de 15 días.

Cada punto usa la celda de océano más cercana a la costa que lo nombra (entre
2 y 22 km mar adentro, comprobado el 18-10-2026), y el JSON dice cuál es y a
qué distancia está. Es la temperatura de la superficie del mar en esa celda,
no la del agua en la playa.

Si la NOAA no responde para un punto, se conserva su último dato con su fecha.
Salidas: docs/datos.json, docs/historial_temperaturas.json y la normal en
docs/mar_climatologia.json (se calcula una vez y se reutiliza).
"""
import json
import math
import os
import time
import urllib.request
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Madrid")
CW = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/"
UPWELL = "https://upwell.pfeg.noaa.gov/erddap/griddap/oisst_rclone.csv"
NRT = "ncdcOisst21NrtAgg_LonPM180"
DEF = "ncdcOisst21Agg_LonPM180"
SALIDA = "docs/datos.json"
HISTORIAL = "docs/historial_temperaturas.json"
CLIMA = "docs/mar_climatologia.json"
NORMAL = (1991, 2020)
VENTANA = 7                     # ±7 días alrededor de cada día del año
METODO = "oisst_v21_normal_1991_2020"

# lat/lon: dónde se pinta el punto · celda: celda OISST de océano más cercana
PUNTOS = [
    {"id": "san_sebastian", "nombre": "San Sebastián", "zona": "Cantábrico",            "lat": 43.32, "lon": -1.98,  "celda": (43.375, -1.875)},
    {"id": "santander",     "nombre": "Santander",     "zona": "Cantábrico",            "lat": 43.46, "lon": -3.80,  "celda": (43.625, -3.875)},
    {"id": "gijon",         "nombre": "Gijón",         "zona": "Cantábrico",            "lat": 43.55, "lon": -5.66,  "celda": (43.625, -5.625)},
    {"id": "coruna",        "nombre": "A Coruña",      "zona": "Atlántico Norte",       "lat": 43.37, "lon": -8.40,  "celda": (43.375, -8.375)},
    {"id": "vigo",          "nombre": "Vigo",          "zona": "Atlántico Norte",       "lat": 42.24, "lon": -8.72,  "celda": (42.125, -8.875)},
    {"id": "huelva",        "nombre": "Huelva",        "zona": "Atlántico Sur",         "lat": 37.14, "lon": -6.83,  "celda": (37.125, -6.875)},
    {"id": "cadiz",         "nombre": "Cádiz",         "zona": "Atlántico Sur",         "lat": 36.52, "lon": -6.28,  "celda": (36.625, -6.375)},
    {"id": "malaga",        "nombre": "Málaga",        "zona": "Mediterráneo Sur",      "lat": 36.72, "lon": -4.41,  "celda": (36.625, -4.375)},
    {"id": "almeria",       "nombre": "Almería",       "zona": "Mediterráneo Sur",      "lat": 36.70, "lon": -2.55,  "celda": (36.625, -2.625)},
    {"id": "cartagena",     "nombre": "Cartagena",     "zona": "Mediterráneo (Murcia)", "lat": 37.50, "lon": -0.85,  "celda": (37.375, -0.875)},
    {"id": "valencia",      "nombre": "Valencia",      "zona": "Mediterráneo",          "lat": 39.47, "lon":  0.33,  "celda": (39.375,  0.375)},
    {"id": "barcelona",     "nombre": "Barcelona",     "zona": "Mediterráneo Norte",    "lat": 41.38, "lon":  2.18,  "celda": (41.375,  2.375)},
    {"id": "tarragona",     "nombre": "Tarragona",     "zona": "Mediterráneo Norte",    "lat": 41.12, "lon":  1.25,  "celda": (41.125,  1.375)},
    {"id": "costa_brava",   "nombre": "Costa Brava",   "zona": "Mediterráneo Norte",    "lat": 41.98, "lon":  3.21,  "celda": (41.875,  3.125)},
    {"id": "sitges",        "nombre": "Sitges",        "zona": "Mediterráneo Norte",    "lat": 41.23, "lon":  1.81,  "celda": (41.125,  1.875)},
    {"id": "palma",         "nombre": "Palma de Mallorca", "zona": "Baleares",          "lat": 39.57, "lon":  2.64,  "celda": (39.375,  2.625)},
    {"id": "ibiza",         "nombre": "Ibiza",         "zona": "Baleares",              "lat": 38.90, "lon":  1.43,  "celda": (38.875,  1.375)},
    {"id": "las_palmas",    "nombre": "Las Palmas",    "zona": "Canarias",              "lat": 28.10, "lon": -15.41, "celda": (28.125, -15.375)},
    {"id": "tenerife",      "nombre": "Tenerife",      "zona": "Canarias",              "lat": 28.46, "lon": -16.25, "celda": (28.375, -16.375)},
    {"id": "fuerteventura", "nombre": "Fuerteventura", "zona": "Canarias",              "lat": 28.66, "lon": -13.86, "celda": (28.625, -13.875)},
    {"id": "lanzarote",     "nombre": "Lanzarote",     "zona": "Canarias",              "lat": 29.04, "lon": -13.60, "celda": (29.125, -13.625)},
    {"id": "ceuta",         "nombre": "Ceuta",         "zona": "Estrecho",              "lat": 35.89, "lon": -5.31,  "celda": (35.875, -5.125)},
    {"id": "melilla",       "nombre": "Melilla",       "zona": "Mediterráneo Sur",      "lat": 35.29, "lon": -2.94,  "celda": (35.375, -2.875)},
]


def log(*a):
    print(*a, flush=True)


def km(a, b, c, d):
    r = math.radians
    h = math.sin(r(c - a) / 2) ** 2 + math.cos(r(a)) * math.cos(r(c)) * math.sin(r(d - b) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def http(url, intentos=5, timeout=180):
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "calentamientoglobal.es/temperatura-mar"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            if i == intentos - 1:
                raise
            log(f"   reintento {i + 1}: {e}")
            time.sleep(6 * (i + 1))


def parse_csv(txt):
    """CSV de ERDDAP (cabecera + unidades) -> {fecha: sst}"""
    out = {}
    for ln in txt.splitlines()[2:]:
        p = ln.split(",")
        if len(p) < 5 or p[4] in ("NaN", ""):
            continue
        try:
            out[p[0][:10]] = float(p[4])
        except ValueError:
            pass
    return out


def serie_cw(ds, celda, ini, fin):
    la, lo = celda
    url = (f"{CW}{ds}.csv?sst[({ini}T12:00:00Z):1:({fin}T12:00:00Z)][(0.0)]"
           f"[({la:.3f}):1:({la:.3f})][({lo:.3f}):1:({lo:.3f})]")
    return parse_csv(http(url))


def ultimo(ds):
    """Último día del conjunto (misma consulta que usa dana_generar.py)."""
    txt = http(f"{CW}{ds}.csv?sst[(last)][(0.0)][(39.125)][(2.125)]")
    return date.fromisoformat(txt.splitlines()[2][:10])


def md(f):
    """Clave día del año; el 29 de febrero cuenta como 28."""
    k = f[5:10]
    return "02-28" if k == "02-29" else k


def climatologia(p, previo):
    """Normal 1991-2020 de cada día del año en la celda del punto."""
    c = previo.get(p["id"])
    if c and tuple(c.get("celda", ())) == tuple(p["celda"]) and len(c.get("normal", {})) >= 365:
        return c
    la, lo = p["celda"]
    lo360 = lo % 360
    url = (f"{UPWELL}?sst[({NORMAL[0]}-01-01T12:00:00Z):1:({NORMAL[1]}-12-31T12:00:00Z)][(0.0)]"
           f"[({la:.3f}):1:({la:.3f})][({lo360:.3f}):1:({lo360:.3f})]")
    log(f"   normal 1991-2020 de {p['nombre']} (celda {la}, {lo})...")
    serie = parse_csv(http(url, timeout=300))
    dias = sorted(serie)
    if len(dias) < 10000:
        raise RuntimeError(f"serie 1991-2020 incompleta ({len(dias)} días)")
    # ventana centrada de 15 días alrededor de cada día del calendario
    base = date(2001, 1, 1)
    por_md = {}
    for f in dias:
        por_md.setdefault(md(f), []).append(serie[f])
    normal = {}
    for i in range(365):
        d0 = base + timedelta(days=i)
        vals = []
        for k in range(-VENTANA, VENTANA + 1):
            vals += por_md.get((d0 + timedelta(days=k)).strftime("%m-%d"), [])
        normal[d0.strftime("%m-%d")] = round(sum(vals) / len(vals), 2)
    time.sleep(2)
    return {"celda": list(p["celda"]), "dias_serie": len(dias), "normal": normal}


def clasificar(anom):
    if anom is None:
        return "#888888", "Sin datos"
    if anom <= -2.0:
        return "#0066CC", "Muy por debajo de la media"
    if anom <= -1.0:
        return "#4499DD", "Por debajo de la media"
    if anom < -0.3:
        return "#88BBEE", "Ligeramente frío"
    if anom <= 0.3:
        return "#44AA66", "Normal"
    if anom < 1.0:
        return "#FFCC44", "Ligeramente cálido"
    if anom < 2.0:
        return "#FF8822", "Por encima de la media"
    return "#CC2200", "Muy por encima de la media"


def signo_de(a):
    return "positiva" if a > 0 else "negativa" if a < 0 else "normal"


def rachas(anoms):
    """anoms: [(fecha, anomalia)] de más antigua a más reciente."""
    max_pos = max_neg = cur = 0
    prev = None
    for _, a in anoms:
        s = signo_de(a)
        cur = cur + 1 if s == prev else 1
        prev = s
        if s == "positiva":
            max_pos = max(max_pos, cur)
        elif s == "negativa":
            max_neg = max(max_neg, cur)
    return cur, prev, max_pos, max_neg


def leer(ruta, defecto):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return defecto


def main():
    ahora = datetime.now(TZ)
    previo = {p["id"]: p for p in leer(SALIDA, {}).get("puntos", [])}
    clima_prev = leer(CLIMA, {}).get("puntos", {})
    historial = leer(HISTORIAL, {})

    try:
        fin_nrt = ultimo(NRT)
    except Exception as e:  # noqa: BLE001
        log(f"NRT no responde: {e}")
        fin_nrt = None
    try:
        fin_def = ultimo(DEF)
    except Exception as e:  # noqa: BLE001
        log(f"Definitiva no responde: {e}")
        fin_def = None
    if not fin_nrt and not fin_def:
        log("La NOAA no responde: se conserva el JSON anterior.")
        return

    clima, resultados, con_dato = {}, [], 0
    for p in PUNTOS:
        log(f"Procesando {p['nombre']}...")
        dist = round(km(p["lat"], p["lon"], *p["celda"]))
        base = {"id": p["id"], "nombre": p["nombre"], "zona": p["zona"], "lat": p["lat"], "lon": p["lon"],
                "celda_lat": p["celda"][0], "celda_lon": p["celda"][1], "distancia_km": dist}
        try:
            c = climatologia(p, clima_prev)
            clima[p["id"]] = c
            serie = {}
            if fin_def:
                serie.update(serie_cw(DEF, p["celda"], (fin_def - timedelta(days=400)).isoformat(), fin_def.isoformat()))
            if fin_nrt and (not fin_def or fin_nrt > fin_def):
                desde = (fin_def + timedelta(days=1)) if fin_def else fin_nrt - timedelta(days=30)
                nrt = serie_cw(NRT, p["celda"], desde.isoformat(), fin_nrt.isoformat())
                serie.update(nrt)
            if not serie:
                raise RuntimeError("serie vacía")
            fecha = max(serie)
            actual = round(serie[fecha], 1)
            normal = c["normal"][md(fecha)]
            anom = round(serie[fecha] - normal, 1)
            # el mismo día del calendario del año anterior (el 29 de febrero, el 28)
            hace_un_anio = f"{int(fecha[:4]) - 1}-{md(fecha)}"
            ant = serie.get(hace_un_anio)
            anoms = [(f, round(serie[f] - c["normal"][md(f)], 2)) for f in sorted(serie)[-365:]]
            dias_c, sig_c, max_pos, max_neg = rachas(anoms)
            historial[p["id"]] = [{"fecha": f, "signo": signo_de(a), "anomalia": a} for f, a in reversed(anoms)]
            color, etiqueta = clasificar(anom)
            resultados.append({
                **base,
                "fecha_dato": fecha,
                "provisional": bool(fin_def and fecha > fin_def.isoformat()),
                "temperatura_actual": actual,
                "temperatura_anio_anterior": round(ant, 1) if ant is not None else None,
                "fecha_anio_anterior": hace_un_anio if ant is not None else None,
                "diferencia_anual": round(serie[fecha] - ant, 1) if ant is not None else None,
                "media_historica_mes": round(normal, 1),   # nombre heredado: es la normal 1991-2020 de ESE día
                "media_1991_2020_dia": round(normal, 1),
                "anomalia": anom,
                "color": color,
                "etiqueta_anomalia": etiqueta,
                "dias_consecutivos": dias_c,
                "signo_consecutivo": sig_c,
                "max_dias_positiva": max_pos,
                "max_dias_negativa": max_neg,
                "rachas_desde": anoms[0][0],
            })
            con_dato += 1
            log(f"  ✓ {fecha}: {actual} °C · normal {normal:.1f} · anomalía {anom:+.1f}")
        except Exception as e:  # noqa: BLE001
            log(f"  ✗ {p['nombre']}: {e}")
            if p["id"] in clima_prev:
                clima[p["id"]] = clima_prev[p["id"]]
            pv = previo.get(p["id"])
            if pv and pv.get("fecha_dato"):
                resultados.append({**pv, **base})      # el dato anterior, con su fecha
                con_dato += 1
            else:
                resultados.append({**base, "fecha_dato": None, "temperatura_actual": None,
                                   "temperatura_anio_anterior": None, "diferencia_anual": None,
                                   "media_historica_mes": None, "anomalia": None,
                                   "color": "#888888", "etiqueta_anomalia": "Sin datos",
                                   "dias_consecutivos": None, "signo_consecutivo": None,
                                   "max_dias_positiva": None, "max_dias_negativa": None})
        time.sleep(1)

    if con_dato == 0:
        log("Ningún punto con dato: se conserva el JSON anterior.")
        return

    fechas = [r["fecha_dato"] for r in resultados if r.get("fecha_dato")]
    os.makedirs("docs", exist_ok=True)
    salida = {
        "ultima_actualizacion": ahora.isoformat(),
        "fecha_legible": ahora.strftime("%d/%m/%Y a las %H:%M"),
        "fecha_dato": max(fechas) if fechas else None,
        "total_puntos": len(PUNTOS),
        "puntos_con_datos": con_dato,
        "fuente": "NOAA OISST v2.1 (satélite, 0,25°)",
        "normal": "1991-2020, misma celda, ventana de 15 días",
        "metodo": METODO,
        "aviso": ("Temperatura de la superficie del mar en la celda de 0,25° más cercana a cada punto (entre 2 y 22 km "
                  "mar adentro), no la del agua en la orilla. Los últimos días son la versión preliminar de la NOAA."),
        "puntos": resultados,
    }
    with open(SALIDA, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)
    with open(HISTORIAL, "w", encoding="utf-8") as f:
        json.dump(historial, f, ensure_ascii=False, indent=1)
    with open(CLIMA, "w", encoding="utf-8") as f:
        json.dump({"fuente": "NOAA OISST v2.1 (definitiva, ERDDAP upwell oisst_rclone)",
                   "periodo": f"{NORMAL[0]}-{NORMAL[1]}", "ventana_dias": 2 * VENTANA + 1, "puntos": clima},
                  f, ensure_ascii=False, separators=(",", ":"))
    log(f"\n✓ {con_dato}/{len(PUNTOS)} puntos · dato más reciente: {salida['fecha_dato']}")


if __name__ == "__main__":
    main()
