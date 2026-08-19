# VFACE

Analyse basée sur la lecture du code réel (clone `SADT`, branche `main`). Fichiers analysés :
- `VFACE/VFACE.py` (module Slicer scripté : widget, téléchargements, orchestration des processus)
- `VFACE/Resources/UI/VFACE.ui` (interface Qt)
- `VFACE/VFACE_utils/createlistprocess.py` (**cœur du pipeline** : construction de la liste des étapes, découpage des dossiers d'entrée, heatmaps, post-traitement Excel)
- `VFACE/VFACE_utils/segmentation_logic.py` (segmentation nnU-Net « BDS » + exports VTK/NIfTI)
- `VFACE/VFACE_utils/_batch_worker.py` (sous-processus de calcul de distance modèle-à-modèle)
- `VFACE/VFACE_utils/functionaq3dc.py` (logique AQ3DC : lecture des landmarks `.json`, calcul et écriture des mesures)
- `VFACE_CLI/VFACE_CLI.py` + `VFACE_CLI.xml` (CLI Slicer de classification ML)
- `VFACE/Resources/ML/` (dossier de poids nnU-Net livré **incomplet**)

## Rôle

VFACE = *Vertical / Visual Facial Asymmetry Classification Engine* (`VFACE/VFACE.py:59`, `README.md:844`). **Rien à voir avec la photogrammétrie ou les visages 3D optiques** : il s'agit d'un **méta-module d'orchestration CBCT** qui enchaîne des modules existants de SlicerAutomatedDentalTools pour évaluer l'asymétrie faciale squelettique.

Deux axes de configuration, indépendants :

1. **Type d'analyse** (`comboBox4`, `VFACE.ui:82-90`) :
   - `Asymmetry Assesment` : le « T2 » est **fabriqué** en **mirroirant** le T1 (matrice `Matrix_mirror.tfm`), puis recalé sur le T1 → on compare le patient à son propre miroir.
   - `Longitudinal studies` : le T2 est un **vrai second scan** fourni par l'utilisateur (`PathLineEdit_4`).
2. **Sortie voulue** (`comboBox2`, `VFACE.ui:63-76`) : `Quantitative + Visualization`, `Quantitative (AQ3DC+ Classification)`, `Visualization (Heatmaps)` - traduits en deux booléens `bool_visualization` / `bool_quantification` (`VFACE.py:1000-1001`).

Chaîne complète (`createlistprocess.py:117-1213`) : resample (`mri2cbct_resample_cbct_mri`) → centrage (`pre_aso_cbct`) → landmarks (`ali_cbct`) → orientation (`semi_aso_cbct`) → masques (`amasss_cli`) → miroir (`automatrix_cli`) → recalage (`areg_cbct`) → segmentation dentaire nnU-Net (`run_bds`) → heatmaps de distance (VTK) → mesures AQ3DC (Excel) → **classification LightGBM** (`vface_cli`, `createlistprocess.py:129` et `VFACE_CLI/VFACE_CLI.py`).

Le CLI `VFACE_CLI` proprement dit est **minuscule** : il ne fait que charger 3 modèles LightGBM, lire un `.xlsx` et écrire un `.xlsx` enrichi de 3 colonnes.

## Entrées

| Entrée | Widget / paramètre | Type | Extensions réellement acceptées | Fichier ou dossier | Scan récursif |
|---|---|---|---|---|---|
| Dossier T1 (`T1 Folder` / `Oriented T1 Folder`) | `PathLineEdit` → `InputFolder` (`VFACE.ui:167-172`, `VFACE.py:735`) | dossier de CBCT | Comptage patients : `.nii.gz`, `.nii`, `.nrrd`, `.nrrd.gz`, `.gipl`, `.gipl.gz`, `.json` (`createlistprocess.py:1764-1765`). Tri T1 en modes « déjà orienté/recalé » : `.nii`, `.nii.gz`, `.nrrd`, `.nrrd.gz` uniquement (`createlistprocess.py:1568`) | **dossier uniquement** (`ctkPathLineEdit::Dirs`, `VFACE.ui:169`) | Oui pour `GetPatients` (`iglob(**, recursive=True)`, `createlistprocess.py:2526`) ; **non** pour `SplitOriented` (`Path.glob`, non récursif, `createlistprocess.py:1568`) |
| Dossier T2 (`T2 Folder` / `Registered T2 Folder`) | `PathLineEdit_4` (`VFACE.ui:207-215`, `VFACE.py:1004`) | dossier CBCT (+ `.tfm`) | CBCT : `.nii`, `.nii.gz`, `.nrrd`, `.nrrd.gz` ; transformées : `.tfm` (`createlistprocess.py:1603-1604`) | dossier | **Non** (`Path.glob`) |
| Dossier des listes de mesures (+ features ML) | `PathLineEdit_3` → `MeasurementsFolder` (`VFACE.ui:179-184`) | dossier de fichiers Excel | `.xlsx`, `.xls` (`createlistprocess.py:1523`) | dossier | **Non** |
| Dossier de sortie | `PathLineEdit_2` → `OutputFolder` (`VFACE.ui:220-225`) | dossier | - | dossier | - |
| Type d'analyse | `comboBox4` | `Asymmetry Assesment` \| `Longitudinal studies` (`VFACE.ui:85,90`) | - | - | - |
| Mode de sortie | `comboBox2` | `Quantitative + Visualization` \| `Quantitative (AQ3DC+ Classification)` \| `Visualization (Heatmaps)` (`VFACE.ui:66,71,76`) | - | - | - |
| Point de départ | `comboBox3` | `Full pipeline` \| `File already Oriented` \| `File already Registered` (`VFACE.ui:113,118,123`) | - | - | - |
| Type de recalage | `comboBox` | `AREG` \| `CMFReg` (`VFACE.ui:233,238`) - utilisé **une seule fois** (`createlistprocess.py:470`) | - | - | - |
| Keep Intermediate files | `checkBox` (`VFACE.ui:251-260`) | booléen | - | - | - |
| Intermediate Output Check | `checkBox_2` (`VFACE.ui:266-275`) | booléen (pauses de visualisation) | - | - | - |

### Entrées implicites (téléchargées, jamais choisies par l'utilisateur)

Le bouton *Check and/or Download Dependencies* (`VFACE.py:887-934`) installe `joblib` + `lightgbm` puis télécharge (`VFACE.py:790-811`) :

| Ressource | URL | Utilisation |
|---|---|---|
| Matrice miroir | `https://github.com/GaelleLeroux/DCBIA_Apply_matrix/releases/download/AutoMatrixMirror/Mirror.zip` → `Mirror_matrix/Mirror/Matrix_mirror.tfm` | `VFACE.py:999` |
| Références ASO (2 plans) | `.../ASO_CBCT/releases/download/v01_goldmodels/Occlusal_Midsagittal_Plane.zip` et `Frankfurt_Horizontal_Midsagittal_Plane.zip` (`VFACE.py:794-795`) | `createlistprocess.py:274,338` |
| Modèles AMASSS | `.../SlicerAutomatedDentalTools/releases/download/AMASSS_CBCT/AMASSS_Models.zip` (`VFACE.py:797`) | `createlistprocess.py:421,446` |
| Modèles ALI (8 zips) | `.../releases/download/v0.1-v2.0_models/*.zip` (`VFACE.py:800-809`) | `createlistprocess.py:824,848,...` |
| Modèles VFACE (LightGBM) | `.../releases/download/VFACE/V_FACE_Models.zip` → dossier `V_FACE` (`VFACE.py:810`) | `model_vface` → `VFACE_CLI` (`VFACE.py:1006`) |
| Liste de mesures par défaut | `.../releases/download/VFACE/DefaultList.zip` → `V_FACE/DefaultList` (bouton *Default*, `VFACE.py:1042-1048`) | remplit `PathLineEdit_3` |
| Poids nnU-Net segmentation | **jamais téléchargés** - `download_info.json` (`https://github.com/gaudot/SlicerDentalSegmentator/releases/download/v1.0.0-alpha/Dataset111_453CT_v100.zip`) n'est lu par aucun code de VFACE ; `downloadWeightsIfNeeded` est un stub qui renvoie `True` (`segmentation_logic.py:57-60`) | `segmentation_logic.py:327` |

Précisions importantes :

- **Le CLI `vface_cli` a 3 entrées positionnelles** (`VFACE_CLI.xml:10-27`, `VFACE_CLI.py:267-281`) : `model_path` (dossier), `excel_path` (fichier `.xlsx`), `output_path` (fichier de sortie). `model_path` doit contenir **exactement** `sym_asymm.txt`, `mand_asym.txt`, `max_asym.txt` - des pickles `joblib` malgré l'extension `.txt` (`VFACE_CLI.py:84-96`).
- **Découpage du dossier T1 par mot-clé dans le nom de fichier** (`SplitOriented`, `createlistprocess.py:1562-1595`) : un fichier va dans `CB` s'il contient `CB`/`CRANIAL`/`CRANIOFACIAL`, dans `MAX` s'il contient `MAX`/`MAXILLA`/`MAXILLARY` (comparaison en MAJUSCULES). Tout autre fichier est **silencieusement ignoré**.
- **Découpage du dossier T2** (`SplitT2`, `createlistprocess.py:1597-1673`) : idem + `MAND`/`MANDIBLE`/`MANDIBULAR`/`MD` et `MX`. Les `.tfm` ne sont exigés que si `transform=True`, c.-à-d. dès qu'on fait de la quantification (`createlistprocess.py:623-626`) ; sinon `FileNotFoundError` (`createlistprocess.py:1606-1607`).
- **Listes de mesures Excel** (`SplitMeasurements`, `createlistprocess.py:1514-1560`) : classement par mot-clé dans le nom - `CB`/`CRANIAL`, `MAND`/`MANDIBLE`, `MAX`/`MAXILLA`, et `FEAT`/`FEATURE` (uniquement en mode `Asymmetry Assesment`). Le fichier « features » sert de **gabarit de colonnes** au post-traitement (`createlistprocess.py:2538-2540`).
- **Format des feuilles Excel de mesures** : soit colonnes `Type of measurement` / `Point 1` / `Point 2 / Line`, soit `Type of measurement` / `Line 1` / `Line 2` (`createlistprocess.py:1727-1734`). Les mesures sont lues sur **toutes** les feuilles (`sheet_name=None`, ligne 1722) mais la liste de landmarks à détecter n'est lue que sur la **première** feuille (`pd.read_excel(df_path)`, ligne 1741).
- **Landmarks d'entrée d'AQ3DC** : fichiers markups `.json` Slicer, lus récursivement, identifiant patient = début du nom avant le premier `_` (`functionaq3dc.py:1439-1487`).
- **Segmentation BDS** : n'accepte que `*.nii*`, `*.gipl`, `*.gipl.gz` en récursif (`segmentation_logic.py:92`) - **le NRRD n'est pas pris en charge**. Device forcé à `cuda` (`createlistprocess.py:1239`), modèle forcé à `DentalSegmentator`.
- Aucune entrée DICOM : tous les appels passent `DCMInput: False` (`createlistprocess.py:235,254,298,...`).

## Sorties

Toutes les sorties sont écrites **sous `OutputFolder`**, dans une arborescence créée à la construction de la liste des processus (donc les dossiers existent même si aucune étape ne les remplit).

| Sortie | Format | Nommage | Condition | Cardinalité |
|---|---|---|---|---|
| `T1 Resample/CBCT/` | volumes | produit par `mri2cbct_resample_cbct_mri` (spacing 0.3³, centrés) (`createlistprocess.py:194-227`) | mode `Full pipeline` | N scans |
| `Centered T1 Scans/{CB,MAX}/` | volumes + `.json` landmarks ALI | `pre_aso_cbct` puis `ali_cbct` écrivent dans le même dossier (`createlistprocess.py:229-334`) | `Full pipeline` | N par sous-dossier |
| `Oriented T1 Scans/{CB,MAX}/` | volumes | suffixes `_CB_Or` / `_MAX_Or` (`add_inname`, `createlistprocess.py:276,340`) | `Full pipeline` ; sinon **copie** du dossier d'entrée (`createlistprocess.py:184-186`) | N par sous-dossier |
| `T2 Resample/`, `T2 Centered/` | volumes | `createlistprocess.py:367-411` | `Longitudinal studies` et mode ≠ `File already Registered` | N |
| `T2_Scan/{CB,MAX}/` | volumes miroirs | suffixe `_mir` (`createlistprocess.py:497-542`) | `Asymmetry Assesment` | N par sous-dossier |
| `T1 Masks/` | masques `CBMASK`,`MANDMASK`,`MAXMASK` (`prediction_ID: "seg"`, `genVtk: False`) | `amasss_cli` (`createlistprocess.py:413-468`) | mode ≠ `File already Registered` | 3 masques × N |
| `T2_Masks/` | masques miroirs `_mir` | `createlistprocess.py:471-495` | `Asymmetry Assesment` **et** `reg_type == CMFReg` | 3 × N |
| `Registered Scan/{Cranial Base,Maxilla,Mandible}/<patient>_OutReg/` | volumes recalés + `.tfm` | matrices attendues : `<patient>_CB_Reg_matrix.tfm`, `_MAND_Reg_matrix.tfm`, `_MAX_Reg_matrix.tfm` (`createlistprocess.py:942,968,994`) | mode ≠ `File already Registered` (sinon simple copie des fichiers fournis) | 3 recalages × N |
| `VTK Files/{T1 CB,T1 MAX,T2 CB,T2 MAND,T2 MAX}/` | `.vtk` binaires | par label : `<volume>_Segmentation_<Label>.vtk` (`segmentation_logic.py:746-747`) avec labels `Upper Skull`, `Mandible`, `Upper Teeth`, `Lower Teeth`, `Mandibular canal` (`segmentation_logic.py:470`) ; fusionné : `<volume>_Segmentation_merged.vtk` (`segmentation_logic.py:655`) | `bool_visualization` | **6 fichiers `.vtk` par scan** (5 labels + merged), × 5 dossiers |
| `Heatmaps/` | `.vtk` avec tableau de points `SignedDistance` + tableau constant `Original` (`createlistprocess.py:2250-2262`) | `<patient>_<zone>_ModelDistance.vtk` avec zone ∈ `merged`, `Mandible`, `Upper_Skull` (`createlistprocess.py:2436`) | `bool_visualization` | **3 par patient** (CB/merged, MAND, MAX) |
| `T1 Landmarks/{CB,MAX}/` | `.json` markups | `ali_cbct` (`createlistprocess.py:822-868`) | `bool_quantification` | 1 fichier par scan et par groupe |
| `Mirrored Landmarks/{CB,MAX}/` | `.json` suffixe `_mir` | `createlistprocess.py:879-924` | `bool_quantification` + `Asymmetry Assesment` | N |
| `Mirrored & Registered Landmarks/{CB,MAND,MAX}/` | `.json` suffixes `_CB_reg`, `_MAND_reg`, `_MAX_reg` | `createlistprocess.py:940-1015` | idem | 3 × N (3 appels **par patient**) |
| `T2 Landmarks/{CB,MAX,MAND}/` | `.json` | `createlistprocess.py:1017-1099` | `bool_quantification` + `Longitudinal studies` | N |
| `Measurements/Measurements_CB.xlsx`, `_MAND.xlsx`, `_MAX.xlsx` | Excel (1 feuille, colonnes `ID`, `Landmarks`, `Transverse`, `AP`, `Vertical`, `3D`, `Yaw/Pitch/Roll`, `BL`, `MD`, `Rotation`, `Arch`, `Segment` - colonnes entièrement « x » supprimées, `createlistprocess.py:1500-1512`) | noms **codés en dur** (`createlistprocess.py:1118,1139,1158`), écrits par `functionaq3dc.py:2182-2201` | `bool_quantification` | **exactement 3 fichiers** |
| `Measurements/PostProcess_Measurements.xlsx` | Excel « ML-ready » : 1 ligne par patient, colonnes = celles du fichier *features* | nom codé en dur (`createlistprocess.py:2674`) | `bool_quantification` + `Asymmetry Assesment` | **1 fichier** |
| `Classification/Classification.xlsx` | Excel = `PostProcess_Measurements.xlsx` + colonnes `Asymmetry` (`Symmetric`/`Asymmetric`), `Mand` (`True`/`False`), `Max` (`True`/`False`) (`VFACE_CLI.py:163,167-168,181,188`) | nom codé en dur (`createlistprocess.py:1199`) | `bool_quantification` + `Asymmetry Assesment` | **1 fichier, quel que soit le nombre de patients** |

Prose complémentaire :

- **Cardinalité globale** : pour N patients en mode complet `Quantitative + Visualization` / `Asymmetry Assesment`, on obtient ≈ `N` volumes orientés ×2, `N` volumes miroirs ×2, `3N` masques, `3N` recalages, `30N` fichiers `.vtk` de segmentation (6 × 5 dossiers), `3N` heatmaps, `5N` fichiers de landmarks, puis **5 fichiers Excel au total** (3 mesures + 1 post-process + 1 classification), tous patients confondus.
- **Nettoyage final** (`VFACE.py:1439-1453`) : si *Keep Intermediate files* n'est **pas** coché, tout sous-dossier de `OutputFolder` dont le nom n'est pas dans `files_to_keep` est **supprimé récursivement** (`shutil.rmtree`).
- **Variation selon `comboBox3`** : en `File already Oriented` / `File already Registered`, les étapes resample/centrage/ALI/ASO (et, pour `File already Registered`, masques + miroir + AREG) ne sont pas ajoutées à la liste ; les fichiers fournis sont simplement **copiés** dans l'arborescence de sortie (`createlistprocess.py:184-186`, `629-633`).
- **Sortie « visualisation intermédiaire »** : si *Intermediate Output Check* est coché, la première sortie trouvée est chargée dans Slicer après certaines étapes (`VFACE.py:1322-1331`, `1356-1366`), formats supportés `.nrrd`, `.nii`, `.nii.gz`, `.vtk` (`VFACE.py:1186-1204`). Aucun fichier n'est écrit par ce mécanisme.

## Comportement dossier vs fichier

- **Tout est dossier** : les 4 `ctkPathLineEdit` sont en mode `Dirs` (`VFACE.ui:169,181,212,222`). Il n'existe **aucun** mode « fichier unique » dans l'UI, contrairement à ce que laisse entendre le README (« Supports analysis of single files or batch processing », `README.md:855`).
- **Récursivité incohérente** :
  - `GetPatients` / `search` : **récursif** (`iglob(path/**/*, recursive=True)`, `createlistprocess.py:2526`) - sert au comptage de scans et à la liste de patients transmise aux heatmaps.
  - `SplitOriented`, `SplitT2`, `SplitMeasurements` : **non récursifs** (`Path.glob`, lignes 1523, 1568, 1603).
  - `SegmentationLogic.setInputFolder` : **récursif** (`rglob("*.nii*")`, `segmentation_logic.py:92`).
  - `batch_process` (heatmaps) : **non récursif** (`Path.iterdir()`, `createlistprocess.py:2358,2370`).
  - `createDictPatient` (AQ3DC) : **récursif** (`glob.iglob(folder/**/, recursive=True)`, `functionaq3dc.py:1477`).
- **Appariement T1/T2** : par identifiant patient dérivé du nom de fichier, découpé sur `_Scan`, `_scan`, `_Or`, `_OR`, `_MAND`, `_MD`, `_MAX`, `_MX`, `_CB`, `_lm`, `_T2`, `_T1`, `_Cl`, puis `.` (`createlistprocess.py:1782-1797` et `2339-2355`). AQ3DC utilise une règle **différente** : tout ce qui précède le premier `_` (`functionaq3dc.py:1481`). Deux conventions de nommage cohabitent donc dans le même pipeline.

## Incohérences et pièges observés dans le code

1. **Le nettoyage final détruit les résultats de quantification.** `files_to_keep` teste `"Quantification" in self.ui.comboBox2.currentText` (`VFACE.py:1444`) alors que les libellés du combo sont `Quantitative + Visualization` et `Quantitative (AQ3DC+ Classification)` (`VFACE.ui:66,71`). La condition est **toujours fausse** → si *Keep Intermediate files* est décoché, `Measurements/` et `Classification/` sont supprimés (`VFACE.py:1452`). Le test `"Quantitative"` utilisé pour `bool_quantification` (`VFACE.py:1001`) est, lui, correct : la faute est isolée au nettoyage.
2. **La table `getOutputPathForModule` est obsolète** (`VFACE.py:1224-1232`) : elle pointe vers `Oriented Scans/Oriented relative CB`, `Oriented Scans/Oriented relative MAX`, `Masks`, `Mirrored_Masks`, `Mirrored_Scan/CB` - **aucun** de ces dossiers n'est créé par `createlistprocess.py`, qui écrit dans `Oriented T1 Scans/{CB,MAX}`, `T1 Masks`, `T2_Masks`, `T2_Scan/{CB,MAX}`. Sur les 7 entrées, seules `AREG - Registering Scan (MAND)` et `BDS - Segmentation T2 MAX` correspondent à un chemin réel → la pause « Intermediate Output Check » est muette pour la plupart des étapes marquées `pause_for_visualization` (`createlistprocess.py:288,352,466,540`).
3. **Le bouton *Default* peut empêcher le téléchargement des modèles ML.** `onDefaultButton` crée `<Downloads>/V_FACE/DefaultList` (`VFACE.py:1042-1046`), donc `<Downloads>/V_FACE` existe ; or `DownloadUnzip` ne télécharge que si le dossier cible n'existe pas (`VFACE.py:836`). Cliquer *Default* **avant** *Check Dependencies* fait que `V_FACE_Models.zip` n'est jamais récupéré → `VFACE_CLI` échouera sur `sym_asymm.txt` introuvable (`VFACE_CLI.py:90-91`).
4. **Poids nnU-Net manquants pour le modèle par défaut.** `_getModelParameter` pointe vers `VFACE/Resources/ML/Dataset111_453CT/.../` (`segmentation_logic.py:327`) mais le dépôt ne contient que `dataset.json` et `plans.json` - pas de `fold_0/checkpoint_final.pth`. Seuls les 3 modèles alternatifs ont une route de téléchargement (`segmentation_logic.py:341-363`), et `downloadWeightsIfNeeded` est un stub retournant `True` (`segmentation_logic.py:57-60`). `download_info.json` n'est référencé nulle part dans le code. `nnUnetFolder()` renvoie de surcroît un chemin faux (`VFACE_utils/VFACE/Resources/ML`, `segmentation_logic.py:852-855`) et n'est jamais appelé.
5. **NRRD accepté en entrée mais ignoré par la segmentation.** `SplitOriented`/`SplitT2` acceptent `.nrrd` et `.nrrd.gz` (`createlistprocess.py:1568,1603`) alors que `setInputFolder` ne collecte que `*.nii*`/`*.gipl*` (`segmentation_logic.py:92`) : un jeu de données NRRD produit `VTK Files/*` vides, puis `Heatmaps/` vide, sans erreur explicite.
6. **Chemins non portables (Windows).** Les copies utilisent `file_info['path'].split("/")[-1]` (`createlistprocess.py:186,632`) au lieu de `os.path.basename` : sous Windows le « nom de fichier » contiendra le chemin complet.
7. **Landmarks ALI sous-détectés.** `create_list_measure` parcourt toutes les feuilles Excel (`createlistprocess.py:1722`) mais `create_list_landmark` seulement la première (`createlistprocess.py:1741`) : les mesures définies sur les feuilles suivantes référenceront des landmarks jamais prédits par ALI → `KeyError`/valeurs manquantes en aval.
8. **Liste de landmarks erronée pour la mandibule T2** (mode `Longitudinal studies`) : `parameter_ali_mand` utilise `list_landmark_max` (`createlistprocess.py:1080`) au lieu de la liste mandibulaire.
9. **`input_matrix` devient un dossier en mode `File already Registered`** (`createlistprocess.py:952-953, 978-979, 1003-1004`) alors que le reste du code passe un fichier `.tfm` - comportement dépendant de la tolérance d'`automatrix_cli`.
10. **Boucle `for patient` inutilement quadratique** : les 3 appels `automatrix` de mirroring+recalage des landmarks sont ajoutés **une fois par patient** (`createlistprocess.py:938-1015`) alors que `input_patient` est le dossier complet → chaque patient re-traite tous les patients (3 × N² exécutions).
11. **Deux widgets portent le même `objectName` `label_5`** (`VFACE.ui:96` « Mode » et `VFACE.ui:129` « Where start? ») : `slicer.util.childWidgetVariables` n'en exposera qu'un.
12. **Valeurs par défaut fantaisistes du parameter node** : `InputFolder = "test"` et `OutputFolder = "testt"` (`VFACE.py:700-703`), poussées dans l'UI via `connectGui`.
13. **Code mort / copié du template** : `VFACELogic.process` applique un simple seuillage `thresholdscalarvolume` (`VFACE.py:1489-1525`) et `registerSampleData` enregistre deux volumes de test Slicer sans rapport, avec des vignettes `VFACE1.png`/`VFACE2.png` absentes de `Resources/Icons` (`VFACE.py:101-130`). `VFACETest` teste ce seuillage, pas VFACE.
14. **Étape de classification exécutée en synchrone bloquant côté Python** pour les processus non-CLI (`VFACE.py:1288-1309`) : `startPythonProcess` appelle directement la fonction, le `QTimer`/`checkPythonProcessStatus` est purement décoratif - l'UI gèle pendant BDS et les heatmaps.
15. **`lightgbm` importé mais inutilisé dans le CLI** (`VFACE_CLI.py:16`) - il reste néanmoins nécessaire au dépicklage des modèles par `joblib`.
16. **Modèles ML nommés `.txt`** (`VFACE_CLI.py:84-86`) alors que ce sont des artefacts binaires `joblib` : trompeur et fragile (validation d'extension, transferts).
17. **`comboBox` (Registration Type) quasi inopérant** : `AREG`/`CMFReg` ne change que l'ajout du mirroring des masques (`createlistprocess.py:470`) ; dans les deux cas c'est `areg_cbct` qui recale.
18. **`CreateListProcess` peut retourner `None`** (`createlistprocess.py:190,636`) alors que `onApplyButton` fait immédiatement `len(self.list_process)` puis `self.list_process[0]` (`VFACE.py:1014-1015`) → `TypeError` non gérée si le dossier d'entrée ne contient aucun fichier reconnu.
19. **Interpolation de distance dégradée silencieusement** : `interpolate_distance_to_original` ne calcule les distances que pour les 1000 premiers points face aux 100 premiers points source (`createlistprocess.py:2177-2193`), le reste restant à 0.0 - les heatmaps de gros maillages peuvent être majoritairement nulles sans avertissement. Idem `create_fallback_result` qui écrit un maillage à distance nulle (`createlistprocess.py:2070-2094`).
20. **Timeout dur de 600 s par paire de heatmap** (`createlistprocess.py:2461`) : au-delà, la paire est simplement perdue (log d'erreur, pas d'échec global).

## Avis - entrées/sorties à ajouter ou retirer

**À ajouter**

- **Un vrai mode « fichier unique »** (ou au moins l'acceptation d'un fichier dans `PathLineEdit`) pour aligner le code sur la promesse du README (`README.md:855`), ou corriger le README.
- **Sélecteur de device (`cuda`/`cpu`/`mps`) et de modèle de segmentation** : `run_bds` force `cuda` et `DentalSegmentator` (`createlistprocess.py:1239`) alors que `SegmentationLogic` supporte déjà 4 modèles et 3 devices (`segmentation_logic.py:100-110`) ; sur machine sans GPU l'étape échoue sans recours.
- **Téléchargement effectif des poids nnU-Net** dans `CheckDependency`, en utilisant `Resources/ML/download_info.json` déjà présent - aujourd'hui la dépendance la plus lourde du pipeline n'est jamais vérifiée.
- **Un `.csv`/`.json` récapitulatif par patient** consolidant classification + mesures clés : le seul livrable final est un `Classification.xlsx` unique, difficile à réintégrer patient par patient.
- **Un fichier de log persistant dans `OutputFolder`** (liste des étapes, patients traités, patients sautés) : actuellement tout part dans la console Python, et les patients ignorés par `SplitOriented`/`batch_process` disparaissent silencieusement.
- **Sortie « qualité »** : nombre de paires heatmap réellement traitées vs attendues (l'information existe déjà, `createlistprocess.py:2498-2500`, mais n'est pas persistée).

**À retirer / corriger**

- **Retirer `registerSampleData`, `VFACELogic.process` et `VFACETest`** : code du template Slicer sans rapport, qui télécharge des volumes tiers et référence des icônes inexistantes (`VFACE.py:85-130`, `1489-1594`).
- **Retirer ou reconstruire `getOutputPathForModule`** (`VFACE.py:1223-1245`) : table de chemins morte qui rend l'option *Intermediate Output Check* trompeuse.
- **Retirer la suppression automatique des dossiers** ou, a minima, corriger `"Quantification"` → `"Quantitative"` (`VFACE.py:1444`) et restreindre `shutil.rmtree` aux dossiers effectivement créés par VFACE : en l'état, pointer un `OutputFolder` déjà peuplé fait perdre des données utilisateur.
- **Retirer `comboBox` (Registration Type)** de l'UI tant qu'il ne pilote que le mirroring des masques, ou l'implémenter réellement.
- **Normaliser les extensions acceptées** : soit ajouter le NRRD à la segmentation, soit refuser explicitement le NRRD à l'entrée (message clair plutôt que des dossiers VTK vides).
- **Unifier les règles d'extraction d'identifiant patient** (`createlistprocess.py:1782` vs `functionaq3dc.py:1481`) et la récursivité des scans : c'est la principale source de « patients qui disparaissent » entre deux étapes.
