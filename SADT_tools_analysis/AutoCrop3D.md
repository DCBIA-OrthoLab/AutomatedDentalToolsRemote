# AutoCrop3D

Analyse basée sur la lecture du code réel (branche `main`). Fichiers analysés :
- `AutoCrop3D/Crop_Volumes_UI/AutoCrop3D.py` (module Slicer scripté : widget + logique)
- `AutoCrop3D/Crop_Volumes_UI/Resources/UI/AutoCrop3D.ui` (interface Qt)
- `AutoCrop3D/Crop_Volumes_CLI/AutoCrop3D_CLI.py` + `AutoCrop3D_CLI.xml` (CLI Slicer)
- `AutoCrop3D/Crop_Volumes_CLI/Crop_Volumes_utils/FilesType.py`, `GenerateVTKfromSeg.py`, `CropCBCT.py` (utilitaires)

## Rôle

AutoCrop3D recadre (crop) en **batch** des volumes 3D (scans CBCT ou segmentations, formats NIfTI/NRRD/GIPL) selon une **région d'intérêt (ROI)** définie par un fichier markups Slicer `.mrk.json` (centre + taille de la boîte, lues dans `markups[0].center` et `markups[0].size` — `AutoCrop3D_CLI.py:70-72`). Deux moteurs de crop :

1. **Chemin CLI (par défaut)** : crop "axis-aligned" en coordonnées physiques via SimpleITK (`AutoCrop3D_CLI.py:74-105`), exécuté comme CLI Slicer (`AutoCrop3D.py:1059-1060`).
2. **Chemin "Crop Volume"** (case *Use module "Crop Volume" for tilted images*, `AutoCrop3D.ui:251-255`) : utilise la logique du module Slicer Crop Volume, exécuté **dans le processus Slicer** (`AutoCrop3D.py:915-998`), adapté aux images inclinées (direction non identité).

## Entrées

| Entrée | Widget / paramètre CLI | Type | Extensions acceptées | Fichier ou dossier | Scan récursif |
|---|---|---|---|---|---|
| Scans à cropper | `editPathF` / `scan_files_path` | fichier **ou** dossier de volumes | Validation UI : `.nii.gz`, `.nrrd.gz`, `.gipl.gz` (`AutoCrop3D.py:808`). Traitement réel : `.nii.gz`, `.nii`, `.nrrd.gz`, `.nrrd`, `.gipl.gz`, `.gipl` (`AutoCrop3D_CLI.py:48`, `AutoCrop3D.py:917`) | les deux (combo `chooseType` File/Folder, `AutoCrop3D.ui:176-187`) | Oui — `glob.iglob(path/**/*, recursive=True)` + `endswith` (`FilesType.py:41-46`, `AutoCrop3D.py:770-773`) |
| ROI | `editPathVolume` / `path_ROI_file` | fichier **ou** dossier de markups ROI | `.mrk.json` uniquement (`AutoCrop3D.py:807`, `AutoCrop3D_CLI.py:51`) | les deux (combo `chooseType_ROI`, `AutoCrop3D.ui:218-232`) | Oui (même fonction `Search`) |
| Dossier de sortie | `editPathOutput` / `output_path` | dossier | — | dossier uniquement (`AutoCrop3D.py:722-726`) | — |
| Suffixe | `editSuffix` / `suffix` | chaîne | — (défaut `"cropped"`, `AutoCrop3D.ui:308-312`) | — | — |
| Keep the same size as input | `checkBoxSize` / `box_Size` (string `'True'`/`'False'`, `AutoCrop3D.py:541`) | booléen | — | — | — |
| Use module "Crop Volume" | `checkBoxCV` | booléen (UI seulement, ne passe pas au CLI) | — | — | — |

Détails importants :

- **Définition de la ROI** : ce n'est **ni** un nœud MRML sélectionné dans la scène, **ni** une taille fixe — c'est un **fichier markups ROI Slicer** (`.mrk.json`). Le CLI lit `json['markups'][0]['center']` et `['size']` et calcule `Lower/Upper = centre ∓ taille/2` en coordonnées physiques, converties en indices via `TransformPhysicalPointToContinuousIndex` (`AutoCrop3D_CLI.py:70-78`). L'orientation de la ROI (`orientation` du .mrk.json) est **ignorée** dans le chemin CLI — d'où l'option "Crop Volume" pour les images inclinées, qui charge la ROI comme nœud markups (`slicer.util.loadMarkups`, `AutoCrop3D.py:953`) et laisse `slicer.modules.cropvolume.logic()` faire le crop (`AutoCrop3D.py:961-970`).
- **Mode ROI-dossier (appariement par patient)** : si la ROI est un dossier, chaque scan est apparié à "sa" ROI. Clé côté ROI : `basename.split('_')[0]` (`FilesType.py:78`, `AutoCrop3D.py:881`). Clé côté scan : basename découpé sur une longue liste de suffixes `_Scan`, `_scan`, `_Seg`, `_seg`, `_Or`, `_OR`, `_MAND`, `_MD`, `_MAX`, `_MX`, `_CB`, `_lm`, `_T2`, `_T1`, `_Cl` puis `'.'` (`AutoCrop3D_CLI.py:59`, `AutoCrop3D.py:927`). Scan sans ROI correspondante → warning et fichier **sauté** (`AutoCrop3D_CLI.py:64-68`, `AutoCrop3D.py:931-949`).
- Le bouton *Run* est désactivé au démarrage (`AutoCrop3D.ui:369-371`) et n'est réactivé **que** par un clic sur un bouton *Select* (`AutoCrop3D.py:696`) — taper les chemins à la main ne suffit pas.
- Paramètre CLI supplémentaire non exposé à l'utilisateur : `logPath` (fichier tampon pour la barre de progression, `AutoCrop3D.py:188`, `AutoCrop3D_CLI.xml:54-59`).

## Sorties

| Sortie | Format | Nommage | Condition | Cardinalité |
|---|---|---|---|---|
| Volume croppé (chemin CLI) | même extension que l'entrée (clé `Search` : `.nii.gz`, `.nii`, `.nrrd.gz`, `.nrrd`, `.gipl.gz`, `.gipl`) | `<basename.split('.')[0]>_<suffix><ext>` ex. `P1_Scan_cropped.nii.gz` (`AutoCrop3D_CLI.py:125-127`) | toujours | **N scans → N fichiers** (moins les patients sans ROI, sautés) |
| Modèle 3D VTK | `.vtk` (vtkPolyDataWriter, `GenerateVTKfromSeg.py:93-102`) | `<basename.split('.')[0]>_<suffix>_vtk.vtk` (`AutoCrop3D_CLI.py:128`) | si `"seg"` apparaît (insensible à la casse) **dans le chemin de sortie complet** (`AutoCrop3D_CLI.py:151`) | 1 par fichier "seg" (échec silencieux possible, `except: pass` ligne 154-155) |
| Volume croppé (chemin Crop Volume) | écrit par `slicer.util.saveNode` (`AutoCrop3D.py:898`) | `basename.replace('.nii.gz', f'_{suffix}.nii.gz')` (`AutoCrop3D.py:891`) — suffixe ajouté **uniquement** pour `.nii.gz` | case `checkBoxCV` cochée | N scans → N fichiers ; **pas de `.vtk`** dans ce chemin |
| Fichier de log de progression | texte | `<tempDir>/process.log` (`AutoCrop3D.py:188`) | chemin CLI seulement | 1 (temporaire, hors dossier de sortie) |
| Fichier temporaire | `image_padded.nii.gz` écrit **dans le répertoire courant** puis supprimé (`GenerateVTKfromSeg.py:88-89`, `:72`) | — | pendant la conversion VTK | transitoire |

Prose :

- **Arborescence préservée** : le chemin de sortie reprend le chemin relatif du scan par rapport au dossier d'entrée : `os.path.join(OutputPath, relative_path)` avec `os.makedirs(..., exist_ok=True)` (`AutoCrop3D_CLI.py:124-133`). Idem côté Crop Volume via `patient_path.replace(path_input, output_dir)` (`AutoCrop3D.py:892-896`) mais **sans** `makedirs` — la sauvegarde échoue silencieusement si le sous-dossier n'existe pas (`AutoCrop3D.py:897-901`).
- **Variation "Keep the same size as input"** (`box_Size == 'True'`, `AutoCrop3D_CLI.py:107-117`) : au lieu d'un volume réduit à la boîte ROI, la sortie a **les mêmes dimensions que l'entrée**, avec les voxels hors ROI mis à 0 (image blanche `sitk.Image` remplie par le contenu de la ROI). Sinon (`else`, ligne 119-120), la sortie est le sous-volume `img[Lower:Upper]` seul.
- **Cardinalité** : 1 ROI unique → appliquée à tous les N scans (N sorties). Dossier de ROIs → appariement par patient, sorties = nombre de scans ayant une ROI appariée. Les erreurs d'écriture sont loguées mais n'arrêtent pas le batch (`AutoCrop3D_CLI.py:135-146`).

## Comportement dossier vs fichier

- **Scans** : le combo `chooseType` (File/Folder) ne change que le dialogue de sélection (`getOpenFileName` vs `getExistingDirectory`, `AutoCrop3D.py:699-705`). Le traitement réel repose uniquement sur `os.path.isdir()` dans `Search` (`FilesType.py:37-52`) : dossier → glob récursif `**/*` + `endswith(ext)` ; fichier → accepté tel quel si son nom se termine par une des extensions.
- **ROI** : même mécanique. Fichier unique `.mrk.json` → même ROI pour tous les scans. Dossier → dictionnaire patient→ROI (`ChangeKeyDict`). Nuance côté CLI : le mode "appariement" ne s'active que si **plus d'un** `.mrk.json` est trouvé (`len(ROIList['.mrk.json']) > 1`, `AutoCrop3D_CLI.py:53,63`) ; côté UI/Crop Volume il s'active dès que le chemin ROI est un dossier (`os.path.isdir(path_ROI)`, `AutoCrop3D.py:918`).
- **Sortie** : toujours un dossier ; la hiérarchie des sous-dossiers d'entrée y est répliquée (chemin CLI).

## Incohérences et pièges observés dans le code

1. **Validation ≠ traitement pour les extensions** : `CheckInput` ne valide que `.nii.gz`, `.nrrd.gz`, `.gipl.gz` (`AutoCrop3D.py:808`), alors que le CLI et le chemin Crop Volume traitent aussi `.nii`, `.nrrd`, `.gipl` (`AutoCrop3D_CLI.py:48`, `AutoCrop3D.py:917`). Un fichier `.nrrd` seul est **refusé** par l'UI ("File authorized : .nii.gz, .nrrd.gz, .gipl.gz", `AutoCrop3D.py:823-826`) alors que le moteur sait le cropper. Dans un dossier mixte, le compteur de progression (`nbFiles`, calculé sur `list_patient` de `CheckInput`, `AutoCrop3D.py:555-558`) est **inférieur** au nombre réellement traité.
2. **`.nrrd.gz` / `.gipl.gz`** annoncés dans les messages d'erreur sont des extensions atypiques ; le format usuel `.nrrd` (compressé en interne) n'est pas mentionné à l'utilisateur.
3. **Bug ROI dossier avec un seul fichier (CLI)** : si la ROI est un **dossier** contenant exactement **1** `.mrk.json`, la condition `>1` (`AutoCrop3D_CLI.py:53`) est fausse, `ROI_Path` reste le chemin du dossier et `json.load(open(ROI_Path))` (`:70`) lève `IsADirectoryError` → le CLI plante.
4. **Appariement patient fragile** : clé ROI = `split('_')[0]` (`FilesType.py:78`) vs clé scan = découpage par suffixes connus (`AutoCrop3D_CLI.py:59`). Un identifiant patient contenant un underscore (ex. `P01_2024_Scan.nii.gz` vs `P01_2024_ROI.mrk.json` → clé ROI `P01`, clé scan `P01_2024`) ne s'apparie jamais ; en plus, deux ROIs `P01_left_...` et `P01_right_...` s'écrasent dans le dictionnaire (dernier gagnant).
5. **Suffixe perdu hors `.nii.gz` (chemin Crop Volume)** : `saveOutput` fait `replace('.nii.gz', ...)` uniquement (`AutoCrop3D.py:891`) ; pour `.nrrd`/`.gipl`, le fichier de sortie garde **exactement** le nom d'entrée (risque d'ambiguïté, voire d'écrasement de l'entrée si sortie = entrée).
6. **ROI hors volume / volume plus petit que la ROI** : le CLI borne correctement (`max(0, l)`, `min(img_size, u)`, `AutoCrop3D_CLI.py:83-87`) — la ROI est donc tronquée au volume. Mais si la ROI est entièrement hors du volume, la taille de crop devient 0 ou négative ; l'écriture échoue et l'erreur est seulement loguée (`:135-146`), le batch continue et l'UI affichera quand même "Scan(s) cropped with success" (`AutoCrop3D.py:618`) car seul le code retour global du CLI est testé.
7. **Détection "segmentation" par sous-chaîne de chemin** : la conversion VTK se déclenche si `"seg"` figure n'importe où dans le **chemin de sortie** (`AutoCrop3D_CLI.py:151`) — un dossier de sortie nommé `.../Segmentation_study/` déclenche la conversion VTK pour **tous** les scans (échouant silencieusement sur les CBCT en niveaux de gris, `except: pass`).
8. **Conversion VTK fragile** : `LABEL_COLORS` ne connaît que les labels 1–6 (`GenerateVTKfromSeg.py:7-14`) ; un label > 6 provoque un `KeyError` avalé par le `except: pass` du CLI. Le fichier temporaire `image_padded.nii.gz` est écrit dans le répertoire courant du process (`GenerateVTKfromSeg.py:88`), pas dans un répertoire temporaire.
9. **Le chemin Crop Volume vide la scène Slicer** : `slicer.mrmlScene.Clear(0)` à chaque itération (`AutoCrop3D.py:998`) supprime **tout** ce que l'utilisateur avait chargé dans Slicer, pas seulement les nœuds du module.
10. **Bouton Run activé seulement via les boutons "Select"** (`AutoCrop3D.py:696`) : coller un chemin dans les QLineEdit laisse le bouton grisé.
11. **`checkBoxSize` masquée quand `checkBoxCV` est cochée** (`AutoCrop3D.py:511-519`) : l'option "taille d'origine" n'existe pas dans le chemin Crop Volume — comportement voulu mais non documenté dans l'UI.
12. Divers restes de code : `img = sitk.ReadImage(...)` inutilisé dans le chemin Crop Volume (`AutoCrop3D.py:929`), fonction `Autofill` avec chemins codés en dur (`AutoCrop3D.py:399-404`), `Crop()` de `CropCBCT.py` explicitement "UNUSED" (`CropCBCT.py:23`), aide du module = texte d'exemple générique (`AutoCrop3D.py:57-60`).

## Avis — entrées/sorties à ajouter ou retirer

**À ajouter :**
- **Aligner la validation UI sur les extensions réellement traitées** (`.nii`, `.nrrd`, `.gipl`, et idéalement `.mha`/`.mhd` que SimpleITK lit nativement) — modification triviale de `AutoCrop3D.py:808`.
- **Accepter un nœud ROI de la scène** (`vtkMRMLMarkupsROINode` via `qMRMLNodeComboBox`) en plus du fichier `.mrk.json` : c'est le workflow naturel dans Slicer (dessiner la ROI puis lancer le batch) ; aujourd'hui il faut d'abord exporter le markups en JSON.
- **Un vrai code d'échec par fichier** : un rapport de sortie (CSV/JSON) listant fichiers traités / sautés (pas de ROI appariée) / en erreur, au lieu de warnings uniquement dans le log du CLI.
- Option explicite **"générer un modèle VTK"** (case à cocher) plutôt que la détection implicite par sous-chaîne `"seg"` dans le chemin.
- `makedirs` avant `saveNode` dans le chemin Crop Volume (`AutoCrop3D.py:897`).

**À retirer / corriger :**
- Le paramètre `logPath` pourrait rester interne mais son contrat (fichier écrasé à chaque run) mérite d'être isolé du dossier temp partagé.
- Retirer le code mort (`CropCBCT.Crop`, `Autofill`, l'import commenté `AutoCrop3D.py:26`) et les échantillons SampleData factices (`AutoCrop3D.py:89-118`, URLs SlicerTestingData génériques) qui ne correspondent pas à l'outil.
- Corriger le cas "dossier ROI avec 1 seul fichier" (`AutoCrop3D_CLI.py:53`) en remplaçant `len(...) > 1` par un test `os.path.isdir`, comme le fait déjà l'UI (`AutoCrop3D.py:918`) — incohérence interne entre les deux moteurs.
- Harmoniser le nommage de sortie des deux chemins (le chemin Crop Volume devrait réutiliser la logique suffixe+extension du CLI, `AutoCrop3D_CLI.py:125-129`).
