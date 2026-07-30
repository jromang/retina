---
id: FWHMEccentricity
category: ImageInspection
title: Carte de FWHM et d'excentricité
brief: Mesure la FWHM et l'excentricité des étoiles cellule par cellule, et dessine la carte du champ.
keywords: [FWHM, excentricité, mise au point, collimation, tilt, suivi, qualité optique, carte de champ]
related: [DynamicPSF, AberrationInspector, SubframeSelector, Deconvolution]
icon: grid-dots
references:
  - "PixInsight — script FWHMEccentricity."
---

## Résumé

Une médiane de FWHM ne dit pas grand-chose : une image peut être excellente au centre et molle
dans un coin, et c'est précisément ce qu'on veut savoir. `FWHMEccentricity` découpe donc le
champ en `grid` × `grid` cellules et rend, pour chacune, la médiane de ses étoiles — puis
dessine la carte dans le viewport.

L'**excentricité** est plus parlante encore que la FWHM. Elle trahit deux défauts qu'on
confond souvent :

- un allongement dans une **direction commune** à tout le champ, c'est le **suivi** (dérive,
  vent, erreur périodique) ;
- un allongement **radial**, faible au centre et croissant vers les bords, c'est l'**optique** —
  tilt du capteur, courbure de champ, coma.

D'où les ellipses dessinées à l'orientation mesurée : une carte de nombres ne montrerait pas la
direction, qui est l'essentiel du diagnostic.

## Cas d'usage

- **Vérifier une mise au point** avant de lancer une nuit d'acquisition.
- **Diagnostiquer un tilt** de capteur ou de porte-oculaire : la carte le rend évident en une
  exécution, là où comparer quatre coins au zoom demande de se souvenir de ce qu'on vient de voir.
- **Choisir `psf_sigma`** pour la [déconvolution](retina-doc://Deconvolution) — mais dans ce cas
  `psf_mode = measured` fait le travail tout seul.

## Fonctionnement

1. Détection des étoiles (`DAOStarFinder`), **les plus brillantes d'abord** : à nombre
   d'ajustements borné, ce sont celles dont la forme est la mieux contrainte.
2. Ajustement d'une PSF elliptique sur chacune — c'est `fit_psf_stars`, l'ajusteur partagé avec
   `DynamicPSF` et `SubframeSelector`. Écrire un second ajustement aurait garanti qu'ils
   divergent, sur la grandeur même qui sert à juger.
3. Médiane par cellule. Une cellule sans étoile ajustable est rendue **à vide** plutôt
   qu'omise : un trou dans la carte est une information.
4. Si `show_map`, les ellipses et les valeurs sont posées en overlays sur la fenêtre.

Les ellipses dessinées sont **agrandies d'un facteur commun** : à l'échelle réelle, une FWHM de
trois pixels sur une image de six mille est invisible. Ce qui compte est la comparaison entre
cellules ; la valeur absolue est écrite à côté.

## Paramètres

- **`fwhm`** — *real*, défaut `3.0`. FWHM approximative pour la détection, en pixels.
- **`threshold_sigma`** — *real*, défaut `5.0`. Seuil de détection en σ du fond.
- **`max_stars`** — *int*, défaut `300`. Nombre d'ajustements. Au-delà de quelques centaines on
  gagne surtout du temps de calcul.
- **`grid`** — *int*, défaut `5`. Le champ est découpé en `grid` × `grid` cellules.
- **`psf_model`** — *enum* `gaussian` | `moffat`, défaut `gaussian`. Le Moffat a des ailes plus
  longues, souvent plus fidèles au seeing réel.
- **`show_map`** — *bool*, défaut `True`. Dessiner la carte dans le viewport.

Lecture seule : aucun pixel n'est modifié, aucune entrée d'historique n'est créée. Le résultat
est dans `.result` — médianes globales, détail par étoile, et la grille des cellules.

## Astuces & pièges

> **Une excentricité élevée mais uniforme n'est pas un défaut d'optique.** Regardez d'abord si
> la direction des ellipses est la même partout : si oui, cherchez du côté du suivi.

- Une cellule à une ou deux étoiles rend une médiane fragile. Augmentez `max_stars`, ou baissez
  `grid` : mieux vaut trois cellules honnêtes que huit incertaines.
- Sur une image déjà étirée, la détection trouve trop d'étoiles faibles ; montez
  `threshold_sigma`.

## Voir aussi

- [DynamicPSF](retina-doc://DynamicPSF) — la même mesure, étoile par étoile et au clic.
- [AberrationInspector](retina-doc://AberrationInspector) — les coins côte à côte, pour voir
  plutôt que mesurer.
- [SubframeSelector](retina-doc://SubframeSelector) — la même mesure, mais sur un lot de poses.

## Références

- PixInsight — script *FWHMEccentricity*.
