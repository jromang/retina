---
id: DynamicPSF
category: ImageInspection
title: DynamicPSF
brief: Mesure la PSF (FWHM, excentricité) sur les étoiles détectées par ajustement de gaussiennes 2D.
keywords: [PSF, FWHM, excentricité, étoiles, DAOStarFinder, mise au point, qualité optique]
related: [RadialProfileMeasurement, SubframeSelector, Deconvolution, StarMask]
icon: chart-dots-3
references:
  - "PixInsight — DynamicPSF tool reference."
  - "Stetson, P. B. (1987) — DAOPHOT: A Computer Program for Crowded-Field Stellar Photometry."
  - "photutils — DAOStarFinder and astropy.modeling.Gaussian2D."
---

## Résumé

`DynamicPSF` mesure la **fonction d'étalement du point** (Point Spread Function) de l'image en
détectant les étoiles puis en ajustant une **gaussienne 2D** sur les plus brillantes d'entre
elles. Il en tire deux indicateurs synthétiques : la **FWHM** (largeur à mi-hauteur, en pixels),
qui quantifie la finesse des étoiles, et l'**excentricité**, qui quantifie leur ovalisation. C'est
un process de **mesure pure, non destructif** — à l'image de `Statistics` — qui ne modifie jamais
les pixels : il alimente `self.result` pour inspection en console ou en script.

## Cas d'usage

- **Diagnostiquer la mise au point** : une FWHM élevée signale un focus imparfait ou une
  turbulence atmosphérique forte au moment de la pose.
- **Détecter un défaut de suivi/autoguidage** : une excentricité élevée trahit des étoiles
  allongées (dérive de monture, jeu mécanique, mauvais polaire).
- **Paramétrer une déconvolution** : la FWHM mesurée sert de point de départ pour construire le
  noyau PSF de `Deconvolution`.
- **Sélectionner les meilleures poses** d'une session avant intégration, en comparant FWHM et
  excentricité frame par frame (complète `SubframeSelector`).

## Fonctionnement

Le process opère en trois étapes :

1. **Estimation robuste du fond** — `astropy.stats.sigma_clipped_stats` calcule médiane et
   écart-type de l'image (luminance = moyenne des canaux si couleur) après rejet itératif à 3σ,
   pour s'affranchir des étoiles et des pixels aberrants.
2. **Détection des sources** — `photutils.detection.DAOStarFinder`, paramétré par `fwhm` (taille
   de noyau de détection attendue) et un seuil `threshold_sigma × std` au-dessus du fond, repère
   les pics stellaires sur l'image fond-soustrait. Les sources sont triées par flux décroissant et
   les `max_stars` plus brillantes sont conservées.
3. **Ajustement gaussien** — pour chaque étoile retenue, une vignette carrée de ±6 pixels autour
   du centroïde est extraite (les étoiles trop proches du bord sont ignorées) et un modèle
   `astropy.modeling.models.Gaussian2D` y est ajusté par moindres carrés (`LevMarLSQFitter`), avec
   un écart-type initial dérivé du `fwhm` de détection. L'ajustement fournit les écarts-types
   $\sigma_x, \sigma_y$ de la gaussienne, dont on tire FWHM et excentricité par étoile. Le résultat
   final est la **médiane** de ces valeurs sur toutes les étoiles ajustées avec succès —
   robuste aux étoiles doubles, saturées ou mal ajustées, qui sont simplement écartées.

## Mathématiques

Pour chaque étoile, l'ajustement produit une gaussienne 2D anisotrope :

$$ g(x, y) = A \exp\!\left[-\frac{(x - x_0)^2}{2\sigma_x^2} - \frac{(y - y_0)^2}{2\sigma_y^2}\right] $$

La **FWHM** d'une gaussienne 1D de variance $\sigma^2$ vaut $2\sqrt{2\ln 2}\,\sigma \approx
2{,}3548\,\sigma$. Pour la PSF elliptique ajustée, DynamicPSF combine les deux axes par leur
moyenne géométrique :

$$ \mathrm{FWHM} = 2{,}3548 \sqrt{\sigma_x \, \sigma_y} $$

L'**excentricité** mesure l'aplatissement de l'ellipse formée par les deux axes de la gaussienne.
En notant $a = \max(\sigma_x, \sigma_y)$ le demi-grand axe et $b = \min(\sigma_x, \sigma_y)$ le
demi-petit axe :

$$ e = \sqrt{1 - \frac{b^2}{a^2}} $$

avec $e = 0$ pour une étoile parfaitement ronde et $e \to 1$ pour une étoile fortement allongée.
Les valeurs FWHM et excentricité rapportées dans `result` sont les **médianes** des valeurs
individuelles $\{\mathrm{FWHM}_i\}$ et $\{e_i\}$ sur les $n$ étoiles ajustées avec succès — un
choix robuste face aux quelques ajustements aberrants inévitables sur un champ réel.

## Paramètres

- **`fwhm`** — *real*, défaut `3.0`, plage `1.0`–`20.0`. FWHM de détection (pixels) transmise à
  `DAOStarFinder` : taille approximative du noyau stellaire attendu, et écart-type initial de la
  gaussienne ajustée. À ajuster à l'échantillonnage réel (grossièrement sous-estimée, elle rate
  les étoiles larges ; surestimée, elle fusionne des étoiles proches).
- **`threshold_sigma`** — *real*, défaut `5.0`, plage `1.0`–`50.0`. Seuil de détection en
  multiples de l'écart-type robuste du fond (σ). Plus il est bas, plus de sources faibles sont
  détectées — au risque d'inclure du bruit.
- **`max_stars`** — *int*, défaut `50`, plage `1`–`500`. Nombre maximal d'étoiles (les plus
  brillantes) sur lesquelles la gaussienne est réellement ajustée. Un nombre plus élevé stabilise
  la médiane mais ralentit la mesure.

## Astuces & pièges

> **Attention** — sur une image bruitée ou peu échantillonnée, un `threshold_sigma` trop bas
> laisse passer du bruit que `DAOStarFinder` interprète comme des étoiles, ce qui biaise la
> médiane. Augmentez le seuil ou stretchez légèrement l'aperçu avant mesure.

> **Note** — les étoiles dont la vignette ±6 px déborde du bord de l'image sont silencieusement
> ignorées, de même que celles dont l'ajustement échoue (étoiles doubles, saturées, ou trop
> proches d'un voisin). `n_stars` dans le résultat peut donc être inférieur à `max_stars`.

- Si `n_stars` vaut 0, le champ ne contient probablement pas assez d'étoiles nettes au-dessus du
  seuil : baissez `threshold_sigma` ou vérifiez la mise au point de la pose.
- Pour une inspection **par étoile** (profil radial complet, pas seulement FWHM/excentricité
  globales), utilisez `RadialProfileMeasurement`.
- Une FWHM mesurée ici constitue un bon point de départ pour le rayon du noyau gaussien de
  `Deconvolution`.

## Voir aussi

- [RadialProfileMeasurement](retina-doc://RadialProfileMeasurement) — profil radial et courbe de
  croissance de l'étoile la plus brillante.
- [SubframeSelector](retina-doc://SubframeSelector) — tri/rejet de poses selon la qualité mesurée.
- [Deconvolution](retina-doc://Deconvolution) — restauration nette utilisant la PSF comme noyau.
- [StarMask](retina-doc://StarMask) — masque des étoiles détectées.

## Références

- PixInsight — *DynamicPSF* tool reference.
- Stetson, P. B. (1987) — *DAOPHOT: A Computer Program for Crowded-Field Stellar Photometry*.
- photutils — *DAOStarFinder* and *astropy.modeling.Gaussian2D*.
