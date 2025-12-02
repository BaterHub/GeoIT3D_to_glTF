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
import struct
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
    # export senza normali per evitare vettori zero e warning validator
    gltf_dict = gltf_export.export_gltf(scene, include_normals=False)

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

    # 5. salviamo come GLB: la versione di trimesh in Colab non espone save_glb,
    #    quindi esportiamo i bytes e patchiamo il chunk JSON con asset.extras.
    output_glb_path.parent.mkdir(parents=True, exist_ok=True)
    glb_bytes = gltf_export.export_glb(scene, include_normals=False)

    patched_glb = _inject_asset_extras_in_glb(
        glb_bytes=glb_bytes,
        asset_extras=asset_extras,
        model_code=model_code,
    )
    output_glb_path.write_bytes(patched_glb)


def _inject_asset_extras_in_glb(glb_bytes: bytes, asset_extras: Dict, model_code: Optional[str]) -> bytes:
    """
    Inserisce asset.extras (e opzionale model_code in scenes[0].extras) nel GLB già esportato.

    Funziona patchando il chunk JSON del GLB senza dipendenze aggiuntive.
    """
    if len(glb_bytes) < 20:
        return glb_bytes

    magic, version, total_length = struct.unpack_from("<4sII", glb_bytes, 0)
    if magic != b"glTF":
        return glb_bytes

    json_chunk_len = struct.unpack_from("<I", glb_bytes, 12)[0]
    json_chunk_type = struct.unpack_from("<I", glb_bytes, 16)[0]
    # 0x4E4F534A == b"JSON"
    if json_chunk_type != 0x4E4F534A:
        return glb_bytes

    json_start = 20
    json_end = json_start + json_chunk_len
    if json_end > len(glb_bytes):
        return glb_bytes

    json_text = glb_bytes[json_start:json_end].decode("utf-8")
    gltf_dict = json.loads(json_text)

    # Inserisco extras
    gltf_dict.setdefault("asset", {})
    gltf_dict["asset"].setdefault("version", "2.0")
    gltf_dict["asset"]["extras"] = asset_extras

    if model_code is not None:
        if gltf_dict.get("scenes") and isinstance(gltf_dict["scenes"], list) and gltf_dict["scenes"]:
            gltf_dict["scenes"][0].setdefault("extras", {})
            gltf_dict["scenes"][0]["extras"]["model_code"] = model_code

    # Imposta target dei bufferView per eliminare warning dei validator
    def _set_buffer_view_targets(gltf: Dict) -> None:
        buffer_views = gltf.get("bufferViews")
        accessors = gltf.get("accessors")
        meshes = gltf.get("meshes")
        if not isinstance(buffer_views, list) or not isinstance(accessors, list) or not isinstance(meshes, list):
            return

        index_accessor_ids = set()
        attribute_accessor_ids = set()

        for mesh in meshes:
            if not isinstance(mesh, dict):
                continue
            for prim in mesh.get("primitives", []):
                if not isinstance(prim, dict):
                    continue
                if "indices" in prim:
                    index_accessor_ids.add(prim["indices"])
                for attr_id in prim.get("attributes", {}).values():
                    attribute_accessor_ids.add(attr_id)

        # bufferView per accessors di indici -> ELEMENT_ARRAY_BUFFER (34963)
        for acc_id in index_accessor_ids:
            if not (isinstance(acc_id, int) and 0 <= acc_id < len(accessors)):
                continue
            acc = accessors[acc_id]
            if not isinstance(acc, dict):
                continue
            bv_id = acc.get("bufferView")
            if isinstance(bv_id, int) and 0 <= bv_id < len(buffer_views):
                bv = buffer_views[bv_id]
                if isinstance(bv, dict) and "target" not in bv:
                    bv["target"] = 34963

        # bufferView per accessors di attributi -> ARRAY_BUFFER (34962)
        for acc_id in attribute_accessor_ids:
            if not (isinstance(acc_id, int) and 0 <= acc_id < len(accessors)):
                continue
            acc = accessors[acc_id]
            if not isinstance(acc, dict):
                continue
            bv_id = acc.get("bufferView")
            if isinstance(bv_id, int) and 0 <= bv_id < len(buffer_views):
                bv = buffer_views[bv_id]
                if isinstance(bv, dict) and "target" not in bv:
                    bv["target"] = 34962

    _set_buffer_view_targets(gltf_dict)

    new_json = json.dumps(gltf_dict, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    # Pad a multipli di 4 byte con spazi (spec GLB)
    pad_len = (-len(new_json)) % 4
    new_json_padded = new_json + (b" " * pad_len)
    new_json_len = len(new_json_padded)

    # Ricompongo GLB: header + chunk JSON + chunk binario originale
    bin_part = glb_bytes[json_end:]
    new_total_length = 12 + 8 + new_json_len + len(bin_part)

    header = struct.pack("<4sII", b"glTF", 2, new_total_length)
    json_header = struct.pack("<II", new_json_len, 0x4E4F534A)

    return header + json_header + new_json_padded + bin_part


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
        base_name = zip_path.stem
        glb_path = output_dir / f"{base_name}.glb"
        export_scene_to_glb(scene, asset_extras, glb_path)

        # 7. Metadati JSON esterno
        meta_json_path = output_dir / f"{base_name}_metadata.json"
        with meta_json_path.open("w", encoding="utf-8") as f:
            json.dump(asset_extras, f, indent=2, ensure_ascii=False, allow_nan=False)

        # 8. Copia tabelle CSV di attributi (disabilitato su richiesta: non serve esportarle)
        # copy_attribute_tables(tmp_dir, output_dir)

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
