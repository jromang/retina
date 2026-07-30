---
id: RadialProfileMeasurement
category: ImageInspection
title: Mesure de profil radial
brief: "Profil radial et courbe de croissance de l'étoile la plus brillante, avec FWHM ajustée (photutils)."
keywords: [FWHM, profil radial, courbe de croissance, mise au point, collimation, photutils, étoile]
related: [DynamicPSF, Statistics, SubframeSelector, StarMask]
icon: chart-arcs
references:
  - "photutils.profiles — RadialProfile and CurveOfGrowth."
  - "PixInsight — PSF / star profile inspection tools."
---

## Résumé

`RadialProfileMeasurement` mesure comment la lumière d'une étoile se répartit autour de son
centre : il localise automatiquement le pixel le plus lumineux de l'image, puis échantillonne
deux courbes autour de ce pic — le **profil radial** (intensité moyenne par anneau concentrique)
et la **courbe de croissance** (flux cumulé dans des ouvertures circulaires de rayon croissant).
Une gaussienne est ajustée sur le profil radial pour en extraire la **FWHM** en pixels. C'est un
process de **mesure pure**, en lecture seule : il ne modifie jamais les pixels, il remplit
simplement `.result` avec les données chiffrées.

## Cas d'usage

- **Contrôle de mise au point** en direct sur une étoile brillante : suivre la FWHM ajustée pour
  affiner le focuser jusqu'au minimum.
- **Diagnostic de collimation/optique** : un profil radial asymétrique ou une courbe de croissance
  qui ne sature pas franchement trahit une aberration optique ou un défaut de collimation.
- **Comparer visuellement plusieurs poses** en traçant leurs profils radiaux côte à côte (via
  `.result["radius"]`/`.result["profile"]`) pour repérer un flou de suivi ou de turbulence.
- **Estimer le rayon d'ouverture optimal** pour une photométrie d'ouverture, en lisant sur la
  courbe de croissance le rayon où le flux cumulé plafonne.

## Fonctionnement

1. L'image est réduite à une carte de luminance (moyenne des canaux si l'image est en couleur).
2. Le pixel de valeur maximale de cette luminance est pris comme **centre de l'étoile** — aucune
   détection de source n'est faite en amont : le process suppose que l'étoile la plus brillante
   de l'image (ou de la preview passée en entrée) domine clairement le champ.
3. Des anneaux concentriques (`RadialProfile` de photutils), dont les bords vont de 0 à
   `max_radius` par pas de 1 pixel, donnent l'intensité moyenne azimutale à chaque rayon.
4. Des ouvertures circulaires imbriquées de rayon croissant (`CurveOfGrowth` de photutils, mêmes
   rayons hors le rayon nul) donnent le flux total cumulé jusqu'à chaque rayon.
5. Une gaussienne 1D est ajustée sur le profil radial pour en dériver la FWHM
   (`RadialProfile.gaussian_fwhm`) ; l'ajustement échoue silencieusement (FWHM à `None`) si le
   profil est dégénéré (fond plat, étoile saturée, données non finies).

## Mathématiques

Soit $I(x,y)$ la carte de luminance et $(x_c, y_c)$ le pixel de valeur maximale. Pour un pixel à
la distance $r = \sqrt{(x-x_c)^2 + (y-y_c)^2}$, le **profil radial** discrétisé en anneaux
$[r_k, r_{k+1}[$ est la moyenne pondérée par le recouvrement géométrique des pixels dans l'anneau :

$$ P(r_k) = \frac{\sum_{(x,y) \in \text{anneau}_k} w_{x,y}\, I(x,y)}{\sum_{(x,y) \in \text{anneau}_k} w_{x,y}} $$

où $w_{x,y} \in [0,1]$ est la fraction d'aire du pixel couverte par l'anneau (méthode `exact`).
La **courbe de croissance** est le flux intégré dans le disque de rayon $r_k$ :

$$ C(r_k) = \sum_{(x,y) \in \text{disque}(r_k)} w_{x,y}\, I(x,y). $$

La FWHM est obtenue en ajustant au profil radial une gaussienne 1D centrée en $r=0$ :

$$ P(r) \approx A \exp\!\left(-\frac{r^2}{2\sigma^2}\right) + B, \qquad
   \mathrm{FWHM} = 2\sqrt{2\ln 2}\;\sigma \approx 2{,}3548\,\sigma. $$

Pour un système optique parfaitement gaussien et non saturé, la courbe de croissance $C(r)$
converge vers le flux total de l'étoile lorsque $r \to \infty$ ; en pratique elle plafonne bien
avant `max_radius` si le rayon max choisi est suffisant.

## Paramètres

- **`max_radius`** — *int*, défaut `15`, plage `3`–`200`. Rayon maximal (en pixels) échantillonné
  pour le profil radial et la courbe de croissance. Doit couvrir largement le disque
  d'Airy/le halo de l'étoile étudiée ; trop petit, la FWHM et la saturation du flux sont
  sous-estimées, trop grand, un voisin ou du bruit de fond dilue le profil.

## Astuces & pièges

> **Attention** — le centre est choisi comme le **pixel le plus lumineux de toute l'image**,
> sans détection de source. Sur un champ encombré ou avec un pixel chaud, isolez d'abord l'étoile
> visée dans une **preview** recadrée avant de lancer la mesure.

> **Note** — la mesure ne soustrait pas le fond de ciel. Sur une image à fond élevé (pollution
> lumineuse, gradient), la FWHM ajustée peut être biaisée ; passez d'abord par
> `BackgroundExtraction` ou `BackgroundNeutralization`.

- Si `.result["fwhm"]` vaut `None`, le profil était trop plat ou dégénéré (souvent une étoile
  saturée à cœur plat, ou un `max_radius` trop petit) : élargissez le rayon ou vérifiez le centrage.
- Pour une FWHM statistique moyenne sur plusieurs étoiles (contrôle qualité global, focus
  automatique), préférez `DynamicPSF`, qui ajuste une gaussienne 2D sur un lot d'étoiles détectées.

## Voir aussi

- [DynamicPSF](retina-doc://DynamicPSF) — FWHM et excentricité moyennes sur plusieurs étoiles détectées.
- [Statistics](retina-doc://Statistics) — statistiques robustes globales de l'image.
- [SubframeSelector](retina-doc://SubframeSelector) — tri/évaluation qualité d'un lot de poses.

## Références

- photutils.profiles — *RadialProfile* et *CurveOfGrowth*.
- PixInsight — outils d'inspection de profil PSF/étoile.
