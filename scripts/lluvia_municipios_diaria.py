#!/usr/bin/env python3
"""
Lluvia diaria por municipio · calentamientoglobal.es
====================================================
Publica `docs/lluvias_municipios.json` con, para cada municipio con ficha, la
lluvia del ultimo dia completo, la de los ultimos 7 dias y los dias que lleva
sin llover. Sale del pluviometro de AEMET, no de la rejilla.

QUE NO PUBLICA, A PROPOSITO: el "% sobre lo normal". Esa cifra se calcula
rejilla contra rejilla y necesita la serie ERA5 completa, que no cabe aqui.
Mezclar el acumulado del pluviometro con la normal de la rejilla desviaba la
mediana un 19 %, y a 3.933 municipios mas de un 20 %. Se sigue calculando
semanalmente en la maquina de trabajo, con la serie entera.

ENTRADAS
  municipios_base.json     lo genera preparar_diario.py; INE -> estacion (16 KB)
  historico_estaciones.json  serie por estacion que este script mantiene
  AEMET_API_KEY            secreto del repositorio

POR QUE SE ACUMULA POR HORA Y NO POR DIA
/observacion/convencional/todas/ devuelve filas HORARIAS de las ultimas 24 h.
Una ejecucion a las 9:00 del dia D ve las horas 9-23 de D-1 y las 0-8 de D: no
ve ningun dia natural entero. Un dia solo queda completo entre la ejecucion de
ese dia y la del siguiente.

Y por eso se guarda una MASCARA de horas ya contadas por estacion y dia. Sin
ella, dos ejecuciones que solapen sumarian dos veces las mismas horas y la
lluvia saldria inflada sin que nada fallara ni avisara. Es el mismo error que
ya nos costo un disgusto sumando las 24 filas horarias en vez de filtrar por
fecha.
"""
import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import date, datetime, timedelta

BASE_AEMET = "https://opendata.aemet.es/opendata/api"
RUTA_OBS = "/observacion/convencional/todas/"
BASE = "municipios_base.json"
HIST = "historico_estaciones.json"
SALIDA = "docs/lluvias_municipios.json"
DIAS_GUARDADOS = 21          # sobra para los 7 dias y deja margen si falla un dia


# ----------------------------------------------------------------- AEMET

def mm(v):
    """'Ip' = inapreciable -> 0,0.

    Descartarlo en silencio era el error facil: perdia los dias de llovizna, que
    son los que deciden si una racha sin llover sigue viva o se ha roto.
    """
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None
    b = s.lower()
    if b == "ip":
        return 0.0
    if b in ("acum", "varias"):
        return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def pide(ruta, clave, reintentos=5):
    """AEMET va en dos pasos: primero el JSON con la URL de los datos, luego los
    datos. Y responde 429 con frecuencia, asi que se reintenta con espera."""
    cab = {"api_key": clave, "Accept": "application/json"}
    for intento in range(reintentos):
        try:
            req = urllib.request.Request(BASE_AEMET + ruta, headers=cab)
            with urllib.request.urlopen(req, timeout=90) as r:
                meta = json.loads(r.read().decode("utf-8", "replace"))
            if meta.get("estado") != 200 or not meta.get("datos"):
                raise RuntimeError("estado %s: %s" % (meta.get("estado"), meta.get("descripcion")))
            with urllib.request.urlopen(meta["datos"], timeout=120) as r:
                # AEMET sirve los datos en ISO-8859-15, no en UTF-8.
                return json.loads(r.read().decode("ISO-8859-15", "replace"))
        except Exception as e:
            if intento == reintentos - 1:
                raise
            print("  reintento %d tras %s" % (intento + 1, type(e).__name__), flush=True)
            time.sleep(8 * (intento + 1))


# ----------------------------------------------------------------- historico

def cargar_hist():
    if not os.path.exists(HIST):
        return {}
    with open(HIST) as f:
        return json.load(f)


def incorporar(hist, filas):
    """Suma cada fila horaria una sola vez.

    hist[fecha][idema] = [mm_acumulado, mascara_de_horas]. La mascara es un
    entero con un bit por hora: si el bit ya esta puesto, esa hora ya se conto y
    la fila se ignora. Asi dos ejecuciones que solapen dan el mismo resultado que
    una.
    """
    nuevas = repetidas = 0
    for r in filas:
        idema = r.get("idema")
        fint = str(r.get("fint", ""))
        v = mm(r.get("prec"))
        if not idema or len(fint) < 13 or v is None:
            continue
        dia, hora = fint[:10], int(fint[11:13])
        est = hist.setdefault(dia, {}).setdefault(idema, [0.0, 0])
        bit = 1 << hora
        if est[1] & bit:
            repetidas += 1
            continue
        est[0] = round(est[0] + v, 1)
        est[1] |= bit
        nuevas += 1
    return nuevas, repetidas


def completo(entrada):
    """Un dia natural necesita sus 24 horas. Con menos, no se publica como dia
    cerrado: es preferible dar el dato de anteayer que uno de medio dia."""
    return bin(entrada[1]).count("1") >= 24


def podar(hist):
    for d in sorted(hist)[:-DIAS_GUARDADOS]:
        del hist[d]


# ----------------------------------------------------------------- calculo

def racha_sin_llover(hist, idema, hasta):
    """Dias consecutivos con menos de 1 mm, contando hacia atras desde `hasta`.
    Se corta en cuanto falta un dia: una racha con huecos no es una racha."""
    n = 0
    d = datetime.strptime(hasta, "%Y-%m-%d").date()
    for _ in range(DIAS_GUARDADOS):
        e = hist.get(d.isoformat(), {}).get(idema)
        if not e or not completo(e):
            break
        if e[0] >= 1.0:
            break
        n += 1
        d -= timedelta(days=1)
    return n


def main():
    clave = os.environ.get("AEMET_API_KEY", "").strip()
    if not clave:
        sys.exit("Falta el secreto AEMET_API_KEY.")
    with open(BASE) as f:
        base = json.load(f)
    municipios = base["municipios"]
    print("Municipios con ficha: %d · estaciones distintas: %d"
          % (len(municipios), len(set(municipios.values()))))

    hist = cargar_hist()
    filas = pide(RUTA_OBS, clave)
    if not isinstance(filas, list):
        sys.exit("Respuesta inesperada de AEMET.")
    nuevas, repetidas = incorporar(hist, filas)
    print("Filas horarias: %d · nuevas %d · ya contadas %d" % (len(filas), nuevas, repetidas))

    # El historico se guarda AQUI, antes de decidir si hay algo que publicar.
    #
    # Estaba al final y era un fallo de los que no fallan: la primera ejecucion
    # salia por "ningun dia completo todavia" SIN guardar lo que acababa de
    # descargar, asi que la siguiente empezaba de cero y ningun dia podia
    # cerrarse nunca. El trabajo diario no habria funcionado jamas, y en el
    # registro solo se veria ese mensaje, que parece normal.
    podar(hist)
    with open(HIST, "w") as f:
        json.dump(hist, f, separators=(",", ":"), sort_keys=True)

    # El ultimo dia natural CERRADO, no "ayer" por calendario: si AEMET se salta
    # una hora, ayer no esta completo y se publica anteayer diciendolo.
    #
    # El umbral se calibra solo, contra el mejor dia del historico, en vez de ser
    # un numero fijo. Un "minimo 50 estaciones" escrito a mano funciona con las
    # 387 de hoy y se rompe en silencio el dia que cambie el reparto de
    # estaciones, o en cualquier prueba con menos municipios.
    refs = set(municipios.values())
    def cuantas(d):
        return sum(1 for e in refs if e in hist[d] and completo(hist[d][e]))
    dias = sorted(hist)
    mejor = max((cuantas(d) for d in dias), default=0)
    cerrados = [d for d in dias if mejor and cuantas(d) >= mejor * 0.6]
    if not cerrados:
        sys.exit("Ningun dia completo todavia. Normal en la primera ejecucion.")
    ultimo = cerrados[-1]
    ventana = [(datetime.strptime(ultimo, "%Y-%m-%d").date() - timedelta(days=k)).isoformat()
               for k in range(7)]
    print("Ultimo dia cerrado: %s · ventana de 7 dias hasta esa fecha" % ultimo)

    salida, sin_dato = {}, 0
    for ine5, e in municipios.items():
        hoy_e = hist.get(ultimo, {}).get(e)
        if not hoy_e or not completo(hoy_e):
            sin_dato += 1
            continue
        dias_ok = [hist[d][e] for d in ventana
                   if d in hist and e in hist[d] and completo(hist[d][e])]
        salida[ine5] = {
            "dia": round(hoy_e[0], 1),
            "sem": round(sum(x[0] for x in dias_ok), 1),
            "sem_dias": len(dias_ok),          # cuantos de los 7 hay de verdad
            "lluvia7": sum(1 for x in dias_ok if x[0] >= 1.0),
            "racha": racha_sin_llover(hist, e, ultimo),
        }

    print("Municipios con dato: %d · sin dato: %d" % (len(salida), sin_dato))
    if len(salida) < len(municipios) * 0.5:
        # Publicar 200 de 999 dejaria la mitad de las fichas mudas sin avisar.
        print("AVISO: menos de la mitad de los municipios tienen dato.")

    os.makedirs("docs", exist_ok=True)
    with open(SALIDA, "w") as f:
        json.dump({"fecha": ultimo,
                   "generado": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                   "fuente": "AEMET OpenData · observación convencional",
                   "municipios": salida},
                  f, ensure_ascii=False, separators=(",", ":"))
    print("✓ %s · %d municipios · datos del %s" % (SALIDA, len(salida), ultimo))


if __name__ == "__main__":
    main()
