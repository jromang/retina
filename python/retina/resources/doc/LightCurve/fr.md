---
id: LightCurve
category: ImageInspection
title: Courbe de lumière
brief: Photométrie différentielle d'une cible sur une série de poses, exportable au format AAVSO.
keywords: [courbe de lumière, photométrie, étoile variable, exoplanète, différentielle, AAVSO, série temporelle, JD]
related: [AperturePhotometry, SubframeSelector, ConeSearch, PlateSolve]
icon: chart-line
references:
  - "AAVSO — spécification du Extended File Format (https://www.aavso.org/aavso-extended-file-format)."
  - "Howell, S. B. — Handbook of CCD Astronomy, ch. 5 (photométrie d'ouverture, techniques différentielles)."
---

## Résumé

`LightCurve` mesure l'éclat d'une cible sur toute une série de poses et en fait une courbe
qu'on peut tracer, exporter et soumettre. C'est le process des étoiles variables et des
transits d'exoplanètes — le terrain où **Siril** est devant tout le monde, PixInsight
compris.

Le process est **global** : il lit une liste de fichiers et ne touche à aucune vue ouverte.

## Cas d'usage

- Suivre une **binaire à éclipses** ou une variable pulsante sur une nuit, et envoyer le
  résultat à l'AAVSO.
- Détecter un **transit d'exoplanète** — quelques millimagnitudes sur quelques heures, ce
  que seule la photométrie différentielle permet depuis le sol.
- Vérifier qu'une **variable soupçonnée** varie vraiment, en la comparant à une étoile de
  contrôle mesurée de la même façon.

## Fonctionnement

Chaque pose est mesurée aux mêmes positions célestes : ouverture circulaire, fond pris dans
un anneau local (le même cœur que
[AperturePhotometry](retina-doc://AperturePhotometry), partagé pour que les deux ne puissent
jamais diverger).

Les positions sont transportées d'une pose à l'autre par l'une de deux voies, essayées dans
cet ordre :

1. le **WCS de l'en-tête**, quand la pose en porte un (les sorties recalées du pipeline le
   propagent) ;
2. sinon, un **appariement d'étoiles** avec la première pose (`astroalign`).

Dans les deux cas, la position prédite est ensuite **recentrée** sur le barycentre local.
C'est ce recentrage, et non la précision du WCS, qui rend la série digne de confiance : une
ouverture décalée de deux pixels perd du flux, et en perd une quantité *variable* d'une pose
à l'autre — ce qui fabrique une variabilité qui n'existe pas.

Chaque pose est datée depuis `DATE-OBS` plus **le demi-temps de pose** : une courbe de
lumière date un flux intégré, et prendre le début décalerait tous les points d'une demi-pose.

## Mesurer une fois, juger autant qu'on veut

Mesurer est cher, juger est gratuit — la même séparation que
[SubframeSelector](retina-doc://SubframeSelector). `measure_raw()` fait la photométrie et la
met en cache **par fichier** ; `evaluate()` en tire les magnitudes en quelques microsecondes.
Changer de mode, réexporter, ou ajouter une nuit à une série existante ne coûte donc rien sur
les poses déjà mesurées.

## Modes de photométrie

- **`ensemble`** (défaut) — la cible est rapportée à la **somme** des flux des étoiles de
  comparaison. Sommer revient à une moyenne pondérée par le flux : une comparaison faible
  pèse peu, et une comparaison qui se révèle variable contamine d'autant moins.
- **`single`** — contre la première comparaison seule. Utile quand le champ n'en offre
  qu'une convenable.
- **`instrumental`** — magnitude brute de la cible, non corrigée. Diagnostic uniquement :
  elle suit la transparence du ciel, la masse d'air et la buée sur le correcteur bien plus
  qu'elle ne suit l'étoile.

Si **toutes** les comparaisons portent une magnitude catalogue (la troisième valeur de leur
désignation), la sortie est ramenée à l'échelle standard et l'export AAVSO déclare
`MTYPE=STD` ; sinon elle reste différentielle et déclare `DIF`. Annoncer une magnitude
standard sans référence catalogue serait une fausse déclaration : le process ne le fait
jamais en silence.

## Désigner les étoiles

Deux syntaxes, séparées par `;` :

- `ra,dec` ou `ra,dec,mag` — en degrés. C'est ce que donne une carte AAVSO, et cela survit à
  une rotation de champ.
- `x:y` — en pixels **de la première pose**, pour une série sans solution astrométrique.

Depuis la console, `set_stars()` est plus commode et écrit les mêmes paramètres :

```python
courbe = LightCurve(frames=sorted(glob("/data/V1234/*.fits")))
courbe.set_stars(target=(210.51, 33.02),
                 comparisons=[(210.48, 33.05, 11.42), (210.55, 32.99, 12.08)],
                 check=(210.60, 33.11))
courbe.output_aavso = "/data/V1234/aavso.txt"
app.run(courbe)
```

## Paramètres

- **`frames`** — *pathlist*. La série, dans n'importe quel ordre (les points sont triés par
  date).
- **`target`**, **`comparisons`**, **`check`** — *str*. Voir ci-dessus. L'étoile de contrôle
  est mesurée exactement comme la cible mais ne sert jamais à la corriger : **sa platitude
  est la preuve que la série est saine**.
- **`mode`** — *enum*, défaut `ensemble`.
- **`aperture_radius`**, **`annulus_inner`**, **`annulus_outer`** — *real*, en pixels.
- **`channel`** — *int*, défaut `-1` (luminance).
- **`matching`** — *enum*, défaut `auto` (WCS puis appariement) ; `wcs` refuse une pose sans
  solution plutôt que de retomber en silence.
- **`recenter`** — *bool*, défaut vrai.
- **`use_cache`** — *bool*, défaut vrai.
- **`obscode`**, **`filter`**, **`chart`**, **`notes`** — *str*, champs d'en-tête AAVSO.
  `notes` sert aussi de nom d'étoile dans l'export.
- **`output_csv`**, **`output_aavso`** — *path*. Écrits depuis le domaine, donc depuis un
  script — le bouton de l'interface ne fera jamais que les renseigner.

## Astuces & pièges

> **Attention** — déclarez toujours une **étoile de contrôle**. Sans elle, rien ne distingue
> une vraie variation d'une ouverture qui dérive, d'un passage nuageux, ou d'une comparaison
> elle-même variable. Une courbe de contrôle plate est ce qui rend la courbe de la cible
> croyable.

> **Note** — les dates sont en **JD**, pas en BJD. La correction barycentrique demande la
> position de l'observateur et celle de la cible, et le format AAVSO accepte le JD
> (`#DATE=JD`). Siril s'arrête au même endroit.

- L'ouverture doit valoir environ 2 à 3 fois la FWHM : trop petite, elle perd une fraction du
  flux qui dépend du seeing ; trop grande, elle ramasse du bruit de fond et les voisines.
- Une pose sans `DATE-OBS` est mesurée et reste dans `.result`, mais elle est **omise** de
  l'export AAVSO : une observation sans instant n'en est pas une.
- Les comparaisons doivent encadrer la cible en éclat et en couleur, et se trouver dans la
  même région du champ.

## Voir aussi

- [AperturePhotometry](retina-doc://AperturePhotometry) — la même mesure sur une image
  unique, avec détection automatique des sources.
- [ConeSearch](retina-doc://ConeSearch) — identifier ce qu'il y a dans le champ, y compris
  la variable qu'on cherche.
- [SubframeSelector](retina-doc://SubframeSelector) — la même conception mesurer-puis-juger,
  appliquée à la qualité des poses.
- [PlateSolve](retina-doc://PlateSolve) — obtenir le WCS qui rend possible la désignation
  céleste.

## Références

- AAVSO — spécification du *Extended File Format*.
- Howell, S. B. — *Handbook of CCD Astronomy*, ch. 5.
