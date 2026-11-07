#!/usr/bin/env python3
"""Monitor de sequía de España (calentamientoglobal.es/sequia/) · bloque B: hub, 52 páginas, bloque del día y WordPress.

Lee lo que deja scripts/sequia.py en docs/sequia/ (index.json, nacional.json, <slug>.json, graf/) y:
  · genera el contenido fijo de /sequia/ y de /sequia/<provincia>/ (Gutenberg, un bloque wp:html, panel oscuro de /nieve/);
  · genera el bloque del día (meta cg_ssr_html, solo etiquetas que deja pasar cg-ssr-bloque.php);
  · crea o actualiza las 53 páginas por la REST de WordPress (mismo mecanismo y misma idempotencia que scripts/nieve.py);
  · deja el sitemap, los metatítulos de Rank Math y los JSON-LD.

Uso (lo llama scripts/sequia.py):  python scripts/sequia.py --vista DIR      → escribe el HTML en DIR para revisarlo
                                   python scripts/sequia.py --publicar [--forzar]
"""
from __future__ import annotations

import base64
import hashlib
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import sequia as S  # noqa: E402

WEB, PAGES, TZ, SALIDA, GRAF = S.WEB, S.PAGES, S.TZ, S.SALIDA, S.GRAF
API = os.environ.get("WP_API", WEB + "/wp-json/wp/v2")
PLANTILLA = "page-templates/no-wrapper.php"
ANCLA = "CGSSRSLOT"
PUBLICADO = SALIDA / "publicado.json"
MITECO = "https://www.miteco.gob.es/es/agua/temas/observatorio-nacional-de-la-sequia/informes-mapas-seguimiento.html"
LIMITE_FIJO = 18000          # caracteres del contenido fijo de una provincia (el conector MCP falla en silencio por encima de ~20.000)
NIV = S.NIVELES              # nivel → (texto, color)
CLASES = {0: "normal", 1: "vigilancia", 2: "sequía moderada", 3: "sequía severa", 4: "sequía extrema", 5: "sin dato"}


# ------------------------------------------------------------------------------------------------------------ utilidades
def esc(t) -> str:
    return html.escape(str(t), quote=True)


def hsh(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def sin_acentos(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn").lower()


def fl(d: str) -> str:
    return S.fecha_txt(date.fromisoformat(d))


def num(v, dec: int = 1) -> str:
    if v is None:
        return "—"
    return S.f1s(v) if dec == 1 else (S.f2(v) if dec == 2 else str(S.p0(v)))


def mm(v) -> str:
    return f"{num(v)} mm" if v is not None else "—"


def ancho(pct, escala: float = 100.0) -> int:
    return max(2, min(100, int(round(100 * float(pct) / escala))))


def cargar() -> tuple:
    idx = S.leer_json(SALIDA / "index.json")
    nac = S.leer_json(SALIDA / "nacional.json")
    if not idx or not nac:
        raise SystemExit("Faltan docs/sequia/index.json o nacional.json: ejecuta antes scripts/sequia.py")
    rs = {}
    for s in S.ORDEN:
        r = S.leer_json(SALIDA / f"{s}.json")
        if not r:
            raise SystemExit(f"Falta docs/sequia/{s}.json")
        rs[s] = r
    return idx, nac, rs


def img_fondo(nombre: str, alt: str, clase: str = "") -> str:
    """El SVG del bloque del día va como fondo de un div (el saneado de WordPress no deja <svg> ni <img>)."""
    p = GRAF / f"{nombre}.svg"
    if not p.exists():
        return ""
    txt = p.read_text(encoding="utf-8")
    m = re.search(r'viewBox="0 0 (\d+) (\d+)"', txt)
    w, h = (int(m.group(1)), int(m.group(2))) if m else (1600, 420)
    url = f"{PAGES}graf/{nombre}.svg?v={hsh(txt)[:10]}"
    return (f'<div class="cgsq-img {clase}" title="{esc(alt)}" style="background-image:url({url});padding-top:{100 * h / w:.2f}%">'
            f'</div><span class="cgsq-sr">{esc(alt)}</span>')


def slug_embalses(slug: str) -> str:
    return S.EMB_SLUG.get(slug, "")


def inicio_txt(r: dict) -> str:
    return S.mes_txt(r["inicio_serie"]) if r.get("inicio_serie") else "el inicio de la serie"


# ------------------------------------------------------------------------------------------------------------------ CSS
FUENTE = ('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" '
          'crossorigin><link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500..800'
          '&amp;display=swap" rel="stylesheet">')
CSS = FUENTE + """<style>
.cgsq{--tinta:#1a2530;--gris:#5d6b78;--hielo:#24608f;--noche:#0f3554;--txt:#e8f1f8;--sub:#b9cddc;--mut:#9fb6c8;--cel:#163a55;--hondo:#0a1b2a;--acc:#bfe6ff;--bra:#ff7a45;
max-width:1120px;margin:0 auto;padding:24px 16px 12px;box-sizing:border-box;background:#fff;color:var(--tinta);font:17px/1.62 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.cgsq *{box-sizing:border-box}.cgsq a{color:var(--hielo);text-underline-offset:3px}.cgsq a:hover{color:var(--noche)}
.cgsq a:focus-visible,.cgsq summary:focus-visible{outline:2px solid var(--bra);outline-offset:2px;border-radius:4px}
.cgsq h1,.cgsq h2,.cgsq h3,.cgsq-big b,.cgsq-cifra b{font-family:"Bricolage Grotesque",-apple-system,"Segoe UI",sans-serif}
.cgsq h2{font-size:30px;line-height:1.15;letter-spacing:-.015em;font-weight:720;margin:52px 0 12px;color:var(--noche)}
.cgsq h3{font-size:18px;line-height:1.35;margin:0;font-weight:700}.cgsq p{margin:0 0 14px;max-width:70ch}
.cgsq-panel{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(0,1fr);column-gap:36px;grid-template-areas:"intro hoy" "hid hid" "dias emb" "prev prev" "nieve nieve" "epis epis";grid-template-rows:repeat(6,auto);grid-auto-rows:0;
background:radial-gradient(1100px 520px at 88% -12%,#1d4a6e 0,#0c2133 58%);color:var(--txt);border-radius:28px;padding:40px 44px 38px}
.cgsq-panel a{color:var(--acc)}.cgsq-panel a:hover{color:#fff}
.cgsq-intro{grid-area:intro;align-self:end}.cgsq-migas{font-size:14px;color:var(--mut);margin:0 0 16px}.cgsq-migas a{color:var(--mut);text-decoration:none}
.cgsq-migas a:hover{text-decoration:underline;color:#fff}.cgsq-migas span{margin:0 6px;opacity:.6}
.cgsq h1{font-size:48px;line-height:1.03;letter-spacing:-.025em;font-weight:760;margin:0 0 18px;color:#fff}
.cgsq h1 span{display:block;font-size:.5em;line-height:1.15;font-weight:560;letter-spacing:-.01em;color:#9fd2f3;margin-top:8px}
.cgsq .lede{font-size:18px;line-height:1.55;color:var(--sub);max-width:36em;margin:0 0 12px}
.cgsq .cgsq-ssr-fijo{font-size:15px;line-height:1.55;color:var(--mut);margin:0;max-width:40em}
.cgsq-panel .cg-ssr-slot,.cgsq-panel .cgsq-dia{display:contents}.cg-ssr-slot{visibility:hidden;font-size:0;line-height:0}
.cg-ssr-slot div,.cg-ssr-slot p,.cg-ssr-slot ul,.cg-ssr-slot a{visibility:visible;font-size:16px;line-height:1.5}
.cgsq-hoy,.cgsq-hid,.cgsq-dias,.cgsq-emb,.cgsq-prev,.cgsq-nieve,.cgsq-epis,.cgsq-cif,.cgsq-top,.cgsq-lista{background:rgba(255,255,255,.06);border:1px solid rgba(191,230,255,.16);border-radius:22px;padding:22px 24px;margin-top:18px}
.cgsq-hoy{grid-area:hoy;margin-top:0;align-self:end}.cgsq-hid{grid-area:hid}.cgsq-dias{grid-area:dias;margin-right:9px}.cgsq-emb{grid-area:emb;margin-left:9px}
.cgsq-prev{grid-area:prev}.cgsq-nieve{grid-area:nieve}.cgsq-epis{grid-area:epis;background:var(--hondo)}
.cgsq .cgsq-dia h2{font-size:15px;font-weight:500;letter-spacing:0;color:var(--mut);margin:0 0 6px;font-family:-apple-system,"Segoe UI",sans-serif}
.cgsq .cgsq-dia h3{font-size:16px;color:#fff;margin:14px 0 4px}.cgsq .cgsq-dia p{font-size:15.5px;line-height:1.5;color:var(--sub);max-width:none;margin:0 0 8px}
.cgsq .cgsq-dia b{color:#fff}.cgsq .cgsq-dia small{display:block;font-size:13px;color:var(--mut)}
.cgsq .cgsq-fecha{font-size:14px!important;color:var(--mut)!important}
.cgsq .cgsq-nivel{display:flex;align-items:center;gap:12px;margin:6px 0 10px!important}.cgsq-nivel b{font:760 36px/1.05 "Bricolage Grotesque",sans-serif;letter-spacing:-.015em}
.cgsq-dot{display:inline-block;width:22px;height:22px;border-radius:50%;flex:none;border:2px solid rgba(255,255,255,.55)}
.cgsq-n0,.cgsq-c0 i{background:#3d8bd1}.cgsq-n1,.cgsq-c1 i{background:#e9d36a}.cgsq-n2,.cgsq-c2 i{background:#f0a04b}.cgsq-n3,.cgsq-c3 i{background:#e0552b}.cgsq-n4,.cgsq-c4 i{background:#8b1a1a}.cgsq-n5,.cgsq-c5 i{background:#6b7c8a}.cgsq-ex{background:#1f6f5b}
.cgsq-chips{list-style:none;margin:8px 0 12px;padding:0;display:flex;flex-wrap:wrap;gap:8px}.cgsq-chips li{background:var(--cel);border-radius:14px;padding:8px 12px;font-size:14px;color:var(--sub);min-width:92px}
.cgsq-chips li b{display:block;font:740 22px/1.1 "Bricolage Grotesque",sans-serif;color:#fff}.cgsq-chips li small{font-size:12px!important}
.cgsq-chips5 li{display:flex;align-items:center;gap:8px;min-width:0}.cgsq-chips5 li b{display:inline;font-size:26px}.cgsq-chips5 i{display:inline-block;width:14px;height:14px;border-radius:50%}
.cgsq-big{display:flex;align-items:baseline;flex-wrap:wrap;gap:4px 12px;margin:2px 0 6px!important}.cgsq-big b{font-size:56px;line-height:1;font-weight:760;letter-spacing:-.02em}.cgsq-big span{font-size:16px;color:var(--acc);font-weight:600}
.cgsq-bar{position:relative;height:14px;border-radius:7px;background:#0c2133;margin:6px 0 4px}.cgsq-bar span{display:block;height:100%;border-radius:7px;background:linear-gradient(90deg,#3d8bd1,#bfe6ff)}
.cgsq-bar.cgsq-nm::after{content:"";position:absolute;left:50%;top:-3px;bottom:-3px;width:2px;background:var(--bra)}
.cgsq-brow{display:grid;grid-template-columns:96px minmax(0,1fr) 56px;gap:10px;align-items:center;font-size:14px;color:var(--sub);margin:6px 0}.cgsq-brow .cgsq-bar{margin:0}.cgsq-brow b{text-align:right}
.cgsq-lug{list-style:none;margin:6px 0 0;padding:0}.cgsq-lug li{display:flex;justify-content:space-between;gap:10px;padding:6px 0;border-top:1px solid rgba(191,230,255,.12);font-size:15px;color:var(--sub)}
.cgsq .cgsq-img{display:block;width:100%;height:0;background-size:100% 100%;background-repeat:no-repeat;margin-top:12px}.cgsq-sr{position:absolute!important;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.cgsq-mods{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0}.cgsq-mods span{background:var(--cel);border-radius:12px;padding:6px 12px;font-size:14px;color:var(--sub)}.cgsq-mods b{color:#fff}
.cgsq-eps{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin-top:10px}.cgsq-ep{background:var(--cel);border-radius:16px;padding:14px 16px;font-size:14px;color:var(--sub)}
.cgsq-ep b{display:block;font:740 22px/1.15 "Bricolage Grotesque",sans-serif;color:#fff;margin:2px 0}.cgsq-ep.cgsq-ahora{box-shadow:inset 0 0 0 2px var(--bra)}
.cgsq-graf{margin:22px 0 6px;background:#0c2133;border-radius:24px;padding:22px 22px 16px;color:var(--txt)}.cgsq-graf img{display:block;width:100%;height:auto}.cgsq-graf figcaption{font-size:14px;color:var(--mut);margin-top:10px}
.cgsq-svgw{overflow-x:auto}.cgsq-ley{display:flex;flex-wrap:wrap;gap:8px 18px;list-style:none;padding:0;margin:12px 0;font-size:15px}.cgsq-ley li{display:inline-flex;align-items:center;gap:8px}.cgsq-ley i{width:16px;height:16px;border-radius:50%;display:inline-block}
.cgsq-faq{max-width:820px}.cgsq-faq details{border-bottom:1px solid #e1e8ee}.cgsq-faq summary{list-style:none;cursor:pointer;display:flex;justify-content:space-between;align-items:center;gap:16px;padding:16px 0}
.cgsq-faq summary::-webkit-details-marker{display:none}.cgsq-faq summary::after{content:"+";font-size:26px;line-height:1;color:var(--hielo);font-weight:300}.cgsq-faq details[open] summary::after{content:"−"}
.cgsq-faq summary h3{color:var(--noche)}.cgsq-faq details p{margin:0 0 18px}.cgsq-enl{list-style:none;padding:0;display:flex;flex-wrap:wrap;gap:8px 20px}
.cgsq-metodo{margin:48px 0 12px;padding:20px 26px 8px;border-radius:20px;background:#f2f5f8;font-size:15px;color:#33414e}.cgsq-metodo p{max-width:none}
.cgsq-mc{display:none}
@media(max-width:860px){.cgsq-panel{grid-template-columns:minmax(0,1fr);grid-template-areas:"intro" "hoy" "hid" "dias" "emb" "prev" "nieve" "epis";grid-template-rows:repeat(8,auto);padding:28px 22px 24px}
.cgsq-hoy{margin-top:22px}.cgsq-dias,.cgsq-emb{margin-left:0;margin-right:0}.cgsq h1{font-size:38px}}
@media(max-width:600px){.cgsq{padding:12px 16px 4px;font-size:16.5px}.cgsq-panel{padding:22px 14px 16px;border-radius:22px}.cgsq h1{font-size:30px}.cgsq .lede{font-size:16.5px}
.cgsq h2{font-size:24px;margin-top:40px}.cgsq-hoy,.cgsq-hid,.cgsq-dias,.cgsq-emb,.cgsq-prev,.cgsq-nieve,.cgsq-epis,.cgsq-cif,.cgsq-top,.cgsq-lista{padding:16px 14px}
.cgsq-nivel b{font-size:28px}.cgsq-big b{font-size:44px}.cgsq-graf{padding:14px 10px 10px;border-radius:18px}.cgsq-svgw svg,.cgsq-svgw img{min-width:600px}.cgsq-brow{grid-template-columns:78px minmax(0,1fr) 50px}}
</style>"""

CSS_HUB = """.cgsq-panel-hub{grid-template-areas:"intro hoy" "mapa top" "cif cif" "lista lista";grid-template-rows:repeat(4,auto)}
.cgsq-mapaw{grid-area:mapa;margin-top:30px;align-self:center}.cgsq-svg{display:block;width:100%;height:auto;overflow:visible}
.cgsq-p{fill:#6b7c8a;stroke:#0c2133;stroke-width:1.2;transition:fill .2s}.cgsq-svg a:hover .cgsq-p,.cgsq-svg a:focus .cgsq-p{stroke:#fff;stroke-width:2.2}
.cgsq-top{grid-area:top;align-self:center;margin-top:30px}.cgsq-cif{grid-area:cif;display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px}
.cgsq-lista{grid-area:lista;padding:12px 14px}.cgsq-fila{display:grid;grid-template-columns:minmax(0,1.4fr) repeat(4,minmax(0,1fr));gap:10px;align-items:center;padding:10px 12px;border-radius:14px;color:var(--txt);text-decoration:none;border-top:1px solid rgba(191,230,255,.08);font-size:15px}
.cgsq a.cgsq-fila:hover{background:var(--cel);color:#fff}.cgsq-fila.cgsq-cab{font-size:12.5px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em;border-top:0}
.cgsq-fila b{color:#fff}.cgsq-fila small{display:inline!important;margin-left:6px}.cgsq-cifra b{display:block;font-size:34px;line-height:1.05;color:#fff}.cgsq-cifra span{display:block;font-size:14px;color:var(--mut)}
@media(max-width:860px){.cgsq-panel-hub{grid-template-areas:"intro" "hoy" "mapa" "top" "cif" "lista";grid-template-rows:repeat(6,auto)}.cgsq-top{margin-top:18px}}
@media(max-width:600px){.cgsq-fila{grid-template-columns:minmax(0,1fr) auto auto;font-size:14px}.cgsq-fila span:nth-child(n+4){display:none}.cgsq-fila.cgsq-cab span:nth-child(n+4){display:none}}
"""


def css_mapa() -> str:
    r = []
    for s in S.ORDEN:
        for n in range(5):   # el nivel 5 (sin dato) es el color de fondo del trazo
            r.append(f".cgsq:has(.cgsq-mc-{s}-{n}) .cgsq-p-{s}{{fill:{NIV[n][1]}}}")
    return "\n".join(r)


# ------------------------------------------------------------------------------------------------------------ textos fijos
PIE = ('<p class="cgsq-pie"><b>Fuente:</b> AEMET (precipitación), MITECO (embalses), ECMWF/DWD/Météo-France/NOAA (previsión) · '
       'cálculo de calentamientoglobal.es · CC BY 4.0 · <a href="' + MITECO + '" rel="noopener">Seguimiento oficial de la sequía '
       '(MITECO)</a>.</p>')


def texto_spi() -> str:
    return ("El SPI (Índice de Precipitación Estandarizado, McKee 1993) compara la lluvia de los últimos 3, 6 o 12 meses con la "
            "del mismo periodo del calendario entre 1991 y 2020, ajustando una distribución gamma. En su escala, 0 es lo normal, −1 un "
            "déficit moderado, −1,5 severo y −2 extremo, las clases que usa AEMET. El semáforo es nuestro y se lee así. " + S.REGLA_SEMAFORO +
            " El SPI cambia una vez al mes; cada día cambian la lluvia del año hidrológico, los días sin lluvia, los embalses y la previsión.")


def ley_niveles() -> str:
    return ('<ul class="cgsq-ley">' + "".join(f'<li><i class="cgsq-n{n}"></i>{esc(NIV[n][0])}</li>' for n in range(5)) +
            '<li><i class="cgsq-n5"></i>Sin dato</li></ul>')


def faq_ld(q: list) -> str:
    d = {"@context": "https://schema.org", "@type": "FAQPage",
         "mainEntity": [{"@type": "Question", "name": a, "acceptedAnswer": {"@type": "Answer", "text": b}} for a, b in q]}
    return '<script type="application/ld+json">' + json.dumps(d, ensure_ascii=False) + "</script>"


def faq_html(q: list) -> str:
    return ('<div class="cgsq-faq"><h2>Preguntas frecuentes</h2>' +
            "".join(f'<details{" open" if k == 0 else ""}><summary><h3>{esc(a)}</h3></summary><p>{esc(b)}</p></details>'
                    for k, (a, b) in enumerate(q)) + "</div>")


def estacion_txt(r: dict) -> str:
    cap = r["capital"]
    if r["tipo"] == "referencia":
        return (f"La estación de referencia de la provincia es {r['estacion']}, no la capital: se usa su serie larga de "
                f"AEMET porque la de {cap} no cubre el periodo 1991-2020.")
    if "ERA5" in (r.get("fuente_serie") or ""):
        return f"{cap} no tiene una estación con serie larga: la lluvia sale del reanálisis ERA5 en la capital (Copernicus), no de AEMET."
    return f"Estación de AEMET en {cap}." if r["estacion"] == cap else f"Estación de AEMET: {r['estacion']} ({cap})."


def lede(r: dict) -> str:
    return (f"Esta página mide cada día si hay sequía meteorológica en {r['provincia']}: un semáforo de cinco niveles con la lluvia de "
            f"{r['capital']} desde {inicio_txt(r)}, el SPI a 3, 6 y 12 meses, la lluvia del año hidrológico frente a lo normal, los "
            f"días sin lluvia, los embalses y la previsión a 15 días.")


def fijo_seo(r: dict) -> str:
    """60-90 palabras, solo cifras de meses cerrados (cambian una vez al mes)."""
    prov, cap = r["provincia"], r["capital"]
    m = next((x for x in reversed(r.get("serie_mensual_24") or []) if x["mes"] == r["ultimo_mes_cerrado"]), None)
    if r["nivel"] == 5 or not m or m.get("p") is None or not m.get("normal"):
        return (f"El Monitor de sequía de calentamientoglobal.es calcula el semáforo de {prov} con la lluvia mensual de {cap} "
                f"desde {inicio_txt(r)} y la compara con el periodo 1991-2020. Ahora mismo la provincia está sin semáforo porque a "
                f"la serie le falta algún mes completo y los huecos no se rellenan nunca; se publican igualmente los embalses, "
                f"el año hidrológico y la previsión a 15 días. El semáforo vuelve en cuanto AEMET valida la lluvia que falta.")
    pct = S.p0(100 * m["p"] / m["normal"])
    return (f"En {S.mes_txt(r['ultimo_mes_cerrado'])}, último mes cerrado, cayeron {S.f1s(m['p'])} mm en {cap}, el {pct} % de lo "
            f"normal del mes (media 1991-2020), y el semáforo de sequía de {prov} cerró el mes en «{r['nivel_texto'].lower()}». "
            f"La serie de lluvia con la que se calcula empieza en {inicio_txt(r)} ({r['fuente_serie']}) y el SPI se ajusta sobre "
            f"1991-2020. El semáforo se actualiza una vez al mes; la lluvia del año hidrológico, los días sin lluvia, los "
            f"embalses y la previsión, cada día.")


def preguntas_prov(r: dict) -> list:
    prov, cap = r["provincia"], r["capital"]
    if r.get("embalses"):
        e = (f"El porcentaje de agua embalsada en {prov}, comparado con hace un año y con la media de los últimos diez años, "
             f"está en el bloque «Embalses» de arriba, con datos del MITECO. El detalle por embalse está en la página de embalses "
             f"de la provincia.")
    else:
        e = (f"{prov} no tiene embalses incluidos en el boletín del MITECO que usamos, así que esta página no muestra tarjeta de "
             f"embalses. Para la sequía hidrológica, el MITECO publica informes mensuales de seguimiento.")
    return [(f"¿Hay sequía ahora en {prov}?",
             f"El semáforo de arriba lo dice con la fecha de hoy. Se calcula con el SPI a 3, 6 y 12 meses de la lluvia de {cap}: "
             f"«normal» es que no hay déficit relevante, «vigilancia» un mes o una temporada algo secos, y de «sequía moderada» a "
             f"«extrema» un déficit sostenido frente a 1991-2020."),
            (f"¿Cuánto ha llovido este año hidrológico en {prov}?",
             f"El año hidrológico empieza el 1 de octubre. La cifra de arriba suma la lluvia de {cap} desde ese día hasta el último "
             f"dato disponible y la compara con la media de 1991-2020 en las mismas fechas. Los últimos días son provisionales "
             f"hasta que AEMET los valida."),
            (f"¿Cómo están los embalses de {prov}?", e),
            (f"¿Va a llover en {prov} en los próximos días?",
             f"La previsión de {cap} a 15 días reúne cuatro modelos (ECMWF, ICON, ARPEGE y GFS) y da la mediana y la horquilla de la "
             f"lluvia esperada frente a lo normal de esas fechas. ECMWF y GFS llegan más lejos, ICON a 7 días y ARPEGE a 4; más allá "
             f"de una semana es solo una tendencia.")]


def jsonld_prov(r: dict) -> str:
    d = {"@context": "https://schema.org", "@type": "Dataset",
         "name": f"Sequía en {r['provincia']}: semáforo, SPI y lluvia del año hidrológico",
         "description": (f"Semáforo diario de sequía meteorológica en {r['provincia']} (SPI a 3, 6 y 12 meses sobre la lluvia de "
                         f"{r['capital']}), lluvia del año hidrológico frente a lo normal 1991-2020, días sin lluvia, embalses y "
                         f"previsión a 15 días."),
         "url": r["urls"]["pagina"], "license": "https://creativecommons.org/licenses/by/4.0/",
         "creator": {"@type": "Organization", "name": "calentamientoglobal.es", "url": WEB + "/"},
         "temporalCoverage": f"{r['inicio_serie']}/..", "dateModified": r["generado"],
         "spatialCoverage": {"@type": "Place", "name": f"{r['provincia']}, España"},
         "variableMeasured": [{"@type": "PropertyValue", "name": f"SPI a {k} meses", "unitText": "índice"} for k in (3, 6, 12)],
         "distribution": [{"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": r["urls"]["json"]},
                          {"@type": "DataDownload", "encodingFormat": "text/csv", "contentUrl": r["urls"]["csv"]}],
         "isBasedOn": ["https://www.aemet.es/es/serviciosclimaticos/datosclimatologicos", MITECO]}
    return json.dumps(d, ensure_ascii=False)


# ------------------------------------------------------------------------------------------------------------ provincia
def html_prov(r: dict) -> str:
    slug, prov = r["slug"], r["provincia"]
    out = [CSS, '<div class="cgsq">', '<div class="cgsq-panel">',
           f'<div class="cgsq-intro"><div class="cgsq-migas"><a href="/">Inicio</a><span>›</span><a href="/#observatorio">Observatorio climático</a>'
           f'<span>›</span><a href="/sequia/">Sequía</a><span>›</span>{esc(prov)}</div>'
           f'<h1>¿Hay sequía en {esc(prov)}?<span> Estado hoy, lluvia del año y embalses</span></h1>'
           f'<p class="lede">{esc(lede(r))}</p><p class="cgsq-ssr-fijo">{esc(fijo_seo(r))}</p></div>',
           f'<div class="cg-ssr-slot">{ANCLA}</div>', "</div>"]
    out.append(f"<h2>La sequía en {esc(prov)} desde {esc(inicio_txt(r))}</h2>")
    out.append(f'<figure class="cgsq-graf"><div class="cgsq-svgw"><img src="{PAGES}graf/{slug}-spi.svg" width="1600" height="420" '
               f'loading="lazy" alt="SPI a 12 meses en {esc(prov)} desde {esc(inicio_txt(r))}"></div><figcaption>SPI a 12 meses de '
               f'cada mes de la serie de {esc(r["capital"])}. Rojo: por debajo de −1 (sequía); azul: por encima de 1 (lluvia '
               f'excedentaria); naranja, el último mes. Datos en <a href="{r["urls"]["csv"]}">CSV</a> y '
               f'<a href="{r["urls"]["json"]}">JSON</a> (CC BY 4.0).</figcaption></figure>')
    out.append(f"<p>{esc(estacion_txt(r))} Los huecos de la serie no se rellenan: un mes sin lluvia completa deja sin calcular "
               f"cualquier acumulado que lo incluya. La lluvia de los últimos días procede del reanálisis ERA5 y de la previsión "
               f"de Open-Meteo y se marca como provisional hasta que AEMET la valida.</p>")
    out.append("<h2>Qué es el SPI y cómo leemos el semáforo</h2>")
    out.append(f"<p>{esc(texto_spi())}</p>" + ley_niveles())
    q = preguntas_prov(r)
    out.append(faq_html(q))
    ln = [f'<li><a href="/lluvias-en-{slug}/">Lluvias en {esc(prov)}</a></li>']
    if r.get("embalses"):
        ln.append(f'<li><a href="{esc(r["embalses"]["pagina"].replace(WEB, ""))}">Embalses de {esc(prov)}</a></li>')
    ln += [f'<li><a href="/nieve/{slug}/">Nieve en {esc(prov)}</a></li>',
           f'<li><a href="/cambio-climatico-en-{slug}/">Cambio climático en {esc(prov)}</a></li>',
           '<li><a href="/sequia-flash/">Qué es una sequía exprés</a></li>', '<li><a href="/sequia/">Sequía en España</a></li>']
    out.append('<h2>Sigue con…</h2><ul class="cgsq-enl">' + "".join(ln) + "</ul>")
    out.append('<div class="cgsq-metodo">' + PIE + "</div></div>")
    out.append(faq_ld(q))
    c = "<!-- wp:html -->\n" + "\n".join(out) + "\n<!-- /wp:html -->"
    assert len(c) <= LIMITE_FIJO, f"{slug}: el contenido fijo mide {len(c)} caracteres (límite {LIMITE_FIJO})"
    return c


def ssr_prov(r: dict) -> str:
    prov, cap, nv = r["provincia"], r["capital"], r["nivel"]
    hoy = date.fromisoformat(r["generado"])
    p = ['<div class="cgsq-dia">']
    # ---- hoy
    p.append(f'<div class="cgsq-hoy"><h2>Hoy en {esc(prov)}</h2><p class="cgsq-fecha">{esc(S.fecha_txt(hoy))}</p>'
             f'<p class="cgsq-nivel"><span class="cgsq-dot cgsq-n{nv}"></span><b>{esc(r["nivel_texto"])}</b></p>')
    if nv != 5 or any(r["spi"][k]["valor"] is not None for k in ("3", "6", "12")):
        p.append('<ul class="cgsq-chips">' + "".join(
            f'<li>SPI {k} meses<b>{esc(num(r["spi"][k]["valor"], 2))}</b><small>{esc(r["spi"][k]["clase"] or "sin dato")}</small></li>'
            for k in ("3", "6", "12")) + "</ul>")
    p.append(f'<p>{esc(r["textos"]["frase_nivel"])}</p><p class="cgsq-fecha">SPI hasta {esc(S.mes_txt(r["ultimo_mes_cerrado"]))}. '
             f'{esc(estacion_txt(r))}</p></div>')
    # ---- año hidrológico
    h = r.get("hidro")
    if h:
        a = h.get("anterior") or {}
        p.append(f'<div class="cgsq-hid"><h2>Año hidrológico: lluvia desde el 1 de octubre</h2>'
                 f'<p class="cgsq-big"><b>{S.p0(h["pct"])} %</b><span>de lo normal</span></p>'
                 f'<p>Del {esc(fl(h["inicio"]))} al {esc(fl(h["hasta"]))} han caído <b>{esc(mm(h["mm"]))}</b> en {esc(cap)}; lo normal '
                 f'en esas fechas (media 1991-2020) son {esc(mm(h["normal_mm"]))}.</p>'
                 f'<div class="cgsq-bar cgsq-nm"><span style="width:{ancho(h["pct"], 200) }%"></span></div>'
                 f'<small>La marca naranja es lo normal (100 %); la barra llega hasta el 200 %.</small>')
        if a.get("pct") is not None:
            p.append(f'<p>El año hidrológico anterior, del {esc(fl(a["inicio"]))} al {esc(fl(a["fin"]))}, sumó {esc(mm(a["mm"]))}: '
                     f'el {S.p0(a["pct"])} % de lo normal ({esc(mm(a["normal_mm"]))}).</p>')
        p.append(img_fondo(f"{r['slug']}-hidro", f"Lluvia acumulada del año hidrológico en {cap} frente a lo normal y al año anterior")
                 + "</div>")
    # ---- días sin lluvia
    d = r.get("dias") or {}
    if d:
        prv = (' <b>Dato provisional</b> (reanálisis/predicción, pendiente de validar por AEMET).'
               if d.get("ultimo_dia_es_provisional") or d.get("provisional") else "")
        ult = (f'El último día con 1 mm o más fue el {esc(fl(d["ultimo_dia_lluvia"]))} ({esc(mm(d["mm_ultimo"]))}).'
               if d.get("ultimo_dia_lluvia") else "")
        p.append(f'<div class="cgsq-dias"><h2>Días sin lluvia en {esc(cap)}</h2><p class="cgsq-big"><b>{d["sin_lluvia"]}</b>'
                 f'<span>{"día seguido" if d["sin_lluvia"] == 1 else "días seguidos"} con menos de 1 mm</span></p><p>{ult}{prv}</p>'
                 f'<p>Días con lluvia en los últimos 30: <b>{d["dias_lluvia_30"]}</b> (lo normal: {esc(num(d["normal_30"]))}); en los '
                 f'últimos 90: <b>{d["dias_lluvia_90"]}</b> (lo normal: {esc(num(d["normal_90"]))}).</p></div>')
    # ---- embalses
    e = r.get("embalses")
    if e:
        fila = lambda et, v: (f'<div class="cgsq-brow"><span>{et}</span><div class="cgsq-bar"><span style="width:{ancho(v)}%"></span></div>'
                              f'<b>{esc(num(v))} %</b></div>')
        p.append('<div class="cgsq-emb"><h2>Embalses de la provincia</h2>' + fila("Hoy", e["pct"]) + fila("Hace un año", e["pct_hace_1a"])
                 + fila("Media 10 años", e["pct_media_10a"]))
        if e.get("grandes"):
            p.append('<h3>Los tres más grandes</h3><ul class="cgsq-lug">' + "".join(
                f'<li><span>{esc(g["nombre"])}</span><b>{esc(num(g["pct"]))} %</b></li>' for g in e["grandes"][:3]) + "</ul>")
        p.append(f'<p class="cgsq-fecha">Boletín del MITECO del {esc(fl(e["boletin"]))}. <a href="{esc(e["pagina"].replace(WEB, ""))}">'
                 f'Embalses de {esc(prov)}</a></p></div>')
    # ---- previsión
    pv = r.get("prevision")
    if pv:
        mods = pv["modelos"]
        ok = [m for m in mods.values() if m.get("respondio") and (m.get("d7") is not None or m.get("d15") is not None)]
        p.append(f'<div class="cgsq-prev"><h2>Próximos 15 días en {esc(cap)}</h2>')
        if pv.get("n_modelos_15", 0) >= 2:
            p.append(f'<p class="cgsq-big"><b>{esc(num(pv["mediana_15"]))} mm</b><span>mediana de los modelos hasta el {esc(fl(pv["hasta"]))}</span></p>'
                     f'<p>Los modelos esperan entre {esc(mm(pv["min_15"]))} y {esc(mm(pv["max_15"]))} en 15 días; la mediana es '
                     f'{esc(mm(pv["mediana_15"]))}, frente a {esc(mm(pv["normal_15"]))} de lo normal en esas fechas.</p>')
        elif pv.get("n_modelos_15", 0) == 1 and pv.get("mediana_15") is not None:
            n15 = next(m["nombre"] for m in mods.values() if m.get("d15") is not None)
            p.append(f'<p class="cgsq-big"><b>{esc(num(pv["mediana_15"]))} mm</b><span>previstos hasta el {esc(fl(pv["hasta"]))}</span></p>'
                     f'<p>Solo {esc(n15)} llega hoy a 15 días y prevé {esc(mm(pv["mediana_15"]))}, frente a {esc(mm(pv["normal_15"]))} '
                     f'de lo normal en esas fechas.</p>')
        else:
            p.append("<p>Los modelos no dan hoy una cifra a 15 días para esta capital.</p>")
        if pv.get("mediana_7") is not None:
            p.append(f'<p>En los próximos 7 días, la mediana es de <b>{esc(mm(pv["mediana_7"]))}</b>.</p>')
        p.append('<div class="cgsq-mods">' + "".join(
            f'<span>{esc(m["nombre"])}: ' + (f'<b>{esc(mm(m["d7"]))}</b> a 7 d' if m.get("d7") is not None else "") + (f'{" · " if m.get("d7") is not None else ""}<b>{esc(mm(m["d15"]))}</b> a 15 d' if m.get("d15") is not None else "") + "</span>"
            for m in ok) + "</div>")
        falt = [m["nombre"] for m in mods.values() if not m.get("respondio")]
        p.append(f'<p class="cgsq-fecha">Previsión de ECMWF, ICON, ARPEGE y GFS (Open-Meteo)'
                 + (f"; hoy no han respondido: {esc(', '.join(falt))}" if falt else "")
                 + ". ICON llega a 7 días y ARPEGE a 4; más allá de una semana es una tendencia.</p></div>")
    # ---- nieve
    n = r.get("nieve")
    if n and hoy.month in (11, 12, 1, 2, 3, 4, 5) and ((n.get("temporada_cm") or 0) > 0 or (n.get("normal_hoy_cm") or 0) > 0):
        p.append(f'<div class="cgsq-nieve"><h2>Nieve en {esc(n["monte"])} ({str(S.p0(n["altitud_m"]))} m)</h2><p>Esta temporada han caído '
                 f'<b>{esc(num(n["temporada_cm"]))} cm</b>; lo normal a estas alturas son {esc(num(n["normal_hoy_cm"]))} cm. '
                 f'<a href="{esc(n["pagina"].replace(WEB, ""))}">Nieve en {esc(prov)}</a></p></div>')
    # ---- episodios
    eps = r.get("episodios") or []
    if eps:
        pa = r.get("puesto_actual") or {}
        p.append(f'<div class="cgsq-epis"><h2>Las mayores sequías de la serie de {esc(cap)}</h2>')
        if pa.get("puesto") and r["spi"]["12"]["valor"] is not None:
            p.append(f'<p>El SPI a 12 meses de hoy, {esc(num(r["spi"]["12"]["valor"], 2))}, es el puesto {pa["puesto"]}.º de los '
                     f'{pa["de"]} meses de la serie, ordenados del más seco al más húmedo.</p>')
        p.append('<div class="cgsq-eps">' + "".join(
            f'<div class="cgsq-ep{" cgsq-ahora" if ep.get("en_curso") else ""}"><span>{esc(S.mes_txt(ep["inicio"]))}{"" if ep["inicio"] == ep["fin"] else " – " + esc(S.mes_txt(ep["fin"]))}'
            f'{" (en curso)" if ep.get("en_curso") else ""}</span><b>SPI {esc(num(ep["spi_min"], 2))}</b>'
            f'<span>{ep["meses"]} {"mes" if ep["meses"] == 1 else "meses"} con SPI a 12 meses ≤ −1 · mínimo en {esc(S.mes_txt(ep["mes_min"]))}'
            f' · lluvia al {S.p0(ep["pct_normal"])} % de lo normal</span></div>' for ep in eps[:5]) + "</div>")
        p.append('<p class="cgsq-fecha">Un episodio son los meses seguidos con SPI a 12 meses igual o inferior a −1; se ordenan por el '
                 'mínimo que alcanzan.</p></div>')
    p.append("</div>")
    return "".join(p)


# ------------------------------------------------------------------------------------------------------------ metas
def titulo_prov(r: dict) -> str:
    return f"Sequía en {r['provincia']}"


ROT = "ABCD"


def metas_prov(r: dict, k: int) -> dict:
    P, C = r["provincia"], r["capital"]
    t = {"A": f"Sequía en {P}: semáforo diario y lluvia del año",
         "B": f"Sequía en {P}: SPI, embalses y días sin lluvia",
         "C": f"¿Hay sequía en {P}? Estado hoy y previsión",
         "D": f"Sequía en {P} hoy: semáforo, lluvia y embalses"}[ROT[k % 4]]
    d = {"A": f"Semáforo diario de sequía en {P}: SPI a 3, 6 y 12 meses con la lluvia de AEMET en {C}, año hidrológico frente a lo normal y embalses. Datos actualizados a diario.",
         "B": f"De la lluvia del año hidrológico a los días sin llover en {C}: el estado de la sequía en {P} con el SPI, los embalses y la previsión a 15 días. Datos actualizados a diario.",
         "C": f"Qué dicen los datos de la sequía en {P}: semáforo de hoy, cuánto ha llovido desde el 1 de octubre frente a lo normal y qué prevén cuatro modelos. Datos actualizados a diario.",
         "D": f"Cómo está la sequía en {P} hoy: nivel del semáforo, SPI, lluvia desde octubre, embalses y previsión de lluvia a 15 días en {C}. Datos actualizados a diario."}[ROT[k % 4]]
    return {"rank_math_title": t, "rank_math_description": d, "rank_math_focus_keyword": f"sequía en {P.lower()}"}


# ------------------------------------------------------------------------------------------------------------------ hub
def _rdp(pts: list, eps: float) -> list:
    if len(pts) < 3:
        return pts
    (x1, y1), (x2, y2) = pts[0], pts[-1]
    dx, dy = x2 - x1, y2 - y1
    den = (dx * dx + dy * dy) ** 0.5 or 1e-9
    k, dmax = 0, 0.0
    for i in range(1, len(pts) - 1):
        d = abs(dy * pts[i][0] - dx * pts[i][1] + x2 * y1 - y2 * x1) / den
        if d > dmax:
            k, dmax = i, d
    if dmax <= eps:
        return [pts[0], pts[-1]]
    return _rdp(pts[:k + 1], eps)[:-1] + _rdp(pts[k:], eps)


def simplificar(d: str, eps: float = 0.45) -> str:
    """El trazo de /nieve/ pesa 273 KB para las 50 provincias; a 514 px de ancho se ve igual con un cuarto de los puntos."""
    out = []
    for sub in d.split("M")[1:]:
        z = sub.strip().endswith("Z")
        pts = [tuple(float(v) for v in q.split(",")) for q in re.findall(r"-?\d+\.?\d*,-?\d+\.?\d*", sub)]
        if len(pts) < 4:
            continue
        cerrado = pts[0] == pts[-1]
        s = _rdp(pts[:-1] if cerrado else pts, eps)
        if cerrado:
            s = s + [s[0]]
        if len(s) < 3:
            continue
        area = abs(sum(s[i][0] * s[i + 1][1] - s[i + 1][0] * s[i][1] for i in range(len(s) - 1))) / 2
        out.append((area, "M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in s) + ("Z" if z else "")))
    grandes = [t for a, t in out if a >= 3.0]      # islotes de menos de 3 px² no se ven a este tamaño
    return "".join(grandes or [max(out)[1]])


def svg_mapa_hub(pub: set) -> str:
    tr = {k: simplificar(v) for k, v in S.trazos_mapa().items()}
    s = ['<svg viewBox="0 0 514 460" role="img" aria-labelledby="cgsq-maph" class="cgsq-svg"><title id="cgsq-maph">Mapa de la sequía en España '
         'por provincias: pulsa en una provincia para ver su página</title>',
         f'<rect x="2" y="{(44 - 36.4) * 46:.0f}" width="187" height="120" rx="8" fill="none" stroke="#2f5a7d" stroke-dasharray="4 4"/>']
    nombres = {x: S.NOMBRE[S.COD[x]] for x in S.ORDEN}
    for slug in S.ORDEN:
        if slug not in tr:
            continue
        pth = f'<path class="cgsq-p cgsq-p-{slug}" d="{tr[slug]}"><title>{esc(nombres[slug])}</title></path>'
        s.append(f'<a href="/sequia/{slug}/" aria-label="Sequía en {esc(nombres[slug])}">{pth}</a>' if slug in pub else pth)
    s.append('<rect x="204" y="368" width="150" height="76" rx="8" fill="none" stroke="#2f5a7d" stroke-dasharray="4 4"/>')
    for j, (slug, et) in enumerate((("ceuta", "Ceuta"), ("melilla", "Melilla"))):
        cx = 244 + j * 70
        c = f'<circle class="cgsq-p cgsq-p-{slug}" cx="{cx}" cy="396" r="14"><title>{et}</title></circle>'
        s.append(f'<a href="/sequia/{slug}/" aria-label="Sequía en {et}">{c}</a>' if slug in pub else c)
        s.append(f'<text x="{cx}" y="430" font-size="14" fill="#e8f1f8" text-anchor="middle">{et}</text>')
    s.append("</svg>")
    return "".join(s)


def grandes_sequias(rs: dict) -> list:
    """Cuatro párrafos. Lo de AEMET, atribuido y fechado; lo demás sale de nuestras series (episodios de SPI a 12 meses)."""
    ventanas = [("1991-1995", "1991-01", "1995-12"), ("2004-2005", "2004-01", "2005-12"), ("2015-2017", "2015-01", "2017-12"),
                ("2022-2023", "2022-01", "2023-12")]
    frases = []
    for nom, a, b in ventanas:
        n, peor = 0, None
        for r in rs.values():
            if r["nivel"] == 5 and not r.get("episodios"):
                continue
            hit = [e for e in (r.get("episodios") or []) if e["inicio"] <= b and e["fin"] >= a]
            if hit:
                n += 1
                m = min(hit, key=lambda e: e["spi_min"])
                if peor is None or m["spi_min"] < peor[1]["spi_min"]:
                    peor = (r, m)
        tot = sum(1 for r in rs.values() if r.get("serie_spi12") and r["serie_spi12"][0]["mes"] <= a)
        frases.append((nom, n, tot, peor))
    out = []
    for nom, n, tot, peor in frases:
        if not tot:
            continue
        t = (f"{nom}: {n} de las {tot} provincias con serie en esos años tuvieron algún episodio con SPI a 12 meses igual o inferior a −1")
        if peor:
            r, m = peor
            t += (f". El más intenso fue el de {r['provincia']} ({S.mes_txt(m['inicio'])} a {S.mes_txt(m['fin'])}), con un SPI a "
                  f"12 meses mínimo de {S.f2(m['spi_min'])} en {S.mes_txt(m['mes_min'])} y una lluvia del {S.p0(m['pct_normal'])} % "
                  f"de lo normal.")
        else:
            t += "."
        out.append(t)
    return out


def html_hub(idx: dict, nac: dict, rs: dict, pub: set) -> str:
    grandes = grandes_sequias(rs)
    q = [("¿Hay sequía en España hoy?", "El mapa de arriba muestra el semáforo de sequía meteorológica de cada provincia con la fecha de "
                                          "hoy. Se calcula con el SPI a 3, 6 y 12 meses de la lluvia de AEMET en su capital; una provincia "
                                          "está en sequía a partir del nivel «sequía moderada»."),
         ("¿Cuál es la diferencia entre sequía meteorológica e hidrológica?",
          "La meteorológica mide cuánto ha llovido frente a lo normal; la hidrológica, cuánta agua hay en embalses, ríos y acuíferos. "
          "Esta página mide la primera y enseña los embalses como contexto. Para la hidrológica, el MITECO publica informes oficiales."),
         ("¿Qué es el año hidrológico?", "El periodo del 1 de octubre al 30 de septiembre, pensado para que una temporada de lluvias no se parta "
                                           "en dos. Aquí se compara la lluvia caída desde el 1 de octubre con la media de 1991-2020."),
         ("¿Qué provincias tienen más sequía?", "La lista de las provincias con el SPI a 12 meses más bajo está en el panel de arriba y se "
                                                 "actualiza con cada cierre de mes."),
         ("¿Puedo usar los datos?", f"Sí, con licencia CC BY 4.0 citando a calentamientoglobal.es: JSON y CSV de cada provincia en {PAGES}.")]
    out = [CSS.replace("</style>", CSS_HUB + css_mapa() + "\n</style>"), '<div class="cgsq">', '<div class="cgsq-panel cgsq-panel-hub">',
           '<div class="cgsq-intro"><div class="cgsq-migas"><a href="/">Inicio</a><span>›</span><a href="/#observatorio">Observatorio climático</a>'
           '<span>›</span>Sequía</div><h1>Sequía en España, hoy:<span> mapa por provincias, lluvia del año hidrológico y embalses</span></h1>'
           '<p class="lede">Un semáforo de sequía meteorológica para cada una de las 52 provincias, calculado con la lluvia oficial de '
           'AEMET en su capital: SPI a 3, 6 y 12 meses, lluvia desde el 1 de octubre frente a lo normal, días sin llover, embalses y '
           'previsión a 15 días.</p></div>',
           '<div class="cgsq-mapaw">' + svg_mapa_hub(pub) + ley_niveles() + "</div>",
           f'<div class="cg-ssr-slot">{ANCLA}</div>', "</div>"]
    out.append("<h2>Qué es la sequía y cómo la medimos</h2>")
    out.append("<p>Hablamos de sequía meteorológica: un déficit de lluvia frente a lo normal durante un tiempo suficiente. No es lo mismo "
               "que la sequía hidrológica, que mira el agua en embalses, ríos y acuíferos y tarda más en notarse; para esa, el MITECO "
               f'publica <a href="{MITECO}" rel="noopener">informes de seguimiento</a> y aquí mostramos los embalses como contexto.</p>')
    out.append("<p>La medida es el SPI (Índice de Precipitación Estandarizado, McKee 1993): la lluvia de los últimos 3, 6 y 12 meses frente a la "
               "del mismo periodo entre 1991 y 2020, con una distribución gamma. 0 es lo normal; −1, un déficit moderado; −1,5, severo; −2, "
               "extremo, como en AEMET. El de 3 meses detecta un mes malo; los de 6 y 12, una sequía de verdad.</p>")
    out.append("<p>El semáforo es nuestro, está documentado y no cambia: " + esc(S.REGLA_SEMAFORO) + "</p>")
    out.append("<p>Cada página suma la lluvia del año hidrológico (desde el 1 de octubre), los días seguidos sin lluvia significativa, los "
               "embalses del MITECO y la previsión a 15 días. La estación es la de la capital; en Las Palmas, Pontevedra y Tarragona, una de "
               "referencia (aeropuerto de Gran Canaria, aeropuerto de Vigo y Observatorio del Ebro, en Tortosa), y Guadalajara, Asturias, "
               "Palencia, Cantabria y Ceuta, sin estación con serie larga, usan el reanálisis ERA5.</p>")
    out.append("<h2>Las grandes sequías de España, en nuestros datos</h2>")
    out.append("<p>Estas cifras salen de las series de las propias capitales, no de informes de terceros: un episodio son los meses "
               "seguidos con SPI a 12 meses igual o inferior a −1.</p>")
    out += [f"<p>{esc(g)}</p>" for g in grandes]
    out.append("<p>Para el año hidrológico 2022-2023, AEMET lo situó como el sexto más seco de lo que va de siglo en la España peninsular, "
               "con 560,7 mm frente a una normal de 640,1 mm (balance publicado en su blog el 17 de octubre de 2023, con serie desde "
               '1961). <a href="https://aemetblog.es/2023/10/17/ano-hidrologico-2022-2023-y-sequia/" rel="noopener">Leer el balance de AEMET</a>.</p>')
    out.append(faq_html(q))
    out.append('<h2>Sigue con…</h2><ul class="cgsq-enl"><li><a href="/lluvias-en-espana/">Lluvias en España</a></li>'
               '<li><a href="/embalses-espana/">Embalses de España</a></li><li><a href="/caudal-rios-espana-mapa/">Caudal de los ríos</a></li>'
               '<li><a href="/nieve/">Nieve en España</a></li><li><a href="/heladas/">Heladas</a></li><li><a href="/sequia-flash/">Qué es una sequía exprés</a></li>'
               '<li><a href="/metodologia/">Metodología</a></li></ul>')
    out.append('<div class="cgsq-metodo"><p><b>Datos.</b> Cada provincia tiene su JSON y su CSV en '
               f'<a href="{PAGES}index.json">{PAGES}index.json</a> (CC BY 4.0, citando a calentamientoglobal.es).</p>' + PIE + "</div></div>")
    out.append(faq_ld(q))
    return "<!-- wp:html -->\n" + "\n".join(out) + "\n<!-- /wp:html -->"


def ssr_hub(idx: dict, nac: dict, rs: dict, pub: set) -> str:
    hoy = date.fromisoformat(nac["generado"])
    n = nac["niveles"]
    p = ['<div class="cgsq-dia"><div class="cgsq-hoy"><h2>Sequía en España hoy</h2>'
         f'<p class="cgsq-fecha">{esc(S.fecha_txt(hoy))}</p><ul class="cgsq-chips cgsq-chips5">' +
         "".join(f'<li class="cgsq-c{k}"><i></i><b>{n[str(k)]["n"]}</b><span>{esc(NIV[k][0].lower() if k < 5 else "sin dato")}</span></li>' for k in range(6))
         + f'</ul><p>{esc(nac["nota"])}</p></div>']
    p.append('<span class="cgsq-mc ' + " ".join(f"cgsq-mc-{s}-{rs[s]['nivel']}" for s in S.ORDEN) + '"></span>')
    p.append('<div class="cgsq-top"><h2>Las 10 provincias con la sequía más larga (SPI a 12 meses)</h2><ul class="cgsq-lug">' + "".join(
        f'<li><span><a href="/sequia/{esc(t["slug"])}/">{esc(t["provincia"])}</a></span><b>{esc(num(t["spi12"], 2))}</b></li>'
        for t in nac["top10_secas"] if t["slug"] in pub) + '</ul><p class="cgsq-fecha">SPI a 12 meses del último mes cerrado; ordenadas de menor '
        'a mayor. Pulsa en una provincia del mapa para ver su página.</p></div>')
    h, e, c = nac.get("hidro_nacional"), nac.get("embalses"), nac.get("capitales_30_dias") or {}
    cif = ['<div class="cgsq-cif">']
    if h:
        cif.append(f'<div class="cgsq-cifra"><b>{S.p0(h["pct"])} %</b><span>de la lluvia normal desde el 1 de octubre: del {esc(fl(h["inicio"]))} '
                   f'al {esc(fl(h["hasta"]))} han caído {esc(mm(h["mm"]))} de media ponderada por superficie, frente a {esc(mm(h["normal_mm"]))}</span></div>')
    if e:
        cif.append(f'<div class="cgsq-cifra"><b>{esc(num(e["pct"]))} %</b><span>de los embalses llenos (hace un año, {esc(num(e["pct_hace_1a"]))} %; '
                   f'media de 10 años, {esc(num(e["pct_media_10a"]))} %). Boletín del MITECO del {esc(fl(e["boletin"]))}</span></div>')
    cif.append(f'<div class="cgsq-cifra"><b>{c.get("n", 0)}</b><span>capitales con 30 días o más sin lluvia significativa'
               + (": " + esc(", ".join(f'{x["capital"]} ({x["dias"]})' for x in (c.get("lista") or [])[:6])) if c.get("lista") else "") + "</span></div></div>")
    p.append("".join(cif))
    fila = ['<div class="cgsq-lista"><h2>Las 52 provincias</h2><div class="cgsq-fila cgsq-cab"><span>Provincia</span><span>SPI 12 m</span>'
            '<span>Lluvia desde 1 oct</span><span>Días sin lluvia</span><span>Embalses</span></div>']
    for r in sorted(rs.values(), key=lambda r: sin_acentos(r["provincia"])):
        spi = num(r["spi"]["12"]["valor"], 2)
        hid = f'{S.p0(r["hidro"]["pct"])} %' if r.get("hidro") else "—"
        dsl = str(r["dias"]["sin_lluvia"]) if r.get("dias") else "—"
        emb = f'{num(r["embalses"]["pct"])} %' if r.get("embalses") else "—"
        cuerpo = (f'<span><b>{esc(r["provincia"])}</b><small>{esc(r["nivel_texto"])}</small></span><span>{esc(spi)}</span><span>{esc(hid)}</span>'
                  f'<span>{esc(dsl)}</span><span>{esc(emb)}</span>')
        fila.append(f'<a class="cgsq-fila" href="/sequia/{r["slug"]}/">{cuerpo}</a>' if r["slug"] in pub
                    else f'<div class="cgsq-fila">{cuerpo}</div>')
    p.append("".join(fila) + "</div></div>")
    return "".join(p)


def jsonld_hub(idx: dict) -> str:
    return json.dumps({"@context": "https://schema.org", "@type": "Dataset",
                       "name": "Sequía en España por provincias: semáforo, SPI y lluvia del año hidrológico",
                       "description": "Semáforo diario de sequía meteorológica de las 52 provincias (SPI a 3, 6 y 12 meses sobre la lluvia de "
                                      "AEMET), lluvia del año hidrológico frente a lo normal 1991-2020, días sin lluvia, embalses y previsión a 15 días.",
                       "url": WEB + "/sequia/", "license": "https://creativecommons.org/licenses/by/4.0/",
                       "creator": {"@type": "Organization", "name": "calentamientoglobal.es", "url": WEB + "/"},
                       "temporalCoverage": "1940-01/..", "dateModified": idx["generado"],
                       "spatialCoverage": {"@type": "Place", "name": "España"},
                       "distribution": [{"@type": "DataDownload", "encodingFormat": "application/json", "contentUrl": PAGES + "index.json"}]},
                      ensure_ascii=False)


def metas_hub() -> dict:
    return {"rank_math_title": "Sequía en España hoy: mapa por provincias y datos",
            "rank_math_description": "¿Hay sequía en tu provincia? Mapa diario de las 52 provincias con el semáforo de sequía (SPI), la lluvia del año "
                                     "hidrológico frente a lo normal, los días sin llover y los embalses. Datos abiertos.",
            "rank_math_focus_keyword": "sequía en españa"}


# ------------------------------------------------------------------------------------------------------------ WordPress
class WP:
    def __init__(self, usuario: str, clave: str):
        self.aut = "Basic " + base64.b64encode(f"{usuario}:{clave}".encode()).decode()

    def pedir(self, metodo: str, ruta: str, datos: dict | None = None, intentos: int = 4):
        url = ruta if ruta.startswith("http") else API + ruta
        cuerpo = json.dumps(datos).encode() if datos is not None else None
        for i in range(intentos):
            req = urllib.request.Request(url, data=cuerpo, method=metodo, headers={
                "Authorization": self.aut, "Content-Type": "application/json", "Accept": "application/json",
                "User-Agent": "calentamientoglobal.es/sequia"})
            try:
                with urllib.request.urlopen(req, timeout=90) as rr:
                    return json.loads(rr.read().decode("utf-8") or "null")
            except urllib.error.HTTPError as e:
                txt = e.read().decode("utf-8", "replace")[:400]
                if e.code in (429, 500, 502, 503, 504) and i < intentos - 1:
                    time.sleep(10 * (i + 1))
                    continue
                raise RuntimeError(f"{metodo} {url} → HTTP {e.code}: {txt}") from None
            except Exception as e:  # noqa: BLE001
                if i < intentos - 1:
                    time.sleep(10 * (i + 1))
                    continue
                raise RuntimeError(f"{metodo} {url} → {type(e).__name__}: {e}") from None

    def buscar(self, slug: str, padre: int) -> dict | None:
        r = self.pedir("GET", f"/pages?slug={slug}&parent={padre}&status=publish,draft,private,pending&context=edit"
                              f"&_fields=id,slug,parent,status")
        return r[0] if r else None


def paginas_publicadas(rs: dict, reg: dict) -> set:
    """Qué provincias llevan enlace: las que no están sin dato o ya se publicaron alguna vez (no se despublican)."""
    return {s for s, r in rs.items() if r["nivel"] != 5 or (reg.get(s) or {}).get("estado") == "publish"}


def vista(carpeta: str) -> None:
    idx, nac, rs = cargar()
    reg = S.leer_json(PUBLICADO, {}) or {}
    pub = paginas_publicadas(rs, reg)
    d = Path(carpeta)
    d.mkdir(parents=True, exist_ok=True)
    fijo, ssr = html_hub(idx, nac, rs, pub), ssr_hub(idx, nac, rs, pub)
    (d / "sequia.html").write_text(fijo.replace(ANCLA, ssr), encoding="utf-8")
    S.log(f"hub: fijo {len(fijo)} caracteres, bloque del día {len(ssr)}")
    for s in S.ORDEN:
        f, b = html_prov(rs[s]), ssr_prov(rs[s])
        (d / f"{s}.html").write_text(f.replace(ANCLA, b), encoding="utf-8")
        if s in ("murcia", "a-coruna", "baleares", "las-palmas"):
            S.log(f"{s}: fijo {len(f)} caracteres, bloque del día {len(b)}")
    S.log(f"HTML de las 53 páginas en {d}")


def publicar(forzar: bool) -> int:
    usuario, clave = os.environ.get("WP_USER"), os.environ.get("WP_APP_PASSWORD")
    if not usuario or not clave:
        S.log("Faltan WP_USER / WP_APP_PASSWORD: no se publica")
        return 1
    idx, nac, rs = cargar()
    wp = WP(usuario, clave)
    reg = S.leer_json(PUBLICADO, {}) or {}
    pub = paginas_publicadas(rs, reg)
    ahora = datetime.now(timezone.utc).isoformat()
    errores = 0

    def subir(clave_reg, padre, slug, titulo, contenido, ssr, jsonld, metas, listo):
        nonlocal errores
        r = reg.get(clave_reg) or {}
        pid = r.get("id")
        if not pid:
            try:
                ex = wp.buscar(slug, padre)
            except RuntimeError as e:
                S.log(f"  ERROR {slug}: {e}")
                errores += 1
                return None
            pid = ex["id"] if ex else None
        estado = "publish" if (listo or r.get("estado") == "publish") else "draft"
        hc, hs = hsh(titulo + contenido + json.dumps(metas, sort_keys=True) + jsonld + estado), hsh(ssr)
        datos = {}
        if forzar or not pid or r.get("hc") != hc:
            datos.update({"title": titulo, "content": contenido, "status": estado, "parent": padre, "slug": slug,
                          "template": PLANTILLA, "comment_status": "closed", "ping_status": "closed"})
            meta = {"cg_ssr_anchor": ANCLA, "cg_ssr_jsonld": jsonld}
            meta.update(metas)
            datos["meta"] = meta
        if forzar or not pid or r.get("hs") != hs or datos:
            datos.setdefault("meta", {})["cg_ssr_html"] = ssr
        if not datos:
            return pid
        ruta = f"/pages/{pid}" if pid else "/pages"
        try:
            res = wp.pedir("POST", ruta, datos)
        except RuntimeError as e:
            if "rank_math" in str(e) and "meta" in datos:      # Rank Math no deja escribir sus metas por REST
                for k in [k for k in datos["meta"] if k.startswith("rank_math")]:
                    datos["meta"].pop(k)
                try:
                    res = wp.pedir("POST", ruta, datos)
                except RuntimeError as e2:
                    S.log(f"  ERROR {slug}: {e2}")
                    errores += 1
                    return pid
            else:
                S.log(f"  ERROR {slug}: {e}")
                errores += 1
                return pid
        pid = res["id"]
        if ssr and not ((res.get("meta") or {}).get("cg_ssr_html") or ""):
            S.log(f"  AVISO {slug}: el bloque del día no se ha guardado (¿snippet cg-ssr-bloque activo?)")
        reg[clave_reg] = {"id": pid, "hc": hc if "content" in datos else r.get("hc"), "hs": hs, "estado": estado,
                          "link": res.get("link"), "actualizado": ahora}
        S.log(f"  {slug} ({estado}): {'contenido y bloque' if 'content' in datos else 'bloque del día'} → {res.get('link')}")
        time.sleep(0.15)
        return pid

    hub = subir("_hub", 0, "sequia", "Sequía en España, hoy: mapa por provincias, lluvia del año hidrológico y embalses",
                html_hub(idx, nac, rs, pub), ssr_hub(idx, nac, rs, pub), jsonld_hub(idx), metas_hub(), True)
    if not hub:
        S.log("No se pudo crear la página /sequia/")
        return 1
    orden = sorted(S.ORDEN, key=lambda s: sin_acentos(rs[s]["provincia"]))
    for k, s in enumerate(orden):
        r = rs[s]
        subir(s, hub, s, titulo_prov(r), html_prov(r), ssr_prov(r), jsonld_prov(r), metas_prov(r, k), r["nivel"] != 5)
    reg["_generado"] = idx["generado"]
    S.escribir(PUBLICADO, json.dumps(reg, ensure_ascii=False, indent=1, sort_keys=True))
    S.escribir(SALIDA / "rankmath-sequia-53.txt", fichero_rankmath(rs, orden))
    S.escribir(SALIDA / "cg-sitemap-sequia-datos.json", json.dumps(
        {"generado": idx["generado"], "urls": ["/sequia/"] + [f"/sequia/{s}/" for s in orden if s in pub]}, ensure_ascii=False))
    if errores:
        S.log(f"{errores} páginas con error")
        return 1
    return 0


def fichero_rankmath(rs: dict, orden: list) -> str:
    o = ["# Metatítulos y metadescripciones de Rank Math para el Monitor de sequía (53 páginas).",
         "# Rotación de 4 plantillas A-B-C-D por orden alfabético de provincia; palabra clave principal «sequía en <provincia>».",
         "# Pega cada bloque en Rank Math → Título SEO / Descripción / Palabra clave principal de la página indicada.", "",
         "URL: /sequia/", "Título: " + metas_hub()["rank_math_title"], "Descripción: " + metas_hub()["rank_math_description"],
         "Palabra clave: " + metas_hub()["rank_math_focus_keyword"], ""]
    for k, s in enumerate(orden):
        m = metas_prov(rs[s], k)
        o += [f"URL: /sequia/{s}/", f"Título: {m['rank_math_title']} ({len(m['rank_math_title'])} car.)",
              f"Descripción: {m['rank_math_description']} ({len(m['rank_math_description'])} car.)",
              f"Palabra clave: {m['rank_math_focus_keyword']}", ""]
    return "\n".join(o)
