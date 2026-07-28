# BATCHDENTALSEG

> Analyse réalisée en lisant le code source réel du module (clone `SADT`), et non le README.
> Toutes les références `fichier:ligne` sont relatives à la racine du dépôt `SlicerAutomatedDentalTools`.
> Fichiers lus : `BATCHDENTALSEG/BATCHDENTALSEG.py`, `BATCHDENTALSEG/BATCHDENTALSEGLib/SegmentationWidget.py` (1924 lignes),
> `BATCHDENTALSEG/BATCHDENTALSEGLib/PythonDependencyChecker.py`, `BATCHDENTALSEG/BATCHDENTALSEGLib/Utils.py`,
> `BATCHDENTALSEG/CMakeLists.txt`, `BATCHDENTALSEG/Resources/ML/**`, `BATCHDENTALSEG/Testing/*`.

## Rôle

Module Slicer scripté (« BatchDentalSegmentator », catégorie *Automated Dental Tools*,
`BATCHDENTALSEG/BATCHDENTALSEG.py:26-27`) qui exécute une segmentation automatique **en lot** de scans
CT/CBCT dento-maxillo-faciaux, à partir de modèles **nnU-Net** (famille DentalSegmentator).

Le module n'a **pas d'UI Qt Designer** : aucun fichier `.ui` n'existe dans `BATCHDENTALSEG/`
(seuls des `.py`, `.png`, `.json` sont déclarés dans `BATCHDENTALSEG/CMakeLists.txt:5-27`).
Toute l'interface est construite en Python dans `SegmentationWidget.__init__`
(`BATCHDENTALSEG/BATCHDENTALSEGLib/SegmentationWidget.py:119-313`).

Le moteur d'inférence n'est pas dans ce dépôt : il est délégué à l'extension externe **SlicerNNUNet**
(`SlicerNNUNetLib.SegmentationLogic`, `.../SegmentationWidget.py:1906-1910` ; `SlicerNNUNetLib.Parameter`,
`.../SegmentationWidget.py:770`). Le module BATCHDENTALSEG ne fait donc que : choisir les fichiers,
choisir/télécharger les poids, lancer l'inférence scan par scan, renommer/colorier les segments et **écrire les fichiers de sortie**.

Pipeline complet (par volume) :
`selectFolder` → `onApplyClicked` → `processNextFile` → `onApplyClickedForVolume` → *(SlicerNNUNet)* →
`onInferenceFinished` → `_loadSegmentationResults` → écriture NIfTI multi-labels + `onExportClicked` → `_cleanupAfterCase` → fichier suivant.

## Entrées

### Tableau récapitulatif

| Entrée (UI) | Type | Valeurs / extensions réellement acceptées | Obligatoire | Référence |
|---|---|---|---|---|
| **Input Folder** | dossier (QFileDialog `getExistingDirectory`) | `*.nii*` (donc `.nii` et `.nii.gz`), `*.gipl`, `*.gipl.gz` — **non récursif** | Oui (contrôlé) | `SegmentationWidget.py:601-611`, validation `:656-660` |
| **Output Folder** | dossier | n/a | Oui *en pratique*, **non contrôlé** | `SegmentationWidget.py:560-564` |
| **Export STL** | case à cocher | booléen, **cochée par défaut** | non | `SegmentationWidget.py:154` |
| **Export OBJ** | case à cocher | booléen, décochée | non | `SegmentationWidget.py:155` |
| **Export NIFTI** | case à cocher | booléen, décochée | non | `SegmentationWidget.py:156` |
| **Export glTF** | case à cocher | booléen, décochée | non | `SegmentationWidget.py:157` |
| **Export VTK** | case à cocher | booléen, décochée | non | `SegmentationWidget.py:158` |
| **Export VTK (merged)** | case à cocher | booléen, décochée | non | `SegmentationWidget.py:159` |
| **glTF reduction factor** | slider ctk | 0.0 → 1.0, défaut 0.9 | non | `SegmentationWidget.py:161-165`, utilisé `:1864` |
| **Device** | combo | `cuda`, `cpu`, `mps` | oui (défaut `cuda`) | `SegmentationWidget.py:181` |
| **Model** | combo | `DentalSegmentator`, `PediatricDentalsegmentator`, `NasoMaxillaDentSeg`, `UniversalLabDentalsegmentator` | oui (défaut `DentalSegmentator`) | `SegmentationWidget.py:182-183` |
| **Segmentation node selector** | `qMRMLNodeComboBox` | `vtkMRMLSegmentationNode` existant, ou « Create new Segmentation on Apply » | non | `SegmentationWidget.py:196-206` |
| **Surface smoothing** | slider | 0 → 1 | non (**affichage 3D uniquement**) | `SegmentationWidget.py:219-225` |
| **Resolve Mirroring** | bouton | visible **seulement** si modèle = `UniversalLabDentalsegmentator` | non | `SegmentationWidget.py:186-191`, `:344-345` |

### Prose

**Sélection des volumes.** Le seul mode d'entrée est le **dossier** ; il n'existe aucun sélecteur de fichier
unique ni sélecteur de nœud volume. `selectFolder` ouvre un `getExistingDirectory` puis construit la liste :

```python
self.folderFiles = list(folder.glob("*.nii*")) + list(folder.glob("*.gipl")) + list(folder.glob("*.gipl.gz"))
```
(`SegmentationWidget.py:608`)

Conséquences directes, lues dans le code :
- `glob` et non `rglob` ⇒ **aucun scan récursif** : les sous-dossiers sont ignorés.
- Seuls `.nii`, `.nii.gz` (via `*.nii*`), `.gipl`, `.gipl.gz` sont pris. **Pas de `.nrrd`, `.mha`, `.mhd`, `.dcm`/DICOM**,
  alors que le chargement réel se fait par `slicer.util.loadVolume` (`SegmentationWidget.py:739`) qui, lui, saurait les lire.
- `*.nii*` attrape aussi des fichiers parasites du type `xxx.nii.json`, `xxx.nii.gz.tmp`.
- `list(folder.glob("*.gipl.gz"))` est redondant avec rien (le motif `*.gipl` ne matche pas `.gipl.gz`) — c'est correct, mais l'ordre final de la liste n'est pas trié : les NIfTI d'abord, puis les GIPL.

**Validation à l'Apply.** `onApplyClicked` ne vérifie que le dossier d'entrée et la non-vacuité de la liste
(`SegmentationWidget.py:656-660`). Le **dossier de sortie n'est jamais vérifié** ; `self.outputFolderPath`
n'est créé que dans `selectOutputFolder` (`SegmentationWidget.py:563`) et n'est **pas initialisé** dans `__init__`
(`SegmentationWidget.py:119-131`).

**Dépendances installées à chaque Apply.** À chaque clic sur Apply, le module réinstalle `light-the-torch`,
puis torch/torchvision, `numexpr`, `numpy<2.0`, `psutil` (`SegmentationWidget.py:666-669`, exécution via `PipRunner`
`:76-114`, `:704`). Ce n'est pas une « entrée » utilisateur mais c'est un prérequis réseau à chaque lancement.

**Choix du modèle et provenance des poids.** Quatre branches dans `onApplyClickedForVolume`
(`SegmentationWidget.py:769-858`) :

| Modèle (combo) | Dossier de poids | URL(s) de téléchargement | Référence |
|---|---|---|---|
| `DentalSegmentator` (défaut) | `BATCHDENTALSEG/Resources/ML` (racine, via `nnUnetFolder()`) | release GitHub du dépôt `gaudot/SlicerDentalSegmentator` (asset `[0]` de la 1re release listée) ; URL enregistrée : `https://github.com/gaudot/SlicerDentalSegmentator/releases/download/v1.0.0-alpha/Dataset111_453CT_v100.zip` | `SegmentationWidget.py:855-858`, `:1920-1923` ; `PythonDependencyChecker.py:59`, `:88-92`, `:129-176` ; `Resources/ML/download_info.json:1` |
| `PediatricDentalsegmentator` | `Resources/ML/Dataset001_380CT/nnUNetTrainer__nnUNetPlans__3d_fullres` | `.../SlicerAutomatedDentalTools/releases/download/PEDIATRICDENTALSEG_MODEL/{checkpoint_final.pth,dataset.json,plans.json}` | `SegmentationWidget.py:776-799` |
| `NasoMaxillaDentSeg` | `Resources/ML/Dataset001_max4/nnUNetTrainer__nnUNetPlans__3d_fullres` | `.../releases/download/NASOMAXILLADENTSEG_MODEL/{checkpoint_final.pth,dataset.json,plans.json}` | `SegmentationWidget.py:801-824` |
| `UniversalLabDentalsegmentator` | `Resources/ML/Dataset002_380CT/nnUNetTrainer__nnUNetPlans__3d_fullres` | `.../releases/download/UNIVERSALLAB_MODEL/{checkpoint_final.pth,dataset.json,plans.json}` | `SegmentationWidget.py:827-850` |

Dans tous les cas : `Parameter(folds="0", modelPath=..., device=...)` ⇒ **un seul fold (fold_0)**
(`SegmentationWidget.py:799`, `:824`, `:850`, `:858`). Si le device choisi n'est pas disponible, une boîte de
dialogue propose le repli CPU (`SegmentationWidget.py:860-871`).

**Entrées « cachées » (non exposées) :** `_minimumIslandSize_mm3 = 60` (`SegmentationWidget.py:126`) utilisé par
`_removeSmallIsland` (`:1487-1498`) — mais ces post-traitements ne sont **jamais appelés** (`_postProcessSegments`
est vide, `:1473-1475`). Le timeout d'urgence est fixé en dur à 5 min (`SegmentationWidget.py:307-309`).

## Sorties

### Tableau récapitulatif (par volume d'entrée traité)

| Sortie | Format | Nom de fichier | Cardinalité | Condition | Référence |
|---|---|---|---|---|---|
| Labelmap multi-labels | `.nii.gz` | `<NomVolume>_Segmentation.nii.gz` | **1** | **toujours** (aucune case à cocher) | `SegmentationWidget.py:1053-1062`, nom fixé `:1202` |
| Surfaces STL | `.stl` | `<NomSeg>_<NomSegment>.stl` (nommage Slicer) | **1 par segment** | case *Export STL* (cochée par défaut) | `SegmentationWidget.py:1677-1681` |
| Surface OBJ | `.obj` (+ `.mtl`) | `<NomSeg>.obj` | 1 (cf. test hérité `Testing/SegmentationWidgetTestCase.py:136`) | case *Export OBJ* | `SegmentationWidget.py:1677-1681` |
| Labelmaps binaires | `.nii.gz` | `<NomSeg>_<NomSegment>.nii.gz` (nommage Slicer) | 1 par segment | case *Export NIFTI* | `SegmentationWidget.py:1691-1694` |
| Modèle glTF | `.gltf` | déterminé par `OpenAnatomyExportLogic.exportModel` | 1 | case *Export glTF* (+ extension SlicerOpenAnatomy) | `SegmentationWidget.py:1697-1698`, `:1858-1872` |
| VTK par label | `.vtk` | `<NomSegAssaini>_<NomSegmentAssaini>.vtk` | **1 par segment** | case *Export VTK* | `SegmentationWidget.py:1800-1855`, nom `:1849` |
| VTK fusionné | `.vtk` | `<NomSeg>_merged.vtk` | **1** | case *Export VTK (merged)* | `SegmentationWidget.py:1701-1797`, nom `:1792` |

`<NomSeg>` = `<NomVolume>_Segmentation` (`SegmentationWidget.py:1202`), `<NomVolume>` étant le nom du nœud créé par
`slicer.util.loadVolume` (`:739`), c'est-à-dire le nom de fichier sans extension.

### Prose : nommage, cardinalité, variations

**Le NIfTI multi-labels est reconstruit à la main.** Après l'inférence, `onInferenceFinished` ne sauvegarde pas
directement le nœud de segmentation : il crée un tableau `numpy` de la taille du volume de référence, exporte
**segment par segment** un labelmap temporaire et y écrit la valeur de label officielle
(`SegmentationWidget.py:1005-1050`), puis reconstruit un `vtkMRMLLabelMapVolumeNode` avec le spacing/origin/IJKtoRAS
du volume source (`:1053-1059`) et l'écrit via `slicer.util.saveNode` (`:1061-1062`). Ce fichier est donc **toujours
produit**, quelles que soient les cases cochées — l'UI ne le mentionne nulle part.

**La valeur de label écrite** provient du tag VTK `LabelValue` s'il existe, sinon du dictionnaire retourné par
`_get_active_label_map` (`SegmentationWidget.py:877-927`), qui dépend du modèle :

| Modèle | Labels écrits dans le `.nii.gz` | Référence |
|---|---|---|
| `DentalSegmentator`, `PediatricDentalsegmentator` | 5 : Upper Skull=1, Mandible=2, Upper Teeth=3, Lower Teeth=4, Mandibular canal=5 | `SegmentationWidget.py:919-927` (cohérent avec `Resources/ML/Dataset111_453CT/.../dataset.json:3-10`) |
| `NasoMaxillaDentSeg` | 6 : Upper Skull=1, Mandible=2, **Maxilla=3**, Upper Teeth=4, Lower Teeth=5, Mandibular canal=6 | `SegmentationWidget.py:907-917` |
| `UniversalLabDentalsegmentator` | 55 : 32 dents permanentes (1-32), 20 dents temporaires (33-52), Mandible=53, Maxilla=54, Mandibular canal=55 | `SegmentationWidget.py:882-905` |

Un segment dont le nom n'est pas dans le dictionnaire actif **est silencieusement ignoré** (log `[WARN] ... — skipped`,
`SegmentationWidget.py:1030-1033`) : il disparaît du NIfTI de sortie.

**Cardinalité globale.** Pour N volumes d'entrée et S segments par volume (S = 5, 6 ou 55 selon le modèle) :
`N × 1` NIfTI multi-labels **+** (`N × S` STL si coché) **+** (`N × 1` OBJ si coché) **+** (`N × S` NIfTI binaires si
coché) **+** (`N × 1` glTF si coché) **+** (`N × S` VTK si coché) **+** (`N × 1` VTK fusionné si coché).
Avec les valeurs par défaut (STL seul) et `UniversalLabDentalsegmentator`, on obtient donc **56 fichiers par scan**.
Tous les fichiers sont écrits **à plat** dans l'unique dossier de sortie — aucun sous-dossier par patient n'est créé
(`SegmentationWidget.py:1061`, `:1670-1672`).

**Ce qui n'est jamais écrit :**
- Aucun `.seg.nrrd` n'est produit ; la segmentation n'est jamais sauvegardée sous forme de nœud de segmentation.
- La sortie brute de nnU-Net reste dans le répertoire temporaire de `SlicerNNUNetLib` (le chemin `self.logic._outFile`
  n'est lu que pour un test de stabilité de taille, `SegmentationWidget.py:1540-1541`) ; elle n'est pas copiée.
- Le résultat de **Resolve Mirroring** n'est écrit sur aucun disque : la fonction crée seulement un nœud
  `<NomSeg>_Mirrored` en mémoire (`SegmentationWidget.py:507-520`).
- `_saveSegmentationAsNifti` (`SegmentationWidget.py:569-594`) est **du code mort** : aucun appel dans tout le module
  (vérifié par grep sur `BATCHDENTALSEG/**/*.py`).

## Comportement dossier vs fichier

- **Uniquement le mode dossier.** Il n'existe aucun `QFileDialog.getOpenFileName` ni sélecteur de volume dans le
  module ; l'unique point d'entrée est `getExistingDirectory` (`SegmentationWidget.py:602`). Traiter un scan unique
  impose de créer un dossier ne contenant que ce scan.
- **Non récursif** (`folder.glob`, `SegmentationWidget.py:608`).
- **Boucle batch.** `processNextFile` charge le fichier courant, lance l'inférence et se termine ;
  l'enchaînement est fait dans le `finally` de `onInferenceFinished` : `currentFileIndex += 1` puis
  `qt.QTimer.singleShot(150, self.processNextFile)` (`SegmentationWidget.py:1106-1117`). Un compteur
  « Scan i/N – nom » est affiché (`:706-724`).
- **Nettoyage entre scans** : suppression des display nodes, de l'item de hiérarchie, du volume, vidage du cache CUDA
  et `gc.collect()` (`SegmentationWidget.py:1130-1195`).
- **Sortie plate** : tous les scans écrivent dans le même dossier ; deux scans homonymes (par ex. `case1.nii` et
  `case1.nii.gz` dans le même dossier, tous deux capturés par `*.nii*`) produisent des noms de sortie en collision.
- **Reprise** : `currentFileIndex` n'est remis à 0 que dans `selectFolder` (`SegmentationWidget.py:610`) ; après un
  arrêt, un nouvel Apply reprend à l'index courant plutôt qu'au début — comportement non documenté dans l'UI.

## Incohérences et pièges observés dans le code

1. **`outputFolderPath` non initialisé et non validé.** Défini uniquement dans `selectOutputFolder`
   (`SegmentationWidget.py:563`), jamais dans `__init__` (`:119-131`), et `onApplyClicked` ne le contrôle pas
   (`:656-660`). Lancer un batch sans avoir choisi le dossier de sortie ⇒ `AttributeError` à la ligne `:1061`,
   attrapée par le `except` `:1075-1081` ⇒ une boîte d'erreur **par scan**, l'inférence ayant déjà tourné.

2. **Une boîte de dialogue modale par scan.** `onExportClicked` est appelé au cœur de la boucle batch
   (`SegmentationWidget.py:1063`) et se termine par `slicer.util.infoDisplay("Export successful …")` (`:1672`) ;
   si aucun format n'est coché, c'est un `warningDisplay` (`:1666-1668`). Un batch de N scans exige donc N clics
   utilisateur : cela annule l'intérêt du mode « batch ».

3. **`NasoMaxillaDentSeg` : ordre des labels incohérent entre l'affichage et l'écriture.**
   `_updateSegmentationDisplay` renomme les segments **par position** dans l'ordre
   `["Upper Skull", "Mandible", "Upper Teeth", "Lower Teeth", "Mandibular canal", "Maxilla "]`
   (`SegmentationWidget.py:1429`), alors que `_get_active_label_map` déclare
   `Maxilla=3, Upper Teeth=4, Lower Teeth=5, Mandibular canal=6` (`:908-917`). Le segment n°3 est donc nommé
   « Upper Teeth » puis ré-encodé avec la valeur 4. En l'absence de tag `LabelValue` fiable, les valeurs écrites
   dans le NIfTI ne correspondent pas aux classes du réseau.

4. **`"Maxilla "` avec une espace finale** (`SegmentationWidget.py:1429`) : ce nom n'existe dans aucun dictionnaire
   (`:908-917` déclare `"Maxilla"`), donc `full_label_map.get(name)` renvoie `None` et le segment est **exclu du
   NIfTI** via le `continue` de `:1030-1033`.

5. **Les segments sont renommés par ID positionnel `Segment_1..Segment_n`** (`SegmentationWidget.py:1415`, `:1432`,
   `:1448`). Si `SlicerNNUNetLib.loadSegmentation()` produit d'autres IDs (ou si une classe est absente de la
   prédiction), `segmentation.GetSegment(segmentId)` renvoie `None` et le renommage est silencieusement sauté
   (`:1419-1420`, `:1436-1437`, `:1452-1453`) — les segments gardent alors leur nom brut et sont ensuite ignorés à
   l'export NIfTI.

6. **`downloadWeights` efface tout `Resources/ML`.** `shutil.rmtree(self.destWeightFolder)`
   (`PythonDependencyChecker.py:149-150`) avec `destWeightFolder = SegmentationWidget.nnUnetFolder()` =
   `BATCHDENTALSEG/Resources/ML` (`PythonDependencyChecker.py:58`, `SegmentationWidget.py:1920-1923`). Une mise à
   jour des poids DentalSegmentator **supprime aussi** `Dataset001_380CT`, `Dataset001_max4` et `Dataset002_380CT`,
   c'est-à-dire les poids des trois autres modèles.

7. **La détection « poids manquants » est trompeuse.** `areWeightsMissing()` teste la présence de **n'importe quel**
   `dataset.json` sous `Resources/ML` (`PythonDependencyChecker.py:113-117`). Or le dépôt versionne déjà
   `Resources/ML/Dataset111_453CT/.../dataset.json` et `plans.json`, mais **pas** le `checkpoint_final.pth`
   (exclu par `.gitignore:6` : `BATCHDENTALSEG/Resources/ML/**/*.pth`). Sur un clone frais, le module considère donc
   les poids présents alors que le checkpoint est absent. Symétriquement, avoir téléchargé le modèle pédiatrique
   suffit à faire croire que DentalSegmentator est installé.

8. **`downloadWeightsIfNeeded` est appelé quel que soit le modèle choisi** (`SegmentationWidget.py:697`) : on télécharge
   (ou vérifie) les poids DentalSegmentator même quand l'utilisateur a sélectionné NasoMaxilla ou UniversalLab.

9. **`getLatestReleaseUrl` prend `assets[0]`** de la concaténation de toutes les releases
   (`PythonDependencyChecker.py:88-92`) : aucune sélection par nom ni par tag — la publication d'une release
   contenant un asset non lié aux poids casse le téléchargement.

10. **Chemins `modelPath` asymétriques.** Pour les trois modèles ajoutés, `modelPath` pointe directement sur
    `.../nnUNetTrainer__nnUNetPlans__3d_fullres` (`SegmentationWidget.py:799`, `:824`, `:850`) ; pour
    DentalSegmentator il pointe sur la racine `Resources/ML` (`:858`). Deux conventions coexistent pour la même API.

11. **Le timeout de 5 minutes est inopérant.** `self._timeout_timer.start()` en début de `processNextFile`
    (`SegmentationWidget.py:729`) est immédiatement annulé par `self._timeout_timer.stop()` du `finally`
    (`:751-752`), qui s'exécute dès que l'inférence est *lancée* (appel non bloquant). Même schéma dans
    `onInferenceFinished` (`:946` puis `:1125`).

12. **`RemoveNode(segmentationNode)` mal indenté.** À `SegmentationWidget.py:1166`, l'appel se trouve **à l'intérieur
    du bloc `except Exception: pass`** ouvert en `:1163-1164` : il n'est exécuté que si la suppression de l'item de
    hiérarchie a levé une exception. Dans le chemin nominal, la suppression du nœud repose entièrement sur
    `shNode.RemoveItem` (`:1162`).

13. **Post-traitements morts.** `_postProcessSegments` ne fait que logger (`SegmentationWidget.py:1473-1475`) ;
    `_keepLargestIsland` (`:1477-1485`) et `_removeSmallIsland` (`:1487-1498`) ne sont appelés nulle part, tout comme
    `_minimumIslandSize_mm3` (`:126`). Le slider « Surface smoothing » (`:219-225`) n'agit que sur le rendu 3D, pas sur
    les fichiers exportés.

14. **`_exportMergedVTK` n'utilise pas les valeurs de label officielles.**
    `ExportAllSegmentsToLabelmapNode(segNode, labelmap)` est appelé sans géométrie de référence ni table de valeurs
    (`SegmentationWidget.py:1709`) : les scalaires du VTK fusionné sont les indices d'ordre des segments, pas les
    valeurs du dictionnaire de `:877-927`. Le `.vtk` fusionné et le `.nii.gz` multi-labels peuvent donc porter des
    numérotations différentes.

15. **`_exportToGLTF` ignore son argument.** La fonction reçoit `segmentationNode` mais exporte
    `self.segmentationNodeSelector.currentNode()` (`SegmentationWidget.py:1858-1864`).

16. **Tests hérités et cassés.** `Testing/IntegrationTestCase.py:5` et `Testing/SegmentationWidgetTestCase.py:8`
    importent `DentalSegmentatorLib` (module inexistant ici) et manipulent `self.widget.inputSelector`
    (`Testing/SegmentationWidgetTestCase.py:43`, `:53`, `:147`…), attribut qui n'existe plus dans
    `SegmentationWidget`. Les tests attendent aussi des noms de segments `"Maxilla & Upper Skull"`
    (`Testing/SegmentationWidgetTestCase.py:98`) alors que le code produit `"Upper Skull"`
    (`SegmentationWidget.py:1445`). La suite de tests référencée par `BATCHDENTALSEG.py:63-82` ne peut pas passer.

17. **Écart README / code sur les extensions d'entrée.** Le README (`README.md:658-660`) parle simplement d'un
    « Input folder (containing volumes to process) » sans préciser que seuls `.nii/.nii.gz/.gipl/.gipl.gz` sont
    acceptés — un dossier de `.nrrd` ou de DICOM produit « No valid volume file found » (`SegmentationWidget.py:659-661`).

18. **Écart README / code sur les sorties.** Le README ne mentionne ni les six formats d'export, ni le fait que le
    `.nii.gz` multi-labels est écrit systématiquement, ni le nommage `<volume>_Segmentation.*`.

19. **Écart README / code sur les libellés.** Le README annonce pour DentalSegmentator/Pediatric un segment
    « Maxilla & Upper Skull » (`README.md:666`, `:673`), le code écrit « Upper Skull » (`SegmentationWidget.py:1445`) ;
    le README annonce pour NasoMaxilla un « Naso-Maxilla Complex » (`README.md:682`), le code écrit « Maxilla »
    (`SegmentationWidget.py:913`, `:1429`).

20. **Dépendances réinstallées à chaque Apply** (`SegmentationWidget.py:666-668`) : `light-the-torch` + torch +
    torchvision sont (ré)installés à chaque lancement de batch, ce qui impose une connexion et allonge fortement le
    démarrage.

## Avis — entrées/sorties à ajouter ou retirer

**À ajouter (entrées)**
- Un vrai **sélecteur fichier unique** (ou l'acceptation d'un nœud volume déjà chargé) : le mode « dossier obligatoire »
  force à créer un dossier pour un seul scan.
- Une **case « scan récursif »** (passer de `glob` à `rglob`, `SegmentationWidget.py:608`) avec reconstruction de
  l'arborescence dans le dossier de sortie.
- **Élargir les extensions** à `.nrrd`, `.nhdr`, `.mha`, `.mhd` et à un dossier DICOM : `slicer.util.loadVolume`
  (`:739`) les gère déjà, seul le filtre `glob` bloque. Idéalement, centraliser la liste d'extensions dans une
  constante partagée avec les autres modules SADT.
- Une **validation du dossier de sortie** dans `onApplyClicked` (`:656-660`), au même titre que le dossier d'entrée.
- Un **suffixe / préfixe de sortie configurable** (aujourd'hui `_Segmentation` est codé en dur, `:1202`).
- Une case **« ignorer les scans déjà traités »** (reprise de batch) : aujourd'hui seul `currentFileIndex` sert de
  reprise implicite (`:610`, `:1107`).
- Exposer le **choix des folds** (aujourd'hui `folds="0"` en dur, `:799`, `:824`, `:850`, `:858`) et le **checkpoint**.
- Un **mode silencieux / sans dialogues** indispensable au batch (cf. incohérence 2).

**À retirer ou déplacer (entrées)**
- Le **slider « Surface smoothing »** (`:219-225`) et le **sélecteur de nœud de segmentation** (`:196-206`) sont des
  contrôles de session interactive sans effet sur les fichiers écrits : ils brouillent une UI batch (le sélecteur
  peut même provoquer la réutilisation d'un nœud existant et donc un nom de sortie erroné, `:1203-1204`, `:1213-1218`).
- Le bouton **Resolve Mirroring** : action manuelle post-batch dont le résultat n'est jamais écrit sur disque
  (`:507-520`) — soit l'intégrer comme option automatique de la boucle avec export, soit le sortir dans un module dédié.
- Le **slider glTF reduction factor** devrait être masqué tant que la case glTF n'est pas cochée.

**À ajouter (sorties)**
- Un **`.seg.nrrd`** (segmentation Slicer native, avec noms/couleurs/tags) : c'est le format le plus utile pour la
  correction manuelle et il n'est aujourd'hui jamais produit.
- Un **fichier de correspondance labels ↔ noms** (`labels.json` ou table de couleurs `.ctbl`) écrit à côté du
  `.nii.gz`, sinon la sémantique des 55 valeurs de `UniversalLabDentalsegmentator` (`:882-905`) est perdue.
- Un **rapport de batch CSV/JSON** (fichier traité, modèle, durée, segments trouvés/manquants, statut) : les
  avertissements « segment ignoré » (`:1030-1033`) ne subsistent aujourd'hui que dans les logs de l'UI.
- Une **organisation en sous-dossiers par scan** pour éviter les collisions à plat et rendre le résultat exploitable
  en aval (`:1061`, `:1670-1672`).

**À retirer / rendre optionnel (sorties)**
- Rendre le **NIfTI multi-labels explicitement optionnel** (case à cocher) ou, à défaut, l'annoncer dans l'UI :
  il est écrit inconditionnellement (`:1053-1062`) alors qu'une case « Export NIFTI » existe et fait autre chose
  (labelmaps binaires par segment, `:1691-1694`) — dualité très trompeuse.
- Clarifier ou supprimer l'un des deux exports VTK (`_exportVTKPerLabel` `:1800` vs `_exportMergedVTK` `:1701`),
  dont les conventions de numérotation diffèrent (cf. incohérence 14).
- Supprimer le code mort `_saveSegmentationAsNifti` (`:569-594`) pour éviter de laisser croire à un second chemin
  d'écriture.
