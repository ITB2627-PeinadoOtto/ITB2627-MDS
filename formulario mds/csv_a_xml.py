import csv
import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

# Obtenir la carpeta on es troba aquest mateix fitxer .py
BASE_DIR = Path(__file__).resolve().parent

CSV_FILE = BASE_DIR / "respuestas.csv"
XML_FILE = BASE_DIR / "incidencies.xml"

# Patró per eliminar caràcters de control invisibles no vàlids en XML
INVALID_XML_CHARS = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x84\x86-\x9f]"
)


def netejar_text(text: str) -> str:
    """Neteja caràcters de control no vàlids per a XML."""
    if not text:
        return ""
    return INVALID_XML_CHARS.sub("", str(text))


def nom_etiqueta(capcalera: str) -> str:
    """
    Converteix una capçalera del CSV en un nom d'etiqueta XML vàlid.
    Qualsevol seqüència de caràcters no alfanumèrics (espais, ?, (), ', :, /, ...)
    es converteix en un sol "_". Exemple:
        "Aquesta incidència ha ocorregut anteriorment?" -> "aquesta_incidència_ha_ocorregut_anteriorment"
        "Ubicació de l'incidència"                      -> "ubicació_de_l_incidència"
    """
    t = unicodedata.normalize("NFC", capcalera).strip().lower()
    t = re.sub(r"[^\w]+", "_", t).strip("_")
    # Un nom d'etiqueta XML no pot començar per un número ni estar buit
    if not t or not t[0].isalpha():
        t = f"campo_{t}"
    return t


# Crear l'element arrel del XML
root = ET.Element("incidencies")

if not CSV_FILE.exists():
    print(f"❌ Error: No s'ha trobat el fitxer CSV a: {CSV_FILE}")
else:
    # utf-8-sig elimina el BOM inicial que afegeixen Excel i Google Forms
    with open(CSV_FILE, mode="r", encoding="utf-8-sig", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            incidencia = ET.SubElement(root, "incidencia")
            for key, value in row.items():
                if not key:
                    continue
                field = ET.SubElement(incidencia, nom_etiqueta(key))
                field.text = netejar_text(value)

    # Guardar l'estructura en un fitxer XML ben format
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ", level=0)
    tree.write(XML_FILE, encoding="utf-8", xml_declaration=True)

    print(
        f"✅ Conversió completada amb èxit. Fitxer guardat a: {XML_FILE}"
    )
