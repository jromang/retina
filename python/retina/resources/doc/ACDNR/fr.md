---
id: ACDNR
category: NoiseReduction
title: ACDNR (débruitage adaptatif piloté par le contraste)
brief: "Fond gaussien lissé mélangé avec l'original via un masque de protection dérivé du gradient local."
keywords: [débruitage, bruit, gradient, masque de protection, gaussien, fond de ciel, structures]
related: [NoiseReduction, TGVDenoise, NonLocalMeansDenoise, WaveletDenoise]
icon: sparkles
references:
  - "PixInsight — ACDNR (Adaptive Contrast-Driven Noise Reduction) tool reference."
  - "scipy.ndimage — gaussian_filter, gaussian_gradient_magnitude."
---

## Résumé

`ACDNR` reproduit le cœur de l'outil éponyme de PixInsight : un débruitage **adaptatif** qui
lisse fortement le bruit dans les zones plates (fond de ciel, halos diffus) tout en préservant
les détails à fort contraste (étoiles, bords de structures nébuleuses). Le principe est simple
et robuste — un flou gaussien standard, mélangé pixel à pixel avec l'image d'origine à travers
un **masque de protection** calculé à partir du gradient local de l'image.

## Cas d'usage

- **Nettoyer le bruit de fond** d'une image déjà étirée sans flouter les étoiles ni les bords
  des nébulosités.
- **Passe de finition douce** en fin de traitement, après un débruitage plus fort (NLM, TGV)
  pour lisser les résidus sans perdre les micro-structures.
- **Alternative rapide** à `NonLocalMeansDenoise`/`TGVDenoise` quand le temps de calcul compte :
  ACDNR est une simple combinaison de deux filtres `scipy.ndimage`, donc très rapide.
- **Réglage progressif** : en montant `protection`, on peut passer continûment d'un lissage
  quasi-total à une quasi-préservation de l'image d'origine.

## Fonctionnement

Pour chaque canal de couleur, l'algorithme calcule deux images dérivées :

1. **Un flou gaussien** `blurred` de l'image, avec un rayon `sigma` — c'est la version « lissée »
   candidate, qui supprime le bruit haute fréquence mais aussi les détails fins.
2. **Une carte de gradient** `grad` (magnitude du gradient d'une version légèrement gaussienne-
   lissée, rayon fixe 1.0) qui repère les zones de fort contraste : contours d'étoiles, bords de
   structures. Cette carte est normalisée par son maximum, puis mise à l'échelle par
   `protection` et écrêtée dans `[0, 1]` pour former le **masque de protection** — 1 signifie
   « garder l'original », 0 signifie « prendre entièrement le flou ».

Le résultat final est un **mélange linéaire par pixel** entre l'original et le flou, pondéré par
ce masque : les zones à fort gradient (donc `protect` proche de 1) restent quasiment intactes,
les zones plates (`protect` proche de 0) sont remplacées par la version lissée — c'est là tout
le bruit qui disparaît.

## Mathématiques

Soit $I$ un canal image et $\sigma$ le paramètre `sigma`. On définit le flou gaussien :

$$ B = G_\sigma * I $$

où $G_\sigma$ est le noyau gaussien de rayon $\sigma$. On calcule ensuite la magnitude du
gradient local, après un lissage gaussien fixe de rayon 1 (pour limiter la sensibilité au bruit
pixel-à-pixel) :

$$ \nabla_g I = \left\| \nabla \big(G_1 * I\big) \right\|_2
= \sqrt{\left(\frac{\partial (G_1 * I)}{\partial x}\right)^2
+ \left(\frac{\partial (G_1 * I)}{\partial y}\right)^2} $$

Ce champ est normalisé par son maximum $g_{\max}$ (avec garde-fou contre la division par zéro),
puis mis à l'échelle par le paramètre `protection` $p \in [0,1]$ et écrêté :

$$ M(x,y) = \operatorname{clip}\!\left(p \cdot \frac{\nabla_g I(x,y)}{g_{\max}},\; 0,\; 1\right) $$

Le pixel de sortie est le mélange convexe :

$$ I'(x,y) = M(x,y)\, I(x,y) + \big(1 - M(x,y)\big)\, B(x,y) $$

Avec `protection = 0`, $M \equiv 0$ partout : la sortie est simplement le flou gaussien complet
(débruitage maximal, structures floutées). Avec `protection = 1`, $M$ atteint 1 exactement là
où le gradient local est maximal dans l'image — ces pixels-là restent inchangés, tandis que le
reste du fond continue d'être lissé proportionnellement à son propre gradient.

## Paramètres

- **`sigma`** — *real*, défaut `2.0`, plage `0.1`–`20.0`. Rayon (écart-type) du flou gaussien
  appliqué au fond. Plus grand = lissage plus fort du bruit, mais flou plus large dans les zones
  non protégées.
- **`protection`** — *real*, défaut `0.5`, plage `0.0`–`1.0`. Facteur d'échelle du masque de
  protection dérivé du gradient. `0` = aucune protection (flou uniforme sur toute l'image) ;
  `1` = protection maximale des zones à fort gradient (étoiles et bords quasi intacts).

## Astuces & pièges

> **Attention** — le seuil de protection est **relatif au maximum de gradient de l'image**
> (`grad.max()`). Une seule étoile très saturée peut écraser l'échelle et rendre le masque trop
> restrictif ailleurs ; dans ce cas, réduisez `protection` ou débruitez d'abord un fond isolé
> (preview) plutôt que l'image entière.

- Un `sigma` trop grand associé à une `protection` faible peut laisser un halo flou visible
  autour des étoiles, faute de transition progressive dans le masque.
- ACDNR n'estime pas le niveau de bruit réel (contrairement à `NonLocalMeansDenoise`) : il n'y a
  pas de mise à l'échelle automatique — ajustez `sigma`/`protection` à l'œil ou via un aperçu.
- Pour un bruit chromatique important, travaillez de préférence sur la luminance seule
  (`ConvertToGrayscale` temporaire ou masque de luminance) afin d'éviter les artefacts de
  bordure colorés.

## Voir aussi

- [NoiseReduction](retina-doc://NoiseReduction) — débruitage générique multi-méthodes.
- [TGVDenoise](retina-doc://TGVDenoise) — variation généralisée totale, sans effet d'escalier.
- [NonLocalMeansDenoise](retina-doc://NonLocalMeansDenoise) — moyenne de patchs similaires.
- [WaveletDenoise](retina-doc://WaveletDenoise) — débruitage par seuillage en ondelettes.

## Références

- PixInsight — *ACDNR* (Adaptive Contrast-Driven Noise Reduction) tool reference.
- scipy.ndimage — *gaussian_filter*, *gaussian_gradient_magnitude*.
