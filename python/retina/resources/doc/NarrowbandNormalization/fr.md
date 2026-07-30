---
id: NarrowbandNormalization
category: ColorCalibration
title: Normalisation bande étroite
brief: Met les canaux d'une composition SHO au même fond, sans effacer ce qui les distingue.
keywords: [SHO, HOO, bande étroite, normalisation, fond de ciel, palette, Hubble]
related: [NBRGBCombination, LinearFit, ChannelCombination, BackgroundNeutralization]
icon: adjustments
references:
  - "PixInsight — script NarrowbandNormalization."
---

## Résumé

Trois filtres étroits acquis séparément n'ont ni le même fond de ciel, ni le même gain apparent.
La palette qui en sort est alors dominée par ces écarts — un canal domine la couleur parce qu'il
a un fond plus haut, non parce qu'il porte plus de signal.

`NarrowbandNormalization` aligne chaque canal sur un canal de référence, **sur les pixels de
fond seulement**.

## Pourquoi le fond, et lui seul

Un ajustement sur toute l'image serait tiré par les régions d'émission — qui sont précisément ce
qu'on veut voir **différer** d'un canal à l'autre. Aligner Hα sur OIII partout reviendrait à
effacer ce qu'on cherche à montrer.

Les pixels de fond sont désignés par le **support multirésolution**, celui-là même qui sert à
mesurer le bruit ([NoiseEvaluation](retina-doc://NoiseEvaluation)) : est du fond ce qui n'est
significatif à aucune des échelles fines, **dans tous les canaux à la fois**. Tous, et non chacun
le sien : un ajustement se fait sur des pixels communs, sinon on compare deux populations
différentes et la droite obtenue ne veut rien dire.

## Le cas dégénéré, qui arrive

Si le fond est **parfaitement plat** — image de synthèse, ou fortement débruitée — la droite
n'est pas définie : sa pente ne dépendrait plus que du bruit numérique. On retombe alors sur le
**décalage**, qui l'est toujours. Ne rien faire serait pire : le process paraîtrait tourner sans
agir, ce qui est le plus difficile à diagnostiquer.

## Deux entrées possibles

- **Jeu mono** : trois vues nommées (`red_view`, `green_view`, `blue_view`), une par filtre. Les
  trois, ou aucune — le process refuse un mélange.
- **Image couleur déjà composée** : sans vue nommée, ce sont les trois canaux de l'image qui
  sont normalisés entre eux.

## Paramètres

- **`reference`** — *enum* `red` | `green` | `blue`, défaut `green`. Le canal auquel les autres
  s'alignent ; il n'est pas modifié.
- **`red_view`**, **`green_view`**, **`blue_view`** — *str*. Les trois vues, ou aucune.
- **`k_sigma`** — *real*, défaut `3.0`. Seuil de significativité qui définit le fond.
- **`match_scale`** — *bool*, défaut `True`. Aligner l'échelle en plus du décalage. À `False`,
  seuls les fonds sont alignés : le contraste de chaque canal reste intact, ce qui est parfois
  préférable — le gain relatif des filtres est alors une information qu'on ne veut pas effacer.

## Astuces & pièges

> **Normalisez avant de composer, pas après.** Une fois les trois canaux empilés en une image
> couleur, un ajustement par canal se heurte au fait que la couleur est déjà faite.

- Le canal de référence est **inchangé** : choisissez celui dont vous êtes satisfait, souvent
  celui qui porte le plus de signal.
- Si un canal est nettement plus bruité que les autres, `match_scale=True` amplifiera son bruit
  en même temps que son signal. Débruitez-le d'abord.

## Voir aussi

- [NBRGBCombination](retina-doc://NBRGBCombination) — injecter une raie dans une image RVB.
- [ChannelCombination](retina-doc://ChannelCombination) — composer l'image couleur.
- [BackgroundNeutralization](retina-doc://BackgroundNeutralization) — neutraliser la teinte du
  fond, geste complémentaire.
- [NoiseEvaluation](retina-doc://NoiseEvaluation) — le même support multirésolution, au service
  de la mesure du bruit.

## Références

- PixInsight — script *NarrowbandNormalization*.
