---
id: Binarize
category: IntensityTransformations
title: Binarisation
brief: Convertit chaque pixel en tout-ou-rien (0 ou 1) par comparaison à un seuil unique.
keywords: [binarisation, seuil, seuillage, masque, tout-ou-rien, threshold]
related: [RangeSelection, HistogramTransformation, StarMask, Invert]
icon: binary
references:
  - "PixInsight — Binarize tool reference."
  - "Seuillage global (thresholding) — traitement d'image classique (Otsu, seuil fixe)."
---

## Résumé

`Binarize` transforme une image en carte **strictement binaire** : chaque échantillon devient
`1.0` s'il atteint ou dépasse un **seuil** unique, `0.0` sinon. C'est l'opération de seuillage
la plus simple qui soit — pas de dégradé, pas de zone de transition — appliquée indépendamment
à chaque canal. Le résultat est un noir et blanc pur, utile comme brique de base pour fabriquer
des masques ou isoler des structures au-dessus/en-dessous d'un niveau donné.

## Cas d'usage

- **Fabriquer un masque grossier** (silhouette d'une galaxie, d'un halo, d'une zone saturée)
  avant de l'affiner par dilatation/érosion (`MorphologicalTransformation`) ou par flou.
- **Isoler les pixels saturés** en binarisant sur un seuil proche de 1, pour les recenser ou
  les exclure d'un calcul de statistiques.
- **Détecter la présence de signal** au-dessus du bruit de fond après avoir estimé un seuil
  (par exemple médiane + k·MAD via `Statistics`), en préparation d'une détection de sources.
- **Créer des cartes binaires pédagogiques** ou de débogage pour visualiser où une condition
  d'intensité est vraie ou fausse dans l'image.

## Fonctionnement

L'opérateur compare chaque valeur de pixel, canal par canal, au paramètre `threshold` :

1. Les données d'entrée sont supposées normalisées dans `[0, 1]` (convention Retina/PixInsight).
2. Chaque échantillon `x` est testé indépendamment : `x >= threshold`.
3. Le résultat est écrit en sortie comme `1.0` (vrai) ou `0.0` (faux), en `float32`.

Aucun lissage, aucune interpolation aux bords : la transition est une **marche** parfaite. Le
process est appliqué à toute l'image (ou à la preview active) et peut être combiné à un masque
d'application (`is_maskable = True`) pour ne binariser qu'une région.

## Mathématiques

Pour une valeur de pixel $x \in [0,1]$ et un seuil $t$ = `threshold`, la sortie est la fonction
échelon (fonction de Heaviside décalée) :

$$ b(x) = \begin{cases} 1 & \text{si } x \ge t \\ 0 & \text{si } x < t \end{cases} $$

Appliquée indépendamment à chaque canal $c$ et chaque position $(u, v)$ :

$$ I'_{c}(u,v) = b\big(I_{c}(u,v)\big) = \mathbb{1}_{\,I_{c}(u,v) \,\ge\, t} $$

où $\mathbb{1}$ est la fonction indicatrice. Cette opération est **non linéaire, non inversible**
(irréversible : toute l'information de gradation est perdue) et **idempotente** — binariser deux
fois de suite avec le même seuil ne change rien après la première application, puisque la sortie
ne contient déjà plus que $\{0, 1\}$.

## Paramètres

- **`threshold`** — *real*, défaut `0.5`, plage `0`–`1`. Seuil de comparaison : tout pixel de
  valeur supérieure ou égale devient blanc (`1.0`), tout le reste devient noir (`0.0`). Un
  seuil bas conserve davantage de pixels à `1` ; un seuil haut n'en conserve que très peu
  (typiquement les cœurs d'étoiles ou zones saturées).

## Astuces & pièges

> **Attention** — l'opération est destructive et **irréversible** : toute nuance entre 0 et 1
> disparaît. Travaillez sur une copie de la vue, ou en aval d'un masque, si l'image d'origine
> doit rester disponible.

> **Note** — le seuil s'applique canal par canal sur une image couleur : une valeur de
> `threshold` unique peut binariser R, G et B à des points visuellement différents. Pour un
> seuil basé sur la luminance avec transition douce, préférez `RangeSelection`.

- Sur une image linéaire non étirée, la majorité du signal est proche de 0 : un `threshold` de
  0,5 ne conservera souvent presque rien. Étirez (`HistogramTransformation`, STF) ou calculez
  un seuil adapté au bruit de fond avant de binariser.
- Pour un masque aux bords progressifs (moins agressif qu'un seuillage dur), `RangeSelection`
  offre un paramètre `fuzziness` et un lissage gaussien.

## Voir aussi

- [RangeSelection](retina-doc://RangeSelection) — sélection par plage d'intensité avec bords flous.
- [HistogramTransformation](retina-doc://HistogramTransformation) — étirement préalable pour
  positionner le signal avant seuillage.
- [StarMask](retina-doc://StarMask) — génération de masque dédiée aux étoiles.
- [Invert](retina-doc://Invert) — inversion complémentaire d'un résultat binarisé.

## Références

- PixInsight — *Binarize* tool reference.
- Seuillage global (thresholding) — traitement d'image classique (Otsu, seuil fixe).
