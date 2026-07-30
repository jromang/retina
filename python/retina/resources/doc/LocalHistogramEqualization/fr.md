---
id: LocalHistogramEqualization
category: MultiscaleProcessing
title: Égalisation d'histogramme locale
brief: Égalisation d'histogramme adaptative locale (CLAHE) pour rehausser le contraste fin sans écraser les tons globaux.
keywords: [CLAHE, contraste local, égalisation, histogramme adaptatif, rehaussement, détails fins]
related: [HistogramTransformation, AdaptiveStretch, UnsharpMask, ACDNR]
icon: chart-histogram
references:
  - "Zuiderveld, K. — Contrast Limited Adaptive Histogram Equalization, Graphics Gems IV (1994)."
  - "scikit-image — skimage.exposure.equalize_adapthist."
---

## Résumé

`LocalHistogramEqualization` applique une **égalisation d'histogramme adaptative à contraste
limité** (CLAHE — *Contrast-Limited Adaptive Histogram Equalization*), via
`skimage.exposure.equalize_adapthist`. Contrairement à `HistogramTransformation`, qui applique
une seule fonction de transfert à toute l'image, cet opérateur calcule une fonction
d'égalisation **différente pour chaque région locale** de l'image, puis interpole en douceur
entre régions voisines. Le résultat rehausse le contraste des structures fines (filaments de
nébuleuse, bras de galaxie, détails lunaires/planétaires) sans écraser les tons globaux ni
saturer le fond de ciel.

## Cas d'usage

- **Faire ressortir des structures ténues** (filaments, dentelles de nébuleuse) noyées dans un
  fond peu contrasté, là où un étirement global ne suffit pas.
- **Détails planétaires/lunaires** : rehausser le relief et les nuances d'albédo à échelle locale.
- **Compléter un étirement classique** (`HistogramTransformation`, `AdaptiveStretch`) par une
  passe de contraste local, en fin de traitement, pour donner du « punch » sans artefacts de halo.
- Alternative à `UnsharpMask`/`ACDNR` quand on cherche un gain de contraste perceptuel plutôt
  qu'un rehaussement de netteté par convolution.

## Fonctionnement

Le traitement est appliqué **indépendamment canal par canal** (R, G, B ou luminance mono) :

1. Les valeurs du canal sont d'abord **écrêtées dans `[0, 1]`** (l'image doit être en flottant
   normalisé).
2. L'image est découpée en une grille de **tuiles contextuelles** dont la taille est fixée par
   `kernel_size` (ou calculée automatiquement par scikit-image, environ 1/8 de chaque dimension,
   si `kernel_size = 0`).
3. Dans chaque tuile, un **histogramme local** est calculé puis **écrêté** : tout bin dépassant
   un seuil dérivé de `clip_limit` voit son excédent redistribué uniformément sur les autres bins
   — c'est ce qui empêche l'amplification du bruit dans les zones quasi uniformes (fond de ciel).
4. La **fonction de transfert** de chaque tuile est la CDF (fonction de répartition cumulée) de
   son histogramme écrêté.
5. La valeur finale de chaque pixel est obtenue par **interpolation bilinéaire** entre les
   fonctions de transfert des quatre tuiles voisines les plus proches, ce qui élimine les
   discontinuités visibles aux frontières de tuiles.

## Mathématiques

Pour une tuile $R$ contenant $N_R$ pixels du canal considéré, soit $h_R(k)$ l'histogramme à
$n_\text{bins}$ niveaux $k = 0,\dots,n_\text{bins}-1$. L'écrêtage limite chaque bin à un plafond
$c$ proportionnel à `clip_limit` :

$$ c = \texttt{clip\_limit} \cdot \frac{N_R}{n_\text{bins}}, \qquad
   h_R^{\text{clip}}(k) = \min\!\big(h_R(k),\, c\big), $$

et l'excédent total $\sum_k \big(h_R(k) - h_R^{\text{clip}}(k)\big)$ est redistribué uniformément
sur les $n_\text{bins}$ bins. La fonction de transfert locale est la CDF normalisée du résultat :

$$ T_R(x) = \frac{1}{N_R}\sum_{k=0}^{x} h_R^{\text{clip,redist}}(k). $$

Pour un pixel de valeur $x$ situé entre les centres de quatre tuiles voisines
$R_{00}, R_{10}, R_{01}, R_{11}$, avec poids bilinéaires $(u, v) \in [0,1]^2$ dérivés de sa
position, la valeur de sortie est :

$$ y = (1-u)(1-v)\,T_{R_{00}}(x) + u(1-v)\,T_{R_{10}}(x)
     + (1-u)v\,T_{R_{01}}(x) + uv\,T_{R_{11}}(x). $$

Plus `clip_limit` est petit, plus $c$ est bas, plus l'amplification locale du contraste est
contenue (histogramme quasi non modifié pour `clip_limit → 0`) ; plus il est proche de 1, plus
l'égalisation se rapproche d'une égalisation d'histogramme classique par tuile, avec risque
d'amplifier fortement le bruit.

## Paramètres

- **`clip_limit`** — *real*, défaut `0.01`, plage `0.0`–`1.0`. Seuil d'écrêtage de l'histogramme
  local, normalisé. Une valeur basse limite fortement l'amplification de contraste (et donc du
  bruit) ; une valeur haute autorise une égalisation plus agressive, au prix d'un bruit local
  plus visible.
- **`kernel_size`** — *int*, défaut `0`, plage `0`–`1024`. Taille (en pixels) des tuiles
  contextuelles utilisées pour le calcul des histogrammes locaux. `0` laisse scikit-image choisir
  automatiquement une taille (~1/8 de chaque dimension de l'image). Une tuile petite suit de
  près les variations fines (mais peut créer des halos) ; une tuile grande se rapproche d'un
  étirement global.

## Astuces & pièges

> **Attention** — `clip_limit` trop élevé amplifie fortement le bruit de fond, en particulier
> dans les zones de ciel peu texturées : commencez avec la valeur par défaut (`0.01`) et
> augmentez progressivement en surveillant le fond.

> **Note** — CLAHE agit **par canal** indépendamment ; sur une image couleur, cela peut légèrement
> décaler la balance colorimétrique locale. Vérifiez le rendu chromatique après application, ou
> travaillez sur un canal de luminance séparé (`ComponentSeparation`) si besoin.

- Un `kernel_size` trop petit peut faire apparaître des halos artificiels autour des étoiles ou
  des bords contrastés : agrandissez la taille de tuile si ces artefacts sont visibles.
- Cet opérateur est **destructif** (il modifie les pixels) : appliquez-le après un étirement
  raisonnable, jamais directement sur des données linéaires brutes.
- Combinez-le avec un masque d'étoiles pour épargner le cœur des étoiles, souvent sensible aux
  effets d'égalisation locale.

## Voir aussi

- [HistogramTransformation](retina-doc://HistogramTransformation) — étirement de tons global (MTF).
- [AdaptiveStretch](retina-doc://AdaptiveStretch) — étirement adaptatif multi-échelle du fond.
- [UnsharpMask](retina-doc://UnsharpMask) — rehaussement de netteté par convolution/masque flou.
- [ACDNR](retina-doc://ACDNR) — réduction de bruit adaptative avec préservation du contraste local.

## Références

- Zuiderveld, K. — *Contrast Limited Adaptive Histogram Equalization*, Graphics Gems IV (1994).
- scikit-image — *skimage.exposure.equalize_adapthist*.
