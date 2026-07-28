# AREG (AREG_CBCT / AREG_IOS / AREG_IOSCBCT)

## Rôle

AREG (« Automatic REGistration ») est le module Slicer de recalage automatique longitudinal / inter-modalité de l'extension SlicerAutomatedDentalTools. Il ne réalise lui-même aucun calcul : `AREGWidget` (`AREG/AREG.py:319`) collecte les chemins et options, délègue à une classe « Method » (`AREG/AREG_Method/Method.py:21`) qui construit une **liste ordonnée de processus** (`Process()` retourne `list_process`), puis exécute ces processus séquentiellement via `slicer.cli.run` ou via un environnement conda (`AREG/AREG.py:1342-1402`, `AREG/AREG.py:1879-2014`).

Trois familles d'entrée sont sélectionnables dans la combo `CbInputType` (`AREG/Resources/UI/AREG.ui:272-290`) : **CBCT to CBCT**, **IOS to IOS**, **IOS to CBCT**. Chaque famille expose des modes dans `CbModeType`, remplis dynamiquement par `SwitchType` (`AREG/AREG.py:749-830`) :

| Famille (`CbInputType`) | Mode (`CbModeType`) | Classe Method | CLI de recalage final |
|---|---|---|---|
| CBCT/CBCT (idx 0) | 0 = Orientation and Registration | `Or_Auto_CBCT` (`AREG/AREG_Method/CBCT.py:566`) | `AREG_CBCT` |
| CBCT/CBCT | 1 = Fully-Automated Registration | `Auto_CBCT` (`AREG/AREG_Method/CBCT.py:374`) | `AREG_CBCT` |
| CBCT/CBCT | 2 = Semi-Automated Registration | `Semi_CBCT` (`AREG/AREG_Method/CBCT.py:33`) | `AREG_CBCT` |
| IOS/IOS (idx 1) | 0 = Orientation and Registration | `Auto_IOS` (`AREG/AREG_Method/IOS.py:27`) | `AREG_IOS` |
| IOS/IOS | 1 = Registration | `Semi_IOS` (`AREG/AREG_Method/IOS.py:448`) | `AREG_IOS` |
| IOS/CBCT (idx 2) | 0 = Fully Automated Registration | `Auto_IOSCBCT` (`AREG/AREG_Method/IOSCBCT.py:437`) | `AREG_IOSCBCT` |
| IOS/CBCT | 1 = Semi Automated Registration | `Semi_IOSCBCT` (`AREG/AREG_Method/IOSCBCT.py:156`) | `AREG_IOSCBCT` |
| IOS/CBCT | 2 = Registration | `Reg_IOSCBCT` (`AREG/AREG_Method/IOSCBCT.py:368`) | `AREG_IOSCBCT` |

Les trois CLI ne font que le recalage terminal ; l'orientation (ASO/PRE_ASO), la détection de landmarks (ALI_CBCT / ALI_IOS), la segmentation (AMASSS_CLI, CrownSegmentationcli) et le rééchantillonnage (MRI2CBCT) sont des **modules externes** appelés en amont dans la même chaîne.

Algorithmes de recalage :
- **AREG_CBCT** : recalage rigide voxel-based Elastix (`itk.ElastixRegistrationMethod`, EulerTransform, Mattes MI, 3 résolutions) sur l'image T1 **masquée** par la segmentation de la zone choisie (`AREG_CBCT/AREG_CBCT_utils/utils.py:501-674`).
- **AREG_IOS** : prédiction d'un patch « Butterfly » sur le palais par réseau MONAI UNet (`AREG_IOS/AREG_IOS_utils/PredPatch.py:21-92`) puis ICP VTK rigide restreint à ce patch (`AREG_IOS/AREG_IOS_utils/ICP.py:93-112`, option `vtkMeshTeeth(list_teeth=[1], property="Butterfly")`, `AREG_IOS/AREG_IOS.py:120-122`).
- **AREG_IOSCBCT** : alignement rigide par landmarks (`vtkLandmarkTransform`, `AREG_IOSCBCT/AREG_IOSCBCT.py:32-61`) puis ICP point-to-plane maison (SVD + cKDTree, 2000 itérations max) contre une isosurface CBCT extraite au seuil 400 HU (`AREG_IOSCBCT/AREG_IOSCBCT.py:63-163`, `:234`).

---

## Entrées

### Vue d'ensemble UI (widgets communs aux trois familles)

| Widget UI | Variable | Rôle selon le mode | Référence |
|---|---|---|---|
| `lineEditScanT1LmPath` + `ButtonSearchScan1` | `input_t1_folder` | T1 Scans / **IOS Scans** (IOSCBCT) | `AREG/Resources/UI/AREG.ui:348`, `AREG/AREG.py:481-483` |
| `lineEditScanT2LmPath` + `ButtonSearchScan2` | `input_t2_folder` | T2 Scans / **CBCT Scans** (IOSCBCT) | `AREG/Resources/UI/AREG.ui:193`, `AREG/AREG.py:487-489` |
| `lineEditMaskT1Path` + `ButtonSearchT1Mask` | `input_t1_mask` | « T1 Masks » (Semi_CBCT) ou « IOS Landmarks » (Reg_IOSCBCT) | `AREG/AREG.py:484-486`, `:573-576`, `:727-730` |
| `lineEditT2LMPath` + `ButtonSearchT2LM` | `input_t2_landmarks` | « CBCT Landmarks » (Reg_IOSCBCT uniquement) | `AREG/AREG.py:491-493`, `:736-738` |
| `lineEditModel1` / `lineEditModel2` / `lineEditModel3` | `model_folder_1/2/3` | sémantique **variable selon le mode** (voir tableaux par mode) | `AREG/AREG.py:495-509` |
| `CbCBCTInputType` | `isDCMInput` | « NIFTI, NRRD, GIPL » (idx 0) ou « DICOM » (idx 1) | `AREG/Resources/UI/AREG.ui:297-310`, `AREG/AREG.py:540-545` |
| `lineEditAddName` | `add_in_namefile` | suffixe des sorties, défaut `Reg` | `AREG/Resources/UI/AREG.ui:566-572` |
| `lineEditOutputPath` + `ButtonOutput` | `folder_output` | dossier de sortie | `AREG/Resources/UI/AREG.ui:587-602`, `AREG/AREG.py:1157-1162` |
| `ApproxcheckBox` | `ApproxStep` | « Include Approximation Step », coché par défaut | `AREG/Resources/UI/AREG.ui:429-440`, `AREG/AREG.py:1321` |
| `LabelSelectcomboBox` | `LabelSeg` | label de segmentation à isoler — **masqué en permanence** | `AREG/Resources/UI/AREG.ui:460-466`, `AREG/AREG.py:518`, `:1318-1320` |
| Cases à cocher dynamiques | `dic_checkbox` | zones de recalage + structures AMASSS (CBCT seulement) | `AREG/AREG.py:2033-2057` |

**Tous les sélecteurs sont des dossiers** : `SearchScan` utilise `qt.QFileDialog.getExistingDirectory` (`AREG/AREG.py:1029-1031`), idem pour la sortie (`AREG/AREG.py:1158-1160`). Aucun champ n'accepte un fichier unique.

### Mode CBCT/CBCT

Zones de recalage et structures de segmentation (cases créées par `initCheckBoxCBCT`, `AREG/AREG.py:2033-2057`, à partir de `DicLandmark`, `AREG/AREG_Method/CBCT.py:197-212`) :

- **Regions of Reference for Registration** : `Cranial Base`, `Mandible`, `Maxilla` → traduites en `CB`, `MAND`, `MAX` (`AREG/AREG_Method/CBCT.py:214-246`). Au moins une est obligatoire (`TestCheckbox`, `AREG/AREG_Method/CBCT.py:73-81`).
- **AMASSS Segmentation** (post-traitement optionnel) : `Cranial Base`, `Cervical Vertebra`, `Mandible`, `Maxilla`, `Skin`, `Upper Airway`.
- `merge_seg_checkbox` « Merge Segmentations », cochée par défaut (`AREG/AREG.py:2054-2057`) → `MERGE` / `SEPARATE`.

| Entrée | Type | Extensions réellement acceptées | Récursif | Obligatoire (mode) | Référence |
|---|---|---|---|---|---|
| Dossier T1 | scans CBCT | `.nii.gz`, `.nii`, `.nrrd`, `.nrrd.gz`, `.gipl`, `.gipl.gz` (+ `.json` collectés mais inutilisés) | **Oui** (`iglob(**, recursive=True)`) | tous | `AREG_CBCT/AREG_CBCT_utils/utils.py:70-72`, `:262-292` |
| Dossier T2 | scans CBCT | idem | Oui | tous | idem |
| Dossier masques T1 | segmentations binaires/labels | mêmes extensions image | Oui | **Semi_CBCT seulement** | `AREG/AREG_Method/CBCT.py:104-105`, `AREG_CBCT/AREG_CBCT_utils/utils.py:111-138` |
| Dossiers DICOM | arborescence `T1/<patient>/*.dcm` | dossiers (un sous-dossier par patient) | 1 niveau | option DICOM, **mode 0 seulement** | `AREG/AREG_Method/CBCT.py:602-632`, `AREG_CBCT/AREG_CBCT_utils/utils.py:719-729` |
| `model_folder_1` | modèles AMASSS | dossier contenant `AMASSS_Models/` + ≥1 `.pth` | Oui | tous | `AREG/AREG_Method/CBCT.py:83-89`, `:323` |
| `model_folder_2` | modèles d'orientation ASO | sous-dossiers `PreASO/` et `<Référence>/` | — | **mode 0** | `AREG/AREG_Method/CBCT.py:682`, `:717` |
| `model_folder_3` | modèles ALI_CBCT | dossier `ALI` rempli par `SearchModelALI` — **champ caché** | — | mode 0 (implicite) | `AREG/AREG.py:1104-1154`, `AREG/AREG_Method/CBCT.py:699` |

**Règle d'appariement patient (CBCT)** — `GetPatients` (`AREG_CBCT/AREG_CBCT_utils/utils.py:68-140`, dupliqué côté module dans `AREG/AREG_Method/CBCT.py:911-982`) :

```
patient = basename.split("_Scan")[0].split("_scan")[0].split("_Or")[0].split("_OR")[0]
                  .split("_MAND")[0].split("_MD")[0].split("_MAX")[0].split("_MX")[0]
                  .split("_CB")[0].split("_lm")[0].split("_T2")[0].split("_T1")[0]
                  .split("_Cl")[0].split(".")[0]
```

Un fichier est classé **segmentation** si son nom (minuscule) contient `mask`, `seg` ou `pred` (`utils.py:99`), sinon **scan** (`utils.py:104`). Quand `segmentationType` est fourni (c'est toujours le cas depuis le CLI, `AREG_CBCT/AREG_CBCT.py:128`), le masque est recherché dans `mask_folder_t1` s'il est fourni, sinon dans le dossier T1 lui-même, et il doit contenir un mot-clé de zone : `CB`→`cb`, `MAND`→`mand`/`md`, `MAX`→`max`/`mx` (`utils.py:51-57`, `:111-138`). La fusion T1/T2 est faite par `MergeDicts` qui **itère sur les clés T1** : un patient présent uniquement en T2 est silencieusement ignoré (`utils.py:236-245`).

`GetDictPatients` est aussi appelé côté UI pour compter les patients (`NumberScan`, `AREG/AREG_Method/CBCT.py:51-52`) et pour valider (`TestScan`, `AREG/AREG_Method/CBCT.py:149-174`) : `Semi_CBCT` exige `["scanT1","scanT2","segT1"]`, `Auto_CBCT` et `Or_Auto_CBCT` seulement `["scanT1","scanT2"]` (`:381-384`, `:597-600`).

### Mode IOS/IOS

| Entrée | Type | Extensions réellement acceptées | Récursif | Obligatoire | Référence |
|---|---|---|---|---|---|
| Dossier T1 | surfaces IOS | `.vtk`, `.stl` **uniquement** côté module | Oui (`Method.search`) | tous | `AREG/AREG_Method/IOS.py:32-33`, `:61-65`, `AREG/AREG_Method/Method.py:196-211` |
| Dossier T2 | surfaces IOS | idem | Oui | tous | idem |
| — même dossier, côté CLI | surfaces | `.vtk`, `.vtp`, `.stl`, `.obj` (filtre `endswith`, `.tfm` exclu) | **Non** (`glob.glob(T1/*)`) | — | `AREG_IOS/AREG_IOS_utils/dataset.py:118-124` |
| `model_folder_1` | modèle de segmentation | dossier contenant **exactement un** `.pth` | Oui | Auto_IOS (validé mais **jamais utilisé**) | `AREG/AREG_Method/IOS.py:85-89`, `:213-216` |
| `model_folder_2` | « Reference Orientation Folder » (gold files ASO) | ≥1 `.vtk` **et** ≥1 `.json` (max 2 de chaque) | Oui | Auto_IOS | `AREG/AREG_Method/IOS.py:132-156`, `:357` |
| `model_folder_3` | « Registration Model Folder » | dossier contenant **exactement un** `.ckpt` | Oui | Auto_IOS + Semi_IOS | `AREG/AREG_Method/IOS.py:90-93`, `:383`, `:480` |

**Règle d'appariement patient (IOS)** — `Sort`/`sort` (`AREG_IOS/AREG_IOS_utils/dataset.py:98-170`, `:241-265`) : le nom de base T1 privé de la sous-chaîne `"T1"` doit être **strictement égal** au nom de base T2 privé de `"T2"`. Exemple : `P1_Upper_T1_Seg.vtk` ↔ `P1_Upper_T2_Seg.vtk`.

Détection Upper/Lower (**sensible à la casse**) : Lower = `["Lower","_L","L_","Mandibule","Md"]`, Upper = `["Upper","_U","U_","Maxilla","Mx"]` (`dataset.py:204-238`). Tout fichier ne portant pas de marqueur *Upper* est rangé dans la liste **Lower** (`dataset.py:138-142`). Le recalage est calculé sur l'arcade **supérieure** uniquement, la matrice étant ensuite appliquée à l'inférieure (`AREG_IOS/AREG_IOS.py:244-269`).

Segmentation dentaire préalable : `__BypassCrownseg__` (`AREG/AREG_Method/IOS.py:226-240`) inspecte chaque surface et la considère déjà segmentée si un tableau de points nommé `PredictedID`, `UniversalID` ou `Universal_ID` existe (`:242-265`) ; sinon elle est envoyée à CrownSegmentationcli. Le CSV d'entrée de la segmentation est construit par `os.walk` filtré sur `.vtk`/`.stl` (`AREG/AREG_Method/IOS.py:108-110`).

### Mode IOS/CBCT

| Entrée | Type | Extensions réellement acceptées | Récursif | Obligatoire (mode) | Référence |
|---|---|---|---|---|---|
| Dossier IOS (`input_t1_folder`) | surfaces | `.vtk`, `.stl` pour la construction du CSV de segmentation ; **`.vtk` seul** côté CLI | `os.walk` (oui) / `os.listdir` (non) | tous | `AREG/AREG_Method/IOSCBCT.py:224-231`, `AREG_IOSCBCT/AREG_IOSCBCT.py:294-296` |
| Dossier CBCT (`input_t2_folder`) | volumes | `.nrrd`, `.nrrd.gz`, `.nii`, `.nii.gz`, `.gipl`, `.gipl.gz` pour le comptage ; **`.nii.gz` seul** côté CLI | oui / non | tous | `AREG/AREG_Method/IOSCBCT.py:31-37`, `AREG_IOSCBCT/AREG_IOSCBCT.py:311-313` |
| Dossier « IOS Landmarks » (`lineEditMaskT1Path`) | markups | `.json` | Non (`os.listdir`) | **Reg_IOSCBCT** | `AREG/AREG_Method/IOSCBCT.py:390-391`, `AREG_IOSCBCT/AREG_IOSCBCT.py:326-328` |
| Dossier « CBCT Landmarks » (`lineEditT2LMPath`) | markups | `.json` | Non | **Reg_IOSCBCT** | `AREG/AREG_Method/IOSCBCT.py:393-394`, `AREG_IOSCBCT/AREG_IOSCBCT.py:344-346` |
| `model_folder_1` | « Orientation Model Folder » (PreASO + gold CBCT + gold IOS) | sous-dossiers `PreASO/`, `<Référence>/`, `IOS/` | — | **Auto_IOSCBCT** | `AREG/AREG_Method/IOSCBCT.py:602`, `:629`, `:708` |
| `model_folder_2` | « CBCT Landmarks identification Folder » (ALI_CBCT) | dossier de modèles | — | Auto + Semi | `AREG/AREG_Method/IOSCBCT.py:289`, `:750` |
| `model_folder_3` | « IOS Landmarks identification Folder » (ALI_IOS) | dossier de modèles | — | Auto + Semi | `AREG/AREG_Method/IOSCBCT.py:320`, `:780` |

**Règle d'appariement patient (IOS/CBCT)** — `getPatients` (`AREG_IOSCBCT/AREG_IOSCBCT.py:240-366`), entièrement par expressions régulières sur le nom de fichier :

- timepoint : `re.search(r'[Tt]([0-2])', filename)` → `T0`/`T1`/`T2` (`:251-254`) ;
- mâchoire : `re.search(r'[_]?[uU][_]?', filename)` → *upper*, sinon `[_]?[lL][_]?` → *lower* (`:256-263`) ;
- identifiant : `re.search(r'([A-Za-z]+)[_]?([0-9]+)[_]?[Tt][0-2]', filename)` → lettres + chiffres (`:265-270`), puis normalisation qui supprime les `_` et les zéros de tête (`P_0001`, `P001`, `P00001` → `P1`, `:272-291`).

La clé de regroupement est `f"{patient_id}_{timepoint}"` : **chaque timepoint est un « patient » distinct**. Un patient complet exige 5 fichiers : `ios_upper`, `ios_lower`, `cbct`, `ios_lm_upper`, `ios_lm_lower`, `cbct_lm_upper`, `cbct_lm_lower` (7 clés en réalité) — toute clé manquante provoque un `KeyError` capturé qui saute le patient (`AREG_IOSCBCT/AREG_IOSCBCT.py:388-393`, `:450-452`).

### Arguments des trois CLI

| CLI | Arguments positionnels | Référence |
|---|---|---|
| `AREG_CBCT` | `t1_folder`, `t2_folder`, `reg_type`, `output_folder`, `add_name`, `DCMInput`, `SegmentationLabel`, `temp_folder`, `ApproxReg`, `mask_folder_t1` | `AREG_CBCT/AREG_CBCT.py:238-247`, `AREG_CBCT/AREG_CBCT.xml:18-86` |
| `AREG_IOS` | `T1`, `T2`, `output`, `model`, `suffix`, `log_path`, `areg_mode` | `AREG_IOS/AREG_IOS.py:308-314`, `AREG_IOS/AREG_IOS.xml:18-65` |
| `AREG_IOSCBCT` | `IOS_folder`, `CBCT_folder`, `IOS_lm_folder`, `CBCT_lm_folder`, `output` | `AREG_IOSCBCT/AREG_IOSCBCT.py:463-467`, `AREG_IOSCBCT/AREG_IOSCBCT.xml:17-50` |

`reg_type` ∈ {`CB`, `MAND`, `MAX`} (`AREG_CBCT/AREG_CBCT.xml:36`, `AREG_CBCT/AREG_CBCT_utils/utils.py:688-691`). `areg_mode` ∈ {`Auto_IOS`, `Semi_IOS`} (`AREG/AREG_Method/IOS.py:386`, `:483`).

---

## Sorties

| Mode | Sortie | Format | Nommage | Cardinalité (N patients) |
|---|---|---|---|---|
| CBCT (tous) | T2 recalé | `.nii.gz` (Int16) | `<output>/<Zone>/<patient>_OutReg/<patient>_<REG>Scan<suffix>.nii.gz` | **N × R** (R = zones cochées) |
| CBCT (tous) | Matrice de recalage | `.tfm` (Euler3D) | `<output>/<Zone>/<patient>_OutReg/<patient>_<REG><suffix>_matrix.tfm` | **N × R** |
| CBCT (tous) | Segmentations AMASSS T1 et T2 | `.nii.gz` + `.vtk` (`genVtk=True`, lissage 5) | géré par AMASSS_CLI, `prediction_ID="seg"` | 2 × N × (structures cochées), 0 si aucune structure cochée |
| CBCT Auto/Or | Masques de recalage T1 | `.nii.gz` | écrits **dans le dossier T1** (Auto) ou dans `<T1>Or` (Or_Auto) | N × R |
| CBCT (tous) | T2 recentré (intermédiaire persistant) | `.nii.gz` | dossier `<input_t2_folder>_Center` | N |
| CBCT Or_Auto | T1 orienté (intermédiaire persistant) | `.nii.gz` | dossier `<input_t1_folder>Or` + `.tfm`/`.json` produits par ASO/ALI | N |
| IOS Auto/Semi | Surface T1 avec patch Butterfly | contenu **VTK legacy**, extension d'origine conservée | `<output>/<nomT1><suffix><ext>` | N |
| IOS Auto/Semi | Surface T2 recalée | idem | `<output>/<nomT2><suffix><ext>` | N |
| IOS Auto/Semi | Surfaces Lower T1 / T2 recalées | idem | `<output>/<nomLowerT1><suffix><ext>`, `<nomLowerT2>…` | N si arcades inférieures présentes |
| IOS **Auto seulement** | Matrice ASO T1 (copie) | `.tfm` | `<output>/<patient>_T1_SegOr.tfm` | N (si le `.tfm` source existe) |
| IOS **Auto seulement** | Matrice composée T2 | `.tfm` (Affine) | `<output>/<patient>_T2_SegOr<suffix>.tfm` | N |
| IOSCBCT (tous) | IOS supérieur recalé | `.vtk` | `<output>/<patient>_<Tx>_Reg_U.vtk` | 1 par (patient, timepoint) |
| IOSCBCT (tous) | IOS inférieur recalé | `.vtk` | `<output>/<patient>_<Tx>_Reg_L.vtk` | 1 par (patient, timepoint) |
| IOSCBCT (tous) | Landmarks IOS recalés | `.mrk.json` | `<output>/<patient>_<Tx>_lm_Reg_U.mrk.json` et `…_L.mrk.json` | 2 par (patient, timepoint) |
| IOSCBCT Auto/Semi | Dossiers intermédiaires **dans le dossier de sortie** | — | `Seg IOS/`, `PRE ASO IOS/`, `CBCT Resampled/`, `PRE ASO CBCT/`, `Oriented CBCT/`, `CBCT Landmarks/`, `IOS Landmarks/`, `Registered IOS/` | 1 jeu par exécution |

### Détails de nommage et cardinalité

**CBCT** (`AREG_CBCT/AREG_CBCT.py:152-158`) :

```python
outpath      = os.path.join(output_dir, translate(reg_type), patient + "_OutReg")
ScanOutPath  = os.path.join(outpath, patient + "_" + reg_type + "Scan" + add_name + ".nii.gz")
TransOutPath = os.path.join(outpath, patient + "_" + reg_type + add_name + "_matrix.tfm")
```

`translate` produit un nom **avec espace** : `Cranial Base`, `Mandible`, `Maxilla` (`AREG_CBCT/AREG_CBCT_utils/utils.py:688-691`). Avec 3 zones cochées et 10 patients : 3 exécutions du CLI `AREG_CBCT` (boucle `for i, reg in enumerate(reg_struct.split(","))`, `AREG/AREG_Method/CBCT.py:296`, `:481`, `:813`) → 30 volumes + 30 matrices, rangés dans 3 arborescences distinctes. Les fichiers sont écrits par `sitk.WriteTransform` et `sitk.WriteImage` (`AREG_CBCT/AREG_CBCT.py:185-187`).

**IOS** (`AREG_IOS/AREG_IOS_utils/utils.py:159-169`) :

```python
def WriteSurf(surf, output_folder, name, inname):
    dir, name = os.path.split(name); name, extension = os.path.splitext(name)
    writer = vtk.vtkPolyDataWriter()
    writer.SetFileName(os.path.join(output_folder, f"{name}{inname}{extension}"))
```

L'écrivain est **toujours** `vtkPolyDataWriter` alors que l'extension d'origine est conservée : une entrée `.stl` produit un fichier nommé `.stl` contenant du VTK legacy. Les matrices ne sont écrites que si `areg_mode == "Auto_IOS"` (`AREG_IOS/AREG_IOS.py:214`) ; l'identifiant patient est extrait par `name_t2.split("_T2")[0]` puis `.split("_")[0]` (`AREG_IOS/AREG_IOS.py:217-218`). La matrice T2 est composée avec la matrice ASO : `inv(areg @ inv(aso))` (`AREG_IOS/AREG_IOS_utils/transformation.py:88`).

**IOSCBCT** (`AREG_IOSCBCT/AREG_IOSCBCT.py:165-169`, `:183-184`) : 4 fichiers par clé `<patient>_<timepoint>`. Le JSON de sortie **réutilise le fichier de landmarks CBCT comme gabarit** et n'en remplace que les positions par les landmarks IOS transformés (`:186-202`) — les labels/couleurs proviennent donc du CBCT. Les matrices `mat_ios_upper/lower` (landmark transform) et `mat_icp_upper/lower` (ICP) sont calculées mais **jamais écrites sur disque**.

### Variations selon les options

- **Zones de recalage cochées** → multiplie les exécutions d'`AREG_CBCT` et crée un sous-dossier par zone (`AREG/AREG_Method/CBCT.py:296-317`).
- **Structures AMASSS cochées** → si la liste est vide, aucune étape de segmentation n'est ajoutée (`AREG/AREG_Method/CBCT.py:351`, `:541`, `:871`).
- **`Merge Segmentations`** → `merge="MERGE"` vs `"SEPARATE"` (`AREG/AREG_Method/CBCT.py:325`, `:514`).
- **`save_in_folder`** : `True` en Semi_CBCT (`:328`, `:342`) mais `False` en Auto/Or_Auto (`:516`, `:530`, `:847`, `:861`) → l'arborescence des segmentations diffère entre modes.
- **Suffixe `add_in_namefile`** : utilisé en CBCT (`add_name`) et IOS (`suffix`) ; **ignoré en IOS/CBCT** (non transmis au CLI) bien qu'exigé par `TestProcess` (`AREG/AREG_Method/IOSCBCT.py:110-111`, `:187-188`, `:399-400`).
- **`ApproxcheckBox`** : transmis jusqu'au CLI (`ApproxReg` → `approx`) mais **sans aucun effet** (voir Incohérences).
- **`LabelSelectcomboBox`** : `SegmentationLabels = [0]` en dur → `LabelSeg = "0"` → `SegLabel = None` dans le CLI (`AREG/AREG.py:408`, `:1318-1320`, `AREG_CBCT/AREG_CBCT.py:63`, `:68-69`).

---

## Comportement dossier vs fichier

- **Tout est dossier.** `SearchScan` et `ChosePathOutput` n'ouvrent que `QFileDialog.getExistingDirectory` (`AREG/AREG.py:1029-1031`, `:1158-1160`). Aucun mode n'accepte un scan isolé.
- **Récursivité asymétrique** :
  - CBCT : `search()` utilise `iglob(path/**/*, recursive=True)` côté module **et** côté CLI → sous-dossiers explorés (`AREG/AREG_Method/CBCT.py:1066-1077`, `AREG_CBCT/AREG_CBCT_utils/utils.py:281-292`).
  - IOS : comptage/validation UI récursifs (`AREG/AREG_Method/Method.py:205-207`) mais le CLI `AREG_IOS` fait un `glob.glob(os.path.join(T1, "*"))` **non récursif** (`AREG_IOS/AREG_IOS_utils/dataset.py:118-119`) → un dossier organisé en sous-dossiers passe la validation puis produit 0 recalage.
  - IOS/CBCT : le CSV de segmentation est construit par `os.walk` (récursif, `AREG/AREG_Method/IOSCBCT.py:224`) mais le CLI `AREG_IOSCBCT` fait 4 `os.listdir` **non récursifs** (`AREG_IOSCBCT/AREG_IOSCBCT.py:294`, `:311`, `:326`, `:344`).
- **Branches « fichier unique » mortes** : `if os.path.isfile(kwargs["input_t1_folder"]): extension = os.path.splitext(self.input)[1]` — `self.input` n'existe sur aucune de ces classes → `AttributeError` immédiat si un chemin de fichier était passé (`AREG/AREG_Method/IOS.py:305-308`, `:331-334`, `AREG/AREG_Method/IOSCBCT.py:244-247`, `:675-678`).
- **DICOM** : arborescence à un niveau `T1/<patient>/`, convertie en `T1/NIFTI/<patient>.nii.gz` (`AREG_CBCT/AREG_CBCT_utils/utils.py:709-736`). Le comptage `NumberScanDCM` retourne simplement `len(os.listdir(scan_folder_t1))` — le sous-dossier `NIFTI` créé par une conversion précédente est donc compté comme un patient (`AREG/AREG_Method/CBCT.py:631-632`).
- **Écriture hors du dossier de sortie** : les dossiers `<input_t2_folder>_Center` et `<input_t1_folder>Or` sont créés **à côté des dossiers d'entrée** (`AREG/AREG_Method/CBCT.py:269`, `:451`, `:714`, `:786`), et en mode `Auto_CBCT` les masques AMASSS sont écrits **dans le dossier T1 d'entrée** (`AREG/AREG_Method/CBCT.py:431`). Les données d'entrée sont donc modifiées.

---

## Incohérences et pièges observés dans le code

1. **`ApproxReg` / « Include Approximation Step » : option totalement inopérante.** La case est lue (`AREG/AREG.py:1321`), passée au CLI (`AREG/AREG_Method/CBCT.py:306`, `:491`, `:823`), parsée (`AREG_CBCT/AREG_CBCT.py:65`), transmise à `VoxelBasedRegistration(..., approx=Approx)` — mais le paramètre `approx` n'est **jamais lu** dans le corps de la fonction, qui appelle inconditionnellement `ElastixReg(..., initial_transform=None)` (`AREG_CBCT/AREG_CBCT_utils/utils.py:577`, `:631-633`).

2. **`SegmentationLabel` mort.** `self.SegmentationLabels = [0]` en dur, `LabelSelectcomboBox` masqué au démarrage (`AREG/AREG.py:408`, `:518`) ; la méthode `GetSegmentationLabel` qui remplirait la liste (`AREG/AREG_Method/CBCT.py:176-186`) n'est appelée nulle part. `LabelSeg` vaut donc toujours `"0"` → `SegLabel = None` → `applyMask` ignore le label (`AREG_CBCT/AREG_CBCT_utils/utils.py:477-486`).

3. **Modèle PreASO introuvable en modes Semi_CBCT et Auto_CBCT.** L'étape « Centering T2 » pointe vers `<SlicerDownload>/Models/Orientation/PreASO` (`AREG/AREG_Method/CBCT.py:273-275`, `:455-457`), mais `getModelUrl()` de `Semi_CBCT` ne contient **que** la clé `Segmentation` (`:121-124`) et l'UI masque le bouton de téléchargement du modèle d'orientation dans ces deux modes (`AREG/AREG.py:565-571`, `:590-596`). Le dossier n'existe donc pas, sauf si l'utilisateur a préalablement lancé le mode « Orientation and Registration ».

4. **Modèle de segmentation IOS exigé mais inutilisé.** `Auto_IOS.TestProcess` impose un dossier contenant exactement un `.pth` (`AREG/AREG_Method/IOS.py:202-203`, `:213-216`), mais `model_folder_1` n'apparaît **nulle part** dans `Auto_IOS.Process` : CrownSegmentationcli est lancé avec `"model": "latest"` (`AREG/AREG_Method/IOS.py:319`, `:345`).

5. **Messages d'erreur inversés (IOS).** `model_folder_1` vide → « Please select folder for the registration model » alors que c'est le dossier de **segmentation** ; `model_folder_3` vide → « Please select folder for the segmentation model » alors que c'est le dossier de **recalage** (`AREG/AREG_Method/IOS.py:202-211`). De plus `search(model_folder_3, ".ckpt")` est évalué avant le test de non-vacuité, donc sur une chaîne vide (`:205`).

6. **`TestModel` sans effet en mode IOS/CBCT.** `IOSCBCT.TestModel` ne teste que les noms de widgets `lineEditModelSegOr` et `lineEditModelAli` (`AREG/AREG_Method/IOSCBCT.py:84-96`) — ces widgets **n'existent pas** dans `AREG.ui` (les champs s'appellent `lineEditModel1/2/3`). La fonction retourne toujours `None` : aucune validation de modèle n'est faite.

7. **`SearchModelALI` inutile et coûteux en IOS/CBCT.** Pour `Auto_IOSCBCT`, `downloadModel(..., name="Orientation")` déclenche la pop-up de choix de référence puis `SearchModelALI` qui télécharge 6 à 7 archives ALI et écrit leur chemin dans `lineEditModel1` (`AREG/AREG.py:1052-1067`, `:1152-1153`) — chemin immédiatement **écrasé** par le dossier `Models/Orientation` quelques lignes plus loin (`:1101`). En mode « Test Files », l'enchaînement `SearchModelALI` puis `downloadModel(..., test=True)` déclenche la pop-up et le téléchargement **deux fois** (`AREG/AREG.py:980-984`).

8. **`lineEditModel3` caché mais obligatoire en CBCT mode 0.** `SwitchModeCBCT(0)` masque `label_4`/`lineEditModel3` (`AREG/AREG.py:610-612`) alors que ce champ porte le chemin des modèles ALI_CBCT utilisé par `parameter_ali["dir_models"]` (`AREG/AREG_Method/CBCT.py:699`). `Or_Auto_CBCT.TestProcess` ne le vérifie pas (`:634-662`) : si l'utilisateur n'a jamais cliqué « Download » sur le modèle d'orientation, ALI_CBCT est lancé avec un dossier vide.

9. **Extraction de mâchoire dangereuse (IOS/CBCT).** `re.search(r'[_]?[uU][_]?', filename)` équivaut à chercher **la lettre `u` ou `U` n'importe où** dans le nom (`AREG_IOSCBCT/AREG_IOSCBCT.py:259`). Tout fichier contenant un `u` (ex. `Sub_01_T1_L.vtk`, `Scan_upper_dup.vtk`) est classé *upper*, le test *lower* n'étant évalué qu'en second. De même `[Tt]([0-2])` matche n'importe quel `t0/t1/t2` du nom (`:253`).

10. **Normalisation d'identifiant destructive (IOS/CBCT).** `P001`, `P_0001` et `P00001` sont fusionnés en `P1` (`AREG_IOSCBCT/AREG_IOSCBCT.py:272-291`) : deux patients distincts d'une même cohorte peuvent s'écraser mutuellement dans le dictionnaire.

11. **Extensions non gérées en IOS/CBCT.** Le CLI n'accepte que `.vtk` pour l'IOS (`:296`) et `.nii.gz` pour le CBCT (`:313`), alors que l'UI annonce « NIFTI, NRRD, GIPL » (`AREG/Resources/UI/AREG.ui:302-306`) et que le comptage côté module accepte 6 extensions (`AREG/AREG_Method/IOSCBCT.py:32`). Un dossier de `.nrrd` passe la validation puis produit zéro sortie (seul un warning « No files to process » est loggé, `AREG_IOSCBCT/AREG_IOSCBCT.py:372-373`).

12. **Extensions IOS : écart README / code.** Le README annonce `.vtk .stl .vtp .off .obj` (`README.md:303`). Le module ne compte que `.vtk`/`.stl` (`AREG/AREG_Method/IOS.py:32-33`), le CLI accepte `.vtk/.vtp/.stl/.obj` (`AREG_IOS/AREG_IOS_utils/dataset.py:122`) et `ReadSurf` lève une exception explicite hors de ces quatre formats (`AREG_IOS/AREG_IOS_utils/utils.py:66-67`). `.off` n'est supporté nulle part.

13. **Sortie `.tfm` jamais écrite en mode Semi_IOS.** `saveMatrixAsTfm` possède une branche `else` produisant `<patient>_T2_Seg<suffix>.tfm` (`AREG_IOS/AREG_IOS_utils/transformation.py:90-92`), mais l'appel est enfermé dans `if args.areg_mode == "Auto_IOS"` (`AREG_IOS/AREG_IOS.py:214`) : cette branche est du code mort et le mode « Registration » IOS ne fournit aucune matrice.

14. **Fichier écrit avec une extension mensongère (IOS).** `WriteSurf` écrit systématiquement du VTK legacy en conservant l'extension source (`AREG_IOS/AREG_IOS_utils/utils.py:166-168`) : une entrée `.stl` produit un `.stl` illisible par un lecteur STL.

15. **Landmarks CBCT chargés puis ignorés.** `AREG_CBCT.py` importe `LoadOnlyLandmarks`, `applyTransformLandmarks`, `WriteJson` (`AREG_CBCT/AREG_CBCT.py:28-36`) et `GetPatients` collecte la clé `lmT2` (`AREG_CBCT/AREG_CBCT_utils/utils.py:106-108`), mais aucune de ces fonctions n'est appelée : **les landmarks T2 ne sont jamais recalés ni écrits**. Le paramètre XML `reg_lm` correspondant est commenté (`AREG_CBCT/AREG_CBCT.xml:88-93`).

16. **Chaînage incohérent des dossiers en IOS/CBCT.** En `Semi_IOSCBCT`, ALI_IOS lit `Seg IOS/` (`AREG/AREG_Method/IOSCBCT.py:319`) tandis qu'AREG lit `Seg IOS/liste_csv_file_Seg/` (`:347`) ; en `Auto_IOSCBCT`, PRE_ASO_IOS lit `Seg IOS/` (`:707`) et AREG lit `PRE ASO IOS/` (`:807`). Le sous-dossier `liste_csv_file_Seg` est une convention implicite de CrownSegmentationcli, dépendante du nom du CSV généré.

17. **`suffix` obligatoire mais ignoré en IOS/CBCT.** Les trois `TestProcess` IOSCBCT refusent de démarrer sans suffixe (`AREG/AREG_Method/IOSCBCT.py:110-111`, `:187-188`, `:399-400`) alors que `add_in_namefile` n'est transmis à aucun paramètre du CLI `AREG_IOSCBCT` (`:346-352`, `:415-421`).

18. **`DisplayAREGIOSCBCT(0)` → division par zéro.** La classe est instanciée avec `nb_progress = 0` (`AREG/AREG_Method/IOSCBCT.py:362`, `:431`, `:822`) et `__call__` calcule `self.progress / self.nb_progress_total * 100` (`AREG/AREG_Method/Progress.py:190`). La classe est de plus **définie deux fois** dans le même fichier (`Progress.py:135` puis `:182`).

19. **`diccheckbox2` jamais rempli.** `setcheckbox2` n'est appelé nulle part ; `enableCheckbox` itère donc sur un dictionnaire vide (`AREG/AREG.py:1174-1183`) — et de toute façon `existsLandmark` retourne `None` dans toutes les implémentations (`AREG/AREG_Method/CBCT.py:248-249`, `IOS.py:444-445`, `IOSCBCT.py:166-167`), ce qui provoque un `return` anticipé (`AREG/AREG.py:1171-1172`). Aucune case n'est jamais pré-cochée automatiquement.

20. **`IOSCBCT.TestCheckbox` mort.** Il exige « au moins 3 landmarks » (`AREG/AREG_Method/IOSCBCT.py:77-82`) mais aucun `TestProcess` du mode IOS/CBCT ne l'appelle, et aucune case n'est créée pour ce mode (`initCheckBoxCBCT` n'est appelé que pour les 3 classes CBCT, `AREG/AREG.py:443-459`).

21. **`Semi_CBCT.TestReference` incohérent.** La fonction calcule `out` puis retourne inconditionnellement `None` (`AREG/AREG_Method/CBCT.py:60-71`), et appelle `self.NumberScan(ref_folder)` avec un seul argument alors que la signature en exige deux (`:51`).

22. **Visibilité contradictoire de `CbCBCTInputType`.** `SwitchModeCBCT(0)` la masque (`AREG/AREG.py:614-615`), puis la fin de `SwitchType` la ré-affiche pour tout mode CBCT d'index 0 (`:848-857`). Résultat net : DICOM n'est proposé qu'en mode « Orientation and Registration » — le seul mode où `TestScanDCM`/`NumberScanDCM` sont réellement implémentés (`AREG/AREG_Method/CBCT.py:602`, `:631`), les autres héritant de stubs qui retournent `None` (`AREG/AREG_Method/Method.py:228-251`).

23. **`DCMInput` transmis à `AREG_CBCT` sur des dossiers déjà convertis.** En `Or_Auto_CBCT`, `DCMInput` vaut `isDCMInput` alors que `t1_folder` est le dossier d'orientation contenant des NIfTI (`AREG/AREG_Method/CBCT.py:815-820`) : `convertdicom2nifti` y est relancé et crée un sous-dossier `NIFTI` vide.

24. **Prérequis CUDA non négociable en IOS.** `PredPatch` force `torch.device("cuda")` et `.cuda()` (`AREG_IOS/AREG_IOS_utils/PredPatch.py:31`, `:43-45`) : aucune bascule CPU, le mode IOS échoue sur machine sans GPU NVIDIA.

25. **Indices XML discontinus (`AREG_IOS.xml`).** Les indices déclarés sont 0, 1, 2, 3, 5, 6, 7 — l'index 4 manque (`AREG_IOS/AREG_IOS.xml:48`), alors que `argparse` attend 7 positionnels consécutifs (`AREG_IOS/AREG_IOS.py:308-314`). Les trois XML conservent par ailleurs les métadonnées du template (`FirstName LastName (Institution)`, `https://github.com/username/project`, description « This is a CLI module that can be bundled in an extension »).

26. **`.split(".")[0]` dans l'extraction d'identifiant CBCT** (`AREG_CBCT/AREG_CBCT_utils/utils.py:92`) : tout point dans un nom de patient tronque l'identifiant (`P.Dupont_T1.nii.gz` → `P`), et les patients ne différant qu'après le premier point fusionnent.

27. **README obsolète.** Il ne documente que les modes CBCT et IOS (`README.md:288-292`) et ignore complètement la famille **IOS to CBCT** ainsi que ses trois modes, ses landmarks et ses sorties.

---

## Modèles IA

| Nom (UI) | Champ | Contenu attendu | URL | Modes exigeant le modèle |
|---|---|---|---|---|
| Segmentation (AMASSS) | `lineEditModel1` (CBCT) | `AMASSS_Models/*.pth` | `https://github.com/DCBIA-OrthoLab/SlicerAutomatedDentalTools/releases/download/AMASSS_CBCT/AMASSS_Models.zip` | CBCT : Semi, Auto, Or_Auto (`AREG/AREG_Method/CBCT.py:121-124`, `:567-575`) |
| Orientation PreASO | `lineEditModel2` (CBCT) / `lineEditModel1` (IOSCBCT) | `PreASO/` | `https://github.com/lucanchling/ASO_CBCT/releases/download/v01_preASOmodels/PreASOModels.zip` | CBCT Or_Auto, IOSCBCT Auto (`AREG/AREG_Method/CBCT.py:571`, `IOSCBCT.py:482`) |
| Gold « Occlusal and Midsagittal Plane » | idem | scan + landmarks de référence | `…/v01_goldmodels/Occlusal_Midsagittal_Plane.zip` | idem (choix par pop-up radio, `AREG/AREG.py:1058-1067`) |
| Gold « Frankfurt Horizontal and Midsagittal Plane » | idem | idem | `…/v01_goldmodels/Frankfurt_Horizontal_Midsagittal_Plane.zip` | idem (défaut, `AREG/AREG.py:407`) |
| ALI_CBCT (7 ou 6 landmarks) | `lineEditModel3` (CBCT, caché) | un `.zip` par landmark (`Ba, S, N, RPo, LPo, ROr, LOr` ou `IF, ANS, PNS, UR1O, UR6O, UL6O`) | `https://github.com/lucanchling/ALI_CBCT/releases/download/models_v01/<LM>.zip` | CBCT Or_Auto (`AREG/AREG.py:1104-1140`, `AREG/AREG_Method/CBCT.py:126-130`) |
| ALI_CBCT dents (8 archives) | `lineEditModel2` (IOSCBCT) | `Cranial_Base`, `Lower_Bones_1/2`, `Lower_Left/Right_Teeth`, `Upper_Bones_v2`, `Upper_Left/Right_Teeth_v2` | `…/releases/download/v0.1-v2.0_models/*.zip` | IOSCBCT Auto + Semi (`AREG/AREG_Method/IOSCBCT.py:197-206`, `:487-496`) |
| ALI_IOS (ALIDDM) | `lineEditModel3` (IOSCBCT) | `Models.zip` | `https://github.com/baptistebaquero/ALIDDM/releases/download/v1.0.3/Models.zip` | IOSCBCT Auto + Semi (`AREG/AREG_Method/IOSCBCT.py:207`, `:497`) |
| Segmentation IOS | `lineEditModel1` (IOS) | un `.pth` | `https://github.com/HUTIN1/ASO/releases/download/v1.0.0/segmentation_model.zip` | IOS Auto — **validé mais inutilisé** (`AREG/AREG_Method/IOS.py:177`) |
| Référence d'orientation IOS (gold files) | `lineEditModel2` (IOS) / `model_folder_1/IOS` (IOSCBCT) | `.vtk` + `.json` | `https://github.com/HUTIN1/ASO/releases/download/v1.0.0/Gold_file.zip` | IOS Auto, IOSCBCT Auto (`AREG/AREG_Method/IOS.py:176`, `IOSCBCT.py:485`) |
| Recalage IOS (patch Butterfly, MONAI UNet) | `lineEditModel3` (IOS) | un `.ckpt` (`torch.load(...)["state_dict"]`) | `https://github.com/HUTIN1/AREG/releases/download/v1.0.0/AREG_model.zip` | **IOS Auto et Semi (obligatoire)** (`AREG/AREG_Method/IOS.py:175`, `AREG_IOS/AREG_IOS_utils/PredPatch.py:27-33`) |
| `dentalmodelseg` (CrownSegmentationcli) | résolu automatiquement | binaire de l'env conda `shapeaxi` ou `lib/Python/bin/dentalmodelseg` | modèle `"latest"` téléchargé par l'outil lui-même | IOS Auto, IOSCBCT Auto + Semi (`AREG/AREG_Method/IOS.py:299-300`, `:319`) |

**Aucun modèle IA n'est requis** pour les modes `Semi_IOS` hormis le `.ckpt` de recalage, et pour `Reg_IOSCBCT` : `getModelUrl()` y retourne `None` (`AREG/AREG_Method/IOSCBCT.py:407-408`), le recalage étant purement géométrique (landmarks + ICP).

Fichiers de test téléchargeables via `ButtonTestFiles` (`AREG/AREG.py:919-995`) : `SemiAuto.zip`, `FullyAuto.zip`, `Or_FullyAuto.zip`, `Or_FullyAuto_DCM.zip` (CBCT), `AREG_test_scans.zip` (IOS), `TestFile.zip` et `RegTestFiles.zip` (IOS/CBCT).

Environnement conda `shapeaxi` (python 3.9, `ocnn==2.2.1`, `shapeaxi==1.0.10`, + `pytorch3d`) requis pour IOS via SlicerConda/WSL (`AREG/AREG.py:2371-2373`, `:2395-2414`, `:2109-2214`).

---

## Avis — entrées/sorties à ajouter ou retirer

### À retirer / corriger en priorité

1. **Retirer ou implémenter `ApproxcheckBox`** : une option visible, cochée par défaut, qui ne change rien est le pire des deux mondes. Soit brancher `initial_transform` dans `ElastixReg`, soit supprimer la case, le paramètre XML et l'argument CLI.
2. **Retirer `LabelSelectcomboBox` / `SegmentationLabel`** ou brancher réellement `GetSegmentationLabel` sur le dossier de masques choisi. En l'état, trois couches (UI, module, CLI) transportent une valeur constante.
3. **Retirer l'exigence de `model_folder_1` en `Auto_IOS`** (modèle `.pth` jamais utilisé) ou le passer à CrownSegmentationcli à la place de `"model": "latest"`.
4. **Retirer l'exigence de suffixe en IOS/CBCT** ou, mieux, le transmettre au CLI `AREG_IOSCBCT` et l'insérer dans les noms `_Reg_U.vtk` / `_lm_Reg_U.mrk.json` — sinon deux exécutions successives écrasent silencieusement les sorties précédentes.
5. **Supprimer les imports morts de landmarks dans `AREG_CBCT.py`** ou, préférablement, réactiver la fonctionnalité (voir ci-dessous).

### À ajouter

6. **Sortie « matrices » pour `AREG_IOSCBCT`** : les matrices landmark et ICP sont calculées puis jetées. Écrire `<patient>_<Tx>_IOS2CBCT_U.tfm` / `_L.tfm` (matrice composée `mat_icp @ mat_landmark`) aligne ce mode sur AREG_CBCT et AREG_IOS, et permet de rejouer le recalage sur d'autres données du même patient (segmentations, landmarks supplémentaires).
7. **Sortie matrice en mode `Semi_IOS`** : la branche `else` de `saveMatrixAsTfm` existe déjà, il suffit de sortir l'appel du `if areg_mode == "Auto_IOS"`.
8. **Recalage des landmarks T2 en CBCT** : `applyTransformLandmarks` + `WriteJson` sont déjà écrits et `lmT2` déjà collecté ; produire `<patient>_<REG><suffix>_lm.mrk.json` est un gain fonctionnel quasi gratuit et attendu par les utilisateurs ASO/ALI.
9. **Entrée « dossier de landmarks T2 » explicite en CBCT** : aujourd'hui les `.json` doivent être mélangés aux scans T2 pour être détectés (`utils.py:106-108`), ce qui est fragile et non documenté dans l'UI.
10. **Un vrai rapport de sortie** (CSV/JSON) listant, par patient et par zone, le fichier produit, la métrique de recalage (RMSE ICP est déjà calculée en IOS/CBCT, `AREG_IOSCBCT/AREG_IOSCBCT.py:161`) et les patients échoués. Actuellement l'échec d'un patient n'est visible que dans la console Python.
11. **Option « dossier de travail temporaire »** : les dossiers `<T2>_Center`, `<T1>Or` et les masques AMASSS écrits dans le dossier T1 d'entrée devraient aller dans un temp dédié ou dans un sous-dossier du dossier de sortie. Écrire dans les données source est un piège majeur pour des données patient partagées.

### À homogénéiser

12. **Unifier les extensions acceptées** entre UI, module et CLI : élargir `AREG_IOSCBCT.getPatients` aux mêmes 6 extensions volumiques et aux 4 extensions de surface (SimpleITK et PyVista les lisent déjà), sinon restreindre l'UI et le README en conséquence.
13. **Unifier la récursivité** : `AREG_IOS.Sort` et `AREG_IOSCBCT.getPatients` devraient utiliser le même `search()` récursif que la partie CBCT, ou l'UI devrait avertir que seuls les fichiers à la racine seront traités.
14. **Unifier les règles de nommage patient** : trois algorithmes différents cohabitent (chaîne de `split` pour CBCT, égalité de basename pour IOS, regex + normalisation destructive pour IOS/CBCT). Une fonction commune, documentée dans l'UI (« nommage attendu : `<ID>_T1_<Upper|Lower>.<ext>` »), supprimerait la majorité des cas « 0 patient trouvé ».
15. **Ajouter une validation « à blanc » avant lancement** : lister à l'écran les paires T1/T2 effectivement appariées (et les fichiers orphelins) avant de démarrer une chaîne qui peut durer des heures ; `TestScan` ne remonte aujourd'hui qu'un compte global.
