#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Focos de fuego en la Amazonía — calentamientoglobal.es

Fuente: INPE · Programa Queimadas, ficheros diarios abiertos de América del Sur
(https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/diario/America_Sul/).
Cada fichero trae, foco a foco: coordenadas, satélite, municipio, estado, país,
bioma (solo en Brasil), días sin lluvia, riesgo de fuego y FRP.

Dos cosas que hay que tener claras antes de tocar este dato:

1) UN FOCO NO ES UN INCENDIO. Es un píxel caliente detectado por un satélite.
   Un incendio grande genera muchos focos y un foco puede ser una quema
   agrícola de media hectárea.

2) NO SE PUEDEN SUMAR TODOS LOS SATÉLITES Y COMPARAR CON EL PASADO. El fichero
   mezcla una docena de satélites y el número de satélites ha crecido con los
   años. Por eso aquí se cuentan las dos cosas por separado:
   - 'todos_satelites': la foto de hoy, buena para el mapa y el titular del día.
   - 'satelite_referencia' (AQUA_M-T): la serie comparable con años anteriores,
     que es la que usa el propio INPE para sus estadísticas históricas.

Definición de Amazonía que usa este script:
   - Brasil: bioma = Amazônia (campo oficial del INPE).
   - Resto: departamentos/estados amazónicos completos (ver REGIONES_AMAZONICAS).
     Los territorios de transición (Santa Cruz, Meta, Vichada…) se cuentan
     aparte, en 'parcial', y no entran en el total.

Salida:
    docs/amazonia/fuego.json            ← lo que consume la web
    docs/amazonia/fuego_historico.json  ← archivo propio, un registro por día

Uso:
    python obtener_amazonia_fuego.py                # últimos 3 días
    python obtener_amazonia_fuego.py --dias 30      # rellena hacia atrás
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
import unicodedata
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

# --------------------------------------------------------------------------
# Configuración
# --------------------------------------------------------------------------

RAIZ = Path(__file__).resolve().parent.parent
SALIDA_DIR = RAIZ / "docs" / "amazonia"
SALIDA = SALIDA_DIR / "fuego.json"
HISTORICO = SALIDA_DIR / "fuego_historico.json"
CLIMATOLOGIA = SALIDA_DIR / "fuego_climatologia.json"   # lo genera el script de backfill

BASE = ("https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/"
        "diario/America_Sul/focos_diario_{fecha}.csv")

SATELITE_REFERENCIA = "AQUA_M-T"
TIEMPO_ESPERA = 120
DIAS_POR_DEFECTO = 3

# Regiones amazónicas por país. Nombres tal y como los escribe el INPE en el
# CSV (la comparación ignora tildes y mayúsculas de todas formas).
REGIONES_AMAZONICAS = {
    "Peru": ["Loreto", "Ucayali", "Madre de Dios", "San Martín", "Amazonas",
             "Huánuco", "Pasco"],
    "Bolivia": ["El Beni", "Pando"],
    "Colombia": ["Amazonas", "Caquetá", "Putumayo", "Guaviare", "Guainía", "Vaupés"],
    "Ecuador": ["Sucumbios", "Orellana", "Napo", "Pastaza", "Morona Santiago",
                "Zamora Chinchipe"],
    "Venezuela": ["Amazonas", "Bolívar"],
    "Guyana": ["*"],
    "Suriname": ["*"],
    "French Guiana": ["*"],
    "Guiana Francesa": ["*"],
}

# Territorios de transición: se contabilizan aparte, nunca en el total.
REGIONES_PARCIALES = {
    "Bolivia": ["Santa Cruz", "La Paz", "Cochabamba"],
    "Colombia": ["Meta", "Vichada"],
    "Peru": ["Junín", "Cusco", "Puno"],
}

FUENTE = {
    "nombre": "INPE · Programa Queimadas (focos diarios de América del Sur)",
    "url": "https://terrabrasilis.dpi.inpe.br/queimadas/portal/dados-abertos/",
    "licencia": "Datos abiertos del INPE",
    "atribucion_obligatoria": "Programa Queimadas · INPE (Brasil)",
}

ADVERTENCIA = (
    "Un foco es un píxel caliente detectado por satélite, no un incendio: un "
    "solo incendio puede generar decenas de focos y una quema agrícola pequeña "
    "genera uno. Para comparar con años anteriores hay que usar la serie del "
    f"satélite de referencia ({SATELITE_REFERENCIA}), no la suma de todos los satélites."
)


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------

def log(msg: str) -> None:
    print(f"[fuego-amazonia] {msg}", flush=True)


def normaliza(s: str) -> str:
    s = (s or "").strip().strip('"')
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


REGIONES_NORM = {normaliza(p): {normaliza(e) for e in v}
                 for p, v in REGIONES_AMAZONICAS.items()}
PARCIALES_NORM = {normaliza(p): {normaliza(e) for e in v}
                  for p, v in REGIONES_PARCIALES.items()}


def clasifica(pais: str, estado: str, bioma: str) -> str:
    """Devuelve 'amazonia', 'parcial' o 'fuera'."""
    p, e, b = normaliza(pais), normaliza(estado), normaliza(bioma)
    if p == "brasil":
        return "amazonia" if b == "amazonia" else "fuera"
    regiones = REGIONES_NORM.get(p)
    if regiones and ("*" in regiones or e in regiones):
        return "amazonia"
    parciales = PARCIALES_NORM.get(p)
    if parciales and e in parciales:
        return "parcial"
    return "fuera"


def descargar_dia(f: date) -> str | None:
    url = BASE.format(fecha=f.strftime("%Y%m%d"))
    for intento in range(1, 4):
        try:
            r = requests.get(url, timeout=TIEMPO_ESPERA)
            if r.status_code == 404:
                log(f"  {f} no está publicado todavía")
                return None
            r.raise_for_status()
            return r.content.decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            log(f"  intento {intento}/3 de {f} fallido: {exc}")
            time.sleep(5 * intento)
    return None


def resumir_dia(f: date, texto: str) -> dict:
    lector = csv.DictReader(io.StringIO(texto))
    total = 0
    por_pais: Counter[str] = Counter()
    por_estado_br: Counter[str] = Counter()
    ref_total = 0
    ref_por_pais: Counter[str] = Counter()
    parcial_por_pais: Counter[str] = Counter()
    frp_suma = 0.0
    frp_n = 0
    sin_lluvia: list[float] = []
    puntos: list[list] = []

    for fila in lector:
        clase = clasifica(fila.get("pais", ""), fila.get("estado", ""), fila.get("bioma", ""))
        if clase == "fuera":
            continue
        pais = (fila.get("pais") or "").strip()
        if clase == "parcial":
            parcial_por_pais[pais] += 1
            continue

        total += 1
        por_pais[pais] += 1
        if normaliza(pais) == "brasil":
            por_estado_br[(fila.get("estado") or "").strip()] += 1

        if (fila.get("satelite") or "").strip() == SATELITE_REFERENCIA:
            ref_total += 1
            ref_por_pais[pais] += 1
            # el mapa se dibuja con el satélite de referencia: menos puntos,
            # sin solapamiento entre satélites y comparable con el pasado
            try:
                puntos.append([
                    round(float(fila["lat"]), 3),
                    round(float(fila["lon"]), 3),
                    round(float(fila.get("frp") or 0), 1),
                ])
            except (TypeError, ValueError):
                pass

        try:
            v = float(fila.get("frp") or 0)
            if v > 0:
                frp_suma += v
                frp_n += 1
        except ValueError:
            pass
        try:
            sin_lluvia.append(float(fila.get("numero_dias_sem_chuva") or 0))
        except ValueError:
            pass

    return {
        "fecha": f.isoformat(),
        "todos_satelites": total,
        "satelite_referencia": ref_total,
        "por_pais": dict(por_pais.most_common()),
        "por_pais_referencia": dict(ref_por_pais.most_common()),
        "estados_brasil": dict(por_estado_br.most_common(10)),
        "parcial_por_pais": dict(parcial_por_pais.most_common()),
        "frp_medio": round(frp_suma / frp_n, 1) if frp_n else None,
        "dias_sin_lluvia_medio": (
            round(sum(sin_lluvia) / len(sin_lluvia), 1) if sin_lluvia else None
        ),
        "puntos_referencia": puntos,
    }


# --------------------------------------------------------------------------
# Archivo propio
# --------------------------------------------------------------------------

def cargar_historico() -> dict:
    if HISTORICO.exists():
        try:
            return json.loads(HISTORICO.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            log("AVISO: el histórico no se pudo leer, se empieza uno nuevo")
    return {"dias": {}}


def guardar_historico(hist: dict) -> None:
    SALIDA_DIR.mkdir(parents=True, exist_ok=True)
    HISTORICO.write_text(
        json.dumps(hist, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def media_movil(hist: dict, hasta: date, dias: int = 7) -> float | None:
    vals = []
    for d in range(1, dias + 1):
        k = (hasta - timedelta(days=d)).isoformat()
        if k in hist["dias"]:
            vals.append(hist["dias"][k]["satelite_referencia"])
    return round(sum(vals) / len(vals), 1) if vals else None


def acumulado_mes(hist: dict, ref: date) -> dict:
    total_ref = 0
    total_todos = 0
    dias = 0
    for k, v in hist["dias"].items():
        f = date.fromisoformat(k)
        if f.year == ref.year and f.month == ref.month:
            total_ref += v["satelite_referencia"]
            total_todos += v["todos_satelites"]
            dias += 1
    return {"satelite_referencia": total_ref, "todos_satelites": total_todos,
            "dias_contados": dias}


def comparacion_historica(mes: int, acumulado_ref: int, dias_contados: int) -> dict | None:
    """Compara el acumulado del mes con la media histórica, si existe el fichero."""
    if not CLIMATOLOGIA.exists():
        return None
    try:
        clima = json.loads(CLIMATOLOGIA.read_text(encoding="utf-8"))
        bloque = clima["meses"][str(mes)]
    except Exception:  # noqa: BLE001
        return None
    media_diaria = bloque["media_diaria"]
    esperado = round(media_diaria * dias_contados)
    return {
        "periodo_referencia": clima.get("periodo"),
        "media_diaria_historica": media_diaria,
        "esperado_a_estas_alturas": esperado,
        "diferencia_pct": (
            round(100.0 * (acumulado_ref - esperado) / esperado, 1) if esperado else None
        ),
    }


# --------------------------------------------------------------------------

def construir(dias: int) -> dict:
    hoy = date.today()
    hist = cargar_historico()
    fallos = []
    nuevos = 0

    for d in range(dias, -1, -1):
        f = hoy - timedelta(days=d)
        clave = f.isoformat()
        # el día en curso y el anterior se vuelven a leer siempre (se completan)
        if clave in hist["dias"] and d > 1:
            continue
        texto = descargar_dia(f)
        if texto is None:
            if d > 1:
                fallos.append({"fecha": clave, "motivo": "fichero no disponible"})
            continue
        resumen = resumir_dia(f, texto)
        resumen["definitivo"] = d >= 1
        # el histórico no guarda los puntos del mapa: solo el recuento
        puntos = resumen.pop("puntos_referencia")
        hist["dias"][clave] = resumen
        if f == hoy or (f == hoy - timedelta(days=1) and not hist.get("_puntos_hoy")):
            hist["_puntos_hoy"] = {"fecha": clave, "puntos": puntos}
        nuevos += 1
        log(f"  {clave}: {resumen['todos_satelites']} focos "
            f"({resumen['satelite_referencia']} del satélite de referencia)")

    if not hist["dias"]:
        raise RuntimeError("no se pudo leer ningún día: no se escribe nada")

    fechas = sorted(hist["dias"])
    ultimo = fechas[-1]
    penultimo = fechas[-2] if len(fechas) > 1 else None
    dia_ultimo = hist["dias"][ultimo]
    dia_previo = hist["dias"][penultimo] if penultimo else None

    guardar_historico(hist)

    ref_fecha = date.fromisoformat(ultimo)
    acum = acumulado_mes(hist, ref_fecha)
    puntos = hist.get("_puntos_hoy", {}).get("puntos", [])

    serie_30 = [
        {"fecha": k,
         "todos_satelites": hist["dias"][k]["todos_satelites"],
         "satelite_referencia": hist["dias"][k]["satelite_referencia"]}
        for k in fechas[-30:]
    ]

    return {
        "actualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fuente": FUENTE,
        "advertencia": ADVERTENCIA,
        "definicion_amazonia": {
            "brasil": "bioma Amazônia (campo oficial del INPE)",
            "otros_paises": REGIONES_AMAZONICAS,
            "excluidos_del_total": REGIONES_PARCIALES,
        },
        "satelite_referencia": SATELITE_REFERENCIA,
        "hoy": {
            "fecha": ultimo,
            "parcial": not dia_ultimo.get("definitivo", False),
            **{k: dia_ultimo[k] for k in
               ("todos_satelites", "satelite_referencia", "por_pais",
                "por_pais_referencia", "estados_brasil", "parcial_por_pais",
                "frp_medio", "dias_sin_lluvia_medio")},
        },
        "dia_anterior": (
            {"fecha": penultimo,
             "todos_satelites": dia_previo["todos_satelites"],
             "satelite_referencia": dia_previo["satelite_referencia"],
             "por_pais": dia_previo["por_pais"]}
            if dia_previo else None
        ),
        "media_7d_referencia": media_movil(hist, ref_fecha),
        "acumulado_mes": acum,
        "comparacion_historica": comparacion_historica(
            ref_fecha.month, acum["satelite_referencia"], acum["dias_contados"]),
        "serie_30_dias": serie_30,
        "dias_archivados": len(fechas),
        "puntos_mapa": puntos,
        "fallos": fallos,
        "nuevos_dias_leidos": nuevos,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dias", type=int, default=DIAS_POR_DEFECTO,
                    help="cuántos días hacia atrás revisar (el INPE guarda ~120)")
    args = ap.parse_args()

    datos = construir(args.dias)
    SALIDA_DIR.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")

    hoy = datos["hoy"]
    log(f"escrito {SALIDA}")
    log(f"  {hoy['fecha']}{' (parcial)' if hoy['parcial'] else ''}: "
        f"{hoy['todos_satelites']} focos en la Amazonía")
    for pais, n in list(hoy["por_pais"].items())[:8]:
        log(f"    {pais:<18} {n}")
    log(f"  acumulado del mes (satélite de referencia): "
        f"{datos['acumulado_mes']['satelite_referencia']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        log(f"FALLO: {exc}")
        sys.exit(1)
