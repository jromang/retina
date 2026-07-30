---
id: AssignICCProfile
category: ColorManagement
title: Attribution de profil ICC
brief: Attache un profil ICC à la fenêtre comme métadonnée, sans toucher aux pixels.
keywords: [ICC, profil couleur, métadonnée, gestion des couleurs, sRGB, littlecms, export]
related: [ICCProfileTransformation, ColorManagementSetup, RGBWorkingSpace, SampleFormatConversion]
icon: certificate
references:
  - "PixInsight — ICCProfile process reference."
  - "International Color Consortium — ICC.1:2022 (Specification ICC.1)."
  - "PIL.ImageCms (littlecms) — documentation Pillow."
---

## Résumé

`AssignICCProfile` **étiquette** une fenêtre avec un profil ICC — il enregistre simplement le
nom ou le chemin du profil dans `view.window.icc_profile`. Aucune conversion colorimétrique
n'est effectuée, aucun pixel n'est modifié : c'est une opération de **métadonnée pure**, l'analogue
du process `ICCProfile` de PixInsight (à ne pas confondre avec `ICCProfileTransformation`). Le
profil ainsi attaché sera embarqué au moment de l'export (TIFF/PNG/JPEG…) et guidera, si besoin,
une conversion ultérieure explicite.

## Cas d'usage

- **Déclarer l'espace colorimétrique** d'une image dont on sait qu'elle a été composée dans
  un espace donné (sRGB, Adobe RGB, un profil d'écran calibré…) sans avoir besoin de convertir
  les valeurs de pixels.
- **Préparer un export** : embarquer un profil dans un TIFF/PNG/JPEG pour que les logiciels tiers
  (visionneuses, réseaux sociaux, imprimeurs) interprètent correctement les couleurs.
- **Corriger une étiquette erronée** : réassigner le bon profil à une image importée sans profil,
  ou avec un profil incorrect, sans perturber le rendu déjà validé à l'écran.
- **Documenter une chaîne de traitement** avant de passer, plus tard, par une vraie conversion
  ([ICCProfileTransformation](retina-doc://ICCProfileTransformation)) vers un espace cible.

## Fonctionnement

Le process reçoit un unique paramètre `profile` — un nom connu (`sRGB`) ou un chemin vers un
fichier `.icc`/`.icm`. À l'exécution (`execute_on`), il se contente d'écrire cette chaîne dans
l'attribut `icc_profile` de la fenêtre associée à la vue (`view.window.icc_profile = self.profile`)
si la vue possède bien une fenêtre. Le tableau de pixels de l'`Image` n'est jamais parcouru :
`execute_on_image` renvoie l'image **telle quelle**, sans copie ni recalcul — le profil vit sur
la fenêtre (`ImageWindow`), pas sur les données brutes.

La résolution effective du profil (`ImageCms.createProfile("sRGB")` pour le nom réservé `sRGB`,
ou `ImageCms.getOpenProfile(path)` pour un fichier) n'intervient que plus tard, quand un autre
maillon de la chaîne (export, ou `ICCProfileTransformation`) a réellement besoin d'ouvrir le
profil via `PIL.ImageCms` (littlecms). `AssignICCProfile` lui-même ne valide donc pas l'existence
ni la validité du fichier au moment de l'assignation.

## Mathématiques

Sans objet : ce process ne réalise aucune transformation numérique sur les pixels et ne calcule
rien — c'est une simple écriture de métadonnée (une chaîne de caractères) sur l'objet fenêtre.
Il n'y a ni formule, ni matrice de conversion, ni courbe de transfert à documenter ici ; ces
notions relèvent d'[ICCProfileTransformation](retina-doc://ICCProfileTransformation), qui elle
convertit effectivement les valeurs de pixels d'un profil source vers un profil cible via
littlecms.

## Paramètres

- **`profile`** — *str*, défaut `sRGB`. Nom du profil (le mot réservé `sRGB` génère un profil
  sRGB standard via littlecms) ou chemin vers un fichier de profil `.icc`/`.icm` sur disque.
  La chaîne est stockée telle quelle sur la fenêtre ; elle n'est résolue en profil ICC concret
  que lorsqu'une autre opération (export, transformation) en a besoin.

## Astuces & pièges

> **Note** — cette opération est **non destructive au sens fort** : elle ne modifie ni les
> pixels ni même l'historique de la vue au-delà de l'attribut de fenêtre. Elle diffère donc de
> la plupart des process qui passent par `begin_process()/end_process()`.

> **Attention** — assigner un profil ne **convertit rien**. Si les pixels ont réellement été
> produits dans un espace différent de celui déclaré, les couleurs affichées ou exportées seront
> incorrectes tant qu'une vraie conversion n'aura pas été appliquée avec
> [ICCProfileTransformation](retina-doc://ICCProfileTransformation).

- Un chemin de fichier invalide n'échoue pas immédiatement : l'erreur ne surgira qu'au moment
  où un consommateur tentera d'ouvrir le profil (export, conversion). Vérifiez le chemin en amont.
- Pour changer les réglages globaux par défaut (profil de travail, intention de rendu) plutôt
  que le profil d'une seule fenêtre, utilisez
  [ColorManagementSetup](retina-doc://ColorManagementSetup).
- Les données internes de Retina sont *scene-linear* en flottant ; l'ICC ne concerne
  véritablement que le **rendu et l'export** en 8/16 bits, pas le pipeline de traitement linéaire.

## Voir aussi

- [ICCProfileTransformation](retina-doc://ICCProfileTransformation) — convertit réellement les
  pixels d'un profil source vers un profil cible.
- [ColorManagementSetup](retina-doc://ColorManagementSetup) — réglages globaux de gestion des
  couleurs (profil de travail, intention de rendu).
- [RGBWorkingSpace](retina-doc://RGBWorkingSpace) — définit l'espace RVB de travail sous-jacent.
- [SampleFormatConversion](retina-doc://SampleFormatConversion) — conversion de format
  d'échantillon, souvent utilisée en aval avant export.

## Références

- PixInsight — *ICCProfile* process reference.
- International Color Consortium — *ICC.1:2022 (Specification ICC.1)*.
- PIL.ImageCms (littlecms) — documentation Pillow.
