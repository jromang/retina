---
id: Rescale
category: IntensityTransformations
title: Redimensionnement d'intensité
brief: Renormalise linéairement les valeurs de pixels de leur plage min/max réelle vers une plage cible.
keywords: [normalisation, dynamique, linéaire, min-max, renormalisation, plage de sortie]
related: [HistogramTransformation, CurvesTransformation, Binarize, Statistics]
icon: arrows-maximize
references:
  - "PixInsight — Rescale tool reference."
---

## Résumé

`Rescale` applique une **renormalisation linéaire** de l'image : elle mesure le minimum et le
maximum réels des échantillons, puis étire (ou compresse) cette plage vers un intervalle de
sortie choisi par l'utilisateur (`low`–`high`, par défaut `[0, 1]`). Contrairement à
`HistogramTransformation`, il n'y a **ni écrêtage, ni courbe de midtones** : c'est une simple
transformation affine, entièrement déterminée par les extrema présents dans les données.

## Cas d'usage

- **Ramener une image dans la plage affichable** après une opération qui a produit des valeurs
  hors `[0, 1]` (convolution avec noyau à poids négatifs, composition HDR en domaine de
  gradient, PixelMath, FFT inverse…).
- **Uniformiser la dynamique** de plusieurs images avant une combinaison (moyenne, LRGB) quand
  leurs plages de valeurs diffèrent.
- **Préparer l'export** vers un format entier (8/16 bits) qui exige des échantillons dans
  `[0, 1]`.
- **Réserver de la marge** en visant une plage de sortie resserrée (p. ex. `[0.05, 0.95]`) pour
  éviter tout écrêtage lors d'opérations additives ultérieures.

## Fonctionnement

1. Le minimum et le maximum sont calculés **sur l'ensemble du tableau** `(H, W, C)`, c'est-à-dire
   **conjointement sur tous les canaux** — pas canal par canal. Cela préserve l'équilibre des
   couleurs d'une image RGB : les trois canaux subissent exactement la même transformation
   affine.
2. Chaque échantillon est remappé linéairement de `[min, max]` vers `[0, 1]`, puis reprojeté vers
   `[low, high]`.
3. Cas dégénéré : si l'image est parfaitement constante (`max == min`), la division par zéro est
   évitée et le résultat est une image uniforme à la valeur `low` (typiquement 0).
4. Le résultat est retourné en `float32`.

## Mathématiques

Soit $x$ un échantillon, $x_{\min}$ et $x_{\max}$ les extrema **globaux** du tableau (tous
canaux confondus), et $\ell$ = `low`, $u$ = `high` les bornes de sortie. On calcule d'abord la
position relative :

$$ y = \frac{x - x_{\min}}{x_{\max} - x_{\min}} \qquad (x_{\max} > x_{\min}) $$

puis la reprojection vers la plage cible :

$$ x' = y \,(u - \ell) + \ell = \ell + (x - x_{\min})\,\frac{u - \ell}{x_{\max} - x_{\min}} $$

C'est une transformation **affine unique** (mêmes coefficients pour tous les pixels et tous les
canaux) : $x_{\min} \mapsto \ell$ et $x_{\max} \mapsto u$, sans courbure ni écrêtage
intermédiaire. Si $x_{\max} = x_{\min}$ (image plate), le quotient n'est pas défini et
l'implémentation retourne $x' = 0$ partout plutôt que de diviser par zéro.

## Paramètres

- **`low`** — *real*, défaut `0.0`, plage `0`–`1`. Borne basse de la plage de sortie : la valeur
  minimale de l'image d'entrée est mappée sur `low`.
- **`high`** — *real*, défaut `1.0`, plage `0`–`1`. Borne haute de la plage de sortie : la valeur
  maximale de l'image d'entrée est mappée sur `high`.

## Astuces & pièges

> **Attention** — les bornes proviennent des extrema **réels** des données : un unique pixel
> chaud ou un artefact isolé domine le mapping et écrase le reste de la dynamique vers le noir.
> Passez `CosmeticCorrection` ou `CosmicClip` avant `Rescale` si l'image contient des pixels
> défectueux.

> **Attention** — sur une image parfaitement constante (test synthétique, masque uniforme),
> `Rescale` renvoie une image entièrement à `low`, effaçant silencieusement tout contenu au lieu
> de lever une erreur.

- Le calcul est **conjoint sur tous les canaux** : il ne corrige pas un déséquilibre de couleur
  existant, il le préserve. Pour normaliser des canaux indépendamment, passez par
  `ChannelExtraction` + `Rescale` + `ChannelCombination`.
- Inverser `low` et `high` (`low > high`) produit un mapping inversé (négatif) en plus de la
  renormalisation — un effet de bord parfois utile, parfois accidentel.
- Sans midtones ni écrêtage, `Rescale` est purement linéaire : pour un étirement perceptuel
  (gamma), utilisez `HistogramTransformation` ou `CurvesTransformation` après ou à la place.

## Voir aussi

- [HistogramTransformation](retina-doc://HistogramTransformation) — étirement non linéaire avec
  point noir/blanc et midtones.
- [CurvesTransformation](retina-doc://CurvesTransformation) — contrôle tonal par courbe libre.
- [Binarize](retina-doc://Binarize) — seuillage en tout-ou-rien après normalisation.
- [Statistics](retina-doc://Statistics) — inspecter min/max/médiane avant de choisir les bornes.

## Références

- PixInsight — *Rescale* tool reference.
