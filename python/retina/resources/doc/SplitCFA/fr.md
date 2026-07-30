---
id: SplitCFA
category: Calibration
title: Séparation CFA (SplitCFA)
brief: "Sépare une mosaïque CFA (Bayer) mono-canal en 4 sous-plans demi-résolution empilés, un par site du filtre."
keywords: [CFA, Bayer, mosaïque, dématriçage, décimation, super-pixel, canaux]
related: [MergeCFA, Debayer, CosmeticCorrection, NoiseReduction]
icon: grid-dots
references:
  - "PixInsight — SplitCFA / MergeCFA scripts (PixInsight Scripts repository)."
  - "Convention CFA Bayer RGGB/BGGR/GRBG/GBRG — voir `Debayer`."
---

## Résumé

`SplitCFA` prend une image **mono-canal brute non dématricée** — la mosaïque de filtre couleur
(CFA, typiquement un motif de Bayer) telle que livrée par le capteur — et la réorganise en
**4 plans demi-résolution** empilés comme canaux (`CFA0`..`CFA3`), un par position dans le bloc
2×2 répété du filtre. C'est une opération purement géométrique de **décimation/repackaging**,
sans interpolation ni perte d'information : `MergeCFA` en est l'inverse exact.

## Cas d'usage

- **Corriger les pixels chauds/froids par photosite** (`CosmeticCorrection`) avant dématriçage,
  pour éviter qu'un défaut ne soit étalé sur ses voisins par l'interpolation du `Debayer`.
- **Calibrer ou empiler chaque site du filtre séparément** (approche « super-pixel » / CFA
  drizzle) — bias/dark/flat par plan — avant de recomposer avec `MergeCFA` puis dématricer.
- **Débruiter indépendamment chaque canal brut** (`NoiseReduction`, `WaveletDenoise`…) sans que
  le bruit d'un site ne contamine ses voisins via l'interpolation couleur.
- **Analyser le bruit ou le gradient de fond par filtre couleur** sur les données natives du
  capteur, avant toute reconstruction couleur.

## Fonctionnement

`SplitCFA` opère uniquement sur le **canal 0** de l'image d'entrée (la mosaïque CFA brute est
supposée mono-canal, capturée avant tout dématriçage).

1. La hauteur et la largeur sont tronquées au nombre pair inférieur : une éventuelle dernière
   ligne ou colonne impaire est ignorée.
2. Le plan est découpé en **quatre sous-grilles** par décimation de facteur 2, selon la parité
   de la ligne et de la colonne : (ligne paire, colonne paire), (paire, impaire), (impaire,
   paire), (impaire, impaire).
3. Les quatre sous-grilles, chacune de taille `(H/2, W/2)`, sont empilées comme quatrième
   dimension pour donner une sortie `(H/2, W/2, 4)`.

Contrairement à `Debayer`, `SplitCFA` **n'interprète pas** le motif du filtre (RGGB, BGGR,
GRBG, GBRG) : il n'a pas de paramètre `pattern`. Il se contente de repartir la grille selon la
parité ; c'est à l'utilisateur de savoir quel plan (`CFA0`..`CFA3`) correspond à quel filtre
couleur, en fonction du motif réel du capteur.

## Mathématiques

Soit $C(y, x)$ la mosaïque CFA d'entrée, $y \in [0, H)$, $x \in [0, W)$. On tronque aux
dimensions paires $H' = 2\lfloor H/2 \rfloor$, $W' = 2\lfloor W/2 \rfloor$. Pour
$i \in [0, H'/2)$, $j \in [0, W'/2)$, les quatre plans sont :

$$
P_0(i,j) = C(2i,\,2j), \quad
P_1(i,j) = C(2i,\,2j{+}1), \quad
P_2(i,j) = C(2i{+}1,\,2j), \quad
P_3(i,j) = C(2i{+}1,\,2j{+}1).
$$

La sortie est l'empilement $S(i,j,k) = P_k(i,j)$ pour $k \in \{0,1,2,3\}$, de forme
$(H'/2, W'/2, 4)$. Cette correspondance est une **bijection** entre la grille de pixels
tronquée et le cube de sortie ; elle est réversible sans perte, exactement inversée par
`MergeCFA` :

$$ C(2i+a,\; 2j+b) = S(i, j,\; 2a+b), \qquad a, b \in \{0,1\}. $$

Aucune moyenne, interpolation ni filtrage n'intervient : chaque échantillon de sortie est un
pixel d'entrée déplacé, pas une combinaison de pixels.

## Paramètres

Ce process n'a **aucun paramètre**. Le découpage suit toujours l'ordre pair/impair des lignes
et colonnes ; il n'y a pas de choix de motif CFA (contrairement à `Debayer`) car l'opération ne
dépend que de la parité, pas de la couleur des filtres.

## Astuces & pièges

> **Attention** — `SplitCFA` suppose une entrée **mono-canal** (mosaïque brute). Appliqué à une
> image déjà en couleur (RGB, issue d'un `Debayer` ou d'un fichier standard), il utilise
> silencieusement le seul canal 0 (rouge) sans lever d'erreur : le résultat n'a alors aucun sens
> physique.

> **Note** — l'identité colorée des plans `CFA0`..`CFA3` dépend du motif Bayer réel du capteur
> **et** de tout décalage de parité introduit par un recadrage antérieur (un crop décalé d'un
> pixel impair inverse lignes/colonnes paires et impaires). Vérifiez toujours la correspondance
> avec le motif déclaré dans `Debayer` avant d'interpréter les plans comme R/G/G/B.

- Traitez systématiquement `SplitCFA` et `MergeCFA` en paire encadrant l'étape par-photosite :
  le résultat recomposé doit être bit-exact à l'original si aucun traitement n'a été appliqué.
- Les deux plans « verts » (`CFA1`/`CFA2` en RGGB) peuvent différer légèrement en gain : les
  traiter séparément puis les recomposer préserve cette information au lieu de la moyenner.

## Voir aussi

- [MergeCFA](retina-doc://MergeCFA) — recompose la mosaïque pleine résolution (inverse exact).
- [Debayer](retina-doc://Debayer) — dématriçage complet avec interprétation du motif CFA.
- [CosmeticCorrection](retina-doc://CosmeticCorrection) — correction de défauts, à appliquer
  idéalement par photosite.
- [NoiseReduction](retina-doc://NoiseReduction) — débruitage, applicable canal par canal après
  séparation.

## Références

- PixInsight — *SplitCFA* / *MergeCFA* scripts (dépôt de scripts PixInsight).
- Convention CFA Bayer RGGB/BGGR/GRBG/GBRG — voir `Debayer`.
