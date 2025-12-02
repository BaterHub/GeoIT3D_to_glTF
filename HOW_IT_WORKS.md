# Come funziona

Il flusso converte uno ZIP GeoIT3D in un `<nome_zip>.glb` con metadati incorporati. I passaggi principali sono nel comando `geoit3d-to-gltf` (`src/geoit3d_to_gltf/convert_zip_to_glb.py`):

1. **Estrazione ZIP**  
   - `extract_zip_to_temp`: estrae lo ZIP in una cartella temporanea.

2. **Metadati del modello**  
   - `read_descriptor`: legge `descriptor.json` (codice, nome, autore, DOI, licenza, date, ecc.).
   - `parse_iso_sheet` (opzionale): legge il foglio Excel ISO/AGID (`ISO_AGID_format`) e costruisce un dizionario compatto (identifier, title, keywords, extent, autori, localizzazione).
   - `make_asset_extras`: combina descriptor, ISO/AGID (se presente) e metadati delle superfici in un unico oggetto JSON da inserire in `asset.extras`.

3. **Parsing geometrie TSurf**  
   - `build_full_scene` (`tsurf_to_trimesh.py`):
     - Legge `dem.ts`, `horizons.ts`, `faults.ts`, `units.ts` se presenti.
     - `parse_gocad_tsurf_file`: estrae vertici/facce per ogni superficie, supportando file multisuperficie.
   - `load_attributes`: associa gli ID superficie alle tabelle CSV (`main_fault_attributes.csv`, `main_horizon_attributes.csv`, `main_unit_attributes.csv`).
   - `_load_color_scheme`: carica la palette da `examples/color_scheme.csv` e mappa i codici `color_fault/color_surface/color_unit` su RGB.
   - Crea una `trimesh.Scene`, aggiunge i mesh colorandoli se la palette contiene il codice, e costruisce `surfaces_metadata` (gruppo, nome nodo, attributi).

4. **Export glTF/GLB**  
   - `export_scene_to_glb`: esporta la scena con `trimesh.exchange.gltf`, garantisce `asset.version=2.0`, aggiunge `asset.extras` e un `model_code` in `scenes[0].extras` se disponibile, salva `<nome_zip>.glb` (inserendo manualmente l'extras nel chunk JSON per compatibilità).
   - Scrive anche `<nome_zip>_metadata.json` (copia di `asset.extras`).

5. **Copia tabelle di attributi**  
   - `copy_attribute_tables`: copia le principali CSV nella cartella di output per consultazione esterna.

6. **Pulizia**  
   - La cartella temporanea viene eliminata salvo l'uso di `--keep-temp`.

## Dati in ingresso attesi
- ZIP con `descriptor.json`, file `.ts` (DEM/HORIZON/FAULT/UNIT), tabelle CSV di attributi, eventuali CSV derivate/kinematics.
- Facoltativo: Excel ISO/AGID con foglio `ISO_AGID_format`.

## Estensioni possibili
- Aggiungere una fase di validazione reale in `validation.py`.
- Gestire strutture di foglio ISO/AGID alternative con mapping configurabile.
- Supportare ulteriori formati di input (es. mesh singole) o esportazioni multiple (glTF + tileset 3D).
