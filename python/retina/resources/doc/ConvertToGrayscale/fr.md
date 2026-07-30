---
id: ConvertToGrayscale
category: ColorSpaces
title: Conversion en niveaux de gris
brief: Convertit une image RGB en niveaux de gris via une luminance pondérée Rec. 709.
keywords: [niveaux de gris, luminance, monochrome, espace colorimétrique, Rec. 709, désaturation]
related: [ConvertToRGBColor, ChannelExtraction, ColorSaturation, ComponentSeparation]
icon: contrast
references:
  - "PixInsight — ConvertToGrayscale tool reference."
  - "ITU-R BT.709-6 — luma coefficients for HD/sRGB primaries."
---

## Résumé

`ConvertToGrayscale` transforme une image RGB en une image **monochrome à un seul canal**, en
combinant les trois canaux couleur par une **somme pondérée** (luminance perçue) plutôt qu'une
simple moyenne. C'est l'équivalent de l'outil du même nom dans PixInsight : une conversion
d'espace colorimétrique qui change la **géométrie** de l'image (nombre de canaux), pas seulement
son apparence.

## Cas d'usage

- Préparer une **image de luminance** en amont d'une combinaison LRGB (`LRGBCombination`), à
  partir d'une image couleur déjà traitée.
- Produire un canal unique pour des traitements qui n'ont de sens qu'en monochrome : détection
  d'étoiles, mesures de PSF, masques structurels, ou export destiné à un instrument mono.
- Simplifier une image couleur bruitée pour évaluer le signal réel sans les artefacts de
  bruit de chrominance.
- Étape préliminaire avant `ComponentSeparation` quand seule la composante de luminance importe.

## Fonctionnement

Le process regarde le nombre de canaux de l'image active :

- Si l'image est **déjà monochrome** (1 canal), elle est simplement recopiée sans modification.
- Sinon, chaque pixel RGB est réduit à une seule valeur par **combinaison linéaire pondérée**
  des trois canaux, puis ce résultat est stocké comme unique canal de sortie (le tableau passe
  de forme `(H, W, 3)` à `(H, W, 1)`).

Les poids utilisés sont ceux de la **luminance relative Rec. 709** (mêmes coefficients que la
conversion sRGB → luminance), qui reflètent la sensibilité différente de l'œil humain au rouge,
au vert et au bleu — le canal vert domine très largement la perception de luminosité.

Cette conversion est **irréversible** : les trois canaux d'origine sont perdus, seule
l'information de luminance combinée subsiste dans le canal résultant.

## Mathématiques

Soit un pixel RGB $(r, g, b) \in [0,1]^3$. La valeur de luminance $y$ est calculée par la
combinaison linéaire :

$$ y = w_r\,r + w_g\,g + w_b\,b $$

avec les coefficients Rec. 709 utilisés par l'implémentation :

$$ w_r = 0{,}2126, \qquad w_g = 0{,}7152, \qquad w_b = 0{,}0722, \qquad w_r + w_g + w_b = 1. $$

La somme des poids valant $1$, un pixel gris neutre ($r=g=b$) reste inchangé en valeur après
conversion. La dominance de $w_g$ traduit le fait que l'œil est bien plus sensible aux
variations du canal vert qu'à celles du rouge ou (surtout) du bleu : deux images de couleurs
différentes mais de même luminance perçue produiront un résultat monochrome très proche.

L'image de sortie a la forme $(H, W, 1)$, chaque plan $(h, w)$ contenant $y(h, w)$ calculé
canal par canal sur toute l'image.

## Paramètres

Ce process n'a aucun paramètre réglable : la pondération des canaux est fixée en dur dans le
code (coefficients Rec. 709) et ne peut pas être ajustée depuis l'interface ni le script.

## Astuces & pièges

> **Attention** — la conversion est destructive et non réversible : une fois les canaux fusionnés,
> il est impossible de reconstruire les proportions RGB d'origine. Travaillez sur une copie de la
> vue ou une preview si vous devez conserver la couleur.

> **Note** — si vous souhaitez un poids différent par canal (par exemple pour imiter une réponse
> spectrale d'instrument particulière), utilisez plutôt `PixelMath` ou `ChannelExtraction` combinée
> à une somme pondérée manuelle : `ConvertToGrayscale` n'expose pas les coefficients.

- Appliqué à une image déjà monochrome, le process est un simple no-op (copie), ce qui le rend
  sûr à chaîner dans un pipeline sans vérification préalable du nombre de canaux.
- Pour repasser en RGB (trois canaux identiques, sans recoloriser), utilisez
  `ConvertToRGBColor`.

## Voir aussi

- [ConvertToRGBColor](retina-doc://ConvertToRGBColor) — conversion inverse (réplication en 3 canaux).
- [ChannelExtraction](retina-doc://ChannelExtraction) — extraire un canal isolé plutôt qu'une luminance combinée.
- [ColorSaturation](retina-doc://ColorSaturation) — ajuster la saturation sans perdre la couleur.
- [ComponentSeparation](retina-doc://ComponentSeparation) — séparer les composantes couleur (PCA/ICA) plutôt que les fusionner.

## Références

- PixInsight — *ConvertToGrayscale* tool reference.
- ITU-R BT.709-6 — coefficients de luma pour les primaires HD/sRGB.
