---
id: MorphologicalTransformation
category: Morphology
title: Transformation morphologique
brief: Applique un opérateur de morphologie mathématique en niveaux de gris (érosion, dilatation, ouverture/fermeture, top-hat, gradient) à un noyau carré plat.
keywords: [morphologie, érosion, dilatation, ouverture, fermeture, top-hat, gradient morphologique]
related: [StarMask, NoiseReduction, CosmeticCorrection, UnsharpMask]
icon: shape
references:
  - "PixInsight — MorphologicalTransformation tool reference."
  - "Serra, J. — Image Analysis and Mathematical Morphology (1982)."
  - "scipy.ndimage — grey_erosion, grey_dilation, grey_opening, grey_closing, white_tophat, black_tophat, morphological_gradient."
---

## Résumé

`MorphologicalTransformation` applique aux pixels un **opérateur de morphologie mathématique
en niveaux de gris**, calculé indépendamment sur chaque canal avec un élément structurant
**carré et plat** de côté `size`. Selon l'opération choisie, l'outil érode ou dilate les
structures locales, les lisse (ouverture/fermeture), isole les petits détails clairs ou
sombres (top-hat), ou en extrait les contours (gradient). C'est un outil de traitement de
forme, complémentaire aux filtres linéaires (convolution) : il agit sur la **géométrie locale**
des extrema plutôt que sur une moyenne pondérée.

## Cas d'usage

- **Isoler les petites étoiles** ou pointes lumineuses avec `white_tophat`, pour construire
  ou affiner un masque d'étoiles.
- **Repérer les défauts sombres** (pixels froids, poussière résiduelle sur le capteur) avec
  `black_tophat`.
- **Nettoyer une image binaire ou un masque** de pixels isolés parasites via `opening`
  (érosion puis dilatation) sans altérer la forme globale des structures conservées.
- **Combler de petits trous** dans un masque via `closing` (dilatation puis érosion).
- **Extraire les contours** d'une structure (galaxie, nébuleuse à bords nets) avec `gradient`.

## Fonctionnement

Le process délègue le calcul aux fonctions de morphologie en niveaux de gris de
`scipy.ndimage`. Pour chaque canal de l'image, un **élément structurant plat** — une fenêtre
carrée de côté `size` où tous les poids sont égaux — glisse sur l'image :

- `erosion` remplace chaque pixel par le **minimum** local sous la fenêtre : les structures
  claires rétrécissent, les structures sombres s'étendent.
- `dilation` remplace chaque pixel par le **maximum** local : effet inverse.
- `opening` enchaîne érosion puis dilatation : supprime les petites structures claires isolées
  (plus petites que `size`) sans déplacer les contours des grandes structures.
- `closing` enchaîne dilatation puis érosion : comble les petits trous ou creux sombres.
- `white_tophat` soustrait l'ouverture à l'image originale : ne garde que les **structures
  claires plus petites que l'élément structurant** (étoiles ponctuelles typiquement).
- `black_tophat` soustrait l'image originale à la fermeture : ne garde que les **structures
  sombres plus petites que l'élément structurant** (pixels chauds/froids, défauts).
- `gradient` calcule la différence dilatation − érosion : une carte de contours dont
  l'épaisseur dépend de `size`.

Le traitement est appliqué canal par canal (pas de mélange colorimétrique), puis le résultat
est reconverti en `float32`.

## Mathématiques

Soit $f$ l'image (un canal) et $B$ l'élément structurant plat, une fenêtre carrée de côté
$n$ = `size` centrée en chaque pixel. L'érosion et la dilatation en niveaux de gris s'écrivent :

$$ (f \ominus B)(x,y) = \min_{(i,j)\in B} f(x+i,\,y+j), \qquad
   (f \oplus B)(x,y) = \max_{(i,j)\in B} f(x-i,\,y-j). $$

Comme $B$ est plat (poids nuls, pas de pondération d'altitude), ces expressions se réduisent
au minimum/maximum glissant sur la fenêtre $n \times n$. Les opérateurs composés en dérivent :

$$ f \circ B = (f \ominus B) \oplus B \quad \text{(ouverture)}, \qquad
   f \bullet B = (f \oplus B) \ominus B \quad \text{(fermeture)}. $$

L'ouverture est **anti-extensive** ($f \circ B \le f$) et supprime les pics plus étroits que
$B$ ; la fermeture est **extensive** ($f \bullet B \ge f$) et comble les creux plus étroits
que $B$. Les top-hats isolent ce que ces opérateurs retirent :

$$ \text{white\_tophat}(f) = f - (f \circ B), \qquad
   \text{black\_tophat}(f) = (f \bullet B) - f. $$

Le gradient morphologique de Beucher approxime la norme du gradient local par la largeur de
la plage de valeurs dans la fenêtre :

$$ \text{gradient}(f) = (f \oplus B) - (f \ominus B). $$

Toutes ces opérations sont **idempotentes pour l'ouverture et la fermeture**
($ (f \circ B) \circ B = f \circ B $), une propriété qui les distingue d'un simple flou :
répéter l'opération avec le même $B$ ne change plus le résultat.

## Paramètres

- **`operation`** — *enum*, défaut `opening`, choix : `erosion`, `dilation`, `opening`,
  `closing`, `white_tophat`, `black_tophat`, `gradient`. Opérateur morphologique appliqué.
- **`size`** — *int*, défaut `3`, plage `1`–`51`. Côté (en pixels) de l'élément structurant
  carré plat. Détermine l'échelle des structures affectées : plus `size` est grand, plus les
  détails supprimés (ou isolés par top-hat) peuvent être larges.

## Astuces & pièges

> **Attention** — `erosion` et `dilation` seules **déplacent les contours** et biaisent la
> photométrie des étoiles (rétrécissement ou grossissement des cœurs). Pour un nettoyage sans
> déformation géométrique globale, préférez `opening`/`closing`, qui restaurent la taille des
> structures conservées.

> **Note** — les opérations sont appliquées indépendamment par canal ; sur une image couleur
> avec un fort déséquilibre entre canaux, cela peut introduire de légères franges chromatiques
> sur les contours traités.

- `size` doit rester **impair de préférence** (fenêtre centrée) et cohérent avec l'échelle du
  détail visé : trop petit, l'opérateur n'a aucun effet visible ; trop grand, il détruit aussi
  les structures utiles.
- Pour un simple débruitage sans notion de forme, `NoiseReduction` ou `WaveletDenoise` sont
  généralement plus adaptés ; la morphologie cible spécifiquement la **taille géométrique**
  des structures, pas leur amplitude statistique.
- `white_tophat`/`black_tophat` fonctionnent bien en **prétraitement** avant seuillage
  (`Binarize`) pour construire un masque de petites sources.

## Voir aussi

- [StarMask](retina-doc://StarMask) — masque d'étoiles dédié, alternative à `white_tophat`.
- [NoiseReduction](retina-doc://NoiseReduction) — débruitage par amplitude plutôt que par forme.
- [CosmeticCorrection](retina-doc://CosmeticCorrection) — correction ciblée des pixels chauds/froids.
- [UnsharpMask](retina-doc://UnsharpMask) — accentuation de contours par filtre linéaire.

## Références

- PixInsight — *MorphologicalTransformation* tool reference.
- Serra, J. — *Image Analysis and Mathematical Morphology* (1982).
- scipy.ndimage — *grey_erosion*, *grey_dilation*, *grey_opening*, *grey_closing*,
  *white_tophat*, *black_tophat*, *morphological_gradient*.
