"""
operace.py – „mozek“ správce souborů.

V tomto modulu NENÍ žádné okno ani tlačítko, jen funkce, které pracují se
soubory. Grafické rozhraní (main.py) je pouze volá. Výhoda: logiku jde
otestovat i použít bez okna a kód je přehlednější.

Obsah:
    1. Chyby a jejich srozumitelné hlášky
    2. Ochrana systémových složek
    3. Výpis složky
    4. Vyhledávání
    5. Základní operace (kopírovat, přesunout, přejmenovat, smazat)
    6. Hromadné přejmenování
    7. Třídění podle typu
    8. Hledání duplicit
    9. ZIP archivy
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import shutil
import string
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional

# send2trash není ve standardní knihovně. Když chybí, program poběží dál,
# jen mazání bude vypnuté (natrvalo nemažeme NIKDY).
try:
    from send2trash import send2trash
except ImportError:
    send2trash = None

# Typ pro funkci, které posíláme textovou zprávu o průběhu („Hotovo 50/200“).
Prubeh = Optional[Callable[[str], None]]


# ---------------------------------------------------------------------------
# 1. CHYBY
# ---------------------------------------------------------------------------

class ChybaOperace(Exception):
    """Naše vlastní chyba. Text v ní je už napsaný srozumitelně pro uživatele."""


def popis_chyby(chyba: BaseException) -> str:
    """Převede libovolnou výjimku na českou větu, které rozumí i běžný uživatel."""
    if isinstance(chyba, ChybaOperace):
        return str(chyba)

    # Většina chyb souborového systému si pamatuje, o který soubor šlo.
    soubor = getattr(chyba, "filename", None)
    dovetek = f"\n\n{soubor}" if soubor else ""

    # Pořadí je důležité: FileNotFoundError atd. jsou podtřídy OSError,
    # takže obecné OSError musí být až na konci.
    if isinstance(chyba, FileNotFoundError):
        return "Soubor nebo složka neexistuje." + dovetek
    if isinstance(chyba, PermissionError):
        return ("Nemáte oprávnění k této operaci, nebo soubor právě používá "
                "jiný program." + dovetek)
    if isinstance(chyba, FileExistsError):
        return "Soubor nebo složka s tímto názvem už existuje." + dovetek
    if isinstance(chyba, NotADirectoryError):
        return "Zadaná cesta není složka." + dovetek
    if isinstance(chyba, IsADirectoryError):
        return "Zadaná cesta je složka, ale očekával se soubor." + dovetek
    if isinstance(chyba, zipfile.BadZipFile):
        return "Soubor není platný ZIP archiv (je poškozený nebo má jiný formát)."
    if isinstance(chyba, OSError):
        return f"Chyba operačního systému: {chyba.strerror or chyba}" + dovetek
    return f"Neočekávaná chyba: {chyba}"


# ---------------------------------------------------------------------------
# 2. OCHRANA SYSTÉMOVÝCH SLOŽEK
# ---------------------------------------------------------------------------

def _normalizuj(cesta: Path | str) -> str:
    """Vrátí úplnou cestu jako text vhodný k porovnávání.

    resolve() udělá z cesty absolutní a rozbalí zkratky jako „..“.
    normcase() na Windows převede vše na malá písmena, protože tam
    „C:\\Windows“ a „c:\\windows“ je totéž. (Na Linuxu nedělá nic.)
    """
    return os.path.normcase(str(Path(cesta).resolve()))


def _je_uvnitr(cesta: str, slozka: str) -> bool:
    """Je (normalizovaná) cesta stejná jako složka, nebo leží někde v ní?"""
    # Lomítko na konci je nutné: jinak by „C:\\Windows2“ prošlo jako „C:\\Windows“.
    return cesta == slozka or cesta.startswith(slozka.rstrip(os.sep) + os.sep)


def _systemove_slozky() -> list[str]:
    """Seznam složek, do kterých program nikdy nesmí zasahovat."""
    if os.name == "nt":  # Windows – skutečné cesty zjistíme z proměnných prostředí
        kandidati = [
            os.environ.get("SystemRoot", r"C:\Windows"),
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.environ.get("ProgramW6432", r"C:\Program Files"),
            os.environ.get("ProgramData", r"C:\ProgramData"),
        ]
    else:  # Linux a macOS
        kandidati = ["/bin", "/boot", "/dev", "/etc", "/lib", "/lib64", "/proc",
                     "/sbin", "/sys", "/usr", "/var", "/System", "/Library"]
    return [_normalizuj(k) for k in kandidati]


CHRANENE_SLOZKY = _systemove_slozky()


def je_chranena(cesta: Path | str) -> bool:
    """True, pokud jde o systémovou složku, něco v ní, nebo o kořen disku (C:\\, /)."""
    normalizovana = _normalizuj(cesta)
    # Kořen disku poznáme tak, že je sám sobě rodičem.
    if Path(normalizovana).parent == Path(normalizovana):
        return True
    return any(_je_uvnitr(normalizovana, s) for s in CHRANENE_SLOZKY)


def over_bezpecnost(*cesty: Path | str) -> None:
    """Vyhodí ChybaOperace, pokud by operace sahala do chráněného místa."""
    for cesta in cesty:
        if je_chranena(cesta):
            raise ChybaOperace(
                "Z bezpečnostních důvodů nelze měnit systémové složky "
                f"(Windows, Program Files…) ani kořen disku:\n\n{cesta}")


# ---------------------------------------------------------------------------
# 3. VÝPIS SLOŽKY
# ---------------------------------------------------------------------------

@dataclass
class InfoOSouboru:
    """Informace o jedné položce. @dataclass za nás napíše __init__ a další metody."""
    cesta: Path
    velikost: Optional[int]  # v bajtech; u složek None
    zmeneno: datetime
    je_slozka: bool

    @property
    def nazev(self) -> str:
        return self.cesta.name


def info_o_souboru(cesta: Path) -> InfoOSouboru:
    """Zjistí velikost a datum změny. stat() se ptá operačního systému."""
    udaje = cesta.stat()
    je_slozka = cesta.is_dir()
    return InfoOSouboru(
        cesta=cesta,
        velikost=None if je_slozka else udaje.st_size,
        zmeneno=datetime.fromtimestamp(udaje.st_mtime),
        je_slozka=je_slozka,
    )


def vypis_slozku(slozka: Path | str) -> list[InfoOSouboru]:
    """Vrátí obsah složky: nejdřív podsložky, pak soubory, vše podle abecedy."""
    slozka = Path(slozka)
    if not slozka.is_dir():
        raise ChybaOperace(f"Složka neexistuje:\n\n{slozka}")

    polozky = []
    for cesta in slozka.iterdir():  # bez oprávnění vyhodí PermissionError
        try:
            polozky.append(info_o_souboru(cesta))
        except OSError:
            continue  # např. rozbitý zástupce – přeskočíme ho, nebudeme padat
    # Klíč (False, …) je před (True, …), takže složky (not True = False) jdou první.
    polozky.sort(key=lambda p: (not p.je_slozka, p.nazev.lower()))
    return polozky


def formatuj_velikost(bajty: Optional[int]) -> str:
    """1536 -> „1.5 KB“. Dělíme 1024, dokud číslo není menší než 1024."""
    if bajty is None:
        return ""
    if bajty < 1024:
        return f"{bajty} B"
    velikost = float(bajty)
    for jednotka in ("KB", "MB", "GB", "TB"):
        velikost /= 1024
        if velikost < 1024:
            break
    return f"{velikost:.1f} {jednotka}"


def rychla_mista() -> list[tuple[str, Path]]:
    """Seznam (název, cesta) pro levý panel: domovské složky a disky.

    Vrací jen místa, která na tomto počítači opravdu existují.
    """
    domov = Path.home()
    kandidati = [("Domů", domov), ("Plocha", domov / "Desktop"),
                 ("Dokumenty", domov / "Documents"), ("Stažené", domov / "Downloads"),
                 ("Obrázky", domov / "Pictures"), ("Hudba", domov / "Music"),
                 ("Videa", domov / "Videos")]
    if os.name == "nt":
        # Windows: zkusíme písmena disků A–Z a necháme ta, která existují.
        kandidati += [(f"Disk {p}:", Path(f"{p}:\\")) for p in string.ascii_uppercase]
    else:
        kandidati.append(("Kořen /", Path("/")))

    mista = []
    for nazev, cesta in kandidati:
        try:
            if cesta.is_dir():
                mista.append((nazev, cesta))
        except OSError:
            continue  # např. prázdná čtečka karet
    return mista


def otevri_v_systemu(cesta: Path) -> None:
    """Otevře soubor programem, který je k němu v systému přiřazený."""
    if os.name == "nt":
        os.startfile(cesta)  # funguje jen na Windows
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(cesta)])
    else:
        subprocess.Popen(["xdg-open", str(cesta)])


# ---------------------------------------------------------------------------
# 4. VYHLEDÁVÁNÍ
# ---------------------------------------------------------------------------

MAX_VYSLEDKU = 5000  # víc výsledků najednou nezobrazujeme, okno by se zahltilo


def hledej_soubory(slozka: Path | str, text_v_nazvu: str = "", pripona: str = "",
                   min_bajtu: Optional[int] = None, max_bajtu: Optional[int] = None,
                   prubeh: Prubeh = None,
                   max_vysledku: int = MAX_VYSLEDKU) -> list[InfoOSouboru]:
    """Projde složku i všechny podsložky a vrátí soubory, které splní VŠECHNY podmínky.

    Prázdná podmínka (např. text_v_nazvu="") se nekontroluje.
    V názvu jdou použít zástupné znaky: * = cokoli, ? = jeden znak
    (např. „foto_*2024*“). Bez nich stačí, když název text obsahuje.
    """
    text = text_v_nazvu.strip().lower()
    se_zastupnymi_znaky = "*" in text or "?" in text
    pripona = pripona.strip().lower()
    if pripona and not pripona.startswith("."):
        pripona = "." + pripona  # uživatel může napsat „jpg“ i „.jpg“

    nalezene: list[InfoOSouboru] = []
    prohledano = 0
    # os.walk postupně vrací (složka, její_podsložky, její_soubory).
    # Složky bez oprávnění tiše přeskočí, takže kvůli nim nespadne.
    for koren, _podslozky, soubory in os.walk(slozka):
        for jmeno in soubory:
            prohledano += 1
            if prubeh and prohledano % 500 == 0:
                prubeh(f"Prohledáno {prohledano} souborů, nalezeno {len(nalezene)}…")

            # Nejdřív levné kontroly podle jména, teprve pak dotaz na velikost.
            if text:
                if se_zastupnymi_znaky:
                    odpovida = fnmatch.fnmatch(jmeno.lower(), text)
                else:
                    odpovida = text in jmeno.lower()
                if not odpovida:
                    continue
            if pripona and not jmeno.lower().endswith(pripona):
                continue
            try:
                info = info_o_souboru(Path(koren) / jmeno)
            except OSError:
                continue
            if min_bajtu is not None and info.velikost < min_bajtu:
                continue
            if max_bajtu is not None and info.velikost > max_bajtu:
                continue

            nalezene.append(info)
            if len(nalezene) >= max_vysledku:
                return nalezene  # pojistka, aby se okno nezahltilo
    return nalezene


# ---------------------------------------------------------------------------
# 5. ZÁKLADNÍ OPERACE
# ---------------------------------------------------------------------------

ZAKAZANE_ZNAKY = '<>:"/\\|?*'  # znaky, které Windows v názvech nepovolí


def over_nazev(nazev: str) -> str:
    """Zkontroluje nový název souboru a vrátí ho bez mezer na krajích."""
    nazev = nazev.strip()
    if nazev in ("", ".", ".."):
        raise ChybaOperace("Název nesmí být prázdný.")
    spatne = sorted({znak for znak in nazev if znak in ZAKAZANE_ZNAKY})
    if spatne:
        raise ChybaOperace(f"Název obsahuje nepovolené znaky: {' '.join(spatne)}")
    return nazev


def cilova_cesta(zdroj: Path | str, cilova_slozka: Path | str) -> Path:
    """Kam by se soubor dostal po zkopírování/přesunutí do cílové složky."""
    return Path(cilova_slozka) / Path(zdroj).name


def _priprav_cil(zdroj: Path, cilova_slozka: Path, prepsat: bool) -> Path:
    """Společné kontroly pro kopírování i přesun. Vrátí cílovou cestu."""
    if not zdroj.exists():
        raise ChybaOperace(f"Soubor nebo složka neexistuje:\n\n{zdroj}")
    if not cilova_slozka.is_dir():
        raise ChybaOperace(f"Cílová složka neexistuje:\n\n{cilova_slozka}")
    over_bezpecnost(cilova_slozka)

    cil = cilova_cesta(zdroj, cilova_slozka)
    z, c = _normalizuj(zdroj), _normalizuj(cil)
    # Složka zkopírovaná do sebe sama by se kopírovala donekonečna.
    if zdroj.is_dir() and _je_uvnitr(_normalizuj(cilova_slozka), z):
        raise ChybaOperace("Složku nelze zkopírovat ani přesunout do ní samotné.")
    # Kdyby byl zdroj uvnitř cíle (nebo by to byl tentýž soubor), přepsáním
    # cíle bychom smazali i zdroj. Tuhle kontrolu MUSÍME udělat před mazáním.
    if _je_uvnitr(z, c):
        raise ChybaOperace("Zdroj a cíl jsou stejné místo (nebo by přepsáním cíle zmizel i zdroj).")

    if cil.exists():
        if not prepsat:
            raise ChybaOperace(f"V cíli už existuje:\n\n{cil}")
        smaz_do_kose(cil)  # starou verzi nemažeme natrvalo, jde do koše
    return cil


def kopiruj(zdroj: Path | str, cilova_slozka: Path | str, prepsat: bool = False) -> Path:
    """Zkopíruje soubor nebo celou složku do cílové složky."""
    zdroj, cilova_slozka = Path(zdroj), Path(cilova_slozka)
    cil = _priprav_cil(zdroj, cilova_slozka, prepsat)
    if zdroj.is_dir():
        shutil.copytree(zdroj, cil)   # zkopíruje složku i s obsahem
    else:
        shutil.copy2(zdroj, cil)      # copy2 zachová i datum změny
    return cil


def presun(zdroj: Path | str, cilova_slozka: Path | str, prepsat: bool = False) -> Path:
    """Přesune soubor nebo složku. Ze systémové složky nic nevezmeme."""
    zdroj, cilova_slozka = Path(zdroj), Path(cilova_slozka)
    over_bezpecnost(zdroj)
    cil = _priprav_cil(zdroj, cilova_slozka, prepsat)
    shutil.move(str(zdroj), str(cil))  # umí přesun i mezi disky
    return cil


def prejmenuj(cesta: Path | str, novy_nazev: str) -> Path:
    """Přejmenuje soubor/složku. Existující soubor nikdy nepřepíše."""
    cesta = Path(cesta)
    over_bezpecnost(cesta)
    nova = cesta.with_name(over_nazev(novy_nazev))
    # Výjimka: změna jen velikosti písmen (foto.JPG -> foto.jpg) je na Windows
    # pořád tentýž soubor, tu povolíme.
    if nova.exists() and _normalizuj(nova) != _normalizuj(cesta):
        raise ChybaOperace(f"„{nova.name}“ už v této složce existuje.")
    cesta.rename(nova)
    return nova


def smaz_do_kose(cesta: Path | str) -> None:
    """Pošle soubor nebo složku do koše. Natrvalo nemaže nikdy."""
    cesta = Path(cesta)
    over_bezpecnost(cesta)
    if send2trash is None:
        raise ChybaOperace("Chybí knihovna send2trash, proto je mazání vypnuté.\n\n"
                           "Nainstalujte ji příkazem:  pip install send2trash")
    if not cesta.exists():
        raise ChybaOperace(f"Soubor nebo složka neexistuje:\n\n{cesta}")
    send2trash(str(cesta))


def vytvor_slozku(rodic: Path | str, nazev: str) -> Path:
    """Vytvoří novou prázdnou složku."""
    rodic = Path(rodic)
    over_bezpecnost(rodic)
    nova = rodic / over_nazev(nazev)
    nova.mkdir()  # když už existuje, vyhodí FileExistsError
    return nova


# ---------------------------------------------------------------------------
# 6. HROMADNÉ PŘEJMENOVÁNÍ
# ---------------------------------------------------------------------------

def navrhni_hromadne_prejmenovani(soubory: Iterable[Path], zaklad: str, start: int = 1,
                                  cislic: int = 3,
                                  podle_data: bool = False) -> list[tuple[Path, Path]]:
    """Vrátí seznam dvojic (starý název, nový název). Zatím nic nepřejmenuje.

    Příklad: zaklad="foto", start=1, cislic=3 -> foto_001.jpg, foto_002.png, …
    Přípona každého souboru zůstane (jen se převede na malá písmena).
    Čísla se přidělují podle abecedy, nebo (podle_data=True) od nejstaršího
    souboru po nejnovější – to se hodí u fotek.
    """
    zaklad = over_nazev(zaklad)
    if podle_data:
        def klic(p: Path):
            return (p.stat().st_mtime, p.name.lower())
    else:
        def klic(p: Path):
            return p.name.lower()
    serazene = sorted((Path(s) for s in soubory), key=klic)
    pary = []
    for cislo, soubor in enumerate(serazene, start=start):
        # {cislo:0{cislic}d} doplní nuly zleva: 7 -> „007“
        novy_nazev = f"{zaklad}_{cislo:0{cislic}d}{soubor.suffix.lower()}"
        pary.append((soubor, soubor.with_name(novy_nazev)))
    return pary


def proved_hromadne_prejmenovani(pary: list[tuple[Path, Path]]) -> int:
    """Provede přejmenování ze seznamu dvojic. Vrátí počet přejmenovaných.

    Proč dva kroky? Když má být „b.jpg“ -> „foto_001.jpg“ a zároveň
    „foto_001.jpg“ -> „foto_002.jpg“, přímé přejmenování by narazilo na
    obsazený název. Proto všechny soubory nejdřív dostanou dočasná jména
    a teprve potom ta konečná.
    """
    nove = [_normalizuj(novy) for _, novy in pary]
    if len(set(nove)) != len(nove):
        raise ChybaOperace("Některé nové názvy by se opakovaly.")

    # Kontrola PŘEDEM: nesmíme přepsat soubor, který do skupiny nepatří.
    stare = {_normalizuj(stary) for stary, _ in pary}
    for stary, novy in pary:
        over_bezpecnost(stary)
        if novy.exists() and _normalizuj(novy) not in stare:
            raise ChybaOperace(f"Soubor „{novy.name}“ už existuje a nepatří mezi "
                               "přejmenovávané. Nic nebylo přejmenováno.")

    # Soubory, které se už jmenují správně, vynecháme.
    k_prejmenovani = [(s, n) for s, n in pary if s.name != n.name]

    # „Deník“: každé provedené přejmenování si zapíšeme jako (odkud, kam).
    # Když se cokoli pokazí, projdeme deník pozpátku a vše vrátíme.
    denik: list[tuple[Path, Path]] = []

    def prejmenuj_a_zapis(odkud: Path, kam: Path) -> None:
        odkud.rename(kam)
        denik.append((odkud, kam))

    try:
        # Krok 1: dočasné názvy.
        docasne = []
        for i, (stary, novy) in enumerate(k_prejmenovani):
            tmp = stary.with_name(f".prejmenovani_{os.getpid()}_{i}.tmp")
            prejmenuj_a_zapis(stary, tmp)
            docasne.append((tmp, novy))
        # Krok 2: konečné názvy.
        for tmp, novy in docasne:
            prejmenuj_a_zapis(tmp, novy)
    except OSError:
        for odkud, kam in reversed(denik):
            kam.rename(odkud)
        raise
    return len(k_prejmenovani)


# ---------------------------------------------------------------------------
# 7. TŘÍDĚNÍ PODLE TYPU
# ---------------------------------------------------------------------------

# Slovník: název cílové složky -> množina přípon, které do ní patří.
KATEGORIE: dict[str, set[str]] = {
    "Obrázky": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg",
                ".heic", ".tif", ".tiff", ".ico", ".raw"},
    "Dokumenty": {".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md",
                  ".xls", ".xlsx", ".ods", ".csv", ".ppt", ".pptx", ".odp"},
    "Videa": {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".webm", ".flv", ".m4v"},
    "Hudba": {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma"},
    "Archivy": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
    "Programy": {".exe", ".msi", ".bat", ".cmd", ".ps1", ".sh", ".apk",
                 ".dmg", ".deb"},
}
OSTATNI = "Ostatní"

# Skryté systémové soubory, které při třídění necháme na místě.
NETRIDIT = {"desktop.ini", "thumbs.db", ".ds_store"}


def kategorie_souboru(cesta: Path | str) -> str:
    """Podle přípony vrátí název kategorie, např. „Obrázky“."""
    pripona = Path(cesta).suffix.lower()
    for nazev, pripony in KATEGORIE.items():
        if pripona in pripony:
            return nazev
    return OSTATNI


def navrhni_trideni(slozka: Path | str) -> dict[str, list[Path]]:
    """Plán třídění: {"Obrázky": [soubory…], …}. Zatím nic nepřesouvá.

    Bere jen soubory přímo ve složce, podsložky nechává být.
    """
    plan: dict[str, list[Path]] = {}
    for cesta in Path(slozka).iterdir():
        if cesta.is_file() and cesta.name.lower() not in NETRIDIT:
            plan.setdefault(kategorie_souboru(cesta), []).append(cesta)
    return plan


def unikatni_cesta(cesta: Path) -> Path:
    """Když název už existuje, přidá číslo: „a.txt“ -> „a (1).txt“, „a (2).txt“…"""
    if not cesta.exists():
        return cesta
    n = 1
    while True:
        kandidat = cesta.with_name(f"{cesta.stem} ({n}){cesta.suffix}")
        if not kandidat.exists():
            return kandidat
        n += 1


def roztrid_podle_typu(slozka: Path | str,
                       plan: Optional[dict[str, list[Path]]] = None) -> int:
    """Přesune soubory do podsložek podle kategorií. Vrátí počet přesunutých.

    Nic se nepřepisuje: při shodě názvu dostane soubor číslo v závorce.
    """
    slozka = Path(slozka)
    over_bezpecnost(slozka)
    if plan is None:
        plan = navrhni_trideni(slozka)

    pocet = 0
    for kategorie, soubory in plan.items():
        cilova = slozka / kategorie
        cilova.mkdir(exist_ok=True)  # exist_ok: nevadí, když už existuje
        for soubor in soubory:
            shutil.move(str(soubor), str(unikatni_cesta(cilova / soubor.name)))
            pocet += 1
    return pocet


# ---------------------------------------------------------------------------
# 8. HLEDÁNÍ DUPLICIT
# ---------------------------------------------------------------------------

@dataclass
class SkupinaDuplicit:
    otisk: str            # SHA-256 hash obsahu
    velikost: int         # velikost jednoho souboru v bajtech
    soubory: list[Path]   # všechny soubory se stejným obsahem


def spocitej_hash(cesta: Path, velikost_bloku: int = 1024 * 1024) -> str:
    """Spočítá SHA-256 „otisk“ obsahu souboru.

    Stejný obsah má vždy stejný otisk. Soubor čteme po 1 MB, aby se ani
    velké video nemuselo celé vejít do paměti.
    """
    h = hashlib.sha256()
    with open(cesta, "rb") as f:          # "rb" = číst binárně
        while blok := f.read(velikost_bloku):  # := přiřadí a zároveň otestuje
            h.update(blok)
    return h.hexdigest()


def najdi_duplicity(slozka: Path | str, prubeh: Prubeh = None) -> list[SkupinaDuplicit]:
    """Najde soubory se stejným obsahem (včetně podsložek).

    Krok 1: seskupíme soubory podle velikosti. To je rychlé, protože se
            nemusí číst obsah. Soubory s různou velikostí nemohou být stejné.
    Krok 2: hash počítáme jen u souborů, které mají „velikostního dvojníka“.
    """
    podle_velikosti: dict[int, list[Path]] = {}
    for koren, _podslozky, soubory in os.walk(slozka):
        for jmeno in soubory:
            cesta = Path(koren) / jmeno
            try:
                if cesta.is_symlink():
                    continue  # zástupce by se tvářil jako duplicita originálu
                velikost = cesta.stat().st_size
            except OSError:
                continue
            if velikost > 0:  # prázdné soubory nás nezajímají
                podle_velikosti.setdefault(velikost, []).append(cesta)
        if prubeh:
            prubeh(f"Procházím: {koren}")

    kandidati = [s for s in podle_velikosti.values() if len(s) > 1]
    celkem = sum(len(s) for s in kandidati)

    vysledek: list[SkupinaDuplicit] = []
    hotovo = 0
    for skupina in kandidati:
        podle_hashe: dict[str, list[Path]] = {}
        for cesta in skupina:
            hotovo += 1
            if prubeh:
                prubeh(f"Porovnávám obsah: {hotovo}/{celkem}")
            try:
                podle_hashe.setdefault(spocitej_hash(cesta), []).append(cesta)
            except OSError:
                continue  # soubor nejde přečíst – přeskočíme
        for otisk, soubory in podle_hashe.items():
            if len(soubory) > 1:
                velikost = soubory[0].stat().st_size
                vysledek.append(SkupinaDuplicit(otisk, velikost, sorted(soubory)))

    # Nahoru dáme skupiny, které zabírají nejvíc zbytečného místa.
    vysledek.sort(key=lambda s: s.velikost * (len(s.soubory) - 1), reverse=True)
    return vysledek


# ---------------------------------------------------------------------------
# 9. ZIP ARCHIVY
# ---------------------------------------------------------------------------

def zabal_do_zip(polozky: Iterable[Path], cil_zip: Path | str,
                 prubeh: Prubeh = None) -> int:
    """Zabalí soubory a složky do ZIPu. Vrátí počet zabalených souborů.

    Existující archiv nepřepíše – o přepsání rozhoduje uživatel předem.
    """
    cil_zip = Path(cil_zip)
    over_bezpecnost(cil_zip.parent)
    if cil_zip.exists():
        raise ChybaOperace(f"Archiv už existuje:\n\n{cil_zip}")

    cil_normalizovany = _normalizuj(cil_zip)
    pocet = 0

    def pridej(archiv: zipfile.ZipFile, soubor: Path, nazev_v_archivu) -> None:
        nonlocal pocet  # měníme proměnnou z vnější funkce
        archiv.write(soubor, arcname=nazev_v_archivu)
        if soubor.is_file():
            pocet += 1
            if prubeh:
                prubeh(f"Balím: {pocet} souborů – {soubor.name}")

    try:
        # ZIP_DEFLATED = soubory se opravdu zkomprimují (zmenší).
        with zipfile.ZipFile(cil_zip, "w", compression=zipfile.ZIP_DEFLATED) as archiv:
            for polozka in map(Path, polozky):
                if polozka.is_dir():
                    # rglob("*") vrátí všechno uvnitř složky, i v podsložkách.
                    for soubor in polozka.rglob("*"):
                        if _normalizuj(soubor) == cil_normalizovany:
                            continue  # archiv nesmí zabalit sám sebe
                        # arcname = cesta UVNITŘ archivu, např. „Fotky/leto/1.jpg“
                        pridej(archiv, soubor, soubor.relative_to(polozka.parent))
                else:
                    pridej(archiv, polozka, polozka.name)
    except BaseException:
        # Balení selhalo: nedokončený (rozbitý) archiv po sobě uklidíme.
        # Je to soubor, který jsme sami před chvílí vytvořili, ne data uživatele.
        cil_zip.unlink(missing_ok=True)
        raise
    return pocet


def _cesty_v_archivu(archiv: zipfile.ZipFile, cil: Path) -> list[tuple[zipfile.ZipInfo, Path]]:
    """Ke každé položce v archivu spočítá, kam by se rozbalila.

    Bezpečnost („Zip Slip“): škodlivý archiv může obsahovat název jako
    „../../Windows/neco.dll“ a zapsat soubor mimo cílovou složku.
    Proto každou cestu ověříme a při problému odmítneme celý archiv.
    """
    cil_normalizovany = _normalizuj(cil)
    vysledek = []
    for info in archiv.infolist():
        cesta = cil / info.filename
        if not _je_uvnitr(_normalizuj(cesta), cil_normalizovany):
            raise ChybaOperace(f"Archiv obsahuje podezřelou cestu „{info.filename}“, "
                               "která míří mimo cílovou složku. Rozbalení bylo zastaveno.")
        vysledek.append((info, cesta))
    return vysledek


def kolize_pri_rozbaleni(zip_soubor: Path | str, cil: Path | str) -> list[Path]:
    """Vrátí soubory, které by rozbalení přepsalo (abychom se mohli zeptat)."""
    with zipfile.ZipFile(zip_soubor) as archiv:
        return [cesta for info, cesta in _cesty_v_archivu(archiv, Path(cil))
                if not info.is_dir() and cesta.exists()]


def rozbal_zip(zip_soubor: Path | str, cil: Path | str) -> int:
    """Rozbalí ZIP do cílové složky. Vrátí počet rozbalených souborů."""
    cil = Path(cil)
    over_bezpecnost(cil)
    with zipfile.ZipFile(zip_soubor) as archiv:
        polozky = _cesty_v_archivu(archiv, cil)  # nejdřív zkontrolujeme VŠECHNY cesty
        cil.mkdir(parents=True, exist_ok=True)
        archiv.extractall(cil)
    return sum(1 for info, _ in polozky if not info.is_dir())
