---
id: HistogramMatching
category: ColorCalibration
title: Appariement d'histogramme
brief: Aligne la distribution d'intensité d'une vue sur celle d'une vue de référence (skimage).
keywords: [histogramme, appariement, mosaïque, intégration, fond de ciel, normalisation]
related: [LinearFit, StarAlignment, Integration, MosaicReproject]
icon: chart-histogram
references:
  - "scikit-image — skimage.exposure.match_histograms."
  - "Gonzalez & Woods — Digital Image Processing, histogram specification."
---

## Résumé

`HistogramMatching` reprogramme la distribution d'intensité d'une vue pour qu'elle épouse
celle d'une **vue de référence**, canal par canal, en s'appuyant sur `match_histograms` de
scikit-image. Contrairement à `HistogramTransformation`, qui applique une courbe de tons
paramétrique (MTF), cette opération recopie **l'histogramme cumulé** d'une autre image :
c'est l'outil à utiliser pour uniformiser le fond et la couleur entre plusieurs trames avant
de les fusionner (mosaïque, intégration, panorama).

## Cas d'usage

- **Uniformiser plusieurs poses** d'une même cible prises à des dates ou conditions de ciel
  différentes (transparence, pollution lumineuse) avant intégration.
- **Raccorder les tuiles d'une mosaïque** pour que les panneaux voisins présentent le même
  fond de ciel et le même équilibre des couleurs avant fusion (`MosaicReproject`,
  `GradientMergeMosaic`).
- **Reproduire l'ambiance tonale** d'une image de référence (rendu déjà validé) sur une
  nouvelle trame du même objet.
- **Recaler la dynamique** d'une image faiblement exposée sur celle d'une pose de référence
  bien exposée, avant combinaison.

## Fonctionnement

Le process prend un seul paramètre : l'identifiant de la **vue de référence** (`reference`).
Sans référence valide (chaîne vide ou vue introuvable), l'image est renvoyée **inchangée**
(copie simple).

Quand une référence est résolue :

1. Si le nombre de canaux de la référence correspond à celui de l'image source, l'appariement
   est effectué en une passe sur tous les canaux à la fois (`channel_axis=-1`), ce qui
   préserve les corrélations entre canaux couleur.
2. Sinon (par exemple référence monochrome pour une source RGB), l'appariement est fait
   **canal par canal** : chaque canal de la source est apparié au canal correspondant de la
   référence, en réutilisant le dernier canal disponible de la référence si celle-ci en a
   moins que la source (`min(c, ref_channels - 1)`).
3. Le résultat est **écrêté** à `[0, 1]` et reconverti en `float32`.

L'algorithme sous-jacent (`skimage.exposure.match_histograms`) calcule, pour chaque canal,
l'histogramme cumulé normalisé de la source et de la référence, puis construit une fonction
de correspondance qui envoie chaque valeur source vers la valeur de référence ayant le même
rang cumulé.

## Mathématiques

Pour un canal donné, soit $F_s$ la **fonction de répartition cumulée** (CDF) empirique des
valeurs de pixels de la source, et $F_r$ celle de la référence :

$$ F_s(x) = \frac{\#\{\, i : x_i \le x \,\}}{N_s}, \qquad
   F_r(y) = \frac{\#\{\, j : y_j \le y \,\}}{N_r}. $$

L'appariement d'histogramme cherche, pour chaque valeur source $x$, la valeur de sortie $y$
qui partage le même **rang cumulé** :

$$ y = F_r^{-1}\!\big(F_s(x)\big). $$

En pratique, $F_s$ et $F_r$ sont des fonctions en escalier construites sur les valeurs
distinctes observées ; $F_r^{-1}$ est obtenue par interpolation entre les valeurs de la
référence dont la CDF encadre $F_s(x)$. Le résultat a, par construction, un histogramme dont
la forme cumulée est identique à celle de la référence (aux effets de quantification près),
ce qui égalise à la fois le **niveau moyen** (fond de ciel) et le **contraste** (étalement des
tons) entre les deux images.

## Paramètres

- **`reference`** — *str*, défaut `""`. Identifiant de la vue de référence dont l'histogramme
  cumulé sert de cible. Chaîne vide ou identifiant non résolu → l'image est renvoyée sans
  modification.

## Astuces & pièges

> **Attention** — la référence doit avoir un **cadrage/contenu comparable** (même champ, même
> proportion de fond de ciel et de signal). Apparier sur une image très différente en contenu
> (ex. champ dense en étoiles vs champ nébuleux) peut introduire des artefacts de postérisation.

> **Note** — sans référence résolvable, le process est un **no-op silencieux** : vérifiez que
> `reference` désigne bien une vue ouverte et non vide.

- Pour un simple recalage de niveau (gain/offset) sans redistribution de la forme de
  l'histogramme, préférez `LinearFit`, plus doux et moins sujet aux artefacts sur du bruit
  de fond faible.
- Effectuez l'appariement **avant** l'intégration ou l'assemblage de mosaïque, pas après :
  il sert à préparer des trames cohérentes, pas à corriger un résultat déjà combiné.
- Sur des images à fort bruit de fond, l'appariement peut amplifier localement le bruit si les
  histogrammes source et référence diffèrent beaucoup en forme ; contrôlez le résultat sous
  masque si nécessaire.

## Voir aussi

- [LinearFit](retina-doc://LinearFit) — recalage linéaire (moindres carrés) plus doux.
- [StarAlignment](retina-doc://StarAlignment) — recalage géométrique préalable à la fusion.
- [Integration](retina-doc://Integration) — empilement des trames une fois uniformisées.
- [MosaicReproject](retina-doc://MosaicReproject) — reprojection WCS pour assembler une mosaïque.

## Références

- scikit-image — *skimage.exposure.match_histograms*.
- Gonzalez & Woods — *Digital Image Processing*, histogram specification.
