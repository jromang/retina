---
id: MosaicPlanner
category: Astrometry
title: Planificateur de mosaïque
brief: Calcule les pointés d'une mosaïque avant de l'acquérir, et dessine la carte de couverture.
keywords: [mosaïque, planification, tuiles, panneaux, recouvrement, framing, champ, pointé]
related: [MosaicReproject, FindingChart, PlateSolve, SurveyReference]
icon: grid-4x4
references:
  - "Calabretta, M. R. & Greisen, E. W. (2002) — Representations of celestial coordinates in FITS, A&A 395, 1077 (projection TAN)."
---

## Résumé

Tout ce que Retina savait faire des mosaïques allait jusqu'ici **à rebours** :
`detect_panels` retrouve les panneaux dans des poses déjà prises. `MosaicPlanner` remonte la
pente — donnez-lui une cible, le champ de votre capteur et un recouvrement, il rend la liste
des pointés à programmer, plus une carte pour vérifier d'un coup d'œil que l'objet est
réellement couvert.

Process global : il ne lit aucune image et produit une nouvelle fenêtre (la carte), résolue,
donc superposable au reste.

## Cas d'usage

- Cadrer un **grand objet** (Andromède, les Dentelles, la Rosette) qui ne tient pas sur le
  capteur.
- Planifier un **relevé grand champ** d'une région, avec un recouvrement maîtrisé.
- Vérifier *avant* la nuit si 3×2 panneaux suffisent, ou s'il en faut 4×3.

## Fonctionnement

Les centres des tuiles sont posés dans le **plan tangent** de la cible, jamais en ajoutant
des degrés à l'ascension droite. C'est tout l'enjeu : un pas constant en RA rétrécit en
cos δ, si bien qu'à +80° de déclinaison une grille naïve placerait ses tuiles six fois trop
près et ne couvrirait qu'un sixième du champ visé. Près du pôle, « un pas en RA » cesse même
d'avoir un sens.

Le pas vaut `champ × (1 − recouvrement)`, et la grille est centrée sur la cible : la mosaïque
est donc symétrique autour d'elle.

La carte dessine l'**empreinte projetée** de chaque tuile — un quadrilatère, pas un
rectangle. Loin du centre, une tuile est réellement déformée par la projection, et la
dessiner droite promettrait une couverture qu'on n'a pas.

## Paramètres

- **`target`** — *str*. Un nom d'objet résolu par Sesame (`M31`), ou `ra,dec` en degrés.
  `set_center(ra, dec)` depuis la console évite entièrement le réseau.
- **`reference_frame`** — *path*. Un FITS dont l'en-tête porte `XPIXSZ`, `FOCALLEN`,
  `NAXIS1` et `NAXIS2` : le champ s'en déduit. Prenez simplement une pose avec le montage
  que vous comptez employer.
- **`fov_width`**, **`fov_height`** — *real*, en degrés. Champ explicite ; prioritaire.
- **`tiles_x`**, **`tiles_y`** — *int*, la grille.
- **`overlap`** — *real*, en pourcent, défaut `20`.
- **`size`** — *int*, taille de la carte en pixels.
- **`output_path`** — *path*. CSV `name,ra_deg,dec_deg`, que tout planétarium et tout
  séquenceur sait importer.
- **`new_image_id`** — *str*.

## Console

```python
plan = MosaicPlanner(target="M31", reference_frame="/data/une_pose.fits",
                     tiles_x=3, tiles_y=2, overlap=25.0,
                     output_path="/data/m31_panneaux.csv")
app.run(plan)
for panneau in plan.result["panels"]:
    print(panneau["panel"], panneau["ra"], panneau["dec"])
```

## Astuces & pièges

> **Attention** — 20 % de recouvrement est un plancher, pas un luxe. Le recalage a besoin
> d'étoiles **communes** à deux panneaux, et le bord du champ est précisément l'endroit où
> les aberrations optiques et le vignetage sont les pires. Sous 15 %, la couture de
> l'assemblage se voit.

- Le recouvrement s'applique sur les deux axes : 3×2 tuiles à 20 % couvrent environ
  `2,6 × 1,8` champs, pas `3 × 2`.
- La carte est une fenêtre comme une autre : mettez-la à côté d'une référence de survey
  ([SurveyReference](retina-doc://SurveyReference)) en vues liées, pour voir ce qui tombe où.
- Une fois les poses acquises, tout l'aval est automatique : le mode framing du
  pré-traitement détecte les panneaux, intègre chacun d'eux et les assemble avec
  [MosaicReproject](retina-doc://MosaicReproject).

## Voir aussi

- [MosaicReproject](retina-doc://MosaicReproject) — assembler les panneaux une fois acquis.
- [FindingChart](retina-doc://FindingChart) — la même mécanique de carte TAN synthétique.
- [PlateSolve](retina-doc://PlateSolve) — résoudre chaque panneau, ce que l'assemblage exige.
- [SurveyReference](retina-doc://SurveyReference) — voir le vrai ciel sur le champ planifié.

## Références

- Calabretta, M. R. & Greisen, E. W. (2002) — *Representations of celestial coordinates in
  FITS*, A&A 395, 1077.
