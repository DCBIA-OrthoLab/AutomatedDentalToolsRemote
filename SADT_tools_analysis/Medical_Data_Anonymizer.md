# Medical Data Anonymizer

> Code analysé : `Medical_Data_Anonymizer_Module/Medical_Data_Anonymizer_Module.py` (767 lignes, module unique, **aucun fichier `.ui`** - toute l'interface est construite par code dans `setup()`, lignes 49–160). Aucune classe Logic réelle : `Medical_Data_Anonymizer_ModuleLogic` est vide (`pass`, lignes 763–764) ; tout le traitement est dans le Widget.

## Rôle

Anonymisation de **documents texte** (comptes rendus, notes cliniques) par détection d'entités PII/PHI avec **Microsoft Presidio** (`presidio-analyzer` / `presidio-anonymizer`, importés lignes 464–465) et le modèle spaCy `en_core_web_lg` (installé lignes 411–413). Le module scanne un dossier d'entrée, extrait le texte de chaque document, applique la méthode d'anonymisation choisie (replace / redact / hash / mask, lignes 721–737) et réécrit un fichier par document dans le dossier de sortie, plus un CSV de correspondance.

**Important : malgré son nom, ce module ne traite AUCUNE image médicale.** Pas de DICOM, pas de NIfTI, pas de NRRD - le filtre d'extensions (ligne 506) n'accepte que `.docx, .txt, .pdf, .csv, .xml, .odt`. Le `helpText` du module est d'ailleurs honnête : *"This module anonymizes text files using Presidio."* (ligne 44).

## Entrées

| Entrée | Widget | Type | Formats acceptés | Obligatoire | Défaut |
|---|---|---|---|---|---|
| Files to be Anonymized | `ctkPathLineEdit` (filtre `Dirs`) | **Dossier uniquement** | `.docx`, `.txt`, `.pdf`, `.csv`, `.xml`, `.odt` (scan **récursif**) | Oui (ligne 446) | - |
| Output Anonymized Files | `ctkPathLineEdit` (filtre `Dirs`) | Dossier | - | Oui (ligne 454) | - |
| 12 cases à cocher d'entités | `QCheckBox` | booléens | - | ≥ 1 cochée (ligne 478) | 7 cochées |
| Anonymization Method | `QComboBox` | choix | `replace` / `redact` / `hash` / `mask` | Non | `replace` |
| Confidence Threshold | `ctkSliderWidget` | float 0.0–1.0 | - | Non | 0.5 (ligne 133) |

- **Dossier d'entrée** : `ctkPathLineEdit` avec `filters = ctk.ctkPathLineEdit.Dirs` (lignes 69–70). Il est **impossible de sélectionner un fichier unique**.
- **Scan récursif** : `os.walk(input_folder)` (ligne 504) parcourt toute l'arborescence. Filtre : `file.endswith((".docx", ".txt", ".pdf", ".csv", ".xml", ".odt")) and not file.startswith("~$")` (ligne 506) - les fichiers de verrouillage Word (`~$xxx.docx`) sont exclus. **Ni DICOM ni NIfTI ne sont acceptés** (aucune mention de `.dcm`, `.nii`, `pydicom` ou `SimpleITK` dans le module).
- **Extraction du texte selon le format** :
  - `.docx` : uniquement `doc.paragraphs` (ligne 538) - les **tableaux, en-têtes et pieds de page Word ne sont pas lus** ;
  - `.txt` : lecture UTF-8 intégrale (lignes 541–542) - un fichier en Latin-1 lèvera `UnicodeDecodeError` ;
  - `.pdf` : `pdfplumber` page par page (lignes 548–552), repli sur `extract_tables()` en cas d'erreur (lignes 556–562), **pas d'OCR** (un PDF scanné donne un texte vide) ;
  - `.csv` : les cellules de chaque ligne sont **jointes par des espaces** (ligne 572), la structure en colonnes est perdue dès la lecture ;
  - `.xml` : extraction récursive de `element.text` et `child.tail` uniquement (lignes 752–761) - les **attributs XML ne sont jamais lus** ;
  - `.odt` : seuls les nœuds texte **directement enfants** des paragraphes `text:P` (lignes 584–588) - le texte dans des `text:span` (gras, couleur… fréquent pour les noms) est ignoré.
- **Entités anonymisées** (lignes 90–103, cochées par défaut en gras) : **PERSON**, **PHONE_NUMBER**, **EMAIL_ADDRESS**, **DATE_TIME**, **LOCATION**, **US_SSN**, **MEDICAL_LICENSE**, US_DRIVER_LICENSE, CREDIT_CARD, US_BANK_NUMBER, IP_ADDRESS, URL. Seules les cases cochées sont passées à Presidio (ligne 476, puis `entities=` ligne 716).
- **Langue forcée à l'anglais** : `analyzer.analyze(text=..., language='en', ...)` (ligne 715). La docstring prétend une « automatic language detection » (ligne 700) et `langdetect` est installé (ligne 405) mais **jamais importé ni utilisé**. Voir Incohérences.
- Bouton « Install Dependencies » (lignes 139–142, 392–442) : `pip_install` de presidio, pandas, python-docx, pdfplumber, odfpy, lxml, langdetect, reportlab + téléchargement du modèle spaCy `en_core_web_lg`, puis demande de redémarrer Slicer.

## Sorties

| Sortie | Format | Nommage | Cardinalité |
|---|---|---|---|
| Documents anonymisés | même extension, **sauf** `.odt` → `.txt` et `.xml` → texte brut | `<nom_original>_anonymized.<ext>` | 1 par fichier d'entrée traité sans erreur (0 en cas d'erreur) |
| `file_mappings.csv` | CSV pandas | fixe, à la racine du dossier de sortie (ligne 500) | 1 par exécution (écrasé à chaque run, ligne 671) |

- **Nommage** : `new_file_name = file.replace(".docx", "_anonymized.docx")` etc. (lignes 609, 614, 620, 626, 636, 643). **Il n'y a AUCUN renommage des patients** : le nom de fichier original est conservé, seul le suffixe `_anonymized` est ajouté. L'UUID généré ligne 531 n'est **jamais utilisé pour nommer quoi que ce soit** - il n'apparaît que dans le CSV.
- **Sortie à plat** : tous les fichiers sont écrits directement dans `output_folder` (`os.path.join(output_folder, new_file_name)`, lignes 610, 615, 621, 627, 637, 644). L'arborescence d'entrée n'est **pas reproduite** → deux fichiers homonymes dans des sous-dossiers différents **s'écrasent silencieusement** (voir Incohérences).
- **Variations de format** :
  - `.odt` → sortie **`.txt`** (ligne 643), le format n'est pas conservé (contrairement au README ligne 505 : « in the selected format ») ;
  - `.xml` → fichier portant l'extension `.xml` mais contenant du **texte brut non XML** (lignes 638–640, commentaire du code : « Save as formatted text since XML anonymization is complex ») ;
  - `.csv` → réécrit via `line.split()` (ligne 632), c'est-à-dire **découpé sur les espaces** : les colonnes d'origine sont détruites et toute cellule multi-mots est éclatée ;
  - `.pdf` → régénéré de zéro avec ReportLab `Preformatted` (lignes 686–696) : mise en page, images et tableaux d'origine perdus ;
  - `.docx` → nouveau document, un paragraphe par ligne (lignes 606–611) : styles, tableaux, en-têtes perdus.
- **Fichier de correspondance** `file_mappings.csv` (lignes 500, 648–652, 667–671) : colonnes `Original File Name`, `Anonymized File Name`, `UUID`. En cas d'erreur sur un fichier, la ligne contient `Anonymized File Name = "ERROR"` et `UUID = "Error: <message>"` (lignes 658–662). Il est **écrasé sans fusion à chaque exécution** (ligne 671).
- **Cardinalité globale** : N fichiers supportés → au plus N fichiers `_anonymized` + 1 `file_mappings.csv` (N+1). Moins en cas d'erreurs ou de collisions de noms. Le message final annonce toujours « Successfully processed N files » (ligne 678) même si des fichiers ont échoué.

## Comportement dossier vs fichier

- **Dossier obligatoire** en entrée comme en sortie (filtre `Dirs`, lignes 70 et 79). Aucun mode « fichier unique ».
- Entrée **récursive** (`os.walk`, ligne 504), sortie **à plat** : `projet/A/rapport.txt` et `projet/B/rapport.txt` produisent tous deux `rapport_anonymized.txt` au même endroit - le second écrase le premier sans avertissement, alors que le CSV de mapping listera pourtant deux lignes identiques.
- Si aucun fichier supporté n'est trouvé : boîte d'information et arrêt propre (lignes 509–515).
- **Aucune protection si dossier de sortie = dossier d'entrée** : au run suivant, les `*_anonymized.txt` et même `file_mappings.csv` (extension `.csv` acceptée !) seraient re-scannés et ré-anonymisés (`*_anonymized_anonymized.*`).

## Incohérences et pièges observés dans le code (surtout risques de fuite de données)

1. **FUITE - échec silencieux = fichier NON anonymisé livré comme anonymisé.** `anonymize_text_presidio()` retourne **le texte original** en cas d'exception Presidio (`return text  # Return original text if anonymization fails`, lignes 748–750). Le fichier est alors écrit avec le suffixe `_anonymized` et enregistré comme succès dans le mapping. C'est le pire scénario de conformité : un document plein de PHI estampillé « anonymisé ». Seule trace : une ligne de log console (ligne 749).
2. **FUITE - les noms de fichiers ne sont jamais anonymisés.** `Dupont_Jean_CR_2024.docx` devient `Dupont_Jean_CR_2024_anonymized.docx` (ligne 609). Le nom du patient survit dans le nom du fichier de sortie ET dans la colonne `Original File Name` de `file_mappings.csv`, lequel est déposé **dans le dossier de sortie destiné au partage** (ligne 500). L'UUID (ligne 531) qui aurait dû servir de nouveau nom n'est jamais exploité.
3. **FUITE - langue codée en dur `'en'`** (ligne 715) alors que la docstring annonce « automatic language detection » (ligne 700) et que `langdetect` est installé (ligne 405) mais jamais utilisé. Sur un document en français, le modèle spaCy anglais ratera une grande partie des noms/lieux → PII résiduelles massives, sans aucun avertissement.
4. **FUITE - extensions sensibles à la casse.** Le filtre `file.endswith(".txt")` (ligne 506) ignore `RAPPORT.TXT`, `scan.PDF`, etc. : ces fichiers ne sont simplement pas traités (risque d'oubli dans un lot « anonymisé »). Pire, si l'extension diffère seulement par la casse d'une partie du nom, `splitext(...).lower()` (ligne 532) et `file.replace(".txt", ...)` (ligne 614) divergent : pour `Report.TXT` accepté par un futur correctif, le `replace` échouerait et la sortie garderait **le nom d'origine sans suffixe**.
5. **FUITE potentielle dans le mapping en cas d'erreur** : le message d'exception complet est écrit dans le CSV (`"UUID": f"Error: {str(e)}"`, ligne 661) - il peut contenir des chemins complets, voire des fragments de contenu.
6. **Perte de données (pas fuite, mais faux sentiment de complétude)** : tableaux/en-têtes/pieds de page `.docx` (ligne 538), attributs `.xml` (lignes 752–761), `text:span` des `.odt` (lignes 584–588), PDF scannés sans OCR (lignes 548–552) - le contenu non extrait disparaît de la sortie. Le document « anonymisé » est donc incomplet sans que l'utilisateur le sache.
7. **Collisions de noms** : sortie à plat + scan récursif → écrasement silencieux des homonymes (voir section précédente). La cardinalité réelle peut être < N sans erreur signalée.
8. **README vs code** : le README annonce une sortie « in the selected format » (README ligne 505) - faux pour `.odt` (→ `.txt`, ligne 643) et `.xml` (texte brut, lignes 638–640). Le README vante aussi « Hash: … for consistent anonymization » ; le hash Presidio est appliqué (ligne 731) mais sans sel/clé configurée, donc ré-identifiable par dictionnaire pour des valeurs à faible entropie (dates, téléphones).
9. **`file_mappings.csv` écrasé à chaque run** (ligne 671) : deux exécutions successives vers le même dossier de sortie perdent la première table de correspondance.
10. **Message de fin trompeur** : « Successfully processed {N} files » (ligne 678) compte tous les fichiers trouvés, y compris ceux en erreur.
11. Mineur : la méthode `replace` passe `operators=None` (lignes 721–723, 743), s'appuyant sur le défaut Presidio (`<ENTITY_TYPE>`) - conforme au README mais implicite ; `mask` est plafonné à 100 caractères masqués (ligne 735).

## Avis - entrées/sorties à ajouter ou retirer

**À ajouter :**
- **Échec bloquant** : en cas d'exception Presidio, ne PAS écrire le fichier (ou l'écrire dans un sous-dossier `failed/`), le marquer en erreur dans le mapping et dans l'UI - c'est le correctif n° 1 pour la conformité.
- **Renommage par UUID** : utiliser l'`unique_id` déjà généré (ligne 531) comme nom de sortie (`<uuid>.txt`), le mapping CSV servant alors réellement de table de correspondance ancien↔nouveau nom ; stocker `file_mappings.csv` **hors** du dossier de sortie partageable (ou le protéger explicitement).
- **Chemin relatif dans le mapping + reproduction de l'arborescence** (ou préfixage) pour éliminer les collisions d'homonymes.
- **Détection de langue réelle** (le paquet `langdetect` est déjà installé) ou au minimum un sélecteur de langue + modèle spaCy correspondant, avec avertissement si le texte n'est pas anglais.
- **Filtre d'extensions insensible à la casse** et rapport final listant les fichiers ignorés/échoués.
- **Mode fichier unique** (second `ctkPathLineEdit` en mode `Files`) pour tester le paramétrage avant un lot.
- Option **append/horodatage** pour `file_mappings.csv` au lieu de l'écrasement.
- À terme, un vrai support **DICOM** (tags PatientName, PatientID, dates…) serait le complément naturel dans une extension d'imagerie - aujourd'hui le nom « Medical Data Anonymizer » laisse croire à tort que les images sont couvertes.
- Garde-fou si dossier de sortie = dossier d'entrée (ou si le dossier de sortie contient déjà des `*_anonymized.*`).

**À retirer / corriger :**
- La sortie `.xml` en texte brut avec extension `.xml` (lignes 638–640) : soit produire du vrai XML (anonymiser nœud par nœud, attributs compris), soit renommer en `.txt` comme pour l'ODT pour ne pas tromper l'aval.
- La réécriture CSV par `line.split()` (ligne 632) qui détruit les colonnes : anonymiser cellule par cellule avec le module `csv`.
- La docstring « automatic language detection » (ligne 700) et l'installation de `langdetect` (ligne 405) tant que la fonctionnalité n'existe pas.
- Le message « Successfully processed N files » (ligne 678) sans décompte des erreurs.
