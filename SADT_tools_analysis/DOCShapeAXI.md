# DOCShapeAXI

> Analyse basée sur la lecture du code réel du dépôt SADT (clone analysé), pas du README.
> Chemins cités relatifs à la racine du dépôt : `DOCShapeAXI/` (module Slicer) et `DOCShapeAXI_CLI/` (CLI).
> Le code de la bibliothèque tierce `shapeaxi` a également été relu (env conda local
> `.../miniconda3/envs/shapeaxi/lib/python3.9/site-packages/shapeaxi/`) pour les points où le
> comportement d'entrée/sortie en dépend (lecture/écriture des surfaces, nommage des tableaux GradCAM).

## Rôle

DOCShapeAXI (« Dental Oral and Craniofacial Shape Analysis eXplainability and Interpretability ») est un
module de **classification / régression par deep learning de formes 3D surfaciques**, appliqué à trois
pathologies : condyles mandibulaires, obstruction des voies aériennes nasopharyngées, et fente alvéolaire
(cleft). Il produit en plus une **carte d'explicabilité GradCAM** peinte sur chaque surface.

Le flux est entièrement hors-Slicer-CLI classique : le widget (`DOCShapeAXI/DOCShapeAXI.py`) ne fait
qu'assembler des arguments puis lance, via conda (environnement `shapeaxi`, `DOCShapeAXI/DOCShapeAXI.py:801`),
un `python -m DOCShapeAXI_CLI` dans un thread (`DOCShapeAXI/DOCShapeAXI.py:859-867`, `:932-968`). Sur Windows
tout passe par WSL. Le fichier `DOCShapeAXI_CLI/DOCShapeAXI_CLI.xml` existe mais n'est **pas** utilisé par
`slicer.cli.run` : le CLI est appelé comme un module Python, les 8 paramètres étant positionnels
(`DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:296-306`).

Le CLI enchaîne systématiquement deux étapes : `saxi_predict` puis `saxi_gradcam`
(`DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:286-291`). L'explicabilité n'est pas optionnelle.

## Entrées

| Entrée (widget) | Type | Extensions réellement acceptées | Où c'est défini / vérifié |
|---|---|---|---|
| `dataTypeComboBox` (« Data Type ») | liste fermée de 3 valeurs | - | items : `DOCShapeAXI/Resources/UI/DOCShapeAXI.ui:350-366` ; lu `DOCShapeAXI/DOCShapeAXI.py:448-449` |
| `mountPointLineEdit` (« Input folder ») | **dossier uniquement** (jamais un fichier) | **`.vtk` seulement** | dialogue dossier : `DOCShapeAXI/DOCShapeAXI.py:439-443` ; validation `os.path.isdir` : `:484` ; filtre `.vtk` : `:990` et `DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:110` |
| `outputLineEdit` (« Output directory ») | dossier | - | `DOCShapeAXI/DOCShapeAXI.py:455-464` ; validation `os.path.isdir` : `:471-476` |
| `checkBoxLatestModel` (« Use the latest version on Github ») | case à cocher, **désactivée** (`enabled=false`) et jamais connectée en Python | - | `DOCShapeAXI/Resources/UI/DOCShapeAXI.ui:392-407` ; aucune occurrence dans `DOCShapeAXI/DOCShapeAXI.py` |

Aucune autre entrée : pas de nœud MRML, pas de sélection de fichier unique, pas de paramètre de batch,
de device, de seuil ou de nombre de workers exposé à l'utilisateur.

Détails importants :

- **Extensions** : le seul format d'entrée réellement traité est **`.vtk`**. Le filtre est écrit deux fois,
  de façon cohérente : côté widget pour compter les sujets (`DOCShapeAXI/DOCShapeAXI.py:988-991`,
  `if ext == '.vtk'`) et côté CLI pour construire le manifeste CSV
  (`DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:110`, `if os.path.splitext(surf)[1] == '.vtk'`). Un `.stl`, `.obj`,
  `.vtp` ou `.off` placé dans le dossier est **silencieusement ignoré** (aucun warning : le `logger.warning`
  de `:112` ne se déclenche que pour un `.vtk` disparu entre le `listdir` et le test, cas quasi impossible).
  La comparaison est sensible à la casse : un fichier `.VTK` est ignoré.
  À noter : la bibliothèque sous-jacente saurait lire `.vtk`, `.vtp`, `.stl`, `.off`, `.obj`
  (`shapeaxi/utils.py:254-284`, fonction `ReadSurf`) - la restriction vient uniquement de SADT.
- **Pas de scan récursif** : `os.listdir(surf_dir)` (`DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:108`) et
  `os.listdir(self.input_dir)` (`DOCShapeAXI/DOCShapeAXI.py:988`). Seul le premier niveau du dossier est lu ;
  les sous-dossiers sont ignorés. L'ordre est celui de `listdir`, donc **non trié et non déterministe**.
- **Types de classification disponibles** (3 items d'UI, mappés vers 5 modèles) - `DOCShapeAXI/DOCShapeAXI.py:1015-1042`
  et boucle de tâches `:627-658` :

  | Data Type (UI) | Tâche(s) lancée(s) | Modèle | `nn` | `num_classes` |
  |---|---|---|---|---|
  | Mandibular Condyle | `severity` | `condyles_4_class` | `SaxiMHAFBClassification` | 4 |
  | Nasopharynx Airway Obstruction | `binary`, puis `severity`, puis `regression` (3 exécutions du CLI) | `airways_2_class`, `airways_4_class`, `airways_4_regress` | `SaxiMHAFBClassification` ×2, `SaxiMHAFBRegression` ×1 | 2, 4, 1 |
  | Alveolar Bone Defect in Cleft | `severity` | `clefts_4_class` | `SaxiMHAFBClassification` | 4 |

  Le choix de la branche se fait par un test sur les **mots** du libellé de la combo
  (`'Condyle' in self.data_type.split(' ')`, `DOCShapeAXI/DOCShapeAXI.py:1016, 1020, 1035`, et
  `'Airway' in ...` au `:627`) : renommer un item de l'UI casse le mapping.
- **Modèles téléchargés** : le CLI récupère d'abord le JSON de description **en ligne** (jamais le fichier
  local `DOCShapeAXI_CLI/model_path.json`) à l'URL
  `https://raw.githubusercontent.com/DCBIA-OrthoLab/SlicerAutomatedDentalTools/refs/heads/main/DOCShapeAXI_CLI/model_path.json`
  (`DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:118-123`), puis télécharge le `.ckpt` correspondant. URLs des poids
  (`DOCShapeAXI_CLI/model_path.json:2-26`), toutes sur la release GitHub `shapeaxi-ckpt-v1` :
  `airways_2_class.ckpt`, `airways_4_class.ckpt`, `airways_4_regress.ckpt`, `cleft_4_class.ckpt`,
  `condyles_4_class.ckpt`.
- **Dépendances installées à la volée** : environnement conda `shapeaxi` en Python 3.12 avec
  `ocnn==2.2.1` et `shapeaxi==1.0.10` (`DOCShapeAXI/DOCShapeAXI.py:838-839`), puis `pytorch3d`
  via `DOCShapeAXI/DOCShapeAXI_utils/install_pytorch.py:26` (roue précompilée fbaipublicfiles, **CUDA
  obligatoire** : `torch.version.cuda.replace(...)` plante en CPU-only). Sous Windows, WSL + libs
  `libxrender1`/`libgl1` sont vérifiés (`DOCShapeAXI/DOCShapeAXI.py:869-883`).
- **Entrées implicites non exposées** : le device est choisi automatiquement
  (`cuda` si disponible, sinon `cpu` - `DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:264`) ; `batch_size` est figé
  à 1 (`:210`, `:144`) ; `num_workers=4` pour l'explicabilité (`:144`).

## Sorties

Tout est écrit **à plat dans le dossier de sortie** choisi par l'utilisateur, sauf les surfaces
d'explicabilité qui vont dans un sous-arbre.

| Sortie | Format | Nommage | Cardinalité | Où c'est écrit |
|---|---|---|---|---|
| Manifeste d'entrée | CSV (1 colonne `surf`, valeurs = **noms de fichiers**, pas chemins absolus) | `files_<data_type>.csv` | 1 fichier, N lignes (N = nb de `.vtk`) | `DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:257-259` (en-tête) et `:102-115` (lignes) ; chemin construit `:267` |
| Poids du réseau | `.ckpt` PyTorch Lightning | `<model>.ckpt` (ex. `condyles_4_class.ckpt`) | 1 par modèle utilisé → **1** (condyle/cleft) ou **3** (airway) | `DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:275-280` |
| Prédictions | CSV | `files_<data_type>_prediction.csv` | **1 seul fichier**, N lignes, **1 colonne ajoutée par tâche** | `DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:240-245` |
| Surfaces d'explicabilité | `.vtk` (VTK legacy, écrit par `utils.WriteSurf`) | `<output_dir>/explainability/<task>/<nom_du_fichier_d_entrée>.vtk` | N par tâche → **N** (condyle/cleft) ou **3×N** (airway) | `DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:150-152`, `:182-183` |
| Journal de progression | texte 1 ligne, CSV inline `task,étape,index,num_classes` | `process.log` **dans le dossier d'installation du module** | 1, réécrit en continu (`w+`) | créé `DOCShapeAXI/DOCShapeAXI.py:810-816` ; écrit `DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:193-194, 234-235, 128-129, 185-186` |

Nommage, cardinalité et variations :

- **Le nom des CSV contient le libellé d'UI complet, espaces compris** : `files_Mandibular Condyle.csv`,
  `files_Nasopharynx Airway Obstruction_prediction.csv`, etc. (`DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:267`,
  `:240`). C'est le seul « suffixe » configurable - indirectement, via le type de données.
- **Colonnes de prédiction** : la colonne s'appelle `<task>_prediction`
  (`DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:244`). Donc :
  - Condyle / Cleft → CSV à 2 colonnes : `surf`, `severity_prediction` (entiers 0-3, issus d'un
    `argmax` après softmax, `:229-231`).
  - Airway → **un seul** CSV à 4 colonnes : `surf`, `binary_prediction` (0/1),
    `severity_prediction` (0-3), `regression_prediction` (**flottant**, pas d'argmax car
    `args.nn == 'SaxiMHAFBRegression'`, `:229`). L'accumulation se fait parce que le CLI relit le CSV
    de sortie s'il existe déjà avant d'y ajouter la nouvelle colonne (`:241-242`).
- **Arbre d'explicabilité** : `explainability/binary/`, `explainability/severity/`,
  `explainability/regression/` pour l'airway ; uniquement `explainability/severity/` pour condyle et cleft
  (`DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:150`). Le README parle d'un dossier « Explainability » avec majuscule,
  le code écrit `explainability` en minuscules.
- **Contenu des surfaces de sortie** : la surface d'entrée est recopiée avec, en `PointData`, un tableau
  scalaire par classe. Le nom du tableau vient de `shapeaxi/saxi_gradcam.py:137-142` :
  `grad_cam_target_class_<i>` quand `num_classes > 1`, sinon `grad_cam_max`. Donc **4 tableaux** pour
  condyle/cleft/airway-severity, **2** pour airway-binary, **1** (`grad_cam_max`) pour airway-regression.
  Chaque tableau est lissé par `psp.MedianFilter` (`DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:180`).
  Le fichier est réécrit à chaque itération de classe (`:182-183` est **dans** la boucle `for class_idx`),
  soit `num_classes` écritures pour un seul résultat final - coûteux mais correct.
- **Total pour N formes** : condyle ou cleft → 1 CSV manifeste + 1 CSV prédiction (N lignes) + 1 `.ckpt`
  + N `.vtk`. Airway → 1 CSV manifeste + 1 CSV prédiction (N lignes, 3 colonnes de prédiction)
  + 3 `.ckpt` + 3N `.vtk`.
- **Aucune sortie n'est chargée dans la scène Slicer** : ni les prédictions ni les surfaces GradCAM.
  L'utilisateur doit ouvrir les fichiers manuellement (procédure décrite dans `README.md:631-647`).

## Comportement dossier vs fichier

**Il n'existe aucun mode « fichier unique »**. C'est cohérent de bout en bout :

- Le bouton d'entrée ouvre un `QFileDialog.getExistingDirectory` (`DOCShapeAXI/DOCShapeAXI.py:440`),
  libellé « Select a folder containing vtk files ».
- La validation exige `os.path.isdir(self.logic.input_dir)` (`DOCShapeAXI/DOCShapeAXI.py:484`) : un chemin
  vers un `.vtk` est refusé avec « input file : Incorrect path » - message trompeur, il parle de « file »
  alors qu'il teste un dossier.
- Le CLI fait `os.listdir(args.input_dir)` sans garde (`DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:108`) : un chemin
  de fichier lèverait `NotADirectoryError`.
- Le champ texte reste éditable à la main, donc rien n'empêche de coller un chemin de fichier ; il sera
  rejeté par `check_input_parameters` avant lancement.
- Le scan est **non récursif** et **non trié** (voir Entrées). Le dossier d'entrée sert aussi de
  `mount_point` au dataset (`DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:142, 207`), puisque le CSV ne stocke que
  des noms de fichiers.
- Le dossier de sortie doit **exister** avant lancement : la validation widget le vérifie
  (`DOCShapeAXI/DOCShapeAXI.py:471`), et le CLI ne le crée jamais (voir Incohérences).

## Incohérences et pièges observés dans le code

1. **`checkBoxLatestModel` : widget mort.** Présent dans l'UI (« Use the latest version on Github »,
   `DOCShapeAXI/Resources/UI/DOCShapeAXI.ui:392-407`), coché par défaut mais `enabled=false`, et **aucune
   référence** dans le Python. Le comportement réel est figé : on télécharge toujours le modèle listé dans
   le JSON de la branche `main` de GitHub.
2. **Le `model_path.json` livré n'est jamais lu.** `download_model` va chercher le JSON en ligne
   (`DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:118-120`), donc la version installée localement peut diverger.
   Conséquences : (a) toute première exécution dépend de la disponibilité de GitHub (le téléchargement est
   bien sauté si le `.ckpt` est déjà présent, `:278`, mais le JSON, lui, n'est jamais mis en cache) ;
   (b) aucune gestion d'erreur réseau (`requests.get` sans `raise_for_status`, `json.loads` direct) : une
   panne renvoie une exception brute ou un `KeyError` sur le nom de modèle.
3. **Modèle non téléchargé si le dossier de sortie n'existe pas.** `if os.path.exists(args.output_dir):`
   (`DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:277`) enveloppe le téléchargement ; si le dossier manque, le CLI
   n'échoue pas là mais plus loin, sur `load_from_checkpoint` d'un fichier inexistant. Le dossier de sortie
   n'est jamais créé (`os.makedirs` n'existe que pour `explainability/`, `:151-152`).
4. **Le manifeste CSV est réutilisé s'il existe déjà** (`if not os.path.exists(args.input_csv)`,
   `DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:282-284`). Deuxième exécution avec le **même dossier de sortie** et
   le **même type de données** mais un **autre dossier d'entrée** → l'ancien `files_<data_type>.csv` est
   réutilisé tel quel, donc on prédit sur l'ancienne liste de sujets. Piège majeur pour un usage batch.
5. **Le CSV de prédiction est également recyclé** : `if os.path.exists(out_name): df = pd.read_csv(out_name)`
   (`DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:241-242`). C'est voulu pour accumuler les 3 colonnes de l'airway,
   mais le `df` rechargé **remplace** celui qui a servi à l'inférence : si l'ancien CSV a un ordre ou un
   nombre de lignes différents, les prédictions sont collées sur les mauvaises lignes (ou pandas lève une
   erreur de longueur). Aucun contrôle de correspondance.
6. **Nom de colonne `surf` codé en dur vs `model.hparams.surf_column`.** Le CSV est créé avec l'en-tête
   `surf` (`DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:259`) mais le dataset lit la colonne
   `model.hparams.surf_column` (`:143`, `:207`). Si un futur checkpoint est entraîné avec un autre nom de
   colonne, l'inférence plante par `KeyError` sans message explicite.
7. **`gradcam_save` est du code mort et cassé** : la fonction (`DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:62-82`)
   appelle `shutil.copy` alors que `shutil` **n'est jamais importé** (imports `:1-26`). Elle n'est appelée
   nulle part, donc l'erreur est latente. Idem pour les classes `MultiHead` et `SelfAttention` (`:84-100`)
   et l'import `subprocess` (`:7`), tous inutilisés.
8. **`linux2windows_path` fait exactement l'inverse de son nom** : elle convertit `C:/x` en `/mnt/c/x`,
   c'est-à-dire Windows → Linux (`DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:247-255`). Le module contient déjà
   `windows_to_linux_path` (`DOCShapeAXI/DOCShapeAXI.py:912-924`) qui fait la même chose sous le bon nom.
9. **Décalage d'indice dans la barre de progression** : la prédiction journalise `idx+1`
   (`DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:235`) et l'explicabilité journalise `idx`
   (`:186`), donc la seconde phase affiche toujours un sujet de retard et ne finit jamais à 100 %.
10. **Division par zéro si le dossier ne contient aucun `.vtk`** : `progressbar_value = round(progress /
    self.nbSubjects * 100, 2)` (`DOCShapeAXI/DOCShapeAXI.py:712`) avec `nbSubjects = 0`
    (`:986-991`). Rien ne prévient l'utilisateur qu'un dossier ne contient aucune forme exploitable.
11. **`self.elapsed_time` peut ne pas exister** : il n'est affecté que dans `update_ui_time` et seulement si
    plus de 0,3 s se sont écoulées (`DOCShapeAXI/DOCShapeAXI.py:604-611`) ; `onProcessCompleted` le lit
    inconditionnellement (`:741`) → `AttributeError` sur un échec immédiat du CLI. Dans le même esprit,
    `update_ui_time` renvoie `None` la plupart du temps, d'où l'affichage « time : None » dans l'UI (`:642`).
12. **`process.log` est écrit dans le dossier d'installation du module**
    (`DOCShapeAXI/DOCShapeAXI.py:811`, `os.path.dirname(__file__)`), pas dans un répertoire temporaire ni
    dans la sortie. En installation système en lecture seule, l'ouverture en écriture du `:816` échoue dès
    l'instanciation de la logique. Le fichier est d'ailleurs versionné dans le dépôt.
13. **Validation d'entrée redondante et message erroné** : `if not(os.path.isdir(...)): if not(os.path.isdir(...)):`
    (`DOCShapeAXI/DOCShapeAXI.py:471-472`) - la branche `else: msg.setText('Unknown error.')` est
    inatteignable. Et le message d'erreur d'entrée dit « input file » pour un dossier (`:485`).
14. **Aucune vérification que le dossier d'entrée contient bien des formes du bon type** : rien n'empêche de
    lancer le modèle « condyle » sur des voies aériennes ; la sortie sera silencieusement absurde.
15. **Incohérence de nommage du checkpoint cleft** : la clé JSON est `clefts_4_class` mais l'URL pointe sur
    `cleft_4_class.ckpt` (`DOCShapeAXI_CLI/model_path.json:18-21`) ; le fichier local est enregistré sous
    `clefts_4_class.ckpt` (`DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:275`). Sans conséquence fonctionnelle, mais
    source de confusion au débogage.
16. **`DOCShapeAXI_CLI.xml` inutilisé et incohérent** : il déclare `num_classes` comme `<string>`
    (`DOCShapeAXI_CLI/DOCShapeAXI_CLI.xml:54-59`) alors que l'argparse attend un `int`
    (`DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:303`) ; de toute façon le module n'est pas lancé via
    `slicer.cli.run`. Le descripteur donne l'illusion d'un CLI Slicer réutilisable qui ne l'est pas.
17. **`args.target_class` est calculé mais non utilisé pour l'attribution** : `mv_cam.attribute(...,
    target=class_idx)` (`DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:172`) alors que `args.target_class` est
    positionné juste au-dessus (`:168-171`). Il ne sert en réalité qu'à nommer le tableau de sortie via
    `gradcam_process`. Fonctionne, mais le couplage est fragile.
18. **`find_model_name` peut renvoyer `(None, None)`** (`DOCShapeAXI/DOCShapeAXI.py:1039-1041`) : le
    `str(self.num_classes)` du `:1004` produit alors la chaîne `"None"` que l'argparse `type=int` rejettera
    avec une erreur obscure. Cas atteignable uniquement si l'on modifie les libellés de la combo, puisque le
    mapping repose sur des mots-clés extraits du texte de l'UI (`DOCShapeAXI/DOCShapeAXI.py:1016, 1020, 1035`).

## Avis - entrées/sorties à ajouter ou retirer

**À ajouter en entrée**

- **Support d'autres extensions de surface** (`.vtp`, `.stl`, `.obj`, `.off`) : la couche `shapeaxi` sait
  déjà les lire (`shapeaxi/utils.py:254-284`). Il suffit d'élargir le filtre de
  `DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:110` et `DOCShapeAXI/DOCShapeAXI.py:990` à une liste commune, avec
  comparaison insensible à la casse. Attention : `WriteSurf` ne gère que `.vtk` et `.stl`
  (`shapeaxi/utils.py:341-354`), et un `.stl` de sortie **perdrait les tableaux GradCAM** - il faut donc
  forcer l'extension de sortie à `.vtk` quelle que soit celle de l'entrée.
- **Sélection fichier unique ou nœud MRML**, à la manière des autres modules SADT : pour tester un cas
  isolé, l'obligation de créer un dossier est pénible.
- **Case « scan récursif »** (ou récursif par défaut) : les jeux de données cliniques sont presque toujours
  organisés par patient.
- **Case « explicabilité »** : GradCAM est actuellement obligatoire et représente l'essentiel du temps de
  calcul et de l'espace disque (N ou 3N surfaces). Beaucoup d'usages ne veulent que le CSV.
- **Sélection des tâches pour l'airway** : imposer les 3 (binaire + sévérité + régression,
  `DOCShapeAXI/DOCShapeAXI.py:627-628`) triple le temps de calcul même quand une seule sortie est utile.
- **Un suffixe / préfixe de sortie**, ou au minimum une normalisation du nom de fichier : `files_Nasopharynx
  Airway Obstruction_prediction.csv` contient des espaces et n'identifie pas la session.
- **Réactiver ou supprimer `checkBoxLatestModel`** : soit on l'implémente (choix entre modèle mis en cache et
  dernière version GitHub), soit on retire la case et le libellé « Model » qui l'accompagne
  (`DOCShapeAXI/Resources/UI/DOCShapeAXI.ui:385-407`).
- **Un chemin de modèle local optionnel** : indispensable pour un usage hors ligne ou pour évaluer un
  checkpoint réentraîné.

**À ajouter en sortie**

- **Les probabilités / scores par classe**, pas seulement l'`argmax` (`DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:229-231`).
  Le softmax est calculé puis jeté ; le conserver donnerait une mesure de confiance, essentielle en clinique.
- **Le chemin absolu de la surface** dans le CSV de prédiction : aujourd'hui seule la colonne `surf`
  (nom de fichier) existe (`:259`), le CSV n'est donc pas exploitable hors de son `mount_point`.
  Le README annonce d'ailleurs « the path of each .vtk file » (`DOCShapeAXI/DOCShapeAXI.py:63-64`),
  ce qui est inexact.
- **Le chargement automatique des résultats dans Slicer** (au moins la première surface GradCAM avec le
  bon scalaire actif et la table de couleurs `ColdToHotRainbow`), plutôt que la procédure manuelle en
  6 étapes du README.
- **Un fichier de métadonnées de run** (JSON : modèle, version du `.ckpt`, date, device, nombre de sujets,
  fichiers ignorés) : rien ne permet aujourd'hui de savoir avec quels poids un CSV a été produit.
- **Une liste explicite des fichiers ignorés** (extensions non gérées) affichée dans l'UI.

**À retirer / déplacer**

- **Le `.ckpt` téléchargé dans le dossier de sortie** (`DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:275-280`) :
  c'est un artefact de cache (plusieurs centaines de Mo, ×3 pour l'airway) qui pollue les résultats et est
  re-téléchargé pour chaque nouveau dossier de sortie. Il devrait aller dans un cache utilisateur partagé
  (type `Documents/SlicerDownloads/`, comme fait AutoMatrix).
- **`process.log` dans le dossier du module** (`DOCShapeAXI/DOCShapeAXI.py:811`) : à déplacer vers un
  répertoire temporaire, et à retirer du dépôt Git.
- **Le manifeste `files_<data_type>.csv`** en tant que sortie visible : c'est un intermédiaire technique ;
  le laisser dans le dossier de sortie est ce qui crée le piège de réutilisation (n°4). À générer dans un
  temporaire, ou à régénérer systématiquement.
- **`DOCShapeAXI_CLI/DOCShapeAXI_CLI.xml`** : soit on passe réellement par `slicer.cli.run`, soit on
  supprime ce descripteur qui décrit une interface non utilisée.
- **Le code mort** : `gradcam_save`, `MultiHead`, `SelfAttention` et l'import `subprocess`
  (`DOCShapeAXI_CLI/DOCShapeAXI_CLI.py:7, 62-82, 84-100`).
