# AMASSS

## Rôle

AMASSS (*Automatic Multi-Anatomical Skull Structure Segmentation*) segmente automatiquement les structures
osseuses et molles du crâne sur des CBCT orientés : mandibule, maxillaire, base du crâne, vertèbres cervicales,
voies aériennes supérieures, peau, ainsi que trois « masques » (CB/MAND/MAX) utilisés par AREG.
Le module Slicer (`AMASSS/AMASSS.py`) ne fait que collecter des paramètres et lancer le CLI `AMASSS_CLI`
(`slicer.modules.amasss_cli`, `AMASSS/AMASSS.py:1608-1616`), qui exécute une prédiction **nnUNet v2**
(`nnUNetv2_predict`, configuration `3d_fullres`, `fold 0`) par structure demandée et écrit les segmentations
(et éventuellement des surfaces `.vtk`) sur disque. Le même CLI est réutilisé par AREG
(`AREG/AREG_Method/CBCT.py:320-348`).

---

## Entrées

| Nom (UI / CLI) | Type | Extensions réellement acceptées | Obligatoire | Détails |
|---|---|---|---|---|
| `InputTypecomboBox` (modalité) | choix : `NIFTI, GIPL, NRRD` / `DICOM` / `Segmentation` | - | oui (défaut index 0) | `AMASSS/Resources/UI/AMASSS.ui:317-333`, logique `AMASSS/AMASSS.py:573-590` |
| `input_type_select` | choix : `File as input` / `Folder as input` | - | oui | `AMASSS.ui:336-347` ; masqué en mode DICOM (`AMASSS.py:581-588`) |
| `MRMLNodeComboBox_file` → `inputVolume` | nœud Slicer `vtkMRMLVolumeNode` | dépend du nœud ; le chemin disque du nœud est transmis | oui en mode fichier | `AMASSS.ui:350-359` ; le chemin est extrait du `StorageNode` (`AMASSS.py:194-200`, `643-653`) |
| `lineEditScanPath` / `SearchScanFolder` → `inputVolume` | dossier (QFileDialog `getExistingDirectory`) | comptage UI : `.nrrd`, `.nrrd.gz`, `.nii`, `.nii.gz`, `.gipl`, `.gipl.gz` (`AMASSS.py:655`, `675`, `679`) ; **traitement CLI** : `.nii`, `.nii.gz`, `.nrrd`, `.nrrd.gz` uniquement (`AMASSS_CLI/AMASSS_CLI.py:475`) | oui en mode dossier | scan **récursif** côté UI, **non récursif** côté CLI (voir plus bas) |
| `lineEditModelPath` / `SearchModelFolder` → `modelDirectory` | dossier de modèles IA | validation UI : présence d'au moins un `.pth` (`AMASSS.py:692`) ; usage réel : sous-dossiers `<CODE_STRUCTURE>/**/…__nnUNetPlans__3d_fullres/fold_0/checkpoint_final.pth` (`AMASSS_CLI.py:560-568`, `610-613`) | oui, sauf mode « Segmentation » (`AMASSS.py:870-873`) | forcé à `'/'` en mode Segmentation (`AMASSS.py:904`) |
| `smallFOVCheckBox` → `highDefinition` | booléen | - | non | change uniquement la liste de cases à cocher (`AMASSS.py:720-727`) ; **paramètre absent du XML du CLI** → sans effet réel |
| Table de structures (`LMTab`) → `skullStructure` | liste de codes texte séparés par `,` | codes : `MAND, MAX, CB, CV, UAW, SKIN, CBMASK, MANDMASK, MAXMASK` (FF) ou `MAND, MAX, TEETH, RC, MCAN` (small FOV) | oui (≥ 1 structure, `AMASSS.py:888-891`) | `GROUPS_FF_SEG`/`GROUPS_HD_SEG` `AMASSS.py:217-227` ; traduction `TRANSLATE` `AMASSS.py:233-246` ; `Teeth` et `Mandibular canal` désactivés (`UNAVAILABLE_MODELS`, `AMASSS.py:231`, `1492-1493`) |
| `OutputTypecomboBox` → `merge` | choix : `One segmentation file` / `Separated segmentations` / `Separated + Merged` → `"MERGE"` / `"SEPARATE"` / `"MERGE SEPARATE"` | - | oui (défaut `MERGE`) | `AMASSS.ui:561-577`, `AMASSS.py:796-807` ; re-splité en liste côté CLI (`AMASSS_CLI.py:820`) |
| `checkBoxSurfaceSelect` → `genVtk` | booléen (défaut décoché) | - | non | `AMASSS.ui:618-631` ; coche automatiquement `saveInFolder` (`AMASSS.py:786-788`) |
| `saveInFolder` → `save_in_folder` | booléen | - | non | `AMASSS.ui:691-695` ; valeur transmise = `saveInFolder OR checkBoxSurfaceSelect` (`AMASSS.py:909`) |
| `SavePredictCheckBox` (`Save in input folder`) | booléen (défaut coché) | - | non | `AMASSS.ui:634-644`, `AMASSS.py:730-778` |
| `SaveFolderLineEdit` / `SearchSaveFolder` → `output_folder` | dossier | - | obligatoire si « Save in input folder » décoché | `AMASSS.py:790-794`, `920` |
| `SaveId` → `prediction_ID` | texte libre (défaut `Pred`) | - | oui (utilisé dans tous les noms de sortie) | `AMASSS.ui:580-587` |
| `horizontalSliderSmoothing` / `spinBoxSmoothing` → `vtk_smooth` | entier 0–95 (défaut 5) | - | non | `AMASSS.ui:768-790`, `AMASSS.py:812-818` ; utilisé uniquement si `genVtk` |
| `temp_fold` | dossier temporaire | - | oui (créé automatiquement) | `Documents/<Slicer>_temp_AMASSS` (`AMASSS.py:931-941`) ; **effacé récursivement** au démarrage du CLI (`AMASSS_CLI.py:461`) |
| `SegmentInput` / `DCMInput` | booléens | - | transmis mais **jamais lus** dans `main()` (`AMASSS_CLI.py:827-828`) | |
| `CenterAllCheckBox`, `SaveAdjustedCheckBox` | booléens | - | non | **désactivés dans le `.ui`** (`enabled=false`, `AMASSS.ui:698-733`) et jamais transmis au CLI |

### Détails et références

**Mode fichier (nœud Slicer).** `onNodeChanged` (`AMASSS.py:643-653`) récupère le nœud sélectionné et en extrait
le **chemin disque** via le `StorageNode` (`PathFromNode`, `AMASSS.py:194-200`). Un volume créé en mémoire
(non sauvegardé, ou importé depuis DICOM dans Slicer) renvoie `None` : `input_path` vaut alors `None`,
`param["inputVolume"] = None`, et le CLI échoue au `os.path.exists` (`AMASSS_CLI.py:477-479`). Aucune conversion
de nœud vers fichier n'est faite.

**Comptage UI des scans.** `CountFileWithExtention` (`AMASSS.py:655-666`) parcourt le dossier avec
`glob.iglob(path/**/, recursive=True)` - donc **récursivement** - et retient les fichiers dont le *basename*
contient une des extensions, en excluant ceux contenant `"Seg"`, `"seg"` ou `"Pred"` (`AMASSS.py:655`).
Le test est un `in` sur la chaîne, pas un `endswith` : un fichier `patient.nii.gz.bak` serait compté.

**Structures → modèles.** Le CLI construit, pour chaque code de structure, le chemin
`modelDirectory/<CODE>` puis cherche `**/*__nnUNetPlans__3d_fullres` en récursif (`AMASSS_CLI.py:560-568`).
Le nom du dataset nnUNet est déduit du dossier parent (`AMASSS_CLI.py:599`) et `nnUNet_results` est positionné
dynamiquement (`AMASSS_CLI.py:600`). Un checkpoint `fold_0/checkpoint_final.pth` est exigé
(`AMASSS_CLI.py:610-613`). Si **aucune** structure n'a de modèle, le scan échoue ; si **certaines** manquent,
elles sont silencieusement ignorées (simple `logger.warning`, `AMASSS_CLI.py:562`, `571`).

**Argument `merge`.** L'UI envoie une chaîne (`"MERGE"`, `"SEPARATE"`, `"MERGE SEPARATE"`), le CLI la
re-découpe en liste avec `re.split(r'[, ]+', …)` (`AMASSS_CLI.py:820`) puis teste par appartenance
(`AMASSS_CLI.py:711`, `731`).

---

## Modèles IA

| Élément | Valeur |
|---|---|
| Bouton `Download latest models` | ouvre `https://github.com/DCBIA-OrthoLab/SlicerAutomatedDentalTools/releases/tag/AMASSS_CBCT` (`AMASSS.py:214`, `711-712`) |
| Archive réellement utilisée (via AREG) | `https://github.com/DCBIA-OrthoLab/SlicerAutomatedDentalTools/releases/download/AMASSS_CBCT/AMASSS_Models.zip` (`AREG/AREG_Method/CBCT.py:123`), décompressée en dossier `AMASSS_Models` (`AREG/AREG_Method/CBCT.py:323`) |
| Bouton `Download test scan` | `https://github.com/Maxlo24/AMASSS_CBCT/releases/download/v1.0.1/MG_test_scan.nii.gz` (`AMASSS.py:215`) |
| Téléchargement | **manuel et obligatoire** : aucun téléchargement automatique dans AMASSS ; le bouton ouvre juste un navigateur |
| Format | modèles **nnUNet v2** (`Dataset…/…__nnUNetPlans__3d_fullres/fold_0/checkpoint_final.pth`) |
| Modèles attendus (un par structure) | `MAND`, `MAX`, `CB`, `CV`, `UAW`, `SKIN`, `CBMASK`, `MANDMASK`, `MAXMASK` (`AMASSS_CLI.py:42-45`, `106-119`) |
| Dépendances Python installées à la volée | `torch 2.2.0`, `torchvision 0.17.0`, `torchaudio 2.2.0`, `itk`, `blosc2`, `dicom2nifti 2.3.0`, `pydicom 2.2.2`, `einops`, `nibabel`, `nnunetv2 2.8.0` (`AMASSS.py:833-837`) |

Remarque : `onDownloadButton` utilise `subprocess.Popen(['firefox'|'xdg-open', url])` (`AMASSS.py:700-715`) - 
code **spécifique à Linux**, alors que le module `webbrowser` est importé (`AMASSS.py:22`) mais jamais utilisé.
Sous Windows/macOS le bouton ne fait rien.

---

## Sorties

| Fichier | Format | Nommage | Condition |
|---|---|---|---|
| Segmentation séparée | même extension que l'entrée (`.nii`, `.nii.gz`, `.nrrd`, `.nrrd.gz`) | `{base}_{prediction_ID}_{CODE}{ext}` (`AMASSS_CLI.py:716`) | mode `SEPARATE`, **ou** si une seule structure prédite (`AMASSS_CLI.py:711`) |
| Segmentation fusionnée | même extension que l'entrée | `{base}_{prediction_ID}_MERGED{ext}` (`AMASSS_CLI.py:744`) | mode `MERGE` **et** ≥ 2 structures prédites (`AMASSS_CLI.py:731`) |
| Surface séparée | `.vtk` (polydata legacy, avec couleurs par cellule) | `{base}_{prediction_ID}_{CODE}.vtk` (`AMASSS_CLI.py:264-266`) | `genVtk = true` |
| Surface fusionnée | `.vtk` | `{base}_{prediction_ID}_MERGED.vtk` (`AMASSS_CLI.py:240-247`) | `genVtk = true` et mode merge |
| Dossier de regroupement | dossier | `{base}_{prediction_ID}_SegOut/` (`AMASSS_CLI.py:534-538`) | `save_in_folder = true` (donc systématiquement dès que `genVtk`) |
| Fichiers temporaires | `p_{NNN}_0000.nii.gz`, `pred_{CODE}/p_{NNN}.nii.gz`, `tmp.nii.gz`, `temp.nrrd` | dans `temp_fold` | supprimés après chaque scan (`AMASSS_CLI.py:762-763`) |

### Cardinalité entrée → sortie

Pour **N** scans en entrée et **S** structures cochées *dont le modèle est effectivement trouvé* :

| Mode `merge` | Segmentations écrites | Fichiers `.vtk` (si `genVtk`) |
|---|---|---|
| `MERGE` (« One segmentation file »), S ≥ 2 | **N × 1** (`_MERGED`) | N × 1 |
| `MERGE`, S = 1 | **N × 1** mais nommé `_{CODE}` et non `_MERGED` (`AMASSS_CLI.py:711`) | N × 1 |
| `SEPARATE` | **N × S** | N × S |
| `MERGE SEPARATE` | **N × (S+1)** | N × (S+1) |

Donc : 1 scan → 1 à S+1 fichiers de segmentation, et autant de `.vtk`. Le nombre de sorties dépend
directement du nombre de cases cochées et du mode choisi. Il peut être **inférieur** au nombre attendu si un
dossier de modèle est absent (structure ignorée sans erreur, `AMASSS_CLI.py:562`, `571`).

Le contenu du fichier fusionné est un volume de labels entiers construit dans l'ordre
`merging_order = ["SKIN","CV","UAW","CB","MAX","MAND","CAN","RC","CBMASK","MANDMASK","MAXMASK"]`
(`AMASSS_CLI.py:829`), avec les valeurs de `LABELS["LARGE"]` :
`MAND=1, CB=2, UAW=3, MAX=4, CV=5, SKIN=6, CBMASK=7, MANDMASK=8, MAXMASK=9` (`AMASSS_CLI.py:43`).
Les fichiers séparés sont binaires (0/1) : le masque est `arr > 0` (`AMASSS_CLI.py:688`), puis ré-échantillonné
sur la géométrie du scan d'origine et casté en `int16` (`AMASSS_CLI.py:290-314`, `399-405`).

**Chargement dans Slicer.** Les `.vtk` ne sont chargés automatiquement que si `self.vtk_output_folder`
est non nul, c'est-à-dire **uniquement** en entrée fichier unique + « Save in input folder » coché
(`AMASSS.py:912-924`, `1078-1114`). Les volumes de segmentation ne sont **jamais** rechargés dans la scène.
L'opacité est réduite à 0.1 pour la peau et à 0.2 pour mandibule/maxillaire si un « Root-canal » est présent
(`AMASSS.py:1101-1114`).

---

## Comportement dossier vs fichier

- **Fichier unique (nœud Slicer)** : `input_files = [input_path]` (`AMASSS_CLI.py:493`). L'extension n'est pas
  filtrée, seulement un `logger.warning` si elle est inattendue (`AMASSS_CLI.py:491-492`) - le fichier est
  traité quand même.
- **Dossier** : `os.listdir(input_path)` - **NON récursif** (`AMASSS_CLI.py:484`). Les sous-dossiers sont
  ignorés. Filtres appliqués : `f.lower().endswith((".nii",".nii.gz",".nrrd",".nrrd.gz"))` et exclusion des
  noms contenant la sous-chaîne `MASK` (sensible à la casse) (`AMASSS_CLI.py:486-488`).
- **Tous les fichiers sont traités**, pas un seul : boucle `for scan_idx, volume_file in enumerate(input_files)`
  (`AMASSS_CLI.py:514`). Un échec sur un scan est journalisé et la boucle continue, sauf sur le dernier scan où
  l'exception est propagée (`AMASSS_CLI.py:771-778`).
- **Divergence de comptage UI/CLI** : l'UI compte récursivement et exclut `Seg`/`seg`/`Pred`
  (`AMASSS.py:655-666`), le CLI liste à plat et n'exclut que `MASK`. Sur une arborescence à sous-dossiers,
  l'UI annonce N scans et le CLI n'en traite que ceux de la racine → la barre de progression et les compteurs
  « Scan ready for segmentation : x / N » (`AMASSS.py:1015-1025`) sont faux.
- **Mode DICOM** : l'UI compte `len(os.listdir(folder))` (`AMASSS.py:677`) et met le libellé « DICOM's Folder »,
  mais le CLI n'effectue **aucune conversion DICOM** (`dicom2nifti` est importé ligne 8 et jamais appelé,
  `isDCMInput` n'est jamais lu). Le dossier ne contenant pas de `.nii/.nrrd`, le CLI sort par `sys.exit(1)`
  (`AMASSS_CLI.py:496-499`).

---

## Incohérences et pièges observés dans le code

1. **`.gipl` / `.gipl.gz` annoncés mais rejetés.** Le combo indique « NIFTI, GIPL, NRRD » (`AMASSS.ui:320`),
   l'UI compte les `.gipl` (`AMASSS.py:655`, `679`) et le README les liste, mais le CLI n'accepte que
   `.nii/.nii.gz/.nrrd/.nrrd.gz` (`AMASSS_CLI.py:475`) : un dossier de GIPL est annoncé « N scans » puis
   traité comme vide (`sys.exit(1)`).
2. **Les `.nrrd` sont copiés sans conversion sous un nom `.nii.gz`.** `shutil.copy(volume_file,
   os.path.join(tmp, f"p_{case_id}_0000.nii.gz"))` (`AMASSS_CLI.py:546-548`) : le contenu NRRD est renommé en
   `.nii.gz` avant d'être donné à `nnUNetv2_predict`, qui lira le fichier selon son extension. En pratique
   seuls les NIfTI fonctionnent de façon fiable, alors que le NRRD est le format par défaut de Slicer.
3. **Mode « Segmentation » cassé.** Le combo propose « Segmentation » en entrée (`AMASSS.ui:328-332`) et l'UI
   force `modelDirectory = '/'` (`AMASSS.py:904`). Le CLI cherche alors `/MAND`, `/MAX`… , n'en trouve aucun et
   lève `FileNotFoundError("No nnUNet models found")` (`AMASSS_CLI.py:576-578`). L'ancienne fonction
   « segmentation existante → surface .vtk » n'existe plus dans le CLI. De plus, `isSegmentInputFunction(True)`
   retire le widget de sélection de structures de la mise en page (`AMASSS.py:601`) mais `seg_status_dic`
   conserve les anciennes valeurs, donc `GetSelected()` renvoie quand même des structures.
4. **`smallFOVCheckBox` sans effet.** `param["highDefinition"]` est construit (`AMASSS.py:905`) mais **ce
   paramètre n'existe pas dans `AMASSS_CLI.xml`** (12 paramètres indexés 0-11, aucun `highDefinition`) : il est
   silencieusement ignoré par `slicer.cli.run`. Côté CLI, tous les appels passent `"LARGE"` en dur
   (`AMASSS_CLI.py:720`, `748`) ; `MODELS_GROUP["SMALL"]` et `LABELS["SMALL"]` (`AMASSS_CLI.py:44`, `114-118`)
   sont du code mort. Cocher la case ne fait que changer la liste des cases affichées.
5. **`Root canal` (RC) fait planter la génération de surface.** RC est coché par défaut en mode small FOV
   (`DEFAULT_SELECT`, `AMASSS.py:229`) ; en mode séparé, `SavePredToVTK` fait
   `LABELS[model_size][struct]` avec `model_size="LARGE"` (`AMASSS_CLI.py:260`) → `KeyError: 'RC'`, exception
   propagée qui fait échouer tout le scan. En mode fusionné, `LABELS["LARGE"].get(struct, 1)`
   (`AMASSS_CLI.py:740`) attribue **le label 1 (= mandibule)** à RC, TEETH et MCAN : collision silencieuse.
6. **`model_size` non transmis.** `SaveSeg` reçoit un paramètre `model_size` mais ne le passe pas à
   `SavePredToVTK` (`AMASSS_CLI.py:438`), qui retombe donc toujours sur `"LARGE"`.
7. **`merging_order` contient `"CAN"` au lieu de `"MCAN"`** (`AMASSS_CLI.py:829`) : même si un modèle de canal
   mandibulaire existait, il ne serait jamais intégré au volume fusionné.
8. **Auto-chargement des `.vtk` quasi toujours vide.** Cocher « Generate surface file » force
   `saveInFolder = True` (`AMASSS.py:786-788`), donc le CLI écrit dans `.../{base}_{ID}_SegOut/`
   (`AMASSS_CLI.py:535`), alors que le widget scanne `self.vtk_output_folder` = le dossier **parent**
   (`AMASSS.py:914-915`, `1083-1085`) : il ne trouve aucun `.vtk`. Le README promet pourtant un chargement
   automatique en entrée fichier unique.
9. **Sorties écrites dans le dossier d'entrée par défaut**, et le CLI ne filtre que `MASK` : au **deuxième
   lancement** sur le même dossier, les sorties du premier run (`scan_Pred_MAND.nii.gz`, `…_MERGED.nii.gz`)
   sont ré-ingérées comme scans d'entrée (`AMASSS_CLI.py:486-488`), contrairement à l'UI qui les exclut via
   `Seg/seg/Pred`. Effet boule de neige garanti.
10. **Dossier de sortie vide non validé.** Si « Save in input folder » est décoché sans choisir de dossier,
    `output_folder = ""` (`AMASSS.py:920`) → `os.makedirs("")` lève une exception au premier scan
    (`AMASSS_CLI.py:538`). Aucune vérification côté UI (contrairement au dossier de scans et de modèles,
    `AMASSS.py:858-876`).
11. **Options « Center all » et « Save adjusted scan » mortes.** Les cases existent avec `enabled=false`
    (`AMASSS.ui:698-733`), les attributs `self.center_all` / `self.save_adjusted` sont initialisés
    (`AMASSS.py:306-307`) mais jamais transmis ni utilisés.
12. **Post-traitement absent.** `CorrectHisto` (`AMASSS_CLI.py:121`, qui ne corrige d'ailleurs plus rien - elle
    se contente d'un `Cast` en float32), `CleanArray` (`AMASSS_CLI.py:319`), `CropSkin` (`AMASSS_CLI.py:386`)
    et `Write` (`AMASSS_CLI.py:137`) ne sont **jamais appelées** : pas de nettoyage morphologique, pas de plus
    grande composante connexe, pas de « peau creuse ». Les sorties sont les masques bruts de nnUNet.
13. **Arrêt prématuré possible du prédicteur.** `wait_for_stable_output` (`AMASSS_CLI.py:52-104`, appelée avec
    `min_size_bytes=100`, `stable_checks=3`, `AMASSS_CLI.py:644-651`) tue le process nnUNet (`proc.terminate()`,
    `AMASSS_CLI.py:653-660`) dès que le fichier de sortie ne change plus pendant 3 secondes - heuristique
    fragile qui peut interrompre nnUNet pendant une écriture lente ou un post-traitement.
14. **Le dossier temporaire est supprimé récursivement au démarrage** (`shutil.rmtree(tmp)`,
    `AMASSS_CLI.py:461`). Il est fourni par l'appelant : un appel programmatique passant un dossier utile
    (AREG passe `Documents/Slicer_temp_AMASSS`) verrait son contenu effacé.
15. **Barres de progression jamais affichées.** `PredScanProgressBar` et `PredSegProgressBar` sont mises à
    `setVisible(False)` en dur (`AMASSS.py:1050-1054`) ; seuls les libellés texte évoluent.
16. **`UpdateRunBtn` référence `self.scan_ready`, attribut inexistant** (`AMASSS.py:984-985`) - la méthode
    n'est jamais appelée, mais le bouton « Run prediction » reste donc toujours actif, même sans entrée.
17. **`prediction_ID` incohérent** : le widget initialise `self.prediction_ID = "Seg_Pred"`
    (`AMASSS.py:304`) mais la valeur réellement envoyée est celle du `.ui`, `"Pred"` (`AMASSS.ui:585`,
    `AMASSS.py:928`).
18. **Filtrage par sous-chaîne et non par extension** : `CountFileWithExtention` teste `ext in basename`
    (`AMASSS.py:662`) - un dossier nommé `..._Pred_SegOut` ou un fichier `x.nii.gz.old` fausse le compte.
19. **Modèle non validé finement côté UI** : la présence d'un `.pth` quelconque suffit (`AMASSS.py:692`), alors
    que le CLI exige une arborescence nnUNet v2 précise ; l'utilisateur ne découvre l'erreur qu'après
    l'installation des paquets et le lancement.

---

## Avis - entrées/sorties à ajouter ou retirer

**À retirer / corriger en priorité**

- **Retirer le mode « Segmentation »** du combo d'entrée, ou réimplémenter la conversion segmentation → `.vtk`
  dans le CLI. En l'état c'est une entrée qui échoue systématiquement (point 3).
- **Retirer le mode « DICOM »** ou brancher réellement `dicom2nifti` dans le CLI (l'import est déjà là). Une
  modalité proposée qui termine en `sys.exit(1)` est pire qu'une absence d'option.
- **Retirer la case « Use small FOV models »** tant que les modèles HD ne sont pas supportés de bout en bout
  (paramètre absent du XML, `"LARGE"` en dur, `KeyError` sur RC). Sinon : ajouter `highDefinition` dans
  `AMASSS_CLI.xml`, propager `model_size` jusqu'à `SavePredToVTK`, et compléter `LABELS`/`LABEL_COLORS` pour
  `RC`/`TEETH`/`MCAN`.
- **Retirer « Center all » et « Save adjusted scan »** du `.ui` (désactivées et non implémentées) - ou les
  implémenter, `save_adjusted` étant utile pour tracer ce qui a réellement été donné au réseau.
- **Retirer `.gipl` des listes d'extensions de l'UI et du README**, ou l'ajouter côté CLI. La divergence
  actuelle est un piège direct pour l'utilisateur.

**À ajouter**

- **Sortie `.seg.nrrd` / segmentation Slicer chargée dans la scène.** Aujourd'hui le module produit des volumes
  de labels bruts que l'utilisateur doit réimporter à la main. Générer un `vtkMRMLSegmentationNode` (avec noms
  et couleurs de segments issus de `LABELS`/`LABEL_COLORS`) transformerait la sortie en résultat directement
  exploitable et éviterait la confusion entre masques binaires et volume fusionné.
- **Sortie « table de contrôle » (CSV/JSON) par lot** : scan traité, structures demandées, structures
  réellement prédites, structures ignorées faute de modèle, temps. Actuellement une structure sans modèle
  disparaît silencieusement du résultat (point 5 de la section précédente) - invisible dans un run de 200 scans.
- **Entrée : filtre d'exclusion des sorties précédentes côté CLI** (aligner sur l'UI : exclure `Pred`,
  `Seg`, l'ID de prédiction courant), et **option « scan récursif »** explicite, cohérente entre UI et CLI.
- **Entrée : accepter un nœud Slicer non sauvegardé** en l'écrivant dans le dossier temporaire avant l'appel
  CLI (aujourd'hui `PathFromNode` renvoie `None` et le run échoue sans message clair).
- **Entrée : chemin du dossier de sortie validé** (non vide, inscriptible) avant lancement, et **suffixe de
  sortie séparé du `prediction_ID`** pour éviter les collisions de re-run.
- **Conversion explicite du volume d'entrée en NIfTI** (SimpleITK read + write) au lieu du `shutil.copy` vers
  `p_XXX_0000.nii.gz` : c'est deux lignes et cela rend le support NRRD/GIPL réel plutôt que déclaratif.
