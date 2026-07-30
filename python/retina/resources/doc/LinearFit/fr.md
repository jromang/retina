---
id: LinearFit
category: ColorCalibration
title: Ajustement linéaire (LinearFit)
brief: Ajuste linéairement chaque canal sur une vue de référence par régression aux moindres carrés.
keywords: [ajustement linéaire, régression, moindres carrés, mosaïque, panneaux, calibration de canaux, égalisation]
related: [ColorCalibration, LRGBCombination, MosaicReproject, HistogramMatching]
icon: chart-line
references:
  - "PixInsight — LinearFit tool reference."
  - "numpy.polyfit — polynomial least-squares fitting."
---

## Résumé

`LinearFit` recale statistiquement une image sur une **vue de référence** en cherchant, pour
chaque canal, la transformation affine `out = a·in + b` qui minimise l'écart quadratique avec le
canal correspondant de la référence. C'est l'équivalent de l'outil `LinearFit` de PixInsight :
un outil de **calibration relative** entre images, pas un étirement — les données restent
linéaires, seuls le gain (`a`) et l'offset (`b`) de chaque canal sont ajustés.

## Cas d'usage

- **Égaliser des panneaux de mosaïque** avant assemblage (`MosaicReproject`), pour que les zones
  de recouvrement se raccordent sans saut de niveau visible.
- **Aligner des poses L, R, G, B** sur une référence commune avant `LRGBCombination`, quand les
  temps de pose ou les conditions de prise de vue diffèrent entre filtres.
- **Comparer/recaler des sessions** prises à des dates différentes (fond de ciel, transparence
  variables) avant de les combiner ou de les différencier (détection de transitoires, comètes).
- Préparer une **soustraction propre** entre deux images (ex. avant/après) en ramenant l'une sur
  l'échelle de l'autre.

## Fonctionnement

Le process prend en paramètre l'identifiant d'une vue de référence (`reference`). Si celle-ci est
vide ou introuvable, l'image est renvoyée inchangée. Sinon, pour **chaque canal** `c` de l'image
active :

1. Le canal de référence correspondant est extrait (si la référence a moins de canaux que
   l'image, par exemple une référence monochrome pour une image couleur, le dernier canal
   disponible de la référence est réutilisé pour les canaux excédentaires).
2. Les deux canaux, aplatis en vecteurs, sont ajustés par une **régression linéaire aux moindres
   carrés du premier degré** (`numpy.polyfit`) : on cherche la droite qui prédit au mieux les
   valeurs de la référence à partir des valeurs de l'image courante.
3. La transformation `a·x + b` trouvée est appliquée à **tout le canal**, pas seulement aux
   pixels ayant servi à l'estimation.
4. Le résultat est écrêté dans `[0, 1]` et reconverti en `float32`.

L'ajustement est donc **global par canal** (un seul couple `(a, b)` par canal, pas de variation
spatiale) — contrairement à `HistogramMatching`, qui recale toute la distribution de tons, ou à
`LocalNormalization`, qui autorise des gains locaux.

## Mathématiques

Pour un canal donné, notons $x_i$ les valeurs de pixels de l'image à ajuster et $y_i$ les valeurs
correspondantes de la référence (mêmes positions, images aplaties). On recherche les coefficients
$(a, b)$ qui minimisent l'erreur quadratique :

$$ (a, b) = \underset{a,\,b}{\arg\min} \sum_i \big(a\,x_i + b - y_i\big)^2 . $$

La solution des moindres carrés ordinaires s'exprime avec les moyennes et covariances
empiriques :

$$ a = \frac{\operatorname{cov}(x, y)}{\operatorname{var}(x)}
     = \frac{\sum_i (x_i - \bar{x})(y_i - \bar{y})}{\sum_i (x_i - \bar{x})^2},
   \qquad
   b = \bar{y} - a\,\bar{x}. $$

Le canal corrigé est ensuite obtenu par transformation affine puis écrêtage :

$$ x'_i = \operatorname{clip}\!\big(a\,x_i + b,\; 0,\; 1\big). $$

Le gain $a$ compense les différences d'échelle (temps de pose, transmission, gain capteur) et
l'offset $b$ compense les différences de niveau de fond entre l'image et la référence. Si les deux
images sont déjà identiques à un facteur près, $a \approx 1$ et $b \approx 0$.

## Paramètres

- **`reference`** — *str*, défaut `""`. Identifiant de la vue (fenêtre ou preview) servant de
  référence pour l'ajustement. Vide ou identifiant introuvable → l'image est renvoyée inchangée
  sans erreur.

## Astuces & pièges

> **Attention** — la régression est faite sur **tous les pixels** du canal, étoiles comprises. Des
> étoiles saturées très différentes entre les deux images (usure, seeing) peuvent biaiser le gain
> estimé. Sur des mosaïques, préférez recadrer sur la **zone de recouvrement commune** avant
> d'exécuter `LinearFit` si l'écart est important.

> **Note** — ce process ne modifie que gain et offset par canal ; il ne corrige pas les gradients
> spatiaux résiduels. Combinez-le avec `BackgroundExtraction` ou `MultiscaleGradientCorrection`
> si le fond de ciel n'est pas plat.

- Fonctionne sur des données **linéaires** (avant étirement) ; appliqué après un étirement
  non linéaire, l'ajustement affine n'a plus de sens physique.
- Si l'image de référence a un seul canal (luminance) et l'image cible plusieurs, chaque canal de
  la cible est recalé sur ce même canal de référence — utile pour aligner des couches L/R/G/B sur
  une luminance commune.
- Vérifiez le résultat avec `Statistics` avant/après pour confirmer que médiane et dispersion sont
  bien rapprochées de la référence.

## Voir aussi

- [ColorCalibration](retina-doc://ColorCalibration) — balance des blancs par régions de référence.
- [LRGBCombination](retina-doc://LRGBCombination) — combinaison de couches L/R/G/B, à préparer avec `LinearFit`.
- [MosaicReproject](retina-doc://MosaicReproject) — assemblage de mosaïques WCS, où l'égalisation des panneaux aide au raccord.
- [HistogramMatching](retina-doc://HistogramMatching) — recalage de toute la distribution de tons, pas seulement gain/offset.

## Références

- PixInsight — *LinearFit* tool reference.
- numpy.polyfit — *polynomial least-squares fitting*.
