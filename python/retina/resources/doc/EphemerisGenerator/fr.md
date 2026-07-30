---
id: EphemerisGenerator
category: Astrometry
title: Générateur d'éphémérides
brief: Calcule la trajectoire apparente (temps, RA, Dec, distance) d'un corps du système solaire sur une série d'instants.
keywords: [éphéméride, astrométrie, RA, Dec, système solaire, comète, astéroïde, trajectoire]
related: [Annotation, CatalogAnnotation, PlateSolve, CometAlignment]
icon: calendar-stats
references:
  - "PixInsight — EphemerisGeneration tool reference."
  - "Astropy — astropy.coordinates.get_body and solar_system_ephemeris."
  - "IAU — International Celestial Reference System (ICRS)."
---

## Résumé

`EphemerisGenerator` calcule, pour un corps du système solaire choisi, une série d'instants
également espacés et, pour chacun, sa **position apparente géocentrique** — ascension droite,
déclinaison et distance à la Terre. C'est un process **global de mesure** (pas de fenêtre en
entrée, aucune image produite) : il reproduit le `EphemerisGeneration` de PixInsight, utilisé
pour tracer la trajectoire d'un objet mobile (comète, astéroïde, planète) sur une annotation ou
pour préparer un recalage suivant l'objet plutôt que le champ d'étoiles.

## Cas d'usage

- **Tracer la trajectoire** d'une comète ou d'un astéroïde sur une mosaïque annotée, pour
  vérifier qu'elle correspond au déplacement observé entre les poses.
- **Préparer un `CometAlignment`** : connaître la position attendue du noyau à chaque instant
  de la série pour guider ou vérifier le recalage sur l'objet plutôt que sur les étoiles.
- **Planifier une session** : obtenir la RA/Dec d'une planète à l'heure prévue d'acquisition
  pour cadrer le champ ou vérifier sa visibilité.
- **Recouper une identification** : confirmer qu'un point mobile détecté dans une série
  d'images correspond bien à la position théorique d'un corps connu.

## Fonctionnement

1. La série d'instants est construite à partir de `start` (ISO UTC) par pas fixe de
   `step_hours`, répété `count` fois : $t_i = t_0 + i \cdot \Delta t$.
2. Pour chaque instant, la position du corps choisi (`body`) est calculée avec l'éphéméride
   **intégrée** d'astropy (`solar_system_ephemeris.set("builtin")`, théories analytiques
   type VSOP87/ELP2000 via ERFA) — **aucun téléchargement** de fichier d'éphémérides JPL n'est
   nécessaire, contrairement à `PlateSolve` en mode astrometry.net en ligne.
3. `get_body()` renvoie la position **géocentrique apparente** (corrigée du temps de propagation
   de la lumière depuis la Terre), exprimée dans le référentiel GCRS puis convertie en **ICRS**
   (référentiel céleste international, quasi inertiel) pour obtenir RA/Dec/distance.
4. Chaque ligne calculée (`time`, `ra_deg`, `dec_deg`, `distance_au`) est accumulée dans la
   liste `self.ephemeris`, exposée après exécution pour être consommée par la GUI/annotation ou
   par un script.

## Mathématiques

Pour l'instant $t_i$, l'éphéméride intégrée fournit le vecteur position géocentrique du corps
$\vec r_i = (x_i, y_i, z_i)$ dans le référentiel équatorial ICRS (corrigé du temps de lumière,
la Terre restant fixe à l'origine). Ascension droite, déclinaison et distance s'en déduisent par
passage cartésien → sphérique :

$$
\alpha_i = \operatorname{atan2}(y_i,\, x_i) \bmod 360°, \qquad
\delta_i = \operatorname{atan2}\!\left(z_i,\, \sqrt{x_i^2 + y_i^2}\right), \qquad
d_i = \lVert \vec r_i \rVert.
$$

La suite d'instants échantillonnés est arithmétique :

$$ t_i = t_0 + i\,\Delta t, \qquad i = 0, \dots, \texttt{count} - 1, \qquad
\Delta t = \texttt{step\_hours} \text{ (heures)}. $$

La distance $d_i$ est exprimée en unités astronomiques (UA, $1\,\text{UA} \approx
1{,}496 \times 10^8$ km). La précision dépend de la théorie analytique utilisée par le backend
`"builtin"` d'astropy (VSOP87 pour les planètes, ELP2000 pour la Lune) : de l'ordre de quelques
secondes d'arc à l'échelle du siècle courant, très suffisante pour tracer une trajectoire ou
cadrer un champ, mais **insuffisante pour un plate-solve de précision** millimagnitude/sub-arcsec
(pour lequel PixInsight ou `PlateSolve` s'appuient sur des données astrométriques réelles, pas
sur une théorie analytique).

## Paramètres

- **`body`** — *enum*, défaut `mars`, choix `sun`, `moon`, `mercury`, `venus`, `mars`, `jupiter`,
  `saturn`, `uranus`, `neptune`. Corps du système solaire dont on calcule la trajectoire. Les
  comètes et astéroïdes ne sont **pas** dans cette liste (l'éphéméride intégrée ne couvre que les
  corps majeurs) ; pour un petit corps, calculez ses positions hors process et injectez-les
  manuellement, ou utilisez `CometAlignment` avec une trajectoire fournie séparément.
- **`start`** — *str*, défaut `2026-01-01T00:00:00`. Instant de départ de la série, au format
  ISO 8601 en **UTC** (ex. `2026-03-15T22:30:00`). Aucune conversion de fuseau n'est effectuée :
  fournissez toujours du temps UTC.
- **`step_hours`** — *real*, défaut `24.0`, plage `0.01`–`8760`. Pas de temps entre deux points
  consécutifs, en heures. `8760` correspond à une année ; une valeur sub-horaire convient pour
  suivre un objet à déplacement rapide (astéroïde proche, comète en approche).
- **`count`** — *int*, défaut `10`, plage `1`–`100000`. Nombre de points calculés dans la série.
  Une valeur élevée avec un pas fin peut représenter un volume de calcul non négligeable
  (chaque point interroge l'éphéméride analytique).

## Astuces & pièges

> **Attention** — l'éphéméride `"builtin"` d'astropy est **analytique**, pas une éphéméride
> JPL DE téléchargée : sa précision (secondes d'arc) est adaptée à l'annotation et à la
> planification, pas à un recalage astrométrique de sub-pixel.

> **Note** — `start` doit être en UTC ISO strict. Une chaîne mal formée (fuseau inclus, format
> ambigu) fait échouer `Time(self.start)` côté astropy.

- La position renvoyée est **géocentrique apparente** (vue depuis le centre de la Terre, temps de
  lumière inclus) — pas topocentrique : elle ne tient pas compte de la parallaxe liée au lieu
  d'observation, généralement négligeable sauf pour la Lune ou un astéroïde très proche.
- Le résultat n'est pas une fenêtre image : `execute_global()` renvoie `True` et remplit
  `self.ephemeris`, une liste de dictionnaires `{time, ra_deg, dec_deg, distance_au}` à
  consommer en script ou via l'annotation GUI.
- Pour visualiser la trajectoire tracée sur une image déjà résolue astrométriquement (WCS),
  combinez ce process avec `Annotation` ou `CatalogAnnotation`.

## Voir aussi

- [Annotation](retina-doc://Annotation) — trace une grille RA/Dec ou des repères sur une image résolue.
- [CatalogAnnotation](retina-doc://CatalogAnnotation) — annote une image à partir d'un catalogue de sources.
- [PlateSolve](retina-doc://PlateSolve) — résolution astrométrique (WCS) nécessaire pour projeter une trajectoire sur l'image.
- [CometAlignment](retina-doc://CometAlignment) — recalage sur un objet mobile plutôt que sur le champ d'étoiles.

## Références

- PixInsight — *EphemerisGeneration* tool reference.
- Astropy — `astropy.coordinates.get_body` et `solar_system_ephemeris`.
- IAU — *International Celestial Reference System (ICRS)*.
