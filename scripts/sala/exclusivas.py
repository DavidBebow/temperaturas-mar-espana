"""La exclusiva del día: en cada provincia, el dato más fuerte que solo da el observatorio, con titular de periódico.

No es una fuente nueva: junta lo que ya está medido y comprobado y elige, provincia a provincia, lo que un periodista
de allí querría publicar hoy. Por orden de fuerza:

1. dia_record · Una estación de AEMET vive en este episodio el día de otoño más lluvioso de sus registros (todos sus
   otoños con dato desde 1991 o desde que empieza): el dossier del episodio (docs/prensa/episodios/<id>.json) lo
   calcula contra los valores diarios de AEMET (archivo/otonio). Con los tres días seguidos y el otoño acumulado.
2. otono_record · Una estación ya lleva este otoño más lluvia que en el otoño completo más lluvioso de su serie
   (otonio_municipios.json para 2026; archivo/otonio para los otoños 1991-2025 con al menos 85 días con dato).
3. verano_record · 2026 ya es el año con más días de verano de la serie de la estación (docs/prensa/analisis/
   verano.json, series diarias de AEMET).

Una historia con versión por provincia (la exclusiva de cada una) y una nacional (la más fuerte de todas, con las
demás como contexto). Pesa más que las demás historias de la provincia: abre su sala.
"""
from __future__ import annotations

import datetime
import gzip
import json
import math

SECCION = "ultima"
FUENTE_OBS = "AEMET OpenData (observación horaria y valores climatológicos diarios); cálculo de calentamientoglobal.es"
FUENTE_D = "AEMET OpenData (valores climatológicos diarios); cálculo de calentamientoglobal.es"
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _fecha(iso, anio=False):
    d = datetime.date.fromisoformat(iso[:10])
    return f"{d.day} de {MESES[d.month - 1]}" + (f" de {d.year}" if anio else "")


def _rango(ini, n):
    a = datetime.date.fromisoformat(ini)
    b = a + datetime.timedelta(n - 1)
    if a.month == b.month:
        return f"del {a.day} al {b.day} de {MESES[b.month - 1]} de {b.year}"
    return f"del {a.day} de {MESES[a.month - 1]} al {b.day} de {MESES[b.month - 1]} de {b.year}"


def _veces(a, b):
    return math.floor(a / b * 10) / 10 if b else None


def _cuanto(a, b):
    """«casi el triple», «más del doble»… solo si es cierto con el cociente exacto."""
    r = a / b if b else 0
    if r >= 4:
        return "más del cuádruple"
    if r >= 3:
        return "más del triple"
    if r >= 2.8:
        return "casi el triple"
    if r >= 2:
        return "más del doble"
    if r >= 1.8:
        return "casi el doble"
    return None


def _crudo(R):
    c = getattr(_crudo, "_c", None)
    if c is None:
        f = R.DOCS.parent / "archivo" / "otonio" / "crudo_otonios.json.gz"
        try:
            with gzip.open(f, "rt", encoding="utf-8") as g:
                c = json.load(g).get("datos") or {}
        except Exception:  # noqa: BLE001
            c = {}
        _crudo._c = c
    return c


def _max_otono_completo(R, ide):
    """El otoño completo (1-9 a 30-11, al menos 85 días con dato) más lluvioso de la estación en 1991-2025."""
    serie = _crudo(R).get(ide) or {}
    best, n = None, 0
    for a, v in serie.items():
        vals = [m for m in v.values() if m is not None]
        if len(vals) >= 85:
            n += 1
            t = sum(vals)
            if not best or t > best[0]:
                best = (t, int(a))
    primero = min((int(a) for a, v in serie.items() if len([m for m in v.values() if m is not None]) >= 85), default=None)
    return (best, n, primero) if best else (None, n, primero)


def _ent(x):
    return int(float(x) + 0.5)


def _titulo(n):
    """Nombre para un titular: «Ibiza, Aeropuerto» → «El aeropuerto de Ibiza»; «Huelva, Ronda Este» → «Huelva»."""
    import re
    m = re.match(r"^(.+?),\s*Aeropuerto$", n) or re.match(r"^(.+?) \(aeropuerto\)$", n)
    if m:
        return f"El aeropuerto de {m.group(1)}"
    return re.split(r" \(|, | - ", n)[0]


def _lugar(R, nombre, cod):
    return nombre if R.H._norm(R.nprov(cod)) in R.H._norm(nombre) else f"{nombre} ({R.nprov(cod)})"


def _episodio(R):
    idx = R.leer(R.DOCS / "prensa" / "episodios" / "index.json", {}) or {}
    for e in idx.get("episodios") or []:
        fin = e.get("cerrado") or R.HOY.isoformat()
        if (R.HOY - datetime.date.fromisoformat(fin)).days <= 7:
            d = R.leer(R.DOCS / "prensa" / "episodios" / f"{e['id']}.json", {}) or {}
            if d.get("ranking"):
                return d
    return None


def _candidatos(R):
    """[(puntos, cod, tipo, datos)] de todas las provincias."""
    out = []
    ep = _episodio(R)
    if ep:
        for r in ep["ranking"]:
            oh = r.get("otono_hist") or {}
            o = r.get("otono") or {}
            cod = r.get("cod")
            if cod not in R.PROV:
                continue
            mx_c = _max_otono_completo(R, r["id"]) if o.get("mm") else (None, 0, None)
            supera = bool(mx_c[0] and o.get("mm") and o["mm"] > mx_c[0][0] and mx_c[1] >= 10)
            if oh.get("record_dia") and oh.get("otonos", 0) >= 10:
                # pesa cuánto supera su máximo, cuánto llovió y lo larga que es la serie
                fuerza = min(6.0, r["max"] / oh["dia_max"] * 2) + min(5.0, r["max"] / 100) + min(3.0, (R.HOY.year - oh["desde"]) / 10)
                out.append((130 + fuerza, cod, "dia_record",
                            dict(r=r, ep=ep, oh=oh, o=o, supera=supera, mx=mx_c)))
            elif supera:
                out.append((125.0, cod, "otono_record", dict(r=r, ep=ep, oh=oh, o=o, mx=mx_c)))
            elif oh.get("record_tres") and oh.get("otonos", 0) >= 10:
                out.append((120.0, cod, "tres_record", dict(r=r, ep=ep, oh=oh, o=o)))
    V = R.leer(R.DOCS / "prensa" / "analisis" / "verano.json", {}) or {}
    est = V.get("estaciones") or {}
    for cod, ide in (V.get("provincias") or {}).items():
        x = est.get(ide) or {}
        a = x.get("actual") or {}
        if a.get("mas_dias") and cod in R.PROV:
            # un poco más si el año acaba de pasar el máximo anterior (en las tres últimas semanas)
            reciente = bool(a.get("fecha_supera")) and (R.HOY - datetime.date.fromisoformat(a["fecha_supera"])).days <= 21
            out.append((95 + min(10.0, (R.HOY.year - x["desde"]) / 10) + (3 if reciente else 0), cod, "verano_record", dict(x=x, a=a, ide=ide)))
    return sorted(out, key=lambda t: -t[0])


def _clave(tipo, c):
    """Clave estable del dato (no cambia de un día a otro): sirve para no mandar dos veces lo mismo al mismo periodista."""
    if tipo == "verano_record":
        return f"verano_record:{c['ide']}:{c['a'].get('anio')}"
    if tipo == "dia_record":
        return f"dia_record:{c['r']['id']}:{c['r'].get('max_fecha')}"
    return f"{tipo}:{c['r']['id']}:{c['ep'].get('id')}"


def _hechos(R, tipo, c, idp):
    """Hechos, titular y cifras de una exclusiva."""
    if tipo in ("dia_record", "otono_record", "tres_record"):
        r, oh, o, ep = c["r"], c["oh"], c["o"], c["ep"]
        n, cod = r["nombre"], r["cod"]
        lugar = _lugar(R, n, cod)
        hh, cifras = [], []
        if tipo == "dia_record":
            v = _veces(r["max"], oh["dia_max"])
            cu = _cuanto(r["max"], oh["dia_max"])
            hh.append(R.hecho(idp, f"La estación de AEMET de {lugar} recogió {R.f1(r['max'])} mm el {_fecha(r['max_fecha'])}: el día de otoño más lluvioso "
                                   f"de sus registros, que empiezan en {oh['desde']}.", FUENTE_OBS,
                              [R.f1(r["max"]) + " mm", str(oh["desde"])], lugar=n, superlativo=True, record=True, liga=[R.f1(r["max"])]))
            hh.append(R.hecho(f"{idp}_ant", f"Su día de otoño más lluvioso hasta ahora era el {_fecha(oh['dia_fecha'], anio=True)}, con {R.f1(oh['dia_max'])} mm"
                                            + (f": esta vez cayó más de {R.f1(v)} veces esa cifra." if v and v >= 1.5 else "."), FUENTE_D,
                              [R.f1(oh["dia_max"]) + " mm", oh["dia_fecha"][:4]] + ([R.f1(v)] if v and v >= 1.5 else []), lugar=n,
                              alias=[cu] if cu else []))
            nt = _titulo(n)
            if cu:
                tit = f"{nt} recoge en un solo día {cu} de lluvia que en el día de otoño más lluvioso de sus registros: {R.f1(r['max'])} litros"
            else:
                tit = f"{nt} vive el día de otoño más lluvioso de sus registros: {R.f1(r['max'])} litros, frente a {R.f1(oh['dia_max'])} de su máximo anterior"
            cifras.append({"n": f"{R.f1(r['max'])} mm", "l": f"en {n} el {_fecha(r['max_fecha'])}: su día de otoño más lluvioso desde {oh['desde']}", "tono": "lluvia"})
            cifras.append({"n": f"{R.f1(oh['dia_max'])} mm", "l": f"su máximo anterior ({_fecha(oh['dia_fecha'], anio=True)})", "tono": "lluvia"})
        elif tipo == "tres_record":
            tit = (f"{_titulo(n)} suma {R.f1(oh['tres_ep'])} litros en tres días, más que en cualquier otro tramo de tres días de otoño desde {oh['desde']}")
            cifras.append({"n": f"{R.f1(oh['tres_ep'])} mm", "l": f"en {n} en tres días", "tono": "lluvia"})
        else:
            mx = c["mx"][0]
            tit = (f"{_titulo(n)} ya ha superado el otoño más lluvioso de sus registros: {R.f1(o['mm'])} litros desde el 1 de septiembre, frente a {R.f1(mx[0])} en {mx[1]}")
            cifras.append({"n": f"{R.f1(o['mm'])} mm", "l": f"en {n} desde el 1 de septiembre", "tono": "lluvia"})
        if oh.get("record_tres") and oh.get("tres_ep"):
            ini = ep["dias_completos"][0]
            hh.append(R.hecho(f"{idp}_tres", f"En tres días, {_rango(ini, len(ep['dias_completos']))}, sumó {R.f1(oh['tres_ep'])} mm; su máximo anterior en tres días "
                                             f"seguidos de otoño eran {R.f1(oh['tres_max'])} mm, {_rango(oh['tres_fecha'], 3)}.", FUENTE_OBS,
                              [R.f1(oh["tres_ep"]) + " mm", R.f1(oh["tres_max"]) + " mm", oh["tres_fecha"][:4]], lugar=n,
                              superlativo=True, record=True))
        mx_c = c.get("mx") or (None, 0, None)
        if o.get("mm"):
            per = o.get("periodo") or "1991-2020"
            vv = _veces(o["mm"], o["normal_total"]) if o.get("normal_total") else None
            t = f"Desde el 1 de septiembre, {n} lleva {R.f1(o['mm'])} mm"
            vals = [R.f1(o["mm"]) + " mm"]
            if vv and vv >= 1.2:
                t += f", más de {R.f1(vv)} veces lo que llueve de media en un otoño entero en ese pluviómetro ({R.f1(o['normal_total'])} mm, {per})"
                vals += [R.f1(vv), R.f1(o["normal_total"]) + " mm", per[:4], per[5:]]
            if mx_c[0] and o["mm"] > mx_c[0][0] and mx_c[1] >= 10:
                t += f", y ya supera su otoño completo más lluvioso desde {mx_c[2]}: {R.f1(mx_c[0][0])} mm en {mx_c[0][1]}"
                vals += [R.f1(mx_c[0][0]) + " mm", str(mx_c[0][1]), str(mx_c[2])]
            hh.append(R.hecho(f"{idp}_oto", t + ".", FUENTE_D, vals, lugar=n, superlativo=bool(mx_c[0] and o["mm"] > mx_c[0][0]),
                              record=bool(mx_c[0] and o["mm"] > mx_c[0][0])))
            if tipo != "otono_record":
                cifras.append({"n": f"{R.f1(o['mm'])} mm", "l": f"en {n} desde el 1 de septiembre", "tono": "lluvia"})
        hh.append(R.hecho(f"{idp}_met", "La comparación es con todos los otoños (1 de septiembre-30 de noviembre) con dato de la estación en los valores diarios "
                                        "validados de AEMET; el dato de este episodio es observación horaria, que AEMET valida en unos días.", FUENTE_D, []))
        return hh, tit, cifras, "Exclusiva · lluvia contra su historia", "lluvia"
    x, a = c["x"], c["a"]
    n = x["nombre"]
    lugar = _lugar(R, n, x["cod"])
    ant = R.lista_y([str(z) for z in a["max_prev_anios"]])
    hh = [R.hecho(idp, f"Con los datos validados por AEMET hasta el {_fecha(a['datos_hasta'])}, la estación de {lugar} suma {a['dias']} días de verano en "
                       f"{a['anio']}: más que cualquier año completo desde {x['desde']} (el máximo anterior eran {a['max_prev']}, en {ant}).", FUENTE_D,
                  [str(a["dias"]), str(x["desde"]), str(a["max_prev"])] + [str(z) for z in a["max_prev_anios"]], lugar=n, superlativo=True, record=True),
          R.hecho(f"{idp}_largo", f"En 1961-1990 tenía de media {_ent(x['base_dias'])} días de verano al año y en 2011-2025, {_ent(x['rec_dias'])}."
                  if x["base"] == "1961-1990" else f"En {x['base']} tenía de media {_ent(x['base_dias'])} días de verano al año y en 2011-2025, {_ent(x['rec_dias'])}.",
                  FUENTE_D, [str(_ent(x["base_dias"])), str(_ent(x["rec_dias"])), x["base"][:4], x["base"][5:], "2011", "2025"], lugar=n),
          R.hecho(f"{idp}_def", f"Días de verano: los del año en que la media de siete días de la temperatura media de la estación alcanza {R.f1(x['umbral'])} °C, "
                                f"un nivel que en {x['base']} se superaba unos 92 días al año (lo que duran junio, julio y agosto).", FUENTE_D,
                  [R.f1(x["umbral"]) + " °C", "92", x["base"][:4], x["base"][5:]], lugar=n)]
    corto = _titulo(n)
    tit = f"{corto} ya ha tenido en {a['anio']} más días de verano que cualquier año desde {x['desde']}: {a['dias']}, frente a {a['max_prev']} en {ant}"
    cifras = [{"n": f"{a['dias']} días", "l": f"de verano en {corto} en {a['anio']}, con datos hasta el {_fecha(a['datos_hasta'])}", "tono": "calor"},
              {"n": f"{a['max_prev']}", "l": f"el máximo anterior desde {x['desde']} ({ant})", "tono": "calor"}]
    return hh, tit, cifras, "Exclusiva · el verano más largo", "calor"


def generar(R, D):
    cands = _candidatos(R)
    if not cands:
        return []
    mejor = {}
    for pts, cod, tipo, c in cands:
        mejor.setdefault(cod, (pts, tipo, c))
    pts0, cod0, tipo0, c0 = cands[0]
    hh, tit, cifras, kicker, tono = _hechos(R, tipo0, c0, "ex")
    otras = [(cod, t, c) for cod, (p, t, c) in mejor.items() if cod != cod0]
    lluvia = [(cod, c) for cod, t, c in otras if t == "dia_record"]
    if lluvia:
        hh.append(R.hecho("ex_otras", "También viven el día de otoño más lluvioso de sus registros "
                                      + R.lista_y([f"{_lugar(R, c['r']['nombre'], cod)}, con {R.f1(c['r']['max'])} mm (su máximo anterior, {R.f1(c['oh']['dia_max'])})"
                                                   for cod, c in lluvia[:4]]) + ".", FUENTE_OBS,
                          [R.f1(c["r"]["max"]) + " mm" for cod, c in lluvia[:4]] + [R.f1(c["oh"]["dia_max"]) for cod, c in lluvia[:4]],
                          superlativo=True, record=True))
    ver = [(cod, c) for cod, t, c in otras if t == "verano_record"]
    if ver:
        hh.append(R.hecho("ex_verano", "Y 2026 ya es el año con más días de verano de su serie en "
                                       + R.lista_y([f"{c['x']['nombre'].split(' (')[0]} (desde {c['x']['desde']})" for cod, c in ver[:6]]) + ".", FUENTE_D,
                          [str(c["x"]["desde"]) for cod, c in ver[:6]] + ["2026"], superlativo=True, record=True))
    if len(tit) > 165:
        tit = tit[:tit.rfind(":")] if ":" in tit else tit[:160]
    pl = {"titular": tit, "subtitulo": hh[1]["dice"] if len(hh) > 1 else "", "entradilla": hh[0]["dice"],
          "cuerpo": [" ".join(h["dice"] for h in hh[2:] if not h["id"].startswith("ex_") or h["id"] in ("ex_tres", "ex_oto", "ex_met"))]
          + [" ".join(h["dice"] for h in hh if h["id"] in ("ex_otras", "ex_verano"))],
          "claves": [h["dice"] for h in hh[:3]], "fijar": ["titular"]}
    pl["cuerpo"] = [p for p in pl["cuerpo"] if p]
    hid = f"{R.HOY.isoformat()}-exclusiva"
    h = R.historia("exclusiva", hid, kicker, tono, round(pts0, 1), hh, pl, cifras, FUENTE_OBS,
                   "Cada exclusiva compara un dato medido hoy por AEMET con toda la serie de esa misma estación: los otoños con dato desde 1991 "
                   "(valores diarios validados) o la serie diaria larga desde los años cuarenta. El cálculo es del observatorio.",
                   ["El dato del episodio es observación horaria sin validar: AEMET publica el diario validado unos 4 días después.",
                    "«Sus registros» son los de esa estación con dato en el archivo del observatorio, no toda la historia del lugar."],
                   "https://calentamientoglobal.es/prensa/")
    h["seccion"] = SECCION
    h["clave"] = _clave(tipo0, c0)
    ep = _episodio(R)
    if ep and (ep.get("graficos") or {}).get("ranking") and tipo0 != "verano_record":
        g = dict(ep["graficos"]["ranking"])
        g.update({"csv": ep.get("csv"), "leyenda": []})
        h["grafico"] = g
    for cod, (pts, tipo, c) in mejor.items():
        hv, tit_p, cif_p, kick_p, tono_p = _hechos(R, tipo, c, "exp")
        mas = [cc for p2, cod2, t2, cc in cands if cod2 == cod and t2 == "dia_record" and cc is not c]
        if mas:
            hv.append(R.hecho("exp_mas", "En la provincia también vive el día de otoño más lluvioso de sus registros "
                                         + R.lista_y([f"{cc['r']['nombre']}, con {R.f1(cc['r']['max'])} mm el {_fecha(cc['r']['max_fecha'])} (su máximo anterior, "
                                                      f"{R.f1(cc['oh']['dia_max'])} mm en {cc['oh']['dia_fecha'][:4]}; serie desde {cc['oh']['desde']})" for cc in mas[:3]]) + ".",
                              FUENTE_OBS, [R.f1(cc["r"]["max"]) + " mm" for cc in mas[:3]] + [R.f1(cc["oh"]["dia_max"]) + " mm" for cc in mas[:3]]
                              + [cc["oh"]["dia_fecha"][:4] for cc in mas[:3]] + [str(cc["oh"]["desde"]) for cc in mas[:3]], superlativo=True, record=True))
        if len(tit_p) > 165:
            tit_p = tit_p[:tit_p.rfind(":")] if ":" in tit_p else tit_p[:160]
        plv = {"titular": tit_p, "subtitulo": hv[1]["dice"] if len(hv) > 1 else "", "entradilla": hv[0]["dice"],
               "cuerpo": [" ".join(z["dice"] for z in hv[2:])] or [hv[0]["dice"]], "claves": [z["dice"] for z in hv[:3]], "fijar": ["titular"]}
        v = {"provincia": R.nprov(cod), "slug": R.PROV[cod][1], "hechos": hv, "plantilla": plv, "cifras": cif_p, "puntos": round(pts, 1),
             "kicker": kick_p, "tono": tono_p, "clave": _clave(tipo, c)}
        if tipo == "verano_record":
            g = {"svg": f"prensa/analisis/graficos/verano-{cod}.svg", "titulo": f"El verano de cada año en {c['x']['nombre']}",
                 "pie": f"Estación de AEMET de {c['x']['nombre']}. Fuente: AEMET OpenData (valores diarios). Cálculo: calentamientoglobal.es.",
                 "csv": "prensa/analisis/verano_anual.csv", "leyenda": []}
            v["grafico"] = g
        elif h.get("grafico"):
            v["grafico"] = h["grafico"]
        h["provincias"][cod] = v
    return [h]
