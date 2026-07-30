---
id: RickerWaveletEnhance
category: MultiscaleProcessing
title: Rehaussement en ondelette de Ricker
brief: "Rehausse les structures d'une échelle donnée (nébulosités, filaments) via un noyau chapeau mexicain (Ricker/Marr)."
keywords: [ondelette, Ricker, Marr, chapeau mexicain, multi-échelle, rehaussement, filaments, nébulosité]
related: [MultiscaleLinearTransform, UnsharpMask, WaveletTransform, LocalHistogramEqualization]
icon: wave-sine
references:
  - "astropy.convolution — RickerWavelet2DKernel / RickerWavelet2D model."
  - "Marr, D. & Hildreth, E. (1980) — Theory of edge detection (Laplacien de Gaussienne / chapeau mexicain)."
  - "PixInsight — ATrousWaveletTransform (filtrage par échelle, principe apparenté)."
---

## Résumé

`RickerWaveletEnhance` accentue les structures dont la taille correspond à une **échelle
unique**, réglée par `width`, en convoluant chaque canal avec un noyau **Ricker (« chapeau
mexicain »)**, aussi appelé Laplacien de Gaussienne. Contrairement à un flou ou un filtre
passe-haut classique, ce noyau est **passe-bande** : il répond fortement aux structures dont
la taille est proche de `width`, et s'annule aussi bien sur le fond uniforme que sur le bruit
très fin. C'est un outil rapide pour faire ressortir nébulosités diffuses et filaments sans
disposer de la pile complète d'échelles d'une transformée en ondelettes.

## Cas d'usage

- **Révéler des filaments ou de la nébulosité faible** noyés dans un fond de ciel bruité, en
  ciblant leur taille caractéristique via `width`.
- **Alternative légère à `MultiscaleLinearTransform`** quand on ne veut agir que sur une seule
  échelle, sans décomposer/recomposer toute la pile de détails.
- **Rehaussement local de contraste** sur des structures étendues (nuages moléculaires, restes
  de supernova) sans amplifier le grain pixel-à-pixel comme le ferait `UnsharpMask` à faible
  rayon.
- **Exploration** : balayer `width` pour identifier visuellement l'échelle où une structure
  d'intérêt ressort le mieux, avant d'affiner avec un outil multi-échelle complet.

## Fonctionnement

Pour chaque canal de couleur, l'opérateur :

1. Construit un noyau 2D de Ricker (`astropy.convolution.RickerWavelet2DKernel`) de largeur
   `width`, de taille par défaut $\lfloor 8\cdot\text{width} + 1\rfloor$ pixels.
2. Convolue l'image avec ce noyau **sans renormalisation** (`normalize_kernel=False`) : comme
   le noyau a une intégrale quasi nulle, la convolution produit une **carte de détail** centrée
   sur zéro — positive sur les structures de la bonne taille, proche de zéro sur le fond plat
   et sur le bruit trop fin par rapport à `width`.
3. Ajoute cette carte de détail à l'image d'origine, pondérée par `amount`, puis écrête le
   résultat dans `[0, 1]`.

Le noyau étant radialement symétrique et à somme nulle, les zones de fond uniforme ne sont
quasiment pas affectées : seul le contraste des structures dont la taille avoisine `width`
est amplifié, ce qui distingue ce process d'un simple filtre passe-haut ou d'un accentuateur
de netteté à large bande.

## Mathématiques

Le noyau de Ricker (Laplacien de Gaussienne normalisé) en 2D, de paramètre d'échelle
$\sigma = \texttt{width}$, s'écrit en fonction du rayon $r = \sqrt{x^2+y^2}$ depuis le centre :

$$ \psi_\sigma(x, y) = \frac{1}{\pi \sigma^4}\left(1 - \frac{r^2}{2\sigma^2}\right)
   \exp\!\left(-\frac{r^2}{2\sigma^2}\right) $$

C'est la dérivée seconde (Laplacien) d'une gaussienne normalisée, à un facteur près : positif
au centre, négatif dans un anneau environnant, et d'intégrale nulle sur le plan
($\int\!\!\int \psi_\sigma = 0$). Cette propriété en fait un **filtre passe-bande** : sa
réponse en fréquence spatiale s'annule à la fois en très basse fréquence (fond uniforme,
gradients lents) et en très haute fréquence (bruit à l'échelle du pixel), avec un maximum
autour de la fréquence associée à $\sigma$.

La carte de détail est la convolution de l'image $I$ par ce noyau :

$$ D(x,y) = (I * \psi_\sigma)(x,y) $$

et le résultat final, par canal, est :

$$ I'(x,y) = \operatorname{clip}\big(I(x,y) + a \cdot D(x,y),\; 0,\; 1\big), \qquad a = \texttt{amount} $$

Augmenter `amount` amplifie le contraste des structures à l'échelle $\sigma$ ; augmenter
`width` déplace la bande de fréquences ciblée vers des structures plus larges (au prix d'un
noyau — et donc d'un temps de calcul — croissant en $\sigma^2$).

## Paramètres

- **`width`** — *real*, défaut `2.0`, plage `0.5`–`50`. Largeur d'échelle (σ) du noyau de
  Ricker, en pixels : fixe la taille des structures rehaussées. Petite valeur → détails fins
  (filaments serrés) ; grande valeur → structures étendues (nappes de nébulosité), avec un
  noyau plus grand et plus coûteux à convoluer.
- **`amount`** — *real*, défaut `1.0`, plage `0`–`10`. Poids d'ajout de la carte de détail à
  l'image d'origine. `0` = aucun effet ; au-delà de `1` l'accentuation devient agressive et
  peut faire apparaître des halos ou des artefacts en anneau autour des structures.

## Astuces & pièges

> **Attention** — un `amount` trop élevé combiné à un `width` petit produit des **anneaux**
> (ringing) autour des étoiles et des bords contrastés, signature typique du Laplacien de
> Gaussienne. Réduisez `amount` ou protégez les étoiles avec un masque avant d'appliquer un
> rehaussement fort.

- Le noyau grandit avec `width` (taille ≈ $8\sigma+1$) : sur de grandes images, des valeurs
  élevées de `width` peuvent ralentir sensiblement le traitement.
- Comme la réponse s'annule sur le bruit fin, ce process amplifie moins le grain que
  `UnsharpMask` à faible rayon — préférez-le quand le bruit du fond de ciel devient visible
  après accentuation.
- Pour rehausser plusieurs échelles simultanément (et pas une seule bande), utilisez plutôt
  `MultiscaleLinearTransform` ou `WaveletTransform`, qui décomposent l'image en une pile
  complète de couches.
- Travaillez de préférence sur une image déjà étirée ou proche de l'étirement final : sur des
  données linéaires très sombres, l'effet visuel de `amount` est difficile à juger.

## Voir aussi

- [MultiscaleLinearTransform](retina-doc://MultiscaleLinearTransform) — décomposition
  complète en ondelettes starlet, rehaussement multi-couches.
- [WaveletTransform](retina-doc://WaveletTransform) — transformée en ondelettes générale.
- [UnsharpMask](retina-doc://UnsharpMask) — accentuation de netteté classique par soustraction
  d'un flou gaussien.
- [LocalHistogramEqualization](retina-doc://LocalHistogramEqualization) — rehaussement de
  contraste local par égalisation adaptative (CLAHE).

## Références

- astropy.convolution — *RickerWavelet2DKernel* / *RickerWavelet2D* model.
- Marr, D. & Hildreth, E. (1980) — *Theory of edge detection* (Laplacien de Gaussienne / chapeau mexicain).
- PixInsight — *ATrousWaveletTransform* (filtrage par échelle, principe apparenté).
