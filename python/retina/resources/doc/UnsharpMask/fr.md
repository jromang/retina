---
id: UnsharpMask
category: Convolution
title: Masque flou
brief: Accentue les détails fins en ajoutant à l'image la différence entre elle-même et sa version floutée.
keywords: [masque flou, unsharp mask, netteté, accentuation, gaussien, contraste local]
related: [GaussianConvolution, Convolution, Deconvolution, MultiscaleLinearTransform]
icon: focus-centered
references:
  - "scikit-image — skimage.filters.unsharp_mask."
  - "PixInsight — UnsharpMask tool reference."
  - "Technique historique de masque flou (photographie argentique et numérique)."
---

## Résumé

`UnsharpMask` accentue les détails fins d'une image en exagérant le contraste local : on
soustrait à l'image une version floutée d'elle-même pour isoler les hautes fréquences (bords,
structures fines), puis on réinjecte ce résidu, amplifié, par-dessus l'image d'origine. C'est la
technique de « masque flou » historique (héritée de la photographie argentique), ici implémentée
par `skimage.filters.unsharp_mask` sur un flou gaussien.

## Cas d'usage

- **Faire ressortir les structures fines** d'une nébuleuse (filaments, dentelles) après un
  étirement, sans retraiter toute l'image.
- **Rehausser la netteté perçue** d'une image légèrement molle issue d'un empilement ou d'un
  échantillonnage.
- **Compléter une déconvolution** : `UnsharpMask` en petite dose affine encore le rendu après
  `Deconvolution` ou `RestorationFilter`.
- **Accentuer les bords planétaires/lunaires** sur des cibles à fort contraste local.

## Fonctionnement

L'opérateur calcule, canal par canal, une version floutée de l'image par convolution gaussienne
de rayon `radius`. La différence entre l'image originale et ce flou constitue le **masque** :
elle ne contient que les hautes fréquences (variations rapides — bords, grain fin, détails).
Ce masque est ensuite multiplié par `amount` puis rajouté à l'image d'origine, ce qui amplifie
localement le contraste aux endroits où l'image varie rapidement, sans toucher aux zones
uniformes (où le masque est proche de zéro). Le résultat est enfin écrêté dans `[0, 1]`.

## Mathématiques

Soit $I$ l'image d'entrée, $r$ = `radius` (l'écart-type $\sigma$ du noyau gaussien utilisé par
scikit-image) et $k$ = `amount`. On calcule d'abord l'image floutée :

$$ B = G_r * I, \qquad G_r(x,y) = \frac{1}{2\pi r^2}\, e^{-\frac{x^2+y^2}{2r^2}} $$

où $*$ est la convolution 2D et $G_r$ un noyau gaussien normalisé de paramètre $r$. Le **masque**
(détail haute fréquence) est la différence :

$$ M = I - B $$

et la sortie est l'image d'origine augmentée du masque amplifié :

$$ I' = \operatorname{clip}\big(I + k \cdot M,\; 0,\; 1\big) = \operatorname{clip}\big((1+k)\,I - k\,B,\; 0,\; 1\big). $$

On reconnaît un filtre passe-haut ajouté à l'identité : plus $k$ est grand, plus le contraste
local est exagéré ; plus $r$ est grand, plus les structures accentuées sont larges (le flou
capture des variations à plus grande échelle, donc le masque contient des détails moins fins).
À $k = 0$, l'opérateur est l'identité.

## Paramètres

- **`radius`** — *real*, défaut `2.0`, plage `0.1`–`50.0`. Écart-type (en pixels) du flou gaussien
  utilisé pour construire le masque. Un rayon petit isole les détails les plus fins (grain,
  bords nets) ; un rayon plus grand accentue des structures plus larges (contraste local à plus
  grande échelle), au risque de créer des halos.
- **`amount`** — *real*, défaut `1.0`, plage `0.0`–`10.0`. Facteur d'amplification du masque
  réinjecté dans l'image. `0` laisse l'image inchangée ; au-delà de `1`-`2`, l'accentuation
  devient vite agressive et fait apparaître du bruit et des halos autour des bords contrastés.

## Astuces & pièges

> **Attention** — le masque flou amplifie **tout** ce qui varie rapidement, y compris le bruit.
> Sur une image bruitée, réduisez le bruit (`NoiseReduction`, `WaveletDenoise`) *avant*
> d'appliquer `UnsharpMask`, ou travaillez sous masque d'étoiles pour épargner le fond de ciel.

- Des `radius` trop petits combinés à un `amount` élevé produisent des halos sombres/clairs
  caractéristiques autour des étoiles et des bords nets — signe qu'il faut réduire l'un des deux.
- Préférez plusieurs passes légères (`amount` modéré) à une seule passe extrême : le résultat est
  plus naturel et plus facile à contrôler visuellement.
- Sur des cibles étendues à faible contraste (nébulosités diffuses), un grand `radius` avec un
  `amount` modéré donne un rehaussement de contraste local plus doux qu'un petit rayon agressif.

## Voir aussi

- [GaussianConvolution](retina-doc://GaussianConvolution) — le flou utilisé en interne pour bâtir le masque.
- [Convolution](retina-doc://Convolution) — convolution générale par noyau personnalisé.
- [Deconvolution](retina-doc://Deconvolution) — restauration de netteté par inversion de la PSF (complémentaire).
- [MultiscaleLinearTransform](retina-doc://MultiscaleLinearTransform) — accentuation sélective par échelle (ondelettes).

## Références

- scikit-image — *skimage.filters.unsharp_mask*.
- PixInsight — *UnsharpMask* tool reference.
- Technique historique de masque flou (photographie argentique et numérique).
