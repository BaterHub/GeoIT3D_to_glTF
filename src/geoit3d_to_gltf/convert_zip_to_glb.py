# CLI principale (ZIP → GLB + metadata)

"""
GeoIT3D_to_glTF.convert_zip_to_glb

Script CLI per convertire un modello 3D GeoIT3D (in formato ZIP)
in un file glTF/GLB pronto per visualizzatori web (es. IPSES/INGV).

Funzionalità principali:
- Estrae lo ZIP in una cartella temporanea
- Legge i metadati da descriptor.json
- (Opzionale) integra i metadati ISO/AGID da un file .xlsx
- Costruisce la scena 3D tramite tsurf_to_trimesh.build_full_scene
- Inserisce i metadati in asset.extras del glTF
- Esporta model.glb e model_metadata.json
- Copia le tabelle CSV di attributi nella cartella di output
"""

from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, Optional, Tuple

import click
import trimesh
from trimesh.exchange import gltf as gltf_export

from .iso_sheet import parse_iso_sheet
from .tsurf_to_trimesh import build_full_scene
# from .validation import validate_model_directory  # al momento non usata


# ----------------------------------------------------------------------
# Utilità per lettura descriptor.json e costruzione extras
# ----------------------------------------------------------------------


def read_descriptor(model_dir: Path) -> Dict:
    """
    Legge il file descriptor.json dalla cartella del modello.
    """
    descriptor_path = model_dir / "descriptor.json"
    if not descriptor_path.exists():
        raise FileNotFoundError(f"descriptor.json non trovato in {model_dir}")

    with descriptor_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def make_asset_extras(
    descriptor: Dict,
    iso_agid: Optional[Dict],
    surfaces_meta: Dict[str, Dict],
) -> Dict:
    """
    Costruisce l'oggetto JSON da inserire in asset.extras del glTF.

    Struttura:

    {
      "core_descriptor": {...},
      "iso_agid": {...},         # se presente
      "surfaces": {...}          # metadati per ogni superficie
    }
    """
    core = {
        "code": descriptor.get("code"),
        "name": descriptor.get("name"),
        "description": descriptor.get("description"),
        "author": descriptor.get("author"),
        "source": descriptor.get("source"),
        "doi": descriptor.get("doi"),
        "license": descriptor.get("license"),
        "creation_datetime": descriptor.get("creation datetime"),
        "publication_datetime": descriptor.get("publication datetime"),
        "meta_url": descriptor.get("meta_url"),
    }

    extras: Dict[str, object] = {
        "core_descriptor": core,
        "surfaces": surfaces_meta,
    }

    if iso_agid is not None:
        extras["iso_agid"] = iso_agid

    return extras


# ----------------------------------------------------------------------
# Estrazione ZIP e copia tabelle CSV
# ----------------------------------------------------------------------


def extract_zip_to_temp(zip_path: Path) -> Path:
    """
    Estrae uno ZIP in una nuova cartella temporanea e restituisce il Path.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="GeoIT3D_model_"))
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(tmp_dir)
    return tmp_dir


def copy_attribute_tables(model_dir: Path, output_dir: Path) -> None:
    """
    Copia le principali tabelle CSV di attributi nella cartella di output,
    se presenti.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_names = [
        "main_fault_attributes.csv",
        "main_fault_derived_attributes.csv",
        "main_fault_kinematics_attributes.csv",
        "main_horizon_attributes.csv",
        "main_horizon_derived_attributes.csv",
        "main_unit_attributes.csv",
    ]

    for name in csv_names:
        src = model_dir / name
        if src.exists():
            dst = output_dir / name
            shutil.copy2(src, dst)


# ----------------------------------------------------------------------
# Export GLB
# ----------------------------------------------------------------------


def export_scene_to_glb(
    scene: trimesh.Scene,
    asset_extras: Dict,
    output_glb_path: Path,
) -> None:
    """
    Esporta una scena trimesh in formato GLB, inserendo asset.extras
    con i metadati forniti.
    """
    # 1. otteniamo il dict glTF dalla scene
    gltf_dict = gltf_export.export_gltf(scene, include_normals=True)

    # 2. assicuriamoci che esista la sezione "asset"
    if "asset" not in gltf_dict:
        gltf_dict["asset"] = {"version": "2.0"}
    elif "version" not in gltf_dict["asset"]:
        gltf_dict["asset"]["version"] = "2.0"

    # 3. inseriamo i metadati in asset.extras
    gltf_dict["asset"]["extras"] = asset_extras

    # 4. opzionale: potremmo inserire qualcosa anche in scenes[0].extras
    #    per ora aggiungiamo solo l'id del modello se presente
    model_code = asset_extras.get("core_descriptor", {}).get("code")
    if "scenes" in gltf_dict and gltf_dict["scenes"]:
        gltf_dict["scenes"][0].setdefault("extras", {})
        if model_code is not None:
            gltf_dict["scenes"][0]["extras"]["model_code"] = model_code

    # 5. salviamo come GLB usando il dizionario arricchito
    output_glb_path.parent.mkdir(parents=True, exist_ok=True)
    gltf_export.save_glb(gltf_dict, output_glb_path.as_posix())


# ----------------------------------------------------------------------
# CLI principale
# ----------------------------------------------------------------------


@click.command()
@click.argument(
    "zip_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(file_okay=False, path_type=Path),
    required=True,
    help="Cartella di output in cui salvare model.glb, model_metadata.json e le tabelle CSV.",
)
@click.option(
    "--iso-sheet",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Foglio metadati ISO/AGID in formato .xlsx (opzionale).",
)
@click.option(
    "--keep-temp",
    is_flag=True,
    default=False,
    help="Se impostato, non cancella la cartella temporanea di estrazione dello ZIP (utile per debug).",
)
def main(
    zip_path: Path,
    output_dir: Path,
    iso_sheet: Optional[Path],
    keep_temp: bool,
) -> None:
    """
    Converte un modello GeoIT3D fornito come ZIP in un file glTF/GLB.

    Esempio:

      geoit3d-to-gltf F184_Mirandola.zip \\
          --output-dir output/F184_Mirandola \\
          --iso-sheet Metadata_Modelli3D_ISO_F184.xlsx
    """

    # 1. Estrazione ZIP
    tmp_dir = extract_zip_to_temp(zip_path)

    try:
        # 2. (Opzionale) Validazione interna - al momento NON usata
        # validate_model_directory(tmp_dir)

        # 3. Metadati: descriptor.json + (eventuale) ISO/AGID
        descriptor = read_descriptor(tmp_dir)
        iso_agid = parse_iso_sheet(iso_sheet) if iso_sheet is not None else None

        # 4. Costruzione scena 3D e metadati per superficie
        #    build_full_scene ritorna:
        #    - scene: trimesh.Scene
        #    - surfaces_meta: dict con info su ogni superficie
        scene, surfaces_meta = build_full_scene(tmp_dir)

        # 5. Costruzione oggetto extras (asset.extras)
        asset_extras = make_asset_extras(descriptor, iso_agid, surfaces_meta)

        # 6. Esportazione GLB
        output_dir.mkdir(parents=True, exist_ok=True)
        glb_path = output_dir / "model.glb"
        export_scene_to_glb(scene, asset_extras, glb_path)

        # 7. Metadati JSON esterno
        meta_json_path = output_dir / "model_metadata.json"
        with meta_json_path.open("w", encoding="utf-8") as f:
            json.dump(asset_extras, f, indent=2, ensure_ascii=False)

        # 8. Copia tabelle CSV di attributi
        copy_attribute_tables(tmp_dir, output_dir)

        click.echo(f"[OK] Conversione completata.")
        click.echo(f"     GLB: {glb_path}")
        click.echo(f"     Metadati: {meta_json_path}")

    finally:
        if not keep_temp:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        else:
            click.echo(f"[INFO] Cartella temporanea conservata in: {tmp_dir}")


if __name__ == "__main__":
    main()
