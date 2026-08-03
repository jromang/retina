---
id: WaveletTransform
category: MultiscaleProcessing
title: Transformée en ondelettes
brief: Décompose l'image en ondelettes orthogonales (DWT) et applique un gain indépendant par bande d'échelle avant reconstruction.
keywords: [ondelettes, DWT, PyWavelets, multi-échelle, gain, netteté, starlet]
related: [MultiscaleLinearTransform, WaveletDenoise, UnsharpMask, MultiscaleMedianTransform]
icon: wave-sine
references:
  - "PyWavelets — pywt.wavedec2 / pywt.waverec2 (2D discrete wavelet transform)."
  - "Starck, J.-L., Murtagh, F., Fadili, J. — Sparse Image and Signal Processing: Wavelets and Related Geometric Multiscale Analysis."
---

## Résumé

`WaveletTransform` décompose l'image en une **transformée en ondelettes discrète 2D** (DWT,
via `pywt.wavedec2`) sur plusieurs échelles, puis **rééchelonne indépendamment** l'approximation
(basses fréquences — fond de ciel, luminosité globale) et l'ensemble des coefficients de détail
(hautes fréquences — structures fines, bruit, bords) avant de reconstruire l'image par la
transformée inverse (`pywt.waverec2`). C'est un outil de traitement multi-échelle générique,
complémentaire à la transformée starlet à trous de `MultiscaleLinearTransform`, mais basé sur de
vraies ondelettes orthogonales (famille au choix : Daubechies, Symlets, Coiflets…).

![Avant — WaveletTransform](figures/before.webp)
![Après — WaveletTransform](figures/after.webp)

*Avant, et après amplification des couches de détail, l'approximation étant laissée telle quelle.*

## Cas d'usage

- **Accentuer les structures fines** (dentelles de nébuleuses, bras spiraux) en augmentant
  `detail_gain` au-delà de 1.
- **Adoucir globalement** le grain ou le bruit résiduel en réduisant `detail_gain` en dessous de 1,
  sans passer par un débruiteur dédié.
- **Rééquilibrer fond/détail** en jouant séparément sur `approx_gain` (luminosité de fond, très
  basse fréquence) et `detail_gain` (texture).
- **Explorer une décomposition multi-échelle orthogonale** avant un traitement plus ciblé
  bande par bande (à comparer avec la starlet, non orthogonale mais isotrope).

## Fonctionnement

Pour chaque canal de couleur, traité indépendamment :

1. **Décomposition** : `pywt.wavedec2` applique `level` niveaux de DWT 2D avec l'ondelette
   `wavelet` (mode de bord `reflect`, qui prolonge l'image par symétrie miroir pour éviter les
   artefacts de bord). On obtient un coefficient d'approximation grossier `cA_level` et, pour
   chaque échelle $j = 1, \dots, \text{level}$, un triplet de détails
   $(cH_j, cV_j, cD_j)$ — horizontal, vertical, diagonal.
2. **Gain par bande** : l'approximation est multipliée par `approx_gain`, et **tous** les
   coefficients de détail (toutes échelles et orientations confondues) sont multipliés par le
   même `detail_gain`.
3. **Reconstruction** : `pywt.waverec2` recompose l'image à partir des coefficients modifiés. Le
   résultat peut légèrement déborder les dimensions d'origine (padding interne de la DWT) ; il est
   recadré à la taille source, puis écrêté dans `[0, 1]`.

Un `detail_gain > 1` renforce le contraste local (accentuation), un `detail_gain < 1` le réduit
(lissage) ; `approx_gain` joue le même rôle mais sur la composante de fond très basse fréquence.

## Mathématiques

La DWT 2D à `level` niveaux décompose une image $I$ en une hiérarchie de sous-bandes obtenues par
filtrage séparable (passe-bas $h$, passe-haut $g$, associés à l'ondelette choisie) suivi d'un
sous-échantillonnage par 2 à chaque niveau :

$$ I \;\longrightarrow\; \big(cA_{L},\; \{cH_j, cV_j, cD_j\}_{j=1}^{L}\big), \qquad L = \texttt{level}, $$

où $cA_L$ est l'approximation finale (passe-bas appliqué $L$ fois) et $cH_j, cV_j, cD_j$ les
détails horizontal/vertical/diagonal de l'échelle $j$ (produits croisés passe-bas/passe-haut sur
les deux dimensions). La transformation appliquée est un simple **rééchelonnage linéaire par
bande** :

$$ cA_L' = a \cdot cA_L, \qquad cH_j' = g \cdot cH_j,\; cV_j' = g \cdot cV_j,\; cD_j' = g \cdot cD_j
\quad \forall j, $$

avec $a$ = `approx_gain`, $g$ = `detail_gain`. La reconstruction inverse la transformée
(filtres miroir en quadrature, sur-échantillonnage puis recombinaison) :

$$ I' = \mathrm{DWT}^{-1}\big(cA_L',\, \{cH_j', cV_j', cD_j'\}_{j=1}^{L}\big). $$

Pour une ondelette orthogonale et des gains égaux à 1 sur toutes les bandes, cette opération est
l'identité (à la précision numérique et au recadrage de bord près) — c'est ce qui garantit que
seuls les gains introduisent une modification de l'image.

## Paramètres

- **`wavelet`** — *str*, défaut `db2`. Nom de l'ondelette PyWavelets (`db2`, `db4`, `sym4`,
  `coif1`…). Détermine la longueur et la forme des filtres, donc la localisation
  fréquence/espace de chaque bande.
- **`level`** — *int*, défaut `3`, plage `1`–`8`. Nombre de niveaux de décomposition. Plus de
  niveaux isolent des structures de plus en plus grandes dans l'approximation.
- **`approx_gain`** — *real*, défaut `1.0`, plage `0`–`5`. Facteur multiplicatif appliqué au
  coefficient d'approximation (fond très basse fréquence). `1.0` = inchangé.
- **`detail_gain`** — *real*, défaut `1.0`, plage `0`–`5`. Facteur multiplicatif appliqué à tous
  les coefficients de détail, toutes échelles confondues. `> 1` accentue les structures fines,
  `< 1` les adoucit.

## Astuces & pièges

> **Attention** — `detail_gain` élevé amplifie **aussi le bruit** en même temps que le signal
> fin : sur une image bruitée, préférez d'abord `WaveletDenoise`, puis un léger `detail_gain`
> pour la netteté.

- Contrairement à la starlet à trous (`MultiscaleLinearTransform`), la DWT est **sous-échantillonnée**
  (décimée) : elle n'est pas invariante par translation, ce qui peut introduire de très légers
  artefacts de bloc visibles sur un gain fort. Pour un traitement sans ce défaut, voir
  `WaveletDenoise` (transformée stationnaire SWT).
- Le gain de détail est **unique pour toutes les échelles** : pour un contrôle indépendant
  échelle par échelle (comme les couches de PixInsight ATWT/MMT), utilisez plutôt
  `MultiscaleLinearTransform` ou `MultiscaleMedianTransform`.
- Le mode de bord `reflect` limite les artefacts sur les contours de l'image, mais un `level`
  élevé sur une petite image peut tout de même produire des effets de bord visibles.

## Voir aussi

- [MultiscaleLinearTransform](retina-doc://MultiscaleLinearTransform) — décomposition starlet à
  trous, avec gain par échelle indépendant.
- [WaveletDenoise](retina-doc://WaveletDenoise) — débruitage par ondelettes stationnaires (SWT)
  avec seuillage doux.
- [UnsharpMask](retina-doc://UnsharpMask) — accentuation de netteté par masque flou, alternative
  simple à un seul niveau.
- [MultiscaleMedianTransform](retina-doc://MultiscaleMedianTransform) — décomposition multi-échelle
  par médianes successives.

## Références

- PyWavelets — *pywt.wavedec2* / *pywt.waverec2* (transformée en ondelettes discrète 2D).
- Starck, J.-L., Murtagh, F., Fadili, J. — *Sparse Image and Signal Processing: Wavelets and
  Related Geometric Multiscale Analysis*.
