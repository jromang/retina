---
id: CreateAlphaChannels
category: ColorSpaces
title: CreateAlphaChannels
brief: Ajoute (ou remplace) le canal alpha depuis une constante, la luminance ou une autre vue.
keywords: [alpha, transparence, canal, RVBA, PNG]
related: [ExtractAlphaChannels, ChannelCombination, ChannelExtraction]
icon: stack-2
---

## Résumé

`CreateAlphaChannels` ajoute un **canal alpha** à l'image — une image grise devient
gris+alpha (2 canaux), une image couleur devient RVBA (4 canaux), la convention PixInsight
que porte le modèle `(H, W, C)`. L'alpha peut être une constante, la luminance de l'image,
ou le premier canal d'une autre vue ouverte.

## Cas d'usage

- **Exporter un PNG avec transparence** (`app.save`) — le débouché naturel de ce process.
- **Emporter un masque avec l'image** : ranger un masque d'étoiles en alpha avant export.
- Préparer des compositions pour des logiciels externes qui honorent le RVBA.

## Fonctionnement

L'alpha est borné à $[0,1]$ et empilé après les canaux nominaux. `constant` remplit avec
**Valeur constante** ; `luminance` applique les poids Rec. 709 sur une image couleur (ou
reprend l'unique canal en gris) ; `view` échantillonne le premier canal de **Vue source**,
qui doit avoir la même géométrie.

## Paramètres

- **Source de l'alpha** — `constant`, `luminance` ou `view`.
- **Valeur constante** — l'alpha uniforme, défaut `1.0` (opaque).
- **Vue source** — identifiant de vue quand la source est `view`.

## Astuces & pièges

- Le viewport web ne compose pas encore l'alpha : le réglage `app.set_transparency_mode`
  existe côté domaine, le shader n'affiche que les canaux nominaux.
- JPEG n'a pas d'alpha : l'export aplatit sur les canaux nominaux.

## Voir aussi

ExtractAlphaChannels, ChannelCombination
