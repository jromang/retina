---
id: PhotometricColorCalibration
category: ColorCalibration
title: Calibration photométrique des couleurs
brief: Balance des blancs astrométrique par photométrie d'ouverture des étoiles Gaia (≈ SPCC de PixInsight).
keywords: [balance des blancs, Gaia, photométrie, WCS, plate-solve, couleur, calibration]
related: [SpectrophotometricColorCalibration, PlateSolve, ColorCalibration, BackgroundNeutralization]
icon: palette
references:
  - "PixInsight — PhotometricColorCalibration (PCC) / SpectrophotometricColorCalibration (SPCC) tool reference."
  - "Gaia DR3 — phot_bp_mean_mag, phot_g_mean_mag, phot_rp_mean_mag (Gaia Archive, gaiadr3.gaia_source)."
  - "photutils.aperture — CircularAperture, aperture_photometry."
  - "astropy.stats — sigma_clipped_stats."
---

## Résumé

`PhotometricColorCalibration` (PCC) calcule une **balance des blancs objective**, ancrée sur le
catalogue stellaire **Gaia DR3**, plutôt que sur un réglage visuel. Le principe : mesurer le flux
instrumental des étoiles du champ dans chaque canal R/G/B, le comparer au flux qu'elles devraient
avoir d'après leurs magnitudes catalogue Gaia (BP/G/RP), et en déduire un **gain par canal** qui
aligne les couleurs stellaires de l'image sur la réalité photométrique. C'est l'équivalent
approché du PCC/SPCC de PixInsight. Le process nécessite une image **couleur** dotée d'un
**WCS** valide (obtenu via `PlateSolve`).

## Cas d'usage

- **Corriger la balance des blancs** d'une image RGB ou LRGB de façon reproductible, sans
  dépendre d'un jugement visuel ou d'une étoile de référence choisie à la main.
- **Comparer des sessions** acquises avec des filtres, capteurs ou conditions différents en les
  ramenant à une même référence colorimétrique (Gaia).
- **Diagnostiquer** une dominante de couleur (nuage fin, filtre mal équilibré, IR/UV résiduel)
  en inspectant les gains renvoyés (`gains`) sans forcément les appliquer (`apply=False`).
- **Valider un traitement RVB** en fin de pipeline, après calibration, empilement, recalage et
  retrait de gradient, avant l'étirement final.

## Fonctionnement

1. **Catalogue** — le process interroge le service Gaia (`astroquery.gaia`) autour du centre du
   champ (déduit du WCS de la fenêtre), sur un rayon angulaire borné à 2°, en filtrant les étoiles
   dont la magnitude G tombe dans `[mag_bright, mag_faint]` et dont BP/RP sont renseignées. Un
   catalogue peut aussi être fourni explicitement en headless via `set_catalog(...)`, pour éviter
   l'accès réseau (tests, environnements hors ligne).
2. **Projection** — les coordonnées célestes (RA/Dec) de chaque étoile sont projetées en pixels
   image via le WCS (`world_to_pixel_values`) ; seules les étoiles à distance `aperture_radius`
   des bords sont conservées.
3. **Photométrie d'ouverture** — pour chaque canal, le fond de ciel local est estimé par
   statistiques robustes (médiane sigma-clippée, `sigma_clipped_stats`) et soustrait, puis le
   flux de chaque étoile est intégré dans une ouverture circulaire de rayon `aperture_radius`
   (`photutils.aperture.CircularAperture` / `aperture_photometry`).
4. **Flux catalogue** — les magnitudes Gaia sont converties en flux via $10^{-0.4\,m}$, avec le
   mapping simplifié **RP→R, G→G, BP→B** (approximation d'un vrai SPCC, qui utiliserait des
   courbes de réponse filtre+capteur et des spectres synthétiques plutôt qu'un mapping 1:1 par
   bande).
5. **Gains** — pour chaque étoile valide (flux mesuré positif et flux catalogue fini), on forme
   le rapport flux-catalogue/flux-mesuré par canal ; le gain final par canal est la **médiane**
   de ces rapports sur toutes les étoiles (robuste aux étoiles mal mesurées, doubles, saturées).
   Les gains sont ensuite normalisés par le gain du canal G, qui sert de référence.
6. **Application** — si `apply=True`, chaque canal est multiplié par son gain puis l'image est
   écrêtée à `[0, 1]` ; sinon, seuls `gains` et `n_stars` sont calculés (mode mesure).

## Mathématiques

Pour une étoile $i$ de magnitudes Gaia $(m_i^{BP}, m_i^G, m_i^{RP})$, le flux catalogue par
canal est déduit de la relation magnitude-flux :

$$ f_i^{R} = 10^{-0.4\,m_i^{RP}}, \qquad f_i^{G} = 10^{-0.4\,m_i^{G}}, \qquad f_i^{B} = 10^{-0.4\,m_i^{BP}}. $$

Le flux instrumental mesuré $\hat{f}_i^{c}$ dans le canal $c$ est la photométrie d'ouverture
après soustraction du fond local $\mu_c$ :

$$ \hat{f}_i^{c} = \sum_{(x,y) \,\in\, A(x_i, y_i, r)} \big( I_c(x,y) - \mu_c \big), $$

où $A(x_i, y_i, r)$ est le disque d'ouverture de rayon $r = $ `aperture_radius` centré sur la
projection pixel $(x_i, y_i)$ de l'étoile, et $\mu_c$ le niveau de fond estimé par médiane
sigma-clippée sur tout le canal. Le gain brut par canal est la médiane, sur les $N$ étoiles
valides, du rapport flux catalogue / flux mesuré :

$$ g_c = \operatorname{med}_i \left( \frac{f_i^{c}}{\hat{f}_i^{c}} \right), $$

puis normalisé par le canal vert, pris comme référence de balance des blancs :

$$ g_c \leftarrow \frac{g_c}{g_G}. $$

L'image corrigée est enfin :

$$ I_c'(x,y) = \operatorname{clip}\big(g_c \cdot I_c(x,y),\; 0,\; 1\big), \qquad c \in \{R, G, B\}. $$

Utiliser la **médiane** plutôt que la moyenne rend l'estimation robuste face aux étoiles doubles,
saturées ou mal centrées, qui produiraient sinon des rapports aberrants.

## Paramètres

- **`mag_bright`** — *real*, défaut `7.0`, plage `-5`–`20`. Magnitude Gaia G la plus brillante
  acceptée. Trop bas laisse passer des étoiles proches de la saturation du capteur, ce qui fausse
  leur flux mesuré.
- **`mag_faint`** — *real*, défaut `13.0`, plage `0`–`22`. Magnitude Gaia G la plus faible
  acceptée. Trop haut inclut des étoiles bruitées, proches du fond de ciel, dont la photométrie
  est peu fiable.
- **`aperture_radius`** — *real*, défaut `5.0`, plage `1`–`50` (pixels). Rayon du disque
  d'ouverture pour la photométrie. Doit couvrir l'essentiel du profil (PSF/FWHM) des étoiles sans
  empiéter sur leurs voisines.
- **`max_stars`** — *int*, défaut `300`, plage `3`–`5000`. Nombre maximal d'étoiles demandées à
  Gaia (limite `TOP` de la requête ADQL). Plus d'étoiles stabilise la médiane mais allonge la
  requête réseau.
- **`apply`** — *bool*, défaut `True`. Si vrai, applique les gains à l'image (opération
  destructive, historisée) ; si faux, se contente de mesurer et de renseigner `gains`/`n_stars`
  sans toucher aux pixels ni pousser d'entrée d'historique.

## Astuces & pièges

> **Attention** — le process échoue explicitement si la fenêtre n'a pas de WCS (lancez
> `PlateSolve` au préalable) ou si l'image n'a pas au moins 3 canaux couleur.

> **Note** — l'approximation Gaia BP/G/RP ≈ bandes larges B/G/R est plus grossière que le vrai
> SPCC de PixInsight, qui intègre des spectres synthétiques sur la réponse réelle filtre+capteur.
> Pour un résultat plus fidèle sur des filtres larges non standards, préférer
> `SpectrophotometricColorCalibration`, qui combine les flux Gaia via des passe-bandes nominales.

- En headless ou sans accès réseau, injectez un catalogue via `set_catalog([(ra, dec, bp, g, rp), …])`
  pour éviter la requête `astroquery.gaia`.
- Si moins de 3 étoiles catalogue tombent dans le champ, ou moins de 3 sont mesurables (flux
  positif), le process lève une erreur : élargissez `mag_faint` ou vérifiez le WCS.
- Lancez d'abord avec `apply=False` pour inspecter `gains` et `n_stars` avant d'appliquer, en
  particulier sur un champ pauvre en étoiles cataloguées.
- Le retrait de gradient (`BackgroundExtraction`/`BackgroundNeutralization`) doit précéder la PCC :
  un fond mal soustrait biaise l'estimation locale du niveau de ciel par canal.

## Voir aussi

- [SpectrophotometricColorCalibration](retina-doc://SpectrophotometricColorCalibration) — variante
  plus fidèle, synthèse des canaux R/G/B par passe-bandes combinant les flux Gaia BP/G/RP.
- [PlateSolve](retina-doc://PlateSolve) — étape préalable obligatoire (fournit le WCS).
- [ColorCalibration](retina-doc://ColorCalibration) — balance des blancs sans catalogue (référence locale).
- [BackgroundNeutralization](retina-doc://BackgroundNeutralization) — neutralise le fond de ciel avant calibration colorimétrique.

## Références

- PixInsight — *PhotometricColorCalibration (PCC)* / *SpectrophotometricColorCalibration (SPCC)* tool reference.
- Gaia DR3 — `phot_bp_mean_mag`, `phot_g_mean_mag`, `phot_rp_mean_mag` (Gaia Archive, `gaiadr3.gaia_source`).
- photutils.aperture — *CircularAperture*, *aperture_photometry*.
- astropy.stats — *sigma_clipped_stats*.
