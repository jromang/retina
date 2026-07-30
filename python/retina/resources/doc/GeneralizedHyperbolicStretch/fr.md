---
id: GeneralizedHyperbolicStretch
category: IntensityTransformations
title: Étirement hyperbolique généralisé
brief: Étire les tons en concentrant le contraste autour d'un point choisi, avec protection des ombres et des hautes lumières.
keywords: [GHS, étirement, hyperbolique, histogramme, contraste, linéaire, point de symétrie]
related: [HistogramTransformation, ArcsinhStretch, MaskedStretch, CurvesTransformation, AutoHistogram]
icon: chart-arcs
references:
  - "Payne, D. & Cranfield, M. (2021-2023) — Generalised Hyperbolic Stretch, ghsastro.co.uk."
---

## Résumé

`GeneralizedHyperbolicStretch` (GHS) transforme les tons en **concentrant le contraste autour
d'un point que vous choisissez**, au lieu de l'étaler uniformément. C'est la différence
essentielle avec `HistogramTransformation` : on ne dispose que d'un budget de contraste fini,
et le GHS permet de le dépenser exactement là où sont les données qui vous intéressent.

Proposé par David Payne en 2021, développé avec Mike Cranfield, il est devenu un module natif
de PixInsight et reste au cœur des traitements primés.

## Cas d'usage

- **Premier étirement d'une image linéaire** : le geste pour lequel il a été conçu. On place le
  point de symétrie juste à droite du pic de fond, on met une intensité locale forte, et on
  monte le facteur jusqu'à ce que le pic arrive vers 0,2–0,25.
- **Ajouter du contraste** à une zone plate d'une image déjà non linéaire, sans toucher au reste.
- **Assombrir le fond** sans écrêter : point de symétrie bas, `HP` égal à `SP`, intensité forte.
- **Revenir en arrière** : la transformation est exactement inversible (`invert`), ce qui permet
  d'étirer, de retirer les étoiles, puis de rendre les deux images à leur état linéaire.

## Fonctionnement

La courbe est bâtie en **quatre morceaux**, raccordés par la tangente puis normalisée pour
courir de 0 à 1 :

| Plage | Forme |
|---|---|
| `0 ≤ x < LP` | segment **linéaire**, tangent à la courbe en `LP` |
| `LP ≤ x < SP` | symétrique de la partie haute, retournée autour de `(SP, 0)` |
| `SP ≤ x < HP` | l'équation hyperbolique généralisée, dont la pente est maximale en `SP` |
| `HP ≤ x ≤ 1` | segment **linéaire**, tangent à la courbe en `HP` |

Les deux segments linéaires sont ce que font `LP` et `HP` : ils *réservent* du contraste aux
ombres et aux hautes lumières, au lieu de le laisser tout entier au voisinage de `SP`.

L'équation de base dépend de l'intensité locale `b`, et change de forme à trois endroits :

$$ b = -1 : \ln(1 + Dx) \qquad b < 0 : \frac{1 - (1 - bDx)^{\frac{b+1}{b}}}{D(b+1)} \qquad
   b = 0 : 1 - e^{-Dx} \qquad b > 0 : 1 - (1 + bDx)^{-\frac{1}{b}} $$

où $D = e^{\texttt{stretch\_factor}} - 1$. Le curseur règle $\ln(D+1)$ et non $D$, parce que
c'est cette grandeur qui varie linéairement avec l'effet perçu.

> **Détail d'implémentation qui a son importance** : ces sous-familles ne sont pas à la même
> échelle — la dérivée en zéro vaut $D$ pour trois d'entre elles et $1$ pour l'intégrale.
> Comme la courbe finale est normalisée, l'écart se simplifie exactement, et c'est justement ce
> qui rend la courbe **continue en `b`** quand on traverse $-1$ et $0$ avec le curseur.

## Paramètres

- **`stretch_factor`** — *real*, défaut `0.0`, plage `0`–`20`. L'ampleur de l'étirement,
  exprimée en $\ln(D+1)$. À zéro, la transformation est l'identité.
- **`local_intensity`** (`b`) — *real*, défaut `0.0`, plage `-5`–`15`. À quel point l'étirement
  se concentre autour de `SP`. Une valeur **élevée** (autour de 10) creuse un pic de contraste
  étroit — c'est ce qu'on veut pour un premier étirement, qui doit séparer le fond des données
  sans brûler les étoiles. Une valeur **basse ou négative** répartit contraste et luminosité
  plus uniformément, ce qui convient aux retouches ultérieures.
- **`symmetry_point`** (`SP`) — *real*, défaut `0.0`, plage `0`–`1`. Où le contraste est
  dépensé. Les valeurs s'écartent de ce point.
- **`protect_shadows`** (`LP`) — *real*, défaut `0.0`. En deçà, transformation linéaire :
  le fond conserve sa définition. Recadré à `SP` s'il le dépasse.
- **`protect_highlights`** (`HP`) — *real*, défaut `1.0`. Au-delà, transformation linéaire :
  les étoiles conservent leur définition.
- **`mode`** — *enum* `rgb` | `lightness` | `colour`, défaut `rgb`.
  - `rgb` : chaque canal indépendamment. Simple, mais **désature** — voir ci-dessous.
  - `lightness` : la seule clarté CIE L\*, chrominance intacte.
  - `colour` : la voie de l'arcsinh — on étire la moyenne des canaux et l'on applique le
    *rapport*, ce qui conserve exactement les proportions entre canaux, donc la saturation.
- **`clip_type`** — *enum* `clip` | `rescale`, défaut `rescale`. Ce qu'on fait, en mode
  `colour`, d'un pixel qui dépasse 1. `rescale` le ramène entier et **garde sa teinte** ;
  `clip` tronque, ce qui fait virer les cœurs d'étoiles au blanc.
- **`invert`** — *bool*, défaut `False`. Applique la transformation inverse.

## Astuces & pièges

> **Pourquoi le mode `rgb` délave l'image.** La saturation d'un pixel, c'est l'écart
> proportionnel entre son canal le plus brillant et le plus sombre. Une courbe de tons étire
> davantage les valeurs basses que les hautes, donc elle rapproche les canaux — et la couleur
> s'en va. Le mode `colour` est là pour ça.

- **Procédez en plusieurs étirements**, pas un seul. C'est tout le principe du GHS : chaque
  passe dépense un peu de contraste là où il faut, plutôt que de tout arbitrer d'un coup.
- L'aperçu temps réel est le bon endroit pour régler `SP` : il y est très sensible.
- Pour le premier étirement, `LP` ne sert généralement à rien, et `HP` non plus — une intensité
  locale forte protège déjà bien les étoiles.
- Le mode `colour` peut écrêter, donc **n'est pas inversible** en toute rigueur. Si vous comptez
  revenir en arrière analytiquement, restez en `rgb`.

## Voir aussi

- [HistogramTransformation](retina-doc://HistogramTransformation) — la fonction de transfert des
  tons moyens, plus simple mais sans point de concentration.
- [ArcsinhStretch](retina-doc://ArcsinhStretch) — même souci de préserver la couleur, une seule
  forme de courbe.
- [MaskedStretch](retina-doc://MaskedStretch) — approche itérative sous masque.
- [CurvesTransformation](retina-doc://CurvesTransformation) — courbe libre, quand on sait
  exactement la forme voulue.

## Références

- Payne, D. & Cranfield, M. — *Generalised Hyperbolic Stretch*, documentation de référence du
  module PixInsight, ghsastro.co.uk. Les équations implémentées ici en sont issues.
