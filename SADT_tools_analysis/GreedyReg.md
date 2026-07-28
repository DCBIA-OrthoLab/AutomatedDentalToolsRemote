# GreedyReg

> Analyse fondée sur la lecture du code (module Slicer + CLI), pas sur le README.
> Fichiers analysés :
> - `GreedyReg/GreedyReg.py` (1704 lignes, toute l'UI est construite en Python — **aucun fichier `.ui`** dans le module)
> - `GreedyReg/GreedyReg_Method/Logic.py` (562 lignes)
> - `GreedyReg_CLI/GreedyReg_CLI.py` (204 lignes) et `GreedyReg_CLI/GreedyReg_CLI.xml`
> - `GreedyReg/CMakeLists.txt`, `GreedyReg_CLI/CMakeLists.txt`

## Rôle

Recalage (registration) de volumes CBCT de type « ITK-SNAP » à l'aide du moteur externe **Greedy** (binaire de la distribution ITK-SNAP). Le module Slicer sert de front-end : sélection des volumes, pré-alignement manuel, création d'un masque, puis lancement du recalage automatique. Le calcul réel est délégué hors-processus au module CLI `GreedyReg_CLI`, qui appelle le binaire `greedy` en sous-processus (`GreedyReg_CLI.py:128`, `GreedyReg_CLI.py:136`).

Quatre modes coexistent dans la même UI :

| Mode | Point d'entrée | Ce qu'il fait réellement |
|---|---|---|
| Alignement manuel | `GreedyReg.py:1185` (`onManualTransformChanged`), `GreedyReg.py:1335` (`onCenterVolumes`) | Modifie un `vtkMRMLLinearTransformNode` en scène. Aucun fichier. |
| Recalage automatique (1 paire) | `GreedyReg.py:1204` (`onRunRegistration`) | Exporte les nœuds en NIfTI dans un dossier temporaire, lance `GreedyReg_CLI`, recharge le volume recalé. |
| Recalage automatique par lot | `GreedyReg.py:1537` (`onRunBatchAuto`) | Passe directement les dossiers T1/T2/masques au CLI, qui boucle sur toutes les paires. |
| Distant Registration (ALI) | `GreedyReg.py:1406` (`onRunDistantRegistration`), `GreedyReg.py:1606` (`onRunBatchDist`) | Détection de landmarks via `slicer.modules.ali_cbct`, puis transformation rigide SVD. **N'utilise pas Greedy.** |

Point important : malgré le nom « Greedy » (moteur capable de recalage difféomorphique), **le code n'utilise que le mode affine** de Greedy — l'argument `-a` est toujours présent et jamais l'étape déformable (`GreedyReg_CLI.py:110`). Voir la section Sorties.

---

## Entrées

### Tableau récapitulatif

| Entrée | Type | Où (fichier:ligne) | Extensions réellement acceptées | Fichier / dossier | Obligatoire |
|---|---|---|---|---|---|
| Fixed (T1) | `vtkMRMLScalarVolumeNode` | `GreedyReg.py:322-326` | tout format chargeable par Slicer (ré-exporté en `.nii.gz`) | nœud MRML | Oui (mode 1 paire) |
| Moving (T2) | `vtkMRMLScalarVolumeNode` | `GreedyReg.py:328-332` | idem | nœud MRML | Oui (mode 1 paire) |
| Mask (T1) | `vtkMRMLSegmentationNode` **ou** `vtkMRMLLabelMapVolumeNode` | `GreedyReg.py:334-340` | idem (export `.nii.gz`) | nœud MRML | Non (`noneEnabled = True`, `GreedyReg.py:339`) |
| Source Volume (Segmentation) | `vtkMRMLScalarVolumeNode` | `GreedyReg.py:342-348` | — | nœud MRML | Non — **usage UI seulement** (volume source du Segment Editor, `GreedyReg.py:781`) |
| Segmentation | `vtkMRMLSegmentationNode` | `GreedyReg.py:352-358` | — | nœud MRML | Non — **usage UI seulement** (`GreedyReg.py:785`) |
| 3D Model (optional) | `vtkMRMLModelNode` | `GreedyReg.py:362-368` | — | nœud MRML | Non — **jamais envoyé à Greedy** (seulement suivi par la transform manuelle, `GreedyReg.py:775-777`) |
| Metric | combo `NMI` / `NCC` / `SSD` | `GreedyReg.py:573-577`, mappé `Logic.py:288` | — | — | Oui (défaut NMI) |
| Transform | combo `Rigid` / `Affine` | `GreedyReg.py:579-581`, mappé `Logic.py:289` | — | — | Oui (défaut Rigid) |
| Use segmentation as mask | case à cocher | `GreedyReg.py:583-585` | — | — | Défaut coché |
| T1 Folder (batch auto) | dossier | `GreedyReg.py:619-622` | `.nii.gz`, `.nii` **uniquement** (`GreedyReg_CLI.py:45`) | dossier, **non récursif** (`os.listdir`, `GreedyReg_CLI.py:44`) | Oui pour le batch |
| T2 Folder (batch auto) | dossier | `GreedyReg.py:624-627` | idem | idem | Oui pour le batch |
| Mask Folder (batch auto) | dossier | `GreedyReg.py:629-632` | `.nii.gz`, `.nii` (`GreedyReg_CLI.py:67`) | idem | Non |
| `initFolder` | dossier de matrices d'init | paramètre CLI `GreedyReg_CLI.xml:39-44`, scan `GreedyReg_CLI.py:52-61` | `.mat` **uniquement** | dossier, non récursif | Non — **non exposé dans l'UI batch** |
| ALI Models | dossier de modèles | `GreedyReg.py:673-682` | sous-dossiers nommés `Lower_Bones_1`, `Lower_Bones_2`, `Upper_Bones_v2`, `Cranial_Base` (`Logic.py:20-34`) | dossier | Oui pour Distant |
| Structures (Mandible / Maxilla / Cranial Base) | 3 cases à cocher | `GreedyReg.py:684-694` | — | — | Oui pour Distant |
| Transform (Distant) | combo `Rigid` / `Affine` | `GreedyReg.py:696-698` | — | — | **Jamais lu par le code** (voir Incohérences) |
| T1 / T2 Folder (batch Distant) | dossiers | `GreedyReg.py:716-724` | `.nii.gz`, `.nii` (`Logic.py:315`) | dossier, non récursif | Oui pour batch Distant |
| Binaire `greedy` | exécutable | `Logic.py:60-67` | `greedy` (Linux/macOS) ou `greedy.exe` (Windows) | fichier | Oui |

### Prose détaillée

**Extensions réellement acceptées.** Le filtre est strict et codé en dur à deux endroits qui doivent rester synchronisés : `GreedyReg_CLI.py:45` (`fname.endswith('.nii.gz') or fname.endswith('.nii')`) côté CLI et `Logic.py:315` (même test) côté aperçu GUI. Aucune autre extension n'est acceptée en mode dossier : ni `.nrrd`, ni `.nhdr`, ni `.mha`/`.mhd`, ni `.gipl`, ni DICOM — pourtant tous ces formats sont couramment utilisés dans SADT et lus nativement par Greedy/ITK. Les matrices d'initialisation sont filtrées séparément sur `.mat` (`GreedyReg_CLI.py:57`).

En revanche, en **mode « 1 paire »**, l'entrée n'est pas un fichier mais un **nœud MRML** déjà chargé dans Slicer : n'importe quel format lisible par Slicer convient, puisque le module ré-exporte systématiquement en `.nii.gz` avant d'appeler le CLI (`GreedyReg.py:1229-1236`). Les deux modes n'ont donc pas du tout la même tolérance de formats.

**Fichier unique vs dossier / scan récursif.** Le CLI ne travaille **que** par dossiers : les cinq premiers paramètres positionnels sont des dossiers (`GreedyReg_CLI.py:195-199`, `GreedyReg_CLI.xml:18-51`). Il n'existe aucun mode « fichier fixe + fichier mobile » au niveau CLI. Le mode « 1 paire » de l'UI simule un batch d'une seule paire : il crée `T1/`, `T2/`, `INIT/`, `OUTPUT/` (et `MASK/` si besoin) dans un `tempfile.mkdtemp()` et y dépose un seul cas nommé `CASE0001` (`GreedyReg.py:1222-1250`). **Aucun scan récursif** : `os.listdir` est utilisé partout (`GreedyReg_CLI.py:44`, `GreedyReg_CLI.py:56`, `Logic.py:316`) ; les sous-dossiers sont ignorés silencieusement.

**Appariement fixed/moving.** L'appariement se fait par un identifiant patient extrait du **début du nom de fichier** avec la regex `^([A-Za-z]+\d+)` insensible à la casse (`GreedyReg_CLI.py:37`, dupliquée en `Logic.py:308`). Exemples : `A01_t1.nii.gz` → `A01` ; `Patient12_scan.nii` → `PATIENT12`. Les clés sont normalisées en majuscules (`GreedyReg_CLI.py:48`). L'intersection des identifiants T1 et T2 donne les paires, triées (`GreedyReg_CLI.py:71-78`). Conséquences :
- un fichier commençant par un chiffre (`01_t1.nii.gz`) ou par un séparateur (`_A01.nii.gz`) **n'est jamais apparié** — il est ignoré sans message ;
- si deux fichiers du même dossier partagent le même préfixe, le dictionnaire ne garde que **le dernier vu dans l'ordre de `os.listdir`** (`GreedyReg_CLI.py:48`), c'est-à-dire un ordre non déterministe, sans avertissement ;
- masques et matrices d'init sont rattachés par le **même** identifiant (`GreedyReg_CLI.py:76-77`), donc `A01_MASK.nii.gz` et `A01_init.mat`.

**Masques.** Deux chemins distincts. En mode 1 paire, le nœud masque sélectionné est exporté en `.nii.gz` par `Logic.exportMask` (`Logic.py:272-275`) dans `MASK/{patientId}_MASK.nii.gz` (`GreedyReg.py:1249`), à condition que la case « Use segmentation as mask » soit cochée (`GreedyReg.py:1245`). En batch, le masque vient du dossier « Mask Folder » et **la case à cocher n'est pas consultée** (`GreedyReg.py:1540`, `GreedyReg.py:1572-1575`). Dans les deux cas, le CLI **binarise** le masque (`> 0`, cast `float32`) dans un fichier temporaire avant de le passer à Greedy (`GreedyReg_CLI.py:92-97`, appelé en `GreedyReg_CLI.py:174-175`), puis le transmet via l'option `-gm` (gradient mask, espace de l'image fixe) — `GreedyReg_CLI.py:119-120`.

**Matrice d'initialisation.** En mode 1 paire, la transform manuelle courante est écrite telle quelle dans `INIT/{patientId}_init.mat` au format texte 4 lignes × 4 valeurs (`Logic.py:277-284`, appelé en `GreedyReg.py:1239-1242`). Si la translation est nulle, `Logic.py:280-281` force `m[0][3] = 0.001` pour que Greedy ne la considère pas comme l'identité. Si aucun `.mat` n'est trouvé pour un cas, le CLI écrit lui-même une identité nudgée (`GreedyReg_CLI.py:82-89`, `GreedyReg_CLI.py:167-170`). La matrice est passée par `-ia` (`GreedyReg_CLI.py:118`).

**Paramètres Greedy effectivement construits** (`GreedyReg_CLI.py:100-121`) :
```
greedy -d 3 -a <metricArgs> -i fixed moving -o warp.mat
       -n 100x100x50x25 -e 0.5 -search 100 10 20 -dof {6|12} -ia init.mat [-gm mask.nii.gz]
```
avec `-m NMI`, `-m NCC 4x4x4` ou `-m SSD` (`GreedyReg_CLI.py:103-108`) et `-dof 6` pour Rigid / `12` pour Affine (`GreedyReg_CLI.py:102`). Timeout de 600 s par appel (`GreedyReg_CLI.py:125`). Les paramètres `-n`, `-e`, `-search` sont **codés en dur** et non exposés dans l'UI.

**Dépendance au binaire `greedy`.** Le binaire est cherché à `GreedyReg_CLI/bin/{linux|mac|windows}/greedy[.exe]` (`Logic.py:49-67`), le dossier `GreedyReg_CLI` étant localisé via `slicer.modules.greedyreg_cli.path` avec repli sur un chemin relatif (`Logic.py:63-66`). Ce dossier `bin/` **n'est pas versionné** dans le dépôt (aucun répertoire `bin` présent). S'il manque, `setup()` affiche un encart rouge « Greedy not found » et un bouton de téléchargement (`GreedyReg.py:293-307`). Le téléchargement (`Logic.py:106-145`) tire ITK-SNAP 4.2.2 depuis SourceForge :
- Linux : archive `.tar.gz`, extraction du membre `itksnap-4.2.2-.../bin/greedy` (`Logic.py:121-122`) ;
- macOS : archive `.tar.gz` **arm64 uniquement** (`Logic.py:124-125`) ;
- Windows : installeur NSIS `.exe`, extrait soit via 7-Zip s'il est installé (`Logic.py:187-202`), soit par installation silencieuse dans un dossier sans espace puis désinstallation (`Logic.py:209-260`).

**Dépendances Python.** `nibabel` est requis (binarisation des masques, écriture NIfTI) : vérifié/installé côté module par `Logic.ensureNibabelInstalled` (`Logic.py:82-104`), et le CLI échoue proprement s'il manque (`GreedyReg_CLI.py:14-22`). Le mode Distant requiert en plus `itk`, `dicom2nifti==2.3.0`, `pydicom==2.2.2`, `monai` (`Logic.py:336-338`) et les modèles ALI, téléchargés au besoin depuis la release `v0.1-v2.0_models` (`Logic.py:37-39`, `Logic.py:427-469`).

---

## Sorties

### Tableau récapitulatif

| Sortie | Format | Nommage | Emplacement | Cardinalité | Écrit par |
|---|---|---|---|---|---|
| Volume recalé | NIfTI compressé `.nii.gz` | `{patientId}_registered.nii.gz` | `outputFolder` | **1 par paire** | `GreedyReg_CLI.py:164`, résultat de `-rm` (`GreedyReg_CLI.py:134`) |
| Matrice de transformation | texte ITK, extension `.mat` | `{patientId}_warp.mat` | `outputFolder` | **1 par paire** | `GreedyReg_CLI.py:165`, résultat de `-o` (`GreedyReg_CLI.py:113`) |
| Volume T2 « aligné » (batch Distant) | `.nii.gz` | `{patientId}_t2_aligned.nii.gz` | **dossier T2 d'entrée** | 1 par paire | `GreedyReg.py:1698-1700` |
| Landmarks ALI | JSON markups Slicer | produit par `ALI_CBCT` | `<tmp>/ali_{fixed\|moving}/{modelSubDir}/` | 1+ par scan × sous-modèle | `Logic.py:495-515` (paramètres), lu en `Logic.py:517-533` |
| Champ de déformation | **jamais produit** | — | — | **0** | — |
| Fichiers intermédiaires (mode 1 paire) | `.nii.gz`, `.mat` | `CASE0001_t1.nii.gz`, `CASE0001_t2.nii.gz`, `CASE0001_init.mat`, `CASE0001_MASK.nii.gz` | `tempfile.mkdtemp()` | 3 à 4 | `GreedyReg.py:1229-1250` |

### Prose : nommage, cardinalité, variations

**Nommage.** Il est entièrement dérivé de l'identifiant patient extrait du nom du fichier T1/T2 : `os.path.join(args.outputFolder, f"{patientId}_registered.nii.gz")` et `f"{patientId}_warp.mat"` (`GreedyReg_CLI.py:164-165`). En mode 1 paire, l'identifiant est la constante `"CASE0001"` (`GreedyReg.py:1222`) — les fichiers produits s'appellent donc toujours `CASE0001_registered.nii.gz` / `CASE0001_warp.mat`, quel que soit le patient réellement traité. Le format `.nii.gz` est imposé par le suffixe du nom de fichier passé à Greedy (`-rm moving output`), il n'est pas configurable.

**Cardinalité.** Exactement **deux fichiers par paire appariée**, toujours, sans variation :
- N paires en entrée → 2N fichiers en sortie (`GreedyReg_CLI.py:156-181`, boucle unique) ;
- il n'y a **aucun** fichier de log, de rapport, de QC ou de résumé écrit sur disque ; la progression passe uniquement par les balises `<filter-progress>` / `<filter-comment>` sur stdout (`GreedyReg_CLI.py:158-159`, `GreedyReg_CLI.py:188-189`) ;
- la première paire en échec provoque `sys.exit(1)` (`GreedyReg_CLI.py:182-184`) : le lot est **interrompu**, les paires suivantes ne sont pas traitées et rien n'indique lesquelles ont abouti hormis les logs.

**Où atterrissent les sorties.**
- Mode 1 paire : `outputFolder` est un sous-dossier `OUTPUT` d'un répertoire temporaire (`GreedyReg.py:1227`). Le volume recalé est rechargé en scène (`GreedyReg.py:1284`) mais **rien n'est persisté** : l'utilisateur doit cliquer « Save Registered Volume » (`GreedyReg.py:1303-1312`) ou « Save Transform Matrix » (`GreedyReg.py:1288-1301`), qui font un simple `shutil.copy` depuis le temporaire vers un chemin choisi par `QFileDialog`. Le répertoire temporaire n'est **jamais supprimé**.
- Mode batch : `outputFolder` est **le dossier T2 lui-même** (`GreedyReg.py:1572-1573`, appel `buildGreedyCliParameters(t1Folder, t2Folder, t2Folder, ...)`). Les résultats sont donc écrits au milieu des données d'entrée. Il n'existe **aucun sélecteur de dossier de sortie dans l'UI**, alors que le CLI, lui, expose bien un `outputFolder` (`GreedyReg_CLI.xml:46-51`).

**Variations affine vs déformable.** Il n'y en a aucune. La commande contient toujours `-a` (mode affine de Greedy, `GreedyReg_CLI.py:110`) et la seule différence entre « Rigid » et « Affine » est `-dof 6` vs `-dof 12` (`GreedyReg_CLI.py:102`). Il n'y a **aucun appel déformable** (`greedy` sans `-a`, options `-s`, `-oroot`, `-it`…), donc **aucun champ de déformation n'est jamais produit**. Le fichier `{patientId}_warp.mat` malgré son nom est une **matrice affine 4×4 en texte**, pas un warp. Le nom et l'intitulé du bouton « Save Transform Matrix » (`GreedyReg.py:598`) sont cohérents entre eux ; c'est le nom de fichier `_warp` qui induit en erreur.

**Sorties du mode Distant.** Le mode Distant « 1 paire » **n'écrit aucun fichier** : il calcule une rigide par SVD sur les landmarks (`Logic.py:535-554`) et se contente de poser la matrice dans le `vtkMRMLLinearTransformNode` de la scène (`GreedyReg.py:1458-1465`). Le mode Distant **batch**, lui, écrit un fichier par paire en recalculant l'affine NIfTI du volume mobile avec `nibabel` (`GreedyReg.py:1691-1700`) : `{patientId}_t2_aligned.nii.gz`, **dans le dossier T2 d'entrée** (`GreedyReg.py:1698`). Les deux chemins ne produisent donc pas le même type de résultat.

---

## Comportement dossier vs fichier

- **Le CLI est exclusivement orienté dossier.** Ses 5 paramètres d'E/S sont des dossiers (`GreedyReg_CLI.xml:18-51`) et `main()` fait `os.makedirs(args.outputFolder, exist_ok=True)` puis `findPairs(...)` (`GreedyReg_CLI.py:146-151`). Passer un fichier ferait échouer `os.path.isdir` (`GreedyReg_CLI.py:42`) et le CLI sortirait avec « No matching T1/T2 pairs found » (`GreedyReg_CLI.py:150-151`).
- **Le mode 1 paire fabrique artificiellement une arborescence de dossiers** dans un temporaire pour se conformer à cette contrainte (`GreedyReg.py:1223-1250`). C'est le seul chemin qui accepte des données autres que du NIfTI, puisqu'il repose sur `slicer.util.exportNode`.
- **Aucune récursion.** `os.listdir` uniquement (`GreedyReg_CLI.py:44`, `GreedyReg_CLI.py:56`, `Logic.py:316`). Une organisation `Patients/A01/T1/scan.nii.gz` n'est pas gérée.
- **Séparation T1/T2 obligatoire.** Les scans fixes et mobiles doivent vivre dans **deux dossiers distincts** ; il n'y a pas d'appariement intra-dossier par suffixe `_T1`/`_T2`. Rien n'empêche cependant de pointer le même dossier pour T1 et T2 (chaque volume serait alors recalé sur lui-même).
- **Masques et inits sont aussi des dossiers**, appariés par le même identifiant, un fichier par cas (`GreedyReg_CLI.py:67-68`).

---

## Incohérences et pièges observés dans le code

1. **Les sorties du batch polluent le dossier d'entrée et cassent les ré-exécutions.** Les résultats sont écrits dans le dossier T2 (`GreedyReg.py:1573`), et `A01_registered.nii.gz` **matche la regex d'identifiant** (`^([A-Za-z]+\d+)` → `A01`, `GreedyReg_CLI.py:37`). Lors d'un second lancement, `findNiftiFiles` peut donc retenir `A01_registered.nii.gz` comme volume mobile à la place de `A01_t2.nii.gz` — le dictionnaire garde la dernière entrée rencontrée dans l'ordre de `os.listdir` (`GreedyReg_CLI.py:48`), ordre non déterministe. Même problème avec `{id}_t2_aligned.nii.gz` du batch Distant (`GreedyReg.py:1699`).
2. **Aucun dossier de sortie dans l'UI.** Le CLI expose `outputFolder` (`GreedyReg_CLI.xml:46-51`), mais l'UI ne l'expose jamais : forcé au temporaire en mode 1 paire, forcé au dossier T2 en batch.
3. **`{patientId}_warp.mat` n'est pas un warp** mais une matrice affine (`-a` toujours présent, `GreedyReg_CLI.py:110`). Nommage trompeur, et Greedy n'est jamais utilisé pour ce qui fait sa spécificité (le difféomorphisme).
4. **Bouton « Save Registered Volume » du panneau Distant : code mort.** `onSaveDistantVolume` lit `self._distantResult` (`GreedyReg.py:1471`), attribut **jamais assigné nulle part** dans le module (seul `_regResult` l'est, `GreedyReg.py:1257`). Le bouton affichera donc toujours « No result to save! ». Cohérent avec le fait que le mode Distant 1-paire n'écrit aucun fichier.
5. **Combo « Transform » du panneau Distant jamais lu.** `_distantTransformSelector` est créé (`GreedyReg.py:696-698`) mais n'est référencé nulle part ailleurs ; le calcul est toujours rigide (`Logic.rigidFromLandmarks`, `Logic.py:535`). L'option « Affine » y est mensongère.
6. **Trois cases à cocher « Structures », une seule région utilisée.** `_selectedDistantRegion` retourne la première région trouvée avec la priorité CB > Mandibule > Maxillaire (`GreedyReg.py:1397-1404`), alors que trois cases à cocher indépendantes suggèrent une sélection multiple.
7. **Le label « Select T1 and T2 folders to detect pairs » ne se met jamais à jour au parcours.** `_browseBatchFolder(lineEdit, pairsLabel)` gère bien un label (`GreedyReg.py:1530-1535`), mais les quatre appels passent `None` (`GreedyReg.py:621`, `626`, `631`, `718`, `723`). La branche `if pairsLabel:` est du code mort et le nombre de paires n'apparaît qu'après avoir cliqué sur « Run ».
8. **La case « Use segmentation as mask » n'a pas d'effet en batch.** Consultée uniquement en mode 1 paire (`GreedyReg.py:1245`) ; en batch, le dossier de masques est utilisé dès qu'il est renseigné (`GreedyReg.py:1540`, `1575`).
9. **`initFolder` inaccessible en batch.** `buildGreedyCliParameters` accepte `initFolder` (`Logic.py:287`), le CLI le documente (`GreedyReg_CLI.xml:39-44`) et sait charger des `.mat`, mais l'appel batch ne le passe pas (`GreedyReg.py:1572-1575`) : toutes les paires du lot partent d'une identité (`GreedyReg_CLI.py:167-170`). Impossible d'appliquer un pré-alignement manuel à un lot.
10. **Convention de coordonnées de la matrice d'init à vérifier.** `writeInitTransform` écrit brute la matrice du `vtkMRMLLinearTransformNode` (`Logic.py:277-284`), qui est en **RAS**, alors que les volumes exportés en NIfTI et lus par Greedy/ITK sont en **LPS**. Aucune conversion de signe n'est faite, contrairement à `parseAliLandmarksFromOutput` qui, lui, convertit explicitement LPS→RAS (`Logic.py:532`). Le pré-alignement manuel risque donc d'être transmis à Greedy avec les axes X/Y inversés — à confirmer par un test, mais l'asymétrie de traitement entre les deux fonctions est un signal fort.
11. **Le commentaire « Apply transform to moving volume before export » (`GreedyReg.py:1232`) est trompeur.** `slicer.util.exportNode` (`GreedyReg.py:1236`) n'applique pas la transform parente ; le pré-alignement ne passe que par le fichier d'init. Un lecteur pourrait croire à une double application.
12. **Duplication de la logique d'appariement.** La regex et le scan existent en double : `GreedyReg_CLI.py:37-49` et `Logic.py:308-319`. Le commentaire de `Logic.py:305-306` le reconnaît (« Matching logic must stay consistent with GreedyReg_CLI.py ») — dérive garantie à terme. `Logic.findBatchPairs` ignore d'ailleurs déjà `initFolder`.
13. **Extensions non gérées.** `.nrrd`, `.nhdr`, `.mha`/`.mhd`, `.gipl`, `.gipl.gz`, DICOM : tous silencieusement ignorés en mode dossier (`GreedyReg_CLI.py:45`). Aucun message n'indique à l'utilisateur qu'un fichier a été écarté pour cause d'extension ou de nom non conforme à la regex.
14. **Fuites de fichiers temporaires.** `tempfile.mkdtemp()` en `GreedyReg.py:1223`, `1430`, `1661` — jamais nettoyés. Seul le CLI nettoie son temporaire par cas (`GreedyReg_CLI.py:186`).
15. **`_platformBinDir` renvoie « mac » pour Darwin mais l'archive téléchargée est arm64 uniquement** (`Logic.py:124-125`) : sur un Mac Intel, le binaire installé sera inexécutable, sans détection d'architecture.
16. **Échec de lot non résilient.** `sys.exit(1)` à la première erreur (`GreedyReg_CLI.py:184`) ; un seul cas pathologique fait perdre le reste du traitement.
17. **`isGreedyAvailable()` n'est évalué qu'au `setup()`** (`GreedyReg.py:293`) : si le binaire est installé manuellement après ouverture du module, l'encart d'avertissement reste affiché jusqu'au rechargement (les boutons Run refont toutefois le test, `GreedyReg.py:1211`, `1547`).
18. **Paramètres de recalage figés.** `-n 100x100x50x25`, `-e 0.5`, `-search 100 10 20`, rayon NCC `4x4x4`, timeout 600 s (`GreedyReg_CLI.py:106`, `114-116`, `125`) : aucun n'est exposé, alors que le timeout notamment est court pour des CBCT haute résolution.
19. **Métadonnées de module incomplètes** : `contributors = ["Your Lab"]` (`GreedyReg.py:281`), `acknowledgementText = ""` (`GreedyReg.py:283`), `<contributor>Your Lab</contributor>` (`GreedyReg_CLI.xml:10`) — placeholders non renseignés.
20. **Beaucoup de surface UI non liée aux E/S du recalage** : le « Sensitivity Demo » (`GreedyReg.py:499-565`) est explicitement décrit dans le code comme un prototype ; il crée des overlays Qt sur les vues Red/Yellow/Green et n'a aucun effet sur les fichiers produits.

---

## Avis — entrées/sorties à ajouter ou retirer

### À ajouter (par ordre de priorité)

1. **Un sélecteur de dossier de sortie dans l'UI batch.** Le paramètre existe déjà côté CLI (`GreedyReg_CLI.xml:46-51`) ; il suffit de l'exposer. Cela règle d'un coup le point 1 (pollution du dossier T2) et le point 2. À défaut, écrire dans un sous-dossier `Registered/` créé sous T2.
2. **Exclure les sorties du scan d'entrée.** Filtrer les noms se terminant par `_registered`, `_warp`, `_t2_aligned` dans `findNiftiFiles` (`GreedyReg_CLI.py:40-49`), sinon les ré-exécutions restent non déterministes.
3. **Élargir les extensions acceptées** à `.nrrd`, `.nhdr`, `.mha`, `.mhd`, `.gipl(.gz)` — Greedy/ITK les lit nativement, il n'y a aucune raison technique de s'en tenir au NIfTI. Un simple tuple d'extensions partagé remplacerait les deux `endswith` dupliqués.
4. **Un vrai mode « fichier fixe + fichier mobile »** dans le CLI (deux chemins de fichiers au lieu de deux dossiers), qui supprimerait l'arborescence temporaire artificielle de `GreedyReg.py:1223-1250` et le nommage fantôme `CASE0001`.
5. **Exposer `initFolder` dans le batch** (le paramètre est déjà implémenté de bout en bout côté CLI) pour permettre un pré-alignement par cas.
6. **Un rapport de lot sur disque** (CSV/JSON) : identifiant, statut, chemins produits, temps, code de retour Greedy. Aujourd'hui il faut lire la console Python. À coupler avec un `continue`-on-error au lieu du `sys.exit(1)` de `GreedyReg_CLI.py:184`.
7. **Exposer la sortie « transform » comme un nœud Slicer chargeable.** Le `.mat` est copié brut (`GreedyReg.py:1300`) mais jamais converti en `vtkMRMLTransformNode` — l'utilisateur ne peut pas l'appliquer à un modèle 3D ou à une segmentation depuis Slicer, alors que le module propose justement un sélecteur de modèle 3D.
8. **Un vrai mode déformable optionnel** (Greedy sans `-a`, avec `-oroot`/`-s`), qui produirait le champ de déformation que le nommage `_warp.mat` laisse déjà espérer. Sinon, renommer en `_affine.mat`.
9. **Exposer au moins le timeout et le nombre d'itérations** (`GreedyReg_CLI.py:114`, `125`) en paramètres avancés.
10. **Détection d'architecture macOS** dans `Logic.downloadGreedyBinary` (`Logic.py:124`) et fallback x86_64.

### À retirer ou corriger

1. **Le bouton « Save Registered Volume » du panneau Distant** (`GreedyReg.py:711-713`) : soit le supprimer, soit réellement écrire le volume aligné en mode 1 paire (le code existe déjà pour le batch en `GreedyReg.py:1691-1700`).
2. **Le combo « Transform » du panneau Distant** (`GreedyReg.py:696-698`) : à supprimer ou à câbler ; en l'état il ment sur le comportement.
3. **Le sélecteur « 3D Model (optional) »** (`GreedyReg.py:362-368`) : soit le retirer des « Input Volumes » (il n'entre jamais dans Greedy), soit lui appliquer la matrice de sortie et permettre son export — c'est actuellement une entrée sans sortie correspondante.
4. **Les sélecteurs « Source Volume (Segmentation) » et « Segmentation »** (`GreedyReg.py:342-360`) : purement UI pour le Segment Editor ; ils n'ont rien à faire dans un panneau intitulé « Input Volumes », qui laisse croire que ce sont des entrées du recalage.
5. **Le panneau « Sensitivity Demo (Standalone Prototype) »** (`GreedyReg.py:510-565`) : prototype auto-déclaré, à sortir d'une version distribuée.
6. **La duplication de `findNiftiFiles`/`ID_PATTERN`** entre `Logic.py:304-328` et `GreedyReg_CLI.py:37-79` : à factoriser dans un module partagé.
7. **L'identifiant en dur `CASE0001`** (`GreedyReg.py:1222`) : le remplacer par le nom du nœud mobile pour que les fichiers sauvegardés soient traçables.
8. **Les trois cases « Structures »** (`GreedyReg.py:684-694`) : soit les transformer en boutons radio (cohérent avec `_selectedDistantRegion`, `GreedyReg.py:1397-1404`), soit gérer réellement le multi-régions.
