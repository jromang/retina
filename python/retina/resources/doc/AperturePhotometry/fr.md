---
id: AperturePhotometry
category: ImageInspection
title: Photométrie d'ouverture
brief: Mesure flux, incertitude et magnitude des sources détectées, fond pris dans un anneau.
keywords: [photométrie, ouverture, anneau, flux, magnitude, SNR, CSV, courbe de lumière]
related: [SourceExtraction, NoiseEvaluation, PhotometricColorCalibration, DynamicPSF]
icon: circle
references:
  - "photutils.aperture — CircularAperture, CircularAnnulus, ApertureStats."
  - "PixInsight — script AperturePhotometry."
---

## Résumé

`AperturePhotometry` détecte les sources, mesure le flux de chacune dans une **ouverture
circulaire**, en soustrait un fond pris dans un **anneau** autour d'elle, et rend une table :
position, flux, incertitude, rapport signal/bruit, magnitude instrumentale — et coordonnées
célestes si le champ est résolu.

## L'anneau de fond n'est pas un détail

Soustraire un fond **global** revient à supposer que le ciel est plat. Il ne l'est jamais :
gradient de pollution lumineuse, halo d'une étoile brillante, nébulosité. L'anneau mesure le
ciel *là où est la source*, et sa **médiane** écarte les voisines qui y traînent.

Sur le champ de test — douze sources de flux connus posées sur un gradient de fond — la mesure
retrouve les flux vrais à **2 % près**. Sans anneau, l'erreur suivrait le gradient.

Une source dont l'anneau **déborde du cadre** est écartée : la garder rendrait un flux calculé
contre un fond partiel, donc faux sans le dire.

## Cas d'usage

- **Courbes de lumière** : mesurer une variable pose après pose, exporter, tracer ailleurs.
- **Contrôle qualité** : le rapport signal/bruit des étoiles d'une pose, comparé d'une nuit à
  l'autre.
- **Vérifier une calibration de flux** ou un point-zéro.

## Ce que l'incertitude vaut, et ne vaut pas

Elle suppose un bruit **gaussien** de dispersion mesurée sur l'anneau, intégré sur l'aire de
l'ouverture, plus l'incertitude sur le fond lui-même. Elle ne suppose **pas** un bruit de
photons : nos images sont normalisées, et le gain qui permettrait de compter les électrons
n'est pas connu du process.

C'est donc une incertitude *relative* : bonne pour comparer des sources entre elles ou une
même source d'une pose à l'autre, pas pour publier une magnitude absolue.

## L'export est un geste de domaine

Une table qu'on ne peut pas sortir ne sert qu'à être regardée. `output_path` écrit le CSV
depuis le domaine — donc depuis la console, donc depuis un script — et un bouton d'interface ne
fera jamais que renseigner ce paramètre. C'est la règle de parité du projet : si l'export
n'existait que dans un panneau, il serait une capacité de la GUI, ce que Retina s'interdit.

Les colonnes sont `id, x, y, ra, dec, flux, flux_error, snr, magnitude, background,
aperture_area`.

## Paramètres

- **`fwhm`** — *real*, défaut `3.0`. FWHM approximative pour la détection.
- **`threshold_sigma`** — *real*, défaut `5.0`. Seuil de détection en σ du fond.
- **`max_sources`** — *int*, défaut `500`. Les plus brillantes d'abord.
- **`aperture_radius`** — *real*, défaut `5.0`. Rayon de l'ouverture, en pixels. Une bonne
  valeur est de l'ordre de 1,5 à 2 FWHM : trop petite, on perd du flux ; trop grande, on
  ramasse les voisines.
- **`annulus_inner`** / **`annulus_outer`** — *real*, défauts `8.0` / `12.0`. L'anneau de fond.
  L'interne doit dépasser l'ouverture d'une marge, sinon il mesure encore l'étoile.
- **`channel`** — *int*, défaut `-1`. Canal mesuré ; `-1` prend la luminance.
- **`zero_point`** — *real*, défaut `0.0`. Constante additive de la magnitude.
- **`output_path`** — *path*. Si renseigné, le CSV est écrit à la fin de la mesure.
- **`show_apertures`** — *bool*, défaut `False`. Dessiner les ouvertures dans le viewport.

Lecture seule ; résultat dans `.result`.

## Astuces & pièges

> **Les étoiles saturées faussent tout.** Leur flux est écrêté, donc sous-estimé, et rien dans
> la mesure ne le signale. Montez `threshold_sigma` ou écartez-les à la lecture.

- Mesurez sur données **linéaires**. Après étirement, le flux n'est plus proportionnel au
  nombre de photons et une magnitude n'a plus de sens.
- Vérifiez `aperture_area` : sur un champ dense, deux ouvertures qui se recouvrent comptent
  deux fois les mêmes pixels.

## Voir aussi

- [SourceExtraction](retina-doc://SourceExtraction) — détection seule, avec segmentation et
  déblending.
- [NoiseEvaluation](retina-doc://NoiseEvaluation) — le bruit de l'image, mesuré proprement.
- [PhotometricColorCalibration](retina-doc://PhotometricColorCalibration) — la même photométrie,
  au service de la couleur.

## Références

- photutils.aperture — *CircularAperture*, *CircularAnnulus*, *ApertureStats*.
- PixInsight — script *AperturePhotometry*.
