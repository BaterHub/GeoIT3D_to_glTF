# GeoIT3D_to_glTF

[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/BaterHub/GeoIT3D_to_glTF/blob/main/GeoIT3D_to_GLTF.ipynb)

Converte uno ZIP GeoIT3D in un glTF/GLB con metadati incorporati, colori da codici CSV e mapping dei domini (codelist) a etichette/URL. Output: `<nome_zip>.glb` + `<nome_zip>_metadata.json`.

## Workflow
- Estrae lo ZIP GeoIT3D e legge `descriptor.json` + ISO/AGID (opzionale).
- Parsea i TSurf (`dem.ts`, `horizons.ts`, `faults.ts`, `units.ts`) e costruisce la scena.
- Unisce attributi principali/derived/kinematics (fault/horizon/unit) senza duplicati.
- Mappa i codici a etichette/URL con `examples/codelist.zip` e `examples/code_mapping.csv`.
- Applica colori dai codici `color_fault/color_surface/color_unit` usando `examples/color_scheme.csv`.
- Scrive metadati in `asset.extras` del GLB e nel JSON esterno `<nome_zip>_metadata.json`.

## Installazione
```bash
pip install .
# oppure per sviluppo
pip install -e .
```

## CLI rapida
```bash
geoit3d-to-gltf examples/F184_Mirandola.zip \
  --output-dir output/F184_Mirandola \
  --iso-sheet examples/Metadata_Modelli3D_ISO.xlsx
```
Opzioni:
- `zip_path` (obbligatorio): ZIP GeoIT3D.
- `--output-dir/-o`: cartella per GLB e metadata JSON.
- `--iso-sheet`: Excel ISO/AGID opzionale.
- `--keep-temp`: conserva la cartella temporanea.

Output in `output/<nome_zip>/`:
- `<nome_zip>.glb` con `asset.extras`.
- `<nome_zip>_metadata.json` (stesso contenuto dei metadati).

## Colab
1. Clicca il badge Colab qui sopra.
2. Menu `Runtime` → `Restart and run all` (oppure esegui le celle con ▶️).
3. Quando richiesto, carica il tuo ZIP GeoIT3D (obbligatorio) e l’ISO `.xlsx` se ce l’hai.
4. Il notebook converte e salva in `output/<nome_zip>/` i file GLB e metadata.
5. Scarica dalla sidebar (icona cartella) con click destro → Download.

## ZIP atteso
```
descriptor.json
dem.ts
horizons.ts
faults.ts
units.ts
main_fault_attributes.csv
main_fault_derived_attributes.csv
main_fault_kinematics_attributes.csv
main_horizon_attributes.csv
main_horizon_derived_attributes.csv
main_unit_attributes.csv
...
```

## Metadati
- Globali in `asset.extras` (standard glTF). Per BabylonJS puoi leggerli da console: `scene.metadata?.gltf?.asset?.extras`.
- Mapping codici → etichette/URL via `examples/codelist.zip` + `examples/code_mapping.csv`.
- ISO/AGID (opzionale): foglio `ISO_AGID_format` con colonna valori “modello”.

## Dev
- CLI: `src/geoit3d_to_gltf/convert_zip_to_glb.py`
- Scene/attributi: `src/geoit3d_to_gltf/tsurf_to_trimesh.py`
- ISO parser: `src/geoit3d_to_gltf/iso_sheet.py`

## Licenza
MIT (vedi `LICENSE`).
