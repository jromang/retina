---
id: DynamicCrop
category: Geometry
title: Recadrage dynamique
brief: Recadre une région fractionnaire [0,1] de l'image et la tourne, en une seule passe — le morceau découpé, ou le rectangle incliné lui-même.
keywords: [recadrage, crop, rotation, cadrage, composition, interpolation]
related: [Crop, Rotation, FastRotation, DynamicAlignment]
icon: crop
references:
  - "PixInsight — DynamicCrop tool reference."
  - "scipy.ndimage.rotate — image rotation with spline interpolation."
  - "scipy.ndimage.map_coordinates — sampling an image on an arbitrary grid."
---

## Résumé

`DynamicCrop` combine en **une seule opération** un recadrage rectangulaire et une rotation,
à la manière de l'outil interactif éponyme de PixInsight. Le rectangle de recadrage est
exprimé en **coordonnées fractionnaires** `[0, 1]` (indépendantes de la résolution de l'image),
et l'angle de rotation s'applique **après** le recadrage, sur la région extraite. C'est l'outil
de composition final : cadrer, redresser un horizon ou aligner un axe galactique, et éliminer
les bords irréguliers issus d'un empilement ou d'un recalage.

![Avant — DynamicCrop](figures/before.webp)
![Après — DynamicCrop](figures/after.webp)

*L'image, et un rectangle tracé à 20° lu en une seule passe. La sortie fait exactement la taille du cadre — l'ancien mode, qui tourne après avoir découpé, agrandit le résultat et laisse des coins noirs.*

## Cas d'usage

- **Cadrer la composition finale** d'une image empilée, en éliminant les bords sombres ou les
  artefacts de bord laissés par `StarAlignment`/`Integration`.
- **Redresser une image** dont l'axe (horizon, plan galactique, traînée) n'est pas horizontal,
  en une seule passe recadrage + rotation plutôt que deux process séparés.
- **Isoler une sous-région d'intérêt** (une galaxie, un amas) avant un traitement plus poussé,
  sans dépendre de la taille en pixels de l'image source.
- Préparer une **vignette recadrée** pour publication, avec un rognage des bords après
  correction d'inclinaison.

## Fonctionnement

Le rectangle se lit toujours de la même façon : `x0, y0` (coin haut-gauche) et `x1, y1` (coin
bas-droite) sont des fractions de la largeur/hauteur de l'image, converties en indices de pixels
par arrondi. Des coins inversés (`x1 < x0` ou `y1 < y0`) sont normalisés automatiquement ; une
largeur ou hauteur nulle est forcée à un pixel minimum pour éviter un recadrage vide.

Ce que veut dire `angle`, en revanche, est décidé par **`mode`** :

**`after_crop`** (défaut, et comportement historique). Le rectangle aligné sur les axes est
découpé *d'abord*, puis le morceau extrait est pivoté avec `scipy.ndimage.rotate` :
interpolation **bilinéaire** (ordre 1), `reshape=True` (le canevas de sortie s'agrandit pour
contenir l'image tournée sans la couper), et remplissage à zéro (`mode="constant", cval=0.0`)
des coins désormais hors de la région source. Si l'angle est nul (à $10^{-9}$ près), la rotation
est sautée et seul le recadrage est renvoyé. La sortie est **écrêtée** dans `[0, 1]`. Deux
conséquences à garder en tête : la sortie est **plus grande** que le rectangle, et ses coins sont
**noirs**.

**`rotated_rect`** (le comportement de PixInsight). Le rectangle *lui-même* est incliné, et les
pixels qu'il couvre sont rééchantillonnés en **une seule passe**
(`scipy.ndimage.map_coordinates`, ordre 1, zéro hors de l'image). La sortie fait **exactement**
la taille du rectangle, et n'a aucun coin noir tant que le rectangle incliné reste dans l'image.
La passe unique n'est pas un détail : tourner puis découper appliquerait deux fois le flou de
l'interpolation, et la première passe devrait couvrir une zone plus large que le résultat final
pour ne pas en amputer les coins.

Les deux modes partagent la **même convention de signe** : un angle positif tourne le contenu
dans le sens antihoraire. Changer de mode n'envoie donc jamais l'image de l'autre côté. Noter la
conséquence dans le panneau interactif : en `rotated_rect`, la poignée incline le *cadre*, si
bien que l'incliner dans le sens horaire rend un contenu tourné dans le sens antihoraire — un
cadre qui tourne sur une photographie.

## Mathématiques

Soit une image de largeur $W$ et hauteur $H$. Les coins fractionnaires sont d'abord ordonnés et
convertis en indices entiers :

$$
x_{\min} = \big\lfloor \min(x_0, x_1)\,W \big\rceil, \qquad
x_{\max} = \max\big(\lfloor \max(x_0, x_1)\,W \rceil,\; x_{\min} + 1\big),
$$

et de même pour $y_{\min}, y_{\max}$ avec $H$ (où $\lfloor \cdot \rceil$ note l'arrondi au plus
proche). La région extraite est $C = I[y_{\min}:y_{\max},\, x_{\min}:x_{\max}]$.

La rotation d'angle $\theta$ = `angle` (en degrés) applique à chaque pixel de sortie $(x', y')$
la transformation inverse vers les coordonnées de $C$, centrée sur le centre de l'image :

$$
\begin{pmatrix} x \\ y \end{pmatrix}
=
\begin{pmatrix} \cos\theta & \sin\theta \\ -\sin\theta & \cos\theta \end{pmatrix}
\begin{pmatrix} x' - c'_x \\ y' - c'_y \end{pmatrix}
+
\begin{pmatrix} c_x \\ c_y \end{pmatrix},
$$

où $(c_x, c_y)$ est le centre de $C$ et $(c'_x, c'_y)$ celui du canevas de sortie agrandi.
La valeur en $(x, y)$, généralement non entière, est estimée par **interpolation bilinéaire**
(spline d'ordre 1) sur les quatre pixels voisins de $C$ ; les positions hors de $C$ reçoivent la
valeur constante $0$. Le canevas de sortie a pour dimensions
$W' = |\,\text{largeur}(C)\cos\theta| + |\text{hauteur}(C)\sin\theta|$ et $H'$ symétriquement,
de sorte que la région tournée y tienne entièrement (`reshape=True`).

En mode `rotated_rect`, la grille de sortie *est* le rectangle — $W' = W_C$, $H' = H_C$ — et la
même matrice s'applique directement, autour du centre du rectangle :

$$
\begin{pmatrix} x \\ y \end{pmatrix}
=
\begin{pmatrix} \cos\theta & -\sin\theta \\ \sin\theta & \cos\theta \end{pmatrix}
\begin{pmatrix} u - c_u \\ v - c_v \end{pmatrix}
+
\begin{pmatrix} c_x \\ c_y \end{pmatrix},
$$

où $(u, v)$ parcourt les pixels de sortie, $(c_u, c_v) = \big(\frac{W_C - 1}{2},
\frac{H_C - 1}{2}\big)$ et $(c_x, c_y)$ est le même point en coordonnées image. Les centres sont
pris sur les **centres de pixels** ($\frac{n-1}{2}$) et non sur le bord ($\frac{n}{2}$) : sinon,
à $\theta = 0$, la grille tomberait à un demi-pixel des échantillons d'origine et les deux modes
ne coïncideraient plus. Les échantillons sont lus par `map_coordinates` en interpolation d'ordre 1
(bilinéaire), canal par canal — interpoler aussi entre canaux mélangerait les couleurs. Aucun
écrêtage : l'interpolation bilinéaire est une combinaison convexe, elle ne peut pas dépasser ses
entrées.

## Paramètres

- **`x0`** — *real*, défaut `0.0`, plage `0`–`1`. Bord **gauche** du rectangle de recadrage,
  en fraction de la largeur de l'image.
- **`y0`** — *real*, défaut `0.0`, plage `0`–`1`. Bord **haut** du rectangle, en fraction de la
  hauteur.
- **`x1`** — *real*, défaut `1.0`, plage `0`–`1`. Bord **droit** du rectangle, en fraction de la
  largeur.
- **`y1`** — *real*, défaut `1.0`, plage `0`–`1`. Bord **bas** du rectangle, en fraction de la
  hauteur.
- **`angle`** — *real*, défaut `0.0`, plage `-360`–`360`. Angle de **rotation** en degrés. `0` =
  aucune rotation (le résultat est alors le recadrage seul), et les deux modes coïncident
  exactement.
- **`mode`** — *enum*, défaut `after_crop`, choix : `after_crop`, `rotated_rect`. Ce à quoi
  l'angle s'applique : la **région découpée** (canevas agrandi, coins noirs) ou le **rectangle de
  découpe** lui-même (sortie exactement à la taille du rectangle). Le défaut préserve les
  recettes, projets et icônes de process enregistrés avant l'existence de ce paramètre.

## Astuces & pièges

> **Attention** — en `after_crop`, la rotation agrandit le canevas (`reshape=True`) et remplit
> les coins vides de **noir** (`0.0`). Si vous voulez une image finale sans bord noir, passez en
> `rotated_rect`, fait exactement pour cela, ou recadrez à nouveau après rotation.

> **Note** — en `rotated_rect`, un rectangle qui déborde de l'image n'est pas une erreur : ce qui
> est dehors est échantillonné à `0.0`. C'est une donnée absente, pas une panne — mais cela
> ramène les bords noirs que le mode évite par ailleurs.

> **Note** — les coordonnées `x0/y0/x1/y1` sont **fractionnaires**, pas des pixels : le même
> `ProcessInstance` s'applique donc identiquement à des images de résolutions différentes (utile
> dans une recette rejouée sur plusieurs frames).

- Un ordre de coins inversé (`x1 < x0` ou `y1 < y0`) n'est pas une erreur : le rectangle est
  normalisé silencieusement — utile pour un tracé de sélection GUI dans n'importe quel sens.
- Pour une rotation d'angle multiple de 90° sans perte ni flou d'interpolation, préférez
  `FastRotation`, qui échange/inverse les axes plutôt que de rééchantillonner.
- Ce process n'est **pas masquable** (`is_maskable = False`) : il change la géométrie de
  l'image, un masque (défini en pixels sur la géométrie d'origine) n'aurait plus de sens après.

## Voir aussi

- [Crop](retina-doc://Crop) — recadrage seul, sans rotation.
- [Rotation](retina-doc://Rotation) — rotation seule, sans recadrage préalable.
- [FastRotation](retina-doc://FastRotation) — rotations exactes à 90°/180°/270° et symétries, sans interpolation.
- [DynamicAlignment](retina-doc://DynamicAlignment) — recalage manuel par points de contrôle (translation/rotation/échelle).

## Références

- PixInsight — *DynamicCrop* tool reference.
- scipy.ndimage — *rotate*, rotation d'image par interpolation spline.
- scipy.ndimage — *map_coordinates*, échantillonnage d'une image sur une grille arbitraire.
