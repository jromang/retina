---
id: ConeSearch
category: Global
title: Recherche par cône
brief: Liste les objets nommés du champ depuis SIMBAD, avec leur type et leur magnitude.
keywords: [SIMBAD, recherche par cône, identification, type d'objet, catalogue, annotation, étoile variable]
related: [GaiaCatalog, APASSCatalog, CatalogAnnotation, LightCurve, PlateSolve]
icon: list-details
references:
  - "Wenger, M. et al. (2000) — The SIMBAD astronomical database, A&AS 143, 9."
  - "CDS Strasbourg — SIMBAD (https://simbad.cds.unistra.fr)."
---

## Résumé

`GaiaCatalog` et `APASSCatalog` rendent des positions et des magnitudes ; ils ne savent pas
qu'une de ces sources s'appelle M51 et qu'une autre est une étoile variable. `ConeSearch`
ajoute précisément cela : un **nom**, un **type d'objet** et une magnitude, demandés à
SIMBAD pour le champ que couvre la solution astrométrique de la vue.

Lecture seule : le process mesure, il ne touche pas aux pixels. Il exige un WCS
([PlateSolve](retina-doc://PlateSolve), ou un fichier qui en porte déjà un).

## Cas d'usage

- Dire **ce qu'on a photographié** — les galaxies, nébuleuses et amas tombés dans le champ,
  par leur nom.
- Trouver la **cible d'une courbe de lumière** : filtrez sur `V*` et vous obtenez les
  étoiles variables du champ, avec les coordonnées à coller dans
  [LightCurve](retina-doc://LightCurve).
- Préparer une annotation : passez le résultat à
  [CatalogAnnotation](retina-doc://CatalogAnnotation) pour dessiner les objets identifiés.

## Fonctionnement

Le centre de la vue est converti en coordonnées célestes, un cône de `radius` degrés est
demandé à SIMBAD, et chaque objet rendu est reprojeté en pixels par le même WCS. Ceux qui
tombent hors du cadre sont écartés — le cône est circulaire, le cadre ne l'est pas.

`radius = 0` (le défaut) prend la **demi-diagonale du champ**, plafonnée à 5° : c'est le plus
petit cône qui couvre à coup sûr le cadre, et un cône beaucoup plus large rendrait des
milliers d'objets pour les jeter juste après projection.

## Paramètres

- **`radius`** — *real*, en degrés, défaut `0` (le champ lui-même).
- **`max_objects`** — *int*, défaut `200`.
- **`object_types`** — *str*, **préfixes** de `otype` SIMBAD séparés par des virgules ; vide
  garde tout. Des préfixes plutôt que des valeurs exactes parce que les types de SIMBAD sont
  hiérarchiques : `G` attrape `G`, `GiG`, `GiC`, `IG`…, et `V*` attrape toutes les sortes
  d'étoiles variables.

## Résultat

`.result` contient `{n_objects, objects, columns}`, chaque objet portant `name`, `ra`,
`dec`, `otype`, `mag` (parfois `None` — SIMBAD n'a pas de magnitude V pour tout) et sa
position pixel `x`, `y`.

## Console

```python
recherche = ConeSearch(object_types="V*")
recherche.execute_on(app.active_view)
for objet in recherche.result["objects"]:
    print(objet["name"], objet["otype"], objet["ra"], objet["dec"])
```

## Astuces & pièges

> **Note** — SIMBAD recense ce qui a été **publié**. Une absence signifie que personne n'a
> catalogué l'objet, pas qu'il n'y a rien. Pour un catalogue d'étoiles systématique, passez
> par [GaiaCatalog](retina-doc://GaiaCatalog).

- La requête passe par le réseau et n'est pas mise en cache : sur un grand champ avec un
  `max_objects` élevé, elle prend quelques secondes.
- `set_objects([...])` injecte une liste directement — c'est ainsi que les tests tournent
  sans toucher au réseau, et ainsi qu'on travaille hors ligne depuis un catalogue enregistré.

## Voir aussi

- [GaiaCatalog](retina-doc://GaiaCatalog) — catalogue d'étoiles systématique, photométrie
  précise.
- [APASSCatalog](retina-doc://APASSCatalog) — magnitudes V, utiles comme étoiles de
  comparaison.
- [CatalogAnnotation](retina-doc://CatalogAnnotation) — dessiner un catalogue sur l'image.
- [LightCurve](retina-doc://LightCurve) — mesurer l'une des variables qu'on vient de trouver.

## Références

- Wenger, M. et al. (2000) — *The SIMBAD astronomical database*, A&AS 143, 9.
- CDS Strasbourg — SIMBAD.
