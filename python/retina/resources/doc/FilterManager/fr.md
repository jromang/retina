---
id: FilterManager
category: ColorCalibration
title: Gestionnaire de courbes spectrales
brief: Consulte, ajoute et retire les courbes de filtres, de rendement de capteur et de blanc de référence.
keywords: [filtre, capteur, rendement quantique, spectre, SPCC, calibration couleur, transmission]
related: [SpectrophotometricColorCalibration, PhotometricColorCalibration, ColorCalibration]
icon: adjustments-horizontal
references:
  - "siril-spcc-database — base communautaire de courbes de filtres et de capteurs (GPL-3)."
---

## Résumé

`FilterManager` est le pendant scriptable de la base de courbes spectrales dont se sert
[SpectrophotometricColorCalibration](retina-doc://SpectrophotometricColorCalibration). Il
répond à trois questions : **qu'est-ce que j'ai**, **à quoi ressemble cette courbe**, et
**comment j'ajoute la mienne**.

Trois familles de courbes :

| `kind` | Ce que c'est |
|---|---|
| `filter` | Transmission d'un filtre, en fraction de 0 à 1. |
| `sensor` | Rendement quantique d'un capteur, même échelle. |
| `white_reference` | Un spectre qu'on décrète neutre — galaxie spirale moyenne, étoile de type solaire… |

## D'où viennent les courbes embarquées

De la base [siril-spcc-database](https://gitlab.com/free-astro/siril-spcc-database), sous
**GPL-3** donc compatible avec la licence de Retina, relevée et vérifiée par la communauté
Siril à partir des documents constructeurs. Chaque fichier cite sa source et sa licence dans
son en-tête ; `action = show` vous les rend.

Retina en embarque un **sous-ensemble** — les capteurs CMOS courants, les jeux RGB des
principaux fabricants, quelques références de blanc. Le reste s'ajoute par `action = add`.

Les filtres à **bande étroite** ne sont volontairement pas dans la base : une bande de 3 ou
7 nm est mieux décrite par sa longueur d'onde centrale et sa largeur (mode `narrowband` du
SPCC) que par une courbe relevée sur un graphique scanné.

## Vos courbes passent devant

Une courbe que vous ajoutez sous un identifiant **déjà embarqué** le masque : c'est ainsi
qu'on corrige une courbe qu'on juge fausse sans toucher à l'installation. La retirer
(`action = remove`) fait réapparaître l'embarquée. Une courbe embarquée, elle, ne se supprime
pas — la demande lève, plutôt que de faire silencieusement rien.

Vos fichiers vivent sous `<config>/spectra/{filters,sensors,whiteref}/`, en CSV à deux
colonnes. Rien n'empêche de les éditer à la main : c'est même l'intérêt du format.

## Paramètres

- **`action`** — *enum* `list` | `show` | `add` | `remove`, défaut `list`.
- **`kind`** — *enum* `filter` | `sensor` | `white_reference`, défaut `filter`.
- **`name`** — *str*. L'identifiant de la courbe (le nom de fichier sans extension).
- **`label`** — *str*. Nom lisible, pour `add`.
- **`channel`** — *str*. Canal associé (`red`, `green`, `blue`, `lum`…), pour `add`.
- **`points`** — *floatlist*. La courbe, à plat : `[λ₁, v₁, λ₂, v₂, …]`, longueurs d'onde en
  nanomètres et valeurs en fraction.

Le résultat est dans `.result` — c'est un process de mesure, il ne transforme aucune image.

## Exemples

```python
# Ce qui est disponible
fm = FilterManager(action='list', kind='sensor')
fm.execute_global(app)
print([c['id'] for c in fm.result['curves']])

# Ajouter la courbe de son filtre
FilterManager(action='add', kind='filter', name='mon_rouge', label='Mon R',
              channel='red',
              points=[580.0, 0.02, 600.0, 0.9, 680.0, 0.92, 700.0, 0.05]
              ).execute_global(app)
```

## Astuces & pièges

> **Échelle des valeurs** : les documents constructeurs donnent tantôt des pourcents, tantôt
> des fractions. Retina ramène tout en fraction au chargement — une courbe dont le maximum
> dépasse 1,5 est considérée comme exprimée en pourcents. Inutile donc de convertir vous-même,
> mais ne mélangez pas les deux dans un même fichier.

- Une courbe demande au moins **deux points**. Hors de son support, la transmission est nulle
  et non prolongée : couvrez toute la bande utile, sinon vous amputez la réponse du canal.
- Le nom de fichier est l'identifiant : sans espace, en minuscules, c'est plus commode.

## Voir aussi

- [SpectrophotometricColorCalibration](retina-doc://SpectrophotometricColorCalibration) — le
  consommateur de ces courbes.
- [PhotometricColorCalibration](retina-doc://PhotometricColorCalibration) — la version sans
  courbes, sur les seules magnitudes Gaia.

## Références

- siril-spcc-database — base communautaire de courbes de filtres et de capteurs (GPL-3).
