---
id: ExtractAlphaChannels
category: ColorSpaces
title: ExtractAlphaChannels
brief: Extrait le canal alpha dans une nouvelle fenêtre grise, ou le retire en place.
keywords: [alpha, transparence, canal, extraction, retrait]
related: [CreateAlphaChannels, ChannelExtraction]
icon: layers-subtract
---

## Résumé

`ExtractAlphaChannels` est l'inverse de `CreateAlphaChannels`, avec le découpage
PixInsight : **extract** produit une nouvelle fenêtre grise portant l'alpha (la source est
intacte), **remove** retire l'alpha de la vue en place — historique et undo ordinaires.

## Cas d'usage

- **Récupérer un masque** rangé en alpha (extraire, puis `app.set_mask`).
- **Aplatir** une image RVBA en RVB avant un process qui attend 3 canaux.

## Fonctionnement

L'alpha est le canal au-delà des canaux nominaux (2e en gris, 4e en couleur). `extract` le
copie dans une image `(H, W, 1)` ouverte en nouvelle fenêtre ; `remove` ne garde que les
canaux nominaux. Une image sans alpha lève une erreur claire.

## Paramètres

- **Mode** — `extract` (nouvelle fenêtre) ou `remove` (transforme la vue).

## Voir aussi

CreateAlphaChannels, ChannelExtraction
