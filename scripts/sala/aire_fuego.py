"""Aire y fuego: focos de calor detectados por satélite, calidad del aire y superficie quemada.

Fuentes (docs/):
- incendios.json + historial_frp.json: detecciones VIIRS (Suomi NPP, NOAA-20, NOAA-21) de NASA FIRMS en tiempo casi
  real. Es una medida (anomalía térmica vista desde el satélite en ese punto), pero no dice qué arde: puede ser un
  incendio forestal, una quema agrícola o una fuente industrial. Por eso se habla de «focos de calor», nunca de
  incendios, y se apartan:
    · los puntos que se repiten casi a diario (fuentes fijas: centrales, fábricas, plantas solares),
    · lo detectado fuera de España o junto a la frontera (el fichero asigna a Galicia focos de Melgaço, en Portugal),
  y la provincia sale de la rejilla de límites provinciales de docs/caudal/provincias_rejilla.json, no del campo
  «comunidad» del fichero (que pone Usagre, en Badajoz, en Andalucía).
- calidad_aire.json: hoy viene de Open-Meteo / CAMS de Copernicus, que es un MODELO, no estaciones de medida. Con la
  regla del 17-10 (una cifra de un lugar solo sale si un organismo la midió allí) no se publica. El generador está
  listo para el día que el fichero traiga mediciones de estaciones (MITECO / EEA / redes autonómicas).
- superficie_incendios.json: EFFIS. Solo sale si el fichero está al día y no es la vista previa.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

SECCION = "aire"

# --------------------------------------------------------------------------- utilidades


def _madrid(R, iso_utc):
    d = datetime.fromisoformat(str(iso_utc).replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(R.MADRID)


def _hhmm(d):
    return f"{d.hour}:{d.minute:02d}"


def _cuando(R, d):
    """Hora para el ticker: «15:23» si es de hoy (hora de Madrid); si no, con el día delante: «Dom 18, 15:23»."""
    if d.date() == R.HOY:
        return _hhmm(d)
    return f"{R.DIAS[d.weekday()][:3].capitalize()} {d.day}, {_hhmm(d)}"


class _Rejilla:
    """Rejilla de 0,05° con el código INE de la provincia de cada celda (0 = fuera de España)."""

    def __init__(self, r):
        self.r = r
        self.g = base64.b64decode(r["g"])

    def celda(self, lat, lon):
        r = self.r
        i = int((r["lat0"] - lat) // r["d"])
        j = int((lon - r["lon0"]) // r["d"])
        if i < 0 or j < 0 or i >= r["nlat"] or j >= r["nlon"]:
            return None
        v = self.g[i * r["nlon"] + j]
        return r["cod"][v - 1] if v else None

    def entorno(self, lat, lon, radio):
        d = self.r["d"]
        return [self.celda(lat + a * d, lon + b * d) for a in range(-radio, radio + 1) for b in range(-radio, radio + 1)]


def _provincia_foco(rej, lat, lon):
    """(dentro_de_españa, cod_provincia | None). Canarias va por recuadro (la rejilla no la cubre)."""
    if 27.3 <= lat <= 29.6 and -18.4 <= lon <= -13.2:
        return True, ("35" if lon >= -16.0 else "38")
    if rej is None:
        return False, None
    # dentro de España con margen: las 25 celdas de alrededor (unos 5 km a cada lado) son españolas
    if any(c is None for c in rej.entorno(lat, lon, 2)):
        return False, None
    vec = rej.entorno(lat, lon, 1)
    return True, (vec[0] if len(set(vec)) == 1 else None)  # provincia solo si las 9 celdas coinciden


def _municipios(R):
    """nombre normalizado → código de provincia, de la lista de municipios españoles del observatorio."""
    m = R.leer(R.DOCS / "municipios.json", {}) or {}
    out = {}
    for x in m.get("items", []):
        cod = (x.get("code") or "")[:2]
        if cod in R.PROV:
            out.setdefault(R.H._norm(x.get("n")), cod)
    return out


def _barras(R, filas, nombre, titulo, unidad, pie, color=None):
    """Barras horizontales sencillas: filas = [(etiqueta, valor, destacada)]."""
    W, fila, ml, mr, mt = 640, 28, 190, 70, 10
    Hh = mt + fila * len(filas) + 14
    mx = max(v for _, v, _ in filas) or 1
    X = lambda v: ml + v / mx * (W - ml - mr)  # noqa: E731
    color = color or R.CALOR
    s = []
    for i, (et, v, dest) in enumerate(filas):
        y = mt + i * fila
        s.append(R._t(ml - 10, y + 18, et, 13.5, R.TINTA, "end", 600 if dest else 400))
        s.append(f'<rect x="{ml}" y="{y + 6}" width="{max(2.0, X(v) - ml):.1f}" height="16" fill="{color if dest else "#E3A487"}"></rect>')
        s.append(R._t(max(X(v), ml + 2) + 6, y + 18.5, f"{R.f1(v)}{unidad}", 13, R.TINTA if dest else R.GRIS, "start", 700 if dest else 500))
    svg = R._svg(W, Hh, titulo, s)
    return R.guardar_grafico(nombre, svg, [(et, v) for et, v, _ in filas], ["lugar", "valor"], titulo, [], pie)


# --------------------------------------------------------------------------- focos de calor (NASA FIRMS)

FUENTE_FIRMS = "NASA FIRMS (instrumento VIIRS de los satélites Suomi NPP, NOAA-20 y NOAA-21)"
SATELITES = "Los satélites Suomi NPP, NOAA-20 y NOAA-21 (instrumento VIIRS, datos de NASA FIRMS) detectaron"
QUE_ES = ("Un foco de calor es una anomalía térmica que ve el satélite al pasar: puede ser un incendio forestal, una quema "
          "agrícola u otra fuente de calor, y no mide por sí solo superficie quemada.")


def _focos(R, I, HF, rej, munis):
    if not I or not I.get("datos_ok") or not I.get("focos_individuales"):
        return []
    act = I.get("ultima_actualizacion")
    try:
        act_d = datetime.fromisoformat(act)
    except Exception:
        return []
    if act_d.tzinfo is None:
        act_d = act_d.replace(tzinfo=R.MADRID)
    if R.AHORA - act_d.astimezone(timezone.utc) > timedelta(hours=30):
        return []  # fichero viejo: no es noticia de hoy
    act_m = act_d.astimezone(R.MADRID)
    ventana = int(I.get("ventana_activa_horas") or 48)
    provincias_ccaa = {R.H._norm(R.nprov(c)) for c in R.PROV} | {R.H._norm(x.get("nombre")) for x in I.get("comunidades", [])}

    validos, fuera, fijos = [], 0, 0
    hace10 = (act_m.date() - timedelta(days=10)).isoformat()

    def _extranjero(f):
        lug = (f.get("lugar") or "").strip()
        nl_ = R.H._norm(lug)
        return bool(lug) and nl_ not in munis and nl_ not in provincias_ccaa

    # focos con un lugar que no es de España (p. ej. Melgaço, en Portugal, que el fichero mete en Galicia): fuera,
    # y con ellos los que están a menos de 5 km, que suelen ser el mismo fuego aunque el fichero no les ponga lugar
    ext = [(float(f["lat"]), float(f["lon"])) for f in I["focos_individuales"] if _extranjero(f)]
    for f in I["focos_individuales"]:
        try:
            lat, lon = float(f["lat"]), float(f["lon"])
        except Exception:
            continue
        lugar = (f.get("lugar") or "").strip()
        nl = R.H._norm(lugar)
        if _extranjero(f) or any(R.H._km((lat, lon), e) < 5 for e in ext):
            fuera += 1
            continue
        dentro, cod = _provincia_foco(rej, lat, lon)
        if not dentro:
            fuera += 1
            continue
        dias = {x.get("t", "")[:10] for x in HF.get(f.get("celda", ""), []) if x.get("t", "")[:10] >= hace10}
        if len(dias) >= 4:
            fijos += 1  # se repite casi a diario: fuente fija (industria, central, planta solar)
            continue
        cerca = lugar if (nl in munis and munis[nl] == cod and cod) else None
        validos.append({"lat": lat, "lon": lon, "frp": float(f.get("frp") or 0), "cod": cod, "cerca": cerca,
                        "t": _madrid(R, f["deteccion_utc"])})
    n = len(validos)
    if n == 0:
        return []

    por_prov = {}
    for v in validos:
        if v["cod"]:
            por_prov.setdefault(v["cod"], []).append(v)
    grupos = {}
    for v in validos:
        if v["cerca"]:
            grupos.setdefault((v["cod"], v["cerca"]), []).append(v)
    grupo = max(grupos.items(), key=lambda kv: len(kv[1])) if grupos else None
    frp_max = max(validos, key=lambda v: v["frp"])

    # ¿es noticia? Muchos focos, un grupo grande en un mismo sitio o una detección muy potente
    notable = n >= 20 or (grupo and len(grupo[1]) >= 8) or frp_max["frp"] >= 50
    puntos = 25 + min(20, n / 3) + (8 if grupo and len(grupo[1]) >= 10 else 0) + (15 if frp_max["frp"] >= 50 else 0) + (10 if n >= 100 else 0)
    if not notable:
        puntos = min(puntos, 25)  # solo sirve de soporte a las versiones provinciales

    ini = min(v["t"] for v in validos)
    fin = max(v["t"] for v in validos)
    hasta = f"en las {ventana} horas hasta las {_hhmm(act_m)} del {R.dia(act_m.date().isoformat())}"
    filas_prov = sorted(((R.nprov(c), len(vs)) for c, vs in por_prov.items()), key=lambda x: (-x[1], R.sin_tildes(x[0])))
    hechos = [R.hecho("focos_total", f"{SATELITES} {n} focos de calor en España {hasta}.",
                      FUENTE_FIRMS, [str(n), str(ventana), _hhmm(act_m)])]
    if filas_prov:
        hechos.append(R.hecho("focos_prov", "Por provincias: " + "; ".join(f"{p}, {k}" for p, k in filas_prov) + ".", FUENTE_FIRMS,
                              [str(k) for _, k in filas_prov]))
    if grupo and len(grupo[1]) >= 3:
        (gc, gl), gv = grupo
        gd = min(v["t"] for v in gv)
        hechos.append(R.hecho("focos_grupo", f"El grupo más numeroso, {len(gv)} focos, se detectó cerca de {gl} ({R.nprov(gc)}) el {R.dia(gd.date().isoformat())}.",
                              FUENTE_FIRMS, [str(len(gv))], lugar=gl, superlativo=True))
    if frp_max["frp"] >= 50:
        donde = f" cerca de {frp_max['cerca']} ({R.nprov(frp_max['cod'])})" if frp_max["cerca"] else (f" en la provincia de {R.nprov(frp_max['cod'])}" if frp_max["cod"] else "")
        hechos.append(R.hecho("focos_frp", f"La detección de mayor potencia, {R.f1(frp_max['frp'])} megavatios, fue{donde} a las {_hhmm(frp_max['t'])} del "
                              f"{R.dia(frp_max['t'].date().isoformat())}.", FUENTE_FIRMS, [R.f1(frp_max["frp"]), _hhmm(frp_max["t"])], superlativo=True))
    if fuera or fijos:
        partes = []
        if fuera:
            partes.append(f"{fuera} detecciones de fuera de España o de junto a la frontera")
        if fijos:
            partes.append(f"{fijos} de puntos que se repiten casi a diario, como los de instalaciones industriales" if fuera else
                          f"{fijos} detecciones de puntos que se repiten casi a diario, como los de instalaciones industriales")
        hechos.append(R.hecho("focos_excl", "No se cuentan " + ", ni ".join(partes) + ".", "calentamientoglobal.es", [str(fijos), str(fuera)]))
    hechos.append(R.hecho("focos_que_es", QUE_ES, FUENTE_FIRMS))

    if grupo and len(grupo[1]) >= 8:
        (gc, gl), gv = grupo
        tit = f"Los satélites detectan {n} focos de calor en España en {ventana} horas; {len(gv)} de ellos, cerca de {gl} ({R.nprov(gc)})"
    elif filas_prov:
        tit = f"Los satélites detectan {n} focos de calor en España en {ventana} horas, con {filas_prov[0][0]} a la cabeza"
    else:
        tit = f"Los satélites detectan {n} focos de calor en España en {ventana} horas"
    pl = {"titular": tit, "subtitulo": hechos[1]["dice"] if len(hechos) > 2 else "", "entradilla": hechos[0]["dice"],
          "cuerpo": [h["dice"] for h in hechos[1:]], "claves": [h["dice"] for h in hechos[:3]]}
    cifras = [{"n": str(n), "l": f"focos de calor detectados por satélite en España en {ventana} horas", "tono": "calor"}]
    if grupo and len(grupo[1]) >= 3:
        cifras.append({"n": str(len(grupo[1])), "l": f"cerca de {grupo[0][1]} ({R.nprov(grupo[0][0])})", "tono": "calor"})
    if filas_prov:
        cifras.append({"n": str(len(filas_prov)), "l": "provincias con al menos un foco asignado", "tono": "calor"})
    hid = f"{R.HOY.isoformat()}-focos-de-calor"
    h = R.historia("focos_calor", hid, "Fuego · detección por satélite", "calor", puntos, hechos, pl, cifras,
                   fuentes="NASA FIRMS (VIIRS Suomi NPP, NOAA-20 y NOAA-21, tiempo casi real)",
                   metodo=(f"Detecciones de las {ventana} horas anteriores a la actualización. La provincia sale de los límites provinciales "
                           "(rejilla de 0,05°) y solo se asigna si el foco no está junto a un límite; se apartan los focos de puntos detectados "
                           "4 días o más de los últimos 10 (fuentes fijas) y los de fuera de España o a unos 5 km de la frontera."),
                   limites=["Un foco de calor no es un incendio confirmado: también lo dan las quemas agrícolas y otras fuentes de calor.",
                            "Las nubes y el humo espeso ocultan focos; un mismo fuego puede dar varios focos.",
                            "Los focos a menos de unos 5 km de un límite provincial cuentan en el total de España pero no en ninguna provincia."],
                   pagina="https://calentamientoglobal.es/incendios-forestales-en-espana-mapa/")
    h["seccion"] = SECCION
    h["tono"] = "calor"
    if filas_prov:
        h["grafico"] = _barras(R, [(p, k, i == 0) for i, (p, k) in enumerate(filas_prov[:12])], f"{hid}", "Focos de calor por provincia",
                               "", f"Focos de calor detectados por satélite (instrumento VIIRS, NASA FIRMS) {hasta}, por provincia. No se cuentan los de fuentes fijas ni los de "
                               "junto a la frontera o a un límite provincial. Fuente: NASA FIRMS. Cálculo: calentamientoglobal.es.")
    if grupo and len(grupo[1]) >= 8:
        h["ultima_hora"] = [{"hora": _cuando(R, min(v["t"] for v in grupo[1])), "tono": "calor",
                             "texto": f"Satélites: {len(grupo[1])} focos de calor cerca de {grupo[0][1]} ({R.nprov(grupo[0][0])})"}]

    # versiones provinciales
    for cod, vs in por_prov.items():
        m = len(vs)
        fuerte = max(v["frp"] for v in vs) >= 50
        if m < 3 and not fuerte:
            continue
        P = R.nprov(cod)
        hv = [R.hecho("focos_p", f"{SATELITES} {m} focos de calor en la provincia de {P} {hasta}.",
                      FUENTE_FIRMS, [str(m), str(ventana), _hhmm(act_m)])]
        gp = {}
        for v in vs:
            if v["cerca"]:
                gp.setdefault(v["cerca"], []).append(v)
        gpo = sorted(gp.items(), key=lambda kv: -len(kv[1]))
        if gpo:
            partes = []
            for lug, gv in gpo[:3]:
                t0 = min(v["t"] for v in gv)
                partes.append(f"{len(gv)} cerca de {lug} el {R.dia(t0.date().isoformat())}")
            hv.append(R.hecho("focos_p_lugares", "De ellos, " + R.lista_y(partes) + ".", FUENTE_FIRMS, [str(len(gv)) for _, gv in gpo[:3]]))
        vmax = max(vs, key=lambda v: v["frp"])
        if fuerte:
            hv.append(R.hecho("focos_p_frp", f"La detección de mayor potencia en la provincia, {R.f1(vmax['frp'])} megavatios, fue a las {_hhmm(vmax['t'])} del "
                              f"{R.dia(vmax['t'].date().isoformat())}.", FUENTE_FIRMS, [R.f1(vmax["frp"]), _hhmm(vmax["t"])], superlativo=True))
        hv.append(R.hecho("focos_p_nac", f"En toda España fueron {n} focos en ese mismo periodo.", FUENTE_FIRMS, [str(n)]))
        hv.append(R.hecho("focos_que_es", QUE_ES, FUENTE_FIRMS))
        if gpo and len(gpo[0][1]) >= 3:
            tv = f"Los satélites detectan {m} focos de calor en {P}, {len(gpo[0][1])} de ellos cerca de {gpo[0][0]}"
            if len(gpo[0][1]) == m:
                tv = f"Los satélites detectan {m} focos de calor cerca de {gpo[0][0]} ({P})"
        else:
            tv = f"Los satélites detectan {m} focos de calor en la provincia de {P} en {ventana} horas"
        plv = {"titular": tv, "subtitulo": hv[1]["dice"] if len(hv) > 3 else "", "entradilla": hv[0]["dice"],
               "cuerpo": [x["dice"] for x in hv[1:]], "claves": [x["dice"] for x in hv[:2]]}
        cif = [{"n": str(m), "l": f"focos de calor en {P} en {ventana} horas", "tono": "calor"}]
        if gpo and len(gpo[0][1]) >= 3:
            cif.append({"n": str(len(gpo[0][1])), "l": f"cerca de {gpo[0][0]}", "tono": "calor"})
        h["provincias"][cod] = {"provincia": P, "slug": R.PROV[cod][1], "hechos": hv, "plantilla": plv, "cifras": cif,
                                "puntos": round(35 + min(15, m) + (10 if gpo and len(gpo[0][1]) >= 10 else 0) + (15 if fuerte else 0), 1)}
    if not notable and not h["provincias"]:
        return []
    return [h]


# --------------------------------------------------------------------------- calidad del aire

_MODELO = ("cams", "open-meteo", "modelo", "previsión", "prevision")
_GUIA = {"pm25": ("PM2,5", 15), "pm10": ("PM10", 45), "no2": ("NO2", 25), "o3": ("ozono", 100)}


def _calidad_aire(R, C):
    """Solo con mediciones de estaciones. Con el modelo CAMS (lo que hay hoy) no sale nada."""
    if not C or not C.get("ciudades"):
        return []
    fuente = str(C.get("fuente") or "")
    if any(x in fuente.lower() for x in _MODELO):
        return []
    try:
        act = datetime.fromisoformat(C["ultima_actualizacion"])
    except Exception:
        return []
    if act.tzinfo is None:
        act = act.replace(tzinfo=R.MADRID)
    if R.AHORA - act.astimezone(timezone.utc) > timedelta(hours=30):
        return []
    fecha = act.astimezone(R.MADRID).date().isoformat()
    malas = []
    for c in C["ciudades"]:
        cod = R.H.cod_provincia(c.get("provincia"))
        if not cod:
            continue
        sobre = [(k, float(c[k])) for k in _GUIA if c.get(k) is not None and float(c[k]) > _GUIA[k][1]]
        if sobre:
            k, v = max(sobre, key=lambda kv: kv[1] / _GUIA[kv[0]][1])
            malas.append({"ciudad": c["nombre"], "cod": cod, "k": k, "v": v, "sahara": bool(c.get("sahariano"))})
    sahara = bool(C.get("episodio_sahariano")) and int(C.get("ciudades_saharianas") or 0) > 0
    if not malas and not sahara:
        return []
    malas.sort(key=lambda m: -m["v"] / _GUIA[m["k"]][1])
    total = int(C.get("ciudades_con_datos") or len(C["ciudades"]))
    hechos = [R.hecho("aire_n", f"{len(malas)} de las {total} ciudades que sigue el observatorio superaron el {R.dia(fecha)} algún valor guía de "
                      f"calidad del aire de la OMS, según {fuente}.", fuente, [str(len(malas)), str(total)])]
    for i, m in enumerate(malas[:5]):
        nom, lim = _GUIA[m["k"]]
        hechos.append(R.hecho(f"aire_c{i}", f"En {m['ciudad']}, {nom}: {R.f1(m['v'])} microgramos por metro cúbico, frente al valor guía de la OMS de {lim}.",
                              fuente, [R.f1(m["v"]), str(lim)], lugar=m["ciudad"], liga=[]))
    if sahara:
        hechos.append(R.hecho("aire_sahara", f"Hubo polvo del Sáhara en {int(C['ciudades_saharianas'])} de esas {total} ciudades.", fuente,
                              [str(int(C["ciudades_saharianas"]))]))
    hechos.append(R.hecho("aire_oms", "Los valores guía de la OMS de 2021 son 15 microgramos por metro cúbico de PM2,5, 45 de PM10, 25 de NO2 y 100 de ozono.",
                          "OMS", ["15", "45", "25", "100"]))
    if malas:
        tit = f"{len(malas)} ciudades superan los valores guía de calidad del aire de la OMS; {malas[0]['ciudad']}, a la cabeza"
    else:
        tit = f"Polvo del Sáhara en {int(C['ciudades_saharianas'])} de las {total} ciudades que sigue el observatorio"
    pl = {"titular": tit, "subtitulo": hechos[1]["dice"] if len(hechos) > 2 else "", "entradilla": hechos[0]["dice"],
          "cuerpo": [h["dice"] for h in hechos[1:]], "claves": [h["dice"] for h in hechos[:3]]}
    hid = f"{R.HOY.isoformat()}-calidad-del-aire"
    h = R.historia("calidad_aire", hid, "Aire · calidad del aire", "calor", 40 + min(30, 4 * len(malas)) + (10 if sahara else 0), hechos, pl,
                   [{"n": str(len(malas)), "l": "ciudades por encima de algún valor guía de la OMS", "tono": "calor"}],
                   fuentes=fuente, metodo="Concentraciones medidas comparadas con los valores guía diarios de la OMS de 2021.",
                   limites=["Los valores guía de la OMS no son los límites legales de la normativa europea, que son más altos."],
                   pagina="https://calentamientoglobal.es/calidad-del-aire/")
    h["seccion"] = SECCION
    if malas:
        h["grafico"] = _barras(R, [(m["ciudad"], round(m["v"] / _GUIA[m["k"]][1] * 100), i == 0) for i, m in enumerate(malas[:12])],
                               hid, "Concentración frente al valor guía de la OMS", " %",
                               f"Contaminante que más supera su valor guía en cada ciudad, en % de ese valor. Fuente: {fuente}. Cálculo: calentamientoglobal.es.")
    for m in malas:
        if m["cod"] in h["provincias"]:
            continue
        nom, lim = _GUIA[m["k"]]
        hv = [R.hecho("aire_p", f"En {m['ciudad']}, la concentración de {nom} fue el {R.dia(fecha)} de {R.f1(m['v'])} microgramos por metro cúbico, "
                      f"por encima del valor guía de la OMS ({lim}), según {fuente}.", fuente, [R.f1(m["v"]), str(lim)], lugar=m["ciudad"]),
              hechos[0], hechos[-1]]
        h["provincias"][m["cod"]] = {"provincia": R.nprov(m["cod"]), "slug": R.PROV[m["cod"]][1], "hechos": hv,
                                     "plantilla": {"titular": f"{m['ciudad']} supera el valor guía de la OMS de {nom}: {R.f1(m['v'])} microgramos por metro cúbico",
                                                   "subtitulo": hechos[0]["dice"], "entradilla": hv[0]["dice"], "cuerpo": [hv[1]["dice"], hv[2]["dice"]],
                                                   "claves": [hv[0]["dice"]]},
                                     "cifras": [{"n": R.f1(m["v"]), "l": f"µg/m³ de {nom} en {m['ciudad']}", "tono": "calor"}], "puntos": 55}
    return [h]


# --------------------------------------------------------------------------- superficie quemada (EFFIS)


def _superficie(R, S):
    if not S or "VISTA PREVIA" in str(S.get("_comment", "")).upper():
        return []
    t = S.get("temporada_actual") or {}
    try:
        a_fecha = datetime.fromisoformat(str(t["a_fecha"])[:10]).date()
        ha = float(t["total_ha"])
    except Exception:
        return []
    if (R.HOY - a_fecha).days > 21 or t.get("aprox"):
        return []
    fuente = S.get("fuente_actual") or "EFFIS"
    anio = int(t.get("anio") or a_fecha.year)
    hist = [x for x in S.get("historico_nacional", []) if not x.get("aprox") and not x.get("parcial") and x.get("anio") != anio]
    hechos = [R.hecho("sup_total", f"En {anio} han ardido en España {R.miles(ha)} hectáreas hasta el {R.dia(a_fecha.isoformat())}, según {fuente}.",
                      fuente, [str(anio), R.miles(ha)])]
    if t.get("media_misma_fecha_ha"):
        med = float(t["media_misma_fecha_ha"])
        hechos.append(R.hecho("sup_media", f"La media a la misma fecha es de {R.miles(med)} hectáreas.", fuente, [R.miles(med)]))
    if t.get("n_incendios"):
        hechos.append(R.hecho("sup_n", f"El sistema cuenta {int(t['n_incendios'])} incendios cartografiados este año.", fuente, [str(int(t["n_incendios"]))]))
    peores = sorted(hist, key=lambda x: -x["ha"])[:3]
    if peores:
        hechos.append(R.hecho("sup_hist", "Años completos con más superficie quemada de la serie: " + "; ".join(f"{x['anio']}, {R.miles(x['ha'])} hectáreas" for x in peores) + ".",
                              fuente, [str(x["anio"]) for x in peores] + [R.miles(x["ha"]) for x in peores], superlativo=True))
    tit = f"En {anio} han ardido {R.miles(ha)} hectáreas en España, según {fuente}"
    if t.get("media_misma_fecha_ha"):
        tit += f"; la media a la misma fecha es de {R.miles(float(t['media_misma_fecha_ha']))}"
    pl = {"titular": tit, "subtitulo": hechos[1]["dice"] if len(hechos) > 1 else "", "entradilla": hechos[0]["dice"],
          "cuerpo": [h["dice"] for h in hechos[1:]] or [hechos[0]["dice"]], "claves": [h["dice"] for h in hechos[:2]]}
    ratio = ha / float(t["media_misma_fecha_ha"]) if t.get("media_misma_fecha_ha") else 1
    hid = f"{a_fecha.isoformat()}-superficie-quemada"
    h = R.historia("superficie_quemada", hid, "Fuego · superficie quemada", "calor", 30 + (20 if ratio >= 2 else 10 if ratio >= 1.3 else 0),
                   hechos, pl, [{"n": R.miles(ha), "l": f"hectáreas quemadas en España en {anio} hasta el {R.dia(a_fecha.isoformat(), semana=False)}", "tono": "calor"}],
                   fuentes=fuente, metodo="Superficie cartografiada por EFFIS (incendios a partir de unas 30 hectáreas).",
                   limites=["EFFIS cartografía los incendios grandes; los pequeños no entran en el total."],
                   pagina="https://calentamientoglobal.es/superficie-quemada-incendios-espana/")
    h["seccion"] = SECCION
    h["fecha"] = a_fecha.isoformat()
    if hist:
        filas = [(str(x["anio"]), x["ha"], False) for x in sorted(hist, key=lambda x: x["anio"])[-10:]] + [(f"{anio} (hasta {a_fecha.day}/{a_fecha.month})", ha, True)]
        h["grafico"] = _barras(R, filas, hid, "Superficie quemada en España por año", " ha", f"Hectáreas por año. Fuente: {fuente}. Cálculo: calentamientoglobal.es.")
    for slug, v in (t.get("provincias") or {}).items():
        cod = R.H.cod_provincia(slug)
        if not cod or not v:
            continue
        P = R.nprov(cod)
        hv = [R.hecho("sup_p", f"En la provincia de {P} han ardido {R.miles(v)} hectáreas en {anio} hasta el {R.dia(a_fecha.isoformat())}, según {fuente}.",
                      fuente, [R.miles(v), str(anio)]), hechos[0]]
        h["provincias"][cod] = {"provincia": P, "slug": R.PROV[cod][1], "hechos": hv,
                                "plantilla": {"titular": f"En {anio} han ardido {R.miles(v)} hectáreas en {P}, según {fuente}", "subtitulo": "",
                                              "entradilla": hv[0]["dice"], "cuerpo": [hv[1]["dice"]], "claves": [hv[0]["dice"]]},
                                "cifras": [{"n": R.miles(v), "l": f"hectáreas quemadas en {P} en {anio}", "tono": "calor"}], "puntos": 45}
    return [h]


# --------------------------------------------------------------------------- entrada


def generar(R, D):
    out = []
    try:
        rej = _Rejilla(R.leer(R.DOCS / "caudal" / "provincias_rejilla.json"))
    except Exception:
        rej = None
    pasos = (
        lambda: _focos(R, R.leer(R.DOCS / "incendios.json", {}) or {}, R.leer(R.DOCS / "historial_frp.json", {}) or {}, rej, _municipios(R)),
        lambda: _calidad_aire(R, R.leer(R.DOCS / "calidad_aire.json", {}) or {}),
        lambda: _superficie(R, R.leer(R.DOCS / "superficie_incendios.json", {}) or {}),
    )
    for i, paso in enumerate(pasos):
        try:
            out.extend(paso() or [])
        except Exception as e:  # noqa: BLE001
            R.LOG.append(f"aire_fuego paso {i}: {type(e).__name__}: {e}")
    return out
