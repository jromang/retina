---
id: HistogramTransformation
category: IntensityTransformations
title: Transformation d'histogramme
brief: Étire et repositionne les tons via une fonction de transfert midtones/shadows/highlights (MTF).
keywords: [histogramme, étirement, MTF, midtones, point noir, gamma]
related: [CurvesTransformation, AutoHistogram, MaskedStretch, ArcsinhStretch]
icon: chart-histogram
references:
  - "PixInsight — HistogramTransformation tool reference."
  - "Conejero, J. — Midtones Transfer Function (MTF)."
---

## Résumé

`HistogramTransformation` applique aux pixels une **fonction de transfert de tons** définie
par trois curseurs : le **point noir** (shadows), le **milieu** (midtones, qui contrôle le
gamma perçu) et le **point blanc** (highlights). C'est l'outil d'étirement fondamental :
il transforme une image linéaire (sombre, concentrée près de zéro) en une image affichable,
ou ajuste finement le contraste et la luminosité d'une image déjà étirée.

Contrairement à la STF (ScreenTransferFunction), qui n'agit que sur **l'affichage**, cette
transformation est **destructive** : elle réécrit les valeurs de pixels dans l'historique.

## Cas d'usage

- **« Cuire » un auto-stretch** : reporter dans les pixels l'étirement non destructif calculé
  par la STF (voir `HistogramTransformation.from_stf_channel`), une fois la composition validée.
- **Ajuster le point noir** pour ancrer le fond de ciel sans écrêter les étoiles.
- **Rehausser les tons moyens** (nébulosités faibles) en abaissant le curseur des midtones.
- **Récupérer des hautes lumières** en descendant le point blanc si le cœur des étoiles sature.

## Fonctionnement

L'opérateur procède en deux temps, canal par canal :

1. **Remappage linéaire** de la plage `[shadows, highlights]` vers `[0, 1]`, avec écrêtage :
   tout ce qui est sous le point noir devient 0, tout ce qui dépasse le point blanc devient 1.
2. **Application de la MTF** (Midtones Transfer Function) paramétrée par `midtones`, qui courbe
   la réponse pour éclaircir (midtones < 0,5) ou assombrir (midtones > 0,5) les tons moyens.

## Mathématiques

Soit $x$ la valeur d'un pixel dans $[0,1]$, $s$ = `shadows`, $h$ = `highlights`,
$m$ = `midtones`. On calcule d'abord la valeur remappée :

$$ x_n = \operatorname{clip}\!\left(\frac{x - s}{\,h - s\,},\; 0,\; 1\right) $$

puis on lui applique la **fonction de transfert des midtones** :

$$ \operatorname{mtf}(m, x_n) = \frac{(m - 1)\,x_n}{(2m - 1)\,x_n - m} $$

Cette fonction envoie $0 \mapsto 0$ et $1 \mapsto 1$, et fait passer l'entrée $m$ sur la sortie
$0{,}5$ : le curseur des midtones fixe donc directement la valeur qui deviendra le gris moyen.
Les cas limites sont continus : $m \to 0$ éclaircit à l'extrême ($\operatorname{mtf}\to 1$),
$m \to 1$ assombrit à l'extrême ($\operatorname{mtf}\to 0$), et $m = 0{,}5$ redonne l'identité.

## Paramètres

- **`shadows`** — *real*, défaut `0.0`, plage `0`–`1`. Point noir : valeur d'entrée mappée sur 0.
  Tout pixel inférieur est écrêté à noir.
- **`midtones`** — *real*, défaut `0.5`, plage `0`–`1`. Équilibre des tons moyens (gamma). En
  dessous de 0,5 l'image s'éclaircit, au-dessus elle s'assombrit.
- **`highlights`** — *real*, défaut `1.0`, plage `0`–`1`. Point blanc : valeur d'entrée mappée sur 1.
  Tout pixel supérieur est écrêté à blanc.
- **`channels`** — *floatlist*, défaut vide. Triplets par canal
  `(shadows, midtones, highlights, …)`, à plat. Vide signifie « les trois valeurs ci-dessus,
  sur chaque canal », ce que ce process a toujours fait. Il existe parce qu'un auto-stretch se
  calcule **par canal** — `STF.auto_from_image` lit la médiane de chacun —, si bien que le
  graver avec un seul triplet décalerait l'équilibre des couleurs de l'affichage même qu'il
  reproduit. Un canal au-delà de la liste garde le dernier triplet.

## Astuces & pièges

> **Attention** — un point noir trop haut supprime définitivement le halo des nébulosités
> faibles. Vérifiez l'histogramme après coup et travaillez sous masque si nécessaire.

- Pour un étirement doux préservant le fond, préférez de petits pas répétés plutôt qu'un
  écrasement en une fois.
- Sur données linéaires, `AutoHistogram` ou un auto-stretch STF donnent un bon point de départ
  à affiner ici.

## Voir aussi

- [CurvesTransformation](retina-doc://CurvesTransformation) — contrôle tonal par courbe libre.
- [MaskedStretch](retina-doc://MaskedStretch) — étirement itératif préservant les étoiles.
- [ArcsinhStretch](retina-doc://ArcsinhStretch) — étirement préservant la couleur.

## Références

- PixInsight — *HistogramTransformation* tool reference.
- Conejero, J. — *Midtones Transfer Function (MTF)*.
