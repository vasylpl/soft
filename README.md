# Správce souborů

Grafický správce souborů v Pythonu (Tkinter). Školní projekt.

## Spuštění

1. Python 3.10 nebo novější (při instalaci na Windows zaškrtněte „tcl/tk and IDLE“).
2. Nainstalujte závislost: `pip install -r requirements.txt`
3. Spusťte: `python main.py`

Bez knihovny `send2trash` program běží, ale mazání je vypnuté (natrvalo nemaže nikdy).

## Co umí

- procházení složek, řazení kliknutím na nadpis sloupce, tlačítko Zpět, panel rychlých míst
- hledání podle názvu (i se zástupnými znaky `*` a `?`), přípony a velikosti
- kopírování, přesun, přejmenování, mazání do koše, nová složka
- hromadné přejmenování s náhledem (`foto_001.jpg`, `foto_002.jpg`, …)
- třídění souborů do složek podle typu
- hledání duplicit podle SHA-256
- zabalení a rozbalení ZIP

## Bezpečnost

- před smazáním a přepsáním se program vždy zeptá
- mazané i přepisované soubory jdou do koše
- systémové složky (Windows, Program Files…) a kořen disku jsou jen pro čtení
- ZIP s cestami mířícími mimo cílovou složku se odmítne

## Klávesové zkratky

| Klávesa | Akce |
|---|---|
| Enter / dvojklik | otevřít složku nebo soubor |
| Backspace, Alt+↑ | o složku výš |
| Alt+← | zpět |
| F2 | přejmenovat |
| Delete | smazat do koše |
| Ctrl+A | vybrat vše |
| Ctrl+F | hledat |
| Ctrl+N | nová složka |
| Ctrl+O | otevřít složku |
| F5 | obnovit |

Pravé tlačítko myši v seznamu otevře nabídku akcí.

## Soubory

- `main.py` – grafické rozhraní (okna, tlačítka, dotazy)
- `operace.py` – logika práce se soubory (bez okna)
- `test_operace.py` – automatické testy logiky

## Testy

```
python -m unittest -v
```

Testy pracují jen v dočasné složce a místo skutečného koše používají náhradní složku.
