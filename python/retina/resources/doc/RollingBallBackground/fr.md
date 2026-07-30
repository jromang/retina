---
id: RollingBallBackground
category: BackgroundModelization
title: Fond par boule roulante (Rolling Ball)
brief: Extraction rapide du fond de ciel par ouverture morphologique — une boule qu'on fait rouler sous la surface d'intensité (skimage).
keywords: [fond de ciel, gradient, rolling ball, morphologie, skimage, ABE, vignetage]
related: [BackgroundExtraction, DynamicBackgroundExtraction, BackgroundNeutralization, GradientCorrection]
icon: circle
references:
  - "Sternberg, S. R. — « Biomedical Image Processing », Computer 16(1), 1983 (algorithme rolling-ball)."
  - "scikit-image — documentation de `skimage.restoration.rolling_ball`."
  - "PixInsight — AutomaticBackgroundExtractor (outil de comparaison)."
---

## Résumé

`RollingBallBackground` estime le **fond de ciel** en faisant rouler virtuellement une boule
de rayon `radius` sous la surface d'intensité de l'image (l'intensité jouant le rôle d'altitude).
La position du sommet de la boule à chaque pixel donne le **modèle de fond**. C'est une
alternative **rapide** à [BackgroundExtraction](retina-doc://BackgroundExtraction) : pas de
grille de boîtes ni de sigma-clipping, juste une opération morphologique classique (méthode de
Sternberg, popularisée par ImageJ) — bien adaptée aux previews et aux champs où un seul rayon
suffit à séparer fond et signal.

## Cas d'usage

- **Aplatir rapidement** un gradient de pollution lumineuse ou de vignetage résiduel, quand la
  vitesse prime sur le contrôle fin par boîtes de `BackgroundExtraction`.
- **Prévisualiser** l'effet d'une extraction de fond avant de régler des paramètres plus
  coûteux (`box_size`, estimateur robuste) sur une méthode plus lente.
- Préparer un fond plat avant `BackgroundNeutralization` et la calibration couleur, sur des
  champs sans structure étendue proche de la taille de la boule.
- Isoler de petites structures brillantes (étoiles, artefacts ponctuels) en sortant le modèle
  seul (`subtract = False`) pour inspection.

## Fonctionnement

Chaque canal est traité **indépendamment**. L'image est vue comme un relief où l'altitude est
l'intensité du pixel : une boule de rayon `radius` (en pixels) est roulée par en dessous de ce
relief, sans jamais le traverser. À chaque position `(x, y)`, l'altitude du sommet de la boule
en contact avec la surface définit la valeur de fond `B(x, y)`. Le calcul (`skimage.restoration.
rolling_ball`) est **exact**, pas une approximation par sous-échantillonnage.

Une conséquence directe : toute structure plus **étroite** que la boule (étoiles, artefacts
ponctuels) ne peut pas faire dévier la boule vers le haut — elle est naturellement exclue du
modèle de fond, sans qu'il soit nécessaire de masquer les étoiles au préalable. À l'inverse, une
structure **plus large** que le rayon (nébulosité étendue, cœur de galaxie) est en partie
« avalée » par la boule et disparaît du résultat si `subtract = True`.

Selon `subtract`, la sortie est soit l'image moins le fond (`I - B`), soit le modèle de fond `B`
lui-même, dans les deux cas écrêtée à `[0, 1]`.

## Mathématiques

Notons $I(x,y)$ l'intensité (l'« altitude ») et $R$ = `radius`. La boule de rayon $R$ définit un
noyau sphérique :

$$ K_R(u,v) = \sqrt{R^2 - u^2 - v^2}, \qquad u^2 + v^2 \le R^2. $$

Faire rouler cette boule sous $I$ équivaut à une **ouverture morphologique en niveaux de gris**
par le noyau non plat $K_R$, c'est-à-dire une érosion suivie d'une dilatation :

$$ E(x,y) = \min_{u^2+v^2 \le R^2} \big[\, I(x+u,\,y+v) - K_R(u,v) \,\big] $$

$$ B(x,y) = \max_{u^2+v^2 \le R^2} \big[\, E(x+u,\,y+v) + K_R(u,v) \,\big] $$

$B$ est le **modèle de fond**. La sortie du process est :

$$ I'(x,y) = \operatorname{clip}\!\big(I(x,y) - B(x,y),\; 0,\; 1\big) \quad \text{si } \texttt{subtract} = \text{Vrai}, $$
$$ I'(x,y) = \operatorname{clip}\!\big(B(x,y),\; 0,\; 1\big) \quad \text{sinon.} $$

La complexité de l'algorithme est **polynomiale en $R$** (degré égal à la dimension spatiale,
donc $O(R^2)$ par pixel en 2D) : un rayon élevé sur une grande image peut devenir coûteux.

## Paramètres

- **`radius`** — *real*, défaut `50.0`, plage `1.0`–`2000.0`. Rayon (en pixels) de la boule
  roulée sous la surface d'intensité. Fixe l'échelle spatiale séparant fond et signal : toute
  structure plus étroite que la boule est traitée comme du bruit/signal ponctuel et exclue du
  fond ; toute structure plus large est absorbée dans le fond. Un rayon trop petit ronge la
  nébulosité étendue ; un rayon trop grand ignore les gradients à petite échelle et ralentit
  fortement le calcul (complexité polynomiale en `radius`).
- **`subtract`** — *bool*, défaut `True`. Si Vrai, soustrait le modèle de fond de l'image
  (`I - B`, écrêté). Si Faux, sort directement le modèle de fond `B` estimé, utile pour
  vérifier qu'il ne contient pas de signal réel avant de l'appliquer.

## Astuces & pièges

> **Attention** — contrairement à `BackgroundExtraction` (qui utilise un sigma-clipping par
> boîtes), cette méthode n'a **aucune connaissance statistique** du bruit : elle repose
> uniquement sur la géométrie du relief d'intensité. Sur une image très bruitée, un lissage
> gaussien léger avant l'extraction améliore la stabilité du modèle.

- Commencez par sortir le modèle seul (`subtract = False`) pour vérifier visuellement qu'il ne
  mord pas sur une nébulosité étendue ou le cœur d'une galaxie.
- Le rayon doit rester **nettement supérieur** au diamètre apparent des étoiles les plus larges,
  sous peine de créer des halos sombres autour d'elles après soustraction.
- Sur un grand champ avec gradient complexe (plusieurs sources de pollution lumineuse), préférez
  `BackgroundExtraction` (grille de boîtes + estimateur robuste) ou
  [DynamicBackgroundExtraction](retina-doc://DynamicBackgroundExtraction) (points manuels), plus
  flexibles qu'un rayon unique.
- Le traitement canal par canal peut légèrement dérégler la balance des couleurs si le fond
  diffère entre canaux ; contrôlez le résultat avec `BackgroundNeutralization` ensuite.

## Voir aussi

- [BackgroundExtraction](retina-doc://BackgroundExtraction) — extraction de fond par grille robuste (≈ABE), plus fine mais plus lente.
- [DynamicBackgroundExtraction](retina-doc://DynamicBackgroundExtraction) — fond à partir de points choisis manuellement (≈DBE).
- [BackgroundNeutralization](retina-doc://BackgroundNeutralization) — neutralisation colorimétrique du fond une fois aplati.
- [GradientCorrection](retina-doc://GradientCorrection) — correction de gradient global.

## Références

- Sternberg, S. R. — *Biomedical Image Processing*, Computer 16(1), 1983 (algorithme rolling-ball).
- scikit-image — documentation de `skimage.restoration.rolling_ball`.
- PixInsight — *AutomaticBackgroundExtractor* (outil de comparaison).
