"""Prueba de scripts/nieve_puertos.py con tests/puertos_muestra.xml (python tests/test_puertos.py)."""
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))
import nieve                      # noqa: E402
import nieve_puertos as NP        # noqa: E402

AHORA = datetime.fromisoformat("2026-11-13T13:45:00+01:00")
XML = (Path(__file__).parent / "puertos_muestra.xml").read_bytes()
MALO = re.compile(r"None|NaN|—|Array|nan\b")


class Puertos(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = nieve.ctx_puertos()
        cls.d = NP.leer(XML, cls.t, AHORA)
        cls.por_id = {x["id"]: x for x in cls.d["tramos"]}

    def test_estados(self):
        e = {i: x["estado"] for i, x in self.por_id.items()}
        self.assertEqual(e, {"1001": "cerrado", "1002": "cadenas", "1003": "pesados", "1004": "nieve"})

    def test_fuera(self):
        for i in ("1005", "1006", "1007", "1008"):       # obra, finalizado, viento, alud de tierra
            self.assertNotIn(i, self.por_id)

    def test_deduplica_y_se_queda_con_la_ultima_version(self):
        self.assertEqual(len(self.d["tramos"]), 4)
        self.assertEqual(self.por_id["1001"]["pk_fin"], 92.0)

    def test_reparto(self):
        self.assertEqual(self.d["totales"], {"cerrados": 1, "cadenas": 1, "pesados": 1, "nieve": 1})
        self.assertEqual({k: v for k, v in self.por_id.items() if v["macizo"]}.keys(), self.por_id.keys())
        self.assertEqual({x["macizo"] for x in self.d["tramos"]}, {"pirineo", "cantabrica", "central", "iberica"})
        self.assertEqual(self.d["macizos"]["pirineo"]["cerrados"], 1)
        self.assertEqual(self.d["provincias"]["leon"]["cadenas"], 1)

    def test_campos(self):
        x = self.por_id["1001"]
        self.assertEqual((x["carretera"], x["provincia_slug"], x["municipio"], x["sentido"]),
                         ("A-136", "huesca", "Sallent de Gállego", "este"))
        self.assertEqual(x["puerto"], "Puerto del Portalet")
        self.assertIsNone(x["nivel_dgt"])
        self.assertIsNone(self.por_id["1002"]["puerto"])
        self.assertEqual(x["desde"], "2026-11-13T07:10+01:00")
        self.assertEqual([t["estado"] for t in self.d["tramos"]], ["cerrado", "cadenas", "pesados", "nieve"])
        self.assertEqual(self.d["corte"], "2026-11-13T13:40:00+01:00")

    def test_provincia_con_dos_macizos_decide_el_punto_mas_cercano(self):
        t = NP.Territorio([{"slug": "x", "nombres": ["Equis"], "puntos": [(42.0, -1.0, "a"), (40.0, -5.0, "b")]}])
        self.assertEqual(t.macizo("x", 41.9, -1.1), "a")
        self.assertEqual(t.macizo("x", 40.2, -4.8), "b")

    def test_bloque_con_tramos(self):
        N = nieve.MACIZO_PAG
        macs = {m: (N[m]["slug"], nieve.MACIZOS[m][0]) for m in nieve.ORDEN_MACIZOS if m in N}
        h = NP.bloque(self.d, "hub", None, None, macs, AHORA)
        self.assertIn("A las 13:40 del 13 de noviembre, la DGT tiene 1 tramo cerrado por nieve o hielo, 1 con cadenas "
                      "obligatorias, 1 con restricción a camiones y autobuses y 1 con nieve o hielo en la calzada.", h)
        self.assertIn("Carreteras con nieve ahora: puertos cerrados y con cadenas", h)
        self.assertIn('href="/nieve/pirineo/"', h)
        self.assertIn("Fuente: DGT. No incluye Cataluña ni el País Vasco.", h)
        self.assertIn("etraffic.dgt.es", h)
        self.assertIn("cambia en minutos", h)
        self.assertNotIn("Servei Català", h)
        self.assertIsNone(MALO.search(re.sub(r"<[^>]+>", " ", h)), h)
        m = NP.bloque(self.d, "macizo", "pirineo", "el Pirineo", macs, AHORA, ["cat"])
        self.assertIn("la DGT tiene en el Pirineo 1 tramo cerrado por nieve o hielo.", m)
        self.assertIn("A-136", m)
        self.assertNotIn("AP-66", m)
        self.assertIn("Servei Català de Trànsit", m)
        p = NP.bloque(self.d, "provincia", "leon", "León", macs, AHORA)
        self.assertIn("AP-66", p)
        self.assertIn("pk 100-110", p)
        self.assertNotIn("A-136", p)
        self.assertNotIn("Servei", p)
        self.assertIsNone(MALO.search(re.sub(r"<[^>]+>", " ", m + p)))

    def test_bloque_sin_tramos(self):
        sin = dict(self.d, tramos=[], totales={k: 0 for k in self.d["totales"]}, macizos={}, provincias={})
        h = NP.bloque(sin, "hub", None, None, {}, AHORA)
        self.assertIn("Sin restricciones por nieve en las carreteras que vigila la DGT, a las 13:40 del 13 de noviembre.", h)
        self.assertIn("Fuente: DGT", h)
        verano = datetime.fromisoformat("2026-07-13T13:45:00+02:00")
        sin_v = dict(sin, corte="2026-07-13T13:40:00+02:00")
        self.assertEqual(NP.bloque(sin_v, "hub", None, None, {}, verano), "")
        con_v = dict(self.d, corte="2026-07-13T13:40:00+02:00")      # con tramos, de junio a octubre sí se pinta
        self.assertIn("Carreteras con nieve ahora", NP.bloque(con_v, "hub", None, None, {}, verano))

    def test_dato_viejo_no_se_pinta(self):
        self.assertEqual(NP.bloque(self.d, "hub", None, None, {}, AHORA + timedelta(hours=7)), "")
        self.assertNotEqual(NP.bloque(self.d, "hub", None, None, {}, AHORA + timedelta(hours=5)), "")

    def test_fallo_conserva_lo_anterior_y_hist(self):
        with tempfile.TemporaryDirectory() as td:
            ruta, hist = Path(td) / "puertos.json", Path(td) / "h.csv"
            d, msg = NP.actualizar(ruta, hist, self.t, AHORA, bajar=lambda: XML)
            self.assertTrue(msg.startswith("ok"))
            self.assertEqual(hist.read_text().splitlines()[1], "2026-11-13,13:45,1,1,1,1")
            d2, msg2 = NP.actualizar(ruta, hist, self.t, AHORA, bajar=lambda: (_ for _ in ()).throw(OSError("sin red")))
            self.assertIn("FALLO", msg2)
            self.assertEqual(d2["corte"], d["corte"])
            self.assertEqual(len(hist.read_text().splitlines()), 2)
            d3, msg3 = NP.actualizar(ruta, hist, self.t, AHORA, bajar=lambda: b"<a><b/></a>")
            self.assertIn("FALLO", msg3)

    def test_bloque_integrado_en_nieve(self):
        nieve.PUERTOS = self.d
        nieve.AHORA = AHORA
        h = nieve.bloque_puertos("hub")
        self.assertIn("cgnv-pt", h)
        s = nieve.ssr_compatible(h)
        for tag in ("<svg", "<img", "<figure", "<dl", "<i>"):
            self.assertNotIn(tag, s)
        self.assertIn("Trafikoa", nieve.bloque_puertos("provincia", "alava", "Álava"))   # sin tramos, en noviembre: una línea
        self.assertIn("Trafikoa", nieve.bloque_puertos("macizo", "vasco", "los Montes Vascos"))
        self.assertIn("Servei", nieve.bloque_puertos("provincia", "lleida", "Lleida"))
        nieve.PUERTOS = None
        self.assertEqual(nieve.bloque_puertos("hub"), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
