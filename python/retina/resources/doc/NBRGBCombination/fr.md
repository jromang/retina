---
id: NBRGBCombination
category: ColorCalibration
title: Combinaison bande étroite / RVB
brief: Injecte Hα, OIII ou SII dans une image RVB large bande, à l'échelle mesurée sur les étoiles.
keywords: [Hα, OIII, SII, bande étroite, RVB, combinaison, SHO, HOO, échelle]
related: [NarrowbandNormalization, ChannelCombination, LinearFit, LRGBCombination]
icon: color-swatch
references:
  - "PixInsight — script NBRGBCombination."
---

## Résumé

Une image à bande étroite montre une raie d'émission avec un contraste que la bande large ne
peut pas avoir : la raie y est noyée dans le continuum. `NBRGBCombination` en injecte le signal
dans le canal RVB de votre choix, sans écraser ce qui s'y trouvait.

La démarche a trois temps :

1. **Mettre la bande étroite à l'échelle** du canal visé. Les deux images n'ont aucune raison
   d'être dans les mêmes unités — filtres, temps de pose et ciel diffèrent.
2. **Prendre l'excès** : ce qui, après mise à l'échelle, dépasse le canal. C'est le signal de
   raie que la bande large ne voit pas.
3. **En ajouter une part**, réglée par `strength`.

Prendre l'excès plutôt que l'image entière est ce qui **préserve les étoiles** : une étoile est
brillante dans les deux, elle ne dépasse donc pas, et n'est pas ajoutée une seconde fois.

## L'échelle vient des étoiles, et c'est moins évident qu'il n'y paraît

Deux approches plausibles échouent, et il a fallu les voir échouer.

**Une régression pixel à pixel** entre les deux images ne marche pas : les pixels d'émission ont
les plus grandes abscisses, donc le plus de bras de levier, et ils tirent la droite à eux. Sur un
champ synthétique dont la vraie échelle valait 0,5, une régression naïve rend **0,042** — le
process n'injecte alors plus rien.

**L'écrêtage itératif des aberrants** empire les choses. Sous une pente déjà effondrée, ce sont
les étoiles *saines* qui ont les plus grands résidus : le clipping les rejette et garde
l'émission.

Ce qui marche est de raisonner **par étoile** : on somme le flux de chacune dans les deux
images, et l'on prend la **médiane** des rapports. Une étoile posée sur la nébuleuse donne un
rapport aberrant, mais elle n'est qu'un point parmi les autres — la médiane l'ignore, là où les
moindres carrés lui obéissaient. Sur le même champ, l'échelle mesurée est **0,494** pour 0,5.

C'est aussi, tout simplement, la façon dont on met deux images à la même échelle en astronomie.

Le **décalage**, lui, est calé sur le **fond de ciel** : caler l'échelle et le pedestal sur les
mêmes points soulèverait le ciel de toute l'image. Chacun là où il est mesurable.

## Paramètres

- **`ha_view`**, **`oiii_view`**, **`sii_view`** — *str*. Identifiants des vues à injecter. Au
  moins une est requise ; les trois peuvent servir ensemble.
- **`ha_channel`**, **`oiii_channel`**, **`sii_channel`** — *enum* `red` | `green` | `blue`.
  Défauts `red`, `green`, `red` — la palette HOO/SHO usuelle.
- **`mode`** — *enum* `manual` | `bandwidth`, défaut `manual`.
  - `manual` : `strength` seule. C'est le réglage qu'on veut en pratique, « combien de Hα »
    étant un jugement esthétique et non une grandeur physique.
  - `bandwidth` : `strength` multipliée par le rapport des largeurs de bande. Physiquement
    fondé, mais **discret** — un rapport 7/100 donne 7 % de l'excès. À savoir avant de
    s'étonner.
- **`strength`** — *real*, défaut `0.5`, plage `0`–`1`.
- **`nb_bandwidth`** / **`rgb_bandwidth`** — *real*, défauts `7.0` / `100.0` nm. Utilisés en
  mode `bandwidth` seulement.

## Astuces & pièges

> **Les images doivent être recalées.** Le process vérifie la géométrie et refuse plutôt que
> de recadrer en silence, mais il ne peut pas voir un décalage d'un pixel — qui laisserait des
> liserés colorés au bord des étoiles.

- Injectez **avant** l'étirement, sur données linéaires : c'est là que la relation d'échelle
  entre les deux images est une simple proportion.
- Si votre champ n'a pas assez d'étoiles (moins de cinq mesurables), l'échelle ne peut pas être
  déterminée et la bande étroite est prise telle quelle : le résultat sera dominé par la
  différence de gain. Élargissez le champ ou mettez les images à l'échelle vous-même.
- Pour une palette SHO complète, faites d'abord passer les trois canaux par
  [NarrowbandNormalization](retina-doc://NarrowbandNormalization).

## Voir aussi

- [NarrowbandNormalization](retina-doc://NarrowbandNormalization) — mettre trois canaux SHO au
  même fond avant de composer.
- [ChannelCombination](retina-doc://ChannelCombination) — composer une image couleur à partir de
  trois vues, sans notion d'excès.
- [LinearFit](retina-doc://LinearFit) — l'ajustement linéaire nu, si vous préférez le piloter.

## Références

- PixInsight — script *NBRGBCombination*.
