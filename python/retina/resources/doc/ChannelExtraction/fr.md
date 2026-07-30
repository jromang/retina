---
id: ChannelExtraction
category: ColorSpaces
title: Extraction de canal
brief: Extrait un canal R, G, B ou une luminance pondérée d'une image couleur en une image mono-canal.
keywords: [canal, RGB, luminance, extraction, niveaux de gris, séparation de couleur]
related: [ChannelCombination, ConvertToGrayscale, ComponentSeparation, SCNR]
icon: layers-linked
references:
  - "PixInsight — ChannelExtraction tool reference (RGB/CIE color spaces)."
  - "ITU-R BT.709 — coefficients de luminance relative."
---

## Résumé

`ChannelExtraction` isole un canal d'une image couleur RGB et produit une nouvelle image
mono-canal. Il peut extraire directement le canal **R**, **G** ou **B**, ou calculer une
**luminance** `L` pondérée façon Rec. 709. Sur une image déjà en niveaux de gris (un seul
canal), le process est un simple passe-plat qui recopie les données.

## Cas d'usage

- **Isoler un canal** pour l'analyser ou le traiter indépendamment (débruitage sélectif,
  inspection du bruit propre à un filtre, diagnostic d'un canal saturé).
- **Extraire une luminance** en amont d'un traitement type LRGB (étirement de la luminance
  séparé de la chrominance, puis recombinaison via `LRGBCombination`).
- **Préparer des masques** à partir d'un canal spécifique (p. ex. un masque d'étoiles plus
  net sur le canal vert, souvent le moins bruité en capteur Bayer).
- **Diagnostiquer un déséquilibre colorimétrique** en comparant visuellement R, G et B
  extraits séparément.

## Fonctionnement

Le process lit le tableau de pixels `(H, W, C)` de la vue active :

- Si l'image ne compte qu'**un seul canal** (déjà mono), les données sont recopiées telles
  quelles — l'extraction est sans effet.
- Si `channel` vaut `R`, `G` ou `B`, le canal correspondant (index 0, 1 ou 2) est extrait
  par tranche et copié dans un tableau `(H, W, 1)`.
- Si `channel` vaut `L`, une **luminance pondérée** est calculée comme combinaison linéaire
  des trois canaux, avec les coefficients de la norme **ITU-R BT.709** (mêmes poids que la
  conversion RGB → niveaux de gris perceptuelle standard).

Dans tous les cas, le résultat est une image à un seul canal, en `float32`.

## Mathématiques

Soit $R(x,y)$, $G(x,y)$, $B(x,y)$ les trois plans de l'image d'entrée. Pour l'extraction
d'un canal primaire, la sortie est simplement une projection :

$$ I'(x,y) = C(x,y), \qquad C \in \{R, G, B\} \text{ selon le paramètre } \texttt{channel}. $$

Pour la luminance ($\texttt{channel} = \texttt{L}$), la sortie est la combinaison linéaire :

$$ L(x,y) = 0{,}2126\, R(x,y) + 0{,}7152\, G(x,y) + 0{,}0722\, B(x,y). $$

Ces coefficients (Rec. 709) reflètent la sensibilité relative de l'œil humain : le canal
vert domine la perception de luminosité, le bleu y contribue le moins. Ils diffèrent des
poids Rec. 601 (0,299 / 0,587 / 0,114) parfois utilisés ailleurs — `ChannelExtraction`
utilise systématiquement Rec. 709.

## Paramètres

- **`channel`** — *enum*, défaut `L`, choix : `R`, `G`, `B`, `L`. Canal à extraire : l'un des
  trois canaux primaires, ou `L` pour la luminance pondérée Rec. 709 calculée à partir des
  trois canaux.

## Astuces & pièges

> **Note** — sur une image déjà mono-canal, le process ne fait que recopier les données :
> il n'y a rien à « extraire » de plus.

> **Attention** — la luminance `L` n'est **pas** une simple moyenne des canaux : les poids
> Rec. 709 favorisent fortement le vert. Sur des images à dominante rouge ou bleu marquée
> (nébuleuses en Hα, par exemple), la luminance extraite peut sous-représenter le signal
> réel de ces canaux.

- Pour reconstruire une image couleur à partir de canaux extraits (éventuellement traités
  séparément), utilisez `ChannelCombination`.
- Pour une conversion RGB → niveaux de gris qui remplace directement l'image (plutôt que
  d'en extraire une copie mono-canal), voir `ConvertToGrayscale`.
- Pour séparer la couleur en composantes statistiquement indépendantes (PCA/ICA) plutôt
  qu'en canaux RGB bruts, voir `ComponentSeparation`.

## Voir aussi

- [ChannelCombination](retina-doc://ChannelCombination) — recompose une image RGB à partir de trois vues/canaux.
- [ConvertToGrayscale](retina-doc://ConvertToGrayscale) — conversion RGB → niveaux de gris de l'image entière.
- [ComponentSeparation](retina-doc://ComponentSeparation) — séparation en composantes indépendantes (PCA/ICA).
- [SCNR](retina-doc://SCNR) — traitement ciblé d'un canal (typiquement le vert) sans l'extraire.

## Références

- PixInsight — *ChannelExtraction* tool reference (espaces couleur RGB/CIE).
- ITU-R BT.709 — coefficients de luminance relative.
