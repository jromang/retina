---
id: ConvertToRGBColor
category: ColorSpaces
title: Conversion en couleur RVB
brief: Convertit une image en niveaux de gris en RVB en répliquant le canal unique sur R, G et B.
keywords: [espace colorimétrique, RVB, niveaux de gris, canaux, conversion, mono vers couleur]
related: [ConvertToGrayscale, ChannelCombination, ChannelExtraction, LRGBCombination]
icon: palette
references:
  - "PixInsight — ConvertToRGBColor tool reference."
---

## Résumé

`ConvertToRGBColor` change l'**espace colorimétrique** d'une image mono-canal (niveaux de
gris) vers un espace RVB à trois canaux, en **répliquant** le canal unique sur les trois
canaux de sortie. Contrairement à `ChannelCombination`, il ne mélange aucune information
colorimétrique nouvelle : le résultat est une image « couleur » achromatique (R = G = B en
tout pixel), visuellement identique à l'original mais dotée de la géométrie de canaux
attendue par les process spécifiquement RVB (`SCNR`, `ColorSaturation`, `LRGBCombination`…).

## Cas d'usage

- Préparer une image en niveaux de gris (luminance, master L, image mono CCD/CMOS) pour lui
  appliquer un process qui exige trois canaux, par exemple avant `LRGBCombination` où la
  chrominance doit déjà être en RVB.
- Assigner ensuite une couleur ou une teinte à une image mono via `PixelMath` ou
  `ColorSaturation`, opérations qui n'ont de sens que sur un espace à plusieurs canaux.
- Uniformiser la géométrie de canaux d'un lot d'images mixtes (mono + couleur) avant un
  traitement par lot ou une intégration commune.
- Créer un point de départ neutre pour une fausse couleur ou une composition narrow-band où
  chaque canal RVB sera ensuite rempli séparément (`ChannelCombination`, `PixelMath`).

## Fonctionnement

Le process inspecte le nombre de canaux de l'image active :

- si l'image compte déjà **3 canaux ou plus**, elle est renvoyée **inchangée** (copie simple,
  aucune opération) — la conversion est un no-op idempotent ;
- sinon (image à **1 canal**), le canal unique est **dupliqué trois fois** pour produire les
  canaux rouge, vert et bleu, produisant une image achromatique dans l'espace RVB.

Aucune interpolation, aucune pondération, aucun changement d'échelle des valeurs : chaque
pixel de sortie porte exactement la valeur du pixel source correspondant, dans les trois
canaux.

## Mathématiques

Soit $I_L(x, y)$ l'image source à un seul canal. La conversion produit l'image RVB
$I_{\text{RGB}}(x, y, c)$ pour $c \in \{R, G, B\}$ par simple duplication :

$$ I_{\text{RGB}}(x, y, c) = I_L(x, y), \qquad \forall\, c \in \{R, G, B\} $$

Cette opération est l'inverse formelle (non exacte) de la conversion en niveaux de gris par
luminance pondérée $L = 0{,}2126\,R + 0{,}7152\,G + 0{,}0722\,B$ utilisée par
`ConvertToGrayscale` : appliquer les deux dans l'ordre (`ConvertToRGBColor` puis
`ConvertToGrayscale`) redonne exactement l'image d'origine, puisque $R = G = B$ annule la
pondération ($0{,}2126 + 0{,}7152 + 0{,}0722 = 1$). L'inverse dans l'autre sens
(`ConvertToGrayscale` puis `ConvertToRGBColor`) est en revanche **destructif** : toute
information de teinte et de saturation présente dans l'image RVB de départ est perdue de
façon irréversible, puisque la luminance ne porte plus qu'un seul scalaire par pixel.

## Paramètres

Ce process n'a **aucun paramètre** : c'est une opération purement structurelle, entièrement
déterminée par le nombre de canaux de l'image d'entrée.

## Astuces & pièges

> **Attention** — le résultat reste **achromatique** ($R = G = B$) tant qu'aucun traitement
> couleur n'est appliqué ensuite. `ConvertToRGBColor` ne colore rien ; il ne fait qu'ouvrir la
> géométrie de canaux nécessaire à des process comme `ColorSaturation`, `SCNR` ou
> `LRGBCombination`.

- Ce process ne modifie **pas** le nombre de canaux d'une image déjà RVB ou davantage
  (LRGB, canaux additionnels) — il est donc sûr à appliquer systématiquement en tête de
  pipeline sans se soucier de l'état d'entrée.
- Comme le process est marqué `is_maskable = False` (il change potentiellement le nombre de
  canaux), il ne peut pas être combiné avec un masque : appliquez d'abord la conversion, puis
  masquez les étapes suivantes si besoin.
- Pour repartir en sens inverse (couleur → niveaux de gris) sans perdre l'information de
  luminance, utilisez `ConvertToGrayscale`, qui pondère les canaux plutôt que de les moyenner
  naïvement.

## Voir aussi

- [ConvertToGrayscale](retina-doc://ConvertToGrayscale) — conversion inverse, RVB vers niveaux de gris pondérés.
- [ChannelCombination](retina-doc://ChannelCombination) — assemble trois vues distinctes en un RVB réel.
- [ChannelExtraction](retina-doc://ChannelExtraction) — extrait un canal RVB en image mono.
- [LRGBCombination](retina-doc://LRGBCombination) — combine une luminance avec une chrominance RVB existante.

## Références

- PixInsight — *ConvertToRGBColor* tool reference.
