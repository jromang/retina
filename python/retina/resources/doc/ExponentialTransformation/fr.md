---
id: ExponentialTransformation
category: IntensityTransformations
title: Transformation exponentielle
brief: Étirement non linéaire simple par loi de puissance (PIP éclaircit, SMI assombrit), façon PixInsight.
keywords: [exponentielle, loi de puissance, gamma, PIP, SMI, étirement, non-linéaire]
related: [HistogramTransformation, ArcsinhStretch, AutoHistogram, CurvesTransformation]
icon: math-function
references:
  - "PixInsight — ExponentialTransformation tool reference."
---

## Résumé

`ExponentialTransformation` applique aux pixels une simple **loi de puissance** (gamma), dans
l'un des deux sens proposés par PixInsight : **PIP** (*Power of Inverted Pixels*), qui éclaircit
l'image en dilatant les tons sombres, ou **SMI**, qui l'assombrit en compressant les tons moyens
et hautes lumières. Un unique paramètre `order` règle la force de l'effet. C'est l'étirement non
linéaire le plus élémentaire du catalogue — sans point noir/blanc réglable ni protection de
couleur, à la différence de `HistogramTransformation` ou `ArcsinhStretch`.

## Cas d'usage

- **Éclaircir rapidement** une image sombre (PIP) sans passer par un réglage MTF à trois curseurs.
- **Assombrir/compresser** des hautes lumières trop envahissantes (SMI), par exemple sur le cœur
  d'une nébuleuse ou d'une galaxie déjà bien étirée.
- **Micro-ajustement de gamma** en fin de traitement, quand un simple coup de pouce de contraste
  suffit et qu'une courbe complète serait disproportionnée.
- **Brique de pipeline** : un `order` proche de `1.0` (quasi-identité) permet d'insérer le process
  dans une recette sans effet notable, puis de l'affiner plus tard.

## Fonctionnement

Le process clippe d'abord les pixels dans `[0, 1]`, puis applique **canal par canal, de façon
indépendante**, l'une des deux lois de puissance choisies par `type` :

- **PIP** (*Power of Inverted Pixels*) : on inverse les pixels ($1-x$), on élève à la puissance
  `order`, puis on ré-inverse le résultat. Les deux bornes $0$ et $1$ restent fixes ; pour
  `order > 1`, la pente au point noir vaut `order`, ce qui **dilate les ombres** (éclaircit) tout
  en laissant les hautes lumières presque inchangées.
- **SMI** : simple puissance directe $x^{\text{order}}$. Pour `order > 1`, toute valeur
  intermédiaire est tirée vers le bas — l'image **s'assombrit et se compresse**, en épargnant
  les extrêmes ($0$ et $1$ restent fixes).

Aucune protection de couleur explicite n'est appliquée (contrairement à `ArcsinhStretch` ou
`AdaptiveStretch`, qui dérivent le facteur d'étirement de la luminance) : chaque canal RVB subit
la même loi de puissance indépendamment, ce qui peut légèrement déplacer la teinte des pixels
saturés en couleur.

## Mathématiques

Soit $x \in [0,1]$ la valeur (clippée) d'un pixel et $p = $ `order`. Les deux fonctions de
transfert sont :

$$
f_{\text{PIP}}(x) = 1 - (1-x)^{p}, \qquad
f_{\text{SMI}}(x) = x^{p}.
$$

Les deux sont liées par la symétrie $x \mapsto 1-x$ : $f_{\text{PIP}}(x) = 1 - f_{\text{SMI}}(1-x)$.
Toutes deux fixent $0$ et $1$ et sont strictement monotones sur $[0,1]$ pour $p>0$. Leurs pentes
au point noir donnent l'intuition de l'effet :

$$
f_{\text{PIP}}'(0) = p, \qquad f_{\text{SMI}}'(0) =
\begin{cases} 0 & \text{si } p>1 \\ +\infty & \text{si } p<1 \end{cases}.
$$

Concrètement : avec $p>1$, PIP a une forte pente au point noir → il **dilate les ombres**
(éclaircit), tandis que SMI a une pente nulle au point noir et écrase les valeurs intermédiaires
vers le bas → il **assombrit/compresse**. Avec $0<p<1$, les deux effets s'inversent (PIP
assombrit, SMI éclaircit). À $p=1$, les deux fonctions sont l'identité.

## Paramètres

- **`type`** — *enum*, défaut `PIP`, choix : `PIP`, `SMI`. Sens de la transformation : `PIP`
  (*Power of Inverted Pixels*) éclaircit en dilatant les ombres ; `SMI` assombrit en compressant
  les tons moyens et hautes lumières.
- **`order`** — *real*, défaut `1.0`, plage `0.1`–`6.0`. Exposant de la loi de puissance. À `1.0`,
  transformation neutre (identité). Plus il s'éloigne de `1.0`, plus l'effet (éclaircissement ou
  assombrissement selon `type`) est marqué.

## Astuces & pièges

> **Attention** — la transformation est **destructive** (comme `HistogramTransformation`) et
> **sans protection de couleur** : sur une image RVB très étirée, un `order` élevé peut faire
> dériver légèrement la teinte des zones saturées, faute de facteur commun calculé sur la
> luminance.

- Pour un ordre très inférieur à `1.0`, l'effet de `PIP` et `SMI` s'inverse (PIP assombrit alors,
  SMI éclaircit) — testez toujours visuellement plutôt que de vous fier au nom.
- Contrairement à `HistogramTransformation`, il n'y a ni point noir ni point blanc réglables :
  travaillez en amont sur le cadrage de l'histogramme si l'image n'est pas déjà bien répartie
  dans `[0,1]`.
- Pour un étirement préservant la couleur sur des données linéaires très concentrées près de
  zéro, préférez `ArcsinhStretch`, qui calcule son facteur sur la luminance.

## Voir aussi

- [HistogramTransformation](retina-doc://HistogramTransformation) — étirement par point noir/milieu/point blanc (MTF).
- [ArcsinhStretch](retina-doc://ArcsinhStretch) — étirement non linéaire préservant la couleur.
- [AutoHistogram](retina-doc://AutoHistogram) — auto-stretch cuit dans les pixels.
- [CurvesTransformation](retina-doc://CurvesTransformation) — contrôle tonal par courbe libre.

## Références

- PixInsight — *ExponentialTransformation* tool reference.
