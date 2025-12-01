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

    # Faults
    fault_attr = _read_csv_if_exists(model_dir / "main_fault_attributes.csv")
    if fault_attr is not None and "id" in fault_attr.columns:
        for _, row in fault_attr.iterrows():
            sid = str(row["id"])
            attrs["FAULT"][sid] = row.to_dict()

    # Horizons
    horiz_attr = _read_csv_if_exists(model_dir / "main_horizon_attributes.csv")
    if horiz_attr is not None and "id" in horiz_attr.columns:
        for _, row in horiz_attr.iterrows():
            sid = str(row["id"])
            attrs["HORIZON"][sid] = row.to_dict()

    # Units
    unit_attr = _read_csv_if_exists(model_dir / "main_unit_attributes.csv")
    if unit_attr is not None and "id" in unit_attr.columns:
        for _, row in unit_attr.iterrows():
            sid = str(row["id"])
            attrs["UNIT"][sid] = row.to_dict()

    return attrs


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
            surf.attributes = attrs["FAULT"].get(surf.id, {})
            nice_name = str(surf.attributes.get("name_fault", surf.id))
        elif surf.group == "HORIZON":
            surf.attributes = attrs["HORIZON"].get(surf.id, {})
            nice_name = str(surf.attributes.get("name_surface", surf.id))
        elif surf.group == "UNIT":
            surf.attributes = attrs["UNIT"].get(surf.id, {})
            nice_name = str(surf.attributes.get("name_unit", surf.id))
        else:
            # DEM: nessuna tabella dedicata
            nice_name = surf.id

        # Aggiorno node_name con un nome più parlante
        surf.node_name = f"{surf.group}_{nice_name}_{surf.id}"

        # Creo la mesh
        if surf.faces is not None and len(surf.faces) > 0:
            mesh = trimesh.Trimesh(
                vertices=surf.vertices,
                faces=surf.faces,
                process=False,
            )
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
