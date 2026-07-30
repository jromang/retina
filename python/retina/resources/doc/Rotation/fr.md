---
id: Rotation
category: Geometry
title: Rotation
brief: Fait pivoter l'image d'un angle quelconque en degrés, en agrandissant le canevas pour ne rien couper.
keywords: [rotation, géométrie, angle, interpolation, recadrage, canevas]
related: [FastRotation, Crop, Resample, PixelInterpolation]
icon: rotate
references:
  - "PixInsight — Rotation tool reference."
  - "scipy.ndimage.rotate — interpolated array rotation documentation."
---

## Résumé

`Rotation` fait pivoter l'image d'un **angle arbitraire** (en degrés, positif = sens
antihoraire) autour de son centre. Contrairement à un simple recadrage, le canevas de sortie
est **agrandi** pour contenir l'intégralité de l'image tournée : aucun pixel du contenu original
n'est perdu, les coins vides étant remplis de noir. C'est l'outil de rotation « fine » de
Retina, à opposer à `FastRotation` qui ne gère que les multiples de 90° sans interpolation.

## Cas d'usage

- **Redresser une image** légèrement inclinée à cause d'un défaut de mise en station ou d'une
  monture non parfaitement alignée avec le cadre souhaité.
- **Aligner l'orientation Nord-haut** d'une image après un plate-solve, en tournant d'un angle
  de position connu.
- **Composer un mosaïquage manuel** où les panneaux ne partagent pas exactement la même
  orientation de capteur.
- **Effets créatifs** ou rotation de vignettes avant recadrage final.

## Fonctionnement

L'opérateur délègue à `scipy.ndimage.rotate` sur les deux premiers axes de l'image (lignes,
colonnes), en laissant l'axe des canaux couleur intact :

1. Le canevas de sortie est **dimensionné** pour englober la totalité des quatre coins de
   l'image tournée (`reshape=True`) — l'image finale est donc plus grande que l'originale dès
   que l'angle n'est pas multiple de 90°.
2. Chaque pixel de sortie est obtenu par **interpolation par spline** d'ordre `order` à partir
   des pixels d'entrée voisins de sa position antécédente par la rotation inverse.
3. Les zones du canevas qui ne correspondent à aucun pixel source (les coins) sont remplies de
   **noir** (`mode="constant"`, `cval=0.0`).
4. Le résultat est enfin **écrêté** dans `[0, 1]` et reconverti en `float32`.

## Mathématiques

Soit $\theta$ l'angle de rotation (converti en radians), $(c_x, c_y)$ le centre de l'image
d'entrée de dimensions $W \times H$. Pour chaque pixel de sortie $(x', y')$, on retrouve sa
position antécédente dans l'image source par la rotation inverse :

$$
\begin{pmatrix} x \\ y \end{pmatrix}
= R(-\theta)\begin{pmatrix} x' - c_x' \\ y' - c_y' \end{pmatrix}
+ \begin{pmatrix} c_x \\ c_y \end{pmatrix},
\qquad
R(\theta) = \begin{pmatrix} \cos\theta & -\sin\theta \\ \sin\theta & \cos\theta \end{pmatrix}
$$

où $(c_x', c_y')$ est le centre du canevas de sortie. La valeur du pixel est ensuite obtenue par
**interpolation par spline d'ordre `order`** autour de $(x, y)$ (ordre 0 = plus proche voisin,
ordre 1 = bilinéaire, ordres supérieurs = splines de degré croissant, plus lisses mais plus
coûteuses et plus sujettes au ringing sur des bords nets comme les étoiles saturées).

La taille du canevas agrandi est calculée pour englober la boîte englobante de l'image tournée :

$$
W' = \big\lceil\, |W\cos\theta| + |H\sin\theta| \,\big\rceil, \qquad
H' = \big\lceil\, |W\sin\theta| + |H\cos\theta| \,\big\rceil .
$$

## Paramètres

- **`angle`** — *real*, défaut `0.0`, plage `-360`–`360`. Angle de rotation en degrés ; positif
  = sens antihoraire, autour du centre de l'image.
- **`order`** — *int*, défaut `1`, plage `0`–`5`. Ordre de l'interpolation par spline utilisée
  pour rééchantillonner l'image tournée (0 = plus proche voisin, 1 = bilinéaire, jusqu'à 5).

## Astuces & pièges

> **Attention** — le canevas de sortie est **agrandi** et les coins non couverts sont remplis de
> noir (valeur 0). Si l'image doit rester rectangulaire sans bordures noires, enchaînez avec
> `Crop` pour ne conserver que le plus grand rectangle inscrit dans le contenu utile.

> **Note** — `is_maskable = False` : comme toute transformation géométrique, la rotation change
> la forme des données et ne peut pas être combinée avec un masque de blend (qui suppose une
> géométrie identique entre avant et après).

- Un ordre d'interpolation élevé (3–5) lisse davantage mais peut introduire des oscillations
  (ringing) autour des étoiles très contrastées ; l'ordre 1 (bilinéaire) est souvent un bon
  compromis pour les images astro.
- Pour des rotations exactes de 90°/180°/270° ou des miroirs, préférez `FastRotation` : sans
  interpolation, donc sans perte ni flou.
- L'écrêtage final dans `[0, 1]` suppose une image déjà normalisée dans cette plage ; sur une
  image linéaire à forte dynamique, vérifiez qu'aucune information n'est perdue par l'écrêtage.

## Voir aussi

- [FastRotation](retina-doc://FastRotation) — rotations sans perte à 90°/180°/270° et miroirs.
- [Crop](retina-doc://Crop) — recadrer les bordures noires laissées par la rotation.
- [Resample](retina-doc://Resample) — rééchantillonnage par facteur d'échelle, même famille d'interpolation.
- [PixelInterpolation](retina-doc://PixelInterpolation) — réglages d'interpolation partagés par les opérateurs géométriques.

## Références

- PixInsight — *Rotation* tool reference.
- scipy.ndimage.rotate — documentation de la rotation de tableau interpolée.
