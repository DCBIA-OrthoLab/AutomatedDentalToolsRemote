# AutoMatrix

> Analyse basée sur la lecture du code source (et non du README) du dépôt `SlicerAutomatedDentalTools`.
> Fichiers analysés : `AutoMatrix/AutoMatrix.py`, `AutoMatrix/Resources/UI/AutoMatrix.ui`,
> `AutoMatrix/AutoMatrix_Method/{applyMatrix,General_tools,Method,Progress}.py`,
> `Automatrix_CLI/{Automatrix_CLI.py,Automatrix_CLI.xml,CMakeLists.txt}`.

## Rôle

AutoMatrix applique **en batch** des matrices de transformation (transformées ITK) à des données
dentaires : volumes CBCT, segmentations et fichiers de landmarks. Le module Slicer n'est qu'une
enveloppe GUI : il valide les chemins, construit un dictionnaire de paramètres puis lance **un
unique** processus CLI (`Automatrix_CLI`) via `slicer.cli.run`.

- Le pipeline complet est : `AutoMatrixWidget.onApplyButton` (`AutoMatrix/AutoMatrix.py:743`)
  → `onPredictButton` (`AutoMatrix/AutoMatrix.py:760`)
  → `Automatrix_Method.Process` (`AutoMatrix/AutoMatrix_Method/applyMatrix.py:64`)
  → `slicer.modules.automatrix_cli` (`AutoMatrix/AutoMatrix_Method/applyMatrix.py:84`)
  → `main()` du CLI (`Automatrix_CLI/Automatrix_CLI.py:225`).
- Toute la logique métier réelle (appariement, resampling, écriture) est dans le CLI ; la classe
  `AutoMatrixLogic.process()` est un `pass` vide (`AutoMatrix/AutoMatrix.py:1094-1099`).
- Les transformées sont appliquées avec **SimpleITK uniquement** (`sitk.ReadTransform`,
  `sitk.ResampleImageFilter`) : `Automatrix_CLI/Automatrix_CLI.py:207-223`, `:285`.
  Aucun code VTK n'est présent dans le CLI (les seuls imports sont `argparse, json, glob, sys, os,
  time, SimpleITK` — `Automatrix_CLI/Automatrix_CLI.py:1-6`).

## Entrées

| Entrée (widget) | Type | Extensions acceptées (validation UI) | Extensions réellement scannées (CLI) | Fichier:ligne |
|---|---|---|---|---|
| `LineEditPatient` + `ComboBoxPatient` | Fichier **ou** dossier (au choix) | `.vtk .vtp .stl .off .obj .nii.gz .nrrd .mrk.json` | `.vtk .vtp .stl .off .obj .nii .nii.gz .nrrd .mrk.json` | UI : `AutoMatrix/AutoMatrix.py:1012` et `:1023` — CLI : `Automatrix_CLI/Automatrix_CLI.py:72`, `:123` |
| `LineEditMatrix` + `ComboBoxMatrix` | Fichier **ou** dossier | `.npy .h5 .tfm .mat .txt` | `.npy .h5 .tfm .mat .txt` | UI : `AutoMatrix/AutoMatrix.py:1035-1043` — CLI : `Automatrix_CLI/Automatrix_CLI.py:137` |
| `LineEditReference` | Fichier unique (image) | aucune validation | lu par `sitk.ReadImage` | `AutoMatrix/Resources/UI/AutoMatrix.ui:254-259`, `Automatrix_CLI/Automatrix_CLI.py:236-241` |
| `LineEditOutput` | Dossier | — | créé par `os.makedirs` | `AutoMatrix/AutoMatrix.py:426-428`, `AutoMatrix/AutoMatrix_Method/applyMatrix.py:68` |
| `LineEditSuffix` | Chaîne (défaut `_apply`) | — | concaténée au nom de sortie | `AutoMatrix/Resources/UI/AutoMatrix.ui:322-328`, `Automatrix_CLI/Automatrix_CLI.py:291` |
| `checkBoxMatrixName` | Booléen (défaut **coché**) | — | ajoute `_<stem de la matrice>` | `AutoMatrix/Resources/UI/AutoMatrix.ui:336-345`, `Automatrix_CLI/Automatrix_CLI.py:290` |
| `CheckBoxSegmentation` (`is_seg`) | Booléen | — | interpolateur NearestNeighbor au lieu de Linear | `AutoMatrix/Resources/UI/AutoMatrix.ui:268-275`, `Automatrix_CLI/Automatrix_CLI.py:210` |
| `CheckBoxMirror` | Booléen | — | télécharge et impose une matrice miroir | `AutoMatrix/AutoMatrix.py:304-324`, `:381-402` |
| `CheckBoxSuffixBased` (« From AReg ») | Booléen | — | mode d'appariement alternatif — **masqué dans l'UI** | `AutoMatrix/AutoMatrix.py:296`, `Automatrix_CLI/Automatrix_CLI.py:259-279` |

Aucune entrée n'est un **nœud MRML** : tout passe par des chemins texte (`QLineEdit`). Les
sélecteurs `qMRMLNodeComboBox` référencés dans `updateParameterNodeFromGUI`
(`AutoMatrix/AutoMatrix.py:733-737` : `inputSelector`, `outputSelector`, `imageThresholdSliderWidget`…)
n'existent pas dans le `.ui` — ce sont des restes du template Slicer, jamais appelés.

**Détail des données patients.** Le sélecteur de fichier est ouvert par `openFinder`
(`AutoMatrix/AutoMatrix.py:405-432`) : `getExistingDirectory` si `ComboBoxPatient.currentIndex==1`
(« Folder »), `getOpenFileName` sinon (`:419-424`). Aucun filtre d'extension n'est passé au dialogue,
donc l'utilisateur peut sélectionner n'importe quoi ; la validation n'a lieu qu'ensuite dans
`CheckGoodEntre` (`AutoMatrix/AutoMatrix.py:996-1050`).

**Détail des matrices.** Formats déclarés : `.npy`, `.h5`, `.tfm`, `.mat`, `.txt`
(`AutoMatrix/AutoMatrix.py:1035-1043`). Le CLI lit chaque matrice avec `sitk.ReadTransform(matrix)`
(`Automatrix_CLI/Automatrix_CLI.py:285`) : `.tfm`, `.h5`, `.mat` et `.txt` sont des formats de
transformée ITK valides, **`.npy` ne l'est pas** — la lecture lèvera une exception attrapée et
loguée en `ERROR` puis le fichier sera ignoré (`:286-288`).

**Scan récursif.** La fonction `search` utilise
`glob.iglob(os.path.normpath("/".join([path, "**", "*"])), recursive=True)` — le scan est donc
**récursif** dans toute l'arborescence, aussi bien pour les patients que pour les matrices :
`AutoMatrix/AutoMatrix_Method/General_tools.py:39-48` et son doublon
`Automatrix_CLI/Automatrix_CLI.py:48-57`.

**Fichier de référence.** Optionnel : la valeur par défaut du champ est la chaîne littérale `"None"`
(`AutoMatrix/Resources/UI/AutoMatrix.ui:256-258`) et le CLI teste explicitement
`args.reference_file != "None"` (`Automatrix_CLI/Automatrix_CLI.py:236`). S'il est fourni et lisible,
il définit la **grille de sortie** (taille/spacing/direction/origine) de tous les volumes
rééchantillonnés (`:213-214`). Sinon chaque scan sert de sa propre référence (`:306`).

**Mode Mirror.** Cocher `CheckBoxMirror` désactive tous les widgets de matrice et de référence,
force `ComboBoxMatrix` sur « File », met le suffixe à `_mir`, **décoche** `checkBoxMatrixName`, puis
télécharge une archive externe (`AutoMatrix/AutoMatrix.py:304-324`). L'URL est en dur :
`https://github.com/GaelleLeroux/DCBIA_Apply_matrix/releases/download/AutoMatrixMirror/Mirror.zip`
(`AutoMatrix/AutoMatrix.py:382`), décompressée dans `~/Documents/SlicerDownloads/Mirror_matrix`, et
le champ matrice est rempli avec `…/Mirror/Matrix_mirror.tfm` (`AutoMatrix/AutoMatrix.py:402`).

## Sorties

| Sortie | Format | Nommage | Fichier:ligne |
|---|---|---|---|
| Volume / segmentation transformé | même extension que l'entrée (`.nii.gz`, `.nrrd`, `.nii`…) | `<nom_sans_ext><suffix>[_<nom_matrice>]<ext>` | `Automatrix_CLI/Automatrix_CLI.py:308`, écriture `:205` |
| Landmarks transformés | `.mrk.json` | `<nom_sans_.mrk.json><suffix>[_<nom_matrice>].mrk.json` | `Automatrix_CLI/Automatrix_CLI.py:295`, écriture `:187-188` |
| Arborescence de dossiers | dossiers | réplique la structure relative de l'entrée | `Automatrix_CLI/Automatrix_CLI.py:250-255` |

**Aucune autre sortie** : pas de CSV, pas de rapport, pas de log fichier écrit (l'argument
`log_path` est déclaré `Automatrix_CLI/Automatrix_CLI.py:336` mais **jamais utilisé** dans le corps
du CLI).

**Construction du chemin de sortie.** Si l'entrée patient est un dossier, le chemin est obtenu par
substitution de préfixe : `outpath = scan.replace(args.input_patient, args.output_folder)`
(`Automatrix_CLI/Automatrix_CLI.py:251`), ce qui **préserve les sous-dossiers**. Si l'entrée est un
fichier, c'est le dossier parent qui est remplacé : `scan.replace(os.path.dirname(args.input_patient),
args.output_folder)` (`:253`). Les dossiers manquants sont créés (`:255`).

**Suffixes.** Le suffixe final est `out_suffix = f"{args.suffix}{matrix_suffix}"` où
`matrix_suffix = f"_{Path(matrix).stem}"` seulement si `matrix_name == "True"`
(`Automatrix_CLI/Automatrix_CLI.py:290-291`). Exemple concret : `P1_T1.nii.gz` + `P1_matrix1.tfm`
avec suffixe `_apply` et « add matrix name » coché → `P1_T1_apply_P1_matrix1.nii.gz`.

**Cardinalité.** La boucle est double : `for scan in values['scan']` puis
`for matrix in matrix_candidates` (`Automatrix_CLI/Automatrix_CLI.py:246`, `:283`). Pour un patient
possédant *n* scans et *m* matrices appariées, on obtient donc **n × m fichiers de sortie**
(à condition que `checkBoxMatrixName` soit coché ; voir « Incohérences » sinon). Cas particuliers :

- 1 fichier patient + 1 fichier matrice → 1 sortie.
- 1 fichier patient + dossier de matrices → autant de sorties que de matrices dont le nom de patient
  extrait correspond.
- Dossier patients + 1 fichier matrice → 1 sortie par fichier patient (la même matrice est assignée à
  **tous** les patients, `AutoMatrix/AutoMatrix_Method/General_tools.py:156-158`).
- Dossier patients + dossier matrices → produit croisé **par patient**, pas global.

**Variations selon les options.**
- *Segmentation* (`is_seg=True`) : interpolation plus proche voisin au lieu de linéaire
  (`Automatrix_CLI/Automatrix_CLI.py:210`) — même nombre de fichiers, contenu différent.
- *Mirror* : le suffixe devient `_mir` et `checkBoxMatrixName` est décoché
  (`AutoMatrix/AutoMatrix.py:316-319`) ; côté CLI, si le nom de la matrice contient « mirror »
  (insensible à la casse), la référence utilisateur est **ignorée** et l'image elle-même sert de
  référence (`Automatrix_CLI/Automatrix_CLI.py:303-304`).
- *Landmarks* : la transformée est **inversée** avant application aux points
  (`transform.GetInverse()`, `Automatrix_CLI/Automatrix_CLI.py:176`) — cohérent avec le fait que le
  resampling d'image utilise la transformée sortie→entrée. Si l'inversion échoue, le fichier est
  simplement sauté avec un WARNING (`:177-179`). Seuls les points `positionStatus == 'defined'` et
  de dimension 3 sont transformés ; les autres sont recopiés tels quels (`:181-185`).
- *`CompositeTransform`* : le CLI cherche une référence implicite en remplaçant `_transform.tfm` par
  `.nii.gz` / `.nii` **dans le chemin de la matrice** (`Automatrix_CLI/Automatrix_CLI.py:191-202`,
  appelé avec `matrix` en 5e argument ligne `:309` alors que le paramètre s'appelle `scan_path`).

## Comportement dossier vs fichier (et règle d'appariement fichier↔matrice)

Tout se joue dans `GetPatients`, dupliquée à l'identique (à un détail près) dans
`AutoMatrix/AutoMatrix_Method/General_tools.py:51-160` et `Automatrix_CLI/Automatrix_CLI.py:60-169`.
C'est **la version du CLI** qui régit le traitement réel ; celle du module ne sert qu'à compter les
scans (`NbScan`, `AutoMatrix/AutoMatrix_Method/applyMatrix.py:39-41`).

**Étape 1 — collecte des scans.**
- `Path(file_path).is_dir()` vrai → `search()` récursif sur les 9 extensions
  (`Automatrix_CLI/Automatrix_CLI.py:72`), puis concaténation dans une liste plate (`:74-99`).
- Sinon → un seul fichier, accepté uniquement si son extension figure dans la liste blanche
  (`Automatrix_CLI/Automatrix_CLI.py:123`). **Si l'extension n'est pas reconnue, `patients` reste
  vide et le CLI ne fait rien, silencieusement** (aucun message d'erreur côté CLI).

**Étape 2 — extraction de la clé patient (le « LinkName »).** Pour chaque scan, le nom de base est
tronqué au premier des marqueurs suivants (`Automatrix_CLI/Automatrix_CLI.py:104`) :

```
_Seg _seg _Scan _scan _Or _OR _MAND _MD _MAX _MX _CB _lm _T2 _T1 _Cl _MR  puis '.'
```
puis, en boucle, `_T0` … `_T49` (`:105-106`). Exemple : `P17_T1_MAND_Seg.nii.gz` → clé `P17`.

**Étape 3 — collecte et appariement des matrices.**
- Si le chemin matrice est un **dossier** : `search()` récursif sur `.npy/.h5/.tfm/.mat/.txt`
  (`Automatrix_CLI/Automatrix_CLI.py:137`), puis extraction d'une clé patient par troncature sur une
  liste de marqueurs **différente** (`:157`) :
  `_SegOr _Left _left _Right _right _Or _OR _MAND _MD _MAX _MX _CB _lm _T2 _T1 _Cl _MA _Mir _mir
  _Mirror _mirror _MR`, puis `.` et `_T0…_T49`.
  L'appariement est ensuite **strictement par égalité de clé** :
  `if matrix_pat in patients.keys(): patients[matrix_pat]['matrix'].append(matrix)` (`:162-163`).
  Une matrice dont la clé ne correspond à aucun patient est **silencieusement ignorée** ; un patient
  sans matrice donne une liste vide et **aucune sortie**.
- Si le chemin matrice est un **fichier** : la même matrice est ajoutée à **tous** les patients
  (`Automatrix_CLI/Automatrix_CLI.py:165-167`), sans aucune vérification d'existence ni de format.

**Étape 4 — mode « From AReg » (`fromAreg == "True"`).** L'appariement par nom est court-circuité
pour les landmarks uniquement (`Automatrix_CLI/Automatrix_CLI.py:259-279`) : le suffixe du fichier
(`_CB`, `_L`, `_U`) sélectionne un sous-dossier et un nom de matrice canonique via `suffix_map`
(`:227-231`), et le chemin construit est
`<dossier_matrices>/<Cranial Base|Maxilla|Mandible>/<ID>_OutReg/<ID>_{CBReg|MAXReg|MANDReg}_matrix.tfm`
(`:264-269`). **Ce chemin est bâti sur `args.matrix_lineEdit`, un attribut inexistant — voir
Incohérences.**

## Incohérences et pièges observés dans le code

1. **`args.matrix_lineEdit` n'existe pas** — `Automatrix_CLI/Automatrix_CLI.py:265` utilise
   `args.matrix_lineEdit` alors que l'argument déclaré est `input_matrix`
   (`Automatrix_CLI/Automatrix_CLI.py:330`, `Automatrix_CLI/Automatrix_CLI.xml:25-30`). Le mode
   « From AReg » lèverait donc systématiquement un `AttributeError`. Il est de fait inatteignable :
   la case est masquée (`self.ui.CheckBoxSuffixBased.setVisible(False)`, `AutoMatrix/AutoMatrix.py:296`).

2. **Les maillages surfaciques sont annoncés mais non traités.** `.vtk`, `.vtp`, `.stl`, `.off`,
   `.obj` sont acceptés par la validation UI (`AutoMatrix/AutoMatrix.py:1012`, `:1023`) et collectés
   par `GetPatients` (`Automatrix_CLI/Automatrix_CLI.py:72-87`), mais le CLI ne connaît que deux
   branches : landmarks `.mrk.json` (`:294-298`) et images via `sitk.ReadImage` (`:302`). Un `.stl`
   ou un `.vtp` déclenche une exception attrapée ligne `:310-312`, loguée en ERROR, et **le fichier
   est sauté sans que l'utilisateur soit alerté dans l'UI**. Le README annonce pourtant le support
   « IOS » (`README.md:381`). Aucun import VTK n'existe dans le CLI.

3. **`.npy` listé comme format de matrice valide mais illisible.** Il est accepté par la validation
   (`AutoMatrix/AutoMatrix.py:1041`) et collecté (`Automatrix_CLI/Automatrix_CLI.py:140-141`), mais
   `sitk.ReadTransform` ne supporte pas NumPy : échec en `:286-288`.

4. **`.nii` (non compressé) est rejeté par l'UI mais supporté par le CLI.** La liste blanche de
   `CheckGoodEntre` omet `.nii` (`AutoMatrix/AutoMatrix.py:1012`, `:1023`) alors que `GetPatients`
   le gère (`Automatrix_CLI/Automatrix_CLI.py:72`, `:123`). En mode « File », un `.nii` déclenche
   donc un avertissement bloquant à tort.

5. **Test de dossier vide patient logiquement faux.** `AutoMatrix/AutoMatrix.py:1013` s'écrit
   `if len(dico['.vtk'])==0 and len(dico['.vtp']) and len(dico['.stl']) and …` : seul le premier
   terme est comparé à 0, les suivants sont évalués par leur véracité. L'avertissement « Folder empty
   or wrong type of file patient » ne se déclenche donc que si le dossier ne contient **aucun** `.vtk`
   mais **au moins un de chaque** des sept autres extensions — c'est-à-dire en pratique jamais. Le
   test équivalent côté matrices (`:1036`) est, lui, correct.

6. **`TestProcess` renvoie un tuple, le widget attend une chaîne.**
   `Automatrix_Method.TestProcess` retourne `ok, out` (`AutoMatrix/AutoMatrix_Method/applyMatrix.py:62`)
   alors que l'appelant fait `if isinstance(error, str)` (`AutoMatrix/AutoMatrix.py:767`). La
   condition est toujours fausse : **les messages d'erreur de `TestProcess` ne sont jamais affichés**
   et l'exécution continue même en cas d'entrée invalide.

7. **La barre de progression ne bouge jamais.** `DisplayAutomatrix.isProgress` exige
   `os.path.isfile(self.log_path)` et une modification de mtime (`AutoMatrix/AutoMatrix_Method/Progress.py:41-47`),
   or le CLI ne crée ni n'écrit jamais ce fichier (`log_path` reçu ligne
   `Automatrix_CLI/Automatrix_CLI.py:336` puis inutilisé) et le chemin pointe vers un
   `slicer.util.tempDirectory()` vierge (`AutoMatrix/AutoMatrix.py:271`). Le CLI émet bien des
   `<filter-progress>` (`Automatrix_CLI/Automatrix_CLI.py:314-322`) mais le garde-fou du log les
   neutralise.

8. **`onProcessStarted` peut planter et compte mal.** `self.dico_patient` n'est initialisé que dans
   la branche « dossier » de `CheckGoodEntre` (`AutoMatrix/AutoMatrix.py:1012`), mais il est lu dès
   que `os.path.isdir(LineEditPatient.text)` est vrai (`AutoMatrix/AutoMatrix.py:936-937`) : si
   l'utilisateur laisse `ComboBoxPatient` sur « File » et saisit un dossier à la main →
   `AttributeError`. De plus le décompte omet `.nii` (`:937`), alors que le CLI le traite.

9. **`OnEndProcess` divise par `self.nb_scans`** (`AutoMatrix/AutoMatrix.py:953`) → `ZeroDivisionError`
   si aucun scan valide n'a été trouvé, c'est-à-dire précisément dans le cas d'erreur que l'on
   voudrait signaler proprement.

10. **Écrasement silencieux quand « Add matrix name » est décoché.** Avec plusieurs matrices
    appariées à un même patient et `matrix_name == "False"`, `matrix_suffix` vaut `""`
    (`Automatrix_CLI/Automatrix_CLI.py:290`) : les *m* itérations écrivent toutes le **même**
    `out_file` et seule la dernière matrice subsiste. La cardinalité annoncée n×m devient n.

11. **Découpage d'extension fragile.** `extension_scan = ''.join(Path(scan).suffixes)`
    (`Automatrix_CLI/Automatrix_CLI.py:248`) capture *tous* les points du nom : `P1.T1.nii.gz` donne
    `.T1.nii.gz`. Et `outpath.split(extension_scan)[0]` (`:308`) coupe à la **première** occurrence
    dans le chemin complet, y compris si elle apparaît dans un nom de dossier. Même fragilité pour
    la clé patient qui coupe à `.split('.')[0]` (`:104`) : un nom contenant un point est tronqué.

12. **Duplication de `GetPatients`/`search` avec dérive.** Les deux copies
    (`AutoMatrix/AutoMatrix_Method/General_tools.py:51-160` et `Automatrix_CLI/Automatrix_CLI.py:60-169`)
    ne sont plus identiques : la version CLI ajoute le marqueur `_SegOr` en tête de la troncature des
    matrices (`Automatrix_CLI/Automatrix_CLI.py:157`), absent de la version module
    (`General_tools.py:148`). Le comptage affiché (`NbScan`) peut donc diverger du traitement réel.

13. **Syntaxe f-string imbriquée requérant Python ≥ 3.12.**
    `f"Name process : {self.list_Processes_Parameters[0]["Process"]}"`
    (`AutoMatrix/AutoMatrix.py:846`) utilise les mêmes guillemets à l'intérieur et à l'extérieur :
    `SyntaxError` à l'import sur les Slicer embarquant Python 3.9/3.10.

14. **`CheckGoodEntre` ne valide ni le champ Reference ni l'existence des chemins.** Un chemin
    inexistant, un dossier saisi là où un fichier est attendu, ou une référence illisible ne sont
    détectés qu'au niveau du CLI, sous forme de WARNING dans la console
    (`Automatrix_CLI/Automatrix_CLI.py:239-241`), invisible pour l'utilisateur.

15. **Le mode Mirror laisse le champ Reference renseigné.** `Mirror()` désactive le widget mais ne
    remet pas son texte à `"None"` (`AutoMatrix/AutoMatrix.py:311-313`) ; la valeur est tout de même
    transmise au CLI. Elle est heureusement neutralisée par le test `"mirror" in
    os.path.basename(matrix).lower()` (`Automatrix_CLI/Automatrix_CLI.py:303`) — mais uniquement
    parce que le fichier téléchargé s'appelle `Matrix_mirror.tfm` (`AutoMatrix/AutoMatrix.py:402`).
    Une matrice miroir renommée perdrait ce comportement.

16. **Nommage du paramètre trompeur.** `apply_transform_to_image(..., scan_path, ...)`
    (`Automatrix_CLI/Automatrix_CLI.py:191`) reçoit en réalité le chemin de la **matrice** (`:309`).
    Le code interne y cherche `_transform.tfm` → `.nii.gz`, ce qui n'a de sens que pour une matrice.

## Dépendances et ressources externes

- **SimpleITK** (`Automatrix_CLI/Automatrix_CLI.py:6`) : seule dépendance de calcul, fournie par Slicer.
- **Aucun modèle de deep learning**, aucun téléchargement de poids, pas d'installation de paquets pip.
- Un **unique téléchargement optionnel** : l'archive `Mirror.zip` du mode Mirror
  (`AutoMatrix/AutoMatrix.py:382`), hébergée sur un dépôt GitHub personnel
  (`GaelleLeroux/DCBIA_Apply_matrix`) et non sur l'organisation du projet — point de fragilité à long
  terme.
- Le CLI est enregistré comme `Automatrix_CLI` (`Automatrix_CLI/CMakeLists.txt`) et référencé côté
  Python par `slicer.modules.automatrix_cli` (`AutoMatrix/AutoMatrix_Method/applyMatrix.py:84`).

## Avis — entrées/sorties à ajouter ou retirer

**À retirer / corriger en priorité**

- **Retirer `.npy` de la liste des matrices** (`AutoMatrix/AutoMatrix.py:1041`,
  `Automatrix_CLI/Automatrix_CLI.py:140`) ou ajouter une conversion NumPy → `sitk.AffineTransform`.
  En l'état c'est une promesse non tenue.
- **Trancher sur les maillages.** Soit retirer `.vtk/.vtp/.stl/.off/.obj` de la validation UI et de
  `GetPatients`, soit rétablir une branche VTK (`vtkTransformPolyDataFilter`) dans le CLI. Aujourd'hui
  un utilisateur d'IOS obtient un dossier de sortie vide sans explication.
- **Retirer complètement le mode « From AReg »** tant qu'il n'est pas réparé : il est masqué, cassé
  (`args.matrix_lineEdit`) et ajoute une branche morte non testée.
- **Aligner la liste blanche UI sur celle du CLI** : ajouter `.nii`, et factoriser la liste dans une
  seule constante partagée plutôt que dans six littéraux dupliqués.

**À ajouter**

- **Un rapport de sortie** (CSV ou JSON) listant, par patient : scans trouvés, matrices appariées,
  fichiers écrits, fichiers sautés et raison. C'est le manque le plus coûteux : aujourd'hui la seule
  trace des échecs est la console Python, et le message final annonce systématiquement un succès
  (`AutoMatrix/AutoMatrix.py:971-980`).
- **Une prévisualisation de l'appariement avant lancement** : la règle de troncature
  (`Automatrix_CLI/Automatrix_CLI.py:104` et `:157`) est une heuristique à ~20 marqueurs, totalement
  opaque pour l'utilisateur. Un tableau « scan → matrice(s) » affiché avant exécution éviterait la
  majorité des mauvaises surprises (matrice ignorée, patient sans matrice).
- **Rendre les marqueurs de troncature configurables** (ou au minimum les exposer en lecture) plutôt
  que codés en dur dans deux listes divergentes.
- **Écrire réellement le `log_path`** côté CLI, ce qui débloquerait la barre de progression déjà
  câblée (`AutoMatrix/AutoMatrix_Method/Progress.py:39-47`).
- **Un garde-fou anti-écrasement** : forcer `matrix_name=True` (ou avertir) dès qu'un patient a plus
  d'une matrice appariée, pour éviter la perte silencieuse décrite au point 10.
- **Une option « inverser la transformée »** exposée dans l'UI : elle est actuellement implicite et
  différente entre images et landmarks (`Automatrix_CLI/Automatrix_CLI.py:176`), ce qui est une
  source classique de confusion.
