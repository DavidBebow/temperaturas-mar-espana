#!/usr/bin/env python3
"""Pruebas del verificador de coherencia (scripts/coherencia.py).
Caso roto a propósito en coherencia_roto/: Valencia con valor 21,3 en hallazgos y 21,8 en antes_raro.json,
titular con PR 47 frente a rareza.PR 42, «hoy» con dato del 31-oct y una lista «Avisos rojos» con un aviso naranja.
Uso: python scripts/sala/tests/test_coherencia.py"""
import sys, time, json, unittest
from datetime import datetime
from pathlib import Path
AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent.parent))
import coherencia as C  # noqa: E402

ROTO = AQUI / "coherencia_roto" / "docs"
HTML_ROJOS = ('<div class="cgh-dest"><b class="cgh-dest-t"><i style="background:#d7261e"></i>Avisos rojos de AEMET</b><ul>'
              '<li><span><a href="/el-tiempo/caceres/">Cáceres</a> <small>lluvias</small></span><b class="cgh-avn" style="background:#d7261e;color:#ffffff">8</b></li>'
              '<li><span><a href="/el-tiempo/santa-cruz-de-tenerife/">Santa Cruz de Tenerife</a> <small>viento</small></span><b class="cgh-avn" style="background:#f08a24;color:#1d1d1f">12</b></li>'
              '</ul><p>Hoy: 2 avisos rojos</p></div>')


class Roto(unittest.TestCase):
    def setUp(self):
        self.est = C.ejecutar(ROTO, salida=None, html_hub=HTML_ROJOS, ahora=datetime(2026, 11, 10, 16, 0, tzinfo=C.MADRID))
        self.por = {c["id"]: c for c in self.est["comprobaciones"]}

    def test_clave(self):
        self.assertEqual(self.por["clave"]["fallos"], 1)  # solo Valencia (valor), Murcia coincide
        f = [x for x in self.est["fallos"] if x["comprobacion"] == "clave"][0]
        self.assertIn("valencia", f["clave"]); self.assertEqual({v["valor"] for v in f["valores"]}, {21.3, 21.8})

    def test_titular(self):
        self.assertEqual(self.por["titular"]["fallos"], 1)

    def test_hoy(self):
        self.assertGreaterEqual(self.por["hoy"]["fallos"], 1)

    def test_niveles(self):
        self.assertEqual(self.por["niveles"]["fallos"], 1)
        f = [x for x in self.est["fallos"] if x["comprobacion"] == "niveles"][0]
        self.assertIn("Santa Cruz de Tenerife: naranja", f["valores"][0]["valor"])

    def test_bloqueados(self):
        self.assertIn("roto-1", {b["id"] for b in self.est["bloqueados"]})
        self.assertNotIn("roto-2", {b["id"] for b in self.est["bloqueados"]})

    def test_marcar(self):
        h = json.load(open(ROTO / "prensa" / "hallazgos.json"))["enviables"]
        m = C.marcar_hallazgos(h)
        self.assertEqual([x["id"] for x in m], ["roto-1"]); self.assertTrue(h[0]["requiere_revision"]); self.assertFalse(h[1].get("requiere_revision"))

    def test_regla_niveles(self):
        self.assertEqual(C.lista_por_nivel("rojo", [("A", "rojo"), ("B", "naranja")]), ["B"])
        self.assertEqual(C.lista_por_nivel("rojo", [("A", "rojo")]), [])

    def test_es_hoy_no_es_etiqueta(self):
        d = datetime(2026, 11, 10, 16, 0, tzinfo=C.MADRID)
        self.assertFalse(C.fallo_hoy("un mes así es hoy al menos tres veces más probable", "2026-10-31", d))
        self.assertTrue(C.fallo_hoy("lluvia de hoy", "2026-11-03", d))
        self.assertFalse(C.fallo_hoy("lluvia de hoy", "2026-11-09", d))


class Real(unittest.TestCase):
    def test_json_reales(self):
        t = time.time(); est = C.ejecutar(C.DOCS, salida=None, html_hub="")
        self.assertLess(time.time() - t, 60)
        self.assertEqual(len(est["comprobaciones"]), 4)
        txt = json.dumps(est, ensure_ascii=False)
        for malo in ("None", "NaN", "Array"):
            self.assertNotIn(malo, txt.replace('"nota"', ""))

    def test_nunca_lanza_con_docs_vacios(self):
        est = C.ejecutar(AQUI / "no_existe", salida=None, html_hub="")
        self.assertEqual(est["n_fallos"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
