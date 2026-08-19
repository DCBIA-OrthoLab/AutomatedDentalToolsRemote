# ASO (ASO_CBCT / ASO_IOS)

> Analyse basée sur la lecture du code réel (module `ASO/ASO.py`, lib `ASO/ASO_Method/`, CLI `ASO_CBCT/` et `ASO_IOS/` + leurs utils). Tous les chemins sont relatifs à la racine du dépôt `SlicerAutomatedDentalTools`.

## Rôle

ASO (Automatic Standardized Orientation) oriente des scans dentaires dans un référentiel standardisé, par recalage rigide (ICP) sur un cas de référence « gold ». Quatre variantes, sélectionnées par deux combobox (`CbInputType` × `CbModeType`, ASO.py:812-856) :

| Variante | Classe widget | Chaîne CLI lancée |
|---|---|---|
| Semi-CBCT | `Semi_CBCT` (ASO_Method/CBCT.py:296) | `SEMI_ASO_CBCT` seul (CBCT.py:388-412) |
| Fully-CBCT | `Auto_CBCT` (CBCT.py:415) | `PRE_ASO_CBCT` → `ALI_CBCT` → `SEMI_ASO_CBCT` (CBCT.py:486-574) |
| Semi-IOS | `Semi_IOS` (ASO_Method/IOS.py:500) | `SEMI_ASO_IOS` seul (IOS.py:594-628) |
| Fully-IOS | `Auto_IOS` (IOS.py:30) | `CrownSegmentationcli` (via conda/shapeaxi) → `PRE_ASO_IOS` (IOS.py:241-329) |

- **Semi** : l'utilisateur fournit scans **et** landmarks ; recalage landmark-based.
- **Fully** : landmarks (CBCT via ALI) ou segmentation dentaire (IOS via CrownSegmentation) sont produits automatiquement avant le recalage.
- CBCT : le recalage rééchantillonne l'image via SimpleITK (ASO_CBCT/ASO_CBCT_utils/utils.py:743-820, 835-860). IOS : transformation du maillage VTK (ASO_IOS/ASO_IOS_utils/transformation.py).
- Fully-IOS impose SlicerConda/WSL + env conda `shapeaxi` (ASO.py:1867-1972, 2439-2440).

## Entrées

### Widget Slicer (ASO.ui / ASO.py) - commun à tous les modes

| Entrée UI | Widget | Type | Sélection | Remarques |
|---|---|---|---|---|
| Type d'entrée | `CbInputType` (ASO.ui:217) | combo CBCT / IOS | - | pilote `SwitchType` (ASO.py:812) |
| Extension CBCT | `CbCBCTInputType` (ASO.ui:231) | combo « NIFTI, GIPL, NRRD » / « DICOM » | - | `isDCMInput` (ASO.py:775-779) ; forcé à False pour IOS (ASO.py:874-875) |
| Mode | `CbModeType` (ASO.ui:245) | combo Fully / Semi | - | |
| Scan / Landmark Folder | `lineEditScanLmPath` + `ButtonSearchScanLmFolder` | **dossier** | `QFileDialog.getExistingDirectory` **sans filtre d'extension** (ASO.py:944) | validé par `TestScan`/`TestScanDCM` |
| Reference Folder | `lineEditRefFolder` + `ButtonSearchReference` | **dossier** | popup radio : références pré-packagées téléchargées (zip) ou « Select your own folder » → `getExistingDirectory` (ASO.py:989-1016) | validé par `TestReference` |
| Model Folder Seg/Or | `lineEditModelSegOr` + `ButtonSearchModelSegOr` | dossier | **téléchargement automatique uniquement** depuis l'URL codée en dur (ASO.py:1042-1063) ; aucun QFileDialog | .ckpt (CBCT) / .pth unique (IOS) |
| Model Folder ALI | `lineEditModelAli` + `ButtonSearchModelAli` | dossier | popup checkbox des landmarks → télécharge `<LM>.zip` un par un (ASO.py:1065-1108) dans `...Downloads/ALI/ALI_CBCT` | CBCT Fully uniquement |
| Suffix | `lineEditAddName` (ASO.ui:525) | texte, défaut `Or` | - | injecté dans les noms de sortie |
| Output folder | `lineEditOutputPath` + `ButtonOutput` | dossier | `getExistingDirectory` (ASO.py:1110-1115) ; défaut auto = `<parent>/<nomDossierEntrée>Or` (ASO.py:985-987) | |
| Small FOV | `checkBoxSmallFOV` (ASO.ui:363) | case à cocher | - | **jamais visible** (voir Incohérences) |
| Dents / landmarks | cases générées dynamiquement (ASO.py:1469-1832) | - | - | Semi-CBCT : ≥ 3 landmarks (CBCT.py:82-87) ; IOS : 3-4 dents par mâchoire, 6-8 si deux mâchoires (IOS.py:125-142) |
| Occlusion | `checkBoxOcclusionAutoIOS`/`SemiIOS` (ASO.ui:406, 468) | case | - | IOS seulement : applique la matrice à la mâchoire opposée |
| Test Files | `ButtonTestFiles` (ASO.py:749) | - | télécharge scans + référence + modèles de test | URLs ci-dessous |

### Mode CBCT (Semi et Fully)

**Extensions scan réellement acceptées** : `[".nrrd", ".nrrd.gz", ".nii", ".nii.gz", ".gipl", ".gipl.gz"]` - testées par `str.endswith` sur un glob **récursif** `glob.iglob(path/**/*, recursive=True)` (CBCT.py:29-34 via `Method.search`, ASO/ASO_Method/Method.py:183-211 ; côté CLI : utils.py:996-1012 avec `ext in file`, et utils.py:1033-1036). Le `.gipl` nu n'est pas listé dans le README mais accepté par le code ; inversement `.nii` nu est accepté partout.

**Landmarks d'entrée (Semi)** : fichiers `.json` (markups Slicer, `markups[0].controlPoints`) - CBCT.py:312, utils.py:118-158.

**Appariement scan ↔ landmarks (règle de nommage)** : le « nom patient » est le basename tronqué aux séparateurs `_scan`, `_Scanreg`, `_Scan`, `_Or`, `_OR`, `_lm`, `_T1`, `_T2`, `.` côté widget (CBCT.py:41-52) ; côté CLI `GetPatients` **sans `_T1`/`_T2`** (utils.py:1020-1028). Ex. attendu : `P1_scan.nii.gz` + `P1_lm_*.json` (+ `P1_*.tfm`). Un `.json` multiple par patient est fusionné (voir MergeJson, sorties). `TestScan` (Semi) exige scan **et** au moins un json par patient (CBCT.py:309-333).

**⚠ Entrée cachée (Semi-CBCT)** : le CLI `SEMI_ASO_CBCT` exige aussi **un fichier `.tfm` par patient** (`data["tfm"]`, SEMI_ASO_CBCT.py:109 ; collecte utils.py:1042-1043). En Fully il est produit par `PRE_ASO_CBCT` ; en Semi autonome il doit être présent dans le dossier d'entrée (les Test Files SemiAuto.zip en contiennent), sinon le patient échoue par `KeyError`. `TestScan` ne le vérifie pas.

**Entrée DICOM (`isDCMInput=True`)** : le dossier d'entrée contient **un sous-dossier par patient** (nom du dossier = nom patient) ; comptage = sous-dossiers ≠ `NIFTI` (CBCT.py:285-293). Conversion en `.nii.gz` dans `<input>/NIFTI/` (utils.py:504-537). En Semi-DICOM, les json doivent matcher le nom du dossier patient (CBCT.py:335-362).

**Référence (gold)** : dossier contenant **exactement 1 scan** (mêmes extensions) + 1 json (CBCT.py:69-80 ; le CLI prend `scan_files[0]` / `json_files[0]`, utils.py:1009-1010). Références téléchargeables (CBCT.py:63-67) :
- Occlusal and Midsagittal Plane : `https://github.com/lucanchling/ASO_CBCT/releases/download/v01_goldmodels/Occlusal_Midsagittal_Plane.zip`
- Frankfurt Horizontal and Midsagittal Plane : `.../Frankfurt_Horizontal_Midsagittal_Plane.zip`

**Modèles IA (Fully-CBCT uniquement)** :
- « Orientation » PreASOModels (`.ckpt`, validation CBCT.py:91-95) : `https://github.com/lucanchling/ASO_CBCT/releases/download/v01_preASOmodels/PreASOModels.zip` (CBCT.py:127-131) - **en pratique inutilisé par le CLI actuel** (voir Incohérences).
- ALI (`.pth`, un modèle par landmark, nom `<LM>_Net*.pth`, CBCT.py:97-101 et 458-461) : base `https://github.com/lucanchling/ALI_CBCT/releases/download/models_v01/` + `<LM>.zip` (CBCT.py:133-137 ; ASO.py:1087-1094). Les cases landmarks ne sont activées que si le landmark est à la fois dans le gold **et** couvert par un `.pth` (CBCT.py:450-476).

**Fichiers de test** : SemiAuto.zip / SemiAuto_DCM.zip / FullyAuto.zip / FullyAuto_DCM.zip (CBCT.py:297-307, 416-438).

**Paramètres CLI** (positionnels, tous `string`) : `SEMI_ASO_CBCT(input, gold_folder, output_folder, add_inname, list_landmark)` (SEMI_ASO_CBCT.xml:20-53, .py:224-232) ; `PRE_ASO_CBCT(input, output_folder, model_folder, SmallFOV, temp_folder, DCMInput)` (PRE_ASO_CBCT.xml, .py:259-266).

### Mode IOS (Semi et Fully)

**Extensions maillage acceptées** : `[".vtk", ".vtp", ".stl", ".off", ".obj"]` (IOS.py:34 ; PRE_ASO_IOS.py:93 ; data_file.py:123), scan **récursif** (`search`, ASO_IOS_utils/utils.py:198-226). Lecteurs réels : vtkPolyDataReader/.vtp XML/.stl/OFFReader maison/.obj (utils.py:25-84).

**Convention Upper/Lower obligatoire dans les noms de fichiers** : un fichier est « Upper » si son basename contient `Upper` ou `_U_` (insensible à la casse), « Lower » si `Lower` ou `_L_` (utils.py:180-195 ; data_file.py:24-64 et 148-160). Un fichier sans marqueur lève `ValueError` (data_file.py:158-159).

**Appariement maillage ↔ json (Semi-IOS)** : nom patient = basename sans extension, sans le marqueur de mâchoire, sans `_out`/`Or` (data_file.py:125-146) ; un json est associé à un vtk si `vtk_name in json_name` **et** même mâchoire (data_file.py:276-291 ; version « semilink » pour l'occlusion : data_file.py:335-388, qui apparie en plus Upper et Lower du même patient). `TestScan` Semi-IOS exige autant de json que de maillages (IOS.py:507-518).

**Référence (gold) IOS** : dossier avec **2 json (Upper + Lower)** et, pour Fully, **2 maillages** (IOS.py:99-123 ; côté CLI : `glob(gold_folder + "/*json")` **non récursif**, SEMI_ASO_IOS.py:119, et 2 surfaces requises PRE_ASO_IOS.py:169-189). URL : `https://github.com/HUTIN1/ASO/releases/download/v1.0.0/Gold_file.zip` (IOS.py:156-159).

**Sélection UI Semi-IOS** : dents × landmarks (`O, MB, DB, CB, CL, OIP, R, RIP`, IOS.py:331-339) combinés en `UR6O,...` (IOS.py:582-584) et passés au CLI en `list_landmark` ; répartis Upper/Lower selon la 1re lettre (utils.py:272-284). **Fully-IOS** : seulement des dents (`list_teeth`), converties en numéros universels 1-32 (PRE_ASO_IOS.py:131-147) ; le recalage utilise le barycentre des dents via le tableau de points `Universal_ID` (PRE_ASO_IOS.py:289-290 ; pre_icp.py:103-198).

**Entrée Fully-IOS - segmentation** : les maillages possédant déjà un tableau `PredictedID` / `UniversalID` / `Universal_ID` court-circuitent la segmentation (copiés en `<nom>_Seg<ext>`, IOS.py:196-239 ; la détection ne lit que .vtk et .stl, IOS.py:219-225). Les autres sont convertis en `.vtk` si besoin (IOS.py:208-211, écriture toujours `.vtk` : ASO_Method/IOS_utils/Reader.py:122-132) puis passés à `CrownSegmentationcli` (liste des chemins écrite dans un CSV `liste_csv_file.csv`, IOS.py:473-497).

**Modèle IA (Fully-IOS)** : dossier devant contenir **exactement un** `.pth` (IOS.py:85-97) ; URL `https://github.com/HUTIN1/ASO/releases/download/v1.0.0/segmentation_model.zip` (IOS.py:150-155). Une URL de modèles ALI-IOS existe (`identification_landmark_ios_model.zip`, IOS.py:161-165) mais n'est jamais exploitée par le pipeline.

**Fichiers de test** : `Test_file_Full-IOS.zip` (IOS.py:144-148), `Test_file_Semi-IOS.zip` (IOS.py:501-505).

**Paramètres CLI** (positionnels) : `SEMI_ASO_IOS(input, gold_folder, output_folder, add_inname, list_landmark, occlusion, jaw, folder_error, log_path)` (SEMI_ASO_IOS.py:526-534) ; `PRE_ASO_IOS(input, gold_folder, output_folder, add_inname, list_teeth, occlusion, jaw, folder_error, log_path)` (PRE_ASO_IOS.py:545-553). `log_path` = fichier temporaire du widget (`<temp>/process.log`, ASO.py:667) utilisé pour la barre de progression.

## Sorties

### CBCT (Semi et Fully - le producteur final est toujours SEMI_ASO_CBCT)

| Fichier | Format | Nommage | Où | Réf. |
|---|---|---|---|---|
| Scan orienté | **toujours `.nii.gz`** quel que soit le format d'entrée | `{patient}_{suffix}.nii.gz` | sous-arborescence du dossier d'entrée **reproduite** dans le dossier de sortie (`input_file.replace(input_dir, out_dir)`) | SEMI_ASO_CBCT.py:152-163 |
| Landmarks orientés | markups `.mrk.json` (LPS) | `{patient}_lm_{suffix}.mrk.json` | idem | SEMI_ASO_CBCT.py:134-149 ; WriteJson utils.py:270-319 |
| Matrice de transformation | **`.tfm`** (CompositeTransform ITK, inclut la transformée d'entrée, inversée) | `{patient}_{suffix}_transform.tfm` | idem | SEMI_ASO_CBCT.py:168-179 ; construction utils.py:796-820 |

**Cardinalité CBCT : N patients → 3 fichiers par patient** (scan + json + tfm). Aucune sortie n'est écrasée : chaque écriture est gardée par `if not os.path.exists(...)` (SEMI_ASO_CBCT.py:144, 161, 174). Un patient dont l'ICP échoue (moins de 3 landmarks fiables restants, utils.py:754) ne produit **rien** et est seulement listé dans le log.

**Effet de bord sur le dossier d'ENTRÉE** : `MergeJson` fusionne tous les json d'un patient en `{patient}_lm_MERGED.mrk.json` **dans le dossier d'entrée** et **supprime les json originaux** (utils.py:65-115, appelé SEMI_ASO_CBCT.py:60-66). En DICOM, un dossier `NIFTI/` est créé dans le dossier d'entrée (utils.py:511-515).

**Intermédiaires Fully-CBCT** (dans des dossiers temporaires Slicer, CBCT.py:489-531) : scan recentré (même basename) + `.tfm` de translation par scan (PRE_ASO_CBCT.py:190-214), puis landmarks prédits par ALI_CBCT ; seuls les 3 fichiers finaux arrivent dans le dossier de sortie utilisateur.

### IOS - Semi (SEMI_ASO_IOS)

| Fichier | Format | Nommage | Réf. |
|---|---|---|---|
| Maillage orienté | `.vtk`/`.vtp`/`.obj` (extension d'origine ; **tout autre ext → `.vtk`**) | `{nom}{suffix}{ext}` - ex. `P1_Upper` + `Or` → `P1_UpperOr.vtk` | SEMI_ASO_IOS.py:385-387 ; WriteSurf utils.py:128-177 |
| Landmarks orientés | `.json` | `{nom_json_sans_ext}{suffix}.json` - ex. `P1_U_lm.mrk.json` → `P1_U_lm.mrk` + `Or` + `.json` = `P1_U_lm.mrkOr.json` | SEMI_ASO_IOS.py:358-364 ; utils.py:238-269 |
| Matrice | **`.npy`** (4×4 numpy) | `matrix_{nom_patient}.npy` | SEMI_ASO_IOS.py:406-411 |
| Erreurs | `.txt` | `{nom}Error.txt` dans `<output>/Error/` | utils.py:287-293 ; chemin IOS.py:598 |
| Log progression | texte | fichier `log_path` (temp) | SEMI_ASO_IOS.py:477-479 |

Sorties **à plat** dans le dossier de sortie (pas de reproduction d'arborescence). Cardinalité : sans occlusion, **par mâchoire** : 1 maillage + 1 json + 1 npy ; avec occlusion, **par patient** : 2 maillages + jusqu'à 2 json + 1 npy (la matrice calculée sur la mâchoire choisie est appliquée à l'autre, SEMI_ASO_IOS.py:422-474). ⚠ le nom de la matrice ne contient pas la mâchoire : Upper et Lower du même patient **écrasent le même `matrix_{nom}.npy`** hors occlusion.

### IOS - Fully (CrownSegmentationcli puis PRE_ASO_IOS)

| Fichier | Format | Nommage | Réf. |
|---|---|---|---|
| Maillage orienté | `.vtk` (les entrées du recalage sont les copies segmentées `_Seg`) | `{nom}_Seg{suffix}.vtk` (ex. `P1_Upper_SegOr.vtk`) | PRE_ASO_IOS.py:438-446 ; WriteSurf utils.py:128-177 |
| Matrice | **`.tfm`** (AffineTransform ITK, matrice **inversée** avant écriture) | `{id_patient}_SegOr.tfm` (suffixe `SegOr` **codé en dur**, ignore le suffixe UI) | PRE_ASO_IOS.py:414-421 ; saveMatrixAsTfm utils.py:300-312 |
| Erreurs / log | `.txt` / log | `<output>/Error/{nom}Error.txt` ; `log_path` | PRE_ASO_IOS.py:209-220 |

Cardinalité : sans occlusion, 1 maillage + 1 tfm par mâchoire ; avec occlusion, 2 maillages + 1 tfm par patient (pas de tfm pour la mâchoire liée, PRE_ASO_IOS.py:465-494). **Aucun landmark n'est produit en Fully-IOS.** ⚠ `PatientNumber` tronque à `_U`/`_L`/`.` (utils.py:295-297) : Upper et Lower du même patient donnent le même id → **collision du `.tfm`** hors occlusion. Intermédiaires : copies `_Seg` dans les dossiers temporaires `input_seg`/`seg` (IOS.py:244-257) + `liste_csv_file.csv` écrit **dans le dossier du module** (IOS.py:477-479).

## Comportement dossier vs fichier

- **Toutes** les entrées (scans, landmarks, référence, modèles, sortie) sont des **dossiers** ; aucun mode fichier-unique n'existe dans l'UI (`getExistingDirectory` partout : ASO.py:944, 1007, 1111).
- Les scans/landmarks/modèles sont découverts **récursivement** (`glob.iglob(.../**/*, recursive=True)` : Method.py:205-208, utils.py CBCT:1001-1007 et 1017-1018, utils.py IOS:217-226). Exception : les json du gold IOS côté CLI sont cherchés **au premier niveau seulement** (`glob(gold_folder + "/*json")`, SEMI_ASO_IOS.py:119) - une référence IOS avec les json dans un sous-dossier passe la validation widget (récursive, IOS.py:103) mais fait échouer le CLI.
- CBCT : l'arborescence relative de l'entrée est **reproduite** en sortie (SEMI_ASO_CBCT.py:137, 154). IOS : sortie **à plat**.
- DICOM (CBCT) : 1 patient = 1 sous-dossier ; conversion dans `<input>/NIFTI/` (utils.py:504-537).
- `Auto_IOS.Process` contient un embryon de gestion « fichier unique » (`os.path.isfile(path_input)`, IOS.py:266-268) mais il est inatteignable (path_input est un dossier créé juste avant) et bogué (`self.input` n'existe pas).

## Incohérences et pièges observés dans le code

1. **Le modèle « Orientation » CBCT (PreASOModels, .ckpt) est mort** : `PRE_ASO_CBCT.py` parse `model_folder`, `SmallFOV`, `temp_folder` (lignes 261-266) mais ne les utilise **jamais** - `main()` ne fait qu'un recentrage géométrique (PRE_ASO_CBCT.py:156-214). Le réseau DenseNet et `PreASOResample` existent (Net.py, ResamplePreASO.py) mais l'import est commenté (`ASO_CBCT_utils/__init__.py:12`) et jamais appelé. L'UI télécharge et valide pourtant ce modèle (ASO.py:1042-1063 ; CBCT.py:91-95).
2. **`checkBoxSmallFOV` toujours caché** : `SwitchMode` fait `setVisible(False)` dans les deux branches (ASO.py:793 et 797) → l'option « Use Small FOV scans » (ASO.ui:363-367) est inatteignable, et de toute façon sans effet (point 1).
3. **Semi-CBCT exige des `.tfm` non documentés/non validés** : `SEMI_ASO_CBCT` lit `data["tfm"]` (SEMI_ASO_CBCT.py:109) mais `TestScan` ne vérifie que scan+json (CBCT.py:309-333) → échec silencieux par patient si le dossier ne contient pas de tfm. Le fichier `ASO_CBCT/LinearTransform_t.tfm` livré dans le dépôt n'est référencé nulle part dans le code.
4. **Bug `.tfm` pour les entrées non-`.nii.gz` en Fully-CBCT** : `PRE_ASO_CBCT` nomme le tfm par `basename.replace(".nii.gz", ".tfm")` (PRE_ASO_CBCT.py:205) ; pour un `.nrrd`/`.gipl` le remplacement ne fait rien, le chemin cible = le scan déjà écrit → le tfm n'est jamais créé (garde `os.path.exists`) → `KeyError 'tfm'` dans SEMI_ASO_CBCT pour ces patients.
5. **Le CLI CBCT modifie le dossier d'ENTRÉE** : `MergeJson` fusionne puis **supprime** les json originaux de l'utilisateur (utils.py:111-115) - destructif et surprenant.
6. **Règles de nommage divergentes widget/CLI (CBCT)** : le widget tronque aussi `_T1`/`_T2` (CBCT.py:49-50), pas le CLI (utils.py:1020-1028) → comptage/appariement potentiellement différents.
7. **Jamais d'écrasement** : toutes les écritures CBCT sont sautées si le fichier existe (SEMI_ASO_CBCT.py:144, 161, 174 ; PRE_ASO_CBCT.py:193, 206) → relancer avec le même suffixe laisse des résultats périmés sans avertissement.
8. **Collisions de matrices IOS** : `matrix_{nom}.npy` (SEMI_ASO_IOS.py:409) et `{id}_SegOr.tfm` (PRE_ASO_IOS.py:418) ne distinguent pas Upper/Lower → écrasement mutuel hors occlusion. Le `.tfm` Fully-IOS ignore aussi le suffixe utilisateur (« SegOr » codé en dur).
9. **Formats de matrices hétérogènes** : `.tfm` ITK en CBCT et Fully-IOS, `.npy` numpy en Semi-IOS.
10. **Bug `Semi_IOS.TestReference`** : en cas d'erreur, `out.split(",")` est appelé sur une **liste** (IOS.py:531) → `AttributeError` au lieu du message ; un gold IOS avec ≠ 2 json plante la validation.
11. **Messages/validations approximatifs IOS** : « folder with one .pht file » (typo, IOS.py:88) ; `Semi_IOS.TestReference` ne vérifie pas les 2 maillages ni la présence Upper **et** Lower ; validation widget récursive vs glob CLI non récursif pour le gold (voir section précédente).
12. **Sorties annoncées vs réelles** : le scan CBCT sort toujours en `.nii.gz` même pour une entrée `.nrrd`/`.gipl` (SEMI_ASO_CBCT.py:159) ; le json IOS sort en `...mrk{suffix}.json` (double extension mal gérée, utils.py:252-254) au lieu de `..._{suffix}.mrk.json` comme en CBCT.
13. **Code mort / reliquats** : `path_preor` créé mais jamais utilisé (IOS.py:247-251) ; `self.input` inexistant (IOS.py:267) ; `getALIModelList` IOS jamais consommé (IOS.py:161-165) ; sentinelle `"Upper_nioegfjhdfjkdffdhjmndfhnmdfhj"` ajoutée à la liste des json (data_file.py:273) ; `PatientNumber` défini deux fois, la 2e écrase la 1re (utils.py:229-235 vs 295-297) ; `updateGUIFromParameterNode` référence `inputSelector`/`outputSelector`/`invertOutputCheckBox` absents de ASO.ui (ASO.py:2069-2081) - crash si jamais appelé (le nœud de paramètres n'est en fait jamais initialisé, ASO.py:2020-2025).
14. **README vs code** : le README pointe `input_test.zip` pour Semi-IOS alors que le code télécharge `Test_file_Semi-IOS.zip` (IOS.py:504) ; le tableau d'extensions CBCT du README omet `.gipl` et `.nii` nus acceptés par le code.
15. **`existsLandmark` Semi-CBCT ignore les landmarks d'entrée** : la disponibilité des cases est déduite du seul gold (CBCT.py:364-386, la comparaison avec les json d'entrée est commentée ligne 373) → on peut cocher un landmark absent des patients.

## Avis - entrées/sorties à ajouter ou retirer

**À retirer / nettoyer**
- Les paramètres morts `model_folder`, `SmallFOV`, `temp_folder` de `PRE_ASO_CBCT` (et le téléchargement PreASOModels côté UI), ou bien réactiver réellement le réseau d'orientation - l'état actuel fait télécharger ~un modèle inutile et affiche une option fantôme.
- La suppression des json d'entrée par `MergeJson` : écrire le MERGED dans un dossier temporaire, jamais dans l'entrée utilisateur.
- L'URL ALI-IOS inutilisée et le code mort listé au point 13.

**À ajouter côté entrées**
- Un vrai sélecteur « dossier modèle personnalisé » pour Seg/Or (le TODO existe, ASO.py:1006) au lieu du téléchargement forcé.
- Validation de la présence des `.tfm` en Semi-CBCT (ou mieux : rendre la transformée initiale optionnelle avec identité par défaut - le `LinearTransform_t.tfm` orphelin suggère que c'était l'intention).
- Vérification stricte du gold IOS (exactement 1 json Upper + 1 json Lower + 2 maillages, non récursif comme le CLI) et messages d'erreur corrigés.
- Support explicite d'un fichier unique en entrée (cas d'usage fréquent en clinique) - aujourd'hui tout est dossier.

**À ajouter/normaliser côté sorties**
- Unifier le format des transformations (toujours `.tfm` ITK, y compris en Semi-IOS à la place du `.npy`), inclure la mâchoire dans le nom (`{patient}_{jaw}_{suffix}.tfm`) et respecter le suffixe utilisateur en Fully-IOS.
- Conserver l'extension d'entrée pour le scan CBCT de sortie (ou documenter la conversion forcée en `.nii.gz`).
- Corriger le nommage des json IOS (`{patient}_lm_{suffix}.mrk.json`) pour l'aligner sur CBCT.
- Une option « overwrite » explicite (ou horodatage) au lieu du skip-si-existant silencieux, et un rapport de synthèse (CSV/JSON) listant patients traités/échoués - l'information existe déjà dans les CLI (structures `error_details`) mais n'est écrite nulle part en dehors du log console et des `Error/*.txt` IOS.
