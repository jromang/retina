---
id: CurvesTransformation
category: IntensityTransformations
title: Transformation par courbes
brief: Redistribue les tons via une courbe de transfert libre passant par des points de contrôle.
keywords: [courbes, courbe de tons, PCHIP, interpolation, contraste, canal]
related: [HistogramTransformation, ArcsinhStretch, LocalHistogramEqualization, MaskedStretch]
icon: chart-line
references:
  - "PixInsight — CurvesTransformation tool reference."
  - "Fritsch, F. N. & Carlson, R. E. (1980) — Monotone Piecewise Cubic Interpolation."
---

## Résumé

`CurvesTransformation` remappe les valeurs de pixels selon une **courbe de tons libre**,
définie par une liste de **points de contrôle** `(x, y)` dans `[0, 1]`. Contrairement à
`HistogramTransformation`, limitée à trois curseurs (noir/milieu/blanc), la courbe peut avoir
une forme arbitraire — en S pour le contraste, plate sur une plage pour protéger des tons,
inversée par endroits — ce qui en fait l'outil de contrôle tonal le plus fin et le plus
général du logiciel. Elle peut s'appliquer globalement (`RGB/K`) ou à un seul canal
(`R`, `G`, `B`), ce qui permet aussi des corrections colorimétriques ciblées.

![Avant — CurvesTransformation](figures/before.webp)
![Après — CurvesTransformation](figures/after.webp)

*Avant, et après une courbe en S de contraste.*

## Cas d'usage

- **Renforcer le contraste local** avec une courbe en S : creuser les ombres, hausser les
  hautes lumières, en laissant les tons moyens presque inchangés.
- **Protéger une plage de tons** (p. ex. le fond de ciel) en aplatissant localement la courbe
  autour de sa valeur, tout en étirant le reste de la dynamique.
- **Corriger une dominante colorée** en appliquant une courbe différente sur un seul canal
  (`channel = R`, `G` ou `B`) plutôt qu'un simple gain global.
- **Affiner un étirement déjà fait** par `HistogramTransformation` ou une STF, avec un contrôle
  point par point impossible à obtenir avec trois curseurs seuls.

## Fonctionnement

L'utilisateur (ou un script) fournit une liste de points `(x, y)` — au minimum les deux
extrémités `(0, 0)` et `(1, 1)` par défaut, ce qui donne l'identité. Le process :

1. **Trie** les points par abscisse croissante (l'ordre de saisie n'importe pas).
2. Construit, pour chaque canal ciblé (`_target_channels`, selon `channel`), la courbe de
   passage par ces points via une **interpolation cubique de Hermite à pentes monotones**
   (PCHIP / Fritsch–Carlson).
3. **Évalue** cette courbe sur chaque pixel du canal, puis **écrête** le résultat dans `[0, 1]`.

Le choix de PCHIP plutôt qu'un spline cubique classique n'est pas anodin : un spline naturel
peut **dépasser** (overshoot) entre deux points proches en valeur mais éloignés en position,
créant des halos ou une inversion locale de tons non voulue. PCHIP garantit que la courbe reste
**monotone entre deux points de contrôle croissants** — pas de dépassement, pas d'inversion —
ce qui est précisément le comportement attendu d'une courbe de tons.

## Mathématiques

Soit $n$ points de contrôle triés $(x_0, y_0), \dots, (x_{n-1}, y_{n-1})$, avec pas
$h_k = x_{k+1} - x_k$ et pentes sécantes $\delta_k = (y_{k+1} - y_k) / h_k$.

**Pentes aux nœuds (Fritsch–Carlson).** Aux extrémités, la pente vaut la sécante adjacente :
$d_0 = \delta_0$, $d_{n-1} = \delta_{n-2}$. Pour un nœud intérieur $k$, si les sécantes qui
l'entourent changent de signe (extremum local), la pente est forcée à zéro pour éviter tout
dépassement :

$$
d_k =
\begin{cases}
0 & \text{si } \delta_{k-1}\,\delta_k \le 0 \\[4pt]
\dfrac{w_1 + w_2}{\dfrac{w_1}{\delta_{k-1}} + \dfrac{w_2}{\delta_k}} & \text{sinon}
\end{cases}
\qquad w_1 = 2h_k + h_{k-1},\quad w_2 = h_k + 2h_{k-1}
$$

(moyenne harmonique pondérée des deux sécantes voisines).

**Évaluation par segment.** Pour $x$ dans l'intervalle $[x_k, x_{k+1}]$, en posant
$t = (x - x_k) / h_k \in [0, 1]$, la valeur interpolée utilise les fonctions de base de
Hermite cubique :

$$
y(x) = h_{00}(t)\,y_k + h_{10}(t)\,h_k\,d_k + h_{01}(t)\,y_{k+1} + h_{11}(t)\,h_k\,d_{k+1}
$$

$$
h_{00}(t)=(1+2t)(1-t)^2,\quad h_{10}(t)=t(1-t)^2,\quad
h_{01}(t)=t^2(3-2t),\quad h_{11}(t)=t^2(t-1)
$$

Enfin, le résultat est écrêté : $y_{\text{final}} = \operatorname{clip}(y(x),\,0,\,1)$. Les
valeurs de $x$ hors de $[x_0, x_{n-1}]$ sont d'abord écrêtées aux bornes avant évaluation.

## Paramètres

- **`points`** — *points* (liste de couples), défaut `[[0.0, 0.0], [1.0, 1.0]]`. Points de
  contrôle `(x, y)` dans `[0, 1]` définissant la courbe de transfert. L'ordre n'a pas
  d'importance (les points sont triés par abscisse avant interpolation) ; deux points
  suffisent pour l'identité, davantage pour une forme complexe. Éviter deux points de même
  abscisse `x`.
- **`channel`** — *enum*, défaut `RGB/K`, choix : `RGB/K`, `R`, `G`, `B`. Canal auquel
  s'applique la courbe. `RGB/K` traite tous les canaux identiquement (ou l'unique canal d'une
  image en niveaux de gris) ; `R`/`G`/`B` cible un seul canal pour une correction colorimétrique.

## Astuces & pièges

> **Attention** — au moins deux points de contrôle sont requis, et il ne doit pas y avoir deux
> points partageant la même abscisse `x` (l'interpolation devient indéfinie : `h_k = 0`).

> **Note** — les points ne sont **pas contraints à être croissants en `y`** : une courbe peut
> volontairement inverser une plage de tons (usage créatif ou technique rare), mais c'est
> alors la monotonie par morceaux qui empêche les dépassements erratiques, pas une contrainte
> globale.

- Pour une courbe en S classique (contraste), placer un point sous la diagonale dans les
  ombres (p. ex. `(0.25, 0.15)`) et un point au-dessus dans les hautes lumières
  (p. ex. `(0.75, 0.85)`).
- Peu de points bien choisis valent mieux qu'une courbe surchargée : PCHIP interpole
  *exactement* par les points fournis, un point mal placé se voit directement dans le résultat.
- Comme pour tout étirement destructif, travaillez idéalement sous **masque** pour protéger
  une région (étoiles, fond de ciel) des variations tonales appliquées ailleurs.

## Voir aussi

- [HistogramTransformation](retina-doc://HistogramTransformation) — étirement à trois curseurs
  (noir/milieu/blanc), plus simple et plus rapide à régler.
- [ArcsinhStretch](retina-doc://ArcsinhStretch) — étirement préservant les rapports de couleur.
- [LocalHistogramEqualization](retina-doc://LocalHistogramEqualization) — contraste local adaptatif (CLAHE).
- [MaskedStretch](retina-doc://MaskedStretch) — étirement itératif préservant les étoiles.

## Références

- PixInsight — *CurvesTransformation* tool reference.
- Fritsch, F. N. & Carlson, R. E. (1980) — *Monotone Piecewise Cubic Interpolation*.
