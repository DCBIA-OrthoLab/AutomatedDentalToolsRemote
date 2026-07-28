# CLIC

> Analyse basée sur la lecture du code réel du dépôt cloné (`CLIC/CLIC.py`, `CLIC/runner/clic_runner.py`, `CLIC/Resources/UI/CLIC.ui`, `CLIC/CMakeLists.txt`, `README.md`). Toutes les références `fichier:ligne` pointent vers ces fichiers.

## Rôle

CLIC (« CLI-C : Classification and Localization of Impacted Canines », README.md:88) est un module scripté 3D Slicer qui segmente des CBCT avec un **Mask R-CNN 2D appliqué coupe par coupe** (docstring CLIC.py:3, clic_runner.py:8-9). Le modèle prédit 3 classes de position de canine incluse : **1 = Buccal, 2 = Bicortical, 3 = Palatal** (légende CLIC.py:364-365), avec un réseau à 4 sorties (3 classes + fond, `_blank_model(4)` clic_runner.py:77 et définition clic_runner.py:44-50).

Architecture d'exécution :
1. Le widget Slicer (`CLICWidget`, CLIC.py:58) crée/valide un environnement conda dédié `clic_env` (Python 3.9, `numpy<2`, `scipy`, `nibabel`, `requests`, CLIC.py:120,167) puis y installe torch 2.2.0 / torchvision 0.17.0 / torchaudio 2.2.0 en cu118 (CLIC.py:182-186).
2. Pour chaque scan, il écrit un JSON de paramètres temporaire `clic_<idx>.json` dans `slicer.app.temporaryPath` (CLIC.py:250-256) puis lance `runner/clic_runner.py` dans l'env conda via `condaRunFilePython` (CLIC.py:261-265).
3. Le runner charge le volume avec nibabel, infère coupe par coupe (seuil de score 0,7, binarisation des masques à 0,5, clic_runner.py:93-94), et écrit la segmentation en NIfTI compressé (clic_runner.py:99-105).
4. Le widget parse le stdout du runner (tags `[PROGRESS]`, `[SEG]`, CLIC.py:268-274) pour mettre à jour la barre de progression et charger la segmentation dans la scène (CLIC.py:305-308), puis affiche une légende colorée dans les vues 2D (CLIC.py:361-385).

## Entrées

| Entrée | Widget UI | Type réel | Extensions acceptées | Obligatoire | Référence |
|---|---|---|---|---|---|
| Scans CBCT | `lineEditScanPath` + bouton `SearchScanFolder` (CLIC.ui:174-181) | **Dossier uniquement** (`QFileDialog.getExistingDirectory`) | `.nii`, `.nii.gz`, `.nrrd`, `.mha`, `.mhd` (insensible à la casse) | Oui | CLIC.py:310-314, CLIC.py:316-329 |
| Dossier modèle | `lineEditModelPath` + `SearchModelFolder` (CLIC.ui:229-236) | Dossier contenant au moins un `*.pth` | `.pth` (premier par ordre alphabétique) | Oui | CLIC.py:137-139 ; clic_runner.py:76 |
| Modèle pré-entraîné (téléchargement) | `DownloadModelPushButton` (CLIC.ui:206-211) | Fichier `.pth` téléchargé | — | Non (alternative au choix manuel) | CLIC.py:331-359 |
| Dossier de sortie | `SaveFolderLineEdit` + `SearchSaveFolder` (CLIC.ui:257-262, 296) | Dossier | — | **Non** (repli : dossier parent du scan) | CLIC.py:140-142 ; clic_runner.py:71 |
| Suffixe | `suffixLineEdit` (CLIC.ui:276-281) | Texte libre | — | Non (défaut `"seg"`) | CLIC.py:255 ; clic_runner.py:72 |

Détails et preuves :

- **Sélection : dossier seulement.** Les trois boutons Browse passent tous par `_browse`, qui appelle `qt.QFileDialog.getExistingDirectory` (CLIC.py:311). Il est donc **impossible de sélectionner un fichier unique via l'UI**, alors que le label affiche « Select Scan File/Folder » (CLIC.ui:165). Le code de collecte gère pourtant le cas fichier (`return [p]` si `p` n'est pas un dossier, CLIC.py:329) — branche morte via l'UI.
- **Extensions filtrées** dans `_collect_scans` : tuple `(".nii", ".nii.gz", ".nrrd", ".mha", ".mhd")` (CLIC.py:318), testées par `name.lower().endswith(ext)` (CLIC.py:322-323), donc `.nii.gz` est correctement reconnu.
- **Scan NON récursif** : un seul niveau. `_collect_scans` liste d'abord les sous-dossiers immédiats contenant au moins un scan valide et, s'il y en a, retourne **les sous-dossiers eux-mêmes** ; sinon il retourne les fichiers valides à la racine du dossier (CLIC.py:325-328). Aucun `rglob`/récursion plus profonde.
- **Validation à l'exécution** : `_on_predict` exige seulement `input_path` et `model_dir` (CLIC.py:226-228) ; message « No scan found » si la collecte est vide (CLIC.py:238-240). Le dossier de sortie n'est jamais vérifié.
- **Modèle IA** : URL de téléchargement unique et codée en dur `https://github.com/DCBIA-OrthoLab/SlicerAutomatedDentalTools/releases/download/CLIC_model/final_model.pth` (CLIC.py:333-337), enregistré dans `~/Documents/CLIC_Models/final_model.pth` (CLIC.py:338-340) ; le champ modèle est alors auto-rempli (CLIC.py:351-352). Côté runner, le poids chargé est `sorted(model_dir.glob("*.pth"))[0]` (clic_runner.py:76) : premier `.pth` alphabétique, `IndexError` brut si le dossier n'en contient aucun.
- **Paramètres inter-processus** : JSON `{input_path, model_folder, output_dir, suffix}` (CLIC.py:251-256), lu par le runner (clic_runner.py:67-72).
- **Données d'exemple** documentées : `MN138.nii`, `UM06.nii` (README.md:804).

## Sorties

| Sortie | Format | Chemin / nommage | Cardinalité | Référence |
|---|---|---|---|---|
| Segmentation | NIfTI compressé, labels int16 (0-3) | `<output_dir>/<stem_du_scan>/<stem_du_scan>_<suffix>.nii.gz` | **1 fichier par scan**, chacun dans son propre sous-dossier | clic_runner.py:100-104 |
| JSON de paramètres | `.json` | `<slicer temporaryPath>/clic_<idx>.json` | 1 par scan, **supprimé après exécution** (`tmp.unlink`) | CLIC.py:250-256, 275 |
| Chargements dans la scène Slicer | nœuds Volume + Segmentation | via `loadVolume` / `loadSegmentation` | 1 volume par scan ; segmentation seulement si le tag `[SEG]` est détecté | CLIC.py:249, 303-308 |
| Légende 2D (Buccal/Bicortical/Palatal) | acteurs VTK dans les vues Red/Yellow/Green | — (affichage uniquement, rien d'écrit) | recréée à chaque segmentation active | CLIC.py:361-385 |
| Modèle téléchargé | `.pth` | `~/Documents/CLIC_Models/final_model.pth` | 1, écrasé à chaque re-téléchargement | CLIC.py:338-348 |

Détails :

- **Nommage** : `out_dir = out_root / inp.stem` puis `out_path = out_dir / f"{inp.stem}_{suffix}.nii.gz"` (clic_runner.py:100-102), `out_dir` créé avec `mkdir(parents=True, exist_ok=True)` (clic_runner.py:101). Le format de sortie est **toujours** `.nii.gz`, quel que soit le format d'entrée.
- **Piège `Path.stem`** : pour un scan `patient.nii.gz`, `inp.stem` vaut `patient.nii` → sortie `<output>/patient.nii/patient.nii_seg.nii.gz` (sous-dossier avec pseudo-extension et double extension dans le nom). Seuls les `.nii` non compressés donnent un nommage propre.
- **Variation selon options** :
  - `output_dir` non renseigné → `out_root = inp.parent` (clic_runner.py:71) : la sortie atterrit dans un sous-dossier **du dossier d'entrée** (c'est le seul mécanisme réalisant « Save Predictions in Input Folder »).
  - `suffix` vide → repli sur `"seg"` côté widget (CLIC.py:255) et côté runner (clic_runner.py:72).
- **Contenu** : volume int16 de même géométrie que l'entrée (affine + header copiés, clic_runner.py:103-104), voxels étiquetés 1/2/3 pour les détections dont le score ≥ 0,7 (clic_runner.py:93-96) ; en cas de chevauchement, la dernière détection écrase les précédentes (écriture séquentielle CLIC/clic_runner.py:94-96).

## Comportement dossier vs fichier

- **Dossier avec fichiers scans à la racine** : chaque fichier `.nii/.nii.gz/.nrrd/.mha/.mhd` est traité séquentiellement (boucle CLIC.py:246-275) ; 1 sous-dossier de sortie + 1 `.nii.gz` par scan.
- **Dossier contenant des sous-dossiers de scans** : `_collect_scans` retourne alors la **liste des sous-dossiers** (CLIC.py:327-328), et chaque sous-dossier est passé tel quel comme `input_path` au runner, qui fait `nib.load(<dossier>)` (clic_runner.py:83) → **échec systématique** (nibabel ne charge pas un répertoire). Ce mode, visiblement pensé pour du DICOM (variable nommée `dcm`, CLIC.py:327), est cassé : le runner devrait itérer sur les fichiers du sous-dossier ou charger une série DICOM, ce qu'il ne fait pas.
- **Fichier unique** : géré dans le code (`return [p]`, CLIC.py:329) mais **inatteignable via l'UI** puisque `_browse` n'ouvre que des dossiers (CLIC.py:311). Seule une manipulation programmatique de `self.input_path` permettrait ce mode.
- **Récursivité** : aucune au-delà du premier niveau de sous-dossiers.

## Incohérences et pièges observés dans le code

1. **Protocole stdout cassé par le logging** (le plus grave) : le runner émet `[PROGRESS]`/`[SEG]`/`[LOG]` via `logger.info` (clic_runner.py:58-60) avec le formatteur `'%(name)s - %(levelname)s - (%(filename)s:%(lineno)d) - %(message)s'` (clic_runner.py:39). Les lignes réelles sont donc `CLIC_runner - INFO - (clic_runner.py:59) - [PROGRESS] 42`, alors que le widget teste `ln.startswith("[PROGRESS]")` et `ln.startswith("[SEG]")` (CLIC.py:269-272). **Ces préfixes ne matchent jamais** : la barre de progression ne bouge pas et la segmentation n'est jamais auto-chargée/colorée (tout part dans le log brut). De plus, `condaRunFilePython` ne retourne la sortie qu'en fin de processus, donc même corrigée, la « progression » serait rétroactive.
2. **Case à cocher fantôme** : `SavePredictCheckBox` « Save Predictions in Input Folder » (CLIC.ui:250-254) n'est **jamais connectée ni lue** dans CLIC.py (aucune occurrence). Le comportement équivalent n'existe que par accident via le repli `output_dir=None → inp.parent` (clic_runner.py:71).
3. **Extensions annoncées mais non lisibles** : `_collect_scans` accepte `.nrrd`, `.mha`, `.mhd` (CLIC.py:318) mais le runner ne lit qu'avec **nibabel** (`nib.load`, clic_runner.py:83), qui ne supporte aucun de ces trois formats → `ImageFileError` garanti. Seuls `.nii`/`.nii.gz` fonctionnent réellement (cohérent avec la docstring clic_runner.py:7).
4. **Mode sous-dossiers/DICOM cassé** : passage de répertoires entiers à `nib.load` (voir section précédente ; CLIC.py:327-328 vs clic_runner.py:83).
5. **UI « File/Folder » mensongère** : label « Select Scan File/Folder » (CLIC.ui:165) vs sélection dossier-uniquement (CLIC.py:311).
6. **Bouton Cancel inopérant** : `_on_cancel` ne fait qu'écrire un log (CLIC.py:288-289) ; `cancel_evt` n'est jamais déclenché par l'utilisateur (il ne sert qu'à terminer la boucle UI en fin de worker, CLIC.py:276).
7. **Widget dupliqué** : deux `QTextEdit` nommés `logTextEdit` dans le .ui (CLIC.ui:343 et CLIC.ui:353) ; `childWidgetVariables` n'en référencera qu'un — les logs peuvent s'afficher dans le mauvais.
8. **Chemins codés en dur spécifiques à une machine** : `/home/luciacev/anaconda3/bin/conda` et `/home/luciacev/anaconda3` comme replis conda (CLIC.py:90, CLIC.py:104-107) — non portable.
9. **Nommage `.nii.gz`** : `Path.stem` ne retire qu'une extension → sous-dossier `X.nii` et fichier `X.nii_seg.nii.gz` pour toute entrée compressée (clic_runner.py:100-102).
10. **Crash silencieux si pas de `.pth`** : `sorted(model_dir.glob("*.pth"))[0]` (clic_runner.py:76) lève `IndexError` sans message utilisateur ; le widget ne vérifie pas le contenu du dossier modèle.
11. **Pip douteux** : le déclassement numpy est passé sous la forme `"'numpy<2.0'"` avec quotes imbriquées (CLIC.py:204), susceptible d'installer littéralement `'numpy<2.0'` ou d'échouer selon le shell intermédiaire.
12. **Écrasement de segmentation existante** sans avertissement (`mkdir exist_ok=True` + `nib.save` direct, clic_runner.py:101-104).
13. **Test vide** : `CLIC/testing/test_CanineSegmentation.py` fait 0 octet — aucune couverture de test.
14. **README vs code** : le README parle d'un bouton « Predict » / « Run Prediction » et d'un choix fichier ou dossier (README.md:802, 825) ; le bouton réel s'appelle « Run » (CLIC.ui:310) et seul un dossier est sélectionnable.

## Avis — entrées/sorties à ajouter ou retirer

**À corriger en priorité (avant d'ajouter quoi que ce soit)**
- Réparer le protocole `[PROGRESS]`/`[SEG]` : faire des `print(...)` bruts (ou retirer le formatteur logging) côté runner, sinon aucune sortie n'est jamais rechargée dans Slicer.
- Soit retirer `.nrrd`/`.mha`/`.mhd` de `_collect_scans`, soit remplacer nibabel par SimpleITK dans le runner (SimpleITK lit les cinq formats et permettrait aussi les séries DICOM) — l'état actuel promet des formats qui plantent.
- Corriger le mode sous-dossiers (itérer sur les fichiers du sous-dossier, ou supprimer cette branche).

**Entrées à ajouter**
- Un vrai sélecteur **fichier OU dossier** (deux boutons, ou `getOpenFileName` avec filtre `*.nii *.nii.gz`), puisque le code du runner gère déjà le scan unique.
- Exposer le **seuil de score** (0,7) et le **seuil de masque** (0,5), aujourd'hui codés en dur (clic_runner.py:93-94) — utile cliniquement pour ajuster sensibilité/spécificité.
- Un sélecteur de **fichier `.pth` précis** plutôt qu'un dossier dont on prend silencieusement le premier `.pth` alphabétique.
- Option CPU/GPU explicite (le runner choisit seul, clic_runner.py:73).

**Entrées à retirer / nettoyer**
- `SavePredictCheckBox` : la retirer du .ui ou la câbler réellement (`output_dir = None` quand cochée) — en l'état c'est une entrée morte trompeuse.
- Les chemins anaconda codés en dur (CLIC.py:90,104) : à retirer d'une extension distribuée publiquement.

**Sorties à ajouter**
- Un **nettoyage du stem** (`.nii.gz` → nom de base propre) pour éviter les dossiers `X.nii`.
- Une option « fichier plat dans le dossier de sortie » (sans sous-dossier par scan) : la cardinalité 1 sous-dossier + 1 fichier par scan complique les traitements batch en aval.
- Un petit **rapport récapitulatif** (CSV/JSON : scan, classe(s) détectée(s), volumes par label, temps) — le module classifie Buccal/Bicortical/Palatal mais n'exporte aujourd'hui **aucune donnée de classification**, uniquement le masque ; c'est la sortie la plus utile qui manque au vu du rôle annoncé de l'outil (classification de canines incluses).
- Un code de retour/erreur structuré du runner (tag `[ERROR]`) pour que le widget signale les scans en échec au lieu de continuer silencieusement.
