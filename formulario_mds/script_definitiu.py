#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ANALITZADOR D'INCIDÈNCIES TIC (Versió Avançada)
===============================================
Llegeix un fitxer XML d'incidències, descarta els registres incoherents i
mostra estadístiques avançades (inclosos drill-down i mapes de calor)
en una interfície de consola interactiva (llibreria `rich`).

Ús:
    python analisis.py                  -> menú interactiu (fitxer per defecte: incidencies.xml)
    python analisis.py dades.xml        -> analitza un altre fitxer
    python analisis.py --resum          -> imprimeix el resum executiu i surt
    python analisis.py --top 20         -> mostra 20 elements als rànquings
    python analisis.py --exportar-json  -> exporta les incidències vàlides a incidencies.json i surt
    python analisis.py --debug          -> en cas d'error inesperat, mostra el detall tècnic

Gestió d'errors: el programa NO ha de mostrar mai un traceback de Python. Tots els
errors previsibles (fitxer inexistent/buit/corrupte, XML mal format, estructura
incorrecta, permisos, arguments erronis, entrades absurdes al menú, Ctrl+C...) es
converteixen en un missatge clar (classe ErrorAplicacio) i el programa surt amb
codi 1. Qualsevol error imprevist queda atrapat a main().

──────────────────────────────────────────────────────────────────────────────
DADES  vs  INFORMACIÓ  (com està organitzat aquest programa)
──────────────────────────────────────────────────────────────────────────────
  1) DADES BRUTES      El que hi ha a l'XML tal qual.
  2) DADES NETES       Registres validats i convertits a tipus reals.
  3) INFORMACIÓ        Dades agregades (estadístiques, temps, matrius).
  4) PRESENTACIÓ       Dibuix de taules i gràfics (rich). Drill-down interactiu.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path


# ══════════════════════════════════════════════════════════════════════════════
#  0. PREPARACIÓ
# ══════════════════════════════════════════════════════════════════════════════
def _rich_disponible() -> bool:
    try:
        import importlib
        importlib.invalidate_caches()
        import rich  # noqa: F401
        from rich.console import Console  # noqa: F401
        return True
    except Exception:
        return False


def _assegura_rich() -> None:
    if _rich_disponible():
        return
    print("Falta la llibreria 'rich', necessària per a la interfície.")
    try:
        if sys.stdin.isatty():
            resposta = input("Vols instal·lar-la ara amb pip? [S/n] ").strip().lower()
            if resposta in ("", "s", "si", "sí", "y", "yes"):
                try:
                    subprocess.check_call([sys.executable, "-m", "pip", "install", "rich"])
                except (subprocess.CalledProcessError, OSError):
                    print("No s'ha pogut instal·lar automàticament (comprova la connexió a Internet).")
                if _rich_disponible():
                    return
                print("La instal·lació no ha funcionat o 'rich' no es pot carregar.")
    except (KeyboardInterrupt, EOFError):
        print("\nOperació cancel·lada.")
        sys.exit(1)
    print("Instal·la-la manualment amb:  pip install rich")
    print("(Si ja està instal·lada, comprova que cap fitxer teu no es digui 'rich.py' "
          "i que utilitzes el mateix Python on l'has instal·lada.)")
    sys.exit(1)

_assegura_rich()

try:
    from rich import box
    from rich.align import Align
    from rich.columns import Columns
    from rich.console import Console, Group
    from rich.markup import escape
    from rich.panel import Panel
    from rich.prompt import Prompt
    from rich.rule import Rule
    from rich.table import Table
    from rich.text import Text
except ImportError as _e:
    print(f"No s'ha pogut carregar la llibreria 'rich' ({_e}).")
    print("Prova de reinstal·lar-la amb:  pip install --upgrade rich")
    sys.exit(1)

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIGURACIÓ
# ══════════════════════════════════════════════════════════════════════════════
BASE_DIR = Path(__file__).resolve().parent
FITXER_PER_DEFECTE = BASE_DIR / "incidencies.xml"
FORMATS_DATA = ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y")
ANY_MINIM = 2000
TOLERANCIA_REPORT = timedelta(0)
LONGITUD_MODEL = (3, 80)

# nivell -> (nom, color)
NIVELLS = {
    1: ("Baix", "green"),
    2: ("Mitjà", "yellow"),
    3: ("Crític", "red"),
}
NIVELL_CRITIC = 3

# Cerca difusa (explorador)
LLINDAR_COINCIDENCIA = 0.85   # a partir d'aquí es considera una coincidència directa
LLINDAR_SUGGERIMENT = 0.50    # per sota, ni tan sols es suggereix
MAX_FILES_CERCA = 15
MAX_LONG_CONSULTA = 100       # caràcters màxims que s'accepten a l'explorador

# Límits de seguretat del fitxer d'entrada
MIDA_MAXIMA = 100 * 1024 * 1024   # 100 MB

CAMPS_XML = {
    "marca_temps": "marca_de_temps",
    "ubicacio": "ubicació_de_l_incidència",
    "data": "data_de_la_incidència",
    "tipus": "tipus_d_equip",
    "model": "marca_i_model_de_l_equip",
    "resum": "resum_del_problema",
    "reincident": "aquesta_incidència_ha_ocorregut_anteriorment",
    "urgencia": "nivell_d_impacte_urgència",
}
CAMPS_OBLIGATORIS = ("marca_temps", "ubicacio", "data", "tipus", "model", "resum", "urgencia")

M_BUIT = "Camp obligatori buit"
M_FORMAT_DATA = "Data amb format invàlid"
M_DATA_ANTIGA = f"Data anterior a l'any {ANY_MINIM}"
M_DATA_FUTURA = "Data futura (posterior a avui)"
M_DATA_POST_REPORT = "Data posterior al moment del report"
M_MARCA_INVALIDA = "Marca de temps invàlida o futura"
M_URGENCIA = "Urgència fora de rang (ha de ser 1-3)"
M_MODEL = "Marca/model d'equip incoherent"

# ══════════════════════════════════════════════════════════════════════════════
#  1. DADES BRUTES
# ══════════════════════════════════════════════════════════════════════════════
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")

def neteja(text: str | None) -> str:
    if not text:
        return ""
    return _CONTROL.sub("", " ".join(text.split()))

@dataclass(frozen=True)
class RegistreBrut:
    num: int
    camps: dict

def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


# ──────────────────────────────────────────────────────────────────────────────
#  Errors controlats: tot el que pot sortir malament es converteix en un
#  ErrorAplicacio amb un missatge entenedor (mai un traceback de Python).
# ──────────────────────────────────────────────────────────────────────────────
class ErrorAplicacio(Exception):
    def __init__(self, titol: str, detall: str = "", consells: tuple | list = ()):
        super().__init__(titol)
        self.titol = titol
        self.detall = detall
        self.consells = tuple(consells)


def _xmls_propers(*carpetes: Path, maxim: int = 8) -> list[str]:
    """Noms dels .xml que hi ha a les carpetes indicades (per suggerir-ne un)."""
    trobats: list[str] = []
    for carpeta in carpetes:
        try:
            for f in sorted(carpeta.iterdir(), key=lambda x: x.name.casefold()):
                if f.is_file() and f.suffix.lower() == ".xml" and f.name not in trobats:
                    trobats.append(f.name)
        except OSError:
            continue
    return trobats[:maxim]


def resol_ruta(text) -> Path:
    """Converteix el que ha escrit l'usuari en una ruta vàlida a un fitxer .xml llegible."""
    brut = str(text).strip().strip("\"'").strip()          # cometes de "arrossegar i deixar"
    if not brut:
        raise ErrorAplicacio("No s'ha indicat cap fitxer.",
                             "El nom del fitxer està buit.",
                             [f"Executa:  python {Path(sys.argv[0]).name} incidencies.xml"])
    if "\x00" in brut:
        raise ErrorAplicacio("El nom del fitxer conté caràcters no vàlids.", repr(brut))

    try:
        candidata = Path(brut).expanduser()
        ruta = candidata
        # Si es dona un nom relatiu i no hi és, provem a la carpeta de l'script
        if not ruta.exists() and not candidata.is_absolute():
            alternativa = BASE_DIR / candidata
            if alternativa.exists():
                ruta = alternativa
        existeix = ruta.exists()
    except (OSError, ValueError, RuntimeError) as e:
        raise ErrorAplicacio("La ruta del fitxer no és vàlida.", f"{brut!r}: {e}")

    if not existeix:
        pistes = _xmls_propers(BASE_DIR, Path.cwd(), maxim=200)
        consells = ["Comprova que el nom està ben escrit (majúscules, accents, extensió .xml)."]
        semblants = difflib.get_close_matches(ruta.name.casefold(), [p.casefold() for p in pistes],
                                              n=3, cutoff=0.75)
        if semblants:
            noms = [next(p for p in pistes if p.casefold() == x) for x in semblants]
            consells.insert(0, "Potser volies dir: " + ", ".join(noms))
        pistes = pistes[:8]
        if ruta.parent != Path(".") and not ruta.parent.exists():
            consells.append(f"La carpeta '{ruta.parent}' no existeix.")
        if pistes:
            consells.append("Fitxers .xml trobats a prop: " + ", ".join(pistes))
        else:
            consells.append(f"No he trobat cap .xml a la carpeta de l'script ({BASE_DIR}).")
        raise ErrorAplicacio("Fitxer no trobat.", str(ruta), consells)

    if ruta.is_dir():
        pistes = _xmls_propers(ruta)
        raise ErrorAplicacio("Has indicat una carpeta, no un fitxer.", str(ruta),
                             ["Indica el fitxer .xml dins d'aquesta carpeta."
                              + (f" Hi ha: {', '.join(pistes)}" if pistes else "")])
    if not ruta.is_file():
        raise ErrorAplicacio("La ruta no és un fitxer normal.", str(ruta))

    if ruta.suffix.lower() != ".xml":
        raise ErrorAplicacio("El fitxer no té l'extensió .xml.",
                             f"{ruta.name}  (extensió: '{ruta.suffix or 'cap'}')",
                             ["Aquest programa només llegeix fitxers XML.",
                              "Si realment és un XML, canvia-li l'extensió a .xml."])

    try:
        mida = ruta.stat().st_size
    except OSError as e:
        raise ErrorAplicacio("No es pot consultar el fitxer.", f"{ruta}: {e.strerror or e}")
    if mida == 0:
        raise ErrorAplicacio("El fitxer està buit (0 bytes).", ruta.name,
                             ["Comprova que l'has desat/exportat correctament."])
    if mida > MIDA_MAXIMA:
        raise ErrorAplicacio("El fitxer és massa gran.",
                             f"{mida / 1024 / 1024:.0f} MB (màxim {MIDA_MAXIMA // 1024 // 1024} MB)")
    return ruta


def _llegeix_bytes(ruta: Path) -> bytes:
    try:
        with open(ruta, "rb") as f:
            return f.read()
    except PermissionError:
        raise ErrorAplicacio("No tens permís per llegir el fitxer.", str(ruta),
                             ["Tanca'l si el tens obert en un altre programa (p. ex. Excel).",
                              "Comprova els permisos del fitxer."])
    except FileNotFoundError:
        raise ErrorAplicacio("El fitxer ha desaparegut mentre es llegia.", str(ruta))
    except IsADirectoryError:
        raise ErrorAplicacio("Has indicat una carpeta, no un fitxer.", str(ruta))
    except MemoryError:
        raise ErrorAplicacio("No hi ha prou memòria per carregar el fitxer.", str(ruta))
    except OSError as e:
        raise ErrorAplicacio("Error del sistema en llegir el fitxer.", f"{ruta}: {e.strerror or e}")


# Signatures de fitxers que sovint es reanomenen a .xml per error
_SIGNATURES = (
    (b"PK\x03\x04", "un fitxer comprimit (.zip, .xlsx, .docx...)"),
    (b"%PDF", "un PDF"),
    (b"\x89PNG", "una imatge PNG"),
    (b"\xff\xd8\xff", "una imatge JPG"),
    (b"GIF8", "una imatge GIF"),
    (b"\xd0\xcf\x11\xe0", "un document antic d'Office (.xls, .doc)"),
    (b"SQLite format 3", "una base de dades SQLite"),
    (b"MZ", "un programa executable"),
    (b"\x7fELF", "un programa executable"),
)

_MISSATGES_XML = (
    ("no element found", "El fitxer s'acaba abans d'hora o no conté cap element XML (truncat o buit)."),
    ("mismatched tag", "Hi ha una etiqueta que no es tanca com toca (o es tanca amb un altre nom)."),
    ("unclosed token", "Hi ha una etiqueta o un text sense acabar (falta un '>' o unes cometes)."),
    ("unclosed cdata", "Hi ha una secció CDATA sense tancar."),
    ("junk after document element", "Hi ha text o etiquetes extra després de l'etiqueta arrel (només n'hi pot haver una)."),
    ("duplicate attribute", "Una etiqueta té un atribut repetit."),
    ("undefined entity", "S'utilitza un símbol '&...;' desconegut (p. ex. '&' sol; ha de ser '&amp;')."),
    ("unbound prefix", "S'utilitza un prefix d'espai de noms que no està declarat."),
    ("xml or text declaration not at start", "La declaració <?xml ...?> ha d'estar al principi absolut del fitxer."),
    ("invalid token", "Hi ha un caràcter no permès en aquesta posició (p. ex. '<' o '&' dins d'un text)."),
    ("not well-formed", "Hi ha un caràcter o una estructura no permesa pel format XML."),
    ("syntax error", "Error de sintaxi: l'estructura de l'XML no és correcta."),
    ("encoding", "La codificació declarada no coincideix amb el contingut real del fitxer."),
    ("reference to invalid character", "Hi ha una referència a un caràcter no permès (&#...;)."),
    ("unknown encoding", "La codificació indicada a la capçalera de l'XML és desconeguda."),
)


def _linia(dades: bytes, num_linia: int) -> str:
    try:
        text = dades.decode("utf-8", errors="replace").splitlines()
        if 1 <= num_linia <= len(text):
            return neteja(text[num_linia - 1])[:110]
    except Exception:
        pass
    return ""


def _revisa_contingut(dades: bytes, nom: str) -> None:
    """Descarta de seguida fitxers que clarament no són XML, amb un missatge precís."""
    inici = dades[:4096]
    if not dades.strip(b"\x00 \t\r\n\xef\xbb\xbf\xff\xfe\xfe\xff"):
        raise ErrorAplicacio("El fitxer no té cap contingut (només espais en blanc).", nom,
                             ["Comprova que l'has desat/exportat correctament."])
    for firma, descripcio in _SIGNATURES:
        if inici.startswith(firma):
            raise ErrorAplicacio("El fitxer no és un XML.",
                                 f"{nom} sembla {descripcio} amb l'extensió canviada a .xml.",
                                 ["Exporta les dades de nou en format XML."])
    # UTF-16 (BOM) pot contenir bytes nuls i és vàlid; qualsevol altre cas amb nuls és binari
    if b"\x00" in inici and not inici.startswith((b"\xff\xfe", b"\xfe\xff")) \
            and not inici.lstrip().startswith((b"\x00<", b"<\x00")):
        raise ErrorAplicacio("El fitxer sembla binari o està corrupte.",
                             f"{nom} conté bytes no textuals.",
                             ["Prova de tornar a descarregar o exportar el fitxer."])
    # Protecció contra entitats malicioses/gegants (p. ex. "billion laughs")
    if b"<!ENTITY" in dades:
        raise ErrorAplicacio("El fitxer conté definicions d'entitats XML (<!ENTITY>).",
                             "Per seguretat no es processen.",
                             ["Un fitxer d'incidències normal no n'hauria de contenir."])
    prefix = dades.lstrip(b"\xef\xbb\xbf \t\r\n")[:200].lower()
    if prefix.startswith((b"<!doctype html", b"<html")):
        raise ErrorAplicacio("El fitxer és una pàgina web (HTML), no un XML d'incidències.", nom)
    if prefix[:1] in (b"{", b"["):
        raise ErrorAplicacio("El fitxer sembla JSON, no XML.", nom)
    if b"<" not in dades:
        raise ErrorAplicacio("El fitxer és text pla, no un XML.",
                             f"{nom} no conté cap etiqueta (<...>).",
                             ["Si és un CSV o un TXT, cal convertir-lo a XML."])


def _parseja_xml(dades: bytes, nom: str) -> ET.Element:
    try:
        return ET.fromstring(dades)
    except ET.ParseError as e:
        linia, columna = getattr(e, "position", (0, 0)) or (0, 0)
        explicacio = ""
        text_error = str(e).lower()
        for clau, missatge in _MISSATGES_XML:
            if clau in text_error:
                explicacio = missatge
                break
        detall = [f"{nom}: l'XML no està ben format."]
        if linia:
            detall.append(f"Error a la línia {linia}, columna {columna + 1}.")
            fragment = _linia(dades, linia)
            if fragment:
                detall.append(f"Línia: {fragment}")
        consells = [explicacio] if explicacio else []
        try:
            dades.decode("utf-8")
        except UnicodeDecodeError:
            if not dades.startswith((b"\xff\xfe", b"\xfe\xff")):
                consells.append("El fitxer no està en UTF-8 (potser és Latin-1/ANSI). "
                                "Desa'l de nou com a UTF-8.")
        consells.append(f"Detall tècnic: {e}")
        raise ErrorAplicacio("L'XML és invàlid o està corrupte.", "\n".join(detall), consells)
    except (ValueError, LookupError, UnicodeError) as e:
        raise ErrorAplicacio("No s'ha pogut interpretar la codificació del fitxer.", f"{nom}: {e}",
                             ["Desa el fitxer de nou en codificació UTF-8."])
    except RecursionError:
        raise ErrorAplicacio("L'XML té una estructura excessivament imbricada.", nom)
    except MemoryError:
        raise ErrorAplicacio("No hi ha prou memòria per processar el fitxer.", nom)


def _nom_etiqueta(tag) -> str | None:
    """Nom de l'etiqueta sense espai de noms ni majúscules; None si no és un element real."""
    if not isinstance(tag, str):
        return None                      # comentaris, instruccions de procés...
    if tag.startswith("{"):
        tag = tag.rsplit("}", 1)[-1]
    return _nfc(tag).casefold()


def llegeix_xml(ruta: Path) -> list[RegistreBrut]:
    ruta = Path(ruta)
    dades = _llegeix_bytes(ruta)
    _revisa_contingut(dades, ruta.name)
    arrel = _parseja_xml(dades, ruta.name)
    del dades

    elements = [e for e in arrel if isinstance(e.tag, str)]
    if not elements:
        raise ErrorAplicacio("L'XML és correcte però no conté cap registre.",
                             f"L'etiqueta arrel <{_nom_etiqueta(arrel.tag)}> no té elements a dins.",
                             ["Un fitxer d'incidències ha de tenir un element per cada incidència."])

    prefixos = {nom: _nfc(p).casefold() for nom, p in CAMPS_XML.items()}
    registres: list[RegistreBrut] = []
    etiquetes_vistes: Counter = Counter()
    for num, element in enumerate(elements, start=1):
        etiquetes = {}
        for fill in element:
            nom_et = _nom_etiqueta(fill.tag)
            if nom_et is None:
                continue
            etiquetes_vistes[nom_et] += 1
            if nom_et not in etiquetes:                      # si es repeteix, mana el primer
                etiquetes[nom_et] = neteja("".join(fill.itertext()))
        camps = {}
        for nom, prefix in prefixos.items():
            camps[nom] = next((v for t, v in etiquetes.items() if t.startswith(prefix)), "")
        registres.append(RegistreBrut(num, camps))

    _comprova_estructura(registres, etiquetes_vistes, ruta.name)
    return registres


def _comprova_estructura(registres: list[RegistreBrut], etiquetes_vistes: Counter, nom: str) -> None:
    """Assegura que l'XML és realment d'incidències i no un XML qualsevol."""
    reconeguts = [c for c in CAMPS_XML if any(r.camps[c] for r in registres)]
    if not reconeguts:
        trobades = ", ".join(sorted(etiquetes_vistes)[:8]) or "cap"
        raise ErrorAplicacio("L'XML és correcte, però no és un fitxer d'incidències.",
                             f"{nom}: no hi ha cap dels camps esperats.",
                             ["Camps esperats (inici del nom de l'etiqueta): " + ", ".join(CAMPS_XML.values()),
                              f"Etiquetes trobades als registres: {trobades}",
                              "Comprova que el fitxer és el correcte i que els registres estan "
                              "directament sota l'etiqueta arrel."])
    absents = [CAMPS_XML[c] for c in CAMPS_OBLIGATORIS if c not in reconeguts]
    if absents:
        raise ErrorAplicacio("Falten camps obligatoris a tot el fitxer.",
                             f"{nom}: aquests camps no apareixen (o estan buits) en cap registre:\n  - "
                             + "\n  - ".join(absents),
                             ["Probablement l'XML no té l'estructura esperada o s'ha editat per error.",
                              f"Etiquetes trobades: {', '.join(sorted(etiquetes_vistes)[:8])}"])

# ══════════════════════════════════════════════════════════════════════════════
#  2. DADES NETES
# ══════════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Incidencia:
    num: int
    marca_temps: datetime
    data: datetime
    ubicacio: str
    tipus: str
    model: str
    resum: str
    reincident: str
    urgencia: int

@dataclass(frozen=True)
class Descart:
    num: int
    motiu: str
    detall: str = ""

@dataclass
class ResultatDepuracio:
    valides: list[Incidencia] = field(default_factory=list)
    descartats: list[Descart] = field(default_factory=list)

    def motius(self) -> Counter:
        return Counter(d.motiu for d in self.descartats)

def _parseja_data(text: str) -> datetime | None:
    for format_ in FORMATS_DATA:
        try:
            return datetime.strptime(text, format_)
        except ValueError:
            continue
    return None

def _sense_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")

def _normalitza_reincidencia(text: str) -> str:
    clau = _sense_accents(text).casefold().strip()
    return {"si": "Sí", "no": "No"}.get(clau, "No ho sé")

def _model_valid(model: str) -> bool:
    minim, maxim = LONGITUD_MODEL
    if not (minim <= len(model) <= maxim):
        return False
    if re.search(r"[<>]|\]\]", model):
        return False
    return not re.match(r"(?i)ex\.?\s*:", model)

def valida(reg: RegistreBrut, ara: datetime) -> Incidencia | Descart:
    c = reg.camps
    for clau in CAMPS_OBLIGATORIS:
        if not c[clau]:
            return Descart(reg.num, f"{M_BUIT}: {CAMPS_XML[clau]}")
    marca = _parseja_data(c["marca_temps"])
    if marca is None or marca > ara:
        return Descart(reg.num, M_MARCA_INVALIDA, c["marca_temps"][:40])
    data = _parseja_data(c["data"])
    if data is None:
        return Descart(reg.num, M_FORMAT_DATA, c["data"][:40])
    if data.year < ANY_MINIM:
        return Descart(reg.num, M_DATA_ANTIGA, c["data"][:40])
    if data > ara:
        return Descart(reg.num, M_DATA_FUTURA, c["data"][:40])
    if data > marca + TOLERANCIA_REPORT:
        return Descart(reg.num, M_DATA_POST_REPORT, f"{c['data']} > report {c['marca_temps']}"[:60])
    try:
        urgencia = int(c["urgencia"])
    except ValueError:
        urgencia = -1
    if urgencia not in NIVELLS:
        return Descart(reg.num, M_URGENCIA, c["urgencia"][:40])
    if not _model_valid(c["model"]):
        return Descart(reg.num, M_MODEL, c["model"][:40] + ("…" if len(c["model"]) > 40 else ""))

    return Incidencia(
        num=reg.num, marca_temps=marca, data=data, ubicacio=c["ubicacio"], tipus=c["tipus"],
        model=c["model"], resum=c["resum"], reincident=_normalitza_reincidencia(c["reincident"]),
        urgencia=urgencia,
    )

def depura(registres: list[RegistreBrut], ara: datetime) -> ResultatDepuracio:
    resultat = ResultatDepuracio()
    for reg in registres:
        sortida = valida(reg, ara)
        (resultat.valides if isinstance(sortida, Incidencia) else resultat.descartats).append(sortida)
    return resultat

# ══════════════════════════════════════════════════════════════════════════════
#  3. INFORMACIÓ
# ══════════════════════════════════════════════════════════════════════════════
@dataclass
class Informe:
    total: int = 0
    models: list = field(default_factory=list)
    tipus: list = field(default_factory=list)
    ubicacions: list = field(default_factory=list)
    urgencia: Counter = field(default_factory=Counter)
    reincidencia: Counter = field(default_factory=Counter)
    periode: tuple | None = None

    # Noves mètriques
    retard_mitja: timedelta = timedelta(0)
    retard_mediana: timedelta = timedelta(0)
    dies_setmana: Counter = field(default_factory=Counter)
    hores_dia: Counter = field(default_factory=Counter)
    matriu_ubicacions: list = field(default_factory=list)  # [(ubicacio, total, u1, u2, u3, idx_critic)]
    problemes_freq: list = field(default_factory=list)     # [(resum, n)]

def percentatge(part: int, total: int) -> float:
    return 100.0 * part / total if total else 0.0

def agrupa(valors, critic=None) -> list:
    grups: dict = {}
    for valor, es_critic in valors:
        clau = valor.casefold()
        g = grups.setdefault(clau, {"noms": Counter(), "n": 0, "critics": 0})
        g["noms"][valor] += 1
        g["n"] += 1
        g["critics"] += 1 if es_critic else 0
    files = [(g["noms"].most_common(1)[0][0], g["n"], g["critics"]) for g in grups.values()]
    return sorted(files, key=lambda f: (-f[1], f[0].casefold()))

def agrupa_resums(incidencies: list[Incidencia]) -> list:
    counts = Counter()
    noms = {}
    for i in incidencies:
        clau = i.resum.casefold().strip()
        counts[clau] += 1
        if clau not in noms:
            noms[clau] = i.resum.strip()
    return sorted([(noms[k], v) for k, v in counts.items()], key=lambda x: (-x[1], x[0]))

def analitza(valides: list[Incidencia]) -> Informe:
    informe = Informe(total=len(valides))
    if not valides:
        return informe

    crit = lambda i: i.urgencia == NIVELL_CRITIC
    informe.models = [(n, q) for n, q, _ in agrupa((i.model, crit(i)) for i in valides)]
    informe.tipus = [(n, q) for n, q, _ in agrupa((i.tipus, crit(i)) for i in valides)]
    informe.ubicacions = agrupa((i.ubicacio, crit(i)) for i in valides)
    informe.urgencia = Counter(i.urgencia for i in valides)
    informe.reincidencia = Counter(i.reincident for i in valides)
    dates = [i.data for i in valides]
    informe.periode = (min(dates), max(dates))

    # Anàlisi Temporal (Retràs)
    retards = []
    for i in valides:
        informe.dies_setmana[i.data.weekday()] += 1
        informe.hores_dia[i.data.hour] += 1
        diff = i.marca_temps - i.data
        if diff.total_seconds() >= 0:
            retards.append(diff)
    if retards:
        retards.sort()
        informe.retard_mitja = sum(retards, timedelta(0)) / len(retards)
        informe.retard_mediana = retards[len(retards) // 2]

    # Matriu Punts Calents (Ubicació vs Urgència)
    matriu = {}
    for i in valides:
        k = i.ubicacio.casefold()
        if k not in matriu:
            matriu[k] = {"nom": i.ubicacio, "total": 0, "urgs": Counter()}
        matriu[k]["nom"] = i.ubicacio
        matriu[k]["total"] += 1
        matriu[k]["urgs"][i.urgencia] += 1

    informe.matriu_ubicacions = sorted(
        [(v["nom"], v["total"], v["urgs"][1], v["urgs"][2], v["urgs"][3], (v["urgs"][3] / v["total"] * 100))
         for v in matriu.values()], key=lambda x: (-x[5], -x[1])
    )

    # Rànquing Problemàtiques
    informe.problemes_freq = agrupa_resums(valides)

    return informe

# ══════════════════════════════════════════════════════════════════════════════
#  3b. CERCA DIFUSA (per a l'explorador)
# ══════════════════════════════════════════════════════════════════════════════
def normalitza_cerca(text: str) -> str:
    """Minúscules, sense accents, espais ni símbols: 'Aula 200' -> 'aula200'."""
    return re.sub(r"[^a-z0-9]", "", _sense_accents(text).casefold())

def puntua(consulta: str, candidat: str) -> float:
    """Puntuació de similitud (0-1) entre el que escriu l'usuari i un nom real."""
    q, c = normalitza_cerca(consulta), normalitza_cerca(candidat)
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0
    # Consulta només numèrica ("200"): coincidència amb un número sencer del nom
    if q.isdigit():
        if q in re.findall(r"\d+", candidat):
            return 0.97
        return 0.90 if q in c else 0.0
    if q in c:                       # coincidència parcial ("aula" -> "Aula 200")
        return 0.92
    completa = SequenceMatcher(None, q, c).ratio()
    parcial = 0.0
    if len(q) < len(c):              # millor finestra del nom amb la mida de la consulta
        parcial = 0.9 * max(
            SequenceMatcher(None, q, c[k:k + len(q)]).ratio() for k in range(len(c) - len(q) + 1)
        )
    return max(completa, parcial)

def cerca_difusa(consulta: str, candidats: list[tuple[str, str, int]]) -> tuple[list, list]:
    """
    candidats: [(tipus, nom, n_incidencies)].
    Retorna (coincidencies, suggeriments), ambdues com [(puntuacio, tipus, nom, n)].
    """
    puntuats = [(puntua(consulta, nom), tipus, nom, n) for tipus, nom, n in candidats]
    ordre = lambda t: (-t[0], -t[3], t[2].casefold())
    coincidencies = sorted((p for p in puntuats if p[0] >= LLINDAR_COINCIDENCIA), key=ordre)
    # Si hi ha coincidències exactes/de número sencer, descarta les parcials més fluixes
    if coincidencies and coincidencies[0][0] >= 0.97:
        coincidencies = [p for p in coincidencies if p[0] >= 0.97]
    suggeriments = []
    if not coincidencies:
        suggeriments = sorted((p for p in puntuats if p[0] >= LLINDAR_SUGGERIMENT), key=ordre)[:5]
    return coincidencies, suggeriments

# ══════════════════════════════════════════════════════════════════════════════
#  4. PRESENTACIÓ
# ══════════════════════════════════════════════════════════════════════════════
def pct(valor: float) -> str:
    return f"{valor:.1f}".replace(".", ",") + " %"

def num(n: int) -> str:
    return f"{n:,}".replace(",", ".")

def barra(valor: float, maxim: float, color: str, amplada: int = 24) -> Text:
    """Barra de proporció per als rànquings."""
    plens = round(amplada * valor / maxim) if maxim else 0
    if valor > 0:
        plens = max(1, plens)
    barra_ = Text()
    barra_.append("█" * plens, style=color)
    barra_.append("░" * (amplada - plens), style="grey35")
    return barra_

def barra_fina(valor: float, maxim: float, color: str, amplada: int = 16) -> Text:
    """Barra subtil d'una sola línia fina."""
    plens = round(amplada * valor / maxim) if maxim else 0
    if valor > 0:
        plens = max(1, plens)
    barra_ = Text()
    barra_.append("━" * plens, style=color)
    barra_.append("─" * (amplada - plens), style="grey30")
    return barra_

def barra_apilada(parts: list[tuple[float, str]], amplada: int = 70) -> Text:
    """Una única línia dividida en segments proporcionals (suma = 100 %)."""
    total = sum(v for v, _ in parts)
    text = Text()
    if not total:
        text.append("─" * amplada, style="grey35")
        return text
    segments = [int(v * amplada / total) for v, _ in parts]
    for idx, (v, _) in enumerate(parts):
        if v > 0 and segments[idx] == 0:
            segments[idx] = 1
    diferencia = amplada - sum(segments)
    if diferencia:
        segments[max(range(len(segments)), key=segments.__getitem__)] += diferencia
    for ample, (_, color) in zip(segments, parts):
        text.append("━" * ample, style=color)
    return text

def targeta(titol: str, n: int, total: int, color: str) -> Panel:
    """Targeta amb el percentatge destacat en color i el recompte a sota."""
    cos = Text(justify="center")
    cos.append(pct(percentatge(n, total)), style=f"bold {color}")
    cos.append(f"\n{num(n)} incidències", style="dim")
    return Panel(Align.center(cos), title=Text(titol, style=f"bold {color}"), border_style=color,
                 box=box.ROUNDED, padding=(1, 2))

@dataclass
class Context:
    fitxer: Path
    llegits: int
    depuracio: ResultatDepuracio
    informe: Informe
    top: int

DIES = ["Dilluns", "Dimarts", "Dimecres", "Dijous", "Divendres", "Dissabte", "Diumenge"]

def capcalera(titol: str, subtitol: str = "", color: str = "cyan") -> Panel:
    cos = Text(titol, style=f"bold {color}", justify="center")
    if subtitol:
        cos.append("\n" + subtitol, style="dim")
    return Panel(Align.center(cos), box=box.DOUBLE, border_style=color, padding=(1, 4))

def taula_ranquing(titol: str, files: list, total: int, color: str, etiqueta: str, limit: int | None) -> Table:
    taula = Table(title=titol, box=box.ROUNDED, header_style="bold white", title_style=f"bold {color}",
                  border_style=color, title_justify="left", expand=False)
    taula.add_column("#", justify="center", no_wrap=True)
    taula.add_column(etiqueta, overflow="ellipsis", max_width=36)
    taula.add_column("Incid.", justify="right")
    taula.add_column("%", justify="right")
    taula.add_column("Proporció", no_wrap=True)
    if limit:
        files = files[:limit]
    maxim = files[0][1] if files else 0
    for posicio, (nom, n, *_resta) in enumerate(files, start=1):
        taula.add_row(str(posicio), Text(nom), num(n),
                      pct(percentatge(n, total)), barra(n, maxim, color))
    return taula

def vista_equips(console: Console, ctx: Context) -> None:
    i = ctx.informe
    console.print(taula_ranquing(f"Top {ctx.top} Equips (Marca i Model)", i.models, i.total, "cyan", "Equip", ctx.top))

def _bloc_distribucio(console: Console, titol: str, elements: list[tuple[str, int, str]], total: int) -> None:
    """Barra apilada de 100 % + una targeta per categoria."""
    console.print(Rule(Text(titol, style="bold white"), style="grey50", align="left"))
    console.print()
    console.print(Align.center(barra_apilada([(n, color) for _, n, color in elements], 70)))
    console.print()
    console.print(Columns([targeta(etiq, n, total, color) for etiq, n, color in elements],
                          equal=True, expand=True))

def vista_urgencia(console: Console, ctx: Context) -> None:
    i = ctx.informe
    elements = [(f"{nivell} · {nom}", i.urgencia.get(nivell, 0), color)
                for nivell, (nom, color) in NIVELLS.items()]
    _bloc_distribucio(console, "Distribució per nivell d'urgència", elements, i.total)

def vista_reincidencia(console: Console, ctx: Context) -> None:
    i = ctx.informe
    elements = [
        ("Reincident", i.reincidencia.get("Sí", 0), "red"),
        ("Primera vegada", i.reincidencia.get("No", 0), "green"),
        ("No ho sé", i.reincidencia.get("No ho sé", 0), "grey62"),
    ]
    _bloc_distribucio(console, "Incidències reincidents", elements, i.total)

def vista_ubicacions(console: Console, ctx: Context, limit: int | None = None) -> None:
    i = ctx.informe
    taula = Table(title="Ubicacions amb més incidències", box=box.ROUNDED, border_style="yellow",
                  title_justify="left", title_style="bold yellow", header_style="bold white")
    taula.add_column("#", justify="center")
    taula.add_column("Ubicació")
    taula.add_column("Incid.", justify="right")
    taula.add_column("%", justify="right")
    taula.add_column("Crítiques", justify="right")
    files = i.ubicacions[:limit] if limit else i.ubicacions
    for pos, (nom, n, critics) in enumerate(files, start=1):
        taula.add_row(str(pos), Text(nom), num(n), pct(percentatge(n, i.total)),
                      Text(num(critics), style="red" if critics else "dim"))
    console.print(taula)

def format_td(td: timedelta) -> str:
    dies = td.days
    hores, residu = divmod(td.seconds, 3600)
    minuts = residu // 60
    parts = []
    if dies: parts.append(f"{dies} dies")
    if hores: parts.append(f"{hores} hores")
    if minuts: parts.append(f"{minuts} min")
    return ", ".join(parts) if parts else "< 1 minut"

def vista_temporal(console: Console, ctx: Context) -> None:
    i = ctx.informe
    console.print(capcalera("Anàlisi Temporal i Retràs", color="blue"))
    console.print(f"[bold]Retràs mitjà en el report (SLA):[/] {format_td(i.retard_mitja)}")
    console.print(f"[bold]Retràs medià:[/] {format_td(i.retard_mediana)}\n")

    t_dies = Table(title="Distribució per Dia de la Setmana", box=box.SIMPLE)
    t_dies.add_column("Dia")
    t_dies.add_column("Incidències")
    t_dies.add_column("Gràfic")
    max_d = max(i.dies_setmana.values()) if i.dies_setmana else 0
    for idx, dia in enumerate(DIES):
        n = i.dies_setmana.get(idx, 0)
        t_dies.add_row(dia, str(n), barra(n, max_d, "blue", 20))
    console.print(t_dies)

def vista_hotspots(console: Console, ctx: Context) -> None:
    i = ctx.informe
    taula = Table(title="Matriu de Punts Calents (Ubicació × Urgència)", box=box.ROUNDED, border_style="red",
                  title_justify="left", title_style="bold red", header_style="bold white")
    taula.add_column("Estat")
    taula.add_column("Ubicació")
    taula.add_column("Total", justify="right")
    taula.add_column("Baixa", justify="right", style="green")
    taula.add_column("Mitjana", justify="right", style="yellow")
    taula.add_column("Crítica", justify="right", style="bold red")
    taula.add_column("Índex de Criticitat", justify="right", style="bold")

    for nom, total, u1, u2, u3, idx in i.matriu_ubicacions[:ctx.top]:
        if idx > 40:
            alerta = Text("ALERTA", style="bold red")
        elif idx > 20:
            alerta = Text("ALT", style="red")
        elif idx > 0:
            alerta = Text("MITJÀ", style="yellow")
        else:
            alerta = Text("BAIX", style="green")
        taula.add_row(alerta, Text(nom), str(total), str(u1), str(u2), str(u3), pct(idx))
    console.print(taula)

def vista_problemes_freq(console: Console, ctx: Context) -> None:
    i = ctx.informe
    taula = Table(title=f"Top {ctx.top} Problemàtiques Més Freqüents", box=box.ROUNDED, border_style="magenta",
                  title_justify="left", title_style="bold magenta", header_style="bold white")
    taula.add_column("#")
    taula.add_column("Resum del Problema")
    taula.add_column("Freqüència", justify="right")
    for pos, (resum, n) in enumerate(i.problemes_freq[:ctx.top], start=1):
        taula.add_row(str(pos), Text(resum), str(n))
    console.print(taula)

# ──────────────────────────────────────────────────────────────────────────────
#  Explorador interactiu amb cerca tolerant a errors
# ──────────────────────────────────────────────────────────────────────────────
def _candidats_cerca(ctx: Context) -> list[tuple[str, str, int]]:
    i = ctx.informe
    return ([("Ubicació", nom, n) for nom, n, _ in i.ubicacions] +
            [("Equip", nom, n) for nom, n in i.models])

def _taula_opcions(titol: str, files: list, color: str) -> Table:
    taula = Table(title=titol, box=box.ROUNDED, border_style=color, title_justify="left",
                  title_style=f"bold {color}", header_style="bold white")
    taula.add_column("#", justify="center")
    taula.add_column("Tipus")
    taula.add_column("Nom", overflow="ellipsis", max_width=44)
    taula.add_column("Incid.", justify="right")
    taula.add_column("Coincidència", justify="right")
    for pos, (puntuacio, tipus, nom, n) in enumerate(files, start=1):
        taula.add_row(str(pos), tipus, Text(nom), num(n), pct(puntuacio * 100))
    return taula

def _tria_resultats(console: Console, consulta: str, candidats: list) -> list | None:
    """Resol què ha volgut dir l'usuari. Retorna [(tipus, nom)] o None si cancel·la."""
    coincidencies, suggeriments = cerca_difusa(consulta, candidats)

    if len(coincidencies) == 1:
        _, tipus, nom, _ = coincidencies[0]
        console.print(f"[green]Coincidència trobada:[/] {escape(nom)} [dim]({tipus.lower()})[/]")
        return [(tipus, nom)]

    if coincidencies:
        console.print(_taula_opcions(f"Coincidències per a '{escape(consulta)}'",
                                     coincidencies[:MAX_FILES_CERCA], "green"))
        if len(coincidencies) > MAX_FILES_CERCA:
            console.print(f"[dim]Es mostren {MAX_FILES_CERCA} de {len(coincidencies)} coincidències.[/]")
        ajuda = "Tria un o més números separats per comes, o Intro per analitzar-les totes"
        font, per_defecte = coincidencies, True
    elif suggeriments:
        console.print(f"[yellow]No hi ha cap coincidència directa per a '{escape(consulta)}'.[/]")
        console.print(_taula_opcions("Potser volies dir...", suggeriments, "yellow"))
        ajuda = "Tria un o més números separats per comes, o Intro per cancel·lar"
        font, per_defecte = suggeriments, False
    else:
        console.print(f"[bold red]No s'ha trobat res semblant a '{escape(consulta)}'.[/]")
        return None

    resposta = Prompt.ask(f"[bold]{ajuda}[/]", default="", show_default=False, console=console).strip()
    if not resposta:
        return [(t, n) for _, t, n, _ in font] if per_defecte else None
    triats = []
    visibles = font[:MAX_FILES_CERCA]
    for tros in re.split(r"[,;\s]+", resposta):
        if not (tros.isascii() and tros.isdigit()):
            continue
        posicio = int(tros)
        if 1 <= posicio <= len(visibles):
            _, tipus, nom, _ = visibles[posicio - 1]
            if (tipus, nom) not in triats:
                triats.append((tipus, nom))
    if not triats:
        console.print(f"[red]Selecció no vàlida. Escriu números entre 1 i {len(visibles)}, "
                      "separats per comes.[/]")
        return None
    return triats

def _mostra_drilldown(console: Console, ctx: Context, seleccio: list) -> None:
    ubicacions = {n.casefold() for t, n in seleccio if t == "Ubicació"}
    models = {n.casefold() for t, n in seleccio if t == "Equip"}
    filtrades = [i for i in ctx.depuracio.valides
                 if i.ubicacio.casefold() in ubicacions or i.model.casefold() in models]
    if not filtrades:
        console.print("[bold red]No hi ha incidències per a la selecció.[/]")
        return

    inf = analitza(filtrades)
    noms = ", ".join(n for _, n in seleccio)
    console.print()
    console.print(Rule(Text(f"Anàlisi de: {noms}", style="bold magenta"), style="magenta", align="left"))
    console.print(f"[bold green]{inf.total} incidències trobades.[/]\n")

    t = Table(box=box.SIMPLE, show_header=False)
    t.add_row("% Crítiques:", pct(percentatge(inf.urgencia.get(NIVELL_CRITIC, 0), inf.total)))
    t.add_row("% Reincidència:", pct(percentatge(inf.reincidencia.get("Sí", 0), inf.total)))
    console.print(t)

    console.print(taula_ranquing("Principals Ubicacions", inf.ubicacions, inf.total, "yellow", "Ubicació", 5))

    t_prob = Table(title="Problemes Reportats (Top 5)", box=box.SIMPLE)
    t_prob.add_column("Resum")
    t_prob.add_column("Ocurrències", justify="right")
    for resum, n in inf.problemes_freq[:5]:
        t_prob.add_row(Text(resum), str(n))
    console.print(t_prob)

def _taula_exemples(titol: str, files: list, color: str) -> Table:
    """Llista compacta de noms reals (nom + n. d'incidències) com a inspiració per cercar."""
    taula = Table(title=titol, box=box.SIMPLE_HEAD, title_justify="left", title_style=f"bold {color}",
                  header_style="bold white", border_style=color, expand=False)
    taula.add_column("Nom", overflow="ellipsis", max_width=34)
    taula.add_column("Incid.", justify="right")
    for nom, n in files:
        taula.add_row(Text(nom), num(n))
    return taula

def _mostra_exemples(console: Console, ctx: Context, quantitat: int = 8) -> None:
    """Mostra els elements més freqüents i alguns exemples de cerca abans del primer prompt."""
    i = ctx.informe
    ubicacions = [(nom, n) for nom, n, _ in i.ubicacions[:quantitat]]
    equips = list(i.models[:quantitat])
    console.print(Columns([
        _taula_exemples("Ubicacions més freqüents", ubicacions, "yellow"),
        _taula_exemples("Equips més freqüents", equips, "cyan"),
    ], padding=(0, 4)))

    # Exemples de cerca construïts amb noms reals de les dades
    idees = []
    if ubicacions:
        nom = ubicacions[0][0]
        compacte = normalitza_cerca(nom)
        idees += [nom, compacte]
        numeros = re.findall(r"\d+", nom)
        if numeros:
            idees.append(numeros[0])
    if equips and equips[0][0].split():
        idees.append(equips[0][0].split()[0])
    vistos, exemples = set(), []
    for idea in idees:
        if idea and idea.casefold() not in vistos:
            vistos.add(idea.casefold())
            exemples.append(f"'{idea}'")
    if exemples:
        console.print(Text("Exemples de cerca: ", style="bold") + Text(", ".join(exemples), style="dim"))
    console.print(Text("Pots escriure el nom complet, una part o una versió amb errors; "
                       "si no hi ha coincidència exacta, et suggerirem les opcions més probables.",
                       style="dim"))

def vista_explorador(console: Console, ctx: Context) -> None:
    console.print(capcalera("Explorador Interactiu i Drill-Down",
                            "Cerca equips o ubicacions: tolera espais, accents i errors tipogràfics "
                            "(p. ex. 'aula200', 'aul 200' o '200')", "magenta"))
    candidats = _candidats_cerca(ctx)
    if not candidats:
        console.print("[bold red]No hi ha dades per explorar.[/]")
        return
    _mostra_exemples(console, ctx)
    while True:
        consulta = Prompt.ask("\nModel d'equip o ubicació a analitzar (Intro per sortir)",
                              default="", show_default=False, console=console).strip()
        if not consulta:
            return
        if len(consulta) > MAX_LONG_CONSULTA:
            console.print(f"[red]La cerca és massa llarga (màxim {MAX_LONG_CONSULTA} caràcters).[/]")
            continue
        if not normalitza_cerca(consulta):
            console.print("[red]Introdueix almenys una lletra o un número.[/]")
            continue
        seleccio = _tria_resultats(console, consulta, candidats)
        if seleccio:
            _mostra_drilldown(console, ctx, seleccio)

# ──────────────────────────────────────────────────────────────────────────────
#  Informe de depuració
# ──────────────────────────────────────────────────────────────────────────────
def _panell_resum(titol: str, valor: int, subtitol: str, color: str) -> Panel:
    cos = Text(justify="center")
    cos.append(num(valor), style=f"bold {color}")
    cos.append(f"\n{subtitol}", style="dim")
    return Panel(Align.center(cos), title=Text(titol, style=f"bold {color}"), border_style=color,
                 box=box.ROUNDED, padding=(1, 2))

def vista_depuracio(console: Console, ctx: Context) -> None:
    dep = ctx.depuracio
    n_desc, n_val = len(dep.descartats), len(dep.valides)

    console.print(Rule(Text("Informe de depuració de dades", style="bold white"), style="grey50", align="left"))
    console.print()
    console.print(Columns([
        _panell_resum("Registres llegits", ctx.llegits, f"Fitxer: {ctx.fitxer.name}", "cyan"),
        _panell_resum("Registres vàlids", n_val, pct(percentatge(n_val, ctx.llegits)) + " del total", "green"),
        _panell_resum("Registres descartats", n_desc, pct(percentatge(n_desc, ctx.llegits)) + " del total", "red"),
    ], equal=True, expand=True))

    if not n_desc:
        console.print(Panel(Text("No s'ha descartat cap registre.", style="green"),
                            border_style="green", box=box.ROUNDED))
        return

    console.print()
    console.print(Align.center(barra_apilada([(n_val, "green"), (n_desc, "red")], 70)))
    console.print()

    exemples: dict[str, str] = {}
    for d in dep.descartats:
        if d.detall and d.motiu not in exemples:
            exemples[d.motiu] = d.detall
    motius = sorted(dep.motius().items(), key=lambda kv: (-kv[1], kv[0]))

    taula = Table(title="Desglossament dels motius de descart", title_justify="left",
                  title_style="bold red", box=box.SIMPLE_HEAD, header_style="bold white",
                  border_style="red", show_footer=True, footer_style="bold",
                  row_styles=["", "on grey11"], pad_edge=True, expand=True)
    taula.add_column("#", justify="center", footer="")
    taula.add_column("Motiu del descart", footer="Total descartats", ratio=3, overflow="fold")
    taula.add_column("Registres", justify="right", footer=num(n_desc))
    taula.add_column("% descartats", justify="right", footer="100,0 %")
    taula.add_column("% del total", justify="right", footer=pct(percentatge(n_desc, ctx.llegits)))
    taula.add_column("Distribució", no_wrap=True, footer="")
    taula.add_column("Exemple", style="dim", ratio=2, overflow="ellipsis", no_wrap=True, footer="")
    for pos, (motiu, n) in enumerate(motius, start=1):
        taula.add_row(str(pos), Text(motiu), num(n), pct(percentatge(n, n_desc)),
                      pct(percentatge(n, ctx.llegits)), barra_fina(n, n_desc, "red"),
                      Text(exemples.get(motiu, "—")))
    console.print(taula)

def resum_executiu(console: Console, ctx: Context) -> None:
    i = ctx.informe
    console.print(capcalera("RESUM EXECUTIU D'INCIDÈNCIES TIC"))
    if not i.total:
        vista_depuracio(console, ctx)
        return

    vista_equips(console, ctx)
    console.print()
    vista_ubicacions(console, ctx, limit=5)
    console.print()
    vista_hotspots(console, ctx)
    console.print()
    vista_temporal(console, ctx)

# ──────────────────────────────────────────────────────────────────────────────
#  Exportació a JSON
# ──────────────────────────────────────────────────────────────────────────────
def exportar_a_json(incidencies_netes: list, ruta_json: Path = BASE_DIR / "incidencies.json") -> None:
    """
    Desa les incidències validades a un fitxer JSON gestionant si ja existeix
    (sobreescriure o afegir sense duplicats).
    """
    nous_registres = []
    for inc in incidencies_netes:
        # Generem un ID únic combinant la marca de temps, ubicació i model
        id_unic = f"{inc.marca_temps.strftime('%Y%m%d%H%M%S')}_{inc.ubicacio}_{inc.model}"
        nous_registres.append({
            "id": id_unic,
            "marca_de_temps": inc.marca_temps.strftime("%d/%m/%Y %H:%M:%S"),
            "data_incidencia": inc.data.strftime("%d/%m/%Y %H:%M:%S"),
            "ubicacio": inc.ubicacio,
            "tipus_equip": inc.tipus,
            "model": inc.model,
            "resum": inc.resum,
            "reincident": inc.reincident,
            "urgencia": inc.urgencia
        })

    # 1. Comprovem si el fitxer ja existeix
    if not ruta_json.exists():
        with open(ruta_json, "w", encoding="utf-8") as f:
            json.dump(nous_registres, f, indent=4, ensure_ascii=False)
        print(f"✅ Fitxer '{ruta_json.name}' creat correctament amb {len(nous_registres)} incidències.")
        return

    # 2. Si JA existeix, preguntem a l'usuari què vol fer
    print(f"\n⚠️  El fitxer '{ruta_json.name}' ja existeix.")
    accio = Prompt.ask(
        "Què vols fer?",
        choices=["sobreescriure", "afegir", "cancel·lar"],
        default="afegir"
    )

    if accio == "cancel·lar":
        print("❌ Operació cancel·lada.")
        return

    if accio == "sobreescriure":
        with open(ruta_json, "w", encoding="utf-8") as f:
            json.dump(nous_registres, f, indent=4, ensure_ascii=False)
        print(f"✅ Fitxer sobreescrit amb {len(nous_registres)} incidències.")

    elif accio == "afegir":
        try:
            with open(ruta_json, "r", encoding="utf-8") as f:
                existents = json.load(f)
        except json.JSONDecodeError:
            existents = []

        ids_existents = {item.get("id") for item in existents if "id" in item}
        
        afegides = 0
        for reg in nous_registres:
            if reg["id"] not in ids_existents:
                existents.append(reg)
                ids_existents.add(reg["id"])
                afegides += 1

        with open(ruta_json, "w", encoding="utf-8") as f:
            json.dump(existents, f, indent=4, ensure_ascii=False)
        
        duplicades = len(nous_registres) - afegides
        print(f"✅ S'han afegit {afegides} incidències noves (s'han ignorat {duplicades} duplicades). Total al fitxer: {len(existents)}.")


def vista_exportar_json(console: Console, ctx: Context) -> None:
    """Funció pont perquè el menú pugui cridar exportar_a_json."""
    exportar_a_json(ctx.depuracio.valides, ctx.fitxer.parent / "incidencies.json")


# ──────────────────────────────────────────────────────────────────────────────
#  Menú interactiu (únic lloc on es mantenen els emojis)
# ──────────────────────────────────────────────────────────────────────────────
OPCIONS = {
    "1": ("📋", "Resum executiu complet", resum_executiu),
    "2": ("🔍", "Explorador interactiu (Drill-down per Equip o Ubicació)", vista_explorador),
    "3": ("🔥", "Matriu de Punts Calents (Ubicació × Urgència)", vista_hotspots),
    "4": ("🕒", "Anàlisi Temporal i Retràs de Report (SLA)", vista_temporal),
    "5": ("🏆", "Top d'equips i problemes freqüents", lambda c, ctx: (vista_equips(c, ctx), c.print(), vista_problemes_freq(c, ctx))),
    "6": ("🚦", "Distribució d'urgència i reincidència", lambda c, ctx: (vista_urgencia(c, ctx), c.print(), vista_reincidencia(c, ctx))),
    "7": ("🧹", "Informe de depuració de dades", vista_depuracio),
    "8": ("💾", "Exportar a incidencies.json", vista_exportar_json),
}

def mostra_menu(console: Console, ctx: Context) -> None:
    taula = Table.grid(padding=(0, 2))
    for tecla, (emoji, text, _) in OPCIONS.items():
        taula.add_row(Text(f"[{tecla}]", style="bold cyan"), Text(f"{emoji}  {text}"))
    taula.add_row(Text("[0]", style="bold red"), Text("🚪  Sortir"))
    console.print(capcalera("ANALITZADOR D'INCIDÈNCIES TIC - AVANÇAT", f"Dades vàlides: {num(ctx.informe.total)}"))
    console.print(Panel(taula, title="[bold]MENÚ PRINCIPAL[/]", border_style="cyan", box=box.ROUNDED, padding=(1, 3)))

def executa_vista(console: Console, funcio, ctx: Context) -> None:
    """Executa una vista; si peta, mostra l'error i torna al menú en lloc de tancar el programa."""
    try:
        funcio(console, ctx)
    except (KeyboardInterrupt, EOFError):
        raise
    except BrokenPipeError:
        raise
    except Exception as e:
        mostra_error(console, ErrorAplicacio(
            "No s'ha pogut mostrar aquesta vista.", f"{type(e).__name__}: {e}",
            ["Torna al menú i prova una altra opció."]))

def bucle_menu(console: Console, ctx: Context) -> None:
    while True:
        if console.is_terminal: console.clear()
        mostra_menu(console, ctx)
        if not ctx.informe.total:
            console.print("[bold yellow]Avís: cap registre ha superat la depuració. "
                          "Mira l'opció 7 per veure el motiu.[/]")
        opcio = Prompt.ask("[bold cyan]Tria una opció[/]", choices=[*OPCIONS, "0"], default="1", console=console)
        if opcio == "0":
            console.print("\nFins aviat.\n")
            return
        if console.is_terminal: console.clear()
        executa_vista(console, OPCIONS[opcio][2], ctx)
        console.print()
        console.input("[dim]Prem Intro per tornar al menú...[/] ")


# ──────────────────────────────────────────────────────────────────────────────
#  Arguments de la línia d'ordres (els errors els mostrem nosaltres, no argparse)
# ──────────────────────────────────────────────────────────────────────────────
class _ParserSegur(argparse.ArgumentParser):
    def error(self, message: str):                       # noqa: D401
        traduccions = (("expected one argument", "falta el valor després de l'opció."),
                       ("unrecognized arguments", "arguments no reconeguts:"),
                       ("invalid", "valor no vàlid:"))
        for original, catala in traduccions:
            if original in message:
                message = message.replace(original, catala)
                break
        raise ErrorAplicacio("Arguments incorrectes.", message)

def _enter_positiu(text: str) -> int:
    try:
        valor = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{text}' no és un nombre enter.")
    if valor < 1:
        raise argparse.ArgumentTypeError("ha de ser 1 o més.")
    return min(valor, 1000)

def _llegeix_arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = _ParserSegur(description="Analitza un fitxer XML d'incidències TIC.", add_help=True)
    parser.add_argument("fitxer", nargs="?", default=None, help="Fitxer XML (per defecte: incidencies.xml)")
    parser.add_argument("--resum", action="store_true", help="Mostra el resum executiu i surt")
    parser.add_argument("--top", type=_enter_positiu, default=10, help="Quantitat d'elements dels rànquings")
    parser.add_argument("--exportar-json", action="store_true",
                        help="Exporta les incidències vàlides a incidencies.json i surt")
    parser.add_argument("--debug", action="store_true", help="Mostra els errors tècnics complets")
    args, sobrants = parser.parse_known_args(argv)
    if sobrants:
        coneguts = ["--resum", "--top", "--exportar-json", "--debug", "--help"]
        pistes = []
        for x in sobrants:
            if x.startswith("-"):
                prop = difflib.get_close_matches(x.split("=")[0], coneguts, n=1, cutoff=0.5)
                pistes.append(f"Opció desconeguda '{x}'" + (f" (volies dir '{prop[0]}'?)" if prop else "."))
            else:
                pistes.append(f"Argument inesperat '{x}' (només es pot indicar un fitxer; "
                              "si el nom té espais, posa'l entre cometes).")
        raise ErrorAplicacio("Arguments incorrectes.", "\n".join(pistes),
                             [f"Ús:  python {Path(sys.argv[0]).name} [fitxer.xml] [--resum] [--top N] [--exportar-json]"])
    return args

def mostra_error(console: Console, e: ErrorAplicacio) -> None:
    cos = Text()
    cos.append(e.titol, style="bold red")
    if e.detall:
        cos.append("\n\n" + e.detall)
    for consell in e.consells:
        cos.append("\n→ " + consell, style="yellow")
    console.print(Panel(cos, title="Error", border_style="red", box=box.ROUNDED, padding=(1, 2)))

def _executa(args: argparse.Namespace, console: Console) -> int:
    ruta = resol_ruta(args.fitxer if args.fitxer is not None else FITXER_PER_DEFECTE)

    try:
        with console.status("[cyan]Llegint i analitzant dades...[/]", spinner="dots"):
            registres = llegeix_xml(ruta)
            depuracio = depura(registres, datetime.now())
            informe = analitza(depuracio.valides)
    except MemoryError:
        raise ErrorAplicacio("No hi ha prou memòria per processar el fitxer.", ruta.name)

    ctx = Context(ruta, len(registres), depuracio, informe, args.top)

    if args.exportar_json:
        if args.resum:
            resum_executiu(console, ctx)
            console.print()
        vista_exportar_json(console, ctx)
        return 0

    if args.resum or not (sys.stdin.isatty() and sys.stdout.isatty()):
        resum_executiu(console, ctx)
        return 0
    try:
        bucle_menu(console, ctx)
    except (KeyboardInterrupt, EOFError):
        console.print("\nFins aviat.\n")
    return 0

def main(argv: list[str] | None = None) -> int:
    debug = "--debug" in (argv if argv is not None else sys.argv[1:])
    try:
        console = Console()
    except Exception as e:
        print(f"No s'ha pogut inicialitzar la consola: {e}")
        return 1
    try:
        return _executa(_llegeix_arguments(argv), console)
    except ErrorAplicacio as e:
        mostra_error(console, e)
        return 1
    except KeyboardInterrupt:
        console.print("\n[yellow]Programa interromput per l'usuari.[/]")
        return 130
    except BrokenPipeError:
        try:
            sys.stdout = open(os.devnull, "w")           # evita el missatge d'error en tancar
        except Exception:
            pass
        return 0
    except Exception as e:                               # xarxa de seguretat final
        if debug:
            raise
        try:
            mostra_error(console, ErrorAplicacio(
                "S'ha produït un error inesperat.", f"{type(e).__name__}: {e}",
                ["Torna-ho a provar amb un altre fitxer o executa amb --debug per veure el detall tècnic."]))
        except Exception:
            print(f"Error inesperat: {type(e).__name__}: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
