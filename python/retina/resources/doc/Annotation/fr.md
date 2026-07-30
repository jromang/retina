---
id: Annotation
category: Astrometry
title: Annotation
brief: Trace une grille de coordonnées célestes (RA/Dec) sur l'image à partir de sa solution WCS.
keywords: [astrométrie, WCS, grille, RA/Dec, coordonnées célestes, plate-solving]
related: [PlateSolve, CatalogAnnotation, GaiaCatalog]
icon: tag
references:
  - "PixInsight — AnnotateImage script reference."
  - "astropy.wcs — World Coordinate System transformations."
  - "FITS WCS Paper II (Calabretta & Greisen, 2002)."
---

## Résumé

`Annotation` superpose à l'image une **grille de coordonnées équatoriales** (ascension droite et
déclinaison) calculée à partir de la solution astrométrique (WCS) de la fenêtre. C'est l'équivalent
du volet « grille » du script `AnnotateImage` de PixInsight : une fois le champ résolu par
`PlateSolve`, cette grille permet de vérifier visuellement l'orientation, l'échelle et la validité
du recalage astrométrique, ou simplement d'habiller une image pour publication.

## Cas d'usage

- **Vérifier une solution astrométrique** : une grille cohérente (lignes régulières, non tordues)
  confirme que le WCS calculé par `PlateSolve` est correct.
- **Repérer l'orientation du champ** (nord/est) avant une composition mosaïque ou une comparaison
  entre sessions.
- **Illustrer une image publiée** avec des repères de coordonnées, à la manière des cartes du ciel.
- **Diagnostiquer une distorsion** : une grille visiblement courbe ou irrégulière trahit un WCS mal
  résolu ou un champ avec forte distorsion optique non modélisée.

## Fonctionnement

Le process exige un WCS déjà présent sur la fenêtre (`window.wcs`), posé par `PlateSolve` — sans
solution astrométrique, il échoue explicitement plutôt que d'improviser une grille arbitraire.

1. Pour **chaque pixel** de l'image, les coordonnées image `(x, y)` sont converties en coordonnées
   célestes `(RA, Dec)` via `wcs.pixel_to_world`, produisant deux cartes `ra(x,y)` et `dec(x,y)` de
   la taille de l'image.
2. Pour chacune des deux cartes, on teste la proximité au multiple le plus proche du **pas de
   grille** `grid_spacing` : les pixels dont RA (ou Dec) tombe à moins de `line_width` du pas
   forment les lignes de la grille.
3. L'image est convertie en couleur si nécessaire (les images mono sont dupliquées sur 3 canaux),
   puis les pixels marqués sont peints en **vert pur** `(0, 1, 0)`.
4. L'opération est **destructive** : elle réécrit les pixels et s'inscrit dans l'historique de la
   vue (`begin_process`/`end_process`), contrairement à une grille d'affichage superposée en overlay.

## Mathématiques

Soit $W$ la transformation WCS pixel → ciel de la fenêtre. Pour chaque pixel $(x, y)$ :

$$ (\alpha, \delta) = W(x, y) $$

où $\alpha$ est l'ascension droite et $\delta$ la déclinaison, en degrés. Pour une coordonnée
$c \in \{\alpha, \delta\}$ et un pas $g$ = `grid_spacing`, on définit l'écart réduit au multiple de
$g$ le plus proche :

$$ f(c) = \left| \frac{c}{g} - \operatorname{round}\!\left(\frac{c}{g}\right) \right| $$

$f(c)$ vaut $0$ exactement sur les méridiens/parallèles multiples de $g$, et croît linéairement
jusqu'à $0{,}5$ à mi-chemin entre deux lignes. Un pixel appartient à la grille si l'une des deux
coordonnées est suffisamment proche d'une ligne, avec $\ell$ = `line_width` :

$$ \text{grille}(x, y) = \big[\, f(\alpha(x,y)) < \ell \,\big] \;\lor\; \big[\, f(\delta(x,y)) < \ell \,\big] $$

Ce test produit un motif périodique de période $g$ dans chaque direction céleste — l'équivalent
d'une fonction en dents de scie seuillée. L'épaisseur apparente des lignes sur l'image dépend donc
à la fois de `line_width` et de l'échelle locale (arcsec/pixel), qui varie avec la déclinaison
(convergence des méridiens vers les pôles) et la projection utilisée par le WCS.

## Paramètres

- **`grid_spacing`** — *real*, défaut `0.5`, plage `0.001`–`90.0`. Pas de la grille en degrés,
  appliqué identiquement en RA et en Dec. Réduire pour un champ étroit (amas, galaxie), augmenter
  pour un grand champ (voie lactée, mosaïque).
- **`line_width`** — *real*, défaut `0.02`, plage `0.001`–`0.2`. Épaisseur des lignes, exprimée en
  **fraction du pas de grille** (pas en pixels). Une valeur trop grande fait fusionner les lignes
  voisines ou envahir l'image.

## Astuces & pièges

> **Attention** — `Annotation` **modifie les pixels** (grille peinte en dur, en vert). Travaillez
> sur une copie de la fenêtre, ou appliquez ce process en fin de traitement, après l'étirement final.

> **Note** — sans WCS valide sur la fenêtre, le process lève une erreur explicite. Exécutez
> `PlateSolve` au préalable ; une résolution imprécise se traduira par une grille visiblement décalée
> ou déformée.

- Près des pôles célestes, la convergence des méridiens en RA fait apparaître des lignes RA très
  rapprochées : réduisez `grid_spacing` avec prudence sur ces champs.
- Pour un repérage d'objets nommés (étoiles, catalogue) plutôt qu'une simple grille de coordonnées,
  utilisez `CatalogAnnotation`.

## Voir aussi

- [PlateSolve](retina-doc://PlateSolve) — calcule la solution astrométrique (WCS) préalable requise.
- [CatalogAnnotation](retina-doc://CatalogAnnotation) — superpose des objets d'un catalogue (Gaia) plutôt qu'une grille.
- [GaiaCatalog](retina-doc://GaiaCatalog) — interrogation directe du catalogue Gaia sur le champ.

## Références

- PixInsight — *AnnotateImage* script reference.
- astropy.wcs — *World Coordinate System* transformations.
- FITS WCS Paper II (Calabretta & Greisen, 2002).
