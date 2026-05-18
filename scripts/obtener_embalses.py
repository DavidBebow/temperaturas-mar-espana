import requests
import json
import os
from datetime import datetime
from bs4 import BeautifulSoup

# ============================================================
# METADATOS ESTÁTICOS — ubicaciones y capacidades
# No cambian, se actualizan manualmente si construyen uno nuevo
# ============================================================

EMBALSES_MURCIA = [
    {"id": "cenajo",        "nombre": "Cenajo",        "rio": "Segura",       "municipio": "Moratalla",   "lat": 38.356, "lon": -2.024, "capacidad_hm3": 437.5},
    {"id": "camarillas",    "nombre": "Camarillas",    "rio": "Mundo",        "municipio": "Hellín",      "lat": 38.164, "lon": -2.094, "capacidad_hm3": 36.7},
    {"id": "alfonso_xiii",  "nombre": "Alfonso XIII",  "rio": "Quípar",       "municipio": "Calasparra",  "lat": 38.214, "lon": -1.728, "capacidad_hm3": 70.0},
    {"id": "la_cierva",     "nombre": "La Cierva",     "rio": "Segura",       "municipio": "Cieza",       "lat": 38.075, "lon": -1.592, "capacidad_hm3": 12.0},
    {"id": "valdeinfierno", "nombre": "Valdeinfierno", "rio": "Luchena",      "municipio": "Lorca",       "lat": 37.953, "lon": -1.872, "capacidad_hm3": 11.3},
    {"id": "puentes",       "nombre": "Puentes",       "rio": "Guadalentín",  "municipio": "Lorca",       "lat": 37.776, "lon": -1.787, "capacidad_hm3": 45.3},
    {"id": "argos",         "nombre": "Argos",         "rio": "Argos",        "municipio": "Calasparra",  "lat": 38.338, "lon": -1.907, "capacidad_hm3": 11.3},
    {"id": "santomera",     "nombre": "Santomera",     "rio": "Ramblas",      "municipio": "Santomera",   "lat": 38.072, "lon": -1.057, "capacidad_hm3": 17.9},
    {"id": "pliego",        "nombre": "Pliego",        "rio": "Pliego",       "municipio": "Pliego",      "lat": 38.009, "lon": -1.558, "capacidad_hm3": 3.6},
    {"id": "mula",          "nombre": "Mula",          "rio": "Mula",         "municipio": "Mula",        "lat": 38.052, "lon": -1.496, "capacidad_hm3": 21.0},
    {"id": "anchuricas",    "nombre": "Anchuricas",    "rio": "Segura",       "municipio": "Moratalla",   "lat": 37.978, "lon": -2.469, "capacidad_hm3": 7.0},
    {"id": "taibilla",      "nombre": "Taibilla",      "rio": "Taibilla",     "municipio": "Nerpio",      "lat": 38.174, "lon": -2.105, "capacidad_hm3": 15.3},
]

# Mapa comunidades autónomas → identificador
COMUNIDADES = {
    "murcia": {
        "nombre": "Región de Murcia",
        "embalses_ids": [e["id"] for e in EMBALSES_MURCIA],
    }
    # Aquí irán añadiéndose el resto de comunidades
}

def obtener_datos_chs():
    """
    Intenta obtener datos en tiempo real del SAIH de la
    Confederación Hidrográfica del Segura (CHS).
    """
    resultados = {}

    # Endpoint CHS SAIH — visor público de embalses
    urls_intentar = [
        "https://www.chsegura.es/saih/datos/embalses.json",
        "http://www.chsegura.es/saih/consultas/Embalsada.json",
        "https://www.chsegura.es/es/confederacion/saih/consultas-datos/",
    ]

    for url in urls_intentar:
        try:
            r = requests.get(url, timeout=15,
                             headers={"User-Agent": "calentamientoglobal.es/embalses"})
            if r.status_code == 200 and r.text.strip().startswith("[") or r.text.strip().startswith("{"):
                data = r.json()
                print(f"  ✓ CHS SAIH OK: {url}")
                # Parsear según la estructura devuelta
                if isinstance(data, list):
                    for item in data:
                        nombre = item.get("nombre") or item.get("name") or ""
                        volumen = item.get("volumen") or item.get("volActual") or item.get("value")
                        capacidad = item.get("capacidad") or item.get("capTotal")
                        if nombre and volumen is not None and capacidad:
                            pct = round((float(volumen) / float(capacidad)) * 100, 1)
                            resultados[nombre.lower().replace(" ", "_")] = {
                                "volumen_hm3": round(float(volumen), 2),
                                "pct": pct
                            }
                return resultados
        except Exception as e:
            print(f"  ✗ {url}: {e}")
            continue

    return resultados

def obtener_datos_miteco():
    """
    Fallback: obtiene datos del Boletín Hidrológico del MITECO.
    Devuelve datos agregados por confederación.
    """
    resultados = {}
    url = "https://www.miteco.gob.es/es/agua/temas/evaluacion-de-los-recursos-hidricos/boletin-hidrologico.html"

    try:
        r = requests.get(url, timeout=20,
                         headers={"User-Agent": "calentamientoglobal.es/embalses"})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # Buscar tabla con datos de confederaciones
        tablas = soup.find_all("table")
        for tabla in tablas:
            filas = tabla.find_all("tr")
            for fila in filas:
                celdas = fila.find_all(["td", "th"])
                if len(celdas) >= 3:
                    texto = celdas[0].get_text(strip=True).lower()
                    if "segura" in texto:
                        try:
                            # Buscar % en las celdas
                            for celda in celdas[1:]:
                                txt = celda.get_text(strip=True).replace(",", ".").replace("%", "")
                                try:
                                    pct = float(txt)
                                    if 0 < pct < 100:
                                        resultados["segura_pct"] = pct
                                        print(f"  ✓ MITECO Segura: {pct}%")
                                        break
                                except ValueError:
                                    continue
                        except Exception:
                            pass

    except Exception as e:
        print(f"  ✗ MITECO: {e}")

    return resultados

def calcular_color(pct):
    if pct is None:      return "#888888", "Sin datos"
    if pct < 20:         return "#CC2200", "Crítico"
    if pct < 40:         return "#FF8822", "Bajo"
    if pct < 60:         return "#FFCC44", "Moderado"
    if pct < 80:         return "#44AA66", "Bueno"
    return "#0066CC",    "Muy bueno"

def generar_json():
    print(f"\n{'='*60}")
    print(f"Actualizando embalses — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*60}\n")

    # Intentar obtener datos reales
    print("Intentando SAIH CHS (Segura)...")
    datos_chs = obtener_datos_chs()

    print("Intentando MITECO boletín...")
    datos_miteco = obtener_datos_miteco()

    # Generar JSON para Murcia
    embalses_resultado = []
    total_vol = 0
    total_cap = 0

    for e in EMBALSES_MURCIA:
        # Buscar dato real por ID o nombre
        volumen_hm3 = None
        pct         = None

        if e["id"] in datos_chs:
            d = datos_chs[e["id"]]
            volumen_hm3 = d["volumen_hm3"]
            pct         = d["pct"]
        elif e["nombre"].lower().replace(" ", "_") in datos_chs:
            d = datos_chs[e["nombre"].lower().replace(" ", "_")]
            volumen_hm3 = d["volumen_hm3"]
            pct         = d["pct"]

        color, etiqueta = calcular_color(pct)

        if volumen_hm3 is not None:
            total_vol += volumen_hm3
            total_cap += e["capacidad_hm3"]

        embalses_resultado.append({
            "id":            e["id"],
            "nombre":        e["nombre"],
            "rio":           e["rio"],
            "municipio":     e["municipio"],
            "provincia":     "Murcia",
            "comunidad":     "Región de Murcia",
            "lat":           e["lat"],
            "lon":           e["lon"],
            "capacidad_hm3": e["capacidad_hm3"],
            "volumen_hm3":   volumen_hm3,
            "pct":           pct,
            "color":         color,
            "etiqueta":      etiqueta,
        })

        estado = f"{pct}%" if pct is not None else "Sin dato"
        print(f"  {e['nombre']}: {estado}")

    pct_media_murcia = round((total_vol / total_cap) * 100, 1) if total_cap > 0 else None

    # Fallback al dato agregado de MITECO si no tenemos individuales
    if pct_media_murcia is None and "segura_pct" in datos_miteco:
        pct_media_murcia = datos_miteco["segura_pct"]

    color_murcia, etiqueta_murcia = calcular_color(pct_media_murcia)

    # ── JSON MURCIA DETALLE ──────────────────────────────────
    os.makedirs("docs/embalses", exist_ok=True)

    murcia_output = {
        "ultima_actualizacion": datetime.now().isoformat(),
        "fecha_legible":        datetime.now().strftime("%d/%m/%Y a las %H:%M"),
        "comunidad":            "Región de Murcia",
        "provincia":            "Murcia",
        "total_embalses":       len(EMBALSES_MURCIA),
        "capacidad_total_hm3":  sum(e["capacidad_hm3"] for e in EMBALSES_MURCIA),
        "volumen_total_hm3":    round(total_vol, 2) if total_vol else None,
        "pct_media":            pct_media_murcia,
        "color":                color_murcia,
        "etiqueta":             etiqueta_murcia,
        "fuente":               "SAIH CHS / MITECO",
        "embalses":             embalses_resultado,
    }

    with open("docs/embalses/murcia.json", "w", encoding="utf-8") as f:
        json.dump(murcia_output, f, ensure_ascii=False, indent=2)
    print(f"\n✓ docs/embalses/murcia.json guardado")

    # ── JSON NACIONAL ────────────────────────────────────────
    nacional_output = {
        "ultima_actualizacion": datetime.now().isoformat(),
        "fecha_legible":        datetime.now().strftime("%d/%m/%Y a las %H:%M"),
        "fuente":               "SAIH CHS / MITECO",
        "comunidades": [
            {
                "id":       "murcia",
                "nombre":   "Región de Murcia",
                "pct":      pct_media_murcia,
                "color":    color_murcia,
                "etiqueta": etiqueta_murcia,
                "url_detalle": "embalses/murcia.html",
                "datos_disponibles": True,
            },
            # El resto de comunidades se añadirán aquí
        ]
    }

    with open("docs/embalses_nacional.json", "w", encoding="utf-8") as f:
        json.dump(nacional_output, f, ensure_ascii=False, indent=2)
    print(f"✓ docs/embalses_nacional.json guardado")

    if pct_media_murcia:
        print(f"\n📊 Murcia: {pct_media_murcia}% embalsado ({etiqueta_murcia})")

if __name__ == "__main__":
    generar_json()
