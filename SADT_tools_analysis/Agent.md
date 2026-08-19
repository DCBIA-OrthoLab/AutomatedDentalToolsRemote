# Agent

## Rôle

`Agent` est le front-end graphique d'un agent IA **entièrement local** qui pilote les autres modules de SlicerAutomatedDentalTools à partir d'une requête en langage naturel. Il n'utilise **aucune API cloud ni clé API** : le LLM est `qwen3:8b` servi par **Ollama** sur `127.0.0.1:11434` (`Agent/Agent.py:18`, `Agent_CLI/Agent_CLI_utils/utils.py:21`, socket probe `Agent/Agent.py:65-76`). Le modèle est surchargeable par la variable d'environnement `ROUTER_MODEL` (`utils.py:24-26`).

Architecture en deux étages :

1. **`Agent/Agent.py`** (module Slicer scripté) : UI de chat (prompt, drop-zone, mode), installation des dépendances (bouton *Check* : pip `ollama`, `pyyaml`, `transformers<4.53.0`, `numpy<2`, `sentence-transformers`, `Agent.py:1157-1163` ; téléchargement automatique du binaire Ollama officiel depuis ollama.com, `Agent.py:101-158` ; `ollama pull qwen3:8b`, `Agent.py:1261-1279`). Il lance ensuite le CLI Slicer `agent_cli` (`Agent.py:796-798`).
2. **`Agent_CLI/Agent_CLI.py`** (CLI `python-real`) : le "cerveau". Pipeline en mode *Agent (Automated)* (`Agent_CLI.py:86-179`) :
   - **Retrieval** : un cross-encoder `cross-encoder/ms-marco-MiniLM-L-6-v2` (sentence-transformers, téléchargé depuis HuggingFace) classe les 22 outils du `manifest.yaml` et garde le top-3 (`utils.py:41-94`, `Agent_CLI.py:102`).
   - **Routage** : `ollama.chat(format="json")` choisit un outil parmi les candidats (`Agent_CLI.py:105-143`).
   - **Extraction de paramètres** : second appel LLM guidé par le manifeste (`parameter_extraction_improved.py:33-74`, `utils.py:220-280`), puis validation/coercition de types (`parameter_validator.py:28-94`).
   - **Construction de la commande** : `[sys.executable, chemin_du_script, args...]` (`utils.py:350-404`).
   
   L'exécution réelle de l'outil se fait côté widget après confirmation utilisateur (QMessageBox `Agent.py:864-869`), via `subprocess.run` avec boucle de "réparation" LLM bornée à 2 tentatives (`Agent.py:943-1013`, `MAX_REPAIR_ATTEMPTS` `Agent.py:14`, prompt de réparation `utils.py:282-321`).

Outils pilotables (déclarés dans `Agent_CLI/manifest.yaml`) : `ali_cbct`, `ali_ios`, `amasss_cli`, `areg_cbct`, `areg_ios`, `autocrop3d`, `automatrix`, `batchdentalseg`, `clic`, `docshapeaxi`, `flexreg`, `medx_dashboard`, `medx_summarize`, 6 sous-outils `mri2cbct_*`, `pre_aso_cbct`, `pre_aso_ios`, `semi_aso_cbct`, `semi_aso_ios`.

## Entrées (tableau + prose)

| Nom | Type | Fichier/Dossier | Extensions filtrées | Obligatoire | Référence |
|---|---|---|---|---|---|
| `prompt` | Texte libre (QTextEdit) | - | - | Oui (les 2 modes) | `Agent.ui:210-238`, `Agent.py:600` |
| Drop zone (`folders`) | Liste de chemins par glisser-déposer | Fichiers **et/ou** dossiers, multiples | **Aucun filtre** (tout URL local accepté) | Oui en mode *Agent (Automated)*, non en mode *Ask* | `Agent.py:210-266` (DropZone), `Agent.py:605-629` (validation) |
| `modeagent` | ComboBox : `Agent (Automated)` / `Ask (Interactive)` | - | - | Oui (défaut Agent) | `Agent.ui:186-197`, `Agent.py:569` |
| Chat précédent (*Previous Chat*) | Fichier texte d'une session sauvegardée | Fichier unique | `*.txt` uniquement | Non | `Agent.py:1104-1109` |
| `history` | JSON `[{"role","content"},...]` (interne, 40 derniers tours) | - | - | Non | `Agent.py:743-750,794`, `Agent_CLI.py:79-84` |
| `temp_folder` | Dossier temporaire créé automatiquement | Dossier | - | Interne | `Agent.py:793` (`slicer.util.tempDirectory()`) |
| `ROUTER_MODEL`, `AGENT_CLI_TOOLS_DIR`, `SLICER_AGENT_HOME` | Variables d'environnement | - | - | Non | `utils.py:26`, `utils.py:160`, `Agent.py:38` |

- Le prompt est envoyé au CLI tel quel ; **Entrée** l'envoie, **Maj+Entrée** insère un saut de ligne (`Agent.py:331-351`).
- La drop-zone n'impose **aucune extension** : `dropEvent` accepte tout chemin local (`Agent.py:254-266`). Les extensions attendues ne vivent que dans les *descriptions* du manifeste lues par le LLM, p. ex. `.nii/.nrrd` pour `ali_cbct` (`manifest.yaml:14`), `STL/VTK/OFF` pour `ali_ios` (`manifest.yaml:58`), `.mrk.json` pour `autocrop3d` (`manifest.yaml:218`), `.tfm/.h5` pour `automatrix` (`manifest.yaml:252`), `PDF/DOCX/TXT` pour `medx_summarize` (`manifest.yaml:520`), `.vtk` pour `flexreg` (`manifest.yaml:389`).
- Les chemins déposés sont concaténés en une chaîne séparée par des virgules (`Agent.py:790`) et injectés dans le prompt d'extraction comme `FOLDERS_CONTEXT`, source de vérité pour les chemins (`Agent_CLI.py:88-98,146`). Si rien n'est déposé (mode Ask), la sentinelle `'nothing'` est envoyée (`Agent.py:784-785`).
- Aucune clé API n'est demandée nulle part : pas de champ, pas de QSettings, pas de fichier de configuration secret.

## Sorties (tableau + prose)

| Sortie | Format | Nommage | Cardinalité | Référence |
|---|---|---|---|---|
| Décision du routeur (stdout du CLI) | JSON une ligne : `{tool, tool_confidence, parameters_confidence, parameters, missing_required, command, [error]}` | - | 1 par requête en mode Agent | `Agent_CLI.py:159-179`, format d'erreur `Agent_CLI.py:53-62` |
| Réponse consultant (stdout du CLI) | Texte brut (les `*` et `#` Markdown sont supprimés) | - | 1 par requête en mode Ask | `Agent_CLI.py:214-217` |
| Exécution d'un outil tiers | `subprocess.run([python, script.py, args...])` - les fichiers résultats (segmentations, landmarks, recalages…) sont produits par l'outil piloté dans l'`output_dir` fourni par l'utilisateur | dépend de l'outil | 0 ou 1 outil par requête (jamais de chaîne d'outils) ; jusqu'à 2 relances corrigées | `Agent.py:962`, `Agent.py:943-1013` |
| Sauvegarde du chat | `.txt` (texte brut du QTextEdit, marqueurs `👨:` / `🤖:`) | `~/Chat_LLM_%Y-%m-%d_%H-%M-%S.txt` (dossier home, non configurable) | 1 fichier par clic sur *Save Chat* | `Agent.py:1077-1082` |
| Bulles de chat dans l'UI | HTML injecté dans un QTextEdit lecture seule | - | flux de conversation | `Agent.py:704-741` |
| Dossier temporaire | dossier vide passé aux paramètres `temp_fold/tmp_folder/temp_folder/log_path/logPath` cachés au LLM | via `slicer.util.tempDirectory()` | 1 par requête | `Agent.py:793`, `utils.py:227-236`, `Agent_CLI.py:152-155` |
| Logs console | stdout/stderr imprimés dans la console Python Slicer | - | - | `Agent.py:825,970-971` |

Le module Agent lui-même **n'écrit aucune donnée d'imagerie** : ses seules productions propres sont le JSON de routage, le chat et son fichier `.txt` de sauvegarde. Toutes les sorties « métier » appartiennent aux outils pilotés, avec les chemins de sortie extraits du prompt/FOLDERS_CONTEXT par le LLM.

## Comportement dossier vs fichier

- La drop-zone accepte indifféremment fichiers et dossiers, en nombre quelconque, avec déduplication par chemin normalisé (`Agent.py:513-526`). Aucune inspection du contenu n'est faite côté Agent : la liste brute est transmise au LLM qui décide quel chemin va dans quel paramètre (`Agent_CLI.py:90-98`).
- La distinction fichier/dossier repose sur des **conventions de nommage**, pas sur le système de fichiers : le prompt d'extraction impose « si le nom du paramètre contient *folder* ou *dir* → chemin de dossier sans nom de fichier » (`parameter_extraction_improved.py:58-61`), et le validateur rejette un paramètre `*folder*/*dir*` se terminant par `.nii.gz/.nii/.stl/.ply/.vtk/.json/.txt/.log` (`parameter_validator.py:189-196`). **L'existence des chemins n'est jamais vérifiée** avant exécution (`parameter_validator.py:180-186` ne teste que la syntaxe `Path(str(value))`).
- La plupart des outils du manifeste attendent des **dossiers** (batch) ; quelques-uns attendent un fichier unique (`ali_ios` `input` STL/VTK/OFF `manifest.yaml:55-58`, `flexreg` `lineedit` .vtk `manifest.yaml:386-389`, `ali_cbct` accepte « fichier ou dossier » `manifest.yaml:14`).
- Le mode *Ask (Interactive)* fonctionne sans aucune donnée déposée (`Agent.py:620-629`).

## Incohérences et pièges observés dans le code

1. **Résolution des chemins d'outils cassée pour la disposition actuelle du dépôt** : `resolve_tool_path` cherche les scripts dans un dossier `CLI files/` à côté du manifeste ou dans les ancêtres (`utils.py:143-179`, le commentaire cite un layout `AI_Agent/Agent_CLI/ + .../CLI files/`). Or dans ce dépôt les scripts vivent dans des dossiers par module (`ALI_CBCT/ALI_CBCT.py`, `ASO_CBCT/PRE_ASO_CBCT/PRE_ASO_CBCT.py`, `MedX_CLI/MedX_Summarize/MedX_Summarize.py`…) - aucun `CLI files/` n'existe. Sans `AGENT_CLI_TOOLS_DIR` ni installation packagée qui aplatit les CLIs, la commande construite pointe vers un chemin inexistant et l'exécution échoue.
2. **`cli_style: ui_module` non implémenté** : `batchdentalseg` et `clic` sont déclarés `ui_module` (`manifest.yaml:285,313`) mais `build_cli_args` ne connaît que `positional` et le style `--flag` par défaut (`utils.py:373-404`) ; ces deux modules scriptés Slicer seraient lancés comme de simples scripts Python avec des flags `--...`, ce qui ne peut pas fonctionner.
3. **Bug d'unpacking** : `extract_parameters` retourne 3 valeurs si l'outil est absent du manifeste (`utils.py:225` `return {}, 0.0, []`) alors que l'appelant en déballe 4 (`Agent_CLI.py:148`) → `ValueError` si le routeur hallucine un nom d'outil hors manifeste. L'annotation de type (`utils.py:220`, `Tuple[Dict, float, List[str]]`) est fausse aussi (4 valeurs au chemin nominal, `utils.py:269`).
4. **`sys.executable` ambivalent** : la commande est construite avec `sys.executable` (`utils.py:390,404`). Correct depuis le process `python-real` d'Agent_CLI, mais `_proposeRepair` reconstruit la commande **dans le process Slicer** (`Agent.py:1015-1068`) où `sys.executable` est le lanceur Slicer - la commande « réparée » peut donc invoquer le mauvais interpréteur.
5. **UI vs code** : le combo propose « Ask (Interactive) » (`Agent.ui:194`) mais la doc/CLI parlent de « Consultant » (`Agent_CLI.xml:32`, README:917) ; seul le test `== "Agent (Automated)"` compte (`Agent_CLI.py:86`). Le bouton caché `RunButton` (« Run module », `Agent.ui:438-474`) n'est connecté nulle part dans `Agent.py` (vestige). La description XML du paramètre `temp_folder` est un copier-coller erroné (« Agent (Automated) or Consultant », `Agent_CLI.xml:39`).
6. **Manifeste incohérent par endroits** : `autocrop3d.box_Size` est déclaré `bool` avec la description « ROI box size in physical coordinates » (`manifest.yaml:225-229`) ; `mri2cbct_resample.center` est un `bool` décrit comme « Interpolation method: linear, nearest, etc. » (`manifest.yaml:700-703`) ; `amasss_cli.temp_fold` décrit comme « Path to log file » (`manifest.yaml:115-118`). Ces descriptions nourrissent directement le LLM : elles induisent des extractions fausses.
7. **UI gelée pendant l'exécution** : `subprocess.run` de l'outil réel est **synchrone dans le thread GUI** (`Agent.py:962`) - Slicer se fige pendant des jobs d'imagerie potentiellement longs, sans bouton d'annulation.
8. **Sécurité / confidentialité** : pas de clé API (tout est local, point positif), mais (a) le binaire Ollama est téléchargé depuis ollama.com et exécuté **sans vérification de checksum/signature** (`Agent.py:119-151`), avec suppression de la quarantaine Gatekeeper sur macOS (`Agent.py:146-150`) ; (b) l'historique de conversation complet passe **en argument de ligne de commande** du CLI (`Agent.py:794`), visible dans la liste des processus ; (c) les paramètres proposés par le LLM sont exécutés après un simple Oui/Non - sans `shell=True` (risque d'injection shell limité) mais sans vérification d'existence des chemins.
9. **Divers** : la sauvegarde du chat atterrit toujours dans le home sans dialogue de choix (`Agent.py:1078`) ; `AgentLogic.process` utilise `wait=False` puis lit immédiatement `GetOutputText()` - résultat toujours vide (`Agent.py:1336-1337`) ; la police `'Courier New'` subsiste dans `Agent.ui:305` malgré le commit « FIX : removed Courrier New font » ; le cross-encoder nécessite un téléchargement HuggingFace au premier run (non couvert par le bouton *Check*).

## Avis - entrées/sorties à ajouter ou retirer

- **Ajouter** : un sélecteur de dossier classique (`ctkPathLineEdit`) en complément de la drop-zone (la drop-zone seule est peu découvrable et non scriptable) ; un champ « dossier de sortie » explicite plutôt que de laisser le LLM le deviner du prompt ; une vérification `os.path.exists()` des paramètres `path` avant le dialogue de confirmation ; un choix du modèle Ollama dans l'UI (aujourd'hui uniquement via `ROUTER_MODEL`) ; un fichier de sortie pour la commande JSON (traçabilité/reproductibilité des runs) ; un bouton d'annulation et une exécution asynchrone (QProcess) de l'outil piloté.
- **Retirer/corriger** : la sentinelle `'nothing'` dans `folders` (remplacer par un vrai paramètre optionnel) ; le `RunButton` mort de l'UI ; le passage de l'historique en argument CLI (préférer un fichier temporaire) ; les entrées `temp_fold/log_path` dupliquées dans le manifeste (déjà injectées automatiquement, elles ne devraient pas être déclarées `required: true`).
- **Cohérence** : aligner « Ask (Interactive) » / « Consultant » ; implémenter ou retirer `cli_style: ui_module` ; adapter `resolve_tool_path` au layout réel du dépôt (dossiers par module) ou documenter `AGENT_CLI_TOOLS_DIR` comme obligatoire en développement.
