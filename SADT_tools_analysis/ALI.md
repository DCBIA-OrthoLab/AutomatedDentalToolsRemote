# ALI (ALI_CBCT / ALI_IOS)

Analyse basée sur la lecture du code réel (branche `main`). Fichiers analysés :
- `ALI/ALI.py` (module Slicer scripté : widget + logic + `LMTab`)
- `ALI/Resources/UI/ALI.ui` (interface Qt)
- `ALI/ALI_Method/Method.py` (classe abstraite + helper `search`), `ALI/ALI_Method/CBCT.py` (`Auto_CBCT`), `ALI/ALI_Method/IOS.py` (`Auto_IOS`), `ALI/ALI_Method/Progress.py`
- `ALI_CBCT/ALI_CBCT.py` + `ALI_CBCT.xml` + `ALI_CBCT_utils/{constants,io,preprocess,environment,agent,brain}.py`
- `ALI_IOS/ALI_IOS.py` + `ALI_IOS.xml` + `ALI_IOS_utils/{model,io,surface,agent,render}.py`

## Rôle

ALI place automatiquement des **landmarks anatomiques** et écrit des fichiers de markups Slicer. Un seul module UI, deux moteurs radicalement différents choisis par le combo `InputTypeComboBox` (`ALI.ui:302-313`, `ALI.py:417`, `ALI.py:458-490`) :

- **CBCT** (`Auto_CBCT`, CLI `ALI_CBCT`) : un **agent de RL profond par landmark** navigue dans le volume à deux échelles de spacing (1 mm puis 0.3 mm) et converge vers la position du point (`ALI_CBCT/ALI_CBCT_utils/agent.py:242-313`). Exécuté comme **CLI Slicer classique** (`ALI.py:921-925`, `CBCT.py:221`).
- **IOS** (`Auto_IOS`, CLI `ALI_IOS`) : segmentation des couronnes (`CrownSegmentationcli`) puis, dent par dent, rendu multi-vues + UNet 2D qui prédit des masques RGB reprojetés sur le maillage (`ALI_IOS/ALI_IOS.py:198-341`). Exécuté **dans un environnement conda `shapeaxi`** via `conda run -n shapeaxi python -m ALI_IOS` (`ALI.py:1164-1202`), pas via `slicer.cli.run`.

## Entrées

### Vue d'ensemble (UI commune)

| Entrée UI | Widget | Type | Mode concerné |
|---|---|---|---|
| Type d'entrée | `InputTypeComboBox` (`ALI.ui:302-313`) | combo « CBCT » / « IOS » | les deux |
| Extension | `ExtensioncomboBox` (`ALI.ui:316-327`) : « NIFTI, NRRD, GIPL » / « DICOM » | combo | **CBCT seul** (masqué en IOS, `ALI.py:467-468`) |
| Fichier vs dossier | `InputComboBox` (`ALI.ui:346-357`) : « Folder as input » / « File as input » | combo | les deux (forcé « dossier » en DICOM, `ALI.py:501-506`) |
| Nœud Slicer | `MRMLNodeComboBox` (`ALI.ui:360-369`) | nœud MRML | `vtkMRMLVolumeNode` en CBCT (`ALI.py:473`), `vtkMRMLModelNode` en IOS (`ALI.py:465`) |
| Dossier de scans | `lineEditScanPath` + `SearchScanFolder` (`ALI.ui:372`, `:434-441`) | dossier | les deux |
| Dossier de modèles IA | `lineEditModelPath` + `SearchModelsFolder` (`ALI.ui:375`, `:444-447`) | dossier de `.pth` | les deux |
| Télécharger les modèles | `SearchModelFolder` « Download Models » (`ALI.ui:472-475`) | bouton → `downloadModel` (`ALI.py:773-811`) | les deux |
| Télécharger un scan test | `DownloadTestPushButton` (`ALI.ui:462-468`) | bouton → `TestFiles` (`ALI.py:595-638`) | les deux |
| Sélection de dents | `self.tooth_lm` (`LMTab`, `ALI.py:405-408`) rempli avec `TEETH` (`ALI.py:112-115`) | 28 cases à cocher | **IOS seul** (masqué en CBCT, `ALI.py:482`) |
| Sélection de landmarks | `self.lm_tab` (`LMTab`, `ALI.py:410-412`) | cases à cocher par groupe | les deux, **contenu dépendant du dossier de modèles** |
| Dossier de sortie | `SaveFolderLineEdit` + `SearchSaveFolder` (`ALI.ui:659`, `:676-682`) | dossier | les deux |
| Sauver dans le dossier des scans | `SavePredictCheckBox` (`ALI.ui:587-597`) | booléen | les deux (actif seulement si dossier en entrée, `ALI.py:522`) |
| Prediction ID | `SaveId` (`ALI.ui:617-621`, valeur `Pred`) | texte | **jamais lu par le code** |
| Group output in a folder | `GroupInFolderCheckBox` (`ALI.ui:577-584`) | booléen | **jamais lu par le code** |

### Mode CBCT

**Scans.** Extensions réellement acceptées : `.nrrd`, `.nrrd.gz`, `.nii`, `.nii.gz`, `.gipl`, `.gipl.gz`.
- Comptage UI : `CountFileWithExtention(scan_folder, [".nrrd",".nrrd.gz",".nii",".nii.gz",".gipl",".gipl.gz"], [])` (`ALI.py:581`), qui fait `glob.iglob(path/**, recursive=True)` + test `ext in basename` (`ALI.py:559-570`) → **scan récursif**.
- Re-comptage/validation : `Auto_CBCT.NumberScan` (`CBCT.py:44-49`) via `Method.search` = `glob.iglob(path/**/*, recursive=True)` + `endswith` (`Method.py:166-194`) → **récursif** également.
- Découverte réelle côté CLI : `input_path.rglob(f"*{ext}")` pour les six extensions (`ALI_CBCT.py:87-96`) → **récursif**, clé du dictionnaire patient = `file.name` (nom de base).
- **Fichier unique** : `input_path.is_file()` → un seul patient (`ALI_CBCT.py:90-91`). Le chemin vient du nœud MRML sélectionné, via `PathFromNode` (`ALI.py:77-83`, `:529-540`).
- **Aucun filtre `QFileDialog`** n'existe : les quatre dialogues du module sont des `getExistingDirectory` (`ALI.py:573`, `:726`, `:814`, `:837`). Il n'y a **pas** de sélecteur de fichier ; le mode « File as input » passe obligatoirement par un nœud chargé dans Slicer.

**DICOM.** Si « DICOM » est choisi, `isDCMInput = True` (`ALI.py:501-506`) et le comptage devient `len(os.listdir(scan_folder))` (`ALI.py:579`) — donc « 1 patient = 1 sous-dossier », sans filtrage. Côté CLI, `convertdicom2nifti(args.input)` convertit **chaque sous-dossier** de l'entrée en `.nii.gz` (`ALI_CBCT.py:66-74`, `preprocess.py:191-271`).

**Modèles.** Dossier de `.pth` organisé en `<landmark>/<echelle>/xxx.pth` : `GetBrain` prend le **nom du dossier grand-parent comme nom du landmark** et le **nom du dossier parent comme clé d'échelle** (`ALI.py:1992-2005`, identique dans `ALI_CBCT_utils/io.py:75-88`). Le tableau des landmarks de l'UI est reconstruit à partir de cette arborescence (`ALI.py:736-754` → `GetAvailableLm`, `ALI.py:1967-1982`), en regroupant les noms via `GROUPS_LANDMARKS` (`ALI.py:101-109`) et en plaçant les inconnus dans un groupe « Other ». Le CLI recharge le même dictionnaire (`ALI_CBCT.py:175`) et associe **1 landmark = 1 agent = 1 jeu de poids** (`ALI_CBCT.py:206-208`, `brain.py:174-177` qui indexe par clé d'échelle `"1"` et `"0-3"`).

**Paramètres CLI fixés en dur** (non exposés à l'utilisateur, `CBCT.py:203-215` / `ALI_CBCT.xml:60-86`) : `spacing="[1,0.3]"`, `speed_per_scale="[1,1]"`, `agent_FOV="[64,64,64]"`, `spawn_radius="10"`, plus `temp_fold` (= `slicer.util.tempDirectory()`) et `DCMInput`. Signature CLI complète : `input, dir_models, lm_type, output_dir, temp_fold, dcm_input, spacing, speed_per_scale, agent_fov, spawn_radius` (`ALI_CBCT.py:256-265`).

**Passage de `lm_type`.** Le widget joint les landmarks cochés par des espaces (`ALI.py:882`), `CBCT.py:206` en refait une **liste Python**, et `slicer.cli.setNodeParameters` sérialise une liste en `str(value)` privé de ses crochets (`slicer/cli.py:44-47`) → la CLI reçoit `'Ba', 'S', 'N'` et `ast.literal_eval(f"[{args.lm_type}]")` (`ALI_CBCT.py:56`) reconstruit bien la liste. La chaîne est aussi comptée telle quelle par `NumberLandmark` (`CBCT.py:51-56`).

### Mode IOS

**Scans.** Extensions acceptées **selon l'étage** :
- Comptage UI : `.vtk` et `.stl` (`ALI.py:583`), récursif.
- `Auto_IOS.NumberScan` / `TestScan` : `.vtk` et `.stl`, fichier **ou** dossier (`IOS.py:35-43`, `:52-68`), récursif via `Method.search`.
- CSV envoyé à la segmentation : `os.walk(input_dir)` + `file.endswith(".vtk") or file.endswith(".stl")` (`IOS.py:92-94`) → **récursif**.
- **CLI `ALI_IOS`** : ne lit que le `.vtk` — `if os.path.isfile(vtkfile) and True in [ext in vtkfile for ext in [".vtk"]]` (`ALI_IOS.py:177`). En entrée « fichier unique », **aucun test d'extension** n'est fait (`ALI_IOS.py:167-171`).
- `ReadSurf` sait techniquement lire `.vtk`, `.vtp`, `.stl`, `.off`, `.obj` (`ALI_IOS_utils/surface.py:40-49`), mais ces formats ne sont jamais atteints par la découverte de fichiers.

**Pré-requis « déjà segmenté ».** `__isSegmented__` ouvre le maillage et cherche un tableau de points nommé `PredictedID`, `UniversalID` ou `Universal_ID` (`IOS.py:208-230`). Les fichiers déjà segmentés sont **copiés** vers le dossier temporaire `seg/` avec suffixe `_Seg` ; les autres vont dans `input_seg/` pour être segmentés par `CrownSegmentationcli` (`IOS.py:190-206`, `:232-274`).

**Dents.** `TEETH` = 14 dents hautes + 14 dents basses (`ALI.py:112-115`), au moins une obligatoire (`ALI.py:870-874`). Traduction en numérotation Universal côté CLI : `TradLabel` (`ALI_IOS_utils/io.py:126-166`, `UR1→8`, `LL7→18`, …) puis test d'appartenance `if int(label) in RI` sur le tableau de labels du maillage (`ALI_IOS.py:235`).

**Landmarks.** `SURFACE_LANDMARKS = {'Cervical': ['CL','CB','R','RIP','OIP'], 'Occlusal': ['O','DB','MB']}` (`ALI.py:117-120`). Le tableau UI n'affiche que les groupes pour lesquels un modèle existe : `GetNetworks` cherche les `.pth` dont le **nom de base contient `_O_` ou `_C_`** (`ALI.py:826-834` + `SURFACE_NETWORK`, `ALI.py:122-125`).

**Modèles.** Côté CLI, l'identifiant de modèle est `basename.split("_")[1]` et la mâchoire est déduite de la présence de la sous-chaîne `Lower` dans le nom de fichier (`ALI_IOS.py:124-138`) : tout `.pth` ne contenant pas « Lower » est classé **Upper**. Le lien landmark↔modèle passe par `MODELS_DICT = {'O': {'O':0,'MB':1,'DB':2}, 'C': {'CL':0,'CB':1}}` (`ALI_IOS_utils/model.py:53-56`) : un type de landmark coché sélectionne le réseau correspondant (`ALI_IOS.py:142-148`), et l'indice donne le canal RGB prédit (`ALI_IOS.py:284-292`). Le nom final du landmark vient de `dic_label` (`model.py:17-26`), construit comme `dent + type` (ex. `UR1O`, `UR1CL`).

**Paramètres CLI fixés en dur** (`IOS.py:276-286` / `ALI_IOS.xml`) : `image_size="224"`, `blur_radius="0"`, `faces_per_pixel="1"`, `log_path` (fichier de progression). Signature : `input, dir_models, lm_type, teeth, output_dir, image_size, blur_radius, faces_per_pixel, log_path` (`ALI_IOS.py:356-365`).

## Sorties

| Sortie | Mode | Format | Nommage | Emplacement | Cardinalité |
|---|---|---|---|---|---|
| Landmarks prédits | CBCT | markups Slicer, **`.mrk.json`** (`environment.py:130`, schéma `markups-schema-v1.0.0`, `ALI_CBCT_utils/io.py:28-71`) | `<nom_scan_avant_le_1er_point>_lm_Pred_<GROUPE>.mrk.json` (`environment.py:129-130`) | `output_dir` (`ALI_CBCT.py:236`) | **1 scan → 1 fichier par groupe de landmarks trouvés** (groupes `CB`, `U`, `L`, `CI`) → 0 à 4 fichiers |
| Landmarks prédits | IOS | markups Slicer, **`.json`** (pas `.mrk.json`) (`ALI_IOS.py:329-330`, `ALI_IOS_utils/io.py:64-124`) | `<basename_du_vtk_segmenté>_<Jaw>_<type>_Pred.json`, ex. `P1_Seg_Upper_O_Pred.json` | `output_dir` | **1 scan → 1 fichier par (mâchoire × type de réseau)** non vide → 0 à 4 fichiers (`Upper/Lower` × `O/C`) |
| Volumes prétraités | CBCT | `.nii.gz` / extension d'origine | `<nom>` (histogramme corrigé) et `<stem>_sp1<ext>`, `<stem>_sp0-3<ext>` (`ALI_CBCT.py:111-132`) | `temp_fold` = `slicer.util.tempDirectory()` | 3 fichiers par scan, temporaires |
| Conversion DICOM→NIfTI | CBCT + DICOM | `.nii.gz` | `<nom_du_sous_dossier>.nii.gz` (`preprocess.py:231`) | **`<dossier_d_entrée>/NIFTI/`** (`preprocess.py:218-219`) — écrit **dans les données de l'utilisateur** | 1 par sous-dossier DICOM |
| Maillages segmentés | IOS | `.vtk` | suffixe `Seg` (`IOS.py:271`) ; copies bypass `<nom>_Seg<ext>` (`IOS.py:196-200`) | `<tempDir>/seg` | 1 par scan |
| `liste_csv_file.csv` | IOS | CSV (colonne `surf`) | fixe | **dans les sources de l'extension** `ALI/ALI_Method/` (`IOS.py:84-86`) | 1, supprimé en fin de traitement (`ALI.py:1073-1081`) |
| `process.log` | IOS | texte (index du patient courant) | fixe | `slicer.util.tempDirectory()/process.log` (`ALI.py:375`, `ALI_IOS.py:344-348`) | 1 |

**Nommage — CBCT.** `id = self.patient_id.split(".")[0]` où `patient_id` est le **nom de fichier complet** (`ALI_CBCT.py:96`, `environment.py:129`) : `MG_test_scan.nii.gz` → `MG_test_scan_lm_Pred_CB.mrk.json`. Le groupe (`CB`, `U`, `L`, `CI`) provient de `LABEL_GROUPS`, construit depuis `GROUP_LABELS` (`ALI_CBCT_utils/constants.py:6-18`). Les coordonnées sont écrites en **LPS** (`ALI_CBCT_utils/io.py:36`).

**Nommage — IOS.** `f"{patient_id}_{jaw}_{models_type}_Pred.json"` (`ALI_IOS.py:329`) où `patient_id = os.path.basename(vtk).split('.')[0]` du fichier **segmenté** (donc portant déjà `_Seg`), `jaw ∈ {Upper, Lower}`, `models_type ∈ {O, C}`. Coordonnées également en LPS (`ALI_IOS_utils/io.py:85`).

**Cardinalité et variations.**
- **CBCT** : l'écriture a lieu une fois par patient, après tous les agents (`ALI_CBCT.py:234-238`). Les landmarks non trouvés (agent renvoyant `-1`, `agent.py:288-300`) sont simplement absents. Si **aucun** agent n'aboutit, `predicted_landmarks` est vide → **aucun fichier écrit** pour ce patient. Le nombre de fichiers n'est donc **pas** égal au nombre de landmarks cochés : les landmarks sont regroupés par région anatomique dans le même `.mrk.json`.
- **IOS** : la boucle est `patient × models_type × jaw` (`ALI_IOS.py:198-341`), un fichier n'est écrit que si `group_data` est non vide (`ALI_IOS.py:326`). Sélectionner uniquement des dents du haut ⇒ pas de fichier `Lower`. Sélectionner uniquement `O` ⇒ pas de fichier `_C_`.
- **Filtrage par sélection (IOS uniquement)** : le réseau `O` prédit toujours O+MB+DB et le réseau `C` toujours CL+CB, mais `GenControlPoint` ne garde que les labels présents dans `landmarks_selected = [dent + type]` (`ALI_IOS.py:101`, `ALI_IOS_utils/io.py:35-53`). La sélection agit donc comme **filtre a posteriori**, pas comme réduction du calcul.
- Aucun fichier de « rapport », de log utilisateur ou de QC n'est produit dans le dossier de sortie.

## Comportement dossier vs fichier

- **Choix UI** : le combo `InputComboBox` bascule entre `lineEditScanPath` (dossier) et `MRMLNodeComboBox` (nœud chargé) — `ALI.py:508-527`. Il n'y a **aucune sélection de fichier sur disque**.
- **CBCT** : les deux cas sont réellement gérés par la CLI (`input_path.is_file()` vs `rglob`, `ALI_CBCT.py:87-99`). Le mode fichier traite **1 scan**, le mode dossier **N scans** récursivement. Deux fichiers homonymes dans des sous-dossiers différents s'écrasent (clé du dictionnaire = `file.name`, `ALI_CBCT.py:95`), et les sorties portent le même nom → **collision silencieuse**.
- **IOS** : `Auto_IOS.Process` distingue explicitement fichier et dossier (`IOS.py:253-260`) — fichier → paramètre `surf`, dossier → `input_csv` + `vtk_folder`. Mais `__BypassCrownseg__` est appelé **avant** ce test (`IOS.py:244-246`) avec `Method.search` qui globe `path/**/*` : sur un **fichier**, il renvoie une liste vide → aucune détection « déjà segmenté », donc un `.vtk` déjà segmenté fourni en fichier unique est **re-segmenté** inutilement.
- **Sortie** : toujours un dossier **plat** (`output_dir`), l'arborescence des sous-dossiers d'entrée n'est **pas** répliquée, ni en CBCT ni en IOS.

## Incohérences et pièges observés dans le code

1. **Avertissement de validation sans arrêt du traitement.** `onPredictButton` affiche le message d'erreur de `TestProcess` puis **enchaîne immédiatement** sur `Process` sans `return` (`ALI.py:883-898`). Si le dossier de sortie est vide, `os.makedirs("")` lève `FileNotFoundError` (`CBCT.py:201`, `IOS.py:240`) et le module casse au lieu d'afficher proprement l'erreur. Le champ `SaveFolderLineEdit` n'est d'ailleurs pré-rempli que par le bouton « Download Test file » (`ALI.py:632-634`).
2. **`.stl` accepté par l'UI, ignoré par la CLI IOS.** L'UI compte et valide les `.stl` (`ALI.py:583`, `IOS.py:37`, `:61-62`) et le CSV de segmentation les inclut (`IOS.py:94`), mais `ALI_IOS.py:177` ne découvre que les `.vtk`. Un `.stl` **déjà segmenté** est copié tel quel dans `seg/` (`IOS.py:196-200`) puis **jamais traité** — silencieusement, sans message.
3. **Landmarks IOS sélectionnables sans modèle.** `SURFACE_LANDMARKS['Cervical']` propose `R`, `RIP`, `OIP` (`ALI.py:118`) alors que `MODELS_DICT` ne connaît que `CL`/`CB` et `O`/`MB`/`DB` (`model.py:53-56`) et que `TYPE_LM` ne contient pas ces trois types (`model.py:7`). Les cocher n'a **aucun effet** : ni sélection de réseau (`ALI_IOS.py:142-148`), ni label produit.
4. **Noms de landmarks « canine incluse » divergents.** L'UI liste `UR3OI, UL3OI, UR3RI, UL3RI` (`ALI.py:102`) tandis que la CLI attend `UR3OIP, UL3OIP, UR3RIP, UL3RIP` (`constants.py:10`). Conséquence grave : `SavePredictedLandmarks` fait `LABEL_GROUPS[landmark]` **sans garde** (`environment.py:123`) ; un landmark absent de `LABELS` (dossier de modèle nommé autrement, groupe « Other » de l'UI) déclenche un `KeyError` capturé plus haut (`ALI_CBCT.py:237-238`) → **aucun fichier n'est écrit pour ce patient**, y compris pour les landmarks correctement prédits.
5. **Deux boutons « Search » homonymes mais de rôles opposés.** `SearchModelsFolder` ouvre un dossier de modèles (`ALI.py:438`) alors que `SearchModelFolder` **télécharge** les modèles (`ALI.py:439-443`) ; leurs libellés UI sont « Search » et « Download Models » (`ALI.ui:444-447`, `:472-475`).
6. **Options de sortie inertes.** `SaveId` (« Prediction ID », valeur `Pred`, `ALI.ui:617-621`) et `GroupInFolderCheckBox` (« Group output in a folder », `ALI.ui:577-584`) ne sont **référencés nulle part** dans `ALI.py` (aucune occurrence). Le suffixe `Pred` est en réalité codé en dur dans les deux CLI (`environment.py:130`, `ALI_IOS.py:329`). L'attribut `self.goup_output_files` (`ALI.py:329`) n'est jamais lu.
7. **Mode DICOM incomplet.** `Auto_CBCT` n'implémente ni `NumberScanDCM` ni `TestScanDCM` ni `getTestFileListDCM` : les versions abstraites renvoient `None` (`Method.py:205-233`). Donc en DICOM : `CheckScan` affiche « Number of Patients to process : None » et `self.nb_patient = None` (`ALI.py:697-720`), ce qui casse `average_time = total_time / self.nb_patient` en fin de traitement (`ALI.py:1048`) ; et « Download Test file » lève une `TypeError` sur `name, url = None` (`ALI.py:599`), rattrapée en message d'erreur générique (`ALI.py:636-638`).
8. **Écriture dans le dossier d'entrée.** En DICOM, la conversion crée `<input>/NIFTI/*.nii.gz` (`preprocess.py:218-219`) : le dossier source de l'utilisateur est modifié, et ces fichiers sont ensuite redécouverts comme scans par `rglob` (`ALI_CBCT.py:93-96`) lors d'une seconde exécution.
9. **Écriture dans le répertoire d'installation.** `create_csv` écrit `liste_csv_file.csv` dans `ALI/ALI_Method/` (`IOS.py:84-86`), c'est-à-dire dans les sources de l'extension — problématique en installation lecture seule.
10. **`path_error` mort.** `path_error = os.path.join(kwargs["output_dir"], "Error")` (`IOS.py:242`) n'est ni créé ni transmis à la CLI : aucun dossier d'erreurs n'est produit malgré l'intention.
11. **Code de téléchargement mort.** `onTestDownloadButton` et `onModelDownloadButton` (`ALI.py:542-548`), et donc les dictionnaires `TEST_SCAN` et `MODELS_LINK` (`ALI.py:86-98`), ne sont connectés à **aucun** widget.
12. **Entrée « nœud » fragile.** Un nœud sans `vtkMRMLStorageNode` (créé dans Slicer, jamais sauvegardé) donne `input_path = None` (`ALI.py:77-83`) ; `TestScan(None)` appelle `os.path.isfile(None)` (`IOS.py:57`) → `TypeError` non gérée.
13. **Détection Upper/Lower des modèles IOS par sous-chaîne.** Tout `.pth` ne contenant pas « Lower » est réputé « Upper » (`ALI_IOS.py:132-135`) ; si un modèle mandibulaire manque, `models_to_use[type]['Lower']` lève un `KeyError` capturé silencieusement (`ALI_IOS.py:335-337`) et la mâchoire est simplement absente des sorties.
14. **Détection de réseau incohérente UI/CLI.** L'UI exige la sous-chaîne `_O_`/`_C_` dans le nom du `.pth` (`ALI.py:826-834`) alors que la CLI prend `basename.split("_")[1]` (`ALI_IOS.py:129`). Un fichier nommé `model_O.pth` est accepté par la CLI mais fait afficher « No models found in the selected folder » côté UI (`ALI.py:756-764`).
15. **Barre de progression heuristique.** `DisplayALICBCT` incrémente de `0.39` par événement et `DisplayALIIOS` de `1` (`Progress.py:71-94`, `:49-68`) : les compteurs « Landmarks : x / y » affichés ne reflètent pas des sorties réellement écrites.
16. **Écart README/code sur le format de sortie.** Le README (`README.md:144-212`) ne documente ni les noms ni les extensions des fichiers produits ; en pratique CBCT écrit du `.mrk.json` et IOS du `.json` — deux conventions différentes pour le même module.

## Modèles IA

| Mode | Bouton | URLs (`getModelUrl`) | Obligatoire | Association landmark ↔ modèle |
|---|---|---|---|---|
| CBCT | « Download Models » → clé `"Landmark"` (`ALI.py:776-801`) | 8 archives ZIP `.../releases/download/v0.1-v2.0_models/` : `Cranial_Base.zip`, `Lower_Bones_1.zip`, `Lower_Bones_2.zip`, `Lower_Left_Teeth.zip`, `Lower_Right_Teeth.zip`, `Upper_Bones_v2.zip`, `Upper_Left_Teeth_v2.zip`, `Upper_Right_Teeth_v2.zip` (`CBCT.py:109-118`) | **Oui** — sans `.pth` le tableau de landmarks reste vide et `TestModel` renvoie « Folder must have models for mask segmentation » (`CBCT.py:77-83`) | Par **arborescence de dossiers** : `<landmark>/<echelle>/*.pth`, nom du landmark = dossier grand-parent, échelles `1` et `0-3` (`ALI.py:1992-2005`, `brain.py:174-177`) |
| IOS | « Download Models » → clé `"Prediction"` (`ALI.py:776-790`) | `https://github.com/baptistebaquero/ALIDDM/releases/download/v1.0.3/Models.zip` (`IOS.py:160`) | **Oui** | Par **nom de fichier** : `split("_")[1]` ∈ {`O`,`C`} et présence de « Lower » (`ALI_IOS.py:124-138`), puis `MODELS_DICT` → canal RGB → label `dic_label` (`model.py:17-26`, `:53-56`) |
| IOS (segmentation) | implicite | `https://github.com/HUTIN1/ASO/releases/download/v1.0.0/segmentation_model.zip` déclaré (`IOS.py:159`) mais **non téléchargé** : le code utilise `dentalmodelseg` du binaire Slicer avec `model="latest"` (`IOS.py:247-248`, `:266`) | dépend de `CrownSegmentationcli` | — |

Autres dépendances IA/environnement :
- **CBCT** : `monai` (`1.3.2` ou `0.7.0` selon la version de Python), `itk`, `dicom2nifti==2.3.0`, `pydicom==2.2.2` installés via `pip_install` dans Slicer (`ALI.py:843-848`).
- **IOS** : environnement conda `shapeaxi` (`ocnn==2.2.1`, `shapeaxi==1.0.10`) + `pytorch3d`, créés/installés à la demande (`ALI.py:1205-1310`, `ALI.py:2054-2073`), WSL requis sous Windows (`ALI.py:1215-1241`).
- Les URLs `getALIModelList` (`CBCT.py:121-125`, `https://github.com/lucanchling/ALI_CBCT/releases/download/models_v01/`) et `getModelUrl()["Segmentation"]` côté CBCT (`CBCT.py:104-107`, modèles AMASSS) ne sont **jamais utilisées** par ALI.
- `TEST_SCAN`/`MODELS_LINK` (`ALI.py:86-98`) pointent vers des **pages de release** (`/tag/…`) et non des fichiers ; ils sont morts (cf. incohérence 11). Le scan de test réellement téléchargé est `MG_test_scan.nii.gz` (`CBCT.py:191-195`), et côté IOS `getTestFileList` renvoie une URL invalide mélangeant `/tag/v1.0.4/` et un nom de fichier (`IOS.py:145-149`) → le téléchargement de test IOS ne peut pas aboutir.

## Avis — entrées/sorties à ajouter ou retirer

**À ajouter**
1. **Un vrai sélecteur de fichier** (`QFileDialog.getOpenFileName` avec filtre `*.nii.gz *.nrrd *.gipl*` en CBCT, `*.vtk *.stl` en IOS). Aujourd'hui « File as input » impose de charger le volume/modèle dans la scène Slicer, ce qui est un détour inutile et fragile (nœuds sans storage node, cf. piège 12).
2. **Suffixe de sortie paramétrable** — le widget `SaveId` existe déjà : le brancher sur le nom de fichier (`_lm_<SaveId>_<groupe>.mrk.json`) au lieu du `Pred` codé en dur, et implémenter `GroupInFolderCheckBox` (sous-dossier par patient), sinon **retirer les deux widgets**.
3. **Préservation de l'arborescence d'entrée** dans la sortie, et **clé patient = chemin relatif** plutôt que `file.name`, pour éliminer les collisions silencieuses en batch récursif.
4. **Option « un seul fichier de landmarks par scan »** : la fusion des groupes (`CB`+`U`+`L`) en un unique `.mrk.json` est ce que la plupart des outils avals (ASO, AREG, AutoMatrix) attendent ; le découpage actuel par groupe oblige l'utilisateur à recombiner manuellement.
5. **Uniformiser l'extension** : `.mrk.json` des deux côtés (IOS écrit du `.json` alors que le contenu est bien un markups Slicer — Slicer ne l'associe pas automatiquement au bon type de nœud).
6. **Un fichier de rapport** (CSV/JSON) listant, par patient, les landmarks trouvés/échoués — l'information existe déjà (`fails` dans `ALI_CBCT.py:186,250-251`) mais ne quitte pas la console.
7. **Un dossier de sortie par défaut** dérivé du dossier d'entrée (`<input>/Predicted`) comme le fait déjà `TestFiles` (`ALI.py:632-634`), pour supprimer le crash sur sortie vide.

**À retirer / corriger**
1. **`R`, `RIP`, `OIP`** de `SURFACE_LANDMARKS` (`ALI.py:118`) tant qu'aucun modèle ne les prédit — ou les griser explicitement.
2. **Le mode DICOM** tel quel : soit implémenter `NumberScanDCM`/`TestScanDCM`/`getTestFileListDCM` dans `Auto_CBCT`, soit masquer l'option (elle produit `nb_patient = None`, un crash en fin de traitement et écrit dans le dossier source de l'utilisateur).
3. **`.stl`** de la validation IOS tant que la CLI ne lit que le `.vtk` — ou, mieux, ajouter `.stl` à la ligne `ALI_IOS.py:177`.
4. **Le code mort** : `onTestDownloadButton`/`onModelDownloadButton`, `TEST_SCAN`, `MODELS_LINK`, `path_error`, `self.goup_output_files`, `getModelUrl()["Segmentation"]` côté CBCT, `getALIModelList`.
5. **L'écriture de `liste_csv_file.csv` dans les sources de l'extension** → la déplacer dans le dossier temporaire déjà créé (`path_tmp`, `IOS.py:234`).
6. **Aligner les noms « canine incluse »** entre `ALI.py:102` et `constants.py:10`, et remplacer `LABEL_GROUPS[landmark]` par un `.get(landmark, "Other")` (`environment.py:123`) pour qu'un landmark inconnu ne fasse plus perdre **toutes** les sorties du patient.
