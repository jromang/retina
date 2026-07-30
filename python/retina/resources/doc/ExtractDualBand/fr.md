---
id: ExtractDualBand
category: Calibration
title: Extraction dual-band (ExtractDualBand)
brief: "Extrait le canal Ha ou OIII d'une brute couleur (OSC) prise sous filtre dual-band, par décimation superpixel."
keywords: [dual-band, narrowband, Ha, OIII, OSC, CFA, Bayer, superpixel, Seestar, Dwarf, télescope intelligent]
related: [Debayer, SplitCFA, MergeCFA, ChannelCombination, NBRGBCombination]
icon: grid-dots
references:
  - "Convention CFA Bayer RGGB/BGGR/GRBG/GBRG — voir `Debayer`."
  - "Raies Hα 656,3 nm et [O III] 500,7 nm ; les filtres dual-band courants (L-eXtreme, L-Ultimate) ne laissent passer que ces deux bandes."
---

## Résumé

`ExtractDualBand` transforme une **brute couleur (OSC) non dématricée**, prise sous **filtre
dual-band Ha/OIII**, en une **image monochrome narrowband**. Il lit directement la matrice de
filtres colorés : la raie Hα (656 nm) n'atteint que les photosites **rouges**, la raie
[O III] (500 nm) que les **verts**. Un bloc CFA 2×2 donne un pixel de sortie — une décimation
**superpixel**, sans la moindre interpolation. La sortie fait la moitié de la largeur et de la
hauteur, en un seul canal.

C'est le process à employer avec les télescopes intelligents (Seestar, Dwarf) et toute caméra
OSC derrière un filtre de type L-eXtreme / L-Ultimate.

## Cas d'usage

- **Séparer une session dual-band OSC en vrais masters Ha et OIII** : extraire sur chaque light
  calibrée, intégrer séparément le lot Ha et le lot OIII, puis recomposer en palette HOO (ou
  façon SHO) avec `ChannelCombination`.
- **Éviter le mélange des raies par le dématriçage** : `Debayer` interpole chaque échantillon
  manquant depuis ses voisins, ce qui mêle deux raies d'émission physiquement étrangères l'une
  à l'autre. Extraire d'abord garde chaque raie pure.
- **Mesurer un vrai rapport signal/bruit par raie** — fond de ciel, gradient et profils
  d'étoiles de l'image Ha sont ceux de Hα seul, pas d'un canal rouge contaminé d'OIII.
- **Alimenter les outils dédiés au narrowband** (`NarrowbandNormalization`,
  `NBRGBCombination`, traitement sans étoiles) avec de véritables données monochromes.

## Fonctionnement

L'entrée doit être une **mosaïque CFA mono-canal** — la sortie native du capteur, avant tout
dématriçage. Une image multi-canaux est refusée par une erreur explicite plutôt que traitée en
silence : une image déjà dématricée ne porte plus de mosaïque récupérable.

1. La hauteur et la largeur sont tronquées au nombre pair inférieur, pour que la grille de
   blocs 2×2 pave exactement l'image (une dernière ligne ou colonne impaire est ignorée).
2. Les quatre lettres de `pattern` sont posées sur les positions du bloc dans l'ordre de
   lecture : `(0,0)`, `(0,1)`, `(1,0)`, `(1,1)`.
3. Avec `band = ha`, le plan situé sur le site **R** est rendu tel quel.
4. Avec `band = oiii`, les **deux plans G sont moyennés**.

Le site bleu est délibérément écarté. Une part d'OIII passe bien le filtre bleu, mais avec un
rendement quantique nettement différent et une autre contribution du fond de ciel ; l'y
ajouter dégraderait la mesure au lieu de l'améliorer.

Moyenner les deux verts n'est pas un détail cosmétique : les deux échantillons verts d'un bloc
sont deux mesures indépendantes de la même émission, quasiment au même endroit — leur moyenne
porte donc le même signal avec un bruit réduit d'un facteur √2.

## Mathématiques

Soit $C(y,x)$ la mosaïque CFA et $\pi \in \{$RGGB, BGGR, GRBG, GBRG$\}$ l'attribution d'une
lettre de filtre à chacune des quatre positions $(a,b)$, $a,b \in \{0,1\}$, du bloc répété. On
note $(a_R, b_R)$ la position du site rouge et $(a_{G_1}, b_{G_1})$, $(a_{G_2}, b_{G_2})$
celles des deux verts. Pour $i \in [0, H/2)$, $j \in [0, W/2)$ :

$$ \mathrm{Ha}(i,j) = C(2i + a_R,\; 2j + b_R), $$

$$ \mathrm{OIII}(i,j) = \tfrac{1}{2}\Big[ C(2i + a_{G_1},\, 2j + b_{G_1}) + C(2i + a_{G_2},\, 2j + b_{G_2}) \Big]. $$

Si les deux échantillons verts portent le même signal $s$ avec un bruit indépendant d'écart
type $\sigma$, leur moyenne a pour signal $s$ et pour bruit

$$ \sigma_{\mathrm{OIII}} = \frac{\sigma}{\sqrt{2}} \approx 0{,}707\,\sigma, $$

soit un gain de √2 en rapport signal/bruit sans coût en résolution, les deux échantillons
appartenant au même pixel de sortie.

Les deux sorties ont la forme $(\lfloor H/2 \rfloor, \lfloor W/2 \rfloor, 1)$. Chaque
échantillon de sortie est soit un pixel d'entrée déplacé (Ha), soit la moyenne de deux d'entre
eux (OIII) : aucun noyau d'interpolation, aucun filtrage, aucune donnée inventée.

## Paramètres

- **`pattern`** — *enum*, défaut `RGGB`, choix : `RGGB`, `BGGR`, `GRBG`, `GBRG`. Le motif CFA
  du capteur, exactement comme dans `Debayer`.
- **`band`** — *enum*, défaut `ha`, choix : `ha`, `oiii`. `ha` prend le site rouge (656 nm) ;
  `oiii` prend la moyenne des deux sites verts (500 nm).

## Astuces & pièges

> **Attention** — à appliquer **avant** `Debayer`, sur la mosaïque brute. Sur une image
> couleur, le process lève une erreur : il n'y a plus de mosaïque à lire.

> **Attention** — un `pattern` erroné ne donne pas une image visiblement cassée, mais une
> image **plausible et fausse** : avec une confusion rouge/vert, le « Ha » serait en réalité un
> site vert. Vérifiez le motif annoncé par le logiciel d'acquisition (mot-clé `BAYERPAT`), et
> rappelez-vous qu'un recadrage antérieur décalé d'un nombre impair de pixels **change** le
> motif effectif.

> **Note** — l'extraction est une décimation : le résultat fait la moitié de la taille dans
> chaque dimension. Appliquez-la à toutes les lights de la session (jamais à une partie
> seulement), sans quoi recalage et intégration se heurteraient à des géométries différentes.

- Calibrez (bias/dark/flat) **avant** d'extraire : les images de calibration sont elles-mêmes
  des mosaïques CFA et doivent être soustraites photosite par photosite.
- Les Ha et OIII extraits d'une même brute partagent la même géométrie WCS au facteur 2 près :
  un plate-solve fait sur l'un se transpose à l'autre.
- Le signal OIII d'une cible dual-band est en général bien plus faible que le Ha : attendez-vous
  à étirer très différemment les deux intégrations avant de les recomposer.

## Voir aussi

- [Debayer](retina-doc://Debayer) — dématriçage couleur complet, exactement l'intention inverse.
- [SplitCFA](retina-doc://SplitCFA) — conserve les quatre sites CFA en plans séparés, sans perte.
- [MergeCFA](retina-doc://MergeCFA) — recompose une mosaïque pleine résolution.
- [ChannelCombination](retina-doc://ChannelCombination) — construit l'image couleur HOO/SHO à
  partir des masters narrowband intégrés.
- [NBRGBCombination](retina-doc://NBRGBCombination) — mêle des données narrowband à une image RGB.

## Références

- Convention CFA Bayer RGGB/BGGR/GRBG/GBRG — voir `Debayer`.
- Raies Hα 656,3 nm et [O III] 500,7 nm ; les filtres dual-band courants (L-eXtreme,
  L-Ultimate) ne laissent passer que ces deux bandes.
