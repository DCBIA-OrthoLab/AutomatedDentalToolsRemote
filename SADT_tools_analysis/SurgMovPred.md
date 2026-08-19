# SurgMovPred (⚠️ absent du CMakeLists racine - non enregistré)

> **Statut d'enregistrement** : le `CMakeLists.txt` racine ne contient **aucune ligne** `add_subdirectory(SurgMovPred)` ni `add_subdirectory(SurgMovPred_CLI)` (vérifié par grep sur tout le fichier ; la liste des modules s'arrête à `Agent`/`Agent_CLI` avant le marqueur `## NEXT_MODULE`, `CMakeLists.txt:58-60`). Les deux dossiers ont pourtant des `CMakeLists.txt` complets et fonctionnels (`SurgMovPred/CMakeLists.txt` avec `slicerMacroBuildScriptedModule`, `SurgMovPred_CLI/CMakeLists.txt` avec `SlicerMacroBuildScriptedCLI`). Le module est donc **prêt à être branché mais non compilé dans l'extension officielle** - vraisemblablement en cours d'intégration (cf. commit récent « ADD : surgmov model selector on server side »).

## Rôle

SurgMovPred (« Surgical Movement Prediction ») prédit des **mouvements chirurgicaux orthognathiques** à partir de mesures céphalométriques tabulaires pré-opératoires (T0). Ce n'est **pas** un outil d'images ni de LLM : c'est de la **régression ML tabulaire** - chaque cible est prédite par un package « stacking » scikit-learn/LightGBM sérialisé (`stacking_package.pkl` contenant `target_name`, `features_names`, `scaler`, `model`, `SurgMovPred_CLI/SurgMovPred_CLI.py:126-131`, `:221-223`). Le module Slicer (`SurgMovPred/SurgMovPred.py`) collecte 3 dossiers et lance le CLI `slicer.modules.surgmovpred_cli` (`SurgMovPred.py:834-842`). Dépendances installées dans le Python de Slicer : pandas, joblib, openpyxl, scikit-learn, lightgbm + `numpy==2.4.0` forcé (`SurgMovPred.py:167-174`).

## Entrées

| Entrée | Widget (.ui) | Type | Extensions réellement acceptées | Fichier/Dossier | Récursif |
|---|---|---|---|---|---|
| Données patients | `inputFolderLineEdit`, filtre `ctkPathLineEdit::Dirs` (`SurgMovPred.ui:31-38`) | dossier de tableurs | `.csv`, `.xlsx`, `.ods` (+ variantes majuscules `.CSV`/`.XLSX`/`.ODS`) | dossier uniquement | **non** (glob premier niveau) |
| Modèles ML | `modelFolderLineEdit` (`SurgMovPred.ui:69-76`) | dossier de modèles | uniquement des fichiers nommés exactement `stacking_package.pkl` | dossier | **oui** (`**/stacking_package.pkl`) |
| Dossier de sortie | `outputFolderLineEdit` (`SurgMovPred.ui:114-121`) | dossier | - | dossier | - |

Détails avec références :

- **Extensions d'entrée** : `extensions = ['*.csv', '*.xlsx', '*.ods']` puis glob avec chaque extension en minuscule **et** en majuscule, non récursif (`SurgMovPred_CLI.py:149-155`). `.csv` → `pd.read_csv`, `.xlsx` → `pd.read_excel`, `.ods` → `pd.read_excel(engine='odf')` (`:167-172`). **Tous les fichiers trouvés sont concaténés** en un seul DataFrame (`pd.concat`, `:185`).
- **Modèles** : recherche récursive `base_path.glob("**/stacking_package.pkl")` (`SurgMovPred_CLI.py:119`) ; on peut pointer la racine `all_models/` ou un sous-dossier de classe (`:281-283`). Un pkl illisible est ignoré avec log (`:128-132`) ; erreur seulement si aucun n'est chargeable (`:134-135`).
- **Colonne ID patient** : détection tolérante par regex (`#`, `id`, `patient id`, `patient number`, `subject`, etc., `SurgMovPred_CLI.py:69-102`) ; si introuvable, la colonne `IDPatient` de sortie est vide avec un warning (`:293-295`).
- **Correspondance de features** : les noms de colonnes sont normalisés par `clean_name` (`:39-64`) ; une feature attendue `X_T0` peut être fournie sans suffixe `_T0` (`:222-224`). Si des features manquent pour un modèle, **ce modèle est simplement sauté** avec un warning (`:228-230`).
- **Modèle IA par défaut (URL)** : bouton `Default` → `https://github.com/DCBIA-OrthoLab/SlicerAutomatedDentalTools/releases/download/SurgMovPred/all_models.zip`, dézippé dans `~/Documents/<AppName>Downloads/SurgMovPred/Models` (`SurgMovPred.py:786-792`).
- **Fichiers de test (URL)** : bouton `Test files` → `https://github.com/DCBIA-OrthoLab/SlicerAutomatedDentalTools/releases/download/SurgMovPred/TestFiles.zip` (`SurgMovPred.py:768-772`).
- **Dépendance macOS (URL)** : `libomp.dylib` téléchargé depuis `https://mac.r-project.org/openmp/openmp-14.0.6-darwin20-Release.tar.gz` et déposé dans `cli-modules/` de Slicer (`SurgMovPred.py:89-148`).
- **Aucune clé API** : tout est local.
- Le bouton Apply n'est activé que si les 3 chemins sont non vides (`SurgMovPred.py:388-401`) ; le CLI XML ne déclare que 3 `string` positionnels `inputFolder`, `modelPath`, `outputFolder` (`SurgMovPred_CLI/SurgMovPred_CLI.xml:14-33`).

## Sorties

| Fichier | Format | Nommage | Cardinalité |
|---|---|---|---|
| `<output>/predictions_outputs.xlsx` | Excel (index pandas inclus, `index=True`) | fixe | 1 par exécution |
| `<output>/predictions_outputs.csv` | CSV (index pandas inclus) | fixe | 1 par exécution |

- Écriture dans `save_results` (`SurgMovPred_CLI.py:256-274`) : `predictions_outputs.xlsx` (`:262`, `:266`) et `predictions_outputs.csv` (`:263`, `:267`), le dossier de sortie étant créé si besoin (`:261` ; également `os.makedirs(..., exist_ok=True)` côté module, `SurgMovPred.py:832`).
- **Contenu** : 1 ligne par ligne d'entrée (tous fichiers concaténés) ; colonnes = `IDPatient` (insérée en position 0, `SurgMovPred_CLI.py:299`) + **une colonne par modèle prédit avec succès** (`target_name` du pkl). Les deux fichiers contiennent exactement les mêmes données.
- **Variations** : aucune option n'influe sur le nommage ou le nombre de fichiers. En revanche, **le nombre de colonnes varie silencieusement** selon les features disponibles dans l'entrée (modèles sautés, `:228-230`) - on peut obtenir un fichier avec seulement `IDPatient` si aucun modèle ne matche, sans que le run échoue (le log dit quand même « Process completed successfully », `:304`).
- Les fichiers sont **écrasés à chaque exécution** (noms fixes, pas d'horodatage).

## Comportement dossier vs fichier

- Les trois entrées sont des **dossiers exclusivement** (`ctkPathLineEdit::Dirs` dans le .ui ; le CLI lève `FileNotFoundError` si `inputFolder` n'est pas un répertoire, `SurgMovPred_CLI.py:144-145`). Impossible de pointer directement un `.xlsx` unique.
- Dossier de données : scan **non récursif** ; les sous-dossiers sont ignorés sans message.
- Dossier de modèles : scan **récursif illimité** - asymétrie assumée (commentaire `:281-282`).
- Tous les tableurs du dossier d'entrée sont **fusionnés en une seule table** : mélanger des fichiers aux schémas différents produit des NaN par concaténation, et donc potentiellement des prédictions fausses ou des modèles sautés.

## Incohérences et pièges observés dans le code

1. **Non enregistré** : absent du `CMakeLists.txt` racine (voir bandeau) → n'existe pas dans l'extension packagée ; utilisable seulement en ajoutant les chemins manuellement dans Slicer.
2. **Bug du bouton « Test files »** : après téléchargement, le code teste `os.path.exists(os.path.join(self.SlicerDownloadPath, "V_FACE/DefaultList"))` (`SurgMovPred.py:773`) - un chemin du module **V_FACE**, copié-collé. Sauf si un dossier V_FACE traîne dans `<Documents>/<App>Downloads/`, les champs input/output ne sont **jamais auto-remplis** ; seul le modèle par défaut l'est (`:780`).
3. **Textes copiés de MedX/CNE** : `helpText` dit « This tool helps to create summaries of clinical notes » (`SurgMovPred.py:236-239`) et la docstring du parameter node parle de notes cliniques `.docx/.pdf`, TMJ/Ortho (`:251-258`) - sans rapport avec la prédiction chirurgicale. La logique nomme aussi ses arguments `notesFolder_input`/`notesFolder_output` (`:815`).
4. **`pip install numpy==2.4.0` inconditionnel à chaque clic Apply** (`SurgMovPred.py:174`) : exécuté avant toute vérification, même si numpy est déjà bon - lent, et risque réel de casser les autres modules SADT (MedX exige au contraire `numpy<2.0.0`, `MedX/MedX.py:903`).
5. **Support `.ods` incomplet** : la lecture ODS exige le moteur `odf` (odfpy) (`SurgMovPred_CLI.py:172`) mais `odfpy` n'est **pas** dans `DEPENDENCIES` (`SurgMovPred.py:167-173`) → tout `.ods` échouera (exception attrapée par fichier, `:179-180`, donc silencieusement ignoré si d'autres fichiers existent).
6. **Reste de code LLM** : `install_function` a un cas spécial `llama-cpp-python` avec index CPU dédié (`SurgMovPred.py:66-67`) alors que cette lib n'est jamais demandée - vestige d'une version antérieure à base de LLM.
7. **Échec « réussi »** : `main` retourne 1 en cas d'exception mais chaque étape logge sans faire échouer le nœud CLI de façon visible côté UI ; surtout, un run où **tous** les modèles sont sautés (features manquantes) se termine en succès avec un fichier de prédictions vide de cibles (`SurgMovPred_CLI.py:228-249`, `:304`).
8. **Pas de barre de progression** : `onCliProgress` existe mais ne fait rien (`SurgMovPred.py:847-849`) et n'est jamais enregistré comme observer ; l'UI n'a pas de QProgressBar (le stylesheet en style un pourtant, `:511-521`).
9. **Doublon de téléchargement** : dans `DownloadUnzip`, après la boucle de lecture par blocs, `shutil.copyfileobj(response, out_file)` est rappelé (`SurgMovPred.py:752`) - inoffensif (flux épuisé) mais mort.
10. **Sorties indexées** : `index=True` (`SurgMovPred_CLI.py:266-267`) ajoute une colonne d'index pandas sans nom à côté d'`IDPatient` - redondant.
11. **UI mineure** : deux layouts portent le même nom `horizontalLayout` (`SurgMovPred.ui:29` et `:67`) ; les tooltips des boutons Apply/Cancel disent « Test Files. » (`:130`, `:143`) ; les propriétés `SlicerParameterName` sont laissées **vides** (`:36`, `:74`, `:118`), donc `connectGui` du parameterNodeWrapper ne lie rien - c'est `_checkCanApply` qui recopie manuellement les chemins (`SurgMovPred.py:394-396`).
12. **État général** : module fonctionnel de bout en bout (le CLI est la partie la plus soignée, avec gestion d'erreurs et logs récents), mais l'enrobage Slicer est encore en développement (textes faux, bouton test cassé, non enregistré au build).

## Avis - entrées/sorties à ajouter ou retirer

- **À corriger en priorité** : enregistrer le module dans le CMakeLists racine ; réparer le chemin `V_FACE/DefaultList` (`SurgMovPred.py:773`) ; corriger helpText/docstrings ; conditionner le `pip install numpy==2.4.0` ; ajouter `odfpy` aux dépendances ou retirer `.ods` des extensions annoncées.
- **À ajouter (entrées)** : possibilité de sélectionner un **fichier unique** (cas d'usage le plus courant : un seul tableur de patients) ; une option pour choisir la classe de modèles (le commit « model selector » suggère que c'est en cours) ; validation en amont des colonnes attendues avec message clair listant les features manquantes.
- **À ajouter (sorties)** : un rapport (`.txt`/`.json`) listant les modèles appliqués/sautés et les features manquantes - aujourd'hui cette information n'existe que dans les logs CLI ; supprimer l'index pandas (`index=False`) ou le nommer ; envisager un horodatage ou un suffixe pour éviter l'écrasement de `predictions_outputs.*`.
- **À retirer** : la branche `llama-cpp-python` d'`install_function` ; le `shutil.copyfileobj` mort ; l'un des deux formats de sortie pourrait devenir optionnel (CSV et XLSX strictement identiques).
