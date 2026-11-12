"""
test_operace.py – automatické testy logiky (modul operace.py).

Spuštění:  python -m unittest -v

Každý test si vytvoří dočasnou složku, něco v ní provede a zkontroluje
výsledek. Po testu se složka sama smaže, takže testy nesahají na skutečné
soubory. Místo opravdového koše používáme „falešný“ (obyčejnou složku),
aby se testy daly spustit i bez knihovny send2trash a neplnily koš.
"""

import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import operace as op


class TestSDocasnouSlozkou(unittest.TestCase):
    """Společný základ: před každým testem připraví složku a falešný koš."""

    def setUp(self) -> None:
        # setUp se spustí před KAŽDÝM testem, tearDown/cleanup po něm.
        docasna = tempfile.TemporaryDirectory()
        self.addCleanup(docasna.cleanup)
        self.slozka = Path(docasna.name) / "prace"
        self.kos = Path(docasna.name) / "kos"
        self.slozka.mkdir()
        self.kos.mkdir()

        # mock.patch dočasně vymění op.send2trash za naši funkci.
        def falesny_kos(cesta: str) -> None:
            shutil.move(cesta, str(self.kos / Path(cesta).name))

        zaplata = mock.patch.object(op, "send2trash", side_effect=falesny_kos)
        self.send2trash = zaplata.start()
        self.addCleanup(zaplata.stop)

    def vytvor(self, nazev: str, obsah: str = "x") -> Path:
        """Pomocník: vytvoří soubor (i s podsložkami) a vrátí jeho cestu."""
        cesta = self.slozka / nazev
        cesta.parent.mkdir(parents=True, exist_ok=True)
        cesta.write_text(obsah, encoding="utf-8")
        return cesta

    def nazvy(self, slozka: Path = None) -> list[str]:
        return sorted(p.name for p in (slozka or self.slozka).iterdir())


class TestOchrana(TestSDocasnouSlozkou):

    def test_systemove_slozky_jsou_chranene(self):
        systemova = Path(op.CHRANENE_SLOZKY[0])
        self.assertTrue(op.je_chranena(systemova))
        self.assertTrue(op.je_chranena(systemova / "neco" / "soubor.txt"))
        self.assertTrue(op.je_chranena(Path(self.slozka.anchor)))  # kořen disku

    def test_bezna_slozka_chranena_neni(self):
        self.assertFalse(op.je_chranena(self.slozka))

    def test_podobny_nazev_neni_chraneny(self):
        # „C:\Windows2“ nesmí být bráno jako „C:\Windows“.
        self.assertFalse(op.je_chranena(op.CHRANENE_SLOZKY[0] + "2"))

    def test_v_systemove_slozce_nejde_mazat(self):
        with self.assertRaises(op.ChybaOperace):
            op.smaz_do_kose(Path(op.CHRANENE_SLOZKY[0]) / "soubor.txt")
        self.send2trash.assert_not_called()  # do koše se nic neposlalo


class TestVypisAHledani(TestSDocasnouSlozkou):

    def test_vypis_slozky_ma_slozky_prvni(self):
        self.vytvor("b.txt")
        self.vytvor("a.txt")
        (self.slozka / "zzz").mkdir()
        self.assertEqual([p.nazev for p in op.vypis_slozku(self.slozka)],
                         ["zzz", "a.txt", "b.txt"])

    def test_formatovani_velikosti(self):
        self.assertEqual(op.formatuj_velikost(500), "500 B")
        self.assertEqual(op.formatuj_velikost(1536), "1.5 KB")
        self.assertEqual(op.formatuj_velikost(None), "")

    def test_hledani_podle_pripony_i_v_podslozkach(self):
        self.vytvor("a.jpg")
        self.vytvor("pod/b.JPG")
        self.vytvor("c.txt")
        nalezene = op.hledej_soubory(self.slozka, pripona="jpg")
        self.assertEqual(sorted(i.nazev for i in nalezene), ["a.jpg", "b.JPG"])

    def test_hledani_podle_nazvu_a_zastupnych_znaku(self):
        self.vytvor("foto_2024_more.jpg")
        self.vytvor("foto_2023_hory.jpg")
        self.vytvor("ukol.txt")
        self.assertEqual(len(op.hledej_soubory(self.slozka, text_v_nazvu="FOTO")), 2)
        nalezene = op.hledej_soubory(self.slozka, text_v_nazvu="foto_*2024*")
        self.assertEqual([i.nazev for i in nalezene], ["foto_2024_more.jpg"])

    def test_hledani_podle_velikosti(self):
        self.vytvor("maly.txt", "x")
        self.vytvor("velky.txt", "x" * 5000)
        nalezene = op.hledej_soubory(self.slozka, min_bajtu=1000)
        self.assertEqual([i.nazev for i in nalezene], ["velky.txt"])


class TestZakladniOperace(TestSDocasnouSlozkou):

    def setUp(self) -> None:
        super().setUp()
        self.cil = self.slozka / "cil"
        self.cil.mkdir()

    def test_kopirovani_souboru(self):
        zdroj = self.vytvor("a.txt", "ahoj")
        op.kopiruj(zdroj, self.cil)
        self.assertTrue(zdroj.exists())  # originál zůstal
        self.assertEqual((self.cil / "a.txt").read_text(encoding="utf-8"), "ahoj")

    def test_kopirovani_slozky_i_s_obsahem(self):
        self.vytvor("fotky/leto/1.jpg")
        op.kopiruj(self.slozka / "fotky", self.cil)
        self.assertTrue((self.cil / "fotky" / "leto" / "1.jpg").exists())

    def test_bez_souhlasu_se_nic_neprepise(self):
        zdroj = self.vytvor("a.txt", "nový")
        self.vytvor("cil/a.txt", "starý")
        with self.assertRaises(op.ChybaOperace):
            op.kopiruj(zdroj, self.cil)
        self.assertEqual((self.cil / "a.txt").read_text(encoding="utf-8"), "starý")

    def test_prepsana_verze_jde_do_kose(self):
        zdroj = self.vytvor("a.txt", "nový")
        self.vytvor("cil/a.txt", "starý")
        op.kopiruj(zdroj, self.cil, prepsat=True)
        self.assertEqual((self.cil / "a.txt").read_text(encoding="utf-8"), "nový")
        self.assertEqual((self.kos / "a.txt").read_text(encoding="utf-8"), "starý")

    def test_slozku_nejde_kopirovat_do_sebe(self):
        self.vytvor("fotky/1.jpg")
        with self.assertRaises(op.ChybaOperace):
            op.kopiruj(self.slozka / "fotky", self.slozka / "fotky")

    def test_kopie_na_stejne_misto_nesmaze_zdroj(self):
        zdroj = self.vytvor("a.txt")
        with self.assertRaises(op.ChybaOperace):
            op.kopiruj(zdroj, self.slozka, prepsat=True)
        self.assertTrue(zdroj.exists())
        self.send2trash.assert_not_called()

    def test_presun(self):
        zdroj = self.vytvor("a.txt")
        op.presun(zdroj, self.cil)
        self.assertFalse(zdroj.exists())
        self.assertTrue((self.cil / "a.txt").exists())

    def test_prejmenovani(self):
        op.prejmenuj(self.vytvor("a.txt"), "b.txt")
        self.assertIn("b.txt", self.nazvy())
        self.assertNotIn("a.txt", self.nazvy())

    def test_prejmenovani_neprepise_existujici_soubor(self):
        a = self.vytvor("a.txt", "A")
        self.vytvor("b.txt", "B")
        with self.assertRaises(op.ChybaOperace):
            op.prejmenuj(a, "b.txt")
        self.assertEqual((self.slozka / "b.txt").read_text(encoding="utf-8"), "B")

    def test_nepovolene_znaky_v_nazvu(self):
        a = self.vytvor("a.txt")
        for spatny in ["", "  ", "a:b.txt", "a/b.txt", "co?.txt"]:
            with self.assertRaises(op.ChybaOperace):
                op.prejmenuj(a, spatny)

    def test_mazani_jde_do_kose(self):
        a = self.vytvor("a.txt")
        op.smaz_do_kose(a)
        self.assertFalse(a.exists())
        self.assertTrue((self.kos / "a.txt").exists())

    def test_bez_send2trash_se_nemaze_vubec(self):
        a = self.vytvor("a.txt")
        with mock.patch.object(op, "send2trash", None):  # jako by knihovna chyběla
            with self.assertRaises(op.ChybaOperace):
                op.smaz_do_kose(a)
        self.assertTrue(a.exists())


class TestHromadnePrejmenovani(TestSDocasnouSlozkou):

    def test_cislovani_a_zachovani_pripony(self):
        soubory = [self.vytvor("b.png"), self.vytvor("a.JPG")]
        pary = op.navrhni_hromadne_prejmenovani(soubory, "foto", start=7, cislic=3)
        self.assertEqual([(s.name, n.name) for s, n in pary],
                         [("a.JPG", "foto_007.jpg"), ("b.png", "foto_008.png")])
        self.assertEqual(self.nazvy(), ["a.JPG", "b.png"])  # návrh nic nezměnil

    def test_nazvy_se_mohou_prekryvat(self):
        # „b.jpg“ má dostat jméno, které zatím patří jinému souboru ze skupiny.
        soubory = [self.vytvor("b.jpg", "B"), self.vytvor("foto_001.jpg", "F")]
        pary = op.navrhni_hromadne_prejmenovani(soubory, "foto")
        op.proved_hromadne_prejmenovani(pary)
        self.assertEqual(self.nazvy(), ["foto_001.jpg", "foto_002.jpg"])
        self.assertEqual((self.slozka / "foto_001.jpg").read_text(encoding="utf-8"), "B")
        self.assertEqual((self.slozka / "foto_002.jpg").read_text(encoding="utf-8"), "F")

    def test_cizi_soubor_se_neprepise(self):
        a = self.vytvor("a.jpg")
        self.vytvor("foto_001.jpg", "cizí")  # není mezi přejmenovávanými
        pary = op.navrhni_hromadne_prejmenovani([a], "foto")
        with self.assertRaises(op.ChybaOperace):
            op.proved_hromadne_prejmenovani(pary)
        self.assertEqual(self.nazvy(), ["a.jpg", "foto_001.jpg"])

    def test_pri_chybe_se_vse_vrati_zpet(self):
        soubory = [self.vytvor("a.jpg"), self.vytvor("b.jpg"), self.vytvor("c.jpg")]
        pary = op.navrhni_hromadne_prejmenovani(soubory, "foto")
        skutecne_rename = Path.rename
        pocet_volani = 0

        def rename_ktery_selze(cesta, cil):
            nonlocal pocet_volani
            pocet_volani += 1
            if pocet_volani == 5:  # 3× dočasný název, 1× konečný, pak „chyba“
                raise PermissionError(13, "simulovaná chyba", str(cesta))
            return skutecne_rename(cesta, cil)

        with mock.patch.object(Path, "rename", rename_ktery_selze):
            with self.assertRaises(PermissionError):
                op.proved_hromadne_prejmenovani(pary)
        self.assertEqual(self.nazvy(), ["a.jpg", "b.jpg", "c.jpg"])


class TestTrideni(TestSDocasnouSlozkou):

    def test_kategorie_podle_pripony(self):
        self.assertEqual(op.kategorie_souboru("a.JPG"), "Obrázky")
        self.assertEqual(op.kategorie_souboru("a.pdf"), "Dokumenty")
        self.assertEqual(op.kategorie_souboru("a.xyz"), op.OSTATNI)

    def test_roztrideni_do_slozek(self):
        for nazev in ["a.jpg", "b.mp4", "c.docx", "d.xyz"]:
            self.vytvor(nazev)
        self.assertEqual(op.roztrid_podle_typu(self.slozka), 4)
        self.assertEqual(self.nazvy(), ["Dokumenty", "Obrázky", "Ostatní", "Videa"])
        self.assertTrue((self.slozka / "Obrázky" / "a.jpg").exists())

    def test_pri_trideni_se_nic_neprepise(self):
        self.vytvor("a.jpg", "nový")
        self.vytvor("Obrázky/a.jpg", "starý")
        op.roztrid_podle_typu(self.slozka)
        obrazky = self.slozka / "Obrázky"
        self.assertEqual(self.nazvy(obrazky), ["a (1).jpg", "a.jpg"])
        self.assertEqual((obrazky / "a.jpg").read_text(encoding="utf-8"), "starý")


class TestDuplicity(TestSDocasnouSlozkou):

    def test_najde_soubory_se_stejnym_obsahem(self):
        self.vytvor("a.txt", "stejný obsah")
        self.vytvor("pod/kopie.dat", "stejný obsah")   # jiný název i přípona
        self.vytvor("c.txt", "jiný obsah!!")           # stejná délka, jiný obsah
        self.vytvor("d.txt", "úplně jiná délka")
        skupiny = op.najdi_duplicity(self.slozka)
        self.assertEqual(len(skupiny), 1)
        self.assertEqual(sorted(p.name for p in skupiny[0].soubory), ["a.txt", "kopie.dat"])

    def test_prazdne_soubory_nejsou_duplicity(self):
        self.vytvor("a.txt", "")
        self.vytvor("b.txt", "")
        self.assertEqual(op.najdi_duplicity(self.slozka), [])


class TestZip(TestSDocasnouSlozkou):

    def test_zabaleni_a_rozbaleni(self):
        self.vytvor("fotky/leto/1.jpg", "obrázek")
        self.vytvor("ukol.txt", "text")
        archiv = self.slozka / "vse.zip"
        pocet = op.zabal_do_zip([self.slozka / "fotky", self.slozka / "ukol.txt"], archiv)
        self.assertEqual(pocet, 2)

        cil = self.slozka / "rozbaleno"
        self.assertEqual(op.kolize_pri_rozbaleni(archiv, cil), [])
        self.assertEqual(op.rozbal_zip(archiv, cil), 2)
        self.assertEqual((cil / "fotky" / "leto" / "1.jpg").read_text(encoding="utf-8"),
                         "obrázek")
        # Druhé rozbalení by už přepisovalo – funkce to musí ohlásit.
        self.assertEqual(len(op.kolize_pri_rozbaleni(archiv, cil)), 2)

    def test_existujici_archiv_se_neprepise(self):
        archiv = self.vytvor("a.zip", "původní")
        with self.assertRaises(op.ChybaOperace):
            op.zabal_do_zip([self.vytvor("a.txt")], archiv)
        self.assertEqual(archiv.read_text(encoding="utf-8"), "původní")

    def test_skodlivy_archiv_je_odmitnut(self):
        archiv = self.slozka / "zly.zip"
        with zipfile.ZipFile(archiv, "w") as zf:
            zf.writestr("../../mimo.txt", "útok")  # cesta ven z cílové složky
        with self.assertRaises(op.ChybaOperace):
            op.rozbal_zip(archiv, self.slozka / "cil")
        self.assertFalse((self.slozka.parent / "mimo.txt").exists())

    def test_poskozeny_archiv_ma_srozumitelnou_hlasku(self):
        archiv = self.vytvor("neni.zip", "tohle není zip")
        with self.assertRaises(zipfile.BadZipFile) as zachyceno:
            op.rozbal_zip(archiv, self.slozka / "cil")
        self.assertIn("není platný ZIP", op.popis_chyby(zachyceno.exception))


class TestHlasky(unittest.TestCase):

    def test_systemove_chyby_maji_ceskou_hlasku(self):
        self.assertIn("neexistuje", op.popis_chyby(FileNotFoundError(2, "x", "a.txt")))
        self.assertIn("oprávnění", op.popis_chyby(PermissionError(13, "x", "a.txt")))
        self.assertIn("a.txt", op.popis_chyby(PermissionError(13, "x", "a.txt")))


if __name__ == "__main__":
    unittest.main()
