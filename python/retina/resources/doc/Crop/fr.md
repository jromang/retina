---
id: Crop
category: Geometry
title: Recadrage
brief: Recadre l'image selon un rectangle défini par des bornes fractionnaires [0,1] du cadre.
keywords: [recadrage, crop, découpe, géométrie, bordures, cadrage]
related: [DynamicCrop, Resample, IntegerResample, Rotation]
icon: crop
references:
  - "PixInsight — Crop tool reference."
  - "scikit-image / numpy — slicing de tableaux 2D/3D."
---

## Résumé

`Crop` découpe l'image en ne conservant qu'un **rectangle** défini par quatre bornes
**fractionnaires** dans `[0, 1]` : `x0`/`y0` fixent le coin haut-gauche de la zone conservée,
`x1`/`y1` son coin bas-droit. C'est l'opérateur de recadrage « en dur » : la géométrie change,
et le résultat remplace l'image active (`is_maskable = False`, puisqu'un masque de blend suppose
une forme inchangée). Exprimer les bornes en fraction du cadre plutôt qu'en pixels rend le réglage
indépendant de la résolution — utile pour rejouer un recadrage sur un ré-échantillonnage différent
de la même image.

## Cas d'usage

- **Éliminer les bords sales** d'une mosaïque d'empilement (zones à faible couverture, artefacts
  de drizzle, franges de recalage) avant l'étirement.
- **Isoler un sujet** (une galaxie, une région d'une grande nébuleuse) pour un traitement dédié
  ou un export final resserré.
- **Retirer le vignettage résiduel** ou les coins mal corrigés par les flats, quand une correction
  de fond ne suffit pas.
- **Préparer une vignette** de contrôle rapide (aperçu recadré) sans passer par une `Preview`
  temporaire.

## Fonctionnement

Les quatre paramètres sont interprétés comme des **fractions du cadre** de l'image active :
`x0`, `x1` le long de la largeur, `y0`, `y1` le long de la hauteur, avec l'origine `(0,0)` au
coin **haut-gauche**. Le process convertit ces fractions en indices entiers de pixels par
arrondi au plus proche (`round(f * dimension)`), puis effectue un simple **découpage de tableau**
(`slicing` numpy) sur les deux premiers axes `(H, W, C)`, tous les canaux étant conservés.

Deux garde-fous rendent l'opérateur robuste à une saisie désordonnée :

1. **Ordre des bornes** : `x0`/`x1` (et `y0`/`y1`) sont automatiquement triées via `min`/`max`,
   donc inverser gauche/droite ou haut/bas dans l'interface ne produit pas d'erreur.
2. **Largeur minimale** : si les bornes triées coïncident (rectangle de largeur ou hauteur nulle
   après arrondi), la borne supérieure est repoussée d'au moins un pixel, garantissant une image
   de sortie non vide.

Le tableau résultant est copié (`.copy()`) pour détacher la vue du buffer original avant de
remplacer les pixels de la vue traitée.

## Mathématiques

Soit une image de dimensions $H \times W$ (hauteur × largeur) et les bornes fractionnaires
$x_0, x_1, y_0, y_1 \in [0,1]$. On calcule d'abord les bornes ordonnées :

$$ \tilde{x}_0 = \min(x_0, x_1), \qquad \tilde{x}_1 = \max(x_0, x_1) $$

et de même pour $\tilde{y}_0, \tilde{y}_1$. Les indices pixels sont obtenus par arrondi :

$$ i_0 = \operatorname{round}(\tilde{y}_0 \cdot H), \quad i_1 = \max\!\big(\operatorname{round}(\tilde{y}_1 \cdot H),\, i_0 + 1\big) $$

$$ j_0 = \operatorname{round}(\tilde{x}_0 \cdot W), \quad j_1 = \max\!\big(\operatorname{round}(\tilde{x}_1 \cdot W),\, j_0 + 1\big) $$

L'image de sortie $I'$, de taille $(i_1 - i_0) \times (j_1 - j_0)$, est simplement la
restriction de $I$ à ce rectangle, canal par canal :

$$ I'(y, x, c) = I(y + i_0,\; x + j_0,\; c) \qquad \text{pour } 0 \le y < i_1-i_0,\ 0 \le x < j_1-j_0 $$

Aucune interpolation n'intervient : chaque pixel de sortie recopie exactement un pixel d'entrée,
l'opérateur est donc **sans perte** sur la zone conservée (contrairement à `Resample`, qui
ré-échantillonne).

## Paramètres

- **`x0`** — *real*, défaut `0.0`, plage `0`–`1`. Bord **gauche** de la zone conservée, en
  fraction de la largeur (`0` = bord gauche de l'image).
- **`y0`** — *real*, défaut `0.0`, plage `0`–`1`. Bord **haut** de la zone conservée, en
  fraction de la hauteur (`0` = bord haut de l'image).
- **`x1`** — *real*, défaut `1.0`, plage `0`–`1`. Bord **droit** de la zone conservée, en
  fraction de la largeur (`1` = bord droit de l'image).
- **`y1`** — *real*, défaut `1.0`, plage `0`–`1`. Bord **bas** de la zone conservée, en
  fraction de la hauteur (`1` = bord bas de l'image).

## Astuces & pièges

> **Attention** — `Crop` est **destructif** et redimensionne l'image : les pixels hors du
> rectangle sont définitivement perdus dans l'historique de la vue (bien que `undo()` reste
> disponible tant que la vue n'est pas ré-enregistrée). Vérifiez le cadrage sur une `Preview`
> avant d'appliquer sur la vue principale.

> **Note** — les bornes étant fractionnaires, le même jeu de paramètres appliqué à deux images
> de résolutions différentes (par ex. avant/après `Resample`) découpe la **même région relative**,
> pas le même nombre de pixels.

- Pour explorer interactivement un rectangle de recadrage à la souris avec aperçu en direct,
  utilisez plutôt [DynamicCrop](retina-doc://DynamicCrop), qui combine recadrage et rotation en
  une seule passe.
- Un recadrage trop serré autour d'un objet gêne les traitements ultérieurs qui ont besoin de
  marge de fond de ciel (mesure de bruit, `BackgroundExtraction`, alignement) : gardez une bordure
  de fond si un traitement global doit encore s'appliquer.

## Voir aussi

- [DynamicCrop](retina-doc://DynamicCrop) — recadrage interactif combiné à une rotation.
- [Resample](retina-doc://Resample) — ré-échantillonnage par facteur d'échelle (avec interpolation).
- [IntegerResample](retina-doc://IntegerResample) — réduction/agrandissement par facteur entier.
- [Rotation](retina-doc://Rotation) — rotation d'un angle arbitraire.

## Références

- PixInsight — *Crop* tool reference.
- scikit-image / numpy — slicing de tableaux 2D/3D.
