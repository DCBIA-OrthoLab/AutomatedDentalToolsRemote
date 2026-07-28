# MedX (⚠️ non compilé : commenté dans le CMakeLists racine)

> **Statut d'enregistrement** : dans le `CMakeLists.txt` racine, les lignes `add_subdirectory(MedX)` et `add_subdirectory(MedX_CLI)` sont **commentées** (`CMakeLists.txt:43-44`), précédées du commentaire `# Replaced by CNE` (`CMakeLists.txt:42`). MedX n'est donc **pas compilé dans l'extension officielle** — il a été remplacé par le module CNE (`add_subdirectory(CNE)` / `CNE_CLI`, `CMakeLists.txt:51-52`). Le code reste présent et complet dans le dépôt.

## Rôle

MedX est un outil d'**analyse de notes cliniques par LLM**, en deux étapes indépendantes exposées dans le même panneau (`MedX/Resources/UI/MedX.ui`) :

1. **Summarize** : résume des notes cliniques de patients (`.docx`/`.pdf`/`.txt`) avec un modèle **BART** (HuggingFace Transformers) fine-tuné pour extraire des paires clé-valeur sur les symptômes/diagnostics ; le prompt est `"Using the following note, extract structured key-value pairs about the patient's symptoms and diagnoses:"` (`MedX_CLI/MedX_Summarize/MedX_Summarize.py:50`). Le modèle est chargé via `BartTokenizer/BartForConditionalGeneration.from_pretrained` (`MedX_CLI/MedX_CLI_utils/utils.py:32-33`). Cette étape s'exécute dans un **environnement conda dédié nommé `summaries`** (Python 3.12) créé via SlicerConda (`MedX/MedX.py:1364`, `1388`), et non dans le Python de Slicer.
2. **Dashboard** : agrège les résumés `*_summary.txt` produits par l'étape 1 (~56 clés attendues de type TMJ : `patient_age`, `headache_intensity`, `disc_displacement`, etc., `MedX_CLI/MedX_CLI_utils/dashboard_utils.py:350-407`) et génère une **figure matplotlib de tableau de bord** + CSV. Cette étape s'exécute via `slicer.cli.run` dans le Python de Slicer (`MedX/MedX.py:938-942`).

## Entrées

### Volet « Summarization »

| Entrée | Widget (.ui) | Type | Extensions acceptées | Fichier/Dossier | Récursif |
|---|---|---|---|---|---|
| Notes cliniques | `LineEditClinicalNotes` (`MedX.ui:207`) | dossier | `.docx`, `.pdf`, `.txt` | dossier uniquement | UI : oui / CLI : **non** (voir incohérences) |
| Modèle BART | `LineEditModel` (`MedX.ui:197`) | dossier | doit contenir au moins un fichier `*safetensors` | dossier uniquement | oui |
| Dossier de sortie | `LineEditOutput` (`MedX.ui:240`) | dossier | — | dossier | — |

- Tous les sélecteurs passent par `QFileDialog.getExistingDirectory` — **aucune sélection de fichier unique n'est possible** (`MedX/MedX.py:441-459`).
- Extensions notes : validées côté module par `TestFile`/`NbScan` avec `['.docx', '.pdf', '.txt']` (`MedX/MedX_Method/summarize.py:26`, `:36`) via `Method.search()` qui fait un glob **récursif** `path/**/*` (`MedX/MedX_Method/Method.py:112-121`). Le placeholder de l'UI annonce les mêmes types (`MedX.ui:212`).
- Côté CLI, le filtre est réappliqué : `file_name.endswith(".pdf"/".docx"/".txt")` (`MedX_CLI/MedX_Summarize/MedX_Summarize.py:71`), mais sur `os.listdir` **non récursif** (`:70`).
- Validation modèle : `TestModel` exige un fichier se terminant par `safetensors` dans le dossier (`MedX/MedX_Method/summarize.py:47-52`).
- **Modèle IA téléchargeable** (bouton `DownloadModel`) : `https://github.com/DCBIA-OrthoLab/SlicerAutomatedDentalTools/releases/download/MedX/BART.zip` (`MedX/MedX_Method/summarize.py:40-45`), dézippé dans `~/Documents/<AppName>Downloads/MedX/` (`MedX/MedX.py:386-392`).
- **Aucune clé API** : le LLM tourne entièrement en local (CPU ou CUDA, `MedX_Summarize.py:32`).
- Dépendances installées dans l'env conda `summaries` : transformers, torch, pymupdf, python-docx, evaluate, scikit-learn, peft, bitsandbytes, matplotlib (`MedX/MedX.py:849-857`).
- Paramètre caché : `log_path` = `<tempSlicer>/process.log`, utilisé pour la barre de progression (`MedX/MedX.py:384`).

### Volet « Dashboard »

| Entrée | Widget (.ui) | Type | Extensions acceptées | Fichier/Dossier | Récursif |
|---|---|---|---|---|---|
| Dossier de résumés | `lineEditSummaries` (`MedX.ui:355`) | dossier | fichiers `*_summary.txt` uniquement (insensible à la casse) | dossier | **non** |
| Dossier de sortie | `lineEditOutDashboard` (`MedX.ui:372`) | dossier | — | dossier | — |
| Option « Load image in Slicer » | `DisplayDashboard` (case cochée par défaut, `MedX.ui:389-399`) | booléen | — | — | — |

- Le CLI Dashboard ne lit **que** les fichiers `*_summary.txt` par `os.listdir` non récursif (`MedX_CLI/MedX_CLI_utils/display_figure.py:44-46`) ; l'identifiant patient est déduit de `file_name.split("_")[0]` (`display_figure.py:46`).
- Dépendances installées dans le Python de Slicer : `numpy<2.0.0`, `pandas`, `matplotlib` (`MedX/MedX.py:903-905`).
- Les CLI déclarent leurs paramètres comme simples `string` positionnels dans les XML : `input_notes`, `input_model`, `output_folder`, `log_path` (`MedX_CLI/MedX_Summarize/MedX_Summarize.xml:18-44`) et `summary_folder`, `output_folder`, `log_path` (`MedX_CLI/MedX_Dashboard/MedX_Dashboard.xml:18-37`).

## Sorties

### Summarize

| Fichier | Format | Nommage | Cardinalité |
|---|---|---|---|
| `<output>/<patient_id>_summary.txt` | texte brut (résumés des chunks séparés par une ligne de 100 tirets) | `<patient_id>_summary.txt` où `patient_id = nom_fichier.split("_")[0]` | **1 par patient** (pas par fichier : plusieurs fichiers `ID_*.ext` sont concaténés avant résumé) |
| `log_path` (process.log) | texte (un entier) | fixe | 1, réécrit après chaque patient |

- Écriture : `MedX_CLI/MedX_Summarize/MedX_Summarize.py:92-96` (nommage et cardinalité), regroupement multi-fichiers par patient `:70-91`, log de progression `:98-99`.
- Le séparateur inter-chunks est défini à `MedX_Summarize.py:64`.
- Les sorties sont **écrasées silencieusement** si elles existent déjà (ouverture en `'w'`).

### Dashboard

| Fichier | Format | Nommage | Cardinalité |
|---|---|---|---|
| `<output>/dashboard.png` | image PNG (figure matplotlib 22×14 pouces, ~15 graphiques) | fixe | 1 |
| `<output>/patient_data.csv` | CSV (1 ligne par patient, ~57 colonnes) | fixe | 1 |
| `<output>/dashboard_full_dataframe.csv` | CSV (même dataframe) | fixe | 1 |

- `dashboard.png` et `patient_data.csv` : `MedX_CLI/MedX_CLI_utils/display_figure.py:678-680`.
- `dashboard_full_dataframe.csv` : écrit dans `generate_dashboard_figure` (`display_figure.py:187-188`) — c'est un **doublon quasi exact** de `patient_data.csv` (seule différence : `patient_data.csv` est écrit après ajout des colonnes dérivées `pain_onset_months` / `age_bin` par `set_pain_onset_data`, `dashboard_utils.py:215-218`).
- Variation selon options : la case `DisplayDashboard` ne change **pas** les fichiers produits ; elle charge seulement `dashboard.png` comme volume dans la vue Red de Slicer après le run (`MedX/MedX.py:952-973`, `:1284-1286`).

## Comportement dossier vs fichier

- **Entrées exclusivement en dossiers** ; aucun mode « fichier unique ».
- **Écart récursif/non-récursif** : le comptage UI (`NbScan`) parcourt le dossier de notes **récursivement** (`Method.py:116-118`), mais le CLI Summarize ne traite que le **premier niveau** (`os.listdir`, `MedX_Summarize.py:70`). Avec des sous-dossiers, la barre de progression annonce plus de fichiers qu'il n'en sera traité, et des notes sont ignorées sans avertissement.
- Le Dashboard est cohérent (non récursif des deux côtés), mais `NbScan` du dashboard compte les `.docx/.pdf/.txt` récursivement (`MedX/MedX_Method/dashboard.py:35-38`) alors que le CLI ne lit que les `*_summary.txt` du premier niveau — le compteur de progression est donc faux dès que le dossier contient autre chose.
- Regroupement patient : tout fichier dont le préfixe avant le premier `_` est identique est fusionné dans un seul résumé (`MedX_Summarize.py:73-76`).

## Incohérences et pièges observés dans le code

1. **Module désactivé** : commenté dans `CMakeLists.txt:42-44` (« Replaced by CNE »). CNE (`CNE/`, `CNE_CLI/`) est le successeur actif ; MedX est de fait du **code hérité**.
2. **Erreur de validation non bloquante (Summarize)** : si `TestProcess` retourne une erreur, elle est affichée mais l'exécution **continue** — pas de `return` après le warning (`MedX/MedX.py:875-877`), contrairement au Dashboard qui retourne bien (`:918-920`).
3. **Résultat de `onCheckRequirements` ignoré** : `check_env = self.onCheckRequirements(...)` n'est jamais testé (`MedX/MedX.py:860`) ; si conda/WSL est absent la fonction retourne `False` mais le flux continue et plantera plus loin.
4. **`MedX_Dashboard.py` importe `torch`** (`MedX_CLI/MedX_Dashboard/MedX_Dashboard.py:3`) alors qu'il ne l'utilise pas, et torch n'est **pas** dans la liste installée pour le dashboard (`MedX/MedX.py:903-905`) → le CLI Dashboard plantera à l'import dans un Slicer sans torch.
5. **Progression du Dashboard morte** : le CLI reçoit `log_path` (`MedX_Dashboard.xml:33-37`) mais ne l'écrit jamais ; `DisplayMedX.isProgress` surveille ce fichier (`MedX/MedX_Method/Progress.py:54-61`) → la barre de progression ne bouge jamais pendant le dashboard.
6. **Progression du Summarize incohérente** : le log compte les **patients** (`idx+1`, `MedX_Summarize.py:99`) mais `nb_scans` compte les **fichiers** (`summarize.py:35-38`) → barre < 100 % si plusieurs fichiers par patient.
7. **Restes de template Slicer** : `updateParameterNodeFromGUI` référence `inputSelector`, `outputSelector`, `imageThresholdSliderWidget`, `invertOutputCheckBox`, `invertedOutputSelector` (`MedX/MedX.py:756-760`) — **aucun de ces widgets n'existe** dans `MedX.ui` (crash si appelé ; il n'est jamais connecté). Idem `registerSampleData` qui télécharge des `.nrrd` de test Slicer génériques (`MedX/MedX.py:206-235`) avec des vignettes `MedX1.png`/`MedX2.png` **absentes** du dossier Icons (seul `MedX.png` existe). `helpText`/`acknowledgement` sont les placeholders du template (`:174-182`).
8. **Code mort** : `extract_key_value_pairs` et `save_dict_to_csv` (`MedX_CLI/MedX_CLI_utils/utils.py:227-268`) ne sont appelés nulle part ; `UpdateProgressBar` affiche « Matrix applied with success » (`MedX/MedX.py:1251`), copié-collé du module AutoMatrix ; la classe UI s'appelle d'ailleurs `Matrix_bis` (`MedX.ui:3-4`). La ligne 81 de `dashboard_utils.py` (`return no_migraine_headache_pct, ...`) est inatteignable et référence des variables inexistantes.
9. **Code obscur** : dans `generate_dashboard_figure`, un bloc `inspect.currentframe()` récupère `output_folder`… qui est déjà un paramètre de la fonction (`display_figure.py:177-186`) — inutile.
10. **Fichier de sortie commité par erreur** : `MedX_CLI/dashboard_full_dataframe.csv` (données dashboard réelles) traîne à la racine de `MedX_CLI/`.
11. **Division par zéro potentielle** : `OnEndProcess` calcule `total_time / self.nb_scans` (`MedX/MedX.py:1289`) → crash si le dossier de notes est vide.
12. **Deux mécanismes d'exécution différents** : Summarize passe par conda (`run_conda_tool`, `MedX/MedX.py:1079-1117`, commande `python -m MedX_Summarize` `:1083`) alors que le dict de process contient quand même `"Process": slicer.modules.medx_summarize` jamais utilisé (`summarize.py:86-94`) ; Dashboard passe par `slicer.cli.run` (`MedX/MedX.py:938`). Déroutant pour la maintenance.
13. **Deux systèmes d'installation de libs** : `install_function` module-level attend des tuples `(lib, contrainte, url)` (`MedX/MedX.py:89-98`, utilisé par le Dashboard `:903-907`), tandis que Summarize passe une liste de strings à l'env conda (`:849-864`). Dans `install_function`, le `return True` est dans la boucle `try` (`:142`) et le bloc `installation_errors` (`:146-150`) est quasi inatteignable.

## Avis — entrées/sorties à ajouter ou retirer

- **À retirer** : le doublon `dashboard_full_dataframe.csv` (garder `patient_data.csv` seul) ; le paramètre `log_path` du CLI Dashboard (jamais utilisé) ou alors l'implémenter ; le code template (sample data, `updateParameterNodeFromGUI`, `extract_key_value_pairs`, `save_dict_to_csv`) ; le CSV commité dans `MedX_CLI/`.
- **À ajouter (entrées)** : un vrai scan récursif dans le CLI Summarize (ou retirer la récursivité de `NbScan`) pour aligner comptage et traitement ; une option de motif d'ID patient (le `split("_")[0]` est implicite et non documenté dans l'UI) ; une validation bloquante des entrées (corriger le `return` manquant).
- **À ajouter (sorties)** : un fichier de statut/rapport (nb de patients traités, fichiers ignorés) ; horodater ou protéger contre l'écrasement des `_summary.txt` ; exposer le format du dashboard (PNG seul aujourd'hui — un PDF/SVG serait utile).
- Si l'outil doit rester dans le dépôt en tant que remplacé par CNE, l'idéal serait de le supprimer ou de documenter clairement son statut déprécié.
