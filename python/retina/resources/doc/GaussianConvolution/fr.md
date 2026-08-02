---
id: GaussianConvolution
category: Convolution
title: Convolution gaussienne
brief: Lisse une image par convolution séparable avec un noyau gaussien (flou gaussien), opérateur natif Rust.
keywords: [convolution, flou gaussien, lissage, sigma, débruitage, noyau séparable]
related: [Convolution, UnsharpMask, Deconvolution, NoiseReduction]
icon: focus-2
references:
  - "Gonzalez, R. C. & Woods, R. E. — Digital Image Processing, ch. Spatial Filtering."
  - "PixInsight — Convolution tool reference."
---

## Résumé

`GaussianConvolution` applique un **flou gaussien** à l'image : chaque pixel est remplacé par
une moyenne pondérée de son voisinage, les poids suivant une courbe gaussienne dont la largeur
est fixée par `sigma`. C'est l'opérateur de lissage le plus fondamental du catalogue — premier
process du projet à avoir été porté en Rust natif (`retina._core`), il sert de référence pour le
motif « opérateur compilé relâchant le GIL » décrit dans `CLAUDE.md`.

![Avant — GaussianConvolution](figures/before.webp)
![Après — GaussianConvolution](figures/after.webp)

*Avant, et après un flou gaussien de σ = 3 — le lissage de référence.*

## Cas d'usage

- **Adoucir le bruit** avant une opération sensible aux hautes fréquences (mesure de FWHM,
  détection de sources) sans introduire d'artefacts en anneaux.
- **Préparer un masque flou** : convolué à grand `sigma`, un masque binaire (étoiles, fond)
  obtient des transitions douces qui évitent les coutures visibles.
- **Simuler/estimer un PSF gaussien** pour des tests de déconvolution (`Deconvolution`) ou pour
  construire le complément « haute fréquence » utilisé par `UnsharpMask`.
- **Réduire légèrement le grain** d'une image déjà étirée, en dernière retouche cosmétique.

## Fonctionnement

Le noyau gaussien 2D est **séparable** : au lieu de convoluer avec un noyau carré coûteux en
$O(n^2)$ opérations par pixel, l'implémentation applique successivement deux convolutions 1D — une
horizontale puis une verticale — chacune en $O(n)$, avec un résultat strictement identique.

1. Un noyau 1D discret est échantillonné à partir de la gaussienne continue, normalisé pour que
   la somme des poids vale 1 (préserve la luminosité moyenne). Son rayon est fixé à
   $\lceil 3\sigma \rceil$ pixels de chaque côté du centre — au-delà, la contribution gaussienne
   est négligeable.
2. Le noyau est convolué le long de l'axe horizontal, canal par canal, avec un **bord réfléchi**
   (miroir) pour éviter tout assombrissement artificiel près des bords de l'image.
3. Le résultat intermédiaire subit la même convolution le long de l'axe vertical.
4. Si `sigma <= 0`, l'image est retournée inchangée (copie), sans calcul.

Le calcul est effectué par le crate `retina_core` (Rust/PyO3, parallélisé avec `rayon`, GIL
relâché via `allow_threads`) ; en l'absence du binaire natif, `backend.gaussian_convolve` retombe
automatiquement sur `scipy.ndimage.gaussian_filter`, puis sur une implémentation numpy pure — la
sortie est numériquement équivalente dans les trois cas.

## Mathématiques

Le noyau gaussien continu 1D de largeur $\sigma$ est :

$$ g_\sigma(x) = \frac{1}{\sqrt{2\pi}\,\sigma} \, \exp\!\left(-\frac{x^2}{2\sigma^2}\right). $$

L'implémentation échantillonne sa version discrète et normalisée sur un rayon
$r = \lceil 3\sigma \rceil$ :

$$ k[i] = \frac{\exp\!\left(-\dfrac{i^2}{2\sigma^2}\right)}{\displaystyle\sum_{j=-r}^{r} \exp\!\left(-\dfrac{j^2}{2\sigma^2}\right)}, \qquad i = -r, \dots, r. $$

Grâce à la **séparabilité** de la gaussienne 2D, $g_\sigma(x,y) = g_\sigma(x)\,g_\sigma(y)$, la
convolution complète s'obtient en deux passes 1D successives, pour chaque canal $c$ :

$$ I'(x,y,c) = \sum_{j=-r}^{r} k[j] \left( \sum_{i=-r}^{r} k[i]\, I(x+i,\, y+j,\, c) \right). $$

Les indices hors image sont repliés par réflexion de bord ($x \mapsto -x-1$ ou $x \mapsto 2n-x-1$)
plutôt que d'être mis à zéro, ce qui évite l'assombrissement typique des convolutions à bord nul.
Le paramètre `sigma` contrôle directement l'**écart-type spatial** du flou : la fréquence de
coupure effective du filtre passe-bas décroît comme $1/\sigma$ — plus `sigma` est grand, plus le
lissage gomme de détails fins.

## Paramètres

- **`sigma`** — *real*, défaut `2.0`, plage `0.0`–`50.0`. Écart-type du noyau gaussien, en pixels.
  Une valeur de `0` désactive tout lissage (image inchangée). Des valeurs faibles (`0.5`–`2`)
  atténuent le bruit fin ; des valeurs élevées (`10`+) produisent un flou marqué, utile pour des
  masques ou des estimations de fond très lisses.

## Astuces & pièges

> **Attention** — un `sigma` trop élevé sur l'image principale efface des détails fins
> irrémédiablement (étoiles faibles, structures nébuleuses ténues). Préférez travailler sous
> masque ou sur une copie/preview pour juger le compromis lissage/perte de signal.

- Le coût de calcul croît avec `sigma` (rayon du noyau $\propto \sigma$) mais reste linéaire par
  pixel grâce à la séparabilité — inutile de limiter artificiellement `sigma` par peur de la
  complexité quadratique d'un noyau 2D plein.
- Pour un flou plus rapide et moins précis (approximation par boîte) ou un rehaussement de
  contours (laplacien), voir le process générique `Convolution`, qui partage la même catégorie
  mais s'appuie sur `scipy.ndimage`.
- Ne pas confondre avec `NoiseReduction`, qui vise à préserver les contours (filtrage adaptatif)
  là où `GaussianConvolution` lisse uniformément, contours compris.

## Voir aussi

- [Convolution](retina-doc://Convolution) — filtre générique (gaussien/boîte/laplacien) via scipy.
- [UnsharpMask](retina-doc://UnsharpMask) — rehaussement de netteté basé sur un flou gaussien.
- [Deconvolution](retina-doc://Deconvolution) — inversion d'un flou (PSF) plutôt que son application.
- [NoiseReduction](retina-doc://NoiseReduction) — débruitage préservant les contours.

## Références

- Gonzalez, R. C. & Woods, R. E. — *Digital Image Processing*, chapitre sur le filtrage spatial.
- PixInsight — *Convolution* tool reference.
