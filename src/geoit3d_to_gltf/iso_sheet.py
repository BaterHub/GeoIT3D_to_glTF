# parser del foglio ISO/AGID (.xlsx)

"""
GeoIT3D_to_glTF.iso_sheet

Parser del foglio metadati ISO/AGID in formato Excel (.xlsx).

Il modulo:
- legge il foglio `ISO_AGID_format`
- raccoglie i valori della colonna 'modello ' (o equivalente)
- costruisce un oggetto JSON compatto `iso_agid` con i campi principali:
  - identifier, title, keywords
  - creation_date_time
  - authors (name, organization)
  - extent (srs, polygon_xy, zmin, zmax)
  - nominal_resolution
  - location (toponym, country_uri, region_uris, city_uri)
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd


def parse_iso_sheet(xlsx_path: Path, sheet_name: str = "ISO_AGID_format") -> Dict[str, Any]:
    """
    Legge il foglio ISO/AGID e costruisce un dizionario di metadati.

    ATTENZIONE:
    - questa implementazione è basata sulla struttura tipica fornita per i modelli ISPRA.
    - se i nomi delle colonne cambiano, potrebbe essere necessario adattare i riferimenti.

    Parametri
    ---------
    xlsx_path : Path
        Percorso al file Excel con il foglio ISO/AGID.
    sheet_name : str
        Nome del foglio da leggere (default: "ISO_AGID_format").

    Ritorna
    -------
    dict
        Oggetto JSON `iso_agid` con i campi principali.
    """
    df = pd.read_excel(xlsx_path, sheet_name=sheet_name)

    # Le colonne possono essere ad es.:
    #  - colonna 0: "Campo"
    #  - colonna 1: "Sottocampo"
    #  - colonna 2: "Cardinalità"
    #  - colonna 'modello ' con i valori effettivi
    #
    # Qui assumiamo:
    #   - i testi stanno in 'modello ' (attenzione allo spazio finale)
    #   - la cardinalità in colonna 2
    #   - la descrizione/label in colonna 0-2

    # Provo a identificare dinamicamente la colonna dei valori
    value_col_name = None
    for col in df.columns:
        # tipicamente è "modello " ma ci teniamo larghi
        if isinstance(col, str) and "modello" in col.lower():
            value_col_name = col
            break

    if value_col_name is None:
        raise ValueError("Colonna per i valori del modello non trovata (es. 'modello ').")

    # colonne di descrizione (potresti adattarle in base al tuo file specifico)
    col0 = df.columns[0]
    col1 = df.columns[1] if len(df.columns) > 1 else None
    col2 = df.columns[2] if len(df.columns) > 2 else None

    def make_key(row) -> str:
        parts: List[str] = []
        for col in (col0, col1):
            if col is None:
                continue
            v = row.get(col)
            if isinstance(v, str) and v.strip():
                parts.append(v.strip())
        # includo cardinalità nel nome chiave per distinguerla, se serve
        card = row.get(col2) if col2 is not None else None
        if isinstance(card, str) and card.strip():
            parts.append(card.strip())
        return " / ".join(parts)

    raw_map: Dict[str, Any] = {}

    for _, row in df.iterrows():
        val = row.get(value_col_name)
        if not isinstance(val, str) or not val.strip():
            continue

        key = make_key(row)
        cardinality = str(row.get(col2)) if col2 is not None and row.get(col2) is not None else ""

        # Se cardinalità è 1..Many accumuliamo in lista
        if "1..Many" in cardinality and key in raw_map:
            if not isinstance(raw_map[key], list):
                raw_map[key] = [raw_map[key]]
            raw_map[key].append(val.strip())
        else:
            raw_map[key] = val.strip()

    # Adesso costruiamo un oggetto iso_agid compatto da raw_map
    # (i nomi chiave qui sono basati sulla tua struttura tipica ISO)

    identifier = _get_first_by_prefix(raw_map, "Identifier")
    title = _get_first_by_prefix(raw_map, "Title")
    keywords = _parse_keywords(raw_map)

    creation_dt = _get_first_by_prefix(raw_map, "Creation date time")

    authors = _collect_authors(raw_map)

    # Estensione spaziale
    srs = _get_first_by_prefix(raw_map, "SRS")
    polygon_xy = _parse_polygon(raw_map)
    zmin = _parse_float(_get_first_by_prefix(raw_map, "Zmin"))
    zmax = _parse_float(_get_first_by_prefix(raw_map, "Zmax"))

    nominal_resolution = _get_first_by_prefix(raw_map, "Nominal scale of the model")

    # Localizzazione
    toponym = _get_first_by_prefix(raw_map, "Toponym")
    country_uri = _get_first_by_prefix(raw_map, "Country")
    region_uri = _get_first_by_prefix(raw_map, "Region")
    city_uri = _get_first_by_prefix(raw_map, "City")

    iso_agid: Dict[str, Any] = {
        "identifier": identifier,
        "title": title,
        "keywords": keywords,
        "creation_date_time": creation_dt,
        "authors": authors,
        "extent": {
            "srs": srs,
            "polygon_xy": polygon_xy,
            "zmin": zmin,
            "zmax": zmax,
        },
        "nominal_resolution": nominal_resolution,
        "location": {
            "toponym": toponym,
            "country_uri": country_uri,
            "region_uris": [region_uri] if isinstance(region_uri, str) else region_uri,
            "city_uri": city_uri,
        },
    }

    return iso_agid


# ----------------------------------------------------------------------
# Funzioni helper per iso_sheet
# ----------------------------------------------------------------------


def _get_first_by_prefix(raw_map: Dict[str, Any], prefix: str) -> Optional[str]:
    """
    Ritorna il primo valore di raw_map la cui chiave inizia con `prefix`.
    Utile perché le chiavi sono tipo: "Identifier / 1", "Title / 1", ecc.
    """
    for key, val in raw_map.items():
        if key.startswith(prefix):
            return val if isinstance(val, str) else None
    return None


def _parse_keywords(raw_map: Dict[str, Any]) -> List[str]:
    """
    Estrae le keyword gestendo sia il caso stringa unica sia liste.
    """
    kw_list: List[str] = []

    for key, val in raw_map.items():
        if key.startswith("Keyword"):
            if isinstance(val, str):
                kw_list.extend([k.strip() for k in val.split(",") if k.strip()])
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, str):
                        kw_list.extend([k.strip() for k in item.split(",") if k.strip()])

    # Rimuovo duplicati mantenendo ordine
    seen = set()
    result: List[str] = []
    for k in kw_list:
        if k not in seen:
            seen.add(k)
            result.append(k)
    return result


def _parse_polygon(raw_map: Dict[str, Any]) -> Optional[List[List[float]]]:
    """
    Prova a interpretare il "Shape perimeter" o equivalente come lista di
    coordinate [x, y]. Molto dipendente da come viene scritto nel foglio.
    """
    txt = None
    for key, val in raw_map.items():
        if key.startswith("Shape perimeter") and isinstance(val, str):
            txt = val
            break

    if txt is None:
        return None

    coords: List[List[float]] = []
    lines = txt.splitlines()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Qui ci si aspetta qualcosa tipo: "X 183559.324 - Y 4968420.614"
        # ma la sintassi reale può variare. Cerchiamo di essere robusti:
        lowered = line.lower()
        if "x" in lowered and "y" in lowered:
            # rimuovo lettere e separatori grossi
            tmp = (
                lowered.replace("x", " ")
                .replace("y", " ")
                .replace("-", " ")
                .replace(":", " ")
            )
            tokens = [t for t in tmp.split() if t]
            # cerco le prime due cose che sembrano numeri
            nums: List[float] = []
            for t in tokens:
                try:
                    nums.append(float(t.replace(",", ".")))
                except ValueError:
                    continue
                if len(nums) == 2:
                    break
            if len(nums) == 2:
                coords.append(nums)

    return coords or None


def _parse_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(str(v).replace(",", "."))
    except Exception:
        return None


def _collect_authors(raw_map: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Estrae un elenco di autori a partire da chiavi che iniziano con 'Authors'
    o simili. Questa parte è volutamente generica: può essere adattata
    se la struttura ISO/AGID specifica è diversa.
    """
    authors: List[Dict[str, str]] = []

    for key, val in raw_map.items():
        if key.startswith("Authors") and isinstance(val, str):
            authors.append({"name": val, "organization": None})

    return authors
