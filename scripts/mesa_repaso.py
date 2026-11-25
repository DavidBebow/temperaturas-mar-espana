#!/usr/bin/env python3
"""
Repaso de 60 días de la mesa de redacción (25-11-2026, chat 1).

Reconstruye qué habría abierto /prensa/ cada día del 27-09 al 25-11-2026 con agrupación, escala única y criterio:
  · marcos grandes desde la serie validada de AEMET de las capitales (archivo/aemet_diario), con 5 días de retraso;
  · récords del mes en las mismas estaciones (≥ 40 años), con 1 día de retraso (el detector de récords de la web es del día);
  · lo que la web publicó ese día: docs/prensa/hallazgos.json (desde el 11-10) y docs/prensa/noticias/hoy.json (desde el 18-10),
    sacados de la historia de git (`--hist` con los JSON ya extraídos, uno por día, el último commit antes de las 14:00 UTC);
  · las historias de la prueba en seco del almacén que sobreviven a las reglas nuevas (estación primero, sin umbrales absolutos
    en reanálisis), con su retraso real (estaciones +5 días, Monitor el mismo día, ERA5-Land +24).
Uso: python scripts/mesa_repaso.py --hist DIR --desde 2026-09-27 --hasta 2026-11-25 --salida repaso.json
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date, timedelta
from pathlib import Path

import mesa_redaccion as M

# Prueba en seco del almacén (claude/detectores-almacen-reglas-y-calibracion-2026-11-25.md, §7) tras las reglas del 25-11:
# fuera las de reanálisis de capital en provincias con estación de AEMET larga y las R01 de estaciones de capital (las cubre
# marcos_grandes con la serie completa). (fecha del dato, retraso, regla, ámbito, lugares, titular, puesto, de, fuente, territorios)
ALMACEN = [
    ("2026-10-26", 7, "R05", "nacional", 21, "El año hidrológico parte España en dos: 10 capitales con más del 150 % de su lluvia normal y 11 con menos del 50 % (reanálisis)", None, None, "reanalisis", []),
    ("2026-10-29", 5, "R01", "provincial", 1, "La estación de AEMET de Ponferrada: lo que va de octubre, el más seco en 73 años (2,0 mm; récord anterior 6,1 en 1985)", 1, 73, "estacion", ["León"]),
    ("2026-10-29", 7, "R07", "nacional", 4, "En 4 capitales, los últimos 90 días han sido de los más cálidos y a la vez de los más secos de su serie para esta fecha (reanálisis): Donostia, Pamplona, Cádiz, Huelva", None, None, "reanalisis", ["San Sebastián", "Pamplona", "Cádiz", "Huelva"]),
    ("2026-10-30", 7, "R07", "nacional", 4, "En 4 capitales, los últimos 90 días han sido de los más cálidos y a la vez de los más secos de su serie para esta fecha (reanálisis): Vitoria, Logroño, Córdoba, Badajoz", None, None, "reanalisis", ["Vitoria", "Logroño", "Córdoba", "Badajoz"]),
    ("2026-10-31", 24, "R02", "provincial", 24, "En 24 municipios de Tarragona, 65.143 habitantes, octubre de 2026 ha sido el más lluvioso desde 1971 (reanálisis ERA5-Land)", 1, 55, "reanalisis", ["Tarragona"]),
    ("2026-10-31", 5, "R03", "provincial", 1, "La estación de AEMET de Pantano El Vado lleva 7 días seguidos con la máxima 4 °C o más por encima de lo normal: nunca había habido una racha así un 31 de octubre en 63 años", 1, 63, "estacion", ["Guadalajara"]),
    ("2026-11-01", 5, "R01", "provincial", 1, "La estación de AEMET de Alcantarilla, Base Aérea: lo que va de 2026 iguala el de noches más cálidas en 85 años (14,64 °C de media de las mínimas, como en 2025)", 2, 85, "estacion", ["Murcia"]),
    ("2026-11-01", 24, "R10", "provincial", 18, "227.674 personas en 18 municipios tuvieron el 1 de noviembre una lluvia de las que caen un día cada mil en su celda (Santa Cruz de Tenerife, reanálisis ERA5-Land)", None, None, "reanalisis", ["Santa Cruz de Tenerife"]),
    ("2026-11-02", 5, "R03", "provincial", 1, "La estación de AEMET de Valladolid Aeropuerto lleva 8 días seguidos con la máxima 4 °C o más por encima de lo normal: nunca había habido una racha así un 2 de noviembre en 85 años", 1, 85, "estacion", ["Valladolid"]),
    ("2026-11-03", 7, "R07", "nacional", 4, "En 4 capitales, los últimos 90 días han sido de los más cálidos y a la vez de los más secos de su serie para esta fecha (reanálisis): Bilbao, Santander, Sevilla, Ourense", None, None, "reanalisis", ["Bilbao", "Santander", "Sevilla", "Ourense"]),
    ("2026-11-05", 5, "R03", "nacional", 4, "4 estaciones de AEMET llevan 3 días seguidos de helada: nunca había habido una racha así un 5 de noviembre en sus series (la más larga, Valle de Hecho, 44 años; también Ponferrada, Soria y Foronda)", 1, 44, "estacion", ["Huesca", "León", "Soria", "Vitoria"]),
    ("2026-11-06", 5, "R03", "provincial", 1, "La estación de AEMET de Santa Cruz de Tenerife lleva 137 noches tropicales seguidas: nunca había habido una racha así un 6 de noviembre en 95 años", 1, 95, "estacion", ["Santa Cruz de Tenerife"]),
    ("2026-11-07", 0, "R04", "nacional", 6, "6 provincias en sequía severa o extrema con los embalses por encima del 65 %: el agua es del año pasado", None, None, "nacional", ["Huelva", "Cádiz", "Gipuzkoa", "Pontevedra", "A Coruña", "Ourense"]),
    ("2026-11-07", 0, "R05", "nacional", 24, "España, partida en dos: 6 provincias por encima del 175 % de su lluvia y 18 por debajo del 40 % en el año hidrológico (Tarragona 451 %, Huelva 0 %)", None, None, "nacional", []),
    ("2026-11-07", 0, "R06", "nacional", 4, "Sequía severa en Pontevedra, donde lo normal son 1.543 mm al año; también en A Coruña, Gipuzkoa y Ourense", None, None, "nacional", ["Pontevedra", "A Coruña", "Gipuzkoa", "Ourense"]),
    ("2026-11-09", 7, "R07", "provincial", 1, "Lugo: los últimos 90 días han sido de los más cálidos y a la vez de los más secos de su serie para esta fecha (reanálisis)", None, None, "reanalisis", ["Lugo"]),
]

RUTINA_NOTICIAS = {"embalses", "lluvia_semana", "lluvia_sequia", "otono_pluviometros", "mar_boyas", "mediterraneo", "prevision_calor",
                   "prevision_lluvia", "prevision_frio", "rios", "focos_calor", "episodio", "temperatura_global", "hielo_marino", "glaciares"}
CONTEXTO_NOTICIAS = {"torrencial", "danas_lluvia", "dana_largo", "temporada", "temporada_tropical", "sequia_calida", "mar_y_dana",
                     "verano_largo", "otono_serie", "cerca_record"}


def _pob_provs(cods):
    m = M.maestro()
    return sum(m["pob_prov"].get(f"prov:{c}", 0) for c in cods)


def _mm(txt):
    v = [float(x.replace(".", "").replace(",", ".")) for x in re.findall(r"(\d[\d.]*,?\d*)\s*(?:litros|mm|l/m)", txt or "")]
    return max(v) if v else 0.0


def de_noticias(hoy_json: dict, dia: date) -> list[dict]:
    """Historias de docs/prensa/noticias/hoy.json del día: rutina → «Datos del día», análisis → «Contexto», exclusivas → noticia
    (con serie corta, que es lo que son casi siempre), y el aviso rojo o ≥ 200 mm en un día → emergencia."""
    out = []
    for h in hoy_json.get("historias", []):
        tipo = h.get("tipo")
        txt = " ".join([h.get("titular") or "", h.get("subtitulo") or "",
                        " ".join(str(c.get("n") or "") + " " + str(c.get("l") or "") for c in (h.get("cifras") or []) if isinstance(c, dict))])
        rojo = "aviso rojo" in txt.lower() or "avisos rojos" in txt.lower()
        mm = _mm(txt)
        pv = h.get("provincias") or {}
        cods = list(pv.keys()) if isinstance(pv, dict) else [str(x) for x in pv]
        r = {"pob": _pob_provs(cods) or None, "n_lugares": max(1, len(cods)), "ambito": "nacional" if len(cods) >= 3 else "provincial",
             "fuente": "sin_serie", "puesto": None, "n_anios": None, "edad": 0, "edad_disponible": 0, "calidad": "tiempo_real",
             "novedad": 1.0, "invalidar": True, "plantilla": True, "titular": h.get("titular", ""), "seccion": "datos"}
        if tipo == "episodio" and (rojo or mm >= 200):
            r.update(emergencia=True, seccion="noticia", fuente="sin_serie", calidad="oficial", puesto=1, n_anios=None, pob=r["pob"])
        elif tipo in ("exclusiva", "record"):
            anio = re.findall(r"desde (\d{4})", txt)
            otonos = re.findall(r"en (\d+) otoños", txt)
            n = (dia.year - int(anio[0])) if anio else (int(otonos[0]) if otonos else None)
            r.update(seccion="noticia", puesto=1, n_anios=n, fuente="estacion" if (n or 0) >= M.ANIOS_SERIE_LARGA else "corta",
                     calidad="tiempo_real" if tipo == "exclusiva" else "validado")
        elif tipo in CONTEXTO_NOTICIAS:
            r["seccion"] = "contexto"
        out.append({"origen": "noticias", "tipo_mesa": "emergencia" if r.get("emergencia") else tipo, "titular": h.get("titular", ""),
                    "fecha_dato": str(dia), "clave": {"indicador": f"noticia:{tipo}", "territorio": (h.get("clave") or "")[:40],
                                                       "periodo": str(dia) if tipo == "episodio" else (h.get("clave") or tipo)},
                    "cifra": (h.get("cifras") or [{}])[0].get("n") if isinstance((h.get("cifras") or [None])[0], dict) else None, "rasgos": r, "puntos_web": h.get("puntos")})
    return out


def de_hallazgos(hall: dict, dia: date) -> list[dict]:
    """enviables + locales de hallazgos.json del día, agrupados por la mesa y con sus rasgos. Lo de requiere_revision no entra."""
    lista = [h for h in (hall.get("enviables") or []) + (hall.get("locales") or []) if not h.get("requiere_revision")
             and not str(h.get("serie", "")).startswith("almacen_")]
    out = []
    for h in M.agrupar(lista):
        r = M.rasgos(h, dia)
        if h.get("serie") == "capitales" and h.get("tipo") in ("record_fecha", "record_absoluto") and h.get("ambito") != "nacional":
            r["seccion"] = "noticia"
        h["rasgos"] = r
        h["origen"] = "hallazgos"
        out.append(h)
    return out


def de_almacen(dia: date) -> list[dict]:
    out = []
    for (fd, lag, regla, amb, n, tit, puesto, de, fuente, terr) in ALMACEN:
        f = date.fromisoformat(fd)
        disp = f + timedelta(days=lag)
        if disp != dia:
            continue
        pob = sum(M.poblacion(t) or 0 for t in terr) or (M.POB_ESPANA if amb == "nacional" else None)
        r = {"pob": pob, "n_lugares": n, "ambito": amb, "fuente": fuente, "puesto": puesto, "n_anios": de, "edad": (dia - f).days,
             "edad_disponible": 0, "calidad": "validado" if fuente == "estacion" else ("oficial" if fuente == "nacional" else "reanalisis"),
             "novedad": 1.0, "invalidar": True, "plantilla": True, "titular": tit, "seccion": "noticia"}
        if regla in ("R05", "R07"):
            r["seccion"] = "contexto"      # mapa de contrastes y compuestos de reanálisis: análisis de fondo
        out.append({"origen": "almacen", "tipo_mesa": f"almacen_{regla}", "titular": tit, "fecha_dato": fd,
                    "clave": {"indicador": f"almacen:{regla}:{tit[:30]}", "territorio": ",".join(terr), "periodo": fd}, "cifra": tit, "rasgos": r})
    return out


LAG = 8   # días entre la fecha del dato validado de AEMET y su llegada al archivo (medido el 25-11: la mayoría acaba el 16-17)


def de_mesa(dia: date) -> list[dict]:
    """Marcos grandes (dato validado hasta dia − 5) y récords del mes (dato de ayer) en las estaciones de las capitales."""
    out = []
    marcos = M.marcos_grandes(dia, lag=LAG)
    nacionales = {(h["periodo"], h["cola"], h["clave"]["periodo"]) for h in marcos if h["tipo_mesa"] == "marco_nacional"}
    for h in marcos:
        f = date.fromisoformat(h["fecha_dato"])
        es_version = h["tipo_mesa"] == "marco_capital" and any(k[0] == h["periodo"] and k[1] == h["cola"] for k in nacionales)
        pob = sum(M.poblacion(t) or 0 for t in h.get("_miembros_territorios", [])) if h["ambito"] == "nacional" else M.poblacion(h["territorio"])
        r = {"pob": pob, "n_lugares": len(h.get("_miembros_territorios") or [1]), "ambito": h["ambito"], "fuente": "estacion",
             "puesto": h["comparacion"]["puesto"], "n_anios": h["comparacion"]["de"], "edad": (dia - f).days,
             "edad_disponible": (dia - date.fromisoformat(h["fecha_disponible"])).days, "calidad": "validado", "novedad": 1.0,
             "invalidar": h["invalidar"], "plantilla": True, "titular": h["titular"], "periodo_validado": True,
             "seccion": "version" if es_version else "noticia"}
        h["rasgos"], h["origen"] = r, "mesa"
        out.append(h)
    recs = M.records_estacion(dia - timedelta(days=1)) + M.rachas_estacion(dia - timedelta(days=LAG))
    for h in M.agrupar(recs):
        if h.get("agregada_por_mesa"):
            n = len(h["versiones_provinciales"])
            p = h["versiones_provinciales"][0]
            mes = M.MESES[date.fromisoformat(p["fecha_dato"]).month - 1]
            if p["tipo_mesa"] == "racha":
                h["titular"] = (f"{n} estaciones de AEMET con 40 años o más de serie viven la racha sin lluvia más larga para esta fecha: "
                                f"{M._lista([v['territorio'] for v in h['versiones_provinciales']])}")
            else:
                var = {"calor": "máxima más alta", "noches": "mínima más alta", "lluvioso": "lluvia de un día más alta"}[p["cola"]]
                h["titular"] = (f"{n} estaciones de AEMET baten el {date.fromisoformat(p['fecha_dato']).day} de {mes} su {var} de cualquier {mes} "
                                f"en series de AEMET de 40 años o más: {M._lista([v['territorio'] for v in h['versiones_provinciales']])}")
            h["comparacion"] = {"puesto": 1, "de": min(v["comparacion"]["de"] for v in h["versiones_provinciales"])}
        r = M.rasgos(h, dia)
        r.update(fuente="estacion", calidad="validado", seccion="noticia", edad_disponible=0, n_anios=h["comparacion"]["de"], puesto=1,
                 periodo_validado=h.get("tipo_mesa") == "racha" or bool(h.get("versiones_provinciales") and h["versiones_provinciales"][0].get("tipo_mesa") == "racha"))
        if h.get("agregada_por_mesa"):
            r["pob"] = sum(M.poblacion(v["territorio"]) or 0 for v in h["versiones_provinciales"])
        h["rasgos"], h["origen"] = r, "mesa"
        out.append(h)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hist", required=True)
    ap.add_argument("--desde", default="2026-09-27")
    ap.add_argument("--hasta", default="2026-11-25")
    ap.add_argument("--salida", default="repaso.json")
    ap.add_argument("--lag", type=int, default=LAG)
    a = ap.parse_args()
    globals()["LAG"] = a.lag
    H = Path(a.hist)
    d0, d1 = date.fromisoformat(a.desde), date.fromisoformat(a.hasta)
    emitidos = {}
    dias = []
    d = d0
    while d <= d1:
        cand = de_mesa(d) + de_almacen(d)
        fh, fn = H / "hall" / f"{d}.json", H / "hoy" / f"{d}.json"
        if fh.exists():
            cand += de_hallazgos(json.loads(fh.read_text()), d)
        if fn.exists():
            cand += de_noticias(json.loads(fn.read_text()), d)
        versiones = [c for c in cand if c["rasgos"].get("seccion") == "version"]
        cand = [c for c in cand if c["rasgos"].get("seccion") != "version"]
        p = M.portada(cand, d, emitidos)

        def res(c):
            if not c:
                return None
            return {"titular": c.get("titular"), "puntos": c["puntuacion"]["puntos"], "origen": c.get("origen"), "tipo": c.get("tipo_mesa") or c.get("tipo"),
                    "ambito": c["rasgos"].get("ambito"), "puertas": c["puntuacion"]["puertas"],
                    "componentes": {k: c["puntuacion"][k] for k in ("A", "R", "N", "F", "Q")}, "puntos_web": c.get("puntos_web")}
        dias.append({"fecha": str(d), "historia_del_dia": res(p["historia_del_dia"]), "mas": [res(c) for c in p["mas"]],
                     "datos_del_dia": [res(c) for c in p["datos_del_dia"][:6]], "contexto": [res(c) for c in p["contexto"][:5]],
                     "n_versiones_provinciales": len(versiones), "fuentes": {"hallazgos": fh.exists(), "noticias": fn.exists()}})
        d += timedelta(days=1)
    Path(a.salida).write_text(json.dumps({"dias": dias}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    sin = sum(1 for x in dias if not x["historia_del_dia"])
    print(f"{len(dias)} días · {sin} sin noticia")
    for x in dias:
        h = x["historia_del_dia"]
        print(x["fecha"], f"[{h['puntos']:5.1f}] {h['titular'][:130]}" if h else "— sin noticia —", "| +", len(x["mas"]))


if __name__ == "__main__":
    main()
