---
id: NoiseReduction
category: NoiseReduction
title: Réduction de bruit
brief: Débruitage généraliste à méthode interchangeable (variation totale, ondelettes, bilatéral).
keywords: [débruitage, bruit, variation totale, ondelettes, bilatéral, lissage, edge-preserving]
related: [TGVDenoise, WaveletDenoise, NonLocalMeansDenoise, ACDNR]
icon: sparkles
references:
  - "scikit-image — skimage.restoration.denoise_tv_chambolle, denoise_wavelet, denoise_bilateral."
  - "Chambolle, A. (2004) — An Algorithm for Total Variation Minimization and Applications."
  - "Chang, Yu & Vetterli (2000) — Adaptive Wavelet Thresholding for Image Denoising (BayesShrink)."
  - "Tomasi & Manduchi (1998) — Bilateral Filtering for Gray and Color Images."
---

## Résumé

`NoiseReduction` est le débruiteur **généraliste** de Retina : un seul process, trois
algorithmes interchangeables via le paramètre `method` — **variation totale** (`tv`),
**seuillage d'ondelettes** (`wavelet`) et **filtre bilatéral** (`bilateral`). C'est le point
d'entrée le plus simple pour lisser le bruit résiduel après intégration, avant d'explorer les
outils plus spécialisés (`TGVDenoise`, `WaveletDenoise`, `NonLocalMeansDenoise`…) qui offrent
davantage de réglages fins. C'est un mince wrapper autour de `skimage.restoration`.

## Cas d'usage

- **Nettoyage rapide** d'une image intégrée avant étirement, sans régler de nombreux
  paramètres.
- **Comparer trois familles de débruitage** en changeant juste `method`, pour choisir celle qui
  convient le mieux au grain de l'image (bruit gaussien, bruit de photon, bruit chromatique).
- **`tv`** : fond de ciel très bruité à aplanir en préservant les contours nets (galaxies,
  bords de nébuleuses).
- **`wavelet`** : bruit multi-échelle, avec seuillage automatique adapté au niveau de bruit
  estimé — peu de réglage nécessaire.
- **`bilateral`** : lissage doux qui respecte les transitions de luminosité tout en gardant un
  contrôle explicite via `strength`.

## Fonctionnement

Le process délègue entièrement le calcul aux fonctions de `skimage.restoration`, sélectionnées
par `method` :

- **`tv`** — `denoise_tv_chambolle(data, weight=strength, channel_axis=-1)` : minimise une
  énergie combinant fidélité aux données et variation totale, résolue par l'algorithme de
  projection duale de Chambolle. Le traitement est **conjoint sur les canaux** (`channel_axis`),
  ce qui évite les artefacts de couleur aux contours.
- **`wavelet`** — `denoise_wavelet(data, channel_axis=-1, rescale_sigma=True)` : décompose
  l'image en ondelettes, estime le bruit par canal de façon robuste et applique un seuillage
  doux (méthode BayesShrink par défaut de scikit-image) sur les coefficients de détail avant
  reconstruction. Nécessite **PyWavelets** (installé par l'extra `[astro]`) ; sans lui, une
  erreur explicite est levée.
- **`bilateral`** — `denoise_bilateral(sigma_color=strength, sigma_spatial=3)`, appliqué
  **canal par canal indépendamment** (boucle Python) : moyenne pondérée par la proximité
  spatiale *et* la similarité d'intensité, ce qui préserve les bords tout en lissant les zones
  homogènes.

## Mathématiques

**Variation totale (Chambolle).** On cherche l'image débruitée $u$ minimisant

$$ E(u) = \frac{1}{2}\int (u-f)^2\,dx \;+\; \lambda \int |\nabla u|\,dx, $$

où $f$ est l'image bruitée et $\lambda$ = `strength` (`weight`). Le terme de variation totale
pénalise les fortes variations locales tout en tolérant les discontinuités nettes (contrairement
à un flou gaussien) — d'où un lissage qui préserve les contours mais peut produire un effet
« en escalier » sur les dégradés doux.

**Ondelettes (seuillage doux, BayesShrink).** Pour chaque sous-bande de détail $w$, le bruit
$\hat\sigma$ est estimé de façon robuste (écart absolu médian des coefficients de plus fine
échelle) :

$$ \hat\sigma = \frac{\operatorname{MAD}(w_{\text{fine}})}{0.6745}. $$

Le seuil BayesShrink par sous-bande est $T = \hat\sigma^2 / \hat\sigma_X$, où $\hat\sigma_X =
\sqrt{\max(\hat\sigma_Y^2-\hat\sigma^2,\,0)}$ estime l'écart-type du signal utile. Chaque
coefficient est ensuite seuillé en douceur :

$$ \eta(w, T) = \operatorname{sign}(w)\,\max(|w| - T,\; 0). $$

**Filtre bilatéral.** Pour un pixel $p$ de voisinage $\Omega$ :

$$ I'(p) = \frac{1}{W_p} \sum_{q \in \Omega} I(q)\;
   G_{\sigma_s}\!\big(\lVert p-q \rVert\big)\;
   G_{\sigma_r}\!\big(|I(p)-I(q)|\big), $$

avec $G_\sigma(x) = \exp(-x^2/2\sigma^2)$, $\sigma_s$ = `sigma_spatial` (fixé à 3 par le
wrapper) et $\sigma_r$ = `sigma_color` = `strength`. Le facteur de similarité d'intensité
$G_{\sigma_r}$ annule le lissage à travers les forts contrastes, ce qui préserve les bords.

## Paramètres

- **`method`** — *enum*, défaut `tv`, choix : `tv`, `wavelet`, `bilateral`. Algorithme de
  débruitage utilisé.
- **`strength`** — *real*, défaut `0.1`, plage `0`–`2`. Intensité du lissage : poids de la
  variation totale ($\lambda$) pour `tv`, ou `sigma_color` (tolérance aux écarts d'intensité)
  pour `bilateral`.

## Astuces & pièges

> **Attention** — avec `method = wavelet`, le paramètre `strength` **n'a aucun effet** : le
> seuillage est entièrement automatique (bruit estimé par canal, `rescale_sigma=True`). Pour
> un contrôle manuel du seuil, utilisez plutôt `WaveletDenoise` (paramètre `threshold`
> explicite).

> **Note** — en mode `bilateral`, chaque canal est filtré **séparément** : sur une image
> couleur très bruitée, cela peut introduire un léger bruit chromatique résiduel. Préférez `tv`
> ou `wavelet` si la fidélité colorimétrique prime.

- `strength` élevée en `tv` lisse fortement mais aplatit les faibles gradients — surveillez la
  nébulosité ténue et travaillez sous masque d'étoiles si nécessaire.
- Pour un débruitage plus fin et plus lent, préférez `NonLocalMeansDenoise` (préserve mieux les
  étoiles ponctuelles) ou `TGVDenoise` (évite l'effet d'escalier du TV classique).

## Voir aussi

- [TGVDenoise](retina-doc://TGVDenoise) — variation totale généralisée du 2e ordre, sans effet
  d'escalier.
- [WaveletDenoise](retina-doc://WaveletDenoise) — seuillage d'ondelettes avec seuil manuel
  (`k × MAD`).
- [NonLocalMeansDenoise](retina-doc://NonLocalMeansDenoise) — moyenne de patches similaires,
  préserve mieux les structures ponctuelles.
- [ACDNR](retina-doc://ACDNR) — lissage adaptatif protégeant les structures à fort contraste.

## Références

- scikit-image — *skimage.restoration.denoise_tv_chambolle*, *denoise_wavelet*,
  *denoise_bilateral*.
- Chambolle, A. (2004) — *An Algorithm for Total Variation Minimization and Applications*.
- Chang, Yu & Vetterli (2000) — *Adaptive Wavelet Thresholding for Image Denoising*
  (BayesShrink).
- Tomasi & Manduchi (1998) — *Bilateral Filtering for Gray and Color Images*.
