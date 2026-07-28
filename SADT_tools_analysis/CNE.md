# CNE

## Rôle

CNE (« Clinical Notes Extraction ») est un module Slicer qui produit des résumés / extractions structurées (paires clé-valeur) à partir de notes cliniques textuelles, via un LLM local exécuté avec `llama-cpp-python` (modèles GGUF fine-tunés, téléchargés depuis Hugging Face). Le helpText le décrit comme un outil pour « create summaries of clinical notes » (`CNE/CNE.py:147-150`). Deux domaines sont supportés : **TMJ** (articulation temporo-mandibulaire) et **Ortho** (orthodontie). CNE remplace l'ancien module MedX (`CMakeLists.txt:42-44` : « Replaced by CNE », MedX commenté ; le README documente encore MedX et jamais CNE, `README.md:41`).

Architecture : le widget `CNEWidget` (`CNE/CNE.py:177`) collecte les paramètres, télécharge le modèle si absent (`CNELogic.getModelPath`, `CNE/CNE.py:478-552`), puis lance le CLI scripté `CNE_CLI` (`CNE/CNE.py:580-589`) qui fait l'extraction de texte, l'inférence LLM et l'écriture des fichiers (`CNE_CLI/CNE_CLI.py:84-259`).

## Entrées

| Nom | Type | Extensions acceptées | Fichier/Dossier | Récursif | Obligatoire | Référence |
|---|---|---|---|---|---|---|
| `notesFolder_input` | Dossier de notes cliniques | `.txt`, `.pdf`, `.docx` (minuscules uniquement, cf. Incohérences) | Dossier uniquement (`ctkPathLineEdit::Dirs`) | Non | Oui | `CNE/CNE.ui:78-85`, `CNE_CLI/CNE_CLI.py:24`, `CNE_CLI/CNE_CLI.py:131-133` |
| `notesType` | Choix radio `TMJ` / `Ortho` | — | — | — | Oui (défaut `TMJ`) | `CNE/CNE.ui:98-110`, `CNE/CNE.py:171`, `CNE/CNE.py:377-382` |
| `notesFolder_output` | Dossier de sortie | — (créé si absent) | Dossier uniquement (`ctkPathLineEdit::Dirs`) | — | Oui | `CNE/CNE.ui:132-139`, `CNE/CNE.py:578` |
| `modelPath` (CLI, auto) | Modèle GGUF | `.gguf` | Fichier unique, résolu automatiquement par le widget | — | Oui (téléchargé automatiquement) | `CNE_CLI/CNE_CLI.xml:39-43`, `CNE/CNE.py:478-552` |

Détails :

- **Extensions réellement acceptées** : la constante `SUPPORTED_EXTENSIONS = (".txt", ".pdf", ".docx")` (`CNE_CLI/CNE_CLI.py:24`) pilote un scan `glob.glob(os.path.join(notesFolder_input, f"*{ext}"))` (`CNE_CLI/CNE_CLI.py:131-133`). Le scan est **non récursif** (pas de `**`, pas de `recursive=True`) : seuls les fichiers à la racine du dossier sont traités. Le dispatch de lecture est fait par extension : PDF via PyMuPDF/`fitz` (`CNE_CLI/CNE_CLI.py:53-62`), DOCX via `python-docx` (`CNE_CLI/CNE_CLI.py:65-70`), tout le reste lu comme texte UTF-8 (`CNE_CLI/CNE_CLI.py:73-81`). Le texte est normalisé (guillemets typographiques, tirets, NBSP, lignes vides) par `clean_text` (`CNE_CLI/CNE_CLI.py:29-50`).
- **Modèles IA** (téléchargés dans `Documents/<AppName>Downloads/CNE/model/`, `CNE/CNE.py:499-510`) :
  - Ortho : `https://huggingface.co/dcbia/Meta-Llama-3.1-8B-Instruct-Ortho/resolve/main/model-q4_0.gguf`, sauvegardé sous `Meta-Llama-3.1-8B-Ortho.gguf` (~4,7 Go) (`CNE/CNE.py:483-486`, URL construite en `CNE/CNE.py:496`).
  - TMJ : `https://huggingface.co/dcbia/Qwen-2.5-7B-Instruct-TMJ/resolve/main/qwen-ft-q4_k_m.gguf`, sauvegardé sous `Qwen-2.5-7B-TMJ.gguf` (~4,4 Go) (`CNE/CNE.py:489-493`).
  - Téléchargement avec `urllib.request.urlretrieve` + `QProgressDialog` annulable ; fichier partiel supprimé en cas d'échec (`CNE/CNE.py:536-550`).
- **Dépendances pip** installées à la demande au clic sur Run : `llama-cpp-python` (roue CPU via `--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu`), `pymupdf`, `python-docx` (`CNE/CNE.py:61-64`, `CNE/CNE.py:93-100`).
- **Fichiers de test** : le bouton « Download Test Files » copie `Resources/testfiles/input_{TMJ,Ortho}` (2 fichiers `.txt` chacun) vers `Documents/<AppName>Downloads/CNE/testfiles/<type>/` et remplit les deux champs de chemins (`CNE/CNE.py:409-476`, `CNE/CNE.py:305-318`).
- **Paramètres d'inférence** : contexte 6144 tokens pour TMJ, 2048 pour Ortho (`CNE_CLI/CNE_CLI.py:150-153`) ; `max_tokens=500`, `temperature=0.1` (`CNE_CLI/CNE_CLI.py:197-201`) ; prompt système `INSTRUCTION_TMJ` uniquement pour TMJ (`CNE_CLI/CNE_CLI.py:22`, `CNE_CLI/CNE_CLI.py:193-194`).

## Sorties

| Sortie | Format | Nommage | Cardinalité | Référence |
|---|---|---|---|---|
| Fichier d'extraction par note | `.txt` (UTF-8), lignes `clé : valeur` ou texte brut du LLM | `Extraction_<basename_sans_ext>.txt` dans `notesFolder_output` | 1 par fichier d'entrée supporté (N entrées → ≤ N sorties ; les fichiers en erreur sont sautés) | `CNE_CLI/CNE_CLI.py:226-230`, `CNE_CLI/CNE_CLI.py:235-239` |
| Modèle GGUF téléchargé (effet de bord) | `.gguf` | `Documents/<AppName>Downloads/CNE/model/{Meta-Llama-3.1-8B-Ortho.gguf,Qwen-2.5-7B-TMJ.gguf}` | 1 par type de notes utilisé, persistant entre les sessions | `CNE/CNE.py:499-513` |
| Fichiers de test copiés (effet de bord, bouton dédié) | `.txt` | `Documents/<AppName>Downloads/CNE/testfiles/<type>/input_<type>/` | 2 fichiers par type | `CNE/CNE.py:425-462` |

Détails :

- **Contenu** : la réponse du LLM est post-traitée. Si un bloc JSON `{...}` est trouvé, il est parsé, la clé `"extraction"` est dépliée si présente, et chaque paire est écrite `f"{key} : {value}\n"` (`CNE_CLI/CNE_CLI.py:205-218`). Sinon (pas de JSON ou JSON invalide), la réponse brute est écrite telle quelle (`CNE_CLI/CNE_CLI.py:219-224`). La structure JSON originale n'est donc **jamais conservée** sur disque.
- **Nommage** : `output_filename = f"Extraction_{os.path.splitext(filename)[0]}.txt"` (`CNE_CLI/CNE_CLI.py:226`). La sortie est toujours `.txt`, quelle que soit l'extension d'entrée — donc `note1.pdf` et `note1.txt` dans le même dossier produisent le **même** fichier `Extraction_note1.txt` (écrasement silencieux, voir Incohérences).
- **Variations selon options** : `notesType` ne change pas le format ni le nommage des sorties ; il change seulement le modèle utilisé, la taille de contexte et la présence du prompt système. Il n'existe aucune autre option influençant les sorties.
- **Aucune sortie MRML** : rien n'est chargé dans la scène Slicer ; le CLI ne retourne aucun paramètre de sortie déclaré dans le XML (`CNE_CLI/CNE_CLI.xml:13-45`, tous les paramètres sont des `<string>` d'entrée).
- **Dossier de sortie créé** par le widget avant lancement : `os.makedirs(notesFolder_output, exist_ok=True)` (`CNE/CNE.py:578`).

## Comportement dossier vs fichier

- L'entrée est **exclusivement un dossier** : le champ UI est filtré `ctkPathLineEdit::Dirs` (`CNE/CNE.ui:79-81`) et le CLI fait un `glob` sur le dossier (`CNE_CLI/CNE_CLI.py:132-133`). Il est impossible de sélectionner un fichier unique.
- Le scan est **non récursif** : les sous-dossiers sont ignorés silencieusement.
- Dossier vide ou sans fichier supporté : simple warning dans le log CLI puis `sys.exit(0)` avec progression forcée à 100 % (`CNE_CLI/CNE_CLI.py:135-139`) — le widget affichera quand même « Notes extraction is complete! » (`CNE/CNE.py:605-607`) sans qu'aucun fichier n'ait été écrit.
- La sortie est également un dossier ; les sorties y sont écrites à plat, sans reproduction d'arborescence (il n'y en a pas, faute de récursion).

## Incohérences et pièges observés dans le code

1. **Dossiers de test de sortie manquants** : `copyTestFiles` tente de copier `output_Ortho` / `output_TMJ` (`CNE/CNE.py:440-443`) mais seuls `input_Ortho` et `input_TMJ` existent dans `CNE/Resources/testfiles/` — la copie est sautée avec un warning (`CNE/CNE.py:452-454`) et le chemin de sortie renvoyé (`CNE/CNE.py:473-476`) puis injecté dans l'UI (`CNE/CNE.py:317`) pointe vers un dossier inexistant (rattrapé de justesse par le `os.makedirs` de `CNE/CNE.py:578`).
2. **Placeholder trompeur sur le champ de sortie** : le dossier de sortie affiche « supported types: .docx / .pdf / .txt » (`CNE/CNE.ui:137`), copié-collé du champ d'entrée alors que la sortie est toujours du `.txt`.
3. **XML CLI non mis à jour depuis le template** : description « Apply a Gaussian blur to an image » (`CNE_CLI/CNE_CLI.xml:6`), contributeur « Andras Lasso (PerkLab) » (`:10`), URL de doc placeholder (`:8`), descriptions de paramètres absurdes (« Replace to add to file names », `:29` ; « by to file names », `:36`), et index de paramètres discontinus 0, 2, 3, 4 (`:21,28,35,42` — l'index 1 manque).
4. **Casse des extensions** : `glob.glob("*.txt")` est sensible à la casse sous Linux/macOS — `NOTE.TXT`, `note.PDF`, `note.Docx` sont silencieusement ignorés (`CNE_CLI/CNE_CLI.py:131-133`). `.doc` (ancien Word) n'est pas géré du tout, alors que le placeholder dit « .docx ».
5. **Collision de noms de sortie** : deux entrées de même nom de base et d'extensions différentes écrasent la même sortie `Extraction_<nom>.txt` sans avertissement (`CNE_CLI/CNE_CLI.py:226-230`).
6. **`notesType` non validé** : `process()` ne bloque que si les dossiers manquent (`CNE/CNE.py:558`) — `notesType` est ajouté à la liste `missing` (`:562-563`) mais ce bloc n'est jamais atteint si seuls les dossiers sont renseignés. Un `notesType` vide (aucun radio coché, `CNE/CNE.py:381-382`) atteint `getModelPath` où ni `repo_id` ni `fileName` ne sont définis → `UnboundLocalError` brut (`CNE/CNE.py:482-496`, pas de branche `else`).
7. **Bouton Run toujours actif** : `_checkCanApply` active inconditionnellement le bouton (`CNE/CNE.py:298-302`), aucune validation des champs côté UI.
8. **Succès affiché même sans traitement** : dossier vide ⇒ `exit(0)` (`CNE_CLI/CNE_CLI.py:135-139`) ⇒ popup « Notes extraction is complete! » (`CNE/CNE.py:605-607`) ; de même, des fichiers individuellement en échec (`failed_files`, `CNE_CLI/CNE_CLI.py:235-239`) n'empêchent pas le statut « Completed ».
9. **Pas de vérification d'intégrité du modèle** : un `.gguf` tronqué (crash, coupure réseau ayant contourné le nettoyage) est réutilisé tel quel puisque seul `os.path.exists` est testé (`CNE/CNE.py:513`).
10. **README obsolète** : le README de l'extension documente MedX (« Summarize clinical notes », `README.md:41`) et ne mentionne jamais CNE, alors que MedX est désactivé dans le build (`CMakeLists.txt:42-44`).
11. **Prompt système uniquement pour TMJ** : `INSTRUCTION_TMJ` n'a pas d'équivalent Ortho (`CNE_CLI/CNE_CLI.py:22`, `:193-194`) — voulu (modèle Ortho fine-tuné sans système ?) mais non documenté.

## Avis — entrées/sorties à ajouter ou retirer

- **Ajouter une option « fichier unique »** ou accepter un chemin de fichier en entrée : pour résumer une seule note, l'utilisateur doit aujourd'hui créer un dossier dédié.
- **Ajouter un scan insensible à la casse** (et éventuellement une option récursive) : trivial à corriger (`glob` sur `ext.lower()` du listing du dossier) et élimine des pertes silencieuses de fichiers.
- **Ajouter une sortie structurée consolidée** (JSON ou CSV : une ligne/objet par note) : le CLI parse déjà le JSON du LLM (`CNE_CLI/CNE_CLI.py:207-217`) puis en détruit la structure ; conserver un `extractions.json` global rendrait les résultats exploitables en aval (statistiques, tableau de bord type MedX).
- **Ajouter un suffixe désambiguïsant au nommage** (ex. `Extraction_note1_pdf.txt`) ou au minimum un avertissement en cas d'écrasement.
- **Ajouter une entrée optionnelle « chemin de modèle local »** dans l'UI : `modelPath` existe déjà côté CLI (`CNE_CLI/CNE_CLI.xml:39-43`) mais n'est pas exposé ; utile hors-ligne ou pour tester d'autres GGUF, et ajouter une vérification de taille/checksum du modèle téléchargé.
- **Retirer** : le placeholder « supported types… » du champ de sortie (`CNE/CNE.ui:137`) et le contenu template du XML CLI ; retirer (ou implémenter) la copie des dossiers `output_*` de test inexistants (`CNE/CNE.py:440-443`).
- **Ajouter un rapport de fin** (n traités / n échoués) remonté à l'UI plutôt que seulement dans les logs CLI (`CNE_CLI/CNE_CLI.py:240-243`), et un code de sortie non nul quand `failed_files` n'est pas vide ou qu'aucun fichier n'a été trouvé.
