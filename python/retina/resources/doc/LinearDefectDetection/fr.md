---
id: LinearDefectDetection
category: ImageInspection
title: Détection de défauts linéaires
brief: Repère les colonnes et lignes dont le niveau s'écarte de leurs voisines, et en exporte la liste.
keywords: [banding, colonnes, lignes, CMOS, défauts, LPS, capteur, JSON]
related: [LinearPatternSubtraction, CosmeticCorrection, DefectMap, NoiseEvaluation]
icon: line
references:
  - "PixInsight — script LinearDefectDetection."
---

## Résumé

`LinearDefectDetection` sert à deux choses : **voir** si votre capteur produit un motif de
colonnes (les défauts sont dessinés dans le viewport), et produire la **liste** que
[LinearPatternSubtraction](retina-doc://LinearPatternSubtraction) corrigera en mode
conservateur.

Le motif est une propriété du **capteur**, pas de la pose : mesurez-le une fois, sur une pose
calibrée ou sur un master, et réutilisez la liste pour toute la série.

## Fonctionnement

Pour chaque colonne, la médiane de ses pixels — c'est-à-dire le fond de ciel à cet endroit,
étoiles et nébuleuses y étant minoritaires. On compare ensuite cette médiane à la **tendance
locale** de ses voisines (filtre médian), et l'on retient les écarts dépassant `threshold_sigma`
dispersions robustes.

Sur une image CFA non débayerisée, cochez `cfa` : une colonne sur deux voit un filtre différent,
et sans cela ce sont les écarts entre couleurs qui seraient signalés.

## Ce qu'un faux positif coûte

Rien, ou presque. Une colonne signalée à tort sera corrigée d'une valeur **inférieure au bruit**.
Le seuil n'a donc pas besoin d'être ajusté finement ; `5.0` sépare confortablement un vrai motif
(cent fois la dispersion) de la fluctuation d'une médiane de colonne.

## Paramètres

- **`columns`** / **`rows`** — *bool*, défauts `True` / `False`.
- **`threshold_sigma`** — *real*, défaut `5.0`. Seuil en dispersions robustes.
- **`cfa`** — *bool*, défaut `False`. Image CFA non débayerisée.
- **`output_path`** — *path*. Écrit la liste en JSON (`{version, defects: [{axis, index,
  offset, sigma}]}`).
- **`show_defects`** — *bool*, défaut `True`. Dessiner les défauts dans le viewport.

Lecture seule ; résultat dans `.result`.

## Voir aussi

- [LinearPatternSubtraction](retina-doc://LinearPatternSubtraction) — corriger ce qui vient
  d'être trouvé.
- [DefectMap](retina-doc://DefectMap) — une carte de défauts fournie, pixel par pixel.
- [NoiseEvaluation](retina-doc://NoiseEvaluation) — pour savoir à quoi se compare « un écart
  inférieur au bruit ».

## Références

- PixInsight — script *LinearDefectDetection*.
