#!/usr/bin/env python3
"""
obtener_reloj_climatico.py · Descarga la API pública del Climate Clock y deja en
docs/reloj_climatico.json lo que necesita la página /reloj-climatico/:

  · la fecha límite (carbon_deadline_1) y el tiempo restante ya calculado
    (días, y el desglose años/días) a la hora de ejecución,
  · las «líneas de vida» con initial / rate / timestamp, para que el navegador
    pueda hacerlas avanzar en vivo igual que el reloj de Union Square,
  · una frase citable en castellano con la fecha del día, para el bloque SSR.

Fuente: https://api.climateclock.world/v2/clock.json (proyecto Climate Clock,
Beautiful Trouble). El reloj se recalcula cada tres meses con el presupuesto de
carbono del IPCC / MCC Berlín; este script sólo lo replica, no lo calcula.

Si la API falla, se conserva el JSON anterior actualizando sólo el tiempo
restante (la fecha límite cambia cada trimestre, no cada día) y se marca
`fuente_ok: false`. Así el contador nunca se queda vacío.

Uso: python scripts/obtener_reloj_climatico.py  (sin dependencias fuera de requests)
"""
import json, sys, datetime as dt
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("pip install requests")

API     = "https://api.climateclock.world/v2/clock.json"
SALIDA  = Path("docs/reloj_climatico.json")
TIMEOUT = 30

# Etiquetas en castellano y orden de presentación. Lo que no esté aquí no se
# muestra (por ejemplo _youth_anxiety, que no es un indicador de solución).
LIFELINES = {
    "renewables_1":                  ("Energía mundial procedente de renovables", 1),
    "initiative_30x30":              ("Superficie terrestre y marina protegida (meta: 30 % en 2030)", 2),
    "loss_damage_g20_debt":          ("Deuda climática de los países del G20 (pérdidas y daños)", 3),
    "end_subsidies":                 ("Subsidios anuales del G20 a los combustibles fósiles", 4),
    "indigenous_land_1":             ("Tierras gestionadas por pueblos indígenas", 5),
    "ff_divestment_stand_dot_earth": ("Capital desinvertido de combustibles fósiles", 6),
    "regen_agriculture":             ("Hectáreas en agricultura regenerativa", 7),
    "women_in_parliaments":          ("Mujeres en los parlamentos del mundo", 8),
    "actnow":                        ("Ahorro estimado hasta 2050 si se actúa ya", 9),
}
UNIDAD_ES = {"%": "%", "$T": "bill. $", "$B": "mil M$", "ha": "ha", "M km²": "M km²"}

MESES = "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split()


def fecha_es(d):
    return f"{d.day} de {MESES[d.month-1]} de {d.year}"


def iso(t):
    return dt.datetime.fromisoformat(t.replace("Z", "+00:00"))


def desglose(ahora, limite):
    """Años, días, horas, minutos y segundos completos entre dos instantes."""
    if limite <= ahora:
        return dict(anos=0, dias=0, horas=0, minutos=0, segundos=0, dias_totales=0)
    # años completos según el calendario, luego el resto en días
    anos = 0
    cursor = ahora
    while True:
        try:
            sig = cursor.replace(year=cursor.year + 1)
        except ValueError:            # 29 de febrero
            sig = cursor.replace(year=cursor.year + 1, day=28)
        if sig > limite:
            break
        cursor, anos = sig, anos + 1
    resto = limite - cursor
    return dict(anos=anos, dias=resto.days, horas=resto.seconds // 3600,
                minutos=(resto.seconds % 3600) // 60, segundos=resto.seconds % 60,
                dias_totales=(limite - ahora).days)


def valor_actual(m, ahora):
    """Mismo cálculo que hace el reloj físico: initial + rate · segundos transcurridos."""
    t0 = iso(m["timestamp"])
    return m["initial"] + m.get("rate", 0) * (ahora - t0).total_seconds()


def frase_citable(ahora, limite, dg):
    partes = []
    if dg["anos"]:
        partes.append(f'{dg["anos"]} {"año" if dg["anos"] == 1 else "años"}')
    partes.append(f'{dg["dias"]} {"día" if dg["dias"] == 1 else "días"}')
    tiempo = " y ".join(partes)
    total = f'{dg["dias_totales"]:,}'.replace(",", ".")   # 1,048 → 1.048
    return (f'A {fecha_es(ahora)}, el reloj climático marca {tiempo} '
            f'({total} días en total) hasta el {fecha_es(limite)}, fecha en la que, '
            f'al ritmo actual de emisiones, se agota el presupuesto de carbono con un 67 % de probabilidad '
            f'de limitar el calentamiento a 1,5 °C, según el proyecto Climate Clock a partir del IPCC y el MCC de Berlín.')


def main():
    ahora = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    previo = json.loads(SALIDA.read_text(encoding="utf-8")) if SALIDA.exists() else None
    fuente_ok = True
    try:
        r = requests.get(API, timeout=TIMEOUT, headers={"User-Agent": "calentamientoglobal.es (reloj climático)"})
        r.raise_for_status()
        modulos = r.json()["data"]["modules"]
        limite_iso = modulos["carbon_deadline_1"]["timestamp"]
        lifelines = []
        for clave, (etiqueta, orden) in LIFELINES.items():
            m = modulos.get(clave)
            if not m or m.get("type") != "value":
                continue
            lifelines.append({
                "id": clave, "orden": orden, "etiqueta": etiqueta,
                "unidad": m.get("unit", ""), "unidad_es": UNIDAD_ES.get(m.get("unit", ""), m.get("unit", "")),
                "initial": m["initial"], "rate": m.get("rate", 0), "timestamp": m["timestamp"],
                "resolution": m.get("resolution"),
                "valor_hoy": round(valor_actual(m, ahora), 4),
                "etiqueta_original": (m.get("labels") or [""])[0],
            })
        lifelines.sort(key=lambda x: x["orden"])
    except Exception as e:                                  # red caída, cambio de esquema…
        print(f"[aviso] no se pudo leer la API ({e}); se reutiliza el JSON anterior", file=sys.stderr)
        if not previo:
            sys.exit(1)
        fuente_ok = False
        limite_iso = previo["fecha_limite"]
        lifelines = previo.get("lifelines", [])
        for lf in lifelines:
            lf["valor_hoy"] = round(valor_actual(lf, ahora), 4)

    limite = iso(limite_iso)
    dg = desglose(ahora, limite)
    salida = {
        "ultima_actualizacion": ahora.isoformat(),
        "fuente_ok": fuente_ok,
        "fuente": {"nombre": "Climate Clock", "url": "https://climateclock.world/", "api": API},
        "fecha_limite": limite_iso,
        "fecha_limite_es": fecha_es(limite),
        "presupuesto": {"gt_co2_desde_2020": 400, "probabilidad": "67 %", "objetivo_c": 1.5,
                        "nota": "Presupuesto de carbono del IPCC (AR6, 2021) tal y como lo aplica Climate Clock; "
                                "el reloj se recalcula aproximadamente cada tres meses."},
        "restante": dg,
        "frase_citable": frase_citable(ahora, limite, dg),
        "lifelines": lifelines,
    }
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f'[ok] límite {salida["fecha_limite_es"]} · quedan {dg["anos"]} años y {dg["dias"]} días '
          f'({dg["dias_totales"]} días) · {len(lifelines)} líneas de vida · fuente_ok={fuente_ok}')


if __name__ == "__main__":
    main()
