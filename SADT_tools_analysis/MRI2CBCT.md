# MRI2CBCT

> Toutes les références `fichier:ligne` sont relatives à la racine du dépôt
> **SlicerAutomatedDentalTools** (dossiers `MRI2CBCT/` et `MRI2CBCT_CLI/`).

## Rôle

MRI2CBCT enchaîne les étapes nécessaires au **recalage rigide d'une IRM (ATM) sur un CBCT** :
réorientation/centrage de l'IRM, séparation gauche/droite, ré-échantillonnage, recadrage autour de l'ATM,
approximation (rapprochement grossier IRM↔CBCT) puis registration finale par Elastix.

Le module Slicer (`MRI2CBCT/MRI2CBCT.py`, 2387 lignes) ne fait **aucun calcul** : il collecte des paramètres,
valide sommairement les dossiers, puis lance séquentiellement des modules CLI via `slicer.cli.run`
(`MRI2CBCT/MRI2CBCT.py:1541-1545`, `1609-1613`, `1660-1664`, `1773-1777`, `1935-1939`, `2069-2073`).
Une seule exception : la **finalisation de l'approximation** est faite dans Slicer (module `FiducialRegistration`)
après la fin du CLI (`MRI2CBCT/MRI2CBCT.py:2163-2164` → `MRI2CBCT/MRI2CBCT_utils/Approx_MRI2CBCT.py:119-191`),
car le CLI tourne dans un sous-processus sans accès à l'API MRML.

Six CLI sont déclarés (`MRI2CBCT_CLI/CMakeLists.txt:2-7`) :
`MRI2CBCT_ORIENT_CENTER_MRI`, `MRI2CBCT_LR_CROP`, `MRI2CBCT_RESAMPLE_CBCT_MRI`, `MRI2CBCT_TMJ_CROP`,
`MRI2CBCT_APPROX`, `MRI2CBCT_REG`, tous appuyés sur la bibliothèque partagée `MRI2CBCT_CLI/MRI2CBCT_CLI_utils/`
(`MRI2CBCT_CLI/MRI2CBCT_CLI_utils/__init__.py:1-16`).

---

## Pipeline et étapes

L'UI est découpée en 4 sections repliables, **renommées à l'exécution** (`MRI2CBCT/MRI2CBCT.py:438-441`) :

| Section `.ui` | Titre affiché | Étapes contenues | CLI appelé |
|---|---|---|---|
| `resampleCollapsibleButton` | **Resample** | Ré-échantillonnage T1/T2 MRI + CBCT + Seg | `mri2cbct_resample_cbct_mri` |
| `inputsCollapsibleButton` | **Preprocess** | 1) Orientation + centrage MRI · 2) Cropping gauche/droite | `mri2cbct_orient_center_mri`, `mri2cbct_lr_crop` |
| `approxCollapsibleButton` | **Approximate** | 3) Approximation automatique (nnUNet condyle) · 3bis) Approximation **manuelle** injectée | `mri2cbct_approx` (+ code Slicer) |
| `outputCollapsibleButton` | **Registration** | 4) Crop ATM (TMJ) · 5) Registration finale | `mri2cbct_tmj_crop`, `mri2cbct_reg` |

L'ordre logique réel (d'après les noms de fichiers attendus en aval) est :
**Orientation MRI → L/R crop → Resample → Approximation → TMJ crop → Registration**,
alors que l'UI affiche « Resample » en premier et regroupe TMJ crop avec Registration.
Chaque étape est **indépendante** : il n'y a aucun chaînage automatique des dossiers de sortie vers l'étape suivante
(chaque `Process()` ne renvoie qu'**une** entrée de `list_Processes_Parameters`,
p. ex. `MRI2CBCT/MRI2CBCT_utils/Preprocess_MRI.py:76-95`).

### Étape 1 — Orientation + centrage MRI (`MRI2CBCT_ORIENT_CENTER_MRI`)

Widget `orientCenterMRI` (`MRI2CBCT/MRI2CBCT.py:1621-1671`) → `Process_MRI.Process`
(`MRI2CBCT/MRI2CBCT_utils/Preprocess_MRI.py:76-95`) → CLI
(`MRI2CBCT_CLI/MRI2CBCT_ORIENT_CENTER_MRI/MRI2CBCT_ORIENT_CENTER_MRI.py:79-112`).
Le CLI applique une nouvelle matrice de direction (`:61`), remplace éventuellement le spacing Z (`:65-67`)
et recalcule l'origine pour « centrer » le volume avec une permutation d'axes codée en dur pour l'IRM
(`:44-53`, `new_origin = [z/2, -x/2, y/2]`).

### Étape 2 — Cropping gauche/droite (`MRI2CBCT_LR_CROP`)

Widget `lrCropMRI2CBCT` (`MRI2CBCT/MRI2CBCT.py:1555-1619`) → `LR_CROP_MRI2CBCT.Process`
(`MRI2CBCT/MRI2CBCT_utils/LR_crop.py:85-104`) → CLI
(`MRI2CBCT_CLI/MRI2CBCT_LR_CROP/MRI2CBCT_LR_CROP.py:29-74`).
L'IRM est coupée **selon Z** (`MRI2CBCT_CLI/MRI2CBCT_CLI_utils/LR_crop.py:20-26`), le CBCT et la segmentation
**selon X** (`:44-50`), avec inversion des étiquettes L/R si la direction X est négative (`:52-56`).

### Étape 3 — Ré-échantillonnage (`MRI2CBCT_RESAMPLE_CBCT_MRI`)

Widget `resampleMRICBCT` (`MRI2CBCT/MRI2CBCT.py:1673-1784`) → `Preprocess_CBCT_MRI.Process`
(`MRI2CBCT/MRI2CBCT_utils/Preprocess_CBCT_MRI.py:102-126`) → CLI
(`MRI2CBCT_CLI/MRI2CBCT_RESAMPLE_CBCT_MRI/MRI2CBCT_RESAMPLE_CBCT_MRI.py:153-174`).
Le CLI construit d'abord un CSV d'inventaire (`MRI2CBCT_CLI/MRI2CBCT_CLI_utils/resample_create_csv.py:42-78`),
puis ré-échantillonne fichier par fichier (`MRI2CBCT_CLI/MRI2CBCT_CLI_utils/resample.py:29-123`) et **supprime le CSV**
(`MRI2CBCT_RESAMPLE_CBCT_MRI.py:122-133`).

### Étape 4 — Approximation

**Automatique** : `approximateMRI` (`MRI2CBCT/MRI2CBCT.py:1997-2080`) → `Approximation_MRI2CBCT.Process`
(`MRI2CBCT/MRI2CBCT_utils/Approx_MRI2CBCT.py:86-117`) → CLI
(`MRI2CBCT_CLI/MRI2CBCT_APPROX/MRI2CBCT_APPROX.py:38-57, 109-119`) →
`approximation()` (`MRI2CBCT_CLI/MRI2CBCT_CLI_utils/approximate.py:77-171`).
Le CLI segmente le condyle du **demi-CBCT** correspondant au côté de l'IRM avec nnUNet
(`MRI2CBCT_CLI/MRI2CBCT_CLI_utils/condyle_segmentation.py:110-141`), calcule un point CBCT (centroïde du masque),
un point IRM (centre de masse, `approx_utils.py:69-83`) et une rotation d'en-têtes (`approx_utils.py:38-66`),
puis écrit un JSON de points par patient (`approximate.py:150-162`).
La transformation finale est calculée **dans Slicer** par `finalizeApproximation`
(`MRI2CBCT/MRI2CBCT_utils/Approx_MRI2CBCT.py:119-191`) via `slicer.modules.fiducialregistration` (`:193-217`).

**Manuelle** : UI injectée dans la même section (`MRI2CBCT/MRI2CBCT.py:320` →
`MRI2CBCT/MRI2CBCT_utils/ManualApprox_MRI2CBCT.py:68-221`) : 6 sliders rotation/translation, poignées
interactives Slicer, bouton « Center MRI on CBCT », sauvegarde par `onConfirm` (`:436-488`).

### Étape 5 — Crop ATM (`MRI2CBCT_TMJ_CROP`)

Widget `tmjCropMRI2CBCT` (`MRI2CBCT/MRI2CBCT.py:1493-1553`) → `TMJ_CROP_MRI2CBCT.Process`
(`MRI2CBCT/MRI2CBCT_utils/TMJ_crop.py:105-130`) → CLI
(`MRI2CBCT_CLI/MRI2CBCT_TMJ_CROP/MRI2CBCT_TMJ_CROP.py:37-183`).
Même segmentation nnUNet que l'approximation (`condyle_segmentation.segment_condyle`), boîte englobante
**fixée à 400×400×400 voxels** centrée sur le centroïde du masque (`MRI2CBCT_TMJ_CROP.py:33-34, 96-107`),
puis rééchantillonnage du CBCT et de la segmentation sur la grille de l'IRM recadrée (`:134-149`).

### Étape 6 — Registration (`MRI2CBCT_REG`)

Widget `registration_MR2CBCT` (`MRI2CBCT/MRI2CBCT.py:1882-1946`) → `Registration_MRI2CBCT.Process`
(`MRI2CBCT/MRI2CBCT_utils/Reg_MRI2CBCT.py:108-129`) → CLI
(`MRI2CBCT_CLI/MRI2CBCT_REG/MRI2CBCT_REG.py:153-212`), en 6 sous-étapes :
1. inversion d'intensité de l'IRM (`mri_inverse.py:19-66`),
2. normalisation percentile de l'IRM (`normalize_percentile.py:57-87`),
3. masquage de l'IRM par la segmentation CBCT (`apply_mask.py:101-135`),
4. normalisation percentile du CBCT,
5. masquage du CBCT,
6. recalage rigide Elastix CBCT masqué ← IRM masquée (`AREG_MRI.py:113-241`).

---

## Entrées (par étape)

### Tableau de synthèse

| Étape | Champ UI | Type | Extensions **réellement** traitées | Récursif ? | Référence |
|---|---|---|---|---|---|
| Orientation | `LineEditMRI` | dossier (`getExistingDirectory`) | `.nii`, `.nii.gz` (CLI) — validation UI accepte aussi `.nrrd` | UI : oui ; CLI : oui (`os.walk`) | `MRI2CBCT.py:1266-1272`, `MRI2CBCT_ORIENT_CENTER_MRI.py:89-93`, `Preprocess_MRI.py:47` |
| Orientation | table `tableWidgetOrient` (3×3 + colonne « Negative ») | 9 entiers ∈ {-1,0,1} | — | — | `MRI2CBCT.py:451-480`, `845-862` |
| Orientation | `checkBoxBilateralMRI` + `AcquisitionSpacing` | booléen + float (mm) | — | — | `MRI2CBCT.py:1631-1634` |
| Orientation | `comboBoxDICOMVolumes` | nœud DICOM chargé | — | — | `MRI2CBCT.py:692-738` (**affichage seul**) |
| Orientation | `lineEditOutputOrientMRI` | dossier | — | — | `MRI2CBCT.py:1319-1321` |
| L/R crop | `lineEditSepCBCT`, `lineEditSepMRI`, `lineEditSepSeg` | dossiers (0 à 3 fournis) | `.nii`, `.nii.gz` | **non** (`glob` à plat) | `MRI2CBCT.py:1343-1353`, `MRI2CBCT_LR_CROP.py:33` |
| L/R crop | `lineEditSepOut` | dossier | — | — | `MRI2CBCT.py:1355-1357` |
| Resample | `lineEditResampleMRI` / `…T2MRI` / `…CBCT` / `…T2CBCT` / `…Seg` / `…T2Seg` | dossiers | `.nii`, `.nii.gz` | oui (`os.walk`) | `MRI2CBCT.py:1295-1317`, `resample_create_csv.py:62-65` |
| Resample | `tableWidgetResample` | 3 entiers (taille) + 3 flottants (spacing) + 2 cases « Keep » | — | — | `MRI2CBCT.py:518-616`, `643-675` |
| Resample | `checkBoxCenterImage` (coché par défaut) | booléen → `"True"`/`"False"` | — | — | `MRI2CBCT.py:1711`, `MRI2CBCT.ui:356-362` |
| Resample | `lineEditOuputResample` | dossier | — | — | `MRI2CBCT.py:1323-1325` |
| Approx | `lineEditApproxCBCT`, `lineEditApproxMRI` | dossier **ou** volume de la scène | `.nii`, `.nii.gz` (pas `.nrrd`) | oui (`os.walk`) | `MRI2CBCT.py:1331-1337`, `1948-1995`, `approximate.py:58-74`, `Approx_MRI2CBCT.py:55-63` |
| Approx | `lineEditOutputApprox` | dossier | — | — | `MRI2CBCT.py:1339-1341` |
| Approx | modèle nnUNet | téléchargé automatiquement | `.pth` + `dataset.json` + `plans.json` | — | `MRI2CBCT.py:1233-1260`, `2008-2011` |
| TMJ crop | `lineEditCropTMJCBCT`, `…MRI`, `…Seg` | dossiers (**3 obligatoires**) | `.nii.gz`, `.nii`, `.nrrd`, `.nrrd.gz`, `.gipl`, `.gipl.gz` (appariement) — mais lecture `nibabel` ⇒ NIfTI seulement | oui (`rglob`) | `MRI2CBCT.py:1359-1369`, `MRI2CBCT_CLI/MRI2CBCT_CLI_utils/TMJ_crop.py:58-83` |
| TMJ crop | `lineEditTMJModel` (+ bouton Download) | dossier modèle nnUNet | `fold_0/checkpoint_final.pth`, `dataset.json`, `plans.json` | — | `MRI2CBCT.py:1192-1203`, `TMJ_crop.py:62-74` |
| TMJ crop | `lineEditCropTMJOut` | dossier | — | — | `MRI2CBCT.py:1371-1373` |
| Registration | `lineEditRegMRI`, `lineEditRegCBCT`, `lineEditRegLabel` | dossiers | `.nii.gz` **quasi exclusivement** (voir ci-dessous) | UI : oui ; CLI : **non** | `MRI2CBCT.py:1274-1293`, `mri_inverse.py:34`, `normalize_percentile.py:73`, `AREG_MRI.py:131` |
| Registration | `tableWidgetNorm` (2×4) | 8 entiers | — | — | `MRI2CBCT.py:484-514`, `1134-1153` |
| Registration | `checkBoxTompraryFold` | booléen | — | — | `MRI2CBCT.py:1897`, `MRI2CBCT_REG.py:202` |
| Registration | `LineEditOutput` | dossier | — | — | `MRI2CBCT.py:1327-1329` |

### Détail par étape

#### Orientation + centrage MRI

- **Sélecteur fichier/dossier neutralisé.** Le `.ui` propose `ComboBoxMRI` avec `File`/`Folder`
  (`MRI2CBCT.ui:569-580`) et `openFinder` en tient compte (`MRI2CBCT.py:1266-1272`), mais le combo est
  **forcé à « Folder » puis désactivé et masqué** (`MRI2CBCT.py:405-406`, `433`). Le mode fichier unique est
  donc inaccessible — et de toute façon inopérant côté CLI (`os.walk` sur un fichier ne renvoie rien).
- **Validation UI vs CLI.** `Process_MRI.TestScan` accepte `.nii`, `.nii.gz`, `.nrrd`
  (`MRI2CBCT_utils/Preprocess_MRI.py:47`), avec un `glob.iglob(..., recursive=True)`
  (`MRI2CBCT_utils/Method.py:92-101`) ; le CLI ne traite que `.nii`/`.nii.gz`
  (`MRI2CBCT_ORIENT_CENTER_MRI.py:92`). Un dossier ne contenant que des `.nrrd` passe la validation et
  produit **zéro** sortie, sans message.
- **Direction.** Les 9 valeurs viennent des cases à cocher (`MRI2CBCT.py:845-862`) ; la valeur par défaut
  est `(0,0,-1, 1,0,0, 0,-1,0)` (`MRI2CBCT.py:880-884`). Transmise en liste, elle est sérialisée par
  `slicer.cli.setNodeParameters` en `"0, 0, -1, 1, 0, 0, 0, -1, 0"` puis re-parsée (`:80`).
- **Spacing Z.** Si « Bilateral MRI » est coché, la valeur de `AcquisitionSpacing` est envoyée ; sinon la
  chaîne littérale `"None"` (`MRI2CBCT.py:1631-1634`), testée telle quelle dans le CLI
  (`MRI2CBCT_ORIENT_CENTER_MRI.py:65`).
- **Aucun appariement IRM↔CBCT** à cette étape : chaque fichier est traité indépendamment.

#### Cropping gauche/droite

- Les trois dossiers sont **optionnels** : un champ vide devient la chaîne `"None"`
  (`MRI2CBCT.py:1565-1574`) et le CLI ne traite que les chemins qui sont des dossiers existants
  (`MRI2CBCT_LR_CROP.py:64-74`).
- **Scan non récursif** : `glob.glob(input_folder/*.nii)` + `*.nii.gz` (`MRI2CBCT_LR_CROP.py:33`), alors que
  la validation UI est récursive et accepte `.nrrd` (`MRI2CBCT_utils/LR_crop.py:51-57`).
- Aucun appariement entre modalités : chaque dossier est traité isolément.

#### Ré-échantillonnage

- Les 6 dossiers sont optionnels (`"None"` si vide, `MRI2CBCT.py:1683-1700`) ; les champs T2 ne sont pris en
  compte que si la case `CheckBoxT2*` correspondante est cochée (`MRI2CBCT.py:1691`, `1695`, `1699`).
- **Taille / spacing** : `get_resample_values` renvoie soit une liste de 3 valeurs, soit la chaîne `"None"`
  si la case « Keep … » est cochée (`MRI2CBCT.py:643-675`). Défauts : taille `443×443×119`, spacing
  `0.3×0.3×0.3` (`MRI2CBCT.py:539-571`).
- **La taille demandée n'est appliquée qu'à l'IRM** : CBCT et Seg reçoivent explicitement `"None"`
  (`MRI2CBCT_RESAMPLE_CBCT_MRI.py:164-172`), par choix documenté dans le code (`:159-163`).
- **Interpolation** : linéaire, sauf pour les segmentations (plus proche voisin, `:91`).
- **Miroir droite/gauche** : déclenché sur la présence de `left`/`right` **dans le chemin du fichier**
  (`:96-101`), et seulement si `isMRI and rightSide and not center`
  (`MRI2CBCT_CLI/MRI2CBCT_CLI_utils/resample.py:57-59`). Avec « Center image » coché par défaut, ce miroir
  n'est **jamais** appliqué.

#### Approximation

- **Deux modes d'entrée** : « Folder » ou « Scene Volume » (combo ajouté par code,
  `MRI2CBCT.py:1958-1962`). En mode scène, le chemin disque est extrait du `StorageNode`
  (`pathFromVolumeNode`, `MRI2CBCT.py:51-60`) ; un volume non sauvegardé est refusé (`:2029-2033`).
- **Appariement IRM↔CBCT** (`MRI2CBCT_CLI/MRI2CBCT_CLI_utils/approximate.py:58-74`) :
  1. l'identifiant patient est extrait du nom du CBCT : `split("CBCT")[0].rstrip("_")` si `CBCT` est présent,
     sinon premier token avant `_`/`.` (`:30-36`) ;
  2. l'IRM est cherchée récursivement avec `startswith(patient_id)` **et** `"MRI"`/`"MR"` dans le nom
     (`approx_utils.py:20-36`), puis, en repli, `startswith(patient_id)` seul (`approximate.py:51-54`).
- **Mode fichier unique** : si les deux chemins sont des fichiers, une seule paire est constituée ; si l'un
  est un fichier et l'autre un dossier → `ValueError` (`approximate.py:101-110`).
- Modèle nnUNet téléchargé automatiquement dans
  `Documents/<Slicer>Downloads/MRI2CBCT/MRI2CBCT_CBCT/ML/Dataset001_myseg/nnUNetTrainer__nnUNetResEncUNetXLPlans__3d_fullres/`
  (`MRI2CBCT.py:1233-1260`), `nnUNet_results` étant déduit de `model_folder.parent.parent`
  (`condyle_segmentation.py:49`).
- **Approximation manuelle** : les volumes viennent soit des sélecteurs de scène, soit du **premier** NIfTI
  trouvé à plat dans les dossiers Approx (`ManualApprox_MRI2CBCT.py:227-232`, `268-294`) — un seul patient à
  la fois.

#### Crop ATM

- **Appariement par identifiant** (`MRI2CBCT_CLI/MRI2CBCT_CLI_utils/TMJ_crop.py:58-83`) : l'ID est obtenu en
  tronquant le nom sur une longue liste de suffixes (`_Scan`, `_OR`, `_CB`, `_T1`, `_seg`, `_crop`, `_Left`,
  `_approximate`, `_CBCT`, `_MRI`, `_MR`, …) (`:21-56`). Les fichiers de segmentation **ne créent pas** de
  patient : ils ne sont rattachés qu'à un patient déjà vu côté CBCT ou IRM (`:70-82`).
- Un patient est ignoré si l'un des trois fichiers manque (`MRI2CBCT_TMJ_CROP.py:169-171`) et **re-skippé**
  s'il existe déjà `MRI/<pid>_MRI_TMJ_crop*.nii.gz` dans la sortie (`:173-176`).
- Extensions listées : `.nii.gz`, `.nii`, `.nrrd`, `.nrrd.gz`, `.gipl`, `.gipl.gz` (`TMJ_crop.py:59`) —
  mais la lecture se fait par `nibabel` (`MRI2CBCT_TMJ_CROP.py:69-70`) : un `.nrrd` sera apparié puis fera
  échouer le patient.

#### Registration

- Les trois combos `File`/`Folder` sont **forcés à « Folder », désactivés et masqués**
  (`MRI2CBCT.py:422-427`, `434-436`) : seul le mode dossier existe.
- **Extensions effectivement supportées** — la chaîne complète n'accepte en pratique que `.nii.gz` :
  - inversion IRM : `os.listdir` **non récursif**, `.nii` et `.nii.gz` (`mri_inverse.py:34-35`) ;
  - normalisation : **`.nii.gz` uniquement** (`normalize_percentile.py:73`) ⇒ une IRM `.nii` est inversée
    puis silencieusement abandonnée ;
  - masquage : récursif, `.nii`/`.nii.gz`, et le nom **doit contenir** `_CBCT` ou `_MR`
    (`apply_mask.py:113-121`) ;
  - recalage : `os.listdir(cbct_folder)` non récursif, fichiers `.nii.gz` contenant `_CBCT`
    (`AREG_MRI.py:131-134`) — sinon `ValueError`.
  La validation UI (`Reg_MRI2CBCT.TestScan`, `MRI2CBCT_utils/Reg_MRI2CBCT.py:46-52`) accepte pourtant
  `.nii`, `.nii.gz` et `.nrrd`, récursivement.
- **Convention de nommage obligatoire** (documentée dans les messages d'erreur, `AREG_MRI.py:145-149`) :
  - CBCT : `PATIENTID_CBCT.nii.gz` ou `PATIENTID_CBCT_*.nii.gz`
  - IRM : `PATIENTID_MR*.nii.gz` ou `PATIENTID_MRI*.nii.gz`
  - masque/segmentation : `PATIENTID_CBCT*.nii.gz`
  L'appariement est fait par préfixe `f"{patient_id}_{modality}"` avec exigence que le reste commence par
  `_` ou soit l'extension (`AREG_MRI.py:98-111`). La segmentation, elle, est retrouvée par un simple
  `startswith(patient_id)` (`apply_mask.py:83-98`) — premier fichier trouvé, ordre `os.listdir` non trié.
- **Normalisation** : table 2×4 (MRI puis CBCT ; min/max de normalisation, percentiles min/max)
  (`MRI2CBCT.py:484-514`). Deux presets : `Default 1` = `[[0,100,0,100],[0,75,10,95]]`, `Default 2` =
  `[[0,100,10,95],[0,100,10,95]]` (`MRI2CBCT.py:1166-1175`). Vérification min<max avant lancement
  (`Reg_MRI2CBCT.py:54-77`). Le CLI ré-extrait les 8 nombres par `re.findall(r'\d+', …)`
  (`MRI2CBCT_REG.py:127-144`) : toute valeur négative serait mal lue (le signe est ignoré), mais les
  `QSpinBox` sont bornés à ≥ 0.

---

## Sorties

### Tableau de synthèse

| Étape | Dossier écrit | Nommage | Cardinalité (N entrées) |
|---|---|---|---|
| Orientation | `<output>/` (à plat) | `<base>_OR.nii` ou `<base>_OR.nii.gz` | N fichiers → **N** |
| L/R crop | `<output>/CBCT/`, `<output>/MRI/`, `<output>/Seg/` | `<base>_cropLeft<ext>`, `<base>_cropRight<ext>` | N fichiers → **2N** par dossier fourni |
| Resample | `<output>/MRI/`, `<output>/CBCT/`, `<output>/Seg/` (à plat) | **nom d'origine conservé** | N fichiers → **N** (+ `resample_csv.csv` temporaire supprimé) |
| Approx (auto) | `<output>/first_approximation/points/` puis `<output>/first_approximation/` | `<pid>_approx_points.json`, `<mri_base>_approximate.nii.gz`, `<pid>_MRI_approximate.tfm` | 1 paire → **3** fichiers |
| Approx (manuel) | `<output>/first_approximation/` | `<mri_base>_approximate.nii.gz`, `<mri_base>_approximate.tfm` | 1 paire → **2** fichiers |
| TMJ crop | `<output>/Mask/`, `<output>/MRI/`, `<output>/CBCT/`, `<output>/CBCT seg/` | `<pid>_Mask_TMJ_<side>.nii.gz`, `<pid>_MRI_TMJ_crop<side>.nii.gz`, `<pid>_CBCT_TMJ_crop<side>.nii.gz`, `<pid>_Seg_TMJ_crop<side>.nii.gz`, `<pid>_Mask_TMJ_crop<side>.nii.gz` | 1 patient → **5** fichiers |
| Registration | 5 dossiers intermédiaires + 1 dossier final (voir ci-dessous) | `<mri_original>_reg.nii.gz`, `<mri_original>_reg_transform.tfm` | 1 patient → **2** fichiers finaux (+ 5 intermédiaires) |

### Détails

**Orientation** (`MRI2CBCT_ORIENT_CENTER_MRI.py:99-105`) : sortie **à plat**, l'arborescence d'entrée est
perdue ; deux fichiers homonymes dans deux sous-dossiers s'écrasent. L'extension de sortie suit celle
d'entrée (`extract_id` renvoie un drapeau `type_file`, `:23-42`). Si `output_folder` est vide, le CLI
écrirait dans le dossier d'entrée (`:82`) — cas empêché par la validation UI (`Preprocess_MRI.py:63-65`).

**L/R crop** (`MRI2CBCT_CLI/MRI2CBCT_CLI_utils/LR_crop.py:34-38`, `65-69`) : deux fichiers par entrée.
Attention, pour le CBCT les noms sont **volontairement croisés** (le ROI « left » est écrit sous
`_cropRight`), avec un `# TODO: Check why left is right` (`:64`). La segmentation passe par `crop_cbct`
(`MRI2CBCT_LR_CROP.py:72-74`), donc coupée selon X comme le CBCT.

**Resample** : le chemin de sortie est calculé par
`file_path.replace(os.path.dirname(file_path), output_resample)`
(`resample_create_csv.py:35`) : sortie **à plat** dans `<output>/MRI|CBCT|Seg`, nom inchangé.
Conséquences : (a) les T2 sont écrits dans **le même** sous-dossier que les T1 et les écrasent si les noms
sont identiques (`MRI2CBCT_RESAMPLE_CBCT_MRI.py:154-157`) ; (b) aucun suffixe ne permet de distinguer un
volume ré-échantillonné d'un original. L'écriture est compressée (`resample.py:236`).

**Approximation automatique** : le CLI n'écrit **que** les JSON de points
(`approximate.py:159-161`). Le volume approximé et la transformation ne sont écrits qu'ensuite, par
`finalizeApproximation` (`Approx_MRI2CBCT.py:174-178`), avec **deux conventions de nommage différentes** :
le volume utilise le nom de base de l'IRM, la transformation utilise l'ID patient. En mode « Scene Volume »,
le volume approximé reste chargé dans la scène (`Approx_MRI2CBCT.py:180-182`).
Les dossiers `mean_registration` et `cropped_cbct` prévus par `run_script_get_transformation`
(`MRI2CBCT_APPROX.py:59-75`) et `run_script_crop_volumes` (`:90-107`) ne sont **jamais** créés :
ces fonctions ne sont pas appelées par `main()` (`:109-119`).

**Approximation manuelle** (`ManualApprox_MRI2CBCT.py:461-478`) : volume `.nii.gz` + transformation `.tfm`
convertie RAS→LPS, dans le même `first_approximation/`. Comme le CLI, elle n'écrit qu'un patient par clic.

**TMJ crop** (`MRI2CBCT_TMJ_CROP.py:53-59`, `84`, `128`, `138`, `142`, `147`) : les sous-dossiers sont créés à
la demande, dont un dossier **contenant un espace** : `CBCT seg`. Le masque est écrit deux fois (grille
demi-CBCT et grille IRM recadrée). Si le masque est vide, seul `Mask/` est écrit puis le patient est
abandonné (`:88-90`) ; si l'intersection de la boîte avec le volume est nulle, rien n'est écrit pour ce
volume (`:53-55`).

**Registration** (`MRI2CBCT_REG.py:38-125`) — arborescence produite sous `folder_general` :

```
a01_MRI_inv/                                    <base>_inv.nii(.gz)
a2_MRI_inv_norm/percentile=[l,u]_norm=[m,M]/    <base>_inv_percentile=[...]_norm=[...].nii.gz
a3_MRI_inv_norm_mask/percentile=[...]/          <base>..._mask.nii.gz      (Int16)
b2_CBCT_norm/percentile=[...]/                  <base>_percentile=[...].nii.gz
b3_CBCT_norm_mask_l2/percentile=[...]/          <base>..._mask.nii.gz      (Int16)
mri=inv+norm[m,M]+p[l,u]_cbct=norm[m,M]+p[l,u]+mask/
        <nom_IRM_original>_reg.nii.gz
        <nom_IRM_original>_reg_transform.tfm
```

Les 5 dossiers intermédiaires (et leurs parents) sont supprimés si « Keep the temporary folder » est
décoché (`MRI2CBCT_REG.py:202-211`). Le nom du dossier final encode les paramètres de normalisation
(`:122`), ce qui permet de comparer plusieurs réglages sans écrasement.
Le volume recalé est produit par ré-échantillonnage de l'IRM **originale** sur sa propre géométrie
(`AREG_MRI.py:231-240`) : la sortie a donc la taille/l'origine de l'IRM d'entrée, pas celles du CBCT.

---

## Comportement dossier vs fichier

| Étape | Fichier unique possible ? | Récursivité réelle |
|---|---|---|
| Orientation | Non (combo File masqué, `MRI2CBCT.py:405-406`, `433`) | **Oui** (`os.walk`, `MRI2CBCT_ORIENT_CENTER_MRI.py:90`) |
| L/R crop | Non | **Non** (`glob` à plat, `MRI2CBCT_LR_CROP.py:33`) — divergence avec la validation UI récursive |
| Resample | Non | **Oui** (`os.walk`, `resample_create_csv.py:62`) mais sortie aplatie |
| Approx (auto) | **Oui** — chemin de fichier accepté des deux côtés (`approximate.py:101-110`), et mode « Scene Volume » (`MRI2CBCT.py:2013-2033`) | Oui (`os.walk`) |
| Approx (manuel) | Oui de fait (1er NIfTI du dossier ou nœud de la scène) | **Non** (`glob` à plat, `ManualApprox_MRI2CBCT.py:229`) |
| TMJ crop | Non | **Oui** (`Path.rglob`, `MRI2CBCT_CLI/MRI2CBCT_CLI_utils/TMJ_crop.py:19`) |
| Registration | Non (combos masqués, `MRI2CBCT.py:434-436`) | **Non** pour l'IRM (`mri_inverse.py:34`), le CBCT (`normalize_percentile.py:72`) et le listing CBCT (`AREG_MRI.py:131`) ; **oui** pour le masquage (`apply_mask.py:113`) et la recherche par patient (`AREG_MRI.py:104`) |

Toutes les validations UI passent par `Method.search`, qui est **toujours récursif**
(`MRI2CBCT/MRI2CBCT_utils/Method.py:92-101`) : l'UI valide donc des arborescences que la moitié des CLI
n'explorent pas.

---

## Incohérences et pièges observés dans le code

### Validations UI qui ne valident rien

1. **`TestProcess` inopérant pour les dossiers optionnels.** Resample et L/R crop remplacent les champs
   vides par la chaîne `"None"` **avant** l'appel (`MRI2CBCT.py:1683-1700`, `1565-1574`), alors que
   `TestProcess` teste `== ""` (`Preprocess_CBCT_MRI.py:61-83`, `MRI2CBCT_utils/LR_crop.py:64-78`).
   Ces messages d'erreur (« Please select an input folder for T2 MRI scans », …) sont donc **du code mort** :
   on peut lancer un Resample sans aucune entrée, seul `output_folder` vide bloque réellement.
2. **Extensions annoncées ≠ extensions traitées.** `.nrrd` est accepté par toutes les fonctions `TestScan`
   (`Preprocess_MRI.py:47`, `Preprocess_CBCT_MRI.py:47`, `Reg_MRI2CBCT.py:47`, `MRI2CBCT_utils/LR_crop.py:51`,
   `MRI2CBCT_utils/TMJ_crop.py:53`) mais **aucun CLI ne le traite**. Idem pour `.nii` en registration
   (abandonné par `normalize_percentile.py:73`) et pour `.gipl`/`.nrrd` dans l'appariement TMJ
   (`MRI2CBCT_CLI/MRI2CBCT_CLI_utils/TMJ_crop.py:59`, alors que la lecture est faite par nibabel).
3. **Vérification récursive / traitement non récursif** : voir tableau ci-dessus (L/R crop, registration).

### Options de l'UI sans effet

4. **`LineEditSuffix` (« Suffix », défaut `_reg`)** existe dans le `.ui` (`MRI2CBCT.ui:1350`) mais **n'est lu
   nulle part** : aucune occurrence dans le code Python. Le suffixe `_reg` est codé en dur dans
   `AREG_MRI.py:226-227`.
5. **`comboBoxDICOMVolumes`** ne fait que renseigner un label d'information
   (`MRI2CBCT.py:709-738`) : la valeur de spacing lue dans les tags DICOM (0018,0088 / 0018,0050) n'est
   **jamais** reportée automatiquement dans `AcquisitionSpacing`, il faut la ressaisir à la main.
6. **Sélecteurs `File`/`Folder`** (`ComboBoxMRI`, `comboBoxRegMRI`, `comboBoxRegCBCT`, `comboBoxRegLabel`) :
   la logique existe dans `openFinder` mais les combos sont forcés, désactivés et masqués
   (`MRI2CBCT.py:405-406`, `422-427`, `433-436`).
7. **`iso_spacing`** : `resample_fn` teste `if(iso_spacing=="True")` (`resample.py:78`) alors que la valeur
   passée est toujours le booléen `False` (`MRI2CBCT_RESAMPLE_CBCT_MRI.py:104-113`) — branche morte.
   Le paramètre nommé `iso_spacing` de `main()` sert en réalité de drapeau « c'est une IRM »
   (`:94`, `isMRI = 1 if iso_spacing else 0`).
8. **Miroir droite/gauche** (`resample.py:57-59`, `119-121`) conditionné à `not center` alors que
   `checkBoxCenterImage` est **coché par défaut** (`MRI2CBCT.ui:356-362`) : en usage normal ce traitement
   n'est jamais exécuté.

### Sorties jamais écrites / code mort

9. **`run_script_get_transformation` et `run_script_crop_volumes`** ne sont jamais appelés
   (`MRI2CBCT_APPROX.py:109-119`) : les dossiers `mean_registration` et `cropped_cbct` n'existent pas.
   Les paramètres `mean_folder` et `ROI_file` sont d'ailleurs commentés dans le XML
   (`MRI2CBCT_APPROX.xml:32-44`).
10. **`crop_volume`** (`crop_approximation.py:290-347`) attend des noms `*_MR_registered.nii.gz` (`:308`) et
    `<pid>_CBCT_Crop.nii.gz` (`:310`), conventions qui n'existent nulle part ailleurs dans le module
    (l'approximation écrit `*_approximate.nii.gz`).
11. **`transform_size`** (`MRI2CBCT_RESAMPLE_CBCT_MRI.py:63-76`) n'est jamais appelée.
12. Le `.ui` déclare `Output` / `Inputs` / `Approximation` comme titres, tous réécrits au démarrage
    (`MRI2CBCT.py:438-441`), et le README décrit une étape « **Orient and Center CBCT** » avec téléchargement
    de modèles (`README.md:532-535`) qui **n'existe pas** dans l'UI actuelle.

### Bugs latents

13. **`NameError` possible en Resample** : si un dossier T2 est renseigné sans son T1
    (`mri_output_folder`, `cbct_output_folder`, `seg_output_folder` ne sont définis que dans la branche T1),
    le CLI plante (`MRI2CBCT_RESAMPLE_CBCT_MRI.py:153-173`).
14. **`resample.py:175` et `:201`** utilisent `args.ow` alors que `args` est un **dictionnaire**
    (`AttributeError`) ; ces branches (`--dir`, `--csv`) ne sont pas empruntées par le module, mais le sont
    par un appel en ligne de commande.
15. **`resample.py:240`** : `logger.warning(e, file=sys.stderr)` — `file` n'est pas un argument valide de
    `logging` ⇒ le gestionnaire d'exception lève lui-même une `TypeError`.
16. **`apply_mask.py:38`** : `logger.warning("failed process on : ", fixed_image_sitk)` — même famille
    d'erreur (argument de formatage manquant).
17. **Approximation manuelle depuis la scène** : `onConfirm` utilise `self._mri_path`, laissé à `None` quand
    le volume vient d'un sélecteur de scène (`ManualApprox_MRI2CBCT.py:247`) ⇒ `os.path.basename(None)`
    lève une exception, capturée et affichée comme « Error: … » (`:461-462`, `:485-487`).
18. **Nom de package erroné** : `install_function` cherche/installe `nnunet_version==2.8.0`
    (`MRI2CBCT.py:94`), qui n'est pas le nom PyPI de nnUNet v2 (`nnunetv2`) — la vérification échoue
    systématiquement et l'installation proposée échouera. Le CLI TMJ importe pourtant
    `nnunetv2.inference.predict_from_raw_data` (`MRI2CBCT_TMJ_CROP.py:5`), import **inutilisé** au demeurant
    (la prédiction passe par le sous-processus `nnUNetv2_predict`, `condyle_segmentation.py:57-71`).
19. **Boîte TMJ figée** : `FIXED_BBOX_VOXELS = [400, 400, 400]` en dur (`MRI2CBCT_TMJ_CROP.py:34`), non
    exposé dans l'UI, et exprimé en **voxels** du demi-CBCT (donc dépendant du spacing du CBCT).
20. **`find_segmentation_file`** retourne le **premier** fichier dont le nom commence par l'ID patient
    (`apply_mask.py:94-96`) : avec des IDs préfixes l'un de l'autre (`B01` / `B010`), le mauvais masque peut
    être utilisé sans avertissement.
21. **Collisions de noms** : orientation et resample écrivent à plat ; deux patients homonymes dans des
    sous-dossiers différents s'écrasent silencieusement.
22. **f-strings avec guillemets imbriqués identiques** (`MRI2CBCT.py:1538-1539`, `1606-1607`, `1657-1658`,
    `1770-1771`, `1932-1933`, `2066-2067`, `resample.py:233`) : syntaxe valide uniquement à partir de
    Python 3.12 — le module ne se charge pas sur un Slicer basé sur Python ≤ 3.11.
23. **Barre de progression** : l'UI affiche « Progress bar is currently not working for this module » pour le
    crop TMJ (`MRI2CBCT.py:1547`), et le CLI TMJ n'émet effectivement aucun `<filter-progress>`.

---

## Avis — entrées/sorties à ajouter ou retirer

### À ajouter

- **Suffixe de sortie effectif** pour Resample et Orientation (et brancher `LineEditSuffix` déjà présent) :
  aujourd'hui un fichier ré-échantillonné est indiscernable de l'original, ce qui rend le pipeline
  difficile à rejouer et favorise les écrasements T1/T2.
- **Sous-dossiers T1/T2 distincts** en sortie de Resample (`<output>/MRI/T1`, `<output>/MRI/T2`) au lieu du
  dossier unique actuel (`MRI2CBCT_RESAMPLE_CBCT_MRI.py:154-157`).
- **Préservation de l'arborescence d'entrée** (ou au minimum détection des collisions de basenames) pour
  Orientation et Resample.
- **Exposer la taille de boîte TMJ** (`FIXED_BBOX_VOXELS`) et la **marge** (`MARGIN`) dans l'UI, en mm plutôt
  qu'en voxels.
- **Entrée « côté » explicite (Left/Right)** pour le Resample, au lieu de la détection par sous-chaîne
  `left`/`right` dans le chemin (`MRI2CBCT_RESAMPLE_CBCT_MRI.py:96-101`).
- **Report automatique du spacing DICOM** du `comboBoxDICOMVolumes` vers `AcquisitionSpacing`.
- **Sortie « rapport »** (CSV/JSON) par étape : patients traités, patients ignorés et motif. Actuellement les
  patients sans correspondance sont seulement `logger.warning` (`approximate.py:71`,
  `MRI2CBCT_TMJ_CROP.py:170`, `apply_mask.py:118-121`) et invisibles depuis l'UI.
- **Support `.nrrd` réel** (ou refus explicite dès l'UI) : c'est le format natif de Slicer et il est annoncé
  par toutes les validations.
- **Mode fichier unique** pour Orientation et Registration : la mécanique existe déjà (combos `File`/`Folder`,
  `pathFromVolumeNode`) et n'attend qu'à être réactivée.

### À retirer / nettoyer

- `crop_approximation.get_transformation` et `crop_volume`, `MRI2CBCT_APPROX.run_script_get_transformation` /
  `run_script_crop_volumes`, `transform_size` : code mort qui laisse croire à des sorties (`mean_registration`,
  `cropped_cbct`) inexistantes. La dépendance `torchreg`/`sklearn` qu'il traîne
  (`crop_approximation.py:8-9`) peut alors disparaître de `install_function`.
- Les blocs `if kwargs[...] == ""` de `Preprocess_CBCT_MRI.TestProcess` et `LR_crop.TestProcess`, ou mieux :
  les corriger pour tester `"None"` et vérifier qu'**au moins une** entrée est fournie.
- Les combos `File`/`Folder` masqués (`ComboBoxMRI`, `comboBoxReg*`) : soit les réactiver, soit les supprimer
  du `.ui`.
- L'import inutilisé `predict_entry_point` (`MRI2CBCT_TMJ_CROP.py:5`) et la dépendance `nnunet_version`
  (`MRI2CBCT.py:94`), à remplacer par `nnunetv2`.
- Le double `logger.warning(..., file=…)` / message mal formaté (`resample.py:240`, `apply_mask.py:38`).
- L'inversion volontaire des étiquettes L/R du CBCT (`MRI2CBCT_CLI/MRI2CBCT_CLI_utils/LR_crop.py:64-66`) :
  à trancher et documenter, car elle contredit le comportement de `crop_mri` et le `# TODO` laissé en place.
