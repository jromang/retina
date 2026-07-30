---
id: PlateSolve
category: Astrometry
title: Résolution astrométrique (Plate Solving)
brief: Détecte les étoiles du champ et résout sa solution astrométrique (WCS), hors ligne ou via l'API Astrometry.net.
keywords: [astrométrie, plate solving, WCS, astrometry.net, quads, index, RA/Dec, échelle de plaque]
related: [Annotation, CatalogAnnotation, StarAlignment, GaiaCatalog]
icon: map-pin
references:
  - "Lang, D. et al. — Astrometry.net: Blind astrometric calibration of arbitrary astronomical images (AJ, 2010)."
  - "astrometry (PyPI) — moteur de résolution hors ligne, bindings Python du solveur Astrometry.net."
  - "astroquery.astrometry_net — client de l'API web Astrometry.net."
  - "photutils — DAOStarFinder, détection de sources ponctuelles."
---

## Résumé

`PlateSolve` établit la correspondance entre les pixels de l'image et les coordonnées célestes
(ascension droite / déclinaison) en identifiant les étoiles du champ sur un catalogue de référence.
Le résultat — une solution **WCS** (World Coordinate System) — est rangé sur `window.wcs` ; les
pixels ne sont **jamais modifiés**. Deux backends sont disponibles : `astrometry`, moteur **hors
ligne** en pur Python s'appuyant sur des fichiers d'index téléchargés une fois puis mis en cache
(défaut), et `astrometry_net`, qui interroge le **service web** Astrometry.net via `astroquery`
(nécessite une clé API et une connexion).

## Cas d'usage

- Obtenir une **solution WCS** pour ensuite tracer une grille RA/Dec avec `Annotation`, ou
  superposer un catalogue d'étoiles avec `CatalogAnnotation`.
- Identifier avec précision le **cadrage** d'une image dont les coordonnées de pointage sont
  inconnues ou approximatives (dérive de monture, image reçue sans métadonnées).
- Mesurer l'**échelle de plaque** (arcsec/pixel) et l'orientation réelle du capteur.
- Fournir le référentiel céleste nécessaire aux traitements photométriques ou aux requêtes de
  catalogue (`GaiaCatalog`, `APASSCatalog`) centrées sur le champ observé.

## Fonctionnement

1. **Détection d'étoiles** — la luminance (moyenne des canaux) est analysée par
   `DAOStarFinder` (photutils) après estimation robuste du fond par statistiques
   sigma-clippées (médiane, écart-type, `sigma=3`). Seuil de détection : 5σ, FWHM stellaire
   supposée : 3 px. Les sources sont triées par flux décroissant et tronquées à `max_stars`
   pour limiter la charge du solveur (trop d'étoiles → explosion combinatoire).
2. **Backend hors ligne (`astrometry`)** — sélectionne la série d'index (`series`, p. ex.
   Tycho-2 `4200`, fiable et hébergée sur `data.astrometry.net`, ou Gaia `5200`, plus lourde
   et hébergée sur NERSC), télécharge dans `cache_dir` (par défaut
   `~/.cache/retina/astrometry-indexes`) les fichiers d'index manquants pour les `scales`
   demandées, puis lance le `Solver` sur la liste d'étoiles pixel. Un `SizeHint`
   (`scale_low`/`scale_high`) et un `PositionHint` (`ra`/`dec`/`radius`) restreignent
   optionnellement l'espace de recherche. En l'absence d'appariement, une erreur est levée.
3. **Backend en ligne (`astrometry_net`)** — envoie la liste d'étoiles pixel et les
   dimensions de l'image au service web via `astroquery.astrometry_net.AstrometryNet`
   (clé API obligatoire), avec bornes d'échelle optionnelles et `timeout`. Le header FITS
   retourné est converti en objet `astropy.wcs.WCS`.
4. La solution WCS est affectée à `view.window.wcs`. C'est un process de **lecture/analyse**
   pur : aucune entrée d'historique n'est poussée, les pixels restent inchangés.

## Mathématiques

**Appariement par géométrie de quads.** Le moteur Astrometry.net (backends hors ligne et en
ligne partagent le même principe) ne compare pas des motifs bruts d'étoiles mais des
**invariants géométriques**. Pour chaque groupe de 4 étoiles (« quad »), les deux plus
éloignées définissent la diagonale d'un repère local normalisé (échelle et rotation
éliminées) ; les deux autres étoiles y prennent des coordonnées $(x_1, y_1, x_2, y_2) \in
[0,1]^4$ qui forment un **code de hachage** indépendant de la translation, de l'échelle et de
la rotation de l'image. Ce code est recherché (arbre kd) parmi les quads précalculés de la
série d'index choisie ; chaque candidat est ensuite **vérifié** en testant si un grand nombre
d'autres étoiles détectées s'alignent avec le catalogue à la position/l'échelle proposées
(test bayésien de cohérence), ce qui élimine les faux positifs même à faible nombre d'étoiles.

**Projection gnomonique (TAN).** Une fois le point central $(\alpha_0, \delta_0)$ et la
matrice `CD` (rotation + échelle) déterminés, la solution WCS relie pixel $(x, y)$ et
coordonnées standard $(\xi, \eta)$ par :

$$ \begin{pmatrix}\xi\\ \eta\end{pmatrix} =
   \begin{pmatrix}CD_{11}&CD_{12}\\ CD_{21}&CD_{22}\end{pmatrix}
   \begin{pmatrix}x-x_0\\ y-y_0\end{pmatrix}, $$

puis la déprojection gnomonique donne les coordonnées célestes :

$$ \alpha = \alpha_0 + \arctan\!\left(\frac{\xi}{\cos\delta_0 - \eta\sin\delta_0}\right), \qquad
   \delta = \arcsin\!\left(\frac{\sin\delta_0 + \eta\cos\delta_0}{\sqrt{1+\xi^2+\eta^2}}\right). $$

L'**échelle de plaque** locale (arcsec/pixel) vaut approximativement $3600 \cdot
\sqrt{\lvert \det(CD)\rvert}$ (en degrés/pixel avant conversion) : c'est la grandeur que
bornent `scale_low`/`scale_high` pour accélérer et fiabiliser la recherche.

## Paramètres

- **`backend`** — *enum*, défaut `astrometry`, choix `astrometry` / `astrometry_net`. Moteur de
  résolution : hors ligne (index locaux) ou service web Astrometry.net.
- **`series`** — *enum*, défaut `4200`, choix `4100`, `4200`, `5000`, `5200`, `5200_heavy`,
  `6000`, `6100`. Série de fichiers d'index à utiliser en mode hors ligne (backend `astrometry`).
- **`scales`** — *intlist*, défaut `[8, 9, 10, 11]`. Échelles d'index (identifiants Astrometry.net)
  à télécharger/utiliser, à adapter au champ (FOV) de l'image — `[8-11]` couvre environ 30′–120′.
- **`cache_dir`** — *path*, défaut `""`. Dossier de cache des fichiers d'index hors ligne ; vide
  = `~/.cache/retina/astrometry-indexes`.
- **`ra`** — *real*, défaut `0.0`, plage `0`–`360`. Ascension droite approximative du centre du
  champ, en degrés (`0` = recherche à l'aveugle).
- **`dec`** — *real*, défaut `0.0`, plage `-90`–`90`. Déclinaison approximative du centre, en degrés.
- **`radius`** — *real*, défaut `0.0`, plage `0`–`180`. Rayon de recherche autour de `ra`/`dec`, en
  degrés (`0` = pas de contrainte de position, recherche aveugle).
- **`scale_low`** — *real*, défaut `0.0`, plage `0`–`3600`. Échelle minimale attendue, en
  arcsec/pixel (`0` = pas de borne basse).
- **`scale_high`** — *real*, défaut `0.0`, plage `0`–`3600`. Échelle maximale attendue, en
  arcsec/pixel (`0` = pas de borne haute).
- **`max_stars`** — *int*, défaut `100`, plage `10`–`1000`. Nombre maximal d'étoiles (les plus
  brillantes) transmises au solveur.
- **`api_key`** — *str*, défaut `""`. Clé API Astrometry.net, requise uniquement par le backend
  en ligne (`astrometry_net`).
- **`timeout`** — *int*, défaut `120`, plage `30`–`1200`. Délai maximal (secondes) accordé à la
  résolution en ligne avant échec.

## Astuces & pièges

> **Attention** — moins de 10 étoiles détectées font échouer le process avec une erreur
> explicite. Sur des champs pauvres en étoiles (nébuleuse pleine cadre très étirée, recadrage
> serré) réduisez le seuil de détection en amont ou fournissez une image moins agressivement
> traitée.

> **Note** — le premier appel au backend hors ligne télécharge les fichiers d'index manquants
> (connexion requise une seule fois) ; les résolutions suivantes sont **100 % hors ligne**. La
> série `4200` (Tycho-2) est fiable et rapide à télécharger ; `5200`/`5200_heavy` (Gaia) sont
> plus complètes mais plus lourdes et hébergées ailleurs (NERSC).

- Renseigner `ra`/`dec`/`radius` et `scale_low`/`scale_high` restreint fortement l'espace de
  recherche : la résolution est bien plus rapide et fiable qu'en mode totalement aveugle.
- Choisissez les `scales` d'index en fonction du champ de vue réel de l'image ; un mauvais
  choix d'échelle d'index empêche tout appariement même avec de bonnes étoiles.
- Ne montez pas `max_stars` sans raison : au-delà d'un certain nombre, le temps de résolution
  explose sans gain notable de fiabilité.
- Le WCS est stocké sur la **fenêtre** (`window.wcs`), pas sur la vue : lancer `PlateSolve` sur
  une preview exige tout de même que la vue appartienne à une fenêtre.

## Voir aussi

- [Annotation](retina-doc://Annotation) — grille RA/Dec tracée à partir du WCS obtenu ici.
- [CatalogAnnotation](retina-doc://CatalogAnnotation) — superpose un catalogue d'étoiles via ce WCS.
- [StarAlignment](retina-doc://StarAlignment) — recalage inter-images fondé sur les étoiles.
- [GaiaCatalog](retina-doc://GaiaCatalog) — interrogation du catalogue Gaia sur le champ résolu.

## Références

- Lang, D. et al. — *Astrometry.net: Blind astrometric calibration of arbitrary astronomical
  images* (AJ, 2010).
- astrometry (PyPI) — moteur de résolution hors ligne, bindings Python du solveur Astrometry.net.
- astroquery.astrometry_net — client de l'API web Astrometry.net.
- photutils — *DAOStarFinder*, détection de sources ponctuelles.
