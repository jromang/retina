---
id: WaveletDenoise
category: NoiseReduction
title: Débruitage par ondelettes (WaveletDenoise)
brief: Débruitage par transformée en ondelettes stationnaire (SWT) et seuillage doux robuste par bande.
keywords: [ondelettes, SWT, seuillage doux, MAD, débruitage, PyWavelets, multi-échelle]
related: [NonLocalMeansDenoise, TGVDenoise, MultiscaleLinearTransform, WaveletTransform]
icon: wave-sine
references:
  - "Donoho, D. L. & Johnstone, I. M. — Ideal spatial adaptation by wavelet shrinkage (1994)."
  - "Nason, G. P. & Silverman, B. W. — The stationary wavelet transform and some statistical applications (1995)."
  - "PyWavelets documentation — swt2 / iswt2 (stationary wavelet transform)."
---

## Résumé

`WaveletDenoise` réduit le bruit en décomposant l'image sur une **transformée en ondelettes
stationnaire** (SWT, *Stationary Wavelet Transform*, aussi appelée « à trous » décimée nulle),
puis en **seuillant en douceur** les coefficients de détail de chaque bande et de chaque
échelle avant reconstruction. Contrairement à la DWT classique (décimée), la SWT est
**invariante par translation** : elle ne sous-échantillonne jamais, ce qui élimine les
artefacts de bloc et les pseudo-structures en damier caractéristiques du débruitage par
ondelettes décimées. Le seuil est dérivé automatiquement du **bruit robuste** (MAD) mesuré
dans chaque bande, sans réglage manuel par échelle.

## Cas d'usage

- **Débruiter des images faible SNR** (cibles faibles, poses courtes, ciel pollué) en
  préservant mieux les structures fines que les filtres spatiaux classiques.
- **Nettoyer le bruit résiduel après empilement** sans lisser les bords des étoiles ni les
  filaments ténus de nébulosité, grâce au seuillage adaptatif par bande.
- **Alternative à `NonLocalMeansDenoise`** quand le bruit est plutôt gaussien/quasi-stationnaire
  et que l'on souhaite un contrôle fin par échelle via `level`.
- **Étape de prétraitement** avant un étirement fort (`HistogramTransformation`,
  `AdaptiveStretch`), qui amplifierait sinon le bruit résiduel.

## Fonctionnement

Pour chaque canal de couleur, indépendamment :

1. **Complétion en miroir** (padding réflectif) de l'image pour que ses dimensions soient
   multiples de `2**level`, contrainte imposée par la SWT à 2 dimensions.
2. **Décomposition SWT** (`pywt.swt2`) sur `level` niveaux avec l'ondelette `wavelet`, produisant
   une approximation basse fréquence et, pour chaque échelle, trois bandes de détail
   (horizontale `cH`, verticale `cV`, diagonale `cD`).
3. Pour **chaque bande de détail**, estimation robuste de l'écart-type du bruit via le
   **MAD** (Median Absolute Deviation) de la bande, puis **seuillage doux** (soft-thresholding)
   des coefficients à `threshold` fois cet écart.
4. **Reconstruction** (`pywt.iswt2`) à partir de l'approximation inchangée et des détails
   seuillés, puis recadrage à la taille d'origine et clip dans `[0, 1]`.

L'approximation (basses fréquences, contenant le fond de ciel et les structures larges) n'est
jamais seuillée : seul le bruit à haute fréquence, porté par les détails, est atténué.

## Mathématiques

Soit $c_{j,o}$ les coefficients de détail à l'échelle $j \in \{1,\dots,\text{level}\}$ et
orientation $o \in \{H, V, D\}$ issus de la SWT. Pour chaque bande, l'écart-type robuste du
bruit est estimé par le **MAD** :

$$ \sigma_{j,o} = 1.4826 \cdot \operatorname{med}\big(\,|c_{j,o} - \operatorname{med}(c_{j,o})|\,\big) $$

Le facteur $1.4826$ rend cet estimateur cohérent avec l'écart-type d'une loi normale. Le seuil
appliqué à la bande est $t_{j,o} = k \cdot \sigma_{j,o}$, où $k$ = `threshold`. Chaque coefficient
subit ensuite un **seuillage doux** (soft-threshold de Donoho–Johnstone) :

$$ \hat{c} = \operatorname{sign}(c)\,\max\big(|c| - t_{j,o},\; 0\big) $$

Le seuillage doux, contrairement au seuillage dur ($\hat c = c \cdot \mathbb{1}_{|c|>t}$), atténue
également les coefficients au-dessus du seuil, ce qui produit une reconstruction plus lisse et
évite les discontinuités visibles autour du seuil. L'image reconstruite est
$\hat{I} = \mathcal{W}^{-1}(\{a\},\{\hat{c}_{j,o}\})$, où $\mathcal{W}^{-1}$ est la SWT inverse
et $a$ l'approximation non modifiée.

## Paramètres

- **`wavelet`** — *str*, défaut `db2`. Famille d'ondelette orthogonale utilisée par PyWavelets
  (ex. `db2`, `sym4`, `coif1`). Les ondelettes de Daubechies (`dbN`) sont un bon choix général ;
  les symlets (`symN`) sont plus symétriques et déforment moins les contours.
- **`level`** — *int*, défaut `3`, plage `1`–`8`. Nombre d'échelles de décomposition. Plus de
  niveaux traitent des structures de bruit à plus grande échelle mais augmentent le coût et le
  risque de lisser des détails fins.
- **`threshold`** — *real*, défaut `3.0`, plage `0`–`20`. Facteur multiplicatif `k` appliqué à
  l'écart robuste (MAD) de chaque bande pour fixer le seuil de seuillage doux. Plus élevé =
  débruitage plus agressif mais risque de lisser les structures faibles.

## Astuces & pièges

> **Attention** — un `threshold` trop élevé aplatit les filaments ténus de nébulosité et le
> grain fin des galaxies, qui partagent le même contenu haute fréquence que le bruit. Contrôlez
> le résultat en zoomant sur les zones de signal faible, pas seulement sur le fond de ciel.

> **Note** — les dimensions de l'image sont automatiquement complétées en miroir pour respecter
> la contrainte `2**level` de la SWT ; le résultat est recadré à la taille d'origine, aucune
> action de l'utilisateur n'est requise.

- Commencez avec `level=3` et `threshold=3.0` (équivalent à un seuil « 3-sigma » classique), puis
  ajustez : montez `threshold` sur du bruit fort, descendez-le si les détails fins se dégradent.
- Sur du bruit fortement non gaussien (chroma noise, artefacts de compression), préférez
  `NonLocalMeansDenoise` ou `TGVDenoise`, mieux adaptés à ces profils de bruit.
- Travaillez de préférence sur des données encore linéaires ou peu étirées : le seuillage MAD
  suppose un bruit dont l'amplitude reste homogène dans chaque bande.

## Voir aussi

- [NonLocalMeansDenoise](retina-doc://NonLocalMeansDenoise) — débruitage par patchs auto-similaires.
- [TGVDenoise](retina-doc://TGVDenoise) — débruitage variationnel préservant les bords.
- [MultiscaleLinearTransform](retina-doc://MultiscaleLinearTransform) — starlet à trous (approche multi-échelle voisine).
- [WaveletTransform](retina-doc://WaveletTransform) — décomposition/reconstruction DWT avec gain par bande.

## Références

- Donoho, D. L. & Johnstone, I. M. — *Ideal spatial adaptation by wavelet shrinkage* (1994).
- Nason, G. P. & Silverman, B. W. — *The stationary wavelet transform and some statistical applications* (1995).
- PyWavelets documentation — *swt2* / *iswt2* (stationary wavelet transform).
