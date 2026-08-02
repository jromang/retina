---
id: RangeSelection
category: MaskGeneration
title: Sélection de plage
brief: Construit un masque à partir d'une plage d'intensité sur la luminance, avec bords adoucis.
keywords: [masque, sélection, plage, luminance, seuillage, fuzziness, mask generation]
related: [StarMask, Binarize, HistogramTransformation, CurvesTransformation]
icon: select
references:
  - "PixInsight — RangeSelection tool reference."
  - "scipy.ndimage — gaussian_filter (lissage du masque)."
---

## Résumé

`RangeSelection` fabrique un **masque niveaux de gris à 1 canal** en sélectionnant les pixels
dont la **luminance** tombe dans une plage `[lower, upper]`. Les bords de la sélection peuvent
être adoucis par une rampe (`fuzziness`) puis lissés par un flou gaussien (`smoothness`). C'est
l'équivalent de l'outil `RangeSelection` de PixInsight : un process **non destructif** qui
**crée une nouvelle fenêtre** (comme `StarMask`), destinée à être utilisée comme masque de
protection ou de ciblage sur une autre vue.

![Image source — RangeSelection](figures/source.webp)
![Masque produit — RangeSelection](figures/mask.webp)

*L'image source, et le masque de la plage de luminosité sélectionnée.*

## Cas d'usage

- **Protéger le fond de ciel** pendant un étirement : sélectionner les basses valeurs
  (`lower=0`, `upper` faible) pour créer un masque qui limite l'effet aux tons faibles.
- **Cibler les hautes lumières** (cœurs d'étoiles, noyau de galaxie) en sélectionnant la plage
  haute, pour appliquer une réduction de bruit ou une compression sélective.
- **Isoler une bande de luminance** (ex. nébulosité de contraste moyen) sans dépendre de la
  détection de structures, contrairement à `StarMask`.
- **Construire un masque de transition douce** entre deux traitements, en jouant sur
  `fuzziness` pour éviter les démarcations nettes.

## Fonctionnement

1. La **luminance** est calculée comme la moyenne des canaux (image déjà en niveaux de gris si
   mono-canal).
2. Sans flou (`fuzziness = 0`), le masque est **binaire** : 1 si la luminance est dans
   `[lower, upper]`, 0 sinon.
3. Avec `fuzziness > 0`, deux **rampes linéaires** de largeur `fuzziness` remplacent les bords
   nets : la sélection croît progressivement de 0 à 1 en entrant dans la plage côté bas
   (autour de `lower`), et redescend de 1 à 0 en la quittant côté haut (autour de `upper`).
4. Si `smoothness > 0`, un **flou gaussien** (`scipy.ndimage.gaussian_filter`, écart-type
   `smoothness`) adoucit encore le masque — utile pour éliminer les artefacts de bord en
   dents de scie sur des structures fines.
5. Si `invert` est actif, le masque est **inversé** (`1 − masque`).
6. Le résultat est ramené dans `[0, 1]` et écrit dans une fenêtre mono-canal indépendante.

## Mathématiques

Soit $L(x,y)$ la luminance normalisée d'un pixel, $\ell$ = `lower`, $u$ = `upper`,
$f$ = `fuzziness`.

**Cas sans flou** ($f = 0$) — indicatrice de l'intervalle :

$$ M(x,y) = \mathbb{1}_{[\ell,\, u]}\big(L(x,y)\big) =
   \begin{cases} 1 & \text{si } \ell \le L(x,y) \le u \\ 0 & \text{sinon.} \end{cases} $$

**Cas avec flou** ($f > 0$) — deux rampes bornées se combinent par un minimum, ce qui donne
un plateau à 1 sur $[\ell, u]$ et des transitions linéaires de largeur $f$ de part et d'autre :

$$ b(x,y) = \operatorname{clip}\!\left(\frac{L(x,y) - (\ell - f)}{f},\, 0,\, 1\right), \qquad
   a(x,y) = \operatorname{clip}\!\left(\frac{(u + f) - L(x,y)}{f},\, 0,\, 1\right) $$

$$ M(x,y) = \operatorname{clip}\!\big(\min(b(x,y),\, a(x,y)),\, 0,\, 1\big) $$

**Lissage optionnel** (convolution gaussienne d'écart-type $\sigma$ = `smoothness`) :

$$ M_\sigma(x,y) = (M * G_\sigma)(x,y), \qquad
   G_\sigma(x,y) = \frac{1}{2\pi\sigma^2}\, e^{-\frac{x^2+y^2}{2\sigma^2}} $$

**Inversion finale** si `invert` est actif :

$$ M'(x,y) = 1 - M_\sigma(x,y) $$

## Paramètres

- **`lower`** — *real*, défaut `0.0`, plage `0`–`1`. Borne basse de la plage de luminance
  sélectionnée.
- **`upper`** — *real*, défaut `1.0`, plage `0`–`1`. Borne haute de la plage sélectionnée.
- **`fuzziness`** — *real*, défaut `0.0`, plage `0`–`1`. Largeur des rampes de transition
  linéaire appliquées de part et d'autre de `[lower, upper]`. À `0`, les bords sont nets
  (masque binaire).
- **`smoothness`** — *real*, défaut `0.0`, plage `0`–`50`. Écart-type $\sigma$ (en pixels) du
  flou gaussien appliqué au masque après le seuillage. À `0`, aucun lissage.
- **`invert`** — *bool*, défaut `False`. Inverse le masque final (sélectionne le complément
  de la plage).

## Astuces & pièges

> **Attention** — `lower > upper` produit une plage vide (masque tout noir) ; le process ne
> réordonne pas automatiquement les bornes.

> **Note** — la luminance utilisée est une simple **moyenne des canaux**, pas une pondération
> perceptuelle (Rec. 709/601). Sur des images très colorées, préférez travailler après une
> conversion en niveaux de gris cohérente si la sélection doit correspondre à une perception
> de luminosité précise.

- Un `fuzziness` non nul évite les artefacts de bord dur (« halo ») visibles quand le masque
  sert à mélanger deux traitements très différents.
- `smoothness` est complémentaire de `fuzziness` : `fuzziness` adoucit la **transition
  d'intensité**, `smoothness` adoucit la **géométrie** du masque (bords irréguliers, bruit).
- Le masque produit est une **nouvelle fenêtre** : il faut ensuite l'assigner comme masque
  d'une autre vue via `view.mask` pour qu'il ait un effet sur les traitements suivants.

## Voir aussi

- [StarMask](retina-doc://StarMask) — masque basé sur la détection de structures stellaires.
- [Binarize](retina-doc://Binarize) — seuillage dur en un masque strictement binaire.
- [HistogramTransformation](retina-doc://HistogramTransformation) — pour étirer la luminance
  avant sélection si la plage utile est peu contrastée.
- [CurvesTransformation](retina-doc://CurvesTransformation) — alternative pour façonner une
  courbe de sélection plus complexe qu'une simple plage.

## Références

- PixInsight — *RangeSelection* tool reference.
- scipy.ndimage — *gaussian_filter* (lissage du masque).
