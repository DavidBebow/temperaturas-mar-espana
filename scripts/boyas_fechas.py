#!/usr/bin/env python3
"""Lo normal para estas fechas en cada boya, con los datos diarios · calentamientoglobal.es

5-11-2026. La sala de prensa comparaba la media de los últimos 7 días de cada boya con la media de todo el mes en su
serie, y a principios de noviembre eso inflaba la diferencia (el mar se enfría a lo largo del mes). Este script usa el
histórico DIARIO de cada boya (privado: clima-scripts/datos/boyas_historico.json, Puertos del Estado vía Copernicus
Marine, medias diarias con control de calidad) y calcula, para cada año anterior, la media de los MISMOS 7 días del
calendario que la semana actual de la boya.

Entrada:
  BOYAS_DATOS   histórico diario (privado; no se publica)
  BOYAS_ACTUAL  docs/boyas_actual.json (fecha del último dato de cada boya)
Salida:
  BOYAS_FECHAS  docs/boyas_fechas.json — solo agregados: por boya, la media de esos 7 días en cada año con al menos
                MIN_DIAS días con dato. No se publica la serie diaria.

Solo biblioteca estándar. Uso: python scripts/boyas_fechas.py
"""
import datetime as dt
import json
import os
import sys

DATOS = os.environ.get("BOYAS_DATOS", "privado/datos/boyas_historico.json")
ACTUAL = os.environ.get("BOYAS_ACTUAL", "docs/boyas_actual.json")
SALIDA = os.environ.get("BOYAS_FECHAS", "docs/boyas_fechas.json")
VENTANA = 7
MIN_DIAS = 5


def _misma_fecha(d, anio):
    try:
        return d.replace(year=anio)
    except ValueError:          # 29 de febrero
        return d.replace(year=anio, day=28)


def main():
    if not os.path.exists(DATOS):
        print(f"Sin histórico diario en {DATOS}: no hay nada que calcular")
        return 0
    hist = (json.load(open(DATOS, encoding="utf-8")) or {}).get("boyas") or {}
    actual = (json.load(open(ACTUAL, encoding="utf-8")) or {}).get("boyas") or {}
    out = {"generado": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
           "fuente": "Puertos del Estado (boyas REDEXT/REDCOS, vía Copernicus Marine In Situ TAC); medias diarias con control de calidad",
           "metodo": (f"Para cada año anterior, media de los mismos {VENTANA} días del calendario que acaban en la fecha del último "
                      f"dato de la boya; solo años con al menos {MIN_DIAS} de esos días con dato."),
           "ventana_dias": VENTANA, "min_dias": MIN_DIAS, "boyas": {}}
    for bid, a in actual.items():
        h = hist.get(bid)
        if not h or not h.get("inicio") or not a.get("fecha"):
            continue
        d0 = dt.date.fromisoformat(h["inicio"])
        vals = h.get("valores") or []
        fin = dt.date.fromisoformat(a["fecha"])
        anios, dias = {}, {}
        for y in range(d0.year, fin.year):
            f = _misma_fecha(fin, y)
            xs = []
            for k in range(VENTANA):
                i = (f - dt.timedelta(days=k) - d0).days
                if 0 <= i < len(vals) and vals[i] is not None:
                    xs.append(vals[i])
            if len(xs) >= MIN_DIAS:
                anios[str(y)] = round(sum(xs) / len(xs), 2)
                dias[str(y)] = len(xs)
        out["boyas"][bid] = {"fin": fin.isoformat(), "anios": anios, "dias": dias,
                             "historico_hasta": (d0 + dt.timedelta(days=len(vals) - 1)).isoformat() if vals else None}
        print(f"{bid:18s} fin {fin}  {len(anios)} años con la semana completa")
    with open(SALIDA, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print(f"Escrito {SALIDA}: {len(out['boyas'])} boyas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
