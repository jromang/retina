---
id: GradientCorrection
category: BackgroundModelization
title: Correction de gradient
brief: Retire un gradient de fond modélisé par une surface polynomiale robuste (ajustement global, pas de grille).
keywords: [gradient, fond de ciel, pollution lumineuse, polynôme, vignettage, sigma-clip]
related: [BackgroundExtraction, MultiscaleGradientCorrection, DynamicBackgroundExtraction, RollingBallBackground]
icon: chart-line
references:
  - "PixInsight — DynamicBackgroundExtraction / AutomaticBackgroundExtractor tool reference."
  - "astropy.stats — sigma_clip pour le rejet robuste des valeurs extrêmes."
  - "numpy.linalg.lstsq — ajustement par moindres carrés."
---

## Résumé

`GradientCorrection` modélise le fond de ciel par une **surface polynomiale bivariée unique**,
ajustée sur l'image entière par moindres carrés, puis la soustrait des pixels (ou l'affiche
telle quelle). Contrairement à `BackgroundExtraction`, qui découpe l'image en boîtes locales,
ce process ajuste **un seul polynôme global** de degré réglable — un outil rapide et léger,
bien adapté aux gradients doux et globaux (pollution lumineuse, vignettage résiduel, lueur
lunaire) plutôt qu'aux variations locales complexes.

## Cas d'usage

- **Retirer un gradient de pollution lumineuse** à faible degré (linéaire ou faiblement
  courbe) sur un champ homogène, sans avoir à poser de points d'échantillonnage manuels.
- **Corriger un vignettage résiduel** mal calibré par les flats, avec un polynôme de degré 2.
- **Dégrossir rapidement** un fond avant un passage plus fin par
  [DynamicBackgroundExtraction](retina-doc://DynamicBackgroundExtraction) ou
  [BackgroundExtraction](retina-doc://BackgroundExtraction).
- **Inspecter le modèle seul** (`subtract = False`) pour vérifier qu'il ne capture pas de signal
  astrophysique avant de l'appliquer.

## Fonctionnement

Pour chaque canal de couleur, indépendamment :

1. Les coordonnées de pixel `(x, y)` sont normalisées dans `[0, 1]` sur la largeur et la hauteur
   de l'image, puis tous les **monômes** $x^i y^j$ avec $i + j \le$ `degree` sont générés —
   c'est la base de la surface polynomiale à ajuster.
2. Un **rejet robuste** (`astropy.stats.sigma_clip`, seuil à 3 σ) écarte les valeurs de pixel
   trop éloignées de la médiane globale : étoiles, nébulosités marquées, artefacts. Seuls les
   pixels de fond restants participent à l'ajustement.
3. Les **coefficients du polynôme** sont estimés par moindres carrés (`numpy.linalg.lstsq`) sur
   les échantillons conservés, puis la surface est **réévaluée sur tous les pixels** de l'image
   (y compris ceux masqués à l'étape 2) pour obtenir un modèle continu et complet.
4. Selon `subtract`, le résultat est soit `image − modèle + pedestal` (fond aplani, décalé pour
   rester positif), soit le **modèle seul** — utile pour l'inspecter avant de valider la
   correction.

Le fait d'ajuster une seule surface globale (plutôt qu'une grille de boîtes locales) rend le
process rapide et robuste aux petits champs, mais moins capable de suivre des gradients très
irréguliers ; voir [MultiscaleGradientCorrection](retina-doc://MultiscaleGradientCorrection)
pour une approche à base d'ondelettes qui s'affranchit de cette limite.

## Mathématiques

Soit un canal image $I(x,y)$ de dimensions $H \times W$. Les coordonnées sont normalisées :

$$ x_n = \frac{x}{W-1}, \qquad y_n = \frac{y}{H-1} \in [0,1]. $$

Pour un degré $d$ = `degree`, la base des monômes retenus est

$$ \{\, x_n^{\,i}\, y_n^{\,j} \;:\; i,j \ge 0,\ i+j \le d \,\}, $$

de taille $\binom{d+2}{2}$ (6 termes pour $d=1$, 10 pour $d=2$, etc.). Le modèle de surface
s'écrit comme combinaison linéaire de cette base :

$$ S(x_n,y_n) = \sum_{i+j \le d} c_{ij}\; x_n^{\,i}\, y_n^{\,j}. $$

Après rejet robuste des valeurs aberrantes (masque $M$ issu d'un sigma-clip à 3 σ sur les
intensités), les coefficients $c_{ij}$ minimisent l'erreur quadratique sur les seuls pixels
retenus :

$$ \hat{c} = \arg\min_{c} \sum_{(x,y) \in M} \big( I(x,y) - S(x_n,y_n;c) \big)^2, $$

résolu par moindres carrés (décomposition SVD via `numpy.linalg.lstsq`). L'image corrigée
est enfin :

$$ I'(x,y) = I(x,y) - S(x_n,y_n;\hat{c}) + p, \qquad p = \texttt{pedestal}, $$

avec écrêtage final dans $[0,1]$. Avec `subtract = False`, la sortie est $S(x_n,y_n;\hat{c})$
directement (sans piédestal).

## Paramètres

- **`degree`** — *int*, défaut `1`, plage `1`–`5`. Degré du polynôme bivarié ajusté au fond.
  `1` = plan incliné (gradient linéaire simple) ; les degrés supérieurs capturent des
  courbures de plus en plus complexes, au risque d'absorber du signal réel si trop élevés.
- **`pedestal`** — *real*, défaut `0.1`, plage `0`–`1`. Décalage additif appliqué après
  soustraction, pour éviter les valeurs négatives écrêtées à zéro dans les zones de fond faible.
- **`subtract`** — *bool*, défaut `True`. Si vrai, soustrait le modèle de l'image (fond
  aplani) ; si faux, produit le modèle de surface lui-même, pour inspection.

## Astuces & pièges

> **Attention** — un degré élevé (4–5) sur un champ riche en nébulosité étendue peut confondre
> le signal diffus avec le gradient et l'aspirer dans le modèle. Commencez toujours par
> `degree = 1` ou `2` et vérifiez le modèle (`subtract = False`) avant de valider.

> **Note** — le rejet sigma-clip protège des étoiles ponctuelles et des artefacts locaux, mais
> pas des nébulosités étendues à faible contraste : celles-ci peuvent rester dans l'échantillon
> et biaiser légèrement l'ajustement.

- Sur un gradient très irrégulier (angle de mur, réflexion locale), un polynôme global sature
  vite en qualité d'ajustement ; préférez alors
  [DynamicBackgroundExtraction](retina-doc://DynamicBackgroundExtraction) (points manuels) ou
  [BackgroundExtraction](retina-doc://BackgroundExtraction) (grille locale).
- Le process est **maskable** : appliquez un masque pour protéger explicitement une galaxie ou
  une nébuleuse étendue de la soustraction, en plus du rejet robuste automatique.
- Ce process n'est pas global : il s'applique à la vue active (ou une preview), pas à un lot de
  fichiers.

## Voir aussi

- [BackgroundExtraction](retina-doc://BackgroundExtraction) — modélisation locale du fond par grille de boîtes (≈ABE).
- [MultiscaleGradientCorrection](retina-doc://MultiscaleGradientCorrection) — retrait de gradient par résidu d'ondelettes starlet.
- [DynamicBackgroundExtraction](retina-doc://DynamicBackgroundExtraction) — fond modélisé à partir de points d'échantillonnage manuels (≈DBE).
- [RollingBallBackground](retina-doc://RollingBallBackground) — extraction de fond par algorithme rolling-ball.

## Références

- PixInsight — *DynamicBackgroundExtraction* / *AutomaticBackgroundExtractor* tool reference.
- astropy.stats — *sigma_clip* pour le rejet robuste des valeurs extrêmes.
- numpy.linalg.lstsq — ajustement par moindres carrés.
