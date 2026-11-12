"""
main.py – grafické rozhraní Správce souborů (Tkinter).

Spuštění:  python main.py

Tento soubor řeší jen okna, tlačítka a dotazy na uživatele. Samotnou práci
se soubory dělá modul operace.py.

Třídy:
    SpravceSouboru              – hlavní okno (seznam souborů, menu, tlačítka)
    OknoHledani                 – vyhledávání souborů
    OknoHromadnehoPrejmenovani  – hromadné přejmenování s náhledem
    OknoDuplicit                – výsledky hledání duplicit
"""

from __future__ import annotations

import threading
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import operace as op

FORMAT_DATA = "%d.%m.%Y %H:%M"


# ===========================================================================
# POMOCNÉ FUNKCE
# ===========================================================================

def sklonuj(pocet: int, jeden: str, dva: str, pet: str) -> str:
    """České skloňování po číslovce: 1 soubor, 2–4 soubory, 5 a více souborů."""
    if pocet == 1:
        tvar = jeden
    elif 2 <= pocet <= 4:
        tvar = dva
    else:
        tvar = pet
    return f"{pocet} {tvar}"


def souboru(pocet: int) -> str:
    return sklonuj(pocet, "soubor", "soubory", "souborů")


def polozek(pocet: int) -> str:
    return sklonuj(pocet, "položka", "položky", "položek")


def seznam_nazvu(cesty: list[Path], nejvic: int = 10) -> str:
    """Názvy pod sebou pro dotazy; u dlouhého seznamu zbytek zkrátí."""
    radky = [f"  • {c.name}" for c in cesty[:nejvic]]
    if len(cesty) > nejvic:
        radky.append(f"  … a další ({len(cesty) - nejvic})")
    return "\n".join(radky)


def vytvor_ikony() -> dict[str, tk.PhotoImage]:
    """Nakreslí dvě ikony 16×16 přímo v kódu, takže nepotřebujeme soubory s obrázky.

    put(barva, to=(x1, y1, x2, y2)) vybarví obdélník. Nevybarvené body
    zůstanou průhledné.
    """
    slozka = tk.PhotoImage(width=16, height=16)
    slozka.put("#D9A441", to=(1, 3, 7, 5))      # „ouško“ složky
    slozka.put("#F2C55C", to=(1, 5, 15, 13))    # tělo složky
    slozka.put("#D9A441", to=(1, 12, 15, 13))   # stín dole

    soubor = tk.PhotoImage(width=16, height=16)
    soubor.put("#7A8A99", to=(3, 1, 13, 15))    # obrys listu
    soubor.put("#FFFFFF", to=(4, 2, 12, 14))    # bílý papír
    for y in (5, 8, 11):                        # tři „řádky textu“
        soubor.put("#A9B4BF", to=(6, y, 10, y + 1))
    return {"slozka": slozka, "soubor": soubor}


def vytvor_tabulku(rodic: tk.Widget, sloupce: dict[str, tuple[str, int]],
                   **nastaveni) -> ttk.Treeview:
    """Vytvoří tabulku (Treeview) se svislým posuvníkem.

    sloupce = {"id_sloupce": ("Nadpis", šířka)}. Zvláštní id "#0" znamená
    první („stromový“) sloupec, který jako jediný umí ikonu a odsazení.
    Tabulku používáme ve více oknech, proto je to samostatná funkce.
    """
    ramec = ttk.Frame(rodic)
    ramec.pack(fill="both", expand=True, padx=5, pady=5)
    tabulka = ttk.Treeview(
        ramec, columns=[k for k in sloupce if k != "#0"],
        show="tree headings" if "#0" in sloupce else "headings", **nastaveni)
    for klic, (nadpis, sirka) in sloupce.items():
        tabulka.heading(klic, text=nadpis, anchor="w")
        tabulka.column(klic, width=sirka, anchor="e" if klic == "velikost" else "w")
    posuvnik = ttk.Scrollbar(ramec, orient="vertical", command=tabulka.yview)
    tabulka.configure(yscrollcommand=posuvnik.set)
    tabulka.pack(side="left", fill="both", expand=True)
    posuvnik.pack(side="right", fill="y")
    return tabulka


# ===========================================================================
# HLAVNÍ OKNO
# ===========================================================================

class SpravceSouboru(tk.Tk):
    """Hlavní okno. Dědí z tk.Tk, takže objekt třídy JE samotné okno."""

    # Sloupce hlavní tabulky: id -> (nadpis, šířka v pixelech)
    SLOUPCE = {"#0": ("Název", 400), "velikost": ("Velikost", 90),
               "zmeneno": ("Změněno", 130), "typ": ("Typ", 110)}

    def __init__(self) -> None:
        super().__init__()
        self.title("Správce souborů")
        self.geometry("1100x650")
        self.minsize(820, 420)

        # --- Stav programu (data, která si okno pamatuje) ---
        self.aktualni_slozka = Path.home()
        self._historie: list[Path] = []                 # navštívené složky pro „Zpět“
        self._polozky: list[op.InfoOSouboru] = []       # obsah aktuální složky
        self._radky: dict[str, op.InfoOSouboru] = {}    # id řádku v tabulce -> položka
        self._razeni_sloupec = "#0"                     # podle čeho je seřazeno
        self._razeni_sestupne = False
        self._pracuje_se = False                        # běží operace na pozadí?

        # Ikony si musíme uložit do self, jinak je Python uklidí a zmizí.
        self.ikony = vytvor_ikony()
        # Výška řádku podle velikosti písma, aby se text ani ikona neořízly.
        vyska = tkfont.nametofont("TkDefaultFont").metrics("linespace") + 8
        ttk.Style(self).configure("Treeview", rowheight=max(vyska, 20))

        # --- Sestavení okna (pořadí určuje rozmístění shora dolů) ---
        self._vytvor_menu()
        self._vytvor_adresni_radek()
        self._vytvor_nastrojovou_listu()
        self._vytvor_stavovy_radek()
        self._vytvor_stred()
        self._vytvor_kontextove_menu()
        self._nastav_klavesove_zkratky()
        # Křížek okna: nejdřív se zeptáme, pokud ještě něco běží.
        self.protocol("WM_DELETE_WINDOW", self.ukoncit)

        self.prejdi_do(Path.home())
        if op.send2trash is None:
            messagebox.showwarning(
                "Chybí send2trash",
                "Knihovna send2trash není nainstalovaná, proto je mazání vypnuté.\n\n"
                "Nainstalujte ji příkazem:\n    pip install send2trash")

    # ----- Sestavení okna ---------------------------------------------------

    def _vytvor_menu(self) -> None:
        pruh_menu = tk.Menu(self)  # pruh s menu nahoře okna
        self.config(menu=pruh_menu)

        # Každé menu popíšeme seznamem (text, funkce); None znamená oddělovač.
        nabidky = {
            "Soubor": [("Otevřít složku…    Ctrl+O", self.vybrat_slozku),
                       ("Nová složka…    Ctrl+N", self.nova_slozka),
                       None,
                       ("Konec", self.ukoncit)],
            "Úpravy": [("Kopírovat do…", self.kopirovat),
                       ("Přesunout do…", self.presunout),
                       ("Přejmenovat…    F2", self.prejmenovat),
                       ("Smazat do koše    Delete", self.smazat),
                       None,
                       ("Vybrat vše    Ctrl+A", self.vybrat_vse)],
            "Nástroje": [("Hledat soubory…    Ctrl+F", self.hledat),
                         ("Hromadné přejmenování…", self.hromadne_prejmenovat),
                         ("Roztřídit podle typu…", self.roztridit),
                         ("Najít duplicity…", self.najit_duplicity),
                         None,
                         ("Zabalit do ZIP…", self.zabalit),
                         ("Rozbalit ZIP…", self.rozbalit)],
        }
        for nazev, polozky in nabidky.items():
            pruh_menu.add_cascade(label=nazev, menu=self._vytvor_nabidku(pruh_menu, polozky))

    def _vytvor_nabidku(self, rodic: tk.Widget, polozky: list) -> tk.Menu:
        """Z popisu [(text, funkce), None, …] vyrobí rozbalovací nabídku."""
        menu = tk.Menu(rodic, tearoff=False)
        for polozka in polozky:
            if polozka is None:
                menu.add_separator()
            else:
                menu.add_command(label=polozka[0], command=polozka[1])
        return menu

    def _vytvor_adresni_radek(self) -> None:
        radek = ttk.Frame(self)
        radek.pack(fill="x", padx=5, pady=(5, 0))
        self.tlacitko_zpet = ttk.Button(radek, text="← Zpět", command=self.zpet)
        self.tlacitko_zpet.pack(side="left")
        ttk.Button(radek, text="↑ Nahoru", command=self.nahoru).pack(side="left", padx=3)
        ttk.Button(radek, text="⟳ Obnovit", command=self.obnovit).pack(side="left")
        # StringVar je „proměnná Tkinteru“ – když ji změníme, změní se i text v poli.
        self.cesta_var = tk.StringVar()
        pole = ttk.Entry(radek, textvariable=self.cesta_var)
        pole.pack(side="left", fill="x", expand=True, padx=3)
        pole.bind("<Return>", lambda _e: self.prejdi_do(self.cesta_var.get()))
        ttk.Button(radek, text="Procházet…", command=self.vybrat_slozku).pack(side="left")

    def _vytvor_nastrojovou_listu(self) -> None:
        lista = ttk.Frame(self)
        lista.pack(fill="x", padx=5, pady=(5, 0))
        tlacitka = [("Kopírovat", self.kopirovat), ("Přesunout", self.presunout),
                    ("Přejmenovat", self.prejmenovat), ("Smazat", self.smazat),
                    ("Nová složka", self.nova_slozka), None,
                    ("Hledat", self.hledat), ("Hromadně přejmenovat", self.hromadne_prejmenovat),
                    ("Roztřídit", self.roztridit), ("Duplicity", self.najit_duplicity), None,
                    ("Zabalit ZIP", self.zabalit), ("Rozbalit ZIP", self.rozbalit)]
        for tlacitko in tlacitka:
            if tlacitko is None:
                ttk.Separator(lista, orient="vertical").pack(side="left", fill="y", padx=6)
            else:
                ttk.Button(lista, text=tlacitko[0], command=tlacitko[1]).pack(side="left", padx=1)

    def _vytvor_stavovy_radek(self) -> None:
        """Dolní řádek: vlevo zpráva o poslední akci, vpravo počet položek a výběr."""
        radek = ttk.Frame(self, relief="sunken")
        radek.pack(fill="x", side="bottom")
        self.stav_var = tk.StringVar()
        self.info_var = tk.StringVar()
        ttk.Label(radek, textvariable=self.stav_var, anchor="w",
                  padding=(5, 2)).pack(side="left", fill="x", expand=True)
        ttk.Label(radek, textvariable=self.info_var, padding=(5, 2)).pack(side="right")
        # „Běhající“ ukazatel; zobrazíme ho jen během operace na pozadí.
        self.ukazatel = ttk.Progressbar(radek, mode="indeterminate", length=120)

    def _vytvor_stred(self) -> None:
        """Vlevo panel rychlých míst, vpravo tabulka se soubory."""
        stred = ttk.Frame(self)
        stred.pack(fill="both", expand=True)

        levy = ttk.Frame(stred)
        levy.pack(side="left", fill="y", padx=(5, 0), pady=5)
        ttk.Label(levy, text="Místa").pack(anchor="w")
        self.mista = op.rychla_mista()
        # exportselection=False: výběr v seznamu nezmizí, když klikneme jinam.
        self.mista_box = tk.Listbox(levy, width=16, exportselection=False,
                                    activestyle="none")
        for nazev, _cesta in self.mista:
            self.mista_box.insert("end", nazev)
        self.mista_box.pack(fill="y", expand=True)
        self.mista_box.bind("<<ListboxSelect>>", self._po_vyberu_mista)

        # extended = jde vybrat víc řádků najednou (Ctrl / Shift + klik)
        self.seznam = vytvor_tabulku(stred, self.SLOUPCE, selectmode="extended")
        for sloupec in self.SLOUPCE:
            # „s=sloupec“ si zapamatuje hodnotu pro každé tlačítko zvlášť.
            # Bez toho by všechny nadpisy řadily podle posledního sloupce.
            self.seznam.heading(sloupec, command=lambda s=sloupec: self.serad_podle(s))

        self.seznam.bind("<Double-1>", self._po_dvojkliku)
        self.seznam.bind("<Return>", lambda _e: self.otevrit())
        self.seznam.bind("<Button-3>", self._ukaz_kontextove_menu)
        self.seznam.bind("<<TreeviewSelect>>", lambda _e: self._aktualizuj_info())
        # Tyto klávesy vážeme jen na tabulku – v adresním řádku má Delete mazat text!
        self.seznam.bind("<Delete>", lambda _e: self.smazat())
        self.seznam.bind("<F2>", lambda _e: self.prejmenovat())
        self.seznam.bind("<BackSpace>", lambda _e: self.nahoru())
        self.seznam.bind("<Control-a>", lambda _e: self.vybrat_vse())

    def _vytvor_kontextove_menu(self) -> None:
        """Nabídka, která se objeví po kliknutí pravým tlačítkem do tabulky."""
        self.kontextove_menu = self._vytvor_nabidku(self, [
            ("Otevřít", self.otevrit), None,
            ("Kopírovat do…", self.kopirovat), ("Přesunout do…", self.presunout),
            ("Přejmenovat…", self.prejmenovat), ("Smazat do koše", self.smazat), None,
            ("Zabalit do ZIP…", self.zabalit), ("Rozbalit ZIP…", self.rozbalit), None,
            ("Nová složka…", self.nova_slozka), ("Obnovit", self.obnovit)])

    def _nastav_klavesove_zkratky(self) -> None:
        self.bind("<Control-f>", lambda _e: self.hledat())
        self.bind("<Control-o>", lambda _e: self.vybrat_slozku())
        self.bind("<Control-n>", lambda _e: self.nova_slozka())
        self.bind("<F5>", lambda _e: self.obnovit())
        self.bind("<Alt-Left>", lambda _e: self.zpet())
        self.bind("<Alt-Up>", lambda _e: self.nahoru())

    # ----- Pomocné metody ---------------------------------------------------

    def nastav_stav(self, text: str) -> None:
        self.stav_var.set(text)

    def ukaz_chybu(self, chyba: BaseException) -> None:
        """Každou chybu ukážeme v okně srozumitelnou větou (viz op.popis_chyby)."""
        messagebox.showerror("Chyba", op.popis_chyby(chyba), parent=self)

    def ukaz_chyby(self, chyby: list[str]) -> None:
        """Víc chyb najednou ukáže v JEDNOM okně (ne sto oken po sobě)."""
        if not chyby:
            return
        text = "\n\n".join(chyby[:5])
        if len(chyby) > 5:
            text += f"\n\n… a další chyby ({len(chyby) - 5})"
        messagebox.showerror("Některé položky se nepodařilo zpracovat", text, parent=self)

    def vybrane_cesty(self) -> list[Path]:
        return [self._radky[iid].cesta for iid in self.seznam.selection()]

    def _vyber_nebo_upozorni(self) -> list[Path]:
        """Vrátí vybrané položky; když nic vybráno není, řekne to uživateli."""
        cesty = self.vybrane_cesty()
        if not cesty:
            messagebox.showinfo("Nic není vybráno",
                                "Nejdřív v seznamu vyberte soubor nebo složku.")
        return cesty

    def _aktualizuj_info(self) -> None:
        """Pravá část stavového řádku: počet položek a co je vybráno."""
        text = polozek(len(self._polozky))
        vybrane = [self._radky[iid] for iid in self.seznam.selection()]
        if vybrane:
            # U složek velikost neznáme (None), proto „or 0“.
            velikost = sum(p.velikost or 0 for p in vybrane)
            text += f"   |   vybráno: {len(vybrane)} ({op.formatuj_velikost(velikost)})"
        self.info_var.set(text)

    def spust_na_pozadi(self, prace, po_dokonceni, popis: str) -> bool:
        """Spustí dlouhou operaci ve vlákně, aby okno mezitím nezamrzlo.

        prace(hlas_prubeh)  – běží ve vlákně; NESMÍ sahat na okno (Tkinter
                              není bezpečný pro vlákna). Průběh hlásí textem.
        po_dokonceni(vysl.) – zavolá se v hlavním vlákně, smí měnit okno.

        Hlavní vlákno se každých 150 ms podívá (metoda after), jestli je hotovo.
        Vrací False, pokud se operace nespustila, protože ještě běží jiná.
        """
        if self._pracuje_se:
            messagebox.showinfo("Chvilku strpení", "Ještě probíhá předchozí operace.")
            return False
        self._pracuje_se = True
        self.nastav_stav(popis)
        self.ukazatel.pack(side="right", padx=5)
        self.ukazatel.start(15)
        stav: dict = {"prubeh": None}  # sdílená „schránka“ mezi vlákny

        def hlas_prubeh(text: str) -> None:
            stav["prubeh"] = text

        def ve_vlakne() -> None:
            try:
                stav["vysledek"] = prace(hlas_prubeh)
            except Exception as chyba:  # chybu předáme hlavnímu vláknu
                stav["chyba"] = chyba

        vlakno = threading.Thread(target=ve_vlakne, daemon=True)
        vlakno.start()

        def zkontroluj() -> None:
            if stav["prubeh"]:
                self.nastav_stav(stav["prubeh"])
            if vlakno.is_alive():
                self.after(150, zkontroluj)  # ještě není hotovo, zkusíme za chvíli
                return
            self._pracuje_se = False
            self.ukazatel.stop()
            self.ukazatel.pack_forget()
            if "chyba" in stav:
                self.nastav_stav("Operace se nezdařila.")
                self.ukaz_chybu(stav["chyba"])
            else:
                po_dokonceni(stav["vysledek"])

        self.after(150, zkontroluj)
        return True

    def ukoncit(self) -> None:
        if self._pracuje_se and not messagebox.askyesno(
                "Ukončit?", "Ještě probíhá operace. Když program teď zavřete, "
                "zůstane nedokončená.\n\nOpravdu ukončit?", icon="warning"):
            return
        self.destroy()

    # ----- Procházení -------------------------------------------------------

    def prejdi_do(self, slozka: Path | str, zapsat_do_historie: bool = True) -> None:
        """Načte obsah složky a zobrazí ho."""
        try:
            slozka = Path(slozka).expanduser().resolve()
            polozky = op.vypis_slozku(slozka)
        except Exception as chyba:
            self.ukaz_chybu(chyba)
            self.cesta_var.set(str(self.aktualni_slozka))  # vrátíme původní cestu
            return

        if zapsat_do_historie and slozka != self.aktualni_slozka:
            self._historie.append(self.aktualni_slozka)
        self.tlacitko_zpet.state(["!disabled"] if self._historie else ["disabled"])

        self.aktualni_slozka = slozka
        self._polozky = polozky
        self.cesta_var.set(str(slozka))
        self._vykresli_seznam()

        # V levém panelu zvýrazníme místo, ve kterém právě jsme (pokud tam je).
        self.mista_box.selection_clear(0, "end")
        for i, (_nazev, cesta) in enumerate(self.mista):
            if cesta == slozka:
                self.mista_box.selection_set(i)

        self.nastav_stav("Systémová složka – jen pro čtení, změny jsou zakázané."
                         if op.je_chranena(slozka) else "")

    def _vykresli_seznam(self) -> None:
        """Seřadí položky podle zvoleného sloupce a naplní jimi tabulku."""
        klice = {"#0": lambda p: p.nazev.lower(),
                 "velikost": lambda p: p.velikost or 0,
                 "zmeneno": lambda p: p.zmeneno,
                 "typ": self._typ}
        polozky = sorted(self._polozky, key=klice[self._razeni_sloupec],
                         reverse=self._razeni_sestupne)
        # Druhé řazení dá složky nahoru. Řazení v Pythonu je „stabilní“:
        # položky se stejným klíčem si nechají pořadí z prvního řazení.
        polozky.sort(key=lambda p: not p.je_slozka)

        self.seznam.delete(*self.seznam.get_children())  # vymažeme staré řádky
        self._radky.clear()
        for p in polozky:
            iid = self.seznam.insert(
                "", "end", text=" " + p.nazev,
                image=self.ikony["slozka" if p.je_slozka else "soubor"],
                values=(op.formatuj_velikost(p.velikost),
                        p.zmeneno.strftime(FORMAT_DATA), self._typ(p)))
            self._radky[iid] = p  # zapamatujeme si, který řádek je která položka

        # Šipka v nadpisu ukazuje, podle čeho a jakým směrem je seřazeno.
        for sloupec, (nadpis, _sirka) in self.SLOUPCE.items():
            if sloupec == self._razeni_sloupec:
                nadpis += "  ▼" if self._razeni_sestupne else "  ▲"
            self.seznam.heading(sloupec, text=nadpis)
        self._aktualizuj_info()

    @staticmethod
    def _typ(polozka: op.InfoOSouboru) -> str:
        return "Složka" if polozka.je_slozka else op.kategorie_souboru(polozka.cesta)

    def serad_podle(self, sloupec: str) -> None:
        """Klik na nadpis sloupce: seřadí; druhý klik na stejný sloupec otočí směr."""
        if sloupec == self._razeni_sloupec:
            self._razeni_sestupne = not self._razeni_sestupne
        else:
            self._razeni_sloupec, self._razeni_sestupne = sloupec, False
        self._vykresli_seznam()

    def obnovit(self) -> None:
        self.prejdi_do(self.aktualni_slozka)

    def nahoru(self) -> None:
        self.prejdi_do(self.aktualni_slozka.parent)

    def zpet(self) -> None:
        """Vrátí se do předchozí navštívené složky."""
        if self._historie:
            # pop() vezme poslední složku ze seznamu. Do historie ji znovu
            # nezapisujeme, jinak bychom se točili mezi dvěma složkami.
            self.prejdi_do(self._historie.pop(), zapsat_do_historie=False)

    def vybrat_slozku(self) -> None:
        slozka = filedialog.askdirectory(initialdir=self.aktualni_slozka)
        if slozka:  # prázdný řetězec = uživatel dal Zrušit
            self.prejdi_do(slozka)

    def vybrat_vse(self) -> None:
        self.seznam.selection_set(self.seznam.get_children())

    def oznac_soubor(self, cesta: Path) -> None:
        """Označí v tabulce řádek s danou cestou a posune na něj seznam."""
        for iid, polozka in self._radky.items():
            if polozka.cesta == cesta:
                self.seznam.selection_set(iid)
                self.seznam.see(iid)
                self.seznam.focus(iid)
                break

    def _po_vyberu_mista(self, _udalost=None) -> None:
        vyber = self.mista_box.curselection()
        if vyber:
            self.prejdi_do(self.mista[vyber[0]][1])

    def _po_dvojkliku(self, udalost) -> None:
        # identify_row vrátí "" při kliknutí mimo řádky (třeba na nadpis sloupce).
        if self.seznam.identify_row(udalost.y):
            self.otevrit()

    def _ukaz_kontextove_menu(self, udalost) -> None:
        radek = self.seznam.identify_row(udalost.y)
        # Pravý klik na nevybraný řádek ho nejdřív vybere (jako v Průzkumníku).
        if radek and radek not in self.seznam.selection():
            self.seznam.selection_set(radek)
        self.kontextove_menu.tk_popup(udalost.x_root, udalost.y_root)

    def otevrit(self) -> None:
        """Složku otevře v seznamu, soubor v programu, který k němu patří."""
        cesty = self.vybrane_cesty()
        if not cesty:
            return
        if cesty[0].is_dir():
            self.prejdi_do(cesty[0])
        else:
            try:
                op.otevri_v_systemu(cesty[0])
            except Exception as chyba:
                self.ukaz_chybu(chyba)

    # ----- Základní operace -------------------------------------------------

    def kopirovat(self) -> None:
        self._kopirovat_nebo_presunout(presunout=False)

    def presunout(self) -> None:
        self._kopirovat_nebo_presunout(presunout=True)

    def _kopirovat_nebo_presunout(self, presunout: bool) -> None:
        """Kopírování a přesun se liší jen volanou funkcí, proto mají jednu metodu.

        Má dvě fáze: 1) všechny dotazy na přepsání (v hlavním vlákně),
        2) samotná práce na pozadí, aby okno u velkých souborů nezamrzlo.
        """
        cesty = self._vyber_nebo_upozorni()
        if not cesty:
            return
        akce = "Přesunout" if presunout else "Kopírovat"
        if presunout:
            try:
                op.over_bezpecnost(*cesty)  # ze systémové složky nic nepřesouváme
            except op.ChybaOperace as chyba:
                self.ukaz_chybu(chyba)
                return
        cil = filedialog.askdirectory(title=f"{akce} do složky…",
                                      initialdir=self.aktualni_slozka)
        if not cil:
            return

        # Fáze 1: u každé položky, která v cíli už existuje, se zeptáme.
        ukoly: list[tuple[Path, bool]] = []  # (zdroj, přepsat?)
        for zdroj in cesty:
            prepsat = False
            if op.cilova_cesta(zdroj, cil).exists():
                # Ano = True, Ne = False, Storno = None
                odpoved = messagebox.askyesnocancel(
                    "Položka už existuje",
                    f"V cílové složce už existuje „{zdroj.name}“.\n\n"
                    "Chcete ji přepsat? Původní verze půjde do koše.\n\n"
                    "Ano = přepsat   Ne = přeskočit   Storno = zrušit vše",
                    icon="warning")
                if odpoved is None:
                    return
                if not odpoved:
                    continue
                prepsat = True
            ukoly.append((zdroj, prepsat))
        if not ukoly:
            return

        # Fáze 2: práce ve vlákně. Chyby sbíráme a ukážeme najednou na konci.
        funkce = op.presun if presunout else op.kopiruj

        def prace(prubeh) -> list[str]:
            chyby = []
            for i, (zdroj, prepsat) in enumerate(ukoly, start=1):
                prubeh(f"{akce}: {i}/{len(ukoly)} – {zdroj.name}")
                try:
                    funkce(zdroj, cil, prepsat=prepsat)
                except Exception as chyba:
                    chyby.append(f"{zdroj.name}: {op.popis_chyby(chyba)}")
            return chyby

        def po_dokonceni(chyby: list[str]) -> None:
            self.obnovit()
            hotovo = "Přesunuto" if presunout else "Zkopírováno"
            self.nastav_stav(f"{hotovo}: {polozek(len(ukoly) - len(chyby))} z {len(ukoly)}.")
            self.ukaz_chyby(chyby)

        self.spust_na_pozadi(prace, po_dokonceni, f"{akce}…")

    def prejmenovat(self) -> None:
        cesty = self._vyber_nebo_upozorni()
        if not cesty:
            return
        if len(cesty) > 1:
            messagebox.showinfo("Přejmenovat", "Vyberte jen jednu položku. Pro více "
                                "souborů použijte Hromadné přejmenování.")
            return
        stara = cesty[0]
        novy = simpledialog.askstring("Přejmenovat", "Nový název:",
                                      initialvalue=stara.name, parent=self)
        if not novy or novy == stara.name:
            return
        try:
            nova = op.prejmenuj(stara, novy)
        except Exception as chyba:
            self.ukaz_chybu(chyba)
            return
        self.obnovit()
        self.oznac_soubor(nova)

    def smazat(self) -> None:
        cesty = self._vyber_nebo_upozorni()
        if not cesty:
            return
        try:
            op.over_bezpecnost(*cesty)  # systémové složky odmítneme hned, jednou hláškou
        except op.ChybaOperace as chyba:
            self.ukaz_chybu(chyba)
            return
        # Bezpečnost: před smazáním se vždy zeptáme.
        kolik = sklonuj(len(cesty), "položku", "položky", "položek")
        if not messagebox.askyesno(
                "Smazat do koše?",
                f"Opravdu přesunout do koše {kolik}?\n\n" + seznam_nazvu(cesty),
                icon="warning"):
            return
        chyby = []
        for cesta in cesty:
            try:
                op.smaz_do_kose(cesta)
            except Exception as chyba:
                chyby.append(f"{cesta.name}: {op.popis_chyby(chyba)}")
        self.obnovit()
        self.nastav_stav(f"Do koše přesunuto: {polozek(len(cesty) - len(chyby))} "
                         f"z {len(cesty)}.")
        self.ukaz_chyby(chyby)

    def nova_slozka(self) -> None:
        nazev = simpledialog.askstring("Nová složka", "Název nové složky:",
                                       initialvalue="Nová složka", parent=self)
        if not nazev:
            return
        try:
            nova = op.vytvor_slozku(self.aktualni_slozka, nazev)
        except Exception as chyba:
            self.ukaz_chybu(chyba)
            return
        self.obnovit()
        self.oznac_soubor(nova)

    # ----- Nástroje ---------------------------------------------------------

    def hledat(self) -> None:
        OknoHledani(self)

    def hromadne_prejmenovat(self) -> None:
        # Bereme vybrané soubory; když není vybráno nic, všechny soubory ve složce.
        soubory = [c for c in self.vybrane_cesty() if c.is_file()]
        if not soubory:
            soubory = [p.cesta for p in self._polozky if not p.je_slozka]
        if not soubory:
            messagebox.showinfo("Hromadné přejmenování", "Ve složce nejsou žádné soubory.")
            return
        OknoHromadnehoPrejmenovani(self, soubory)

    def roztridit(self) -> None:
        slozka = self.aktualni_slozka
        try:
            op.over_bezpecnost(slozka)
            plan = op.navrhni_trideni(slozka)
        except Exception as chyba:
            self.ukaz_chybu(chyba)
            return
        if not plan:
            messagebox.showinfo("Roztřídit", "V této složce nejsou žádné soubory k třídění.")
            return

        prehled = "\n".join(f"  {kategorie}: {souboru(len(soubory))}"
                            for kategorie, soubory in sorted(plan.items()))
        if not messagebox.askyesno(
                "Roztřídit podle typu?",
                f"Soubory ve složce\n{slozka}\nse přesunou do podsložek:\n\n{prehled}\n\n"
                "Žádný soubor se nepřepíše (při shodě názvu se přidá číslo). Pokračovat?"):
            return
        try:
            pocet = op.roztrid_podle_typu(slozka, plan)
        except Exception as chyba:
            self.ukaz_chybu(chyba)
            self.obnovit()
            return
        self.obnovit()
        self.nastav_stav(f"Roztříděno: {souboru(pocet)}.")

    def najit_duplicity(self) -> None:
        slozka = self.aktualni_slozka
        if not messagebox.askyesno(
                "Najít duplicity",
                f"Prohledat složku\n{slozka}\nvčetně všech podsložek?\n\n"
                "U velkých složek to může chvíli trvat."):
            return

        def po_dokonceni(skupiny: list[op.SkupinaDuplicit]) -> None:
            if not skupiny:
                self.nastav_stav("Žádné duplicity nenalezeny.")
                messagebox.showinfo("Duplicity", "Žádné duplicitní soubory nebyly nalezeny.")
                return
            kolik = sklonuj(len(skupiny), "skupina", "skupiny", "skupin")
            self.nastav_stav(f"Nalezeno: {kolik} duplicit.")
            OknoDuplicit(self, skupiny)

        self.spust_na_pozadi(lambda prubeh: op.najdi_duplicity(slozka, prubeh),
                             po_dokonceni, "Hledám duplicity…")

    def zabalit(self) -> None:
        cesty = self._vyber_nebo_upozorni()
        if not cesty:
            return
        navrh = (cesty[0].stem if len(cesty) == 1 else "archiv") + ".zip"
        # confirmoverwrite=False: na přepsání se zeptáme sami (a starý soubor dáme do koše).
        cil = filedialog.asksaveasfilename(
            title="Uložit ZIP jako…", initialdir=self.aktualni_slozka,
            initialfile=navrh, defaultextension=".zip",
            filetypes=[("ZIP archiv", "*.zip")], confirmoverwrite=False)
        if not cil:
            return
        cil = Path(cil)
        if cil.suffix.lower() != ".zip":
            cil = cil.with_suffix(".zip")

        if cil.exists():
            if cil in cesty:
                messagebox.showerror("Zabalit do ZIP", "Archiv nemůže přepsat soubor, "
                                     "který se do něj má zabalit. Zvolte jiný název.")
                return
            if not messagebox.askyesno("Archiv už existuje",
                                       f"„{cil.name}“ už existuje. Přepsat?\n"
                                       "Původní archiv půjde do koše.", icon="warning"):
                return
            try:
                op.smaz_do_kose(cil)
            except Exception as chyba:
                self.ukaz_chybu(chyba)
                return

        def po_dokonceni(pocet: int) -> None:
            self.obnovit()
            self.oznac_soubor(cil)
            self.nastav_stav(f"Zabaleno: {souboru(pocet)} do „{cil.name}“.")

        self.spust_na_pozadi(lambda prubeh: op.zabal_do_zip(cesty, cil, prubeh),
                             po_dokonceni, f"Balím do {cil.name}…")

    def rozbalit(self) -> None:
        cesty = self._vyber_nebo_upozorni()
        if not cesty:
            return
        zip_soubor = cesty[0]
        if len(cesty) != 1 or zip_soubor.suffix.lower() != ".zip":
            messagebox.showinfo("Rozbalit ZIP", "Vyberte jeden soubor s příponou .zip.")
            return
        slozka = filedialog.askdirectory(
            title=f"Kam rozbalit? (vytvoří se podsložka „{zip_soubor.stem}“)",
            initialdir=self.aktualni_slozka)
        if not slozka:
            return
        cil = Path(slozka) / zip_soubor.stem  # rozbalíme do podsložky s názvem archivu

        try:
            op.over_bezpecnost(cil)
            kolize = op.kolize_pri_rozbaleni(zip_soubor, cil)
        except Exception as chyba:
            self.ukaz_chybu(chyba)
            return
        if kolize:
            kolik = sklonuj(len(kolize), "existující soubor", "existující soubory",
                            "existujících souborů")
            if not messagebox.askyesno(
                    "Přepsat soubory?",
                    f"Rozbalením se přepíše {kolik}:\n\n" + seznam_nazvu(kolize)
                    + "\n\nPokračovat?", icon="warning"):
                return

        def po_dokonceni(pocet: int) -> None:
            self.obnovit()
            self.oznac_soubor(cil)
            self.nastav_stav(f"Rozbaleno: {souboru(pocet)} do „{cil}“.")

        self.spust_na_pozadi(lambda _prubeh: op.rozbal_zip(zip_soubor, cil),
                             po_dokonceni, f"Rozbaluji {zip_soubor.name}…")


# ===========================================================================
# OKNO HLEDÁNÍ
# ===========================================================================

class OknoHledani(tk.Toplevel):
    """Samostatné okno pro vyhledávání. Toplevel = další okno vedle hlavního."""

    def __init__(self, aplikace: SpravceSouboru) -> None:
        super().__init__(aplikace)
        self.aplikace = aplikace
        self.slozka = aplikace.aktualni_slozka
        self.title("Hledat soubory")
        self.geometry("880x520")
        self.transient(aplikace)  # okno se drží nad hlavním oknem

        formular = ttk.Frame(self, padding=8)
        formular.pack(fill="x")
        ttk.Label(formular, text=f"Hledám ve: {self.slozka} (včetně podsložek)").grid(
            row=0, column=0, columnspan=6, sticky="w", pady=(0, 6))

        # Čtyři vstupní pole. Uložíme si jejich proměnné do slovníku.
        self.pole: dict[str, tk.StringVar] = {}
        popisky = [("nazev", "Název obsahuje:"), ("pripona", "Přípona:"),
                   ("min", "Min. velikost (KB):"), ("max", "Max. velikost (KB):")]
        for i, (klic, popis) in enumerate(popisky):
            radek, sloupec = divmod(i, 2)  # rozmístění do mřížky 2×2
            ttk.Label(formular, text=popis).grid(row=radek + 1, column=sloupec * 2,
                                                 sticky="w", padx=(0, 4), pady=2)
            self.pole[klic] = tk.StringVar()
            vstup = ttk.Entry(formular, textvariable=self.pole[klic], width=30)
            vstup.grid(row=radek + 1, column=sloupec * 2 + 1, sticky="w", padx=(0, 15))
            vstup.bind("<Return>", lambda _e: self.hledej())
            if i == 0:
                vstup.focus_set()  # kurzor rovnou do prvního pole
        ttk.Button(formular, text="Hledat", command=self.hledej).grid(
            row=1, column=4, rowspan=2, sticky="ns")
        ttk.Label(formular, foreground="gray40",
                  text="Tip: v názvu jde použít * (cokoli) a ? (jeden znak), "
                       "např. foto_*2024*").grid(
            row=3, column=0, columnspan=6, sticky="w", pady=(6, 0))

        self.info_var = tk.StringVar(value="Vyplňte alespoň jednu podmínku a stiskněte Hledat.")
        ttk.Label(self, textvariable=self.info_var, padding=(8, 0)).pack(fill="x")

        self.vysledky = vytvor_tabulku(
            self, {"nazev": ("Název", 250), "velikost": ("Velikost", 90),
                   "zmeneno": ("Změněno", 130), "slozka": ("Složka", 370)},
            selectmode="browse")
        self.vysledky.bind("<Double-1>", self._prejdi_k_souboru)
        self.vysledky.bind("<Return>", self._prejdi_k_souboru)
        self._cesty: dict[str, Path] = {}

    def _kb_na_bajty(self, klic: str) -> int | None:
        """Převede text z pole (v KB) na bajty. Prázdné pole = žádná podmínka."""
        text = self.pole[klic].get().strip().replace(",", ".")
        if not text:
            return None
        try:
            return int(float(text) * 1024)
        except ValueError:
            raise op.ChybaOperace(f"Velikost musí být číslo, ne „{text}“.") from None

    def hledej(self) -> None:
        try:
            min_b, max_b = self._kb_na_bajty("min"), self._kb_na_bajty("max")
            if min_b is not None and max_b is not None and min_b > max_b:
                raise op.ChybaOperace("Minimální velikost je větší než maximální.")
        except op.ChybaOperace as chyba:
            messagebox.showerror("Chyba", str(chyba), parent=self)
            return
        nazev, pripona = self.pole["nazev"].get(), self.pole["pripona"].get()
        if not (nazev.strip() or pripona.strip() or min_b is not None or max_b is not None):
            messagebox.showinfo("Hledat", "Zadejte alespoň jednu podmínku.", parent=self)
            return

        spusteno = self.aplikace.spust_na_pozadi(
            lambda prubeh: op.hledej_soubory(self.slozka, nazev, pripona, min_b, max_b, prubeh),
            self._zobraz_vysledky, "Hledám soubory…")
        if spusteno:
            self.info_var.set("Hledám…")

    def _zobraz_vysledky(self, nalezene: list[op.InfoOSouboru]) -> None:
        if not self.winfo_exists():
            return  # uživatel mezitím okno zavřel
        self.vysledky.delete(*self.vysledky.get_children())
        self._cesty.clear()
        for info in nalezene:
            iid = self.vysledky.insert("", "end", values=(
                info.nazev, op.formatuj_velikost(info.velikost),
                info.zmeneno.strftime(FORMAT_DATA), str(info.cesta.parent)))
            self._cesty[iid] = info.cesta

        if not nalezene:
            text = "Nic nenalezeno."
        elif len(nalezene) >= op.MAX_VYSLEDKU:
            text = (f"Zobrazeno prvních {op.MAX_VYSLEDKU} výsledků – "
                    "zkuste podmínky zpřesnit.")
        else:
            text = f"Nalezeno: {souboru(len(nalezene))}. Dvojklikem přejdete do složky."
        self.info_var.set(text)
        self.aplikace.nastav_stav(text)

    def _prejdi_k_souboru(self, _udalost=None) -> None:
        """Dvojklik na výsledek: hlavní okno přejde do složky a soubor označí."""
        vyber = self.vysledky.selection()
        if not vyber:
            return
        cesta = self._cesty[vyber[0]]
        self.aplikace.prejdi_do(cesta.parent)
        self.aplikace.oznac_soubor(cesta)


# ===========================================================================
# OKNO HROMADNÉHO PŘEJMENOVÁNÍ
# ===========================================================================

class OknoHromadnehoPrejmenovani(tk.Toplevel):
    """Zadání vzoru + živý náhled, jak se budou soubory jmenovat."""

    def __init__(self, aplikace: SpravceSouboru, soubory: list[Path]) -> None:
        super().__init__(aplikace)
        self.aplikace = aplikace
        self.soubory = soubory
        self.pary: list[tuple[Path, Path]] = []
        self.title(f"Hromadné přejmenování ({souboru(len(soubory))})")
        self.geometry("680x500")
        self.transient(aplikace)
        self.grab_set()  # modální okno: dokud je otevřené, hlavní okno nereaguje

        formular = ttk.Frame(self, padding=8)
        formular.pack(fill="x")
        self.zaklad = tk.StringVar(value="foto")
        self.start = tk.StringVar(value="1")
        self.cislic = tk.StringVar(value="3")
        self.podle_data = tk.BooleanVar(value=False)
        ttk.Label(formular, text="Základ názvu:").pack(side="left")
        pole = ttk.Entry(formular, textvariable=self.zaklad, width=20)
        pole.pack(side="left", padx=(3, 12))
        pole.focus_set()
        pole.select_range(0, "end")  # text je označený, stačí začít psát
        ttk.Label(formular, text="Začít od:").pack(side="left")
        ttk.Spinbox(formular, from_=0, to=99999, textvariable=self.start, width=6).pack(
            side="left", padx=(3, 12))
        ttk.Label(formular, text="Počet číslic:").pack(side="left")
        ttk.Spinbox(formular, from_=1, to=6, textvariable=self.cislic, width=4).pack(
            side="left", padx=3)
        ttk.Checkbutton(self, text="Číslovat podle data změny (od nejstaršího), "
                        "ne podle abecedy", variable=self.podle_data).pack(
            anchor="w", padx=8)

        self.info_var = tk.StringVar()
        ttk.Label(self, textvariable=self.info_var, padding=(8, 4)).pack(fill="x")
        self.nahled = vytvor_tabulku(self, {"stary": ("Původní název", 310),
                                            "novy": ("Nový název", 310)})

        tlacitka = ttk.Frame(self, padding=8)
        tlacitka.pack(fill="x")
        ttk.Button(tlacitka, text="Zrušit", command=self.destroy).pack(side="right")
        self.tlacitko_ok = ttk.Button(tlacitka, text="Přejmenovat", command=self.proved)
        self.tlacitko_ok.pack(side="right", padx=5)
        self.bind("<Escape>", lambda _e: self.destroy())

        # trace_add: při každé změně kteréhokoli pole se znovu vytvoří náhled.
        for promenna in (self.zaklad, self.start, self.cislic, self.podle_data):
            promenna.trace_add("write", lambda *_: self.obnov_nahled())
        self.obnov_nahled()

    def obnov_nahled(self) -> None:
        self.nahled.delete(*self.nahled.get_children())
        try:
            start, cislic = int(self.start.get()), int(self.cislic.get())
            if start < 0 or not 1 <= cislic <= 6:
                raise ValueError
            self.pary = op.navrhni_hromadne_prejmenovani(
                self.soubory, self.zaklad.get(), start, cislic, self.podle_data.get())
        except ValueError:
            self.pary = []
            self.info_var.set("„Začít od“ musí být číslo od 0 a „Počet číslic“ 1 až 6.")
        except (op.ChybaOperace, OSError) as chyba:
            self.pary = []
            self.info_var.set(op.popis_chyby(chyba))
        else:
            for stary, novy in self.pary:
                self.nahled.insert("", "end", values=(stary.name, novy.name))
            self.info_var.set("Náhled – zatím se nic nepřejmenovalo.")
        self.tlacitko_ok.state(["!disabled"] if self.pary else ["disabled"])

    def proved(self) -> None:
        if not self.pary:
            return
        if not messagebox.askyesno("Potvrzení", f"Přejmenovat {souboru(len(self.pary))}?",
                                   parent=self):
            return
        try:
            pocet = op.proved_hromadne_prejmenovani(self.pary)
        except Exception as chyba:
            messagebox.showerror("Chyba", op.popis_chyby(chyba), parent=self)
            self.aplikace.obnovit()
            return
        self.destroy()
        self.aplikace.obnovit()
        self.aplikace.nastav_stav(f"Přejmenováno: {souboru(pocet)}.")


# ===========================================================================
# OKNO DUPLICIT
# ===========================================================================

class OknoDuplicit(tk.Toplevel):
    """Zobrazí skupiny stejných souborů a umožní vybrané kopie poslat do koše."""

    def __init__(self, aplikace: SpravceSouboru, skupiny: list[op.SkupinaDuplicit]) -> None:
        super().__init__(aplikace)
        self.aplikace = aplikace
        kolik = sklonuj(len(skupiny), "skupina", "skupiny", "skupin")
        self.title(f"Duplicitní soubory – {kolik}")
        self.geometry("880x540")
        self.transient(aplikace)

        zbytecne = sum(s.velikost * (len(s.soubory) - 1) for s in skupiny)
        ttk.Label(self, padding=8, text=(
            f"Duplicity zabírají zbytečně {op.formatuj_velikost(zbytecne)}. "
            "Označte soubory ke smazání (Ctrl+klik), nebo použijte tlačítko dole."
        )).pack(fill="x")

        # Stromová tabulka: skupina je „rodič“, její soubory jsou „děti“.
        self.strom = vytvor_tabulku(self, {"#0": ("Skupina / soubor", 680),
                                           "velikost": ("Velikost", 100)},
                                    selectmode="extended")

        self._cesty: dict[str, Path] = {}         # řádek souboru -> cesta
        self._skupiny: dict[str, list[str]] = {}  # řádek skupiny -> řádky jejích souborů
        for i, skupina in enumerate(skupiny, start=1):
            rodic = self.strom.insert(
                "", "end", open=True,
                text=f"Skupina {i}: {len(skupina.soubory)}× stejný obsah "
                     f"(SHA-256 {skupina.otisk[:12]}…)",
                values=(op.formatuj_velikost(skupina.velikost),))
            self._skupiny[rodic] = []
            for cesta in skupina.soubory:
                iid = self.strom.insert(rodic, "end", text=str(cesta), values=("",),
                                        image=aplikace.ikony["soubor"])
                self._cesty[iid] = cesta
                self._skupiny[rodic].append(iid)

        tlacitka = ttk.Frame(self, padding=8)
        tlacitka.pack(fill="x")
        ttk.Button(tlacitka, text="Označit všechny kromě prvního v každé skupině",
                   command=self.oznac_kopie).pack(side="left")
        ttk.Button(tlacitka, text="Zavřít", command=self.destroy).pack(side="right")
        ttk.Button(tlacitka, text="Smazat označené do koše",
                   command=self.smaz_oznacene).pack(side="right", padx=5)
        self.strom.bind("<Delete>", lambda _e: self.smaz_oznacene())

    def oznac_kopie(self) -> None:
        """V každé skupině ponechá první soubor jako „originál“ a ostatní označí."""
        kopie = [iid for deti in self._skupiny.values() for iid in deti[1:]]
        self.strom.selection_set(kopie)

    def smaz_oznacene(self) -> None:
        oznacene = [iid for iid in self.strom.selection() if iid in self._cesty]
        if not oznacene:
            messagebox.showinfo("Nic není označeno", "Označte soubory ke smazání.", parent=self)
            return

        # Pojistka: nenecháme omylem smazat VŠECHNY kopie – nezůstal by originál.
        cele_skupiny = [r for r, deti in self._skupiny.items()
                        if deti and all(d in oznacene for d in deti)]
        if cele_skupiny and not messagebox.askyesno(
                "Pozor", f"U některých skupin (celkem {len(cele_skupiny)}) jste označili "
                "všechny kopie, takže by nezůstal žádný originál.\n\nOpravdu pokračovat?",
                icon="warning", parent=self):
            return

        cesty = [self._cesty[iid] for iid in oznacene]
        if not messagebox.askyesno(
                "Smazat do koše?", f"Přesunout do koše {souboru(len(cesty))}?\n\n"
                + seznam_nazvu(cesty), icon="warning", parent=self):
            return

        smazano = 0
        chyby = []
        for iid in oznacene:
            try:
                op.smaz_do_kose(self._cesty[iid])
            except Exception as chyba:
                chyby.append(f"{self._cesty[iid].name}: {op.popis_chyby(chyba)}")
                continue
            smazano += 1
            # Smazaný řádek odstraníme i z tabulky a z evidence skupin.
            rodic = self.strom.parent(iid)
            self.strom.delete(iid)
            del self._cesty[iid]
            self._skupiny[rodic].remove(iid)

        # Skupina, kde zbyl jediný soubor (nebo žádný), už není duplicita.
        # Uklízíme až po smyčce; list(...) dělá kopii, protože slovník
        # nejde měnit ve chvíli, kdy ho procházíme.
        for rodic, deti in list(self._skupiny.items()):
            if len(deti) < 2:
                for zbyly in deti:
                    del self._cesty[zbyly]
                del self._skupiny[rodic]
                self.strom.delete(rodic)
        self.aplikace.obnovit()
        self.aplikace.nastav_stav(f"Do koše přesunuto: {souboru(smazano)}.")
        self.aplikace.ukaz_chyby(chyby)
        if not self._skupiny:
            self.destroy()  # všechny duplicity jsou vyřešené


# ===========================================================================
# SPUŠTĚNÍ
# ===========================================================================

if __name__ == "__main__":
    # Tento blok se provede jen při přímém spuštění (python main.py),
    # ne při importu souboru jako modulu.
    SpravceSouboru().mainloop()  # mainloop čeká na kliknutí a jiné události
