---
id: GalaxyModel
category: MultiscaleProcessing
title: Modèle de galaxie (isophotes)
brief: Ajuste des ellipses isophotes concentriques sur une galaxie puis soustrait le modèle lisse pour révéler les structures superposées.
keywords: [galaxie, isophotes, ellipse, photutils, bras spiraux, modèle lisse, résidu]
related: [RadialProfileMeasurement, BackgroundExtraction, LarsonSekanina, MultiscaleMedianTransform]
icon: atom
references:
  - "photutils.isophote — Ellipse, EllipseGeometry, build_ellipse_model."
  - "Jedrzejewski, R. (1987), MNRAS 226, 747 — Adaptive iterative isophote-fitting method (IRAF ELLIPSE)."
---

## Résumé

`GalaxyModel` ajuste une famille d'**ellipses isophotes concentriques** sur le corps lisse d'une
galaxie (méthode `photutils.isophote.Ellipse`, héritière de l'algorithme ELLIPSE d'IRAF), puis
reconstruit à partir de ces ellipses un **modèle lisse** de la distribution de lumière. Soustrait
de l'image d'origine, ce modèle fait apparaître tout ce qui s'écarte de la symétrie elliptique —
bras spiraux, barres, amas globulaires superposés, queues de marée, poussière — en éliminant le
gradient de luminosité dominant du disque/bulbe qui, sinon, masque ces détails plus faibles.

## Cas d'usage

- **Révéler les bras spiraux et la structure fine** d'une galaxie dont le corps lisse écrase le
  contraste des détails, en travaillant sur le résidu (image − modèle).
- **Isoler les amas globulaires ou les régions HII** superposés au disque, plus faciles à repérer
  et à traiter (accentuation, coloration) une fois le fond galactique aplati.
- **Détecter des queues de marée ou des irrégularités** trahissant une interaction ou une fusion,
  invisibles sous le halo lumineux du corps principal.
- **Exporter le modèle seul** (`subtract=False`) pour l'inspecter, le comparer à un profil radial,
  ou l'utiliser comme référence de symétrie.

## Fonctionnement

Le process traite chaque canal indépendamment :

1. Le centre de départ `(x0, y0)` est fixé (ou pris au milieu de l'image si `-1`), et une
   géométrie d'ellipse initiale est construite avec le demi-grand axe `sma0`, l'ellipticité `eps`
   et un angle de position nul.
2. `Ellipse.fit_image()` fait croître/décroître cette géométrie de proche en proche (pas
   géométrique) et, à chaque rayon, **ajuste** le centre, l'ellipticité et l'angle de position en
   minimisant les harmoniques de Fourier de basse fréquence de l'intensité échantillonnée le long
   de l'ellipse — méthode itérative de Jedrzejewski (1987), portée depuis IRAF ELLIPSE. Le
   résultat est une liste d'isophotes ajustées (`isolist`), une par rayon.
3. `build_ellipse_model()` interpole ces isophotes pour reconstruire une **image lisse pleine
   résolution** : chaque pixel reçoit l'intensité de l'isophote qui passe par sa position radiale.
4. Selon `subtract`, la sortie est le **résidu** (canal − modèle) ou le **modèle** lui-même ;
   le résultat est ramené dans `[0, 1]`.

Si l'ajustement ne converge sur **aucune** isophote pour un canal (galaxie trop faible, centre mal
placé, image saturée…), ce canal est renvoyé **inchangé**, sans erreur — le process est donc
silencieusement partiel en cas d'échec.

## Mathématiques

Pour une ellipse de centre $(x_0, y_0)$, demi-grand axe $a$ (le `sma` courant), ellipticité
$\varepsilon = 1 - b/a$ et angle de position $\theta_0$, l'intensité est échantillonnée le long du
contour elliptique en fonction de l'angle excentrique $\theta$. Elle est décomposée en série de
Fourier tronquée :

$$ I(\theta) \approx I_0 + A_1 \sin\theta + B_1 \cos\theta + A_2 \sin 2\theta + B_2 \cos 2\theta. $$

$I_0$ est l'**intensité moyenne de l'isophote** (le niveau retenu pour cette valeur de $a$) ; les
harmoniques $A_1, B_1$ traduisent un **mauvais centrage**, et $A_2, B_2$ une **mauvaise
ellipticité ou un mauvais angle de position**. À chaque itération, l'algorithme met à jour
$(x_0, y_0, \varepsilon, \theta_0)$ dans la direction qui réduit l'amplitude de ces harmoniques,
jusqu'à convergence ou échec (bruit trop fort, bord d'image, isophote non fermée).

Le modèle reconstruit $M(x,y)$ interpole $I_0(a)$ entre les rayons ajustés successifs. La sortie
est alors, canal par canal :

$$ I_{\text{sortie}}(x,y) = \operatorname{clip}\!\big(I(x,y) - M(x,y),\; 0,\; 1\big) \quad
   \text{(si `subtract=True`)}, \qquad
   I_{\text{sortie}}(x,y) = M(x,y) \quad \text{(sinon)}. $$

## Paramètres

- **`x0`** — *int*, défaut `-1`, plage `-1`–`1000000`. Centre X de départ en pixels ; `-1` = milieu
  de l'image.
- **`y0`** — *int*, défaut `-1`, plage `-1`–`1000000`. Centre Y de départ en pixels ; `-1` = milieu
  de l'image.
- **`sma0`** — *real*, défaut `10.0`, plage `1.0`–`1000.0`. Demi-grand axe (pixels) de la première
  isophote ajustée ; point de départ de la croissance géométrique vers l'intérieur et l'extérieur.
- **`eps`** — *real*, défaut `0.2`, plage `0.0`–`0.95`. Ellipticité initiale $1 - b/a$ de la
  géométrie de départ (0 = cercle, proche de 1 = ellipse très aplatie).
- **`subtract`** — *bool*, défaut `True`. Si vrai, sortie = image − modèle (résidu). Si faux,
  sortie = modèle lisse lui-même.

## Astuces & pièges

> **Attention** — l'ajustement se fait **canal par canal**, indépendamment. Sur une image
> couleur, des convergences différentes selon les canaux (ou un échec sur un seul canal, qui
> retombe sur l'original) produisent des **franges colorées** dans le résidu. Pour un résultat
> propre, il est souvent préférable d'appliquer le process à une version en niveaux de gris ou à
> la luminance, puis de recombiner.

> **Note** — le process n'est **pas maskable** (`is_maskable = False`). Pour ne travailler que sur
> la galaxie, isolez-la au préalable dans une `Preview` ou un `Crop` avant d'exécuter le process.

- Choisissez `sma0` sur une isophote bien définie du disque, à l'écart du noyau (souvent saturé ou
  très piqué) et des étoiles de premier plan brillantes.
- Une `eps` initiale trop éloignée de la vraie ellipticité de la galaxie peut empêcher la
  convergence dès les premiers rayons ; une estimation grossière à l'œil suffit généralement.
- Un échec silencieux (canal inchangé) est fréquent sur des galaxies faibles ou peu contrastées :
  vérifiez toujours le résultat en sortant d'abord le modèle seul (`subtract=False`).
- Pour des galaxies fortement asymétriques (interaction, fusion), l'hypothèse d'isophotes
  elliptiques est mise à mal : les harmoniques d'ordre 2 ne convergeront pas bien, ce qui est en
  soi révélateur mais limite la qualité du modèle lissé.

## Voir aussi

- [RadialProfileMeasurement](retina-doc://RadialProfileMeasurement) — mesure de profil radial,
  complémentaire à l'analyse d'isophotes.
- [BackgroundExtraction](retina-doc://BackgroundExtraction) — même logique de modèle lisse
  soustrait, appliquée au fond de ciel plutôt qu'à une galaxie.
- [LarsonSekanina](retina-doc://LarsonSekanina) — autre technique de rehaussement par soustraction
  d'un modèle radial/rotationnel lisse, pour les comètes.
- [MultiscaleMedianTransform](retina-doc://MultiscaleMedianTransform) — séparation de structures à
  différentes échelles, alternative pour révéler des détails superposés.

## Références

- photutils.isophote — *Ellipse*, *EllipseGeometry*, *build_ellipse_model*.
- Jedrzejewski, R. (1987), *MNRAS* 226, 747 — méthode itérative adaptative d'ajustement
  d'isophotes (IRAF ELLIPSE).
