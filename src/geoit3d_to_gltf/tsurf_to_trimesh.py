"""
GeoIT3D_to_glTF.tsurf_to_trimesh

Parsing dei file GOCAD TSurf (DEM, horizons, faults, units) e
costruzione di una scena trimesh.Scene + metadati per superficie.

Questo modulo:
- legge file .ts multisuperficie (GOCAD TSurf)
- converte ogni superficie in una mesh trimesh.Trimesh
- collega le superfici alle tabelle di attributi CSV
- costruisce una scena 3D completa
- restituisce:
    - scene: trimesh.Scene
    - surfaces_metadata: dict[ID_superficie] -> {group, node_name, attributes}
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import trimesh
import csv
import zipfile
from io import TextIOWrapper


# ----------------------------------------------------------------------
# Dataclass per descrivere una superficie
# ----------------------------------------------------------------------


@dataclass
class SurfaceGeometry:
    """
    Rappresenta una superficie estratta da un file GOCAD TSurf.
    """
    id: str                 # es. SRF_0001_001, FLT_0001_001, UNT_0001_001, dem
    group: str              # DEM / HORIZON / FAULT / UNIT
    node_name: str          # nome del nodo nella scena (es. HORIZON_AES_SRF_0001_001)
    vertices: np.ndarray    # (N, 3)
    faces: Optional[np.ndarray]  # (M, 3) oppure None se mancano triangoli
    attributes: Dict[str, str]   # attributi provenienti dalle CSV (se presenti)


# ----------------------------------------------------------------------
# Parser GOCAD TSurf (multi-superficie in un singolo file .ts)
# ----------------------------------------------------------------------


def parse_gocad_tsurf_file(tsurf_path: Path, group: str) -> List[SurfaceGeometry]:
    """
    Legge un file GOCAD TSurf che può contenere più superfici (più blocchi
    'GOCAD TSurf 1 ... TFACE ...') e restituisce una lista di SurfaceGeometry
    (per ora senza attributi, che verranno aggiunti a parte).
    """
    text_lines = tsurf_path.read_text(encoding="utf-8", errors="ignore").splitlines()

    # surfaces_raw: lista di tuple (surf_name, vertices_dict, faces_list)
    surfaces_raw: List[Tuple[str, Dict[int, Tuple[float, float, float]], List[Tuple[int, int, int]]]] = []

    vertices: Dict[int, Tuple[float, float, float]] = {}
    faces: List[Tuple[int, int, int]] = []
    surf_name: Optional[str] = None
    in_header = False

    # Aggiungiamo una riga sentinella per flush finale
    for line in text_lines + ["GOCAD TSurf EOF"]:
        line = line.strip()
        if not line:
            continue

        if line.startswith("GOCAD TSurf"):
            # Chiudo l’eventuale superficie precedente
            if surf_name is not None and vertices:
                surfaces_raw.append((surf_name, vertices, faces))

            # Reset per la nuova superficie
            vertices = {}
            faces = []
            surf_name = None
            in_header = False
            continue

        if line.startswith("HEADER"):
            in_header = True
            continue

        if in_header:
            if line.startswith("}"):
                in_header = False
            elif line.lower().startswith("name:"):
                surf_name = line.split(":", 1)[1].strip()
            continue

        # Parte geometrica
        parts = line.split()
        if not parts:
            continue

        if parts[0] in ("PVRTX", "VRTX"):
            # PVRTX id x y z ...
            try:
                vid = int(parts[1])
                x, y, z = map(float, parts[2:5])
                vertices[vid] = (x, y, z)
            except Exception:
                # Ignora righe malformate
                pass

        elif parts[0] == "TRGL":
            try:
                i, j, k = map(int, parts[1:4])
                faces.append((i, j, k))
            except Exception:
                pass
        else:
            # Ignora altre parole chiave (BSTONE, BORDER, ecc.)
            pass

    # Flush finale se c'è una superficie ancora aperta
    if surf_name is not None and vertices:
        surfaces_raw.append((surf_name, vertices, faces))

    surfaces: List[SurfaceGeometry] = []

    for name, verts_dict, faces_list in surfaces_raw:
        # Mappa ID dei vertici in indici 0..N-1
        sorted_ids = sorted(verts_dict.keys())
        id_to_idx = {vid: i for i, vid in enumerate(sorted_ids)}
        verts = np.array([verts_dict[vid] for vid in sorted_ids], dtype=float)

        if faces_list:
            faces_arr = np.array(
                [[id_to_idx[i], id_to_idx[j], id_to_idx[k]] for (i, j, k) in faces_list],
                dtype=np.int64,
            )
        else:
            faces_arr = None

        # ID base = nome TSurf
        surf_id = name  # es. SRF_0001_001
        node_name = f"{group}_{surf_id}"

        surfaces.append(
            SurfaceGeometry(
                id=surf_id,
                group=group,
                node_name=node_name,
                vertices=verts,
                faces=faces_arr,
                attributes={},  # riempito poi
            )
        )

    return surfaces


# ----------------------------------------------------------------------
# Lettura tabelle di attributi (faults, horizons, units)
# ----------------------------------------------------------------------


def _read_csv_if_exists(path: Path) -> Optional[pd.DataFrame]:
    if path.exists():
        return pd.read_csv(path)
    return None

def _merge_dicts(base: Dict, extra: Dict) -> Dict:
    """
    Restituisce una copia di base con campi extra aggiunti solo se non presenti.
    """
    merged = dict(base)
    for k, v in extra.items():
        if k not in merged:
            merged[k] = v
    return merged


def load_attributes(model_dir: Path) -> Dict[str, Dict[str, Dict]]:
    """
    Legge le tabelle degli attributi nella cartella del modello e
    restituisce un dizionario:

    {
      "FAULT": { "FLT_0001_001": {...}, ... },
      "HORIZON": { "SRF_0001_001": {...}, ... },
      "UNIT": { "UNT_0001_001": {...}, ... }
    }

    Ogni valore interno è un dict con tutte le colonne della riga.
    """
    attrs: Dict[str, Dict[str, Dict]] = {
        "FAULT": {},
        "HORIZON": {},
        "UNIT": {},
    }

    # Faults - main
    fault_attr = _read_csv_if_exists(model_dir / "main_fault_attributes.csv")
    if fault_attr is not None and "id" in fault_attr.columns:
        for _, row in fault_attr.iterrows():
            sid = str(row["id"])
            attrs["FAULT"][sid] = row.to_dict()

    # Faults - derived
    fault_der_attr = _read_csv_if_exists(model_dir / "main_fault_derived_attributes.csv")
    if fault_der_attr is not None and "id" in fault_der_attr.columns:
        for _, row in fault_der_attr.iterrows():
            sid = str(row["id"])
            merged = attrs["FAULT"].get(sid, {})
            attrs["FAULT"][sid] = _merge_dicts(merged, row.to_dict())

    # Faults - kinematics
    fault_kin_attr = _read_csv_if_exists(model_dir / "main_fault_kinematics_attributes.csv")
    if fault_kin_attr is not None and "id" in fault_kin_attr.columns:
        for _, row in fault_kin_attr.iterrows():
            sid = str(row["id"])
            merged = attrs["FAULT"].get(sid, {})
            attrs["FAULT"][sid] = _merge_dicts(merged, row.to_dict())

    # Horizons - main
    horiz_attr = _read_csv_if_exists(model_dir / "main_horizon_attributes.csv")
    if horiz_attr is not None and "id" in horiz_attr.columns:
        for _, row in horiz_attr.iterrows():
            sid = str(row["id"])
            attrs["HORIZON"][sid] = row.to_dict()

    # Horizons - derived
    horiz_der_attr = _read_csv_if_exists(model_dir / "main_horizon_derived_attributes.csv")
    if horiz_der_attr is not None and "id" in horiz_der_attr.columns:
        for _, row in horiz_der_attr.iterrows():
            sid = str(row["id"])
            merged = attrs["HORIZON"].get(sid, {})
            attrs["HORIZON"][sid] = _merge_dicts(merged, row.to_dict())

    # Units
    unit_attr = _read_csv_if_exists(model_dir / "main_unit_attributes.csv")
    if unit_attr is not None and "id" in unit_attr.columns:
        for _, row in unit_attr.iterrows():
            sid = str(row["id"])
            attrs["UNIT"][sid] = row.to_dict()

    return attrs


# ----------------------------------------------------------------------
# Palette colori (CMYK -> RGB)
# ----------------------------------------------------------------------


def _load_color_scheme(csv_path: Optional[Path] = None) -> Dict[int, Tuple[int, int, int]]:
    """
    Carica la palette da color_scheme.csv (colonne: color, CMYK_code, RGB_code)
    e restituisce un mapping {color_code: (r, g, b)}.
    """
    if csv_path is None:
        csv_path = Path(__file__).resolve().parents[2] / "examples" / "color_scheme.csv"

    palette: Dict[int, Tuple[int, int, int]] = {}
    if not csv_path.exists():
        return palette

    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                code = int(str(row.get("color", "")).strip())
                rgb_hex = str(row.get("RGB_code", "")).strip()
                if rgb_hex.startswith("#"):
                    rgb_hex = rgb_hex[1:]
                if len(rgb_hex) != 6:
                    continue
                r = int(rgb_hex[0:2], 16)
                g = int(rgb_hex[2:4], 16)
                b = int(rgb_hex[4:6], 16)
                palette[code] = (r, g, b)
            except Exception:
                continue

    return palette


# ----------------------------------------------------------------------
# Mapping codici -> etichette/URL tramite codelist
# ----------------------------------------------------------------------


def _load_code_mapping(csv_path: Optional[Path] = None) -> Dict[str, str]:
    """
    Legge code_mapping.csv e restituisce un dizionario
    { field_name -> source_file }.
    """
    if csv_path is None:
        csv_path = Path(__file__).resolve().parents[2] / "examples" / "code_mapping.csv"

    mapping: Dict[str, str] = {}
    if not csv_path.exists():
        return mapping

    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            field = (row.get("field_name") or "").strip()
            src = (row.get("source_file") or "").strip()
            if field and src:
                mapping[field] = src
    return mapping


def _load_codelists(source_files: List[str], zip_path: Optional[Path] = None) -> Dict[str, Dict[str, Dict[str, Optional[str]]]]:
    """
    Carica le codelist richieste da un archivio zip.
    Ritorna: {source_file: {code: {"label": ..., "url": ...}}}
    """
    if zip_path is None:
        zip_path = Path(__file__).resolve().parents[2] / "examples" / "codelist.zip"

    codelists: Dict[str, Dict[str, Dict[str, Optional[str]]]] = {}
    if not zip_path.exists():
        return codelists

    needed = {src for src in source_files if src}
    if not needed:
        return codelists

    with zipfile.ZipFile(zip_path, "r") as zf:
        for src in needed:
            inner_path = f"codelist/{src}"
            if inner_path not in zf.namelist():
                continue
            with zf.open(inner_path, "r") as fh:
                reader = csv.DictReader(TextIOWrapper(fh, encoding="utf-8"))
                code_dict: Dict[str, Dict[str, Optional[str]]] = {}
                for row in reader:
                    # Trova le colonne code/label/url in maniera robusta
                    keys = {k.lower(): k for k in row.keys() if k}
                    code_key = keys.get("code")
                    url_key = None
                    for cand in ("url", "uri", "link"):
                        if cand in keys:
                            url_key = keys[cand]
                            break
                    # Prima scelta label è "type", altrimenti prima colonna diversa da code/url
                    label_key = None
                    for cand in ("type", "label", "description", "name"):
                        if cand in keys:
                            label_key = keys[cand]
                            break
                    if not label_key:
                        for k in row.keys():
                            lk = k.lower()
                            if lk not in ("code", "url", "uri", "link"):
                                label_key = k
                                break

                    if not code_key:
                        continue

                    code_val = (row.get(code_key) or "").strip()
                    if not code_val:
                        continue
                    label_val = (row.get(label_key) or "").strip() if label_key else None
                    url_val = (row.get(url_key) or "").strip() if url_key else None
                    code_dict[code_val] = {"label": label_val or None, "url": url_val or None}

                codelists[src] = code_dict

    return codelists


def _apply_code_mapping(attrs: Dict[str, object], code_mapping: Dict[str, str], codelists: Dict[str, Dict[str, Dict[str, Optional[str]]]]) -> Dict[str, object]:
    """
    Sostituisce i codici con dizionari {code, label, url} se trovati nella codelist.
    Mantiene i valori originali se non c'è corrispondenza.
    """
    mapped: Dict[str, object] = {}
    for key, val in attrs.items():
        src_file = code_mapping.get(key)
        if src_file and val is not None:
            code_str = str(val).strip()
            info = codelists.get(src_file, {}).get(code_str)
            if info:
                mapped[key] = {"code": code_str, "label": info.get("label"), "url": info.get("url")}
                continue
        mapped[key] = val
    return mapped


# ----------------------------------------------------------------------
# Costruzione della scena completa (DEM + horizons + faults + units)
# ----------------------------------------------------------------------


def build_full_scene(model_dir: Path) -> Tuple[trimesh.Scene, Dict[str, Dict]]:
    """
    Costruisce la scena 3D completa a partire dai file .ts nella cartella
    del modello e collega gli attributi alle superfici.

    Ritorna:
      - scene: trimesh.Scene
      - surfaces_metadata: dict ID superficie → metadati (tipo, nome nodo, attributi)

    surfaces_metadata ha struttura tipo:

    {
      "SRF_0001_001": {
        "group": "HORIZON",
        "node_name": "HORIZON_AES_SRF_0001_001",
        "attributes": {...}
      },
      ...
    }
    """
    model_dir = Path(model_dir)

    # 1. Carico attributi
    attrs = load_attributes(model_dir)
    palette = _load_color_scheme()
    code_mapping = _load_code_mapping()
    codelists = _load_codelists(list(code_mapping.values()))

    # 2. Parsing TSurf
    surfaces: List[SurfaceGeometry] = []

    ts_files = [
        ("dem.ts", "DEM"),
        ("horizons.ts", "HORIZON"),
        ("faults.ts", "FAULT"),
        ("units.ts", "UNIT"),
    ]

    for fname, group in ts_files:
        ts_path = model_dir / fname
        if ts_path.exists():
            surfaces.extend(parse_gocad_tsurf_file(ts_path, group))

    # 3. Arricchisco con attributi e creo la scena
    scene = trimesh.Scene()
    surfaces_metadata: Dict[str, Dict] = {}

    for surf in surfaces:
        # Collega attributi se presenti
        if surf.group == "FAULT":
            raw_attrs = attrs["FAULT"].get(surf.id, {})
            nice_name = str(raw_attrs.get("name_fault", surf.id))
            color_code = raw_attrs.get("color_fault")
        elif surf.group == "HORIZON":
            raw_attrs = attrs["HORIZON"].get(surf.id, {})
            nice_name = str(raw_attrs.get("name_surface", surf.id))
            color_code = raw_attrs.get("color_surface")
        elif surf.group == "UNIT":
            raw_attrs = attrs["UNIT"].get(surf.id, {})
            nice_name = str(raw_attrs.get("name_unit", surf.id))
            color_code = raw_attrs.get("color_unit")
        else:
            # DEM: nessuna tabella dedicata
            raw_attrs = {}
            nice_name = surf.id
            color_code = None

        # Applico mapping dei codici a etichette/URL (mantiene i valori non mappati)
        surf.attributes = _apply_code_mapping(raw_attrs, code_mapping, codelists)

        # Aggiorno node_name solo con gruppo e id (richiesta)
        surf.node_name = f"{surf.group}_{surf.id}"

        # Creo la mesh
        if surf.faces is not None and len(surf.faces) > 0:
            mesh = trimesh.Trimesh(
                vertices=surf.vertices,
                faces=surf.faces,
                process=False,
            )

            # Applico colore se disponibile nella palette
            rgba = None
            try:
                if color_code is not None:
                    code_int = int(str(color_code))
                    if code_int in palette:
                        r, g, b = palette[code_int]
                        rgba = [r, g, b, 255]
            except Exception:
                rgba = None

            if rgba is not None:
                mesh.visual.face_colors = np.tile(np.array(rgba, dtype=np.uint8), (len(mesh.faces), 1))

        else:
            # Se non ci sono facce, salto (oppure potresti gestirla come point cloud)
            continue

        # Aggiungo la geometria alla scena
        scene.add_geometry(mesh, node_name=surf.node_name)

        # Salvo metadati minimi per questa superficie
        surfaces_metadata[surf.id] = {
            "group": surf.group,
            "node_name": surf.node_name,
            "attributes": surf.attributes,
        }

    return scene, surfaces_metadata
