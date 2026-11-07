"""Nota pública mensual «capital a capital» de la huella climática (7-11-2026, bloque A).

Lo llama scripts/sala/atribucion.py al final de su paso del workflow (no hay workflow nuevo). Lee los JSON que acaba de escribir
(docs/huella/<slug>.json, antes_raro.json) y, para el último mes cerrado, escribe:

  docs/huella/nota-<AAAA-MM>.json   titular, fecha, entradilla, parrafos, metodo, licencia, markdown, tabla (50 capitales)
  docs/huella/nota-<AAAA-MM>.md     la nota en Markdown
  docs/huella/nota-<AAAA-MM>.csv    la tabla completa
  docs/huella/nota-<AAAA-MM>.png    1600×900, barras de PR por capital, color por fuente (estilo de tu_capital.dibujar_nacional)

Todo sale de ficheros y es re-derivable; ninguna cifra está escrita a mano. Un fallo aquí nunca rompe el paso de atribución.
"""
from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

URL_NOTA = "calentamientoglobal.es/prensa/huella-{mes_es}/"
PAGES = "https://davidbebow.github.io/temperaturas-mar-espana"
FONDO, TEXTO, SEC, ACENTO, DEST, HONDO = "#0c2133", "#e8f1f8", "#9fb6c8", "#bfe6ff", "#ff7a45", "#163a55"
COL_FUENTE = {"AEMET": "#ff7a45", "ERA5": "#6694ca"}
PALABRAS = (400, 480)
ENTRADILLA = (40, 60)


def _palabras(t: str) -> int:
    return len(re.findall(r"\S+", t))


def slug_mes_es(ym: str, MESES) -> str:
    """'2026-10' -> 'octubre-2026' (para la URL de la nota)."""
    return f"{MESES[int(ym[5:7]) - 1]}-{ym[:4]}"


def _leer_capitales(at):
    """Capitales con dato mensual de media: el mes de referencia más frecuente entre los meses cerrados."""
    filas, cuenta = [], Counter()
    for f in sorted(at.SALIDA.glob("*.json")):
        if f.name in ("index.json", "antes_raro.json") or f.name.startswith("nota-"):
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        mes = d.get("mes") or {}
        m, ref = mes.get("media"), mes.get("referencia")
        if not m or not ref or ref.get("tipo") != "cerrado" or m.get("PR") is None:
            continue
        cuenta[ref["mes"]] += 1
        filas.append((ref["mes"], d, m, ref))
    if not cuenta:
        return None, []
    ym = cuenta.most_common(1)[0][0]
    return ym, [(d, m, ref) for (k, d, m, ref) in filas if k == ym]


def _fila(d, m, ref):
    fuente = "AEMET" if m.get("fuente_mensual") == "aemet" else "ERA5"
    return {"slug": d["slug"], "capital": d["capital"], "valor": m["valor"], "normal_antes": m["media_antes"],
            "normal_ahora": m["media_ahora"], "T_antes": m["T_antes"], "T_ahora": m["T_ahora"], "PR": m["PR"],
            "pr_min": m["pr_min"], "pr_max": m["pr_max"], "fuente": fuente, "citabilidad": m.get("citabilidad"),
            "estacion": d.get("estacion"), "significativo": bool(m.get("significativo")), "hasta": ref.get("hasta")}


def _contexto_balance(at, ym: str):
    """Frase de contexto del balance mensual (docs/prensa/balance/<ym>.json) si existe; si no, None."""
    ruta = at.DOCS / "prensa" / "balance" / f"{ym}.json"
    if not ruta.exists():
        return None
    try:
        b = json.loads(ruta.read_text(encoding="utf-8"))
        nac = b["nacional"]
        prov = " provisional" if b.get("estado") != "cerrado" else ""
        return (f"El balance mensual{prov} del observatorio (normal de 1991-2020, una estación de AEMET por provincia) sitúa "
                f"{b['titulo_mes']} {at.fnum(nac['anomalia_media'])} °C por encima de lo normal en {nac['n']} provincias: es "
                f"otra medida, con otra normal.")
    except Exception:
        return None


def _titular(at, ym, filas, tot):
    """Titular del hallazgo nacional (scripts/hallazgos_prensa.py::_agregar_antes_raro_mes), de antes_raro.json."""
    anio, mes = int(ym[:4]), int(ym[5:7])
    try:
        cand = json.loads((at.SALIDA / "antes_raro.json").read_text(encoding="utf-8"))["candidatos"]
    except Exception:
        cand = []
    lista = [c for c in cand if c.get("indicador") == "mes_media_alta" and c.get("ambito_tiempo") == "mes"
             and str(c.get("fecha", ""))[:7] == ym]
    n = len(lista)
    if n < 3:
        return None, lista
    n_dato = len(filas)
    sel = [c for c in lista if c["rareza"].get("T_antes") is not None and float(c["rareza"]["T_antes"]) < at.T_MAX
           and c.get("tipo_fuente") == "aemet"] or [c for c in lista if c["rareza"].get("T_antes") is not None]
    top = max(sel, key=lambda c: float(c["rareza"]["T_antes"]))
    Ttop = at.frase_T(top["rareza"]["T_antes"], float(top["rareza"]["T_antes"]) >= at.T_MAX)
    if n_dato >= at.FRAC_NACIONAL * tot:
        denom = f"de las {tot} capitales" if n_dato >= tot else f"de las {n_dato} capitales con dato"
        return (f"Un {at.MESES[mes - 1]} como el de {anio} es hoy al menos tres veces más probable que en 1961-1990 en {n} "
                f"{denom}; en {top['capital']} era un mes de {Ttop}"), lista
    return (f"En {n} capitales, un {at.MESES[mes - 1]} como el de {anio} es hoy al menos tres veces más probable que en "
            f"1961-1990; en {top['capital']} era un mes de {Ttop}"), lista


def _lista_y(nombres):
    return ", ".join(nombres[:-1]) + " y " + nombres[-1] if len(nombres) > 1 else nombres[0]


def _texto(at, ym, filas, tot, titular, lista):
    """Entradilla y párrafos. Sin adjetivos, cada cifra con fecha, fuente, climas y método."""
    anio, mes = int(ym[:4]), int(ym[5:7])
    mes_es = f"{at.MESES[mes - 1]} de {anio}"
    n = len(filas)
    n_flag = len(lista)
    ordenadas = sorted(filas, key=lambda r: (-float(r["PR"]), -float(r["pr_min"]), r["capital"]))
    top5 = ordenadas[:5]
    n_a = sum(1 for r in filas if r["fuente"] == "AEMET")
    n_e = n - n_a
    f_a = sum(1 for c in lista if c.get("tipo_fuente") == "aemet")     # las mismas 31 de antes_raro.json
    f_e = n_flag - f_a
    nacional_ok = n >= at.FRAC_NACIONAL * tot
    cobertura = f"{n} de las {tot} capitales" if nacional_ok else f"{n} capitales (de {tot}; no es una imagen del conjunto de España)"

    entradilla = (f"En {n_flag} de las {n} capitales con dato, un {at.MESES[mes - 1]} como el de {anio} es hoy al menos tres "
                  f"veces más probable que en 1961-1990. La nota compara dos climas de la misma serie de cada capital, "
                  f"1961-1990 y 1996-2025, con estaciones de AEMET y el reanálisis ERA5.")

    p1 = (f"Esta nota mide cuántas capitales españolas tuvieron en {mes_es} una temperatura media mensual que antes era rara. "
          f"Hay dato en {cobertura}. En {n_flag}, un mes así es hoy al menos tres veces más probable que en 1961-1990, con un "
          f"intervalo del 90 % que no incluye el 1 y un periodo de retorno de al menos 10 años en 1961-1990. En las otras "
          f"{n - n_flag} no se cumplen esas condiciones.")

    items = [f"{r['capital']}, al menos {at.fnum(r['pr_min'])} (media {at.fnum(r['valor'])} °C; normal "
             f"{at.fnum(r['normal_antes'])} °C en 1961-1990, {at.fnum(r['normal_ahora'])} °C en 1996-2025)" for r in top5]
    p2 = ("Las cinco capitales con mayor cociente, con el límite inferior del intervalo del 90 % "
          "(«un mes así es hoy al menos X veces más probable»): " + "; ".join(items) + ".")
    bajos = [r["capital"] for r in top5 if r["pr_min"] < at.ANTES_RARO_PR]
    if bajos:
        p2 += f" En {_lista_y(bajos)} el límite inferior queda por debajo de 3: el intervalo es amplio."

    p3 = (f"De las {n} capitales, {n_a} van por la serie mensual de una estación de AEMET y {n_e} por el reanálisis ERA5 "
          f"(Copernicus/ECMWF), un modelo y no una estación. Una capital va por AEMET si su estación tiene al menos "
          f"{at.MIN_ANIOS} años válidos en cada clima y una serie homogénea; si no, va por ERA5, con citabilidad media. Entre "
          f"las {n_flag} destacadas, {f_a} son de AEMET y {f_e} de ERA5.")

    ctx = _contexto_balance(at, ym)
    mayor = max(filas, key=lambda r: float(r["PR"]))
    p4 = (f"Qué no dice esta nota: compara dos climas observados y no atribuye {mes_es} a una causa. Los intervalos del 90 % "
          f"son amplios en la cola: en {mayor['capital']} el cociente es {at.fratio(mayor['PR'], True)} y el intervalo va de "
          f"{at.fratio(mayor['pr_min'], True)} a {at.fratio(mayor['pr_max'], True)}.")
    if ctx:
        p4 += " " + ctx

    p5 = (f"Cómo se ha calculado. Se toma la media de {at.MESES[mes - 1]} de cada año de 1961-1990 y de 1996-2025 en la serie "
          f"de cada capital y se ajusta una distribución a cada clima. El PR es la probabilidad de un mes igual o más cálido "
          f"que el observado ahora, dividida por la de antes. El periodo de retorno es la inversa de cada probabilidad. El "
          f"intervalo del 90 % sale de {at.NBOOT} remuestreos de años.")

    p6 = (f"Cómo citar y reutilizar. Licencia {at.LICENCIA}: se puede copiar y republicar citando «calentamientoglobal.es, "
          f"huella climática, {mes_es}» enlazando la nota. La tabla de las {n} capitales está en CSV y JSON; el método, en "
          f"calentamientoglobal.es/metodologia/#huella-climatica. Fuentes: AEMET y reanálisis ERA5; cálculo propio.")
    return mes_es, entradilla, [p1, p2, p3, p4, p5, p6]


def _csv(filas) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["capital", "media", "normal_antes", "normal_ahora", "T_antes", "T_ahora", "PR", "pr_min", "pr_max", "fuente",
                "citabilidad"])
    for r in filas:
        w.writerow([r["capital"], r["valor"], r["normal_antes"], r["normal_ahora"], r["T_antes"], r["T_ahora"], r["PR"],
                    r["pr_min"], r["pr_max"], r["fuente"], r["citabilidad"]])
    return buf.getvalue()


def _markdown(titular, fecha_txt, entradilla, parrafos, filas, at) -> str:
    out = [f"# {titular}", "", f"*{fecha_txt}*", "", f"**{entradilla}**", ""]
    out += [p + "\n" for p in parrafos]
    out += ["## Tabla", "",
            "| Capital | Media (°C) | Normal 1961-1990 (°C) | Normal 1996-2025 (°C) | T antes (años) | T ahora (años) | PR | IC 90 % | Fuente | Citabilidad |",
            "|---|---|---|---|---|---|---|---|---|---|"]
    for r in filas:
        out.append(f"| {r['capital']} | {at.fnum(r['valor'])} | {at.fnum(r['normal_antes'])} | {at.fnum(r['normal_ahora'])} | "
                   f"{at.fratio(r['T_antes'], True)} | {at.fratio(r['T_ahora'], True)} | {at.fratio(r['PR'], True)} | "
                   f"{at.fratio(r['pr_min'], True)}-{at.fratio(r['pr_max'], True)} | {r['fuente']} | {r['citabilidad']} |")
    return "\n".join(out) + "\n"


def dibujar_png(at, ruta: Path, filas, mes_es: str, url_nota: str, n_flag: int):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    plt.rcParams["font.family"] = "DejaVu Sans"
    n = len(filas)
    mitad = (n + 1) // 2
    cols = [filas[:mitad], filas[mitad:]]
    tope = max(float(r["PR"]) for r in filas)
    xmax = max(10.0, min(tope, at.PR_TOPE_PUB)) * 2.6
    xmin = min(0.5, min(float(r["PR"]) for r in filas) * 0.8)
    fig = plt.figure(figsize=(16, 9), dpi=100, facecolor=FONDO)
    anchos = [(0.135, 0.33), (0.62, 0.33)]
    for (x0, w), bloque in zip(anchos, cols):
        if not bloque:
            continue
        ax = fig.add_axes([x0, 0.13, w, 0.69], facecolor=FONDO)
        k = len(bloque)
        ys = list(range(k))[::-1]
        for y, r in zip(ys, bloque):
            pr = min(float(r["PR"]), at.PR_TOPE_PUB)
            ax.barh(y, pr - 1.0, left=1.0, height=0.72, color=COL_FUENTE[r["fuente"]], lw=0, zorder=3)
            ax.text(max(pr, 1.0) * 1.08, y, f"{at.fratio(r['PR'], True)}  (≥ {at.fratio(r['pr_min'], True)})",
                    color=TEXTO, fontsize=10, va="center", zorder=6,
                    bbox={"facecolor": FONDO, "edgecolor": "none", "pad": 1.5})
        ax.set_xscale("log")
        ax.set_xlim(xmin, xmax)
        ax.axvline(1.0, color=SEC, lw=1.0, zorder=2)
        ax.axvline(at.ANTES_RARO_PR, color=ACENTO, lw=1.2, ls="--", zorder=2)
        ax.set_yticks(ys)
        ax.set_yticklabels([r["capital"] for r in bloque], color=TEXTO, fontsize=11)
        ax.set_ylim(-0.7, k - 0.3)
        ax.tick_params(axis="y", length=0)
        ax.set_xticks([])
        ax.minorticks_off()
        for s in ax.spines.values():
            s.set_visible(False)
    fig.text(0.02, 0.945, f"{mes_es.capitalize()}, capital a capital: cuánto más probable es hoy un mes así", color=TEXTO,
             fontsize=25, fontweight="bold", va="center")
    fig.text(0.02, 0.897, (f"Cociente de probabilidad (PR) de la temperatura media del mes: 1996-2025 frente a 1961-1990, "
                           f"en {n} capitales. Entre paréntesis, el límite inferior del intervalo del 90 %."),
             color=SEC, fontsize=13, va="center")
    fig.text(0.02, 0.862, (f"{n_flag} de {n} cumplen los criterios de «antes era raro»: PR ≥ 3, intervalo sin el 1 y periodo de "
                           f"retorno antes ≥ 10 años · línea discontinua: PR 3 · eje logarítmico"),
             color=SEC, fontsize=13, va="center")
    fig.legend(handles=[Patch(color=COL_FUENTE["AEMET"], label="Estación de AEMET"),
                        Patch(color=COL_FUENTE["ERA5"], label="Reanálisis ERA5 (no es una estación)")],
               loc="lower right", bbox_to_anchor=(0.98, 0.065), frameon=False, labelcolor=TEXTO, fontsize=12, ncol=2)
    fig.text(0.02, 0.04, f"{url_nota} · datos AEMET y reanálisis ERA5 · cálculo de calentamientoglobal.es · {at.LICENCIA}",
             color=SEC, fontsize=13, va="center")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(ruta, dpi=100, facecolor=FONDO)
    plt.close(fig)


def nota_mensual(at, dibujar: bool = True):
    """Escribe la nota del último mes cerrado. at es el módulo atribucion (constantes y formato). Devuelve el dict o None."""
    tot = len(at.SLUGS)
    ym, caps = _leer_capitales(at)
    if not ym or len(caps) < 3:
        at.log("nota mensual: sin mes cerrado con dato")
        return None
    filas = sorted((_fila(*c) for c in caps), key=lambda r: (-float(r["PR"]), -float(r["pr_min"]), r["capital"]))
    titular, lista = _titular(at, ym, filas, tot)
    n_flag = len(lista)
    if titular is None:
        at.log(f"nota mensual: {ym} con menos de 3 capitales «antes era raro»; no hay nota")
        return None
    mes_es, entradilla, parrafos = _texto(at, ym, filas, tot, titular, lista)
    pal, pal_e = sum(_palabras(p) for p in parrafos), _palabras(entradilla)
    if not (PALABRAS[0] <= pal <= PALABRAS[1]) or not (ENTRADILLA[0] <= pal_e <= ENTRADILLA[1]):
        at.log(f"nota mensual: AVISO longitud fuera de rango (párrafos {pal}, entradilla {pal_e})")
    fecha_cierre = max(r["hasta"] for r in filas if r.get("hasta"))
    fecha_txt = at.fecha_larga(date.fromisoformat(fecha_cierre))
    url = URL_NOTA.format(mes_es=slug_mes_es(ym, at.MESES))
    md = _markdown(titular, f"Datos hasta el {fecha_txt}", entradilla, parrafos, filas, at)
    generado = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    n_a = sum(1 for r in filas if r["fuente"] == "AEMET")
    obj = {"mes": ym, "titular": titular, "fecha": fecha_cierre, "fecha_txt": fecha_txt, "entradilla": entradilla,
           "parrafos": parrafos, "metodo": at.METODO_CORTO, "licencia": at.LICENCIA, "markdown": md,
           "n_capitales": tot, "n_con_dato": len(filas), "n_antes_raro": n_flag, "n_aemet": n_a, "n_era5": len(filas) - n_a,
           "palabras": pal, "url": f"https://{url}", "climas": {"antes": list(at.ANTES), "ahora": list(at.AHORA)},
           "archivos": {"csv": f"{PAGES}/huella/nota-{ym}.csv", "png": f"{PAGES}/huella/nota-{ym}.png",
                        "json": f"{PAGES}/huella/nota-{ym}.json",
                        "csv_dossier": f"{PAGES}/prensa/dossier/huella-antes-raro-espana-{ym}.csv"},
           "tabla": filas, "generado": generado}
    at.escribir_json(at.SALIDA / f"nota-{ym}.json", obj)
    at.escribir_texto(at.SALIDA / f"nota-{ym}.md", md)
    at.escribir_texto(at.SALIDA / f"nota-{ym}.csv", _csv(filas))
    if dibujar:
        try:
            dibujar_png(at, at.SALIDA / f"nota-{ym}.png", filas, mes_es, url, n_flag)
        except Exception as e:
            at.log(f"nota mensual: PNG no generado ({type(e).__name__}: {e})")
    at.log(f"nota mensual {ym}: {len(filas)} capitales, {n_flag} con PR ≥ 3, {pal} palabras · docs/huella/nota-{ym}.*")
    return obj
