---
id: ChannelMatch
category: Geometry
title: ChannelMatch
brief: Translation subpixel par canal et correction linéaire pour réaligner les canaux RVB.
keywords: [canal, alignement, recalage, aberration chromatique, frange]
related: [StarAlignment, ChannelCombination, ChannelExtraction]
icon: arrows-move
---

## Résumé

`ChannelMatch` décale chaque canal d'une image couleur indépendamment, avec une précision
subpixel, et applique un facteur de correction linéaire optionnel par canal. C'est l'outil
des **franges colorées** : aberration chromatique latérale, ou légère dérive entre filtres
d'une session mono+filtres combinée en RVB.

![Avant — ChannelMatch](figures/before.webp)
![Après — ChannelMatch](figures/after.webp)

*Des liserés colorés, et le même champ une fois les canaux remis en coïncidence. Le décalage est injecté — la source est bâtie bande par bande sur une grille unique et ne porte aucune aberration chromatique propre.*

## Cas d'usage

- **Éliminer les franges** rouges/bleues autour des étoiles après `ChannelCombination`.
- **Parfaire** un jeu RVB recalé globalement mais pas canal par canal.
- **Équilibrer les canaux** linéairement (facteurs) sans toucher aux histogrammes.

## Fonctionnement

Chaque canal est translaté de (`dx[c]`, `dy[c]`) pixels par interpolation spline
(`scipy.ndimage.shift`, ordre `order`), puis multiplié par `factors[c]`. Les bords
découverts restent à zéro, comme après un recalage. Le résultat est borné à $[0,1]$.
Sur une image mono-canal, le process est un no-op documenté.

## Paramètres

- **Décalages X (px)** / **Décalages Y (px)** — décalages subpixel par canal, `[R, V, B]`.
- **Facteurs de correction linéaire** — multiplicateur par canal, défaut `1.0`.
- **Ordre d'interpolation** — ordre de la spline (3 = cubique ; 1 = bilinéaire, plus rapide).

## Astuces & pièges

- Travailler sur des données **linéaires** ; mesurer le décalage sur une étoile brillante
  avec la sonde de readout.
- Préférer des paires de décalages qui se compensent pour préserver le centre géométrique.

## Voir aussi

StarAlignment, ChannelCombination, ChannelExtraction
