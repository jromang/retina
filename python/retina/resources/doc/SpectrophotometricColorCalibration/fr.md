---
id: SpectrophotometricColorCalibration
category: ColorCalibration
title: Calibration colorimétrique spectrophotométrique (SPCC)
brief: Balance des blancs par photométrie synthétique sur les spectres réels de Gaia et la réponse mesurée de votre instrument.
keywords: [SPCC, calibration couleur, Gaia, spectres XP, photométrie synthétique, balance des blancs, WCS, filtres, bande étroite]
related: [FilterManager, PhotometricColorCalibration, PlateSolve, BackgroundNeutralization, ColorCalibration]
icon: palette
references:
  - "PixInsight — SpectrophotometricColorCalibration tool reference."
  - "Gaia DR3 — spectres échantillonnés BP/RP et bandes G, BP, RP (Gaia Collaboration, 2022)."
  - "siril-spcc-database — courbes de filtres et de capteurs (GPL-3)."
  - "photutils.aperture — CircularAperture / aperture_photometry."
---

## Résumé

`SpectrophotometricColorCalibration` (SPCC) calcule une **balance des blancs par photométrie
stellaire**. Le raisonnement tient en une phrase : pour chaque étoile du champ, on sait ce que
l'instrument *aurait dû* mesurer — son spectre intégré sur la réponse de chaque canal — et on
le compare à ce qu'il a mesuré. Le rapport donne le gain du canal.

Encore faut-il de vrais spectres et de vraies courbes. Retina emploie les **spectres
échantillonnés de Gaia DR3** (`spectrum_source = gaia_xp`), qui portent le rougissement et la
métallicité de chaque étoile, et une **base de courbes** de transmission de filtres et de
rendement de capteurs (voir [FilterManager](retina-doc://FilterManager)). La **référence de
blanc** fixe ensuite ce qu'on décrète neutre.

Tant qu'aucune courbe n'est nommée, le process retombe explicitement sur des **passe-bandes
nominales** appliquées aux trois magnitudes Gaia — le comportement d'origine. C'est délibéré :
trois canaux sans courbe auraient la même réponse, et le SPCC deviendrait un no-op silencieux.

Le process nécessite un **WCS** (issu de `PlateSolve`) et une image **couleur**.

## Cas d'usage

- **Calibrer la couleur** d'une image RVB avant l'étirement final, pour obtenir des étoiles
  et des teintes cohérentes avec un standard photométrique objectif (Gaia) plutôt qu'avec un
  simple équilibrage visuel.
- **Remplacer un `ColorCalibration` manuel** par une méthode ancrée dans un catalogue, utile
  quand le champ contient assez d'étoiles cataloguées non saturées.
- **Vérifier la cohérence colorimétrique** entre plusieurs sessions/optiques : les gains
  `SpectrophotometricColorCalibration.gains` obtenus servent de diagnostic même sans
  appliquer la correction (`apply=False`).
- **Chaîne LRGB/narrowband** : à exécuter sur la composition couleur finale, après
  alignement et avant l'étirement non linéaire.

## Fonctionnement

1. **Récupération du catalogue** : si aucun catalogue n'a été injecté via `set_catalog(…)`,
   le process interroge Gaia DR3 en ligne (`astroquery.gaia`) dans un rayon centré sur le champ
   (borné à 2°), en filtrant sur `mag_bright`/`mag_faint` et plafonnant à `max_stars`. En mode
   `gaia_xp`, une **seconde requête** récupère les spectres échantillonnés par DataLink et les
   rééchantillonne sur la grille de travail (336–1020 nm, pas de 2 nm). Une étoile sans spectre
   XP n'est pas écartée : elle repasse par le chemin photométrique.
2. **Projection WCS** : les coordonnées célestes (ra, dec) du catalogue sont converties en
   coordonnées pixel via le WCS de la fenêtre (`win.wcs.world_to_pixel_values`) ; seules les
   étoiles tombant dans le champ, à `aperture_radius` près des bords, sont conservées.
3. **Photométrie d'ouverture instrumentale** : pour chaque canal R, G, B, le fond de ciel est
   estimé par statistiques robustes sigma-clippées (`astropy.stats.sigma_clipped_stats`) et
   soustrait, puis le flux de chaque étoile est intégré dans une ouverture circulaire de
   rayon `aperture_radius` (`photutils.aperture.CircularAperture` /
   `aperture_photometry`).
4. **Flux synthétique** : le spectre de l'étoile est intégré sur la réponse de chaque canal —
   transmission du filtre × rendement du capteur, ou passe-bande rectangulaire en mode bande
   étroite. Sans spectre ni courbe, on retombe sur les passe-bandes nominales appliquées aux
   flux $10^{-0.4\,m}$ des trois magnitudes Gaia.
5. **Calcul des gains** : le rapport flux-catalogue / flux-mesuré est calculé étoile par
   étoile puis canal par canal, la **médiane** de ces rapports donnant un gain robuste aux
   valeurs aberrantes ; le gain est ensuite normalisé par celui du canal G (référence de
   balance des blancs).
6. **Application** : si `apply=True`, chaque canal est multiplié par son gain et le résultat
   est écrêté dans `[0, 1]` ; sinon, seule la mesure est effectuée (les gains restent
   accessibles sur l'instance, aucune entrée d'historique n'est créée).

## Mathématiques

Soit $R_c(\lambda)$ la réponse du canal $c$ — produit de la transmission du filtre et du
rendement quantique du capteur — et $S_i(\lambda)$ le spectre de l'étoile $i$. Le flux que
l'instrument aurait dû mesurer est

$$ f^{\text{synth}}_{c,i} = \int S_i(\lambda)\, R_c(\lambda)\, \mathrm{d}\lambda, $$

et la référence de blanc $W(\lambda)$ définit le neutre par

$$ w_c = \int W(\lambda)\, R_c(\lambda)\, \mathrm{d}\lambda. $$

Les intégrales sont des sommes sur la grille de Gaia (336–1020 nm, pas de 2 nm) : plus fin
n'apporterait rien, les spectres n'existant pas ailleurs.

### Le repli sans spectre ni courbe

Pour chaque étoile $i$ du catalogue tombant dans le champ, on convertit ses magnitudes Gaia
$(m_{BP,i}, m_{G,i}, m_{RP,i})$ en flux catalogue :

$$ f_{RP,i} = 10^{-0.4\,m_{RP,i}}, \qquad f_{G,i} = 10^{-0.4\,m_{G,i}}, \qquad
   f_{BP,i} = 10^{-0.4\,m_{BP,i}}. $$

Le flux **synthétique par canal instrument** $c \in \{R, G, B\}$ est obtenu par une matrice
de passe-bandes nominales $\mathbf{P}$ (chaque ligne somme à 1) appliquée au vecteur
$(f_{RP,i}, f_{G,i}, f_{BP,i})$ :

$$ \begin{pmatrix} f^{\text{synth}}_{R,i} \\ f^{\text{synth}}_{G,i} \\ f^{\text{synth}}_{B,i}
   \end{pmatrix}
   = \mathbf{P} \begin{pmatrix} f_{RP,i} \\ f_{G,i} \\ f_{BP,i} \end{pmatrix}, \qquad
   \mathbf{P} = \begin{pmatrix} 0.85 & 0.10 & 0.05 \\ 0.10 & 0.80 & 0.10 \\
   0.05 & 0.10 & 0.85 \end{pmatrix}. $$

La ligne $R$ est dominée par RP (0,85), la ligne $B$ par BP (0,85), et la ligne $G$ par G
(0,80) — avec une contamination croisée de 10 à 15 % qui modélise le recouvrement des
passe-bandes Gaia. Côté image, le flux instrumental mesuré $f^{\text{mes}}_{c,i}$ est la
somme des pixels de l'ouverture après soustraction du fond local $\tilde{b}_c$ :

$$ f^{\text{mes}}_{c,i} = \sum_{(x,y)\,\in\,\text{ouverture}_i} \big(I_c(x,y) - \tilde{b}_c\big). $$

Le gain de canal est la **médiane robuste** du rapport flux-catalogue/flux-mesuré sur toutes
les étoiles valides $\mathcal{V}$ (flux mesuré positif, flux synthétique fini) :

$$ g_c = \frac{1}{w_c} \operatorname{med}_{i \in \mathcal{V}}
   \left( \frac{f^{\text{synth}}_{c,i}}{f^{\text{mes}}_{c,i}} \right), \qquad
   g_c \leftarrow \frac{g_c}{g_G}. $$

Diviser par $w_c$ est ce qui *définit* le blanc : sans cette division on calibrerait sur un
spectre plat, qui n'est le blanc de personne.

La normalisation par $g_G$ fixe le canal vert comme référence (balance des blancs sans
changement de luminance globale). L'image corrigée est enfin :

$$ I'_c(x,y) = \operatorname{clip}\big(g_c \, I_c(x,y),\; 0,\; 1\big). $$

Utiliser la médiane plutôt que la moyenne rend l'estimation résistante aux étoiles doubles,
saturées ou mal centrées qui biaiseraient un rapport moyen classique.

## Paramètres

- **`mag_bright`** — *real*, défaut `7.0`, plage `-5`–`20`. Magnitude Gaia G la plus brillante
  retenue dans le catalogue ; exclut les étoiles les plus lumineuses, souvent saturées dans
  l'image et donc biaisées en photométrie d'ouverture.
- **`mag_faint`** — *real*, défaut `13.0`, plage `0`–`22`. Magnitude Gaia G la plus faible
  retenue ; au-delà, le rapport signal/bruit stellaire devient trop faible pour une mesure
  fiable.
- **`aperture_radius`** — *real*, défaut `5.0`, plage `1`–`50`. Rayon (en pixels) de
  l'ouverture circulaire de photométrie. Doit être ajusté au FWHM des étoiles de l'image
  (trop petit = flux sous-estimé, trop grand = contamination par les voisines).
- **`max_stars`** — *int*, défaut `300`, plage `3`–`5000`. Nombre maximal d'étoiles
  interrogées dans le catalogue Gaia (limite la requête `TOP N` et le temps de calcul).
- **`apply`** — *bool*, défaut `True`. Si vrai, applique les gains à l'image (opération
  destructive, entrée d'historique). Si faux, effectue seulement la mesure : les gains
  restent lisibles sur `process.gains` sans modifier l'image.

### Réponse instrumentale

- **`spectrum_source`** — *enum* `gaia_xp` | `gaia_photometry`, défaut `gaia_xp`. Les spectres
  échantillonnés, ou les seules trois magnitudes.
- **`red_filter`**, **`green_filter`**, **`blue_filter`** — *str*, vides par défaut.
  Identifiants de courbes de transmission (`FilterManager(action='list', kind='filter')`).
- **`red_sensor`**, **`green_sensor`**, **`blue_sensor`** — *str*, vides par défaut. Courbes de
  rendement quantique. Un capteur couleur en a une par canal, un capteur mono une seule qu'on
  répète sur les trois.
- **`white_reference`** — *str*, défaut `average_spiral_galaxy`. Le spectre décrété neutre.
  Vide = spectre plat.

### Bande étroite

- **`narrowband`** — *bool*, défaut `False`. Remplace les courbes de filtres par des
  passe-bandes rectangulaires.
- **`red_wavelength`** / **`red_bandwidth`** (défauts `656.3` / `7.0` nm, soit Hα),
  **`green_wavelength`** / **`green_bandwidth`** et **`blue_wavelength`** /
  **`blue_bandwidth`** (défauts `500.7` nm, soit OIII) — *real*, en nanomètres.

## Astuces & pièges

> **Attention** — SPCC nécessite un **WCS valide** sur la fenêtre (lancez `PlateSolve` au
> préalable) et une image **couleur** à au moins 3 canaux ; sinon le process lève une
> exception explicite plutôt que de produire un résultat silencieusement faux.

> **Nommez vos filtres et votre capteur.** Sans eux, le process retombe sur des coefficients
> nominaux : cela marche, mais on n'exploite ni les spectres réels, ni la réponse de votre
> matériel. `FilterManager(action='list')` dit ce qui est disponible, et `action='add'` permet
> d'entrer une courbe qui manque.

> **Un capteur monochrome n'a qu'une courbe.** Mettez-la dans les trois `*_sensor` : c'est bien
> le même capteur qui voit les trois filtres. Un capteur couleur, lui, a une courbe par canal.

- Écartez d'abord les étoiles saturées (`mag_bright` suffisamment élevé) : un flux
  instrumental écrêté fausse tous les gains, pas seulement celui du canal saturé.
- En l'absence de connexion réseau ou pour un test reproductible, utilisez
  `set_catalog(...)` pour fournir un catalogue Gaia déjà téléchargé ou synthétique.
- Un champ trop pauvre en étoiles (moins de 3 valides après filtrage) fait échouer le
  calcul : élargissez `mag_faint` ou vérifiez le rayon de recherche du catalogue.
- Exécutez `BackgroundNeutralization` en amont si le fond de ciel a une teinte marquée : SPCC
  corrige la couleur des **étoiles**, pas le gradient de fond.

## Voir aussi

- [FilterManager](retina-doc://FilterManager) — consulter et compléter la base de courbes.
- [PhotometricColorCalibration](retina-doc://PhotometricColorCalibration) — variante avec
  mapping 1:1 RP→R/G→G/BP→B, sans passe-bandes combinées.
- [PlateSolve](retina-doc://PlateSolve) — résolution astrométrique préalable, requise pour le WCS.
- [BackgroundNeutralization](retina-doc://BackgroundNeutralization) — neutralisation
  colorimétrique du fond de ciel, complémentaire.
- [ColorCalibration](retina-doc://ColorCalibration) — calibration couleur générique
  (sans catalogue).

## Références

- PixInsight — *SpectrophotometricColorCalibration* tool reference.
- Gaia DR3 — spectres échantillonnés BP/RP et bandes G, BP, RP (Gaia Collaboration, 2022).
- siril-spcc-database — courbes de filtres et de capteurs, communauté Siril (GPL-3).
- photutils.aperture — *CircularAperture* / *aperture_photometry*.
