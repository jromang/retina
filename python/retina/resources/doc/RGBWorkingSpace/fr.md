---
id: RGBWorkingSpace
category: ColorSpaces
title: Espace de travail RVB (RGBWorkingSpace)
brief: Renormalise le gain de chaque canal RVB selon des poids de luminance relatifs, façon RGBWS de PixInsight.
keywords: [RGBWS, poids de luminance, balance des couleurs, Rec.709, canaux RVB, gain par canal]
related: [ColorCalibration, SCNR, ColorSaturation, LinearFit]
icon: color-swatch
references:
  - "PixInsight — RGBWorkingSpace process reference."
  - "ITU-R BT.709 — coefficients de luminance relative R/V/B."
---

## Résumé

`RGBWorkingSpace` modélise, de façon minimale, l'espace de travail RVB de PixInsight : il
prend trois **poids de luminance** (un par canal Rouge/Vert/Bleu) et les utilise pour
**rééquilibrer le gain de chaque canal**. Contrairement à PixInsight, où RGBWS ne fait
qu'attacher des coefficients de pondération réutilisés par d'autres outils (calcul de
luminance, SCNR, etc.), cette version Retina **applique directement** le rééquilibrage aux
pixels : c'est un raccourci pragmatique tant que le pipeline ne porte pas de métadonnée de
poids partagée entre process.

## Cas d'usage

- **Simuler une autre convention de pondération** (Rec.709, Rec.601, équi-énergie…) avant des
  traitements sensibles à la luminance (`SCNR`, `ColorSaturation`, réduction de bruit
  structurelle) pour voir comment leur résultat varierait selon la définition du canal Vert
  « dominant ».
- **Corriger un déséquilibre global de canaux** en donnant plus de poids au canal le plus
  faible et moins au plus fort — un ajustement rapide et grossier, à ne pas confondre avec un
  vrai étalonnage colorimétrique.
- **Pédagogie / expérimentation** : visualiser concrètement l'effet d'un changement de
  pondération RVB sur une image réelle, avant d'implémenter des outils luminance-dépendants
  plus fins.

## Fonctionnement

1. Si l'image a moins de 3 canaux (monochrome), elle est renvoyée inchangée (copie).
2. Les trois poids `rw`, `gw`, `bw` sont **normalisés** pour sommer à 1 (repli sur 1.0 si la
   somme est nulle, pour éviter une division par zéro).
3. Chaque poids normalisé est multiplié par 3, ce qui donne un **gain par canal** dont la
   somme vaut toujours 3 (gain moyen = 1) : c'est ce facteur ×3 qui rend le résultat neutre
   quand les trois poids sont égaux.
4. Chaque canal est multiplié par son gain, puis le résultat est **écrêté** dans `[0, 1]` et
   reconverti en `float32`.

## Mathématiques

Soit $w = (r_w, g_w, b_w)$ les poids fournis et $S = r_w + g_w + b_w$ (avec $S \leftarrow 1$
si $S = 0$). Les poids normalisés et les gains par canal sont :

$$ \tilde{w}_c = \frac{w_c}{S}, \qquad g_c = 3\,\tilde{w}_c, \qquad c \in \{R, G, B\}. $$

Par construction $\sum_c g_c = 3$, donc le gain moyen vaut toujours $1$. L'image de sortie est :

$$ I'_c(x,y) = \operatorname{clip}\big(I_c(x,y)\cdot g_c,\; 0,\; 1\big). $$

Le cas neutre ($I' = I$) correspond exactement à $\tilde{w}_R = \tilde{w}_G = \tilde{w}_B =
\tfrac{1}{3}$, c'est-à-dire des poids **égaux entre eux**, quelle que soit leur valeur absolue
commune (puisqu'ils sont renormalisés). Tout écart d'un poids par rapport aux deux autres se
traduit par une amplification (poids relatif > 1/3) ou une atténuation (poids relatif < 1/3)
proportionnelle du canal correspondant.

## Paramètres

- **`rw`** — *real*, défaut `0.2126`, plage `0`–`1`. Poids de luminance relatif du canal
  Rouge (valeur par défaut = coefficient Rec.709).
- **`gw`** — *real*, défaut `0.7152`, plage `0`–`1`. Poids de luminance relatif du canal
  Vert (valeur par défaut = coefficient Rec.709).
- **`bw`** — *real*, défaut `0.0722`, plage `0`–`1`. Poids de luminance relatif du canal
  Bleu (valeur par défaut = coefficient Rec.709).

## Astuces & pièges

> **Attention** — les valeurs par défaut (`0.2126 / 0.7152 / 0.0722`) sont les coefficients
> Rec.709, mais **elles ne sont pas égales entre elles** : appliquer le process avec ces
> réglages par défaut **n'est pas neutre**. Avec ces poids, le gain effectif vaut
> $g_R \approx 0{,}64$, $g_G \approx 2{,}15$, $g_B \approx 0{,}22$ — l'image vire nettement
> au vert. Pour un passage neutre, réglez les trois poids à une **valeur identique**
> (p. ex. `rw = gw = bw = 0.333`).

- Ce n'est **pas** un outil d'étalonnage colorimétrique (voir `ColorCalibration` ou
  `SpectrophotometricColorCalibration` pour un vrai calage sur des catalogues d'étoiles) : les
  poids ici sont choisis à la main, sans référence photométrique.
- Les gains étant appliqués canal par canal indépendamment, une teinte dominante préexistante
  (pollution lumineuse, filtre non calibré) sera amplifiée si son canal reçoit un poids élevé.
- Travaillez de préférence sur une image linéaire non étirée : sur une image déjà étirée, le
  rééquilibrage de gain déplace aussi le point noir perçu de chaque canal.

## Voir aussi

- [ColorCalibration](retina-doc://ColorCalibration) — étalonnage colorimétrique par étoiles de référence.
- [SCNR](retina-doc://SCNR) — suppression sélective de la dominante verte.
- [ColorSaturation](retina-doc://ColorSaturation) — ajustement de la saturation par teinte.
- [LinearFit](retina-doc://LinearFit) — ajustement linéaire des canaux sur une référence.

## Références

- PixInsight — *RGBWorkingSpace* process reference.
- ITU-R BT.709 — coefficients de luminance relative R/V/B.
