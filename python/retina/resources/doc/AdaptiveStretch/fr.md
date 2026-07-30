---
id: AdaptiveStretch
category: IntensityTransformations
title: Étirement adaptatif
brief: "Étirement non-linéaire construit automatiquement à partir des écarts entre pixels voisins (AdaptiveStretch de PixInsight)."
keywords: [étirement, adaptatif, contraste, bruit, courbe de transfert, luminance, MaskedStretch]
related: [MaskedStretch, HistogramTransformation, MultiscaleAdaptiveStretch, ArcsinhStretch]
icon: adjustments
references:
  - "PixInsight — AdaptiveStretch tool reference."
  - "Conejero, J. — AdaptiveStretch: a data-driven, contrast-adaptive non-linear stretch."
---

## Résumé

`AdaptiveStretch` construit une **courbe de transfert non-linéaire** directement à partir du
contenu de l'image, sans qu'aucun point ne soit placé à la main. Il analyse les différences
d'intensité entre pixels voisins : là où ces écarts dépassent un seuil de bruit, il en déduit
un **détail réel** et dilate la plage de tons correspondante ; là où ils restent en-dessous, il
suppose du **bruit** et comprime la plage. Le résultat est un étirement qui renforce
sélectivement le contraste des zones structurées (nébulosités, bras de galaxie) sans amplifier
le grain du fond de ciel. Il s'agit d'un process **destructif** : les pixels sont réécrits dans
l'historique de la vue.

## Cas d'usage

- **Étirer une image linéaire** en préservant les faibles structures diffuses sans faire
  ressortir le bruit du fond de ciel.
- **Alternative sans réglage manuel** à `HistogramTransformation`/`CurvesTransformation` quand
  on veut un premier jet automatique piloté par les données plutôt qu'une courbe dessinée à la
  main.
- **Renforcer le contraste local** de nébuleuses ou de galaxies faibles avant un ajustement fin
  par courbes.
- **Comparer plusieurs seuils de bruit** pour trouver le compromis détail/bruit adapté au SNR
  réel de la pose.

## Fonctionnement

1. L'intensité de chaque pixel est **discrétisée** en `resolution` niveaux entiers dans
   `[0, resolution-1]`.
2. Pour chaque paire de pixels **adjacents** (voisin droit et voisin du bas), on calcule l'écart
   absolu entre leurs niveaux. Si cet écart dépasse le seuil `noise_threshold` (converti en
   niveaux discrets), la paire **vote pour dilater** le niveau d'intensité le plus bas des deux ;
   sinon elle **vote pour le comprimer**.
3. Ces votes, accumulés sur toute l'image, forment une estimation de la **pente locale** de la
   courbe de transfert à chaque niveau : `pente = max(votes_dilatation - votes_compression, 0)`.
   La pente est donc toujours positive ou nulle, ce qui garantit une courbe **monotone**.
4. Si `contrast_protection > 0`, les pentes les plus extrêmes sont plafonnées (écrêtées à un
   quantile), ce qui empêche un petit nombre de transitions très nettes de dominer toute la
   courbe et de créer des halos de contraste violents.
5. La courbe finale s'obtient en **intégrant** (somme cumulée) les pentes puis en la
   renormalisant dans `[0, 1]` : elle est appliquée à chaque pixel par interpolation sur son
   niveau discret.
6. En couleur, la courbe est calculée **une seule fois sur la luminance** (moyenne R,V,B), puis
   appliquée à chaque canal via un simple **ratio d'échelle** — la teinte du pixel est donc
   préservée, seule sa luminosité change.

## Mathématiques

Soit $x \in [0,1]$ l'intensité d'un pixel (ou de la luminance en couleur) et $n$ =
`resolution`. On discrétise :

$$ k(x) = \operatorname{clip}\!\big(\lfloor x\,(n-1) \rfloor,\; 0,\; n-1\big) \in \{0,\dots,n-1\}. $$

Pour chaque paire de pixels adjacents $(a, b)$ (voisins horizontaux et verticaux), on note
$\ell = \min(k_a, k_b)$ et $d = |k_a - k_b|$, et on compare $d$ au seuil discret
$\tau = \texttt{noise\_threshold} \cdot (n-1)$ :

$$
\begin{cases}
\text{pos}[\ell] \mathrel{+}= 1 & \text{si } d > \tau \quad\text{(détail réel)} \\
\text{neg}[\ell] \mathrel{+}= 1 & \text{si } d \le \tau \quad\text{(bruit)}
\end{cases}
$$

La pente locale de la courbe au niveau $\ell$ est :

$$ \delta[\ell] = \max\big(\text{pos}[\ell] - \text{neg}[\ell],\; 0\big) + \varepsilon, $$

où $\varepsilon$ (petit plancher) garantit une croissance strictement positive. Avec
`contrast_protection` $= p \in [0,1]$, les pentes non nulles sont plafonnées au quantile
$q_{1 - 0.99\,p}$ de leur propre distribution avant d'ajouter $\varepsilon$. La courbe de
transfert s'obtient par intégration puis renormalisation :

$$ C(\ell) = \frac{\sum_{i=0}^{\ell} \delta[i] \;-\; \delta[0]}{\displaystyle\sum_{i=0}^{n-1} \delta[i] \;-\; \delta[0]}, \qquad
   y = C\big(k(x)\big). $$

En couleur, la courbe $C$ est dérivée de la luminance $L = (R+V+B)/3$, puis appliquée par
mise à l'échelle homogène des trois canaux :

$$ (R', V', B') = (R, V, B) \cdot \frac{C(k(L))}{L}, \qquad L > 0. $$

Ce ratio préserve exactement la teinte et la saturation du pixel : seule son intensité change.

## Paramètres

- **`noise_threshold`** — *real*, défaut `0.001`, plage `1e-06`–`0.5`. Seuil (en fraction de la
  plage `[0,1]`) au-delà duquel un écart entre pixels voisins est considéré comme du détail réel
  plutôt que du bruit. Plus il est bas, plus la courbe dilate agressivement de petites
  variations — au risque d'amplifier le bruit de fond ; plus il est haut, plus l'étirement reste
  conservateur.
- **`contrast_protection`** — *real*, défaut `0.0`, plage `0.0`–`1.0`. Plafonne les pentes
  extrêmes de la courbe pour limiter les sur-contrastes locaux (halos autour des étoiles ou des
  bords nets). `0` = aucune protection ; proche de `1` = plafond très bas, courbe quasi linéaire.
- **`resolution`** — *int*, défaut `4096`, plage `64`–`65536`. Nombre de niveaux discrets de la
  courbe de transfert. Une résolution élevée donne une courbe plus fine (moins de paliers
  visibles) mais coûte plus de mémoire et de temps de calcul ; une résolution basse peut
  introduire des marches visibles sur des images à fort gradient dynamique.

## Astuces & pièges

> **Attention** — un `noise_threshold` trop bas amplifie le bruit du fond de ciel autant que le
> vrai signal : si le fond devient granuleux après application, remontez le seuil ou débruitez
> avant l'étirement (`NoiseReduction`, `WaveletDenoise`).

> **Note** — le calcul parcourt toutes les paires de pixels voisins de l'image : sur de très
> grandes images, une `resolution` élevée augmente le temps de calcul sans forcément améliorer
> le rendu visuel — commencez par la valeur par défaut.

- Si des halos de contraste apparaissent autour des étoiles ou de bords nets, augmentez
  `contrast_protection` plutôt que de baisser encore `noise_threshold`.
- Comme il est destructif, appliquez `AdaptiveStretch` sur une copie ou après avoir validé la
  composition (registration, calibration) : il ne peut pas être re-décomposé comme une STF.
- Pour un étirement itératif avec protection explicite des hautes lumières plutôt que du bruit,
  préférez `MaskedStretch`.

## Voir aussi

- [MaskedStretch](retina-doc://MaskedStretch) — étirement itératif protégeant les hautes lumières.
- [HistogramTransformation](retina-doc://HistogramTransformation) — étirement manuel par point noir/milieu/blanc.
- [MultiscaleAdaptiveStretch](retina-doc://MultiscaleAdaptiveStretch) — variante multi-échelle du même principe.
- [ArcsinhStretch](retina-doc://ArcsinhStretch) — étirement arcsinh préservant la couleur.

## Références

- PixInsight — *AdaptiveStretch* tool reference.
- Conejero, J. — *AdaptiveStretch: a data-driven, contrast-adaptive non-linear stretch*.
