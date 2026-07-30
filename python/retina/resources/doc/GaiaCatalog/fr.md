---
id: GaiaCatalog
category: Global
title: Catalogue Gaia
brief: Interroge Gaia DR3 en ligne pour lister et projeter en pixels les étoiles du champ résolu (WCS).
keywords: [Gaia, catalogue, astrométrie, TAP, ADQL, WCS, plate solve, étoiles de référence]
related: [PlateSolve, APASSCatalog, CatalogAnnotation, PhotometricColorCalibration]
icon: database
references:
  - "Gaia Collaboration — Gaia Data Release 3 (DR3), 2022."
  - "ESA/Gaia archive — TAP/ADQL access to gaiadr3.gaia_source."
  - "astroquery.gaia — Python client for the Gaia TAP+ service."
---

## Résumé

`GaiaCatalog` interroge en ligne le relevé stellaire **Gaia DR3** (via `astroquery.gaia`) pour
la portion de ciel couverte par la vue active, puis **projette chaque étoile en coordonnées
pixel** grâce au WCS établi par `PlateSolve`. Le résultat — une liste d'étoiles avec ascension
droite, déclinaison, magnitude G et position `(x, y)` — est stocké dans `.result`, prêt à servir
d'entrée à l'annotation, à la calibration photométrique ou à la sélection d'étoiles de référence.
C'est un process de **mesure pure** : il ne modifie jamais les pixels de l'image.

## Cas d'usage

- **Fournir une liste d'étoiles de référence** à `PhotometricColorCalibration` ou
  `SpectrophotometricColorCalibration` pour un étalonnage colorimétrique physique.
- **Alimenter `CatalogAnnotation`** afin de superposer des repères d'étoiles nommées/magnitudes
  sur l'image finale.
- **Vérifier la qualité d'un plate solve** : comparer le nombre et la position des étoiles
  cataloguées à celles réellement détectées dans l'image.
- **Choisir des étoiles de calibration** pour la photométrie différentielle ou la mesure de FWHM
  en un point précis du champ.

## Fonctionnement

1. **Pré-requis WCS** : la vue doit porter une solution astrométrique (`window.wcs`), obtenue au
   préalable par `PlateSolve`. Sans WCS, le process lève une erreur explicite.
2. **Calcul du rayon de recherche** : le centre du champ est déterminé par projection du pixel
   central via le WCS ; le rayon de la requête conique est la séparation angulaire entre ce
   centre et le coin `(0, 0)` de l'image, **plafonnée à 3°** pour éviter des requêtes trop
   coûteuses sur de très grands champs.
3. **Requête TAP/ADQL** : une requête `SELECT TOP max_stars ra, dec, phot_g_mean_mag FROM
   gaiadr3.gaia_source WHERE CONTAINS(POINT(...), CIRCLE(...)) AND phot_g_mean_mag < mag_limit`
   est soumise de façon asynchrone au service Gaia via `astroquery.gaia.Gaia.launch_job_async`.
4. **Projection en pixels** : chaque étoile `(ra, dec)` renvoyée est convertie en coordonnées
   image via `wcs.world_to_pixel_values`, puis les étoiles tombant hors du cadre `[0, w) × [0, h)`
   sont écartées.
5. **Résultat** : `.result = {"n_stars": N, "stars": [{"ra", "dec", "mag", "x", "y"}, …]}`. Aucune
   entrée d'historique n'est créée (`execute_on` ne modifie pas la vue).

`APASSCatalog` suit exactement la même logique mais interroge APASS DR9 (photométrie BVgri à
large bande) via Vizier plutôt que Gaia.

## Mathématiques

**Rayon de recherche.** Le champ est centré sur le pixel $(w/2, h/2)$, projeté en coordonnées
célestes $(\alpha_0, \delta_0)$ par le WCS. Le rayon de la requête conique est la séparation
angulaire sur la sphère céleste entre ce centre et le coin de l'image, donnée par la formule des
haversines :

$$ \Delta\sigma = 2 \arcsin\!\sqrt{\sin^2\!\Big(\tfrac{\delta_1-\delta_0}{2}\Big) +
   \cos\delta_0 \cos\delta_1 \sin^2\!\Big(\tfrac{\alpha_1-\alpha_0}{2}\Big)}, \qquad
   r = \min(\Delta\sigma,\ 3°). $$

**Requête conique ADQL.** Le filtre `CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', α₀, δ₀, r))
= 1` sélectionne les sources dont la séparation angulaire au centre est inférieure à $r$, ce qui
revient à l'inégalité ci-dessus appliquée à chaque ligne de `gaiadr3.gaia_source`, combinée à la
coupure de magnitude `phot_g_mean_mag < mag_limit`.

**Projection céleste → pixel.** Le WCS transforme chaque paire $(\alpha_i, \delta_i)$ en position
image $(x_i, y_i)$ via la projection tangente (TAN) standard : coordonnées standard
$(\xi, \eta)$ au plan tangent au pôle du champ,

$$ \xi = \frac{\cos\delta \,\sin(\alpha - \alpha_0)}
   {\sin\delta_0 \sin\delta + \cos\delta_0 \cos\delta \cos(\alpha-\alpha_0)}, \qquad
   \eta = \frac{\cos\delta_0 \sin\delta - \sin\delta_0 \cos\delta \cos(\alpha-\alpha_0)}
   {\sin\delta_0 \sin\delta + \cos\delta_0 \cos\delta \cos(\alpha-\alpha_0)}, $$

puis $(\xi, \eta)$ est converti en pixels par la matrice CD/PC et le point de référence `CRPIX`
du WCS (`astropy.wcs.WCS.world_to_pixel_values`, qui encapsule ces étapes).

## Paramètres

- **`mag_limit`** — *real*, défaut `16.0`, plage `0.0`–`22.0`. Magnitude G (Gaia) limite : seules
  les étoiles plus brillantes (magnitude inférieure) que ce seuil sont retenues par la requête.
- **`max_stars`** — *int*, défaut `1000`, plage `1`–`100000`. Nombre maximal de lignes ramenées
  par la requête TAP (clause `TOP`), avant filtrage sur le cadre image.

## Astuces & pièges

> **Attention** — la clause `TOP max_stars` de la requête n'est **pas accompagnée d'un
> `ORDER BY` sur la magnitude** : les étoiles renvoyées ne sont donc pas nécessairement les plus
> brillantes du champ, seulement les `max_stars` premières lignes dans l'ordre de retour du
> service Gaia. Pour être sûr d'obtenir les étoiles les plus brillantes, resserrez `mag_limit`
> plutôt que de vous fier uniquement à `max_stars`.

> **Note** — `GaiaCatalog` exige un WCS valide sur la fenêtre (`view.window.wcs`) ; lancez
> toujours `PlateSolve` au préalable, sinon le process échoue avec une erreur explicite.

- La requête est **en ligne** (accès réseau au service Gaia) : un `execute_on` peut prendre
  plusieurs secondes selon la densité du champ et la charge du service.
- Le rayon de recherche est **plafonné à 3°** : sur un très grand champ (objectif grand-angle),
  seule une partie du champ sera couverte par le catalogue téléchargé.
- Pour des tests headless ou un usage hors ligne, `set_catalog([(ra, dec, mag), …])` permet
  d'injecter directement une liste d'étoiles et de court-circuiter la requête réseau.
- Les étoiles hors cadre (projetées en dehors de `[0, w) × [0, h)`) sont silencieusement
  écartées du résultat — seul le champ effectivement imagé est représenté.

## Voir aussi

- [PlateSolve](retina-doc://PlateSolve) — calcule le WCS requis en amont.
- [APASSCatalog](retina-doc://APASSCatalog) — catalogue photométrique BVgri équivalent (Vizier).
- [CatalogAnnotation](retina-doc://CatalogAnnotation) — annote l'image à partir d'un catalogue.
- [PhotometricColorCalibration](retina-doc://PhotometricColorCalibration) — calibration couleur
  s'appuyant sur des étoiles de référence catalogées.

## Références

- Gaia Collaboration — *Gaia Data Release 3 (DR3)*, 2022.
- ESA/Gaia archive — accès TAP/ADQL à `gaiadr3.gaia_source`.
- astroquery.gaia — client Python pour le service Gaia TAP+.
