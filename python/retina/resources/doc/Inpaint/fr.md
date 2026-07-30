---
id: Inpaint
category: Painting
title: Comblement par inpainting
brief: "Comble une carte de défauts ou les trous laissés par un retrait d'étoiles en propageant les gradients voisins (OpenCV Telea/Navier-Stokes)."
keywords: [inpainting, retrait d'étoiles, défauts, Telea, Navier-Stokes, comblement, masque]
related: [StarRemoval, DefectMap, CloneStamp, SeamlessClone]
icon: eraser
references:
  - "Telea, A. — An Image Inpainting Technique Based on the Fast Marching Method, 2004."
  - "Bertalmio, M., Bertozzi, A., Sapiro, G. — Navier-Stokes, Fluid Dynamics, and Image and Video Inpainting, 2001."
  - "OpenCV — cv::inpaint (module photo)."
---

## Résumé

`Inpaint` reconstruit une région désignée de l'image en **propageant l'information des pixels
sains environnants** vers l'intérieur de la zone à combler, plutôt que d'en faire une simple
moyenne locale. Il s'appuie sur les deux algorithmes d'inpainting d'OpenCV — **Telea** (marche
rapide guidée par les isophotes) et **Navier-Stokes** (diffusion inspirée de la dynamique des
fluides) — nettement plus naturels qu'un filtre médian ou un remplissage par interpolation
simple, en particulier sur fond structuré (nébulosité, dégradé de fond de ciel).

## Cas d'usage

- **Combler les trous laissés par `StarRemoval`** : les étoiles retirées laissent des disques
  sombres ou vides que `Inpaint` referme en poursuivant les structures de fond.
- **Effacer des artefacts ponctuels** : pixels chauds résiduels, traînée de satellite courte,
  poussière de capteur, à partir d'une **carte de défauts** (voir `DefectMap`).
- **Réparer une zone abîmée** après un montage ou une mosaïque partielle, en alternative
  scriptable au geste manuel de `CloneStamp`/`SeamlessClone`.
- **Prétraiter avant analyse** (détection de sources, mesure de PSF) pour éviter qu'un défaut
  ponctuel ne pollue les statistiques locales.

## Fonctionnement

Le process détermine d'abord un **masque binaire** des pixels à reconstruire :

1. Si `mask_path` pointe vers un fichier, celui-ci est chargé (canal rouge si couleur) et tout
   pixel **non nul** désigne une zone à combler.
2. Sinon, le masque est dérivé directement de l'image : la **luminance** (moyenne des canaux,
   ou canal unique en niveaux de gris) est comparée à `zero_threshold` — tout pixel à ou en
   dessous du seuil est considéré comme un « trou » (cas typique des étoiles retirées, dont le
   disque est mis à zéro en amont).

Si aucun pixel n'est sélectionné, l'image est renvoyée inchangée. Sinon, chaque canal est
converti en 8 bits et passé à `cv2.inpaint`, qui reconstruit la zone masquée par propagation
depuis sa frontière, avec un rayon de voisinage `radius` et une méthode (`telea` ou `ns`) — le
résultat est reconverti en float32 `[0,1]`.

## Mathématiques

**Méthode Telea (Fast Marching Method).** Les pixels de la frontière du trou sont traités en
premier, puis on avance vers l'intérieur en suivant l'ordre croissant d'une carte de temps
d'arrivée $T$ calculée par marche rapide (FMM). Pour un pixel $p$ à reconstruire, la valeur est
une moyenne pondérée des pixels connus $q$ de son voisinage de rayon `radius` :

$$
I(p) = \frac{\displaystyle\sum_{q \,\in\, B_r(p)\,\cap\,\text{connu}} w(p,q)\,
\big[\,I(q) + \nabla I(q)\cdot(p-q)\,\big]}
{\displaystyle\sum_{q \,\in\, B_r(p)\,\cap\,\text{connu}} w(p,q)}
$$

où le poids combine trois facteurs — direction, distance et niveau d'arrivée :

$$
w(p,q) = \operatorname{dir}(p,q)\cdot\operatorname{dst}(p,q)\cdot\operatorname{lev}(p,q),
\qquad
\operatorname{dir}(p,q) = \frac{(p-q)\cdot N(p)}{\lVert p-q\rVert},\quad
\operatorname{dst}(p,q) = \frac{1}{\lVert p-q\rVert^{2}},\quad
\operatorname{lev}(p,q) = \frac{1}{1+\lvert T(p)-T(q)\rvert}.
$$

Le terme $\nabla I(q)\cdot(p-q)$ prolonge localement l'**isophote** (ligne d'iso-intensité) de
$q$ vers $p$, ce qui donne une reconstruction qui suit les gradients existants plutôt qu'un
simple aplat.

**Méthode Navier-Stokes.** Le trou est comblé en résolvant itérativement une équation de
transport qui traite le Laplacien de l'image $\omega = \Delta I$ comme une **vorticité** au sens
de la mécanique des fluides, transportée le long des isophotes :

$$ \frac{\partial I}{\partial t} = \nabla^{\perp}\omega \cdot \nabla I, $$

alternée avec des étapes de **diffusion anisotrope** qui lissent le résultat tout en respectant
les bords, jusqu'à convergence sur la zone masquée. Cette approche est en général plus lisse
mais légèrement plus coûteuse que Telea sur de grandes zones.

## Paramètres

- **`mask_path`** — *path*, défaut `""`. Chemin d'une image servant de carte de masque ; tout
  pixel non nul (canal rouge si couleur) désigne une zone à combler. Vide = masque dérivé de
  `zero_threshold`.
- **`zero_threshold`** — *real*, défaut `0.0`, plage `0`–`1`. Seuil de luminance en dessous
  duquel (inclus) un pixel est considéré comme un trou, utilisé uniquement si `mask_path` est
  vide (cas typique : trous laissés à zéro par un retrait d'étoiles).
- **`radius`** — *int*, défaut `3`, plage `1`–`30`. Rayon (en pixels) du voisinage de pixels
  connus pris en compte pour reconstruire chaque pixel du trou.
- **`method`** — *enum*, défaut `telea`, choix `telea` / `ns`. Algorithme d'inpainting : Telea
  (marche rapide, rapide et net) ou Navier-Stokes (diffusion fluide, plus lisse).

## Astuces & pièges

> **Attention** — sur de **grandes zones** à combler, l'inpainting invente une texture plausible
> mais **non réelle** : il ne « redécouvre » jamais un signal astronomique perdu. Réservez-le aux
> petits défauts (étoiles ponctuelles, artefacts) et documentez son usage si l'image est publiée.

> **Note** — le traitement se fait canal par canal indépendamment ; sur une image couleur avec
> un fort déséquilibre RGB local (halo chromatique autour d'une étoile retirée), un léger
> artefact de teinte peut subsister au centre du disque comblé.

- Un `radius` trop grand lisse excessivement et peut faire « baver » le fond structuré dans le
  trou ; commencez petit (2–4) et n'augmentez que si des franges résiduelles subsistent.
- Pour combler des centaines d'étoiles retirées d'un coup, préférez un masque unique cumulant
  tous les disques plutôt que d'appeler le process pixel par pixel.
- `ns` donne souvent un résultat plus doux sur fond de nébulosité étendue ; `telea` est plus
  fidèle sur des bords nets (jonctions de mosaïque, artefacts rectangulaires).

## Voir aussi

- [StarRemoval](retina-doc://StarRemoval) — retire les étoiles et fournit typiquement les trous à combler.
- [DefectMap](retina-doc://DefectMap) — construit une carte de défauts réutilisable comme `mask_path`.
- [CloneStamp](retina-doc://CloneStamp) — retouche manuelle par copie de disque, alternative dirigée.
- [SeamlessClone](retina-doc://SeamlessClone) — clonage à fondu de Poisson pour les grandes zones.

## Références

- Telea, A. — *An Image Inpainting Technique Based on the Fast Marching Method*, 2004.
- Bertalmio, M., Bertozzi, A., Sapiro, G. — *Navier-Stokes, Fluid Dynamics, and Image and Video Inpainting*, 2001.
- OpenCV — *cv::inpaint* (module photo).
