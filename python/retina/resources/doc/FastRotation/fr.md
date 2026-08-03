---
id: FastRotation
category: Geometry
title: Rotation rapide
brief: Rotations sans perte multiples de 90° et miroirs horizontal/vertical, par simple réindexation numpy.
keywords: [rotation, miroir, flip, 90 degrés, sans perte, orientation, géométrie]
related: [Rotation, Crop, IntegerResample, Resample]
icon: rotate-clockwise
references:
  - "PixInsight — FastRotation tool reference."
  - "NumPy — numpy.rot90, flip d'axes par réindexation."
---

## Résumé

`FastRotation` effectue les cinq transformations géométriques les plus courantes — rotation
de 90°, 180°, 270° et miroir horizontal ou vertical — en **réindexant** simplement le tableau
de pixels, sans aucune interpolation. Contrairement à `Rotation` (angle quelconque), ces
opérations sont **exactes et sans perte** : chaque pixel de sortie est une copie directe d'un
pixel d'entrée, jamais une combinaison pondérée de voisins.

![Avant — FastRotation](figures/before.webp)
![Après — FastRotation](figures/after.webp)

*Avant, et après un quart de tour. Rien n'est interpolé et aucun coin n'est perdu — les mêmes pixels, dans un autre ordre.*

## Cas d'usage

- **Corriger l'orientation d'une caméra** montée à 90°/180°/270° de la référence attendue,
  avant alignement ou empilement.
- **Réconcilier des frames** issues d'instruments différents (caméra guide, filtre roue avec
  monture retournée) avant `StarAlignment`.
- **Corriger un miroir optique** (train optique avec renvoi, caméra montée en miroir) via
  `hmirror`/`vmirror`, en amont de tout traitement photométrique ou astrométrique.
- **Réorienter rapidement** une image pour l'affichage ou la composition, sans dégrader la
  netteté — utile juste avant une capture d'écran ou un export final.

## Fonctionnement

L'opérateur choisit, selon le paramètre `operation`, l'une des cinq réindexations suivantes du
tableau `(H, W, C)` :

- `rotate90` / `rotate180` / `rotate270` — rotation antihoraire du plan image via
  `numpy.rot90` sur les axes `(0, 1)` (lignes/colonnes), respectivement 1, 2 ou 3 quarts de tour.
- `hmirror` — inversion de l'axe des colonnes (`data[:, ::-1, :]`), miroir gauche-droite.
- `vmirror` — inversion de l'axe des lignes (`data[::-1, :, :]`), miroir haut-bas.

Aucun pixel n'est recalculé : le tableau résultat est une **permutation** du tableau d'entrée,
puis rendu contigu en mémoire (`np.ascontiguousarray`) pour la suite du pipeline. Les rotations
de 90°/270° **échangent largeur et hauteur** de l'image ; 180°, `hmirror` et `vmirror`
conservent les dimensions. Comme toute la catégorie `Geometry`, le process n'est **pas
maskable** (`is_maskable = False`) : un masque suppose une géométrie inchangée entre entrée et
sortie, ce qui n'est garanti que pour 180°/miroirs, pas pour 90°/270°.

## Mathématiques

Soit $I(y, x)$ l'image d'entrée de dimensions $H \times W$. Les cinq opérations sont des
permutations exactes de coordonnées, sans aucune interpolation ni pondération :

$$
\begin{aligned}
\text{rotate90}(I)(y, x) &= I(x,\; W - 1 - y) \\
\text{rotate180}(I)(y, x) &= I(H - 1 - y,\; W - 1 - x) \\
\text{rotate270}(I)(y, x) &= I(H - 1 - x,\; y) \\
\text{hmirror}(I)(y, x) &= I(y,\; W - 1 - x) \\
\text{vmirror}(I)(y, x) &= I(H - 1 - y,\; x)
\end{aligned}
$$

Chaque valeur de sortie étant une **copie exacte** d'une valeur d'entrée (bijection sur les
indices), l'opération est involutive ou cyclique selon le cas ($\text{rotate90}^4 = \text{id}$,
$\text{hmirror}^2 = \text{id}$) et **ne modifie ni le bruit ni la dynamique** des pixels — à
l'opposé de `Rotation`, dont l'interpolation à angle quelconque lisse légèrement le signal et
introduit une corrélation entre pixels voisins.

## Paramètres

- **`operation`** — *enum*, défaut `rotate90`, choix : `rotate90`, `rotate180`, `rotate270`,
  `hmirror`, `vmirror`. Transformation géométrique à appliquer : rotation antihoraire d'un,
  deux ou trois quarts de tour, ou miroir horizontal (gauche-droite) / vertical (haut-bas).

## Astuces & pièges

> **Attention** — `rotate90` et `rotate270` échangent largeur et hauteur : toute vue liée
> (preview, masque, WCS/astrométrie) doit être recalculée après coup, ces opérations ne
> préservant pas la géométrie d'origine.

> **Note** — pour un angle arbitraire (ex. aligner un cadre sur le nord céleste avec un
> décalage de quelques degrés), utilisez `Rotation`, qui interpole ; `FastRotation` ne couvre
> que les multiples exacts de 90° et les miroirs, sans dégradation du signal.

- Combinez rotation et miroir en deux passes successives pour obtenir n'importe laquelle des
  8 symétries du carré (groupe diédral $D_4$) sans jamais interpoler.
- Si un WCS (solution astrométrique) est déjà attaché à la fenêtre, une rotation de 90°/270°
  invalide son orientation implicite ; re-résoudre avec `PlateSolve` après coup si nécessaire.

## Voir aussi

- [Rotation](retina-doc://Rotation) — rotation à angle quelconque, avec interpolation.
- [Crop](retina-doc://Crop) — recadrage rectangulaire.
- [IntegerResample](retina-doc://IntegerResample) — rééchantillonnage par facteur entier.
- [Resample](retina-doc://Resample) — rééchantillonnage par facteur d'échelle quelconque.

## Références

- PixInsight — *FastRotation* tool reference.
- NumPy — *numpy.rot90*, flip d'axes par réindexation.
