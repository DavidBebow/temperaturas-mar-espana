"""
Script de DIAGNÓSTICO: prueba la API de AEMET con UNA SOLA estación
y muestra todo el detalle. Sustituye temporalmente tu script por este
y ejecuta el workflow para ver qué pasa exactamente.
"""
import requests
import os
from datetime import date, timedelta

API_KEY = os.environ.get("AEMET_API_KEY", "")

print("=" * 60)
print("DIAGNÓSTICO AEMET OpenData")
print("=" * 60)

# 1. Comprobar que el secret está disponible
if not API_KEY:
    print("❌ AEMET_API_KEY no está definida como variable de entorno.")
    print("   Comprueba que el secret existe en GitHub y se pasa al script.")
    exit(1)

print(f"✓ API_KEY recibida (longitud: {len(API_KEY)} caracteres)")
print(f"  Primeros 10 caracteres: {API_KEY[:10]}...")
print(f"  Últimos 5 caracteres: ...{API_KEY[-5:]}")

# 2. Probar con una sola petición a Sevilla, últimos 10 días
ayer = date.today() - timedelta(days=1)
fecha_ini = ayer - timedelta(days=10)
idema = "5783"  # Sevilla

url = (
    f"https://opendata.aemet.es/opendata/api/valores/climatologicos/diarios/datos"
    f"/fechaini/{fecha_ini.strftime('%Y-%m-%dT00:00:00UTC')}"
    f"/fechafin/{ayer.strftime('%Y-%m-%dT00:00:00UTC')}"
    f"/estacion/{idema}"
)

print(f"\n📡 Probando URL:")
print(f"   {url}")

# Prueba 1: API key como header
print(f"\n🔍 Intento 1: API key como header")
try:
    r = requests.get(url, headers={"api_key": API_KEY, "Accept": "application/json"}, timeout=15)
    print(f"   Status: {r.status_code}")
    print(f"   Respuesta: {r.text[:400]}")
    if r.status_code == 200:
        body = r.json()
        print(f"   Estado interno: {body.get('estado')}")
        print(f"   URL de datos: {body.get('datos')}")
        if body.get("datos"):
            print(f"\n   📥 Descargando datos desde: {body['datos']}")
            r2 = requests.get(body["datos"], timeout=15)
            print(f"   Status descarga: {r2.status_code}")
            if r2.status_code == 200:
                datos = r2.json()
                print(f"   ✓ Recibidos {len(datos)} registros diarios.")
                if datos:
                    print(f"   Primer registro: {datos[0]}")
            else:
                print(f"   ❌ Respuesta descarga: {r2.text[:300]}")
except Exception as e:
    print(f"   ❌ Excepción: {e}")

# Prueba 2: API key como query param (formato alternativo)
print(f"\n🔍 Intento 2: API key como parámetro de URL (?api_key=...)")
url2 = url + f"/?api_key={API_KEY}"
try:
    r = requests.get(url2, headers={"Accept": "application/json"}, timeout=15)
    print(f"   Status: {r.status_code}")
    print(f"   Respuesta: {r.text[:400]}")
except Exception as e:
    print(f"   ❌ Excepción: {e}")

print("\n" + "=" * 60)
print("FIN del diagnóstico")
print("=" * 60)
