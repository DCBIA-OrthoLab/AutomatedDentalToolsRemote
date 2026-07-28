# FlexReg

> Analyse basée sur la lecture du code réel : `FlexReg/FlexReg.py` (module Slicer, 2636 lignes), `FlexReg/Resources/UI/FlexReg.ui`, `FlexReg_CLI/FlexReg_CLI.py` + `FlexReg_CLI/FlexReg_CLI.xml` et `FlexReg_CLI/FlexReg_Method/*`. Les chemins cités sont relatifs à la racine du dépôt SADT.

## Rôle

FlexReg réalise la **registration (recalage rigide ICP) de scans intra-oraux (IOS)** entre deux temps (T1 = scan fixe, T2 = scan mobile), en limitant l'ICP à une **zone (« patch ») définie sur la surface**. Le flux est entièrement interactif :

1. L'utilisateur charge **un fichier .vtk par fenêtre 3D** (2 fenêtres de scans + 1 fenêtre de résultat, layout custom 501, `FlexReg/FlexReg.py:300-326`).
2. Il crée un ou plusieurs patchs par scan, de deux manières (combobox `Parameter` / `Landmark`, `FlexReg/FlexReg.py:1341-1343`) :
   - **« Butterfly » paramétrique** : à partir de 4 numéros de dents (labels `Universal_ID`) + ratios + ajustements A-P → CLI type `butterfly` → `butterflyPatch()` (`FlexReg_CLI/FlexReg_CLI.py:52-85`, `FlexReg_CLI/FlexReg_Method/make_butterfly.py:53-158`).
   - **Courbe fermée dessinée** : markups `vtkMRMLMarkupsClosedCurveNode` + un point milieu fiducial, projetés sur la surface → CLI type `curve` → `drawPatch()` (`FlexReg/FlexReg.py:2272-2497`, `FlexReg_CLI/FlexReg_Method/draw.py:22-56`).
3. Le patch est stocké **dans le fichier .vtk lui-même** comme point-data array `Butterfly{i}` + array fusionné `Butterfly` (OR logique de tous les patchs, `FlexReg_CLI/FlexReg_CLI.py:228-256`).
4. Bouton *Registration* : ICP `vtkIterativeClosestPointTransform` (rigide, 1000 itérations, `FlexReg_CLI/FlexReg_Method/ICP.py:94-113`) sur **les points où `Butterfly == 1`** (`vtkMeshTeeth(list_teeth=[1], property="Butterfly")`, `FlexReg_CLI/FlexReg_CLI.py:172`), puis écriture du T2 recalé, de la matrice `.tfm`, et optionnellement de l'arcade inférieure transformée.

Si le scan n'a pas de segmentation `Universal_ID`, le module lance automatiquement **CrownSegmentation / dentalmodelseg** (via SlicerConda/shapeaxi) pour segmenter les couronnes (`FlexReg/FlexReg.py:1892-1930`, `1948-1992`, `2133-2173`).

## Entrées

| # | Nom (UI) | Widget / paramètre CLI | Type | Extensions réellement acceptées | Fichier / dossier | Rôle |
|---|----------|------------------------|------|--------------------------------|-------------------|------|
| 1 | *Fix scan* (T1) | `lineedit` du widget 1 → CLI `path_reg` | maillage surfacique segmenté | **`.vtk` uniquement** (filtre dialog `FlexReg/FlexReg.py:1687`, vérif `checkLineEdit` `:1695-1696`, lecture `vtkPolyDataReader` `FlexReg_CLI/FlexReg_CLI.py:138-140`) | fichier unique | scan de référence, jamais modifié par l'ICP |
| 2 | *Moving scan* (T2) | `lineedit` du widget 2 → CLI `lineedit` | maillage surfacique segmenté | **`.vtk` uniquement** (mêmes lignes ; lecture `FlexReg_CLI/FlexReg_CLI.py:35-38`) | fichier unique | scan à recaler ; **modifié en place** lors de la création des patchs |
| 3 | *Apply to lower arch* | `lineEditLowerArch` → CLI `lower_arch` | maillage surfacique | **`.vtk` uniquement** (filtre `VTK Files (*.vtk)` `FlexReg/FlexReg.py:390`, lecture `vtkPolyDataReader` `FlexReg_CLI/FlexReg_CLI.py:155-158`) | fichier unique, optionnel (défaut littéral `"None"`, `FlexReg.ui:269`) | arcade antagoniste T2 à laquelle la même matrice est appliquée |
| 4 | *Output folder* | `lineEditOutput` → CLI `path_output` | dossier | — (choix via `getExistingDirectory`, `FlexReg/FlexReg.py:386`) | dossier | destination des sorties ICP |
| 5 | *Suffix* | `lineEditSuffix` → CLI `suffix` | chaîne | défaut `_REG` (`FlexReg.ui:253`) | — | suffixe des fichiers produits |
| 6 | Dents 1-4 (mode *Parameter*) | 4 × `Teeth n` → CLI `lineedit_teeth_*` | entiers (Universal Numbering 1-32) | défauts 5, 12, 3, 14 (`FlexReg/FlexReg.py:1369-1383`) | — | coins du patch butterfly (centroïdes des labels `Universal_ID`, `make_butterfly.py:77-99`) |
| 7 | `Ratio (R-L)` ×4, `Adjust (A-P)` ×4 | → CLI `lineedit_ratio_*`, `lineedit_adjust_*` | flottants (défauts 0.345/0.32 et -0.1/-2) | — | — | largeur transversale et décalage antéro-postérieur du patch |
| 8 | Courbe + point milieu (mode *Landmark*) | nœuds markups → CLI `curve`, `middle_point` (sérialisés en chaîne, `FlexReg/FlexReg.py:2454-2460`) | markups Slicer | créés dans la scène (pas de fichier) | — | contour du patch dessiné + graine de remplissage (dilatation `propagation.py`) |
| 9 | *Patch* / *Create new patch* / *Delete patch* | combobox + checkbox → CLI `index_patch` | entier ≥ 1 | — | — | index de l'array `Butterfly{i}` visé |
| 10 | Segmentation `Universal_ID` | point-data array du .vtk | array scalaire par point | implicite dans le .vtk | — | **prérequis** du patch butterfly et de l'orientation ; auto-générée par CrownSegmentation sinon (`FlexReg/FlexReg.py:1924-1930`) |
| 11 | Modèle de segmentation (implicite) | téléchargement `07-21-22_val-loss0.169.pth` | `.pth` | URL codée en dur (`FlexReg/FlexReg.py:1868`) | fichier | modèle CrownSegmentation (téléchargé dans `Documents/SlicerDownloads`) |

Points saillants :

- **Aucun mode dossier / batch** : chaque entrée est un fichier unique choisi par `QFileDialog.getOpenFileName` ; il n'existe **aucun scan récursif** ni traitement de répertoire dans tout le module.
- **`.vtk` legacy uniquement, partout**. Le widget refuse toute autre extension (`checkLineEdit`, `FlexReg/FlexReg.py:1695-1696`) et le CLI lit toutes les surfaces avec `vtkPolyDataReader` sans regarder l'extension (`FlexReg_CLI/FlexReg_CLI.py:35`, `:138`, `:155`). La fonction `ReadSurf` qui saurait lire `.vtp`/`.stl`/`.obj` existe (`FlexReg_CLI/FlexReg_Method/utils.py:22-68`) mais n'est atteignable que via `ICP.pathTo`, appelé seulement si la source est une chaîne (`ICP.py:64-65`) — le CLI passe toujours des `vtkPolyData`, donc **ce code est mort**.
- **La zone de registration** est définie soit par sélection de dents (butterfly, mode par défaut), soit par courbe fermée + point milieu. Pas de sphère. Le patch butterfly exige en outre que les dents **3, 5, 12 et 14** (UR6, UR4, UL4, UL6 — arcade supérieure) soient segmentées pour l'étape d'orientation (`make_butterfly.py:80-81`, `FlexReg/FlexReg.py:1916-1917`) : le module est donc de fait conçu pour des **arcades maxillaires** en entrée principale.
- Le spinbox « nombre de scans » (2-10, `FlexReg.ui:154-161`) est **masqué** (`FlexReg/FlexReg.py:275-276`) ; le nombre de scans est verrouillé à 2 (`manageNumberWidgetScan(2)`, `:290`) et `Reg.setT1T2` n'utilise que les widgets 0 et 1 (`:357`).
- Environnements requis en entrée implicite : SlicerConda + env conda `shapeaxi` (ocnn 2.2.1, shapeaxi 1.0.10, pytorch3d) pour la segmentation automatique (`FlexReg/FlexReg.py:866-885`, `2013-2115`) ; numpy<2, itk, torch 2.2.0, monai 1.3.2 côté Slicer (`:1710-1715`).

## Sorties

| Sortie | Format | Nommage exact | Cardinalité | Condition |
|--------|--------|---------------|-------------|-----------|
| T2 recalé | `.vtk` (polydata legacy, LPS) | `{path_output}/{nom_T2 sans ".vtk"/"vtp"}{suffix}.vtk` (`FlexReg_CLI/FlexReg_CLI.py:279-286`) | 1 par clic *Registration* | mode `icp` |
| Matrice de recalage (inverse, repère LPS) | `.tfm` (SimpleITK `AffineTransform`) | `{path_output}/{basename_T2 sans ext}{suffix}.tfm` (`FlexReg_CLI/FlexReg_CLI.py:201-204`) | 1 par clic *Registration* | mode `icp` |
| Arcade inférieure recalée | `.vtk` | `{path_output}/{nom_lower_arch sans ".vtk"/"vtp"}{suffix}.vtk` (`FlexReg_CLI/FlexReg_CLI.py:302-308`) | 0 ou 1 | mode `icp` **et** `lower_arch != "None"` (et le widget n'envoie le chemin que si `Path(...).is_file()`, `FlexReg/FlexReg.py:336-339`) |
| Scan enrichi du patch | `.vtk` — **écrase le fichier d'entrée** | même chemin que l'entrée (`writer.SetFileName(args.lineedit)`, `FlexReg_CLI/FlexReg_CLI.py:276-277`) | 1 par Update / Draw / Delete patch | modes `butterfly`, `curve`, `delete` |
| Arrays point-data ajoutés | `Butterfly{i}` (un par patch) + `Butterfly` (fusion OR de tous les patchs) | dans le .vtk (`make_butterfly.py:153-158`, `draw.py:53-56`, `FlexReg_CLI/FlexReg_CLI.py:228-256`) | N patchs + 1 | tous modes |
| Scan segmenté (si segmentation auto) | `.vtk` écrit **dans le dossier du scan d'entrée** | géré par CrownSegmentationcli (`out`/`vtk_folder` = `os.path.dirname(lineedit)`, `FlexReg/FlexReg.py:1956-1965`, `2144-2155`) | 0 ou 1 par scan non segmenté | scan sans `Universal_ID` |

Prose :

- **Cardinalité totale d'un run ICP standard : 2 fichiers** (`T2{suffix}.vtk` + `T2{suffix}.tfm`), **3 avec l'option lower arch**. Le T1 (fixe) n'est jamais écrit.
- Le nommage utilise `outpath.split('.vtk')[0].split('vtp')[0] + suffix + '.vtk'` (`FlexReg_CLI/FlexReg_CLI.py:283`, `:306`, et miroir côté widget `FlexReg/FlexReg.py:1200-1201`). Le second `split('vtp')` est **sans point** : tout nom de fichier contenant la sous-chaîne `vtp` (ex. `scan_vtp2.vtk`) est tronqué de façon inattendue.
- Le dossier de sortie est créé s'il n'existe pas (`FlexReg_CLI/FlexReg_CLI.py:280-281`, `:303-304`), mais le `.tfm` est écrit **avant** cette création (`:202-203`) : si `path_output` n'existe pas, `sitk.WriteTransform` échoue avant la création du dossier.
- La matrice `.tfm` sauvegardée est l'**inverse** de la matrice ICP, conjuguée par `diag(-1,-1,1,1)` pour repasser du RAS interne au LPS des fichiers (`FlexReg_CLI/FlexReg_CLI.py:193-199`) — elle est prévue pour être appliquée dans ITK/Slicer sur d'autres données du même patient.
- Les modes patch (`butterfly`, `curve`, `delete`) ne produisent **aucun nouveau fichier** : ils réécrivent le `.vtk` d'entrée en place, en y ajoutant/supprimant des arrays. L'option *Output folder* n'a aucun effet sur eux.
- Affichage post-traitement : le widget recharge T1 et le T2 recalé dans la 3e vue avec deux couleurs fixes (`FlexReg/FlexReg.py:1194-1246`).

## Comportement dossier vs fichier

- **Tout est fichier unique.** T1, T2 et lower arch sont des fichiers `.vtk` individuels ; il n'y a ni glob, ni `os.walk`, ni itération de dossier dans `FlexReg/FlexReg.py` ou `FlexReg_CLI/FlexReg_CLI.py`. Pas de mode batch : pour recaler 10 patients il faut 10 manipulations manuelles complètes (chargement, patch sur T1, patch sur T2, registration).
- Le seul « dossier » est l'**Output folder** (entrée n°4), utilisé uniquement par le mode `icp` pour y déposer les 2-3 fichiers de sortie, avec `os.makedirs` au besoin (`FlexReg_CLI/FlexReg_CLI.py:280-281`).
- Effet de bord notable : la segmentation automatique écrit dans le **dossier du scan d'entrée** (`os.path.dirname(self.lineedit.text)`, `FlexReg/FlexReg.py:1958`, `:1965`, `:2154`), pas dans l'Output folder.

## Incohérences et pièges observés dans le code

1. **Écrasement silencieux des fichiers d'entrée** : les modes `butterfly`/`curve`/`delete` réécrivent le `.vtk` source sans sauvegarde ni avertissement (`FlexReg_CLI/FlexReg_CLI.py:276-277`). Un crash au milieu de l'écriture peut corrompre le scan original.
2. **CUDA obligatoire pour tout** : le bloc commun de fusion des patchs fait `.cuda()` inconditionnellement (`FlexReg_CLI/FlexReg_CLI.py:237`, `:250`), de même que `drawPatch` (`FlexReg_CLI/FlexReg_Method/draw.py:26-45`). Sur une machine sans GPU NVIDIA, **tous** les modes du CLI plantent, y compris un simple `delete`, alors que rien dans l'UI ne l'exige.
3. **UI vs code — widgets fantômes** : `updateParameterNodeFromGUI` référence `self.ui.outputSelector`, `invertedOutputSelector` (`FlexReg/FlexReg.py:688-690`) qui **n'existent pas** dans `FlexReg.ui` ; la section *Advanced* du .ui contient un `invertOutputCheckBox` (`FlexReg.ui:286-305`) jamais lu par le code utile. Restes du template Slicer.
4. **Extensions annoncées vs gérées** : `ReadSurf` gère `.vtp/.stl/.obj` (`FlexReg_CLI/FlexReg_Method/utils.py:22-68`) mais est inatteignable (voir Entrées) ; le nommage de sortie prévoit le cas `vtp` (`FlexReg_CLI/FlexReg_CLI.py:283`) alors qu'un `.vtp` ne peut même pas être lu (lecteur legacy `vtkPolyDataReader` uniquement). Le `split('vtp')` sans point est en outre un bug de troncature pour tout nom contenant « vtp ».
5. **`.tfm` écrit avant la création du dossier de sortie** (`FlexReg_CLI/FlexReg_CLI.py:202-203` vs `:280-281`) : échec si l'utilisateur tape un chemin inexistant au lieu de le choisir au dialog.
6. **XML CLI** : description erronée de `index_patch` (« icp : suffix to add to the register file », copié-collé, `FlexReg_CLI/FlexReg_CLI.xml:156`) ; tous les paramètres sont déclarés `<string>` alors que le script attend des int/float (`FlexReg_CLI/FlexReg_CLI.py:324-347`).
7. **Multi-scans factice** : spinbox 2-10 masqué (`FlexReg/FlexReg.py:275`), la registration ne considère que les widgets 1 et 2 (`:357`) — l'UI laisse croire à une capacité N-scans inexistante.
8. **Test unitaire cassé** : `FlexRegTest.test_FlexReg1` appelle `logic.process(inputVolume, outputVolume, threshold, True)` (`FlexReg/FlexReg.py:1054`) alors que `process()` ne prend aucun argument (`:777`) ; les SampleData enregistrés sont des volumes `.nrrd` du template (`:195-224`), sans rapport avec des maillages IOS.
9. **Hypothèse arcade supérieure codée en dur** : l'orientation exige les dents 3/5/12/14 (`FlexReg/FlexReg.py:1916-1917`, `make_butterfly.py:81`) — sur une arcade mandibulaire (dents 17-32), le patch butterfly échoue avec `ToothNoExist` ; seule la voie « lower arch » (transformation passive) traite la mandibule.
10. **Lower arch silencieusement ignorée** : si le chemin saisi n'est pas un fichier, le widget envoie `"None"` sans message (`FlexReg/FlexReg.py:336-339`) — l'utilisateur croit avoir recalé son arcade inférieure alors que rien n'est produit.
11. **Métadonnées du module non renseignées** : contributeurs « John Doe (AnyWare Corp.) », helpText du template (`FlexReg/FlexReg.py:161-166`).
12. **`path_file` de `getOpenFileName`** est passé tel quel à `setText` (`FlexReg/FlexReg.py:390-391`, `:1687-1689`) — fonctionne avec les bindings Qt de Slicer (retour str) mais fragile.

## Avis — entrées/sorties à ajouter ou retirer

**À ajouter :**
- **Support `.stl`/`.obj`/`.vtp` en entrée** : les IOS sortent des scanners en `.stl`/`.obj` ; le code `ReadSurf` existe déjà (`FlexReg_CLI/FlexReg_Method/utils.py:22`) — il suffirait de l'utiliser dans le CLI et d'élargir le filtre du dialog.
- **Mode batch / dossier** : entrée « dossier T1 + dossier T2 + appariement par nom » comme dans les autres modules SADT (AREG), pour éviter la manipulation patient par patient.
- **Sortie non destructive des patchs** : écrire le scan patché dans l'Output folder (ou une option « overwrite »), au lieu d'écraser l'entrée.
- **Sortie du T1 copié/patché et un rapport** (RMSE ICP, nombre de points du patch) : aujourd'hui aucune métrique de qualité du recalage n'est produite alors que `icp.run` retourne déjà `source_icp`/`target_int` (`FlexReg_CLI/FlexReg_Method/ICP.py:81-89`).
- **Fallback CPU** pour les opérations torch (aucune n'exige réellement le GPU : ce sont des `cdist`/`logical_or`).
- **Sauvegarde/chargement des courbes** (markups `.mrk.json`) pour rendre le patch « Landmark » reproductible ; `LoadJsonLandmarks` existe déjà mais n'est jamais branché (`FlexReg_CLI/FlexReg_Method/utils.py:96`).

**À retirer / nettoyer :**
- La section *Advanced* et `invertOutputCheckBox` du `.ui`, `updateParameterNodeFromGUI`, les SampleData `.nrrd` et le test du template — code mort trompeur.
- Le spinbox « nombre de scans » masqué : soit l'implémenter, soit le supprimer du `.ui`.
- Le paramètre CLI `lower_arch` par valeur sentinelle `"None"` (remplacer par un vrai optionnel) et la double sentinelle `"None"`/chaîne vide dispersée dans les 21 arguments positionnels du CLI, très fragile.
- Le `split('vtp')` sans point dans le nommage des sorties (`FlexReg_CLI/FlexReg_CLI.py:283`, `:306` ; `FlexReg/FlexReg.py:1201`), à remplacer par `os.path.splitext`.
