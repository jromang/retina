---
id: BackgroundNeutralization
category: ColorCalibration
title: Neutralisation du fond
brief: Aligne la médiane du fond de ciel sur les trois canaux couleur pour retirer la dominante colorée.
keywords: [fond de ciel, dominante colorée, balance des couleurs, sigma-clipping, médiane robuste, calibration couleur]
related: [ColorCalibration, BackgroundExtraction, PhotometricColorCalibration, SCNR]
icon: color-swatch
references:
  - "PixInsight — BackgroundNeutralization tool reference."
  - "astropy.stats — sigma_clipped_stats (médiane robuste par sigma-clipping itératif)."
---

## Résumé

`BackgroundNeutralization` corrige la **dominante colorée du fond de ciel** en réalignant la
médiane robuste de chaque canal couleur (R, V, B) sur la médiane la plus basse des trois. Une
image couleur mal calibrée présente souvent un fond légèrement rougeâtre, verdâtre ou bleuté
(pollution lumineuse, filtres, réponse du capteur) ; ce process rend le fond **neutre en teinte**
avant balance des blancs ou étirement, sans toucher au reste de la dynamique.

## Cas d'usage

- **Retirer une dominante de fond** avant `ColorCalibration` ou `PhotometricColorCalibration`, pour
  que ces étapes partent d'un fond neutre.
- **Corriger un déséquilibre RVB** dû à des temps de pose ou des flats différents par filtre.
- **Préparer une image LRVB ou OSC** avant étirement, quand le fond de ciel affiche une teinte
  visible à l'écran (souvent rouille ou vert-jaune).
- Étape de routine dans un pipeline couleur, juste après `BackgroundExtraction`/soustraction de
  gradient et avant la calibration colorimétrique.

## Fonctionnement

Le process ne s'applique qu'aux images à **3 canaux ou plus** (RVB) ; en mono, il ne fait rien.
Pour chaque canal R, V, B :

1. Calcul d'une **médiane robuste** du canal par sigma-clipping itératif (`astropy.stats.
   sigma_clipped_stats`, seuil `sigma = 3.0`), qui écarte les valeurs aberrantes — étoiles,
   pixels chauds, nébulosité brillante — pour n'estimer que le **niveau de fond**.
2. Le canal dont la médiane est la **plus basse** sert de **référence** (`target`).
3. Chaque canal est **décalé** (offset constant, additif) pour amener sa médiane au niveau de
   `target` : les canaux plus clairs sont assombris d'autant, le canal de référence reste
   inchangé.
4. Le résultat est **écrêté** dans `[0, 1]`.

C'est une correction **par décalage constant**, pas un gain multiplicatif : elle n'affecte pas le
contraste relatif à l'intérieur d'un canal, seulement son niveau de fond absolu.

## Mathématiques

Pour chaque canal $c \in \{R, G, B\}$, soit $\tilde{x}_c$ la médiane robuste obtenue par
sigma-clipping itératif à $3\sigma$ :

$$ \tilde{x}_c = \operatorname{sigma\_clipped\_median}(I_c,\; \sigma = 3) $$

La cible est la médiane la plus basse des trois canaux :

$$ t = \min(\tilde{x}_R,\, \tilde{x}_G,\, \tilde{x}_B) $$

et la correction appliquée à chaque canal est un simple décalage :

$$ I_c'(x,y) = \operatorname{clip}\!\big(I_c(x,y) - (\tilde{x}_c - t),\; 0,\; 1\big) $$

Après transformation, les trois canaux ont (approximativement) la **même médiane de fond** $t$ :
le fond de ciel devient gris neutre, sans altérer les écarts de signal au-dessus de ce niveau.

## Paramètres

Ce process n'a **aucun paramètre exposé** : l'estimateur (sigma-clipping à 3σ) et le choix du
canal de référence (médiane minimale) sont fixes.

## Astuces & pièges

> **Attention** — ce process suppose que le fond de ciel est bien **le fond**, c'est-à-dire que la
> médiane du canal n'est pas polluée par une nébulosité étendue ou un gradient résiduel important.
> Passez `BackgroundExtraction`/`GradientCorrection` **avant** pour aplanir le fond, sinon la
> médiane robuste peut être biaisée par le signal.

- N'agit que sur des images **couleur (≥ 3 canaux)** ; sans effet sur une image mono.
- Ne remplace pas une calibration colorimétrique complète (`ColorCalibration`,
  `PhotometricColorCalibration`) : il neutralise le **fond**, pas la balance des couleurs du
  signal (étoiles, galaxies).
- Étant un simple décalage additif, il ne corrige pas une dominante qui varie spatialement
  (gradient de couleur) — c'est le rôle de `GradientCorrection` en amont.
- Toujours écrêté dans `[0, 1]` : sur une image déjà proche de la saturation, le décalage négatif
  d'un canal peut produire un clipping localisé ; vérifiez l'histogramme après coup.

## Voir aussi

- [ColorCalibration](retina-doc://ColorCalibration) — balance des couleurs par référence de blanc.
- [BackgroundExtraction](retina-doc://BackgroundExtraction) — aplanit le fond avant neutralisation.
- [PhotometricColorCalibration](retina-doc://PhotometricColorCalibration) — calibration couleur par catalogue.
- [SCNR](retina-doc://SCNR) — réduction ciblée d'une dominante verte (bandes étroites).

## Références

- PixInsight — *BackgroundNeutralization* tool reference.
- astropy.stats — *sigma_clipped_stats* (médiane robuste par sigma-clipping itératif).
