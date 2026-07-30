---
id: SpectrophotometricFluxCalibration
category: ColorCalibration
title: Calibration de flux spectrophotométrique
brief: "Calibration de flux : dérive un point-zéro instrument→physique depuis Gaia (magnitude G)."
keywords: [flux, photométrie, point-zéro, Gaia, WCS, calibration, magnitude]
related: [SpectrophotometricColorCalibration, PhotometricColorCalibration, PlateSolve, SourceExtraction]
icon: prism
references:
  - "Gaia DR3 — phot_g_mean_mag et système photométrique Gaia."
  - "photutils.aperture — aperture_photometry, CircularAperture."
  - "PixInsight — SpectrophotometricColorCalibration (mode flux calibration)."
---

## Résumé

`SpectrophotometricFluxCalibration` établit un **point-zéro** reliant le flux instrumental
(compté en unités de pixel/ADU normalisé) au flux physique réel des étoiles, en s'appuyant sur
le catalogue **Gaia DR3** et la **magnitude G**. Contrairement à `PhotometricColorCalibration` et
`SpectrophotometricColorCalibration`, qui corrigent la **balance des couleurs** (gains relatifs
R/G/B), ce process ne touche qu'à un **facteur d'échelle global unique** (`zero_point`) : il ne
change pas les teintes, seulement l'échelle radiométrique. Il sert de brique pour rendre les
mesures d'intensité **comparables entre sessions**, instruments ou nuits d'observation.

## Cas d'usage

- **Mesurer un point-zéro** de calibration de flux sans modifier l'image (mode par défaut,
  `apply = False`) : utile pour caractériser un capteur/setup ou documenter une session.
- **Comparer des intensités absolues** entre plusieurs images d'une même cible prises à des
  dates différentes, une fois chacune ramenée à la même échelle physique.
- **Préparer une mesure photométrique** (variables, novae, comètes) en amont d'une analyse
  quantitative, en s'assurant que les flux mesurés sont physiquement cohérents avec Gaia.
- **Diagnostiquer une dérive d'exposition/gain** entre sessions en comparant les `zero_point`
  successifs.

## Fonctionnement

Le process requiert une vue dont la fenêtre porte un **WCS** valide (obtenu via `PlateSolve`) :

1. **Interrogation du catalogue Gaia** (`astroquery.gaia`) autour du centre de l'image, sur un
   rayon dérivé du champ, filtrée sur une plage de magnitude G (`mag_bright`–`mag_faint`) — ou
   catalogue fourni explicitement via `set_catalog(...)` pour un usage headless/hors-ligne.
2. **Projection** des positions (RA, Dec) catalogue sur les pixels via le WCS
   (`world_to_pixel_values`), et rejet des étoiles trop proches des bords du champ (marge =
   `aperture_radius`).
3. **Photométrie d'ouverture** (`photutils.aperture.CircularAperture` +
   `aperture_photometry`) sur le **canal de luminance** — le canal G (vert) si l'image est
   couleur, sinon l'unique canal — après soustraction d'un fond de ciel robuste
   (`sigma_clipped_stats`, médiane à 3σ).
4. Pour chaque étoile retenue, calcul du **flux physique attendu** à partir de sa magnitude Gaia
   G : $\phi_{\text{phys}} \propto 10^{-0.4\,G}$.
5. Le **point-zéro** est la **médiane** (robuste aux valeurs aberrantes) du rapport flux
   physique / flux mesuré sur l'ensemble des étoiles valides (flux mesuré strictement positif).
6. En mode `apply = True`, l'image est multipliée par ce point-zéro puis **renormalisée** par son
   maximum pour rester affichable dans `[0, 1]` ; en mode mesure (`apply = False`), seuls
   `zero_point` et `n_stars` sont renseignés sur l'instance, sans modifier l'image ni pousser
   d'entrée d'historique.

## Mathématiques

Soit $\{(\phi_i, G_i)\}_{i=1}^{N}$ l'ensemble des étoiles catalogue valides dans le champ, où
$\phi_i$ est le flux instrumental mesuré (photométrie d'ouverture, fond soustrait) et $G_i$ leur
magnitude Gaia. Le flux physique attendu se déduit de la relation magnitude/flux :

$$ \phi_i^{\text{phys}} = 10^{-0.4\, G_i}. $$

Le point-zéro $Z$ est estimé comme la **médiane des rapports** individuels, ce qui le rend
résistant aux étoiles mal mesurées (saturation, contamination, voisinage) sans nécessiter de
rejet sigma explicite :

$$ Z = \operatorname{med}_i \left( \frac{\phi_i^{\text{phys}}}{\phi_i} \right), \qquad
   i \in \{\, i : \phi_i > 0 \,\}. $$

En mode `apply`, l'image $I$ est remise à l'échelle puis renormalisée par son maximum
$M = \max(Z \cdot I)$ pour rester affichable :

$$ I' = \operatorname{clip}\!\left( \frac{Z \cdot I}{M},\; 0,\; 1 \right). $$

Cette renormalisation par le maximum préserve le **rapport relatif** entre pixels (donc la
cohérence photométrique interne à l'image) tout en gardant les valeurs dans la plage
d'affichage flottant standard — le point-zéro réel $Z$ reste disponible via l'attribut
`zero_point` de l'instance pour tout calcul quantitatif ultérieur.

## Paramètres

- **`mag_bright`** — *real*, défaut `7.0`, plage `-5.0`–`20.0`. Magnitude Gaia G la plus
  brillante acceptée ; exclut les étoiles les plus lumineuses, susceptibles d'être saturées ou
  non linéaires dans l'image.
- **`mag_faint`** — *real*, défaut `13.0`, plage `0.0`–`22.0`. Magnitude Gaia G la plus faible
  acceptée ; borne le rapport signal/bruit minimal des étoiles utilisées pour la mesure.
- **`aperture_radius`** — *real*, défaut `5.0`, plage `1.0`–`50.0`. Rayon (en pixels) de
  l'ouverture circulaire de photométrie ; doit couvrir l'essentiel du flux du PSF sans trop
  inclure de fond ni de voisins.
- **`max_stars`** — *int*, défaut `300`, plage `3`–`5000`. Nombre maximal d'étoiles demandées à
  la requête Gaia (limite `TOP` de la requête ADQL).
- **`apply`** — *bool*, défaut `False`. Si `False` (défaut), le process ne fait que **mesurer**
  le point-zéro (`zero_point`, `n_stars`) sans modifier l'image ni pousser d'entrée d'historique.
  Si `True`, l'image est effectivement remise à l'échelle et renormalisée.

## Astuces & pièges

> **Attention** — un WCS est **obligatoire** : exécutez `PlateSolve` avant ce process. Sans
> WCS valide (`window.wcs is None`), une `ValueError` est levée immédiatement.

> **Note** — le mode par défaut (`apply = False`) ne modifie jamais l'image : c'est une mesure
> pure. Pensez à consulter `instance.zero_point` et `instance.n_stars` après exécution plutôt que
> de vous fier à un changement visuel.

- Le point-zéro dépend de l'**échelle d'entrée** de l'image (linéaire non étirée de préférence) :
  appliquer ce process après un étirement non linéaire (`HistogramTransformation`,
  `CurvesTransformation`) fausse la relation flux/magnitude.
- Trop peu d'étoiles valides (moins de 3 dans le champ après filtrage des bords, ou moins de 3
  avec un flux mesuré positif) déclenche une erreur explicite — élargissez `mag_bright`/
  `mag_faint` ou vérifiez le rayon d'ouverture.
- Pour un usage **hors ligne** (sans accès réseau à Gaia), fournissez un catalogue local via
  `set_catalog([(ra, dec, bp, g, rp), …])` avant d'appeler `execute_on`.
- Ce process **ne corrige pas la couleur** : pour une balance des blancs photométrique, utilisez
  `PhotometricColorCalibration` ou `SpectrophotometricColorCalibration` en complément.

## Voir aussi

- [SpectrophotometricColorCalibration](retina-doc://SpectrophotometricColorCalibration) — balance
  des couleurs par photométrie synthétique Gaia (gains par canal, même infrastructure de mesure).
- [PhotometricColorCalibration](retina-doc://PhotometricColorCalibration) — balance des couleurs
  simple (mapping direct RP/G/BP → R/G/B).
- [PlateSolve](retina-doc://PlateSolve) — étape préalable obligatoire (fournit le WCS).
- [SourceExtraction](retina-doc://SourceExtraction) — détection de sources, utile pour valider
  visuellement le champ avant calibration photométrique.

## Références

- Gaia DR3 — *phot_g_mean_mag* et système photométrique Gaia.
- photutils.aperture — *aperture_photometry*, *CircularAperture*.
- PixInsight — *SpectrophotometricColorCalibration* (mode calibration de flux).
