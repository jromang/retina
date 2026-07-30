---
id: AberrationInspector
category: ImageInspection
title: Inspecteur d'aberrations
brief: Assemble les coins, les bords et le centre de l'image en une mosaïque, pour les comparer d'un coup d'œil.
keywords: [aberrations, coma, tilt, courbure de champ, coins, mosaïque, qualité optique]
related: [FWHMEccentricity, DynamicPSF, RadialProfileMeasurement]
icon: grid-4x4
references:
  - "PixInsight — script AberrationInspector."
---

## Résumé

`AberrationInspector` découpe `mosaic_size` × `mosaic_size` vignettes réparties sur toute
l'image — les quatre coins, les bords, le centre — et les assemble côte à côte dans une
**nouvelle fenêtre**.

Le geste est bête, et c'est sa force. Comparer les quatre coins d'une image de cinquante
mégapixels demande sinon quatre allers-retours de zoom, pendant lesquels l'œil oublie ce qu'il
vient de voir. Mis côte à côte, la coma, le tilt et la courbure de champ deviennent
immédiatement lisibles.

## Cas d'usage

- **Contrôler un correcteur de coma** ou un réducteur de focale : les coins doivent se
  ressembler.
- **Régler un tilt** de porte-oculaire, en itérant : une mosaïque avant, une après.
- **Choisir un recadrage** : si deux coins sont irrécupérables, autant le voir avant de traiter.

## Fonctionnement

Les origines des vignettes vont de zéro au bord opposé, de sorte que les coins de la mosaïque
sont bien les coins de l'image, et son centre le centre. Les vignettes sont séparées de
`separation` pixels noirs, qui évitent de prendre la jointure pour une structure.

Une vignette plus grande que ne le permet l'image est **recadrée**, jamais agrandie : agrandir
des pixels donnerait l'illusion d'un défaut optique.

## Paramètres

- **`mosaic_size`** — *int*, défaut `3`, plage `2`–`9`. Nombre de vignettes par côté. Trois
  suffit dans presque tous les cas : coins, milieux de bords, centre.
- **`panel_size`** — *int*, défaut `256`, plage `32`–`2048`. Côté d'une vignette, en pixels de
  l'image d'origine.
- **`separation`** — *int*, défaut `4`, plage `0`–`64`. Épaisseur du trait noir entre vignettes.

Produit une **nouvelle fenêtre** ; l'image d'origine n'est pas touchée.

## Astuces & pièges

> **Regardez-la à 100 %.** Une mosaïque réduite à l'écran ne montre rien : c'est la forme des
> étoiles qu'on inspecte, à l'échelle du pixel.

- Sur données **linéaires**, appliquez une STF avant de regarder — sinon la mosaïque paraîtra
  noire, comme l'image dont elle vient.
- `AberrationInspector` montre, il ne mesure pas. Pour un chiffre, voyez
  [FWHMEccentricity](retina-doc://FWHMEccentricity).

## Voir aussi

- [FWHMEccentricity](retina-doc://FWHMEccentricity) — la même question, en chiffres et en carte.
- [DynamicPSF](retina-doc://DynamicPSF) — la forme d'une étoile en particulier.
- [RadialProfileMeasurement](retina-doc://RadialProfileMeasurement) — profil radial et courbe
  de croissance.

## Références

- PixInsight — script *AberrationInspector*.
