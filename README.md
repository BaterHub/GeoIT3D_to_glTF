# GeoIT3D_to_glTF

[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/BaterHub/GeoIT3D_to_glTF/blob/main/GeoIT3D_to_glTF_Colab.ipynb)

Conversione di modelli geologici 3D GeoIT3D (ISPRA) in file glTF/GLB pronti per la pubblicazione su web viewer (es. IPSES). Il comando principale `geoit3d-to-gltf` prende in input uno ZIP prodotto dal workflow GeoIT3D e genera un `model.glb` con metadati incorporati e le tabelle CSV di attributi a lato.

## Caratteristiche
- Estrazione automatica di uno ZIP GeoIT3D in una cartella temporanea.
- Parsing dei file GOCAD TSurf (`dem.ts`, `horizons.ts`, `faults.ts`, `units.ts`) e costruzione di una scena `trimesh.Scene`.
- Collegamento delle superfici alle tabelle di attributi CSV, se presenti.
- Inserimento dei metadati (descriptor.json + foglio ISO/AGID opzionale) dentro `asset.extras` del glTF.
- Esporta `model.glb` e un `model_metadata.json` esterno; copia le principali CSV di attributi.

## Requisiti
- Python 3.10+
- Dipendenze principali: `trimesh`, `numpy`, `pandas`, `click`, `openpyxl` (installate automaticamente).

## Installazione
```bash
pip install .
# oppure in sviluppo
pip install -e .
```

## Uso rapido
```bash
geoit3d-to-gltf examples/F184_Mirandola.zip \
  --output-dir output/F184_Mirandola \
  --iso-sheet examples/Metadata_Modelli3D_ISO.xlsx
```

Argomenti/opzioni:
- `zip_path`: ZIP del modello GeoIT3D (contenente `descriptor.json`, file `.ts`, CSV, ecc.).
- `--output-dir/-o`: cartella dove salvare `model.glb`, `model_metadata.json` e le CSV copiate.
- `--iso-sheet`: file Excel con foglio ISO/AGID (opzionale); se assente, i metadati ISO non vengono aggiunti.
- `--keep-temp`: conserva la cartella temporanea di estrazione per debug.

Output:
- `model.glb`: scena glTF binaria con `asset.extras` popolato.
- `model_metadata.json`: copia dei metadati in un JSON esterno.
- CSV di attributi (fault/horizon/unit) copiate se presenti.

## Struttura attesa dello ZIP
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

## Note su metadati ISO/AGID
- Il parser cerca il foglio `ISO_AGID_format` e la colonna dei valori che contiene “modello”.
- Campi estratti: identifier, title, keywords, creation_date_time, autori, estensione spaziale (SRS, poligono XY, Zmin/Zmax), nominal resolution, localizzazione.
- Eventuali modifiche alla struttura del foglio possono richiedere adattamenti in `src/geoit3d_to_gltf/iso_sheet.py`.

## Sviluppo
- Entry point CLI: `src/geoit3d_to_gltf/convert_zip_to_glb.py` (`geoit3d-to-gltf`).
- Parser TSurf e costruzione scena: `src/geoit3d_to_gltf/tsurf_to_trimesh.py`.
- Parser metadati ISO/AGID: `src/geoit3d_to_gltf/iso_sheet.py`.
- Validazione placeholder (non usata): `src/geoit3d_to_gltf/validation.py`.

## Licenza
MIT License (vedi `LICENSE`).
