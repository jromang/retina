---
id: MosaicReproject
category: ImageIntegration
title: Mosaïque par reprojection WCS
brief: Reprojette et co-additionne plusieurs FITS plate-solvés sur une grille céleste commune pour bâtir une mosaïque astrométrique.
keywords: [mosaïque, reprojection, WCS, astrométrie, plate-solve, champ étendu, reproject]
related: [PlateSolve, GradientMergeMosaic, Integration, Annotation]
icon: grid-4x4
references:
  - "reproject (astropy-affiliated) — mosaicking.reproject_and_coadd / find_optimal_celestial_wcs."
  - "astropy.wcs — World Coordinate System pour FITS."
  - "PixInsight — pratique de mosaïquage par recalage astrométrique (WCS)."
---

## Résumé

`MosaicReproject` assemble plusieurs images **plate-solvées** (chacune porte un WCS FITS
valide dans son en-tête) en une **mosaïque astrométrique unique**. Contrairement aux fusions
par gradient qui recalent les images entre elles par corrélation de contenu, ici c'est le
**ciel lui-même qui sert de référentiel** : chaque frame est reprojetée sur une grille céleste
commune calculée automatiquement, puis les recouvrements sont co-additionnés. C'est un process
**global** : il ne s'applique pas à une vue active mais lit une liste de fichiers et produit
une **nouvelle fenêtre** (`new_image_id`).

## Cas d'usage

- **Assembler un grand champ** (nébuleuse étendue, région de la Voie lactée) à partir de
  plusieurs tuiles (« tiles ») acquises séparément et plate-solvées individuellement.
- **Combiner des sessions à échelles ou orientations différentes** (foyers/capteurs distincts) :
  la reprojection sur un WCS commun gère nativement les rotations et changements d'échelle.
- **Réunir des acquisitions non contiguës dans le temps** (nuits différentes) sans dépendre
  d'un recalage par étoiles — seule l'astrométrie WCS compte.

## Fonctionnement

1. Chaque fichier de `frames` est ouvert avec `astropy.io.fits` ; le premier HDU contenant des
   données est retenu, ainsi que son WCS **céleste** (`WCS(header).celestial`, RA/Dec, ignorant
   d'éventuels axes non spatiaux).
2. `reproject.mosaicking.find_optimal_celestial_wcs` calcule, à partir de l'ensemble des WCS et
   footprints d'entrée, un **WCS de sortie optimal** ainsi que la forme de grille (`shape_out`)
   couvrant l'union de tous les champs, avec une échelle de pixel cohérente.
3. Pour chaque canal (0 en mono, jusqu'à 3 en RGB — les frames mono sont répétées sur le dernier
   canal disponible si le nombre de canaux diffère), `reproject.mosaicking.reproject_and_coadd`
   reprojette chaque frame sur la grille commune par **interpolation** (`reproject_interp`) et
   **co-additionne** les recouvrements selon `combine` (`mean` ou `sum`).
4. Les zones non couvertes par aucune frame produisent des `NaN`, remplacés par 0
   (`np.nan_to_num`). Le résultat est empilé en `(H, W, C)`, écrêté dans `[0, 1]`, et publié
   dans une nouvelle fenêtre via `app.new_window`.

> **Note** — le WCS céleste est extrait uniquement du **canal 0** de chaque frame ; pour une
> mosaïque couleur, on suppose implicitement que tous les canaux d'une même frame partagent la
> même astrométrie (cas standard d'une image RVB alignée en interne).

## Mathématiques

Soit $I_i$ l'image de la frame $i$ munie de son WCS $W_i$ (transformation pixel → coordonnées
célestes RA/Dec), et $W_\text{out}$ le WCS de sortie sur la grille commune. Pour chaque pixel
$(x, y)$ de la grille de sortie, la reprojection par interpolation calcule la coordonnée céleste
correspondante $W_\text{out}(x,y)$, la convertit en coordonnées pixel de la frame $i$ via
$W_i^{-1}$, puis interpole $I_i$ à cette position :

$$ \hat I_i(x,y) = I_i\big(W_i^{-1}(W_\text{out}(x,y))\big), $$

accompagnée d'une **empreinte de couverture** (footprint) $F_i(x,y) \in \{0,1\}$ qui vaut 1 si
$(x,y)$ tombe à l'intérieur du champ de la frame $i$, 0 sinon (les régions hors champ ne sont
pas extrapolées).

Sur les recouvrements, la co-addition combine les frames couvrant chaque pixel,
$K(x,y) = \{\, i : F_i(x,y) = 1 \,\}$, selon `combine` :

$$
M(x,y) =
\begin{cases}
\dfrac{1}{|K(x,y)|} \displaystyle\sum_{i \in K(x,y)} \hat I_i(x,y) & \text{si } \texttt{combine = mean} \\[10pt]
\displaystyle\sum_{i \in K(x,y)} \hat I_i(x,y) & \text{si } \texttt{combine = sum}
\end{cases}
$$

Si $K(x,y) = \varnothing$ (aucune frame ne couvre ce pixel), la valeur est indéfinie ($\mathrm{NaN}$)
et remplacée par 0 en sortie. Le mode `mean` préserve l'échelle photométrique d'origine (utile
pour une mosaïque directement affichable) ; le mode `sum` accumule le signal des recouvrements
(utile si l'on ré-intègre ensuite la mosaïque dans un pipeline de calibration de flux).

## Paramètres

- **`frames`** — *pathlist*, défaut `[]`. Liste des fichiers FITS plate-solvés à assembler.
  Chaque fichier doit contenir un WCS valide dans son en-tête (voir `PlateSolve`).
- **`combine`** — *enum*, défaut `mean`, choix : `mean`, `sum`. Mode de combinaison des pixels
  recouverts par plusieurs frames : moyenne (photométrie préservée) ou somme (accumulation).
- **`new_image_id`** — *str*, défaut `mosaic`. Identifiant de la fenêtre résultat créée.

## Astuces & pièges

> **Attention** — toutes les frames doivent être **plate-solvées au préalable** (`PlateSolve`) :
> sans WCS exploitable dans l'en-tête, la reprojection échoue ou produit un WCS incohérent.
> Un WCS approximatif (mauvaise échelle ou rotation) se traduit par des jonctions visiblement
> décalées entre tuiles.

- La grille de sortie est calculée automatiquement pour couvrir **toutes** les frames ; une
  frame très excentrée par rapport aux autres peut faire exploser la taille de l'image finale.
- Les zones de recouvrement gagnent en SNR (surtout en mode `mean`), tandis que les bords de
  chaque tuile (couverts par une seule frame) restent au niveau de bruit d'origine — les
  jonctions peuvent rester visibles si l'exposition ou le fond de ciel diffère fortement entre
  sessions ; envisagez `BackgroundExtraction`/`GradientCorrection` en amont sur chaque tuile.
- Pour des champs non résolus astrométriquement (pas de WCS fiable), préférez un recalage par
  contenu avec `GradientMergeMosaic`.

## Voir aussi

- [PlateSolve](retina-doc://PlateSolve) — calcule le WCS nécessaire en amont de la mosaïque.
- [GradientMergeMosaic](retina-doc://GradientMergeMosaic) — mosaïquage par fusion de gradients, sans WCS.
- [Integration](retina-doc://Integration) — empilement multi-frames avec rejet robuste (champ identique).
- [Annotation](retina-doc://Annotation) — superposition d'une grille RA/Dec sur la mosaïque obtenue.

## Références

- reproject (astropy-affiliated) — *mosaicking.reproject_and_coadd* / *find_optimal_celestial_wcs*.
- astropy.wcs — World Coordinate System pour FITS.
- PixInsight — pratique de mosaïquage par recalage astrométrique (WCS).
