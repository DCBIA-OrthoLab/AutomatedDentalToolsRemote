# Analyse des outils de SlicerAutomatedDentalTools

Analyse en profondeur des entrées/sorties de chaque outil du dépôt
[DCBIA-OrthoLab/SlicerAutomatedDentalTools](https://github.com/DCBIA-OrthoLab/SlicerAutomatedDentalTools),
basée sur la lecture du code source (widgets Slicer, fichiers `.ui`, CLI et utilitaires),
et non uniquement de la documentation.

Chaque fiche documente : le rôle de l'outil, ses entrées (types, extensions réellement
acceptées dans le code, fichier unique vs dossier), ses sorties (formats, nommage,
cardinalité entrée→sortie), le comportement réel en mode dossier, les incohérences
UI/code observées, et un avis sur les entrées/sorties à ajouter ou retirer.

Date de l'analyse : 2026-07-27 (dépôt cloné à cette date, branche par défaut).

## Fiches par outil

| Fiche | Rôle résumé |
|---|---|
| [AMASSS](AMASSS.md) | Segmentation multi-anatomique de CBCT |
| [ALI](ALI.md) | Identification automatique de landmarks (CBCT et IOS) |
| [ASO](ASO.md) | Orientation standardisée automatique (CBCT et IOS) |
| [AREG](AREG.md) | Registration automatique (CBCT/CBCT, IOS/IOS, IOS/CBCT) |
| [AutoMatrix](AutoMatrix.md) | Application de matrices de transformation en batch |
| [AutoCrop3D](AutoCrop3D.md) | Recadrage automatique de volumes en batch |
| [FlexReg](FlexReg.md) | Registration par zones de scans intra-oraux |
| [MRI2CBCT](MRI2CBCT.md) | Pipeline de registration MRI/CBCT |
| [BATCHDENTALSEG](BATCHDENTALSEG.md) | Segmentation dentaire en batch (nnUNet) |
| [DOCShapeAXI](DOCShapeAXI.md) | Classification de formes 3D par deep learning |
| [CLIC](CLIC.md) | Classification/localisation de canines incluses (Mask R-CNN sur CBCT) |
| [CNE](CNE.md) | Extraction/résumé de notes cliniques par LLM local (remplace MedX) |
| [Medical Data Anonymizer](Medical_Data_Anonymizer.md) | Anonymisation de données médicales |
| [VFACE](VFACE.md) | Méta-pipeline CBCT complet (ALI→ASO→AMASSS→AREG→mesures→classification) |
| [GreedyReg](GreedyReg.md) | Registration via Greedy |
| [Agent](Agent.md) | Agent conversationnel pilotant les modules |
| [MedX](MedX.md) | Résumé de notes cliniques (BART) - ⚠️ désactivé, remplacé par CNE |
| [SurgMovPred](SurgMovPred.md) | Prédiction de mouvement chirurgical (ML tabulaire) - ⚠️ absent du CMakeLists racine |
