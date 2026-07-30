---
id: Superbias
category: Calibration
title: Superbias
brief: "Modélise un master bias en lissé sans bruit par décomposition starlet (garde la structure grande échelle)."
keywords: [superbias, master bias, starlet, à trous, débruitage, calibration, ondelettes]
related: [Integration, ImageCalibration, MultiscaleLinearTransform, MultiscaleMedianTransform]
icon: photo
references:
  - "PixInsight — SuperBias script/process reference."
  - "Starck, J.-L. & Murtagh, F. — Astronomical Image and Data Analysis (starlet / à trous wavelet transform)."
  - "Starck, J.-L., Fadili, J., Murtagh, F. — The Undecimated Wavelet Decomposition and its Reconstruction."
---

## Résumé

`Superbias` transforme un master bias brut (moyenne/médiane d'une pile de biases) en une
version **lissée et sans bruit**, en ne conservant que sa **structure à grande échelle**
(motifs d'amplificateur, bandes de lecture, gradients de polarisation) et en supprimant le
bruit de lecture fin qu'une simple moyenne n'élimine jamais complètement. C'est l'équivalent
du script *SuperBias* de PixInsight : au lieu d'utiliser le bias empilé tel quel pour la
calibration, on utilise ce modèle lissé, qui n'injecte pas de bruit supplémentaire dans les
lights calibrées.

## Cas d'usage

- **Fabriquer un master bias de qualité** à partir d'une pile de biases déjà intégrée
  (`Integration`), avant de l'utiliser dans `ImageCalibration`.
- **Réduire le bruit ajouté par la soustraction du bias** : un bias brut, même moyenné sur
  plusieurs dizaines de frames, garde un résidu de bruit de lecture qui se propage dans
  chaque light calibrée. Le superbias supprime ce résidu tout en gardant les motifs fixes du
  capteur (colonnes chaudes, patterns d'ampli, glow de coin).
- **Isoler les structures fixes du capteur** pour diagnostic (mise en évidence des motifs de
  lecture indépendamment du bruit thermique aléatoire).

## Fonctionnement

L'algorithme applique une **décomposition starlet** (transformée en ondelettes « à trous »,
isotrope et non décimée) canal par canal, puis ne garde que le **résidu** de la décomposition —
la version la plus lissée de l'image, obtenue après avoir retiré les `noise_layers` premières
couches de détail (les plus fines, donc les plus bruitées).

Concrètement, pour chaque canal :

1. On convolue itérativement l'image avec un noyau B3-spline dilaté (« à trous ») à des
   échelles croissantes $2^0, 2^1, \dots, 2^{n-1}$, où $n$ = `noise_layers`.
2. À chaque itération $j$, la **couche de détail** est la différence entre l'approximation
   courante et l'approximation plus lissée obtenue par la convolution à l'échelle $j$.
3. Après $n$ itérations, il reste un **résidu** — l'image lissée à l'échelle $2^{n}$ — qui ne
   contient plus que les structures dont la taille caractéristique dépasse cette échelle.

Seul ce résidu est renvoyé (les couches de détail, porteuses du bruit fin pixel à pixel, sont
jetées) : c'est le « superbias ». Le résultat est ensuite écrêté dans `[0, 1]`.

## Mathématiques

La transformée starlet utilise le noyau B3-spline 1D $h = \tfrac{1}{16}(1, 4, 6, 4, 1)$,
séparable en 2D (convolution successive sur les lignes puis les colonnes). À l'échelle $j$, ce
noyau est dilaté par insertion de $2^j - 1$ zéros entre ses coefficients (algorithme *à trous*),
ce qui donne un filtre passe-bas $h_j$ de support croissant sans sous-échantillonnage.

En notant $c_0 = I$ l'image d'entrée (par canal), l'algorithme itère pour $j = 0, \dots, n-1$ :

$$ c_{j+1} = h_j * c_j, \qquad w_{j+1} = c_j - c_{j+1}, $$

où $w_{j+1}$ est la couche de détail à l'échelle $j{+}1$ et $c_{j+1}$ l'approximation lissée qui
sert d'entrée à l'itération suivante. La reconstruction exacte de l'image d'origine serait :

$$ I = c_n + \sum_{j=1}^{n} w_j . $$

`Superbias` ne garde que le premier terme, le **résidu** $c_n$ :

$$ I_{\text{superbias}} = \operatorname{clip}(c_n,\; 0,\; 1). $$

Les couches $w_1, \dots, w_n$, qui concentrent l'essentiel du bruit de lecture haute fréquence
(corrélé sur quelques pixels au plus), sont éliminées. Plus $n$ = `noise_layers` est grand, plus
l'échelle de coupure $2^n$ est élevée et plus le lissage est agressif : le résultat converge
vers une image quasi constante qui ne conserve que les gradients les plus larges.

## Paramètres

- **`noise_layers`** — *int*, défaut `6`, plage `1`–`12`. Nombre de couches de détail starlet
  annulées avant reconstruction. Une valeur faible (1–2) ne retire que le bruit pixel à pixel le
  plus fin et conserve des motifs assez petits (colonnes, blocs d'ampli) ; une valeur élevée
  (8–12) lisse beaucoup plus fort et ne garde que des gradients à très grande échelle, au risque
  d'effacer des motifs de lecture réels de taille moyenne.

## Astuces & pièges

> **Attention** — appliquez `Superbias` sur un bias déjà **intégré** (`Integration` sur une
> pile de dizaines de biases), jamais sur un bias unique : sur une seule pose, le lissage
> starlet ne fait que flouter le bruit sans base statistique solide pour distinguer signal fixe
> et bruit aléatoire.

> **Note** — `noise_layers` trop élevé peut gommer des structures fixes réelles (patterns
> d'amplificateur à moyenne échelle, glow de coin) que l'on souhaiterait conserver dans le
> master de calibration. Comparez visuellement le superbias et le bias intégré brut (differ via
> `PixelMath`) avant de valider le choix.

- Le superbias résultant s'utilise exactement comme un master bias classique dans
  `ImageCalibration` (paramètre bias).
- Comme `Superbias` opère canal par canal, il peut être appliqué directement sur un bias couleur
  ou CFA sans démosaïçage préalable si les canaux du capteur le permettent (voir `SplitCFA` pour
  traiter chaque site de Bayer séparément si nécessaire).

## Voir aussi

- [Integration](retina-doc://Integration) — empile la pile de biases brute avant modélisation.
- [ImageCalibration](retina-doc://ImageCalibration) — consomme le master bias (superbias ou non).
- [MultiscaleLinearTransform](retina-doc://MultiscaleLinearTransform) — même transformée starlet,
  avec contrôle indépendant de chaque échelle.
- [MultiscaleMedianTransform](retina-doc://MultiscaleMedianTransform) — variante non linéaire
  (médiane) de la décomposition multi-échelle.

## Références

- PixInsight — *SuperBias* script/process reference.
- Starck, J.-L. & Murtagh, F. — *Astronomical Image and Data Analysis* (transformée starlet / à trous).
- Starck, J.-L., Fadili, J., Murtagh, F. — *The Undecimated Wavelet Decomposition and its Reconstruction*.
