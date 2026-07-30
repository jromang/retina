---
id: APASSCatalog
category: Global
title: Catalogue APASS
brief: Interroge le catalogue photométrique APASS DR9 (Vizier II/336) et projette les étoiles du champ en pixels via le WCS.
keywords: [APASS, catalogue, photométrie, Vizier, WCS, calibration couleur, magnitude V]
related: [PlateSolve, GaiaCatalog, PhotometricColorCalibration, CatalogAnnotation]
icon: database
references:
  - "Henden, A. A. et al. — The AAVSO Photometric All-Sky Survey (APASS), DR9."
  - "Vizier catalogue II/336 — APASS DR9."
  - "astroquery.vizier — Vizier query interface."
---

## Résumé

`APASSCatalog` interroge en ligne le catalogue **APASS DR9** (*AAVSO Photometric All-Sky
Survey*, table Vizier `II/336`) pour récupérer les étoiles présentes dans le champ couvert par
la vue active, puis projette leurs coordonnées célestes en positions pixel grâce au WCS de la
fenêtre. C'est un process **de mesure, en lecture seule** : il ne modifie jamais les pixels ni
n'ouvre de nouvelle fenêtre — le résultat est stocké dans `.result` et sert de base à d'autres
outils (annotation, calibration photométrique, sélection d'étoiles de référence).

APASS est un catalogue **photométrique multi-bandes** (Johnson B, V et Sloan g′, r′, i′), ce qui
le rend particulièrement utile pour la **calibration couleur** d'instruments à large bande,
contrairement à Gaia qui ne fournit qu'une seule magnitude photométrique large (`phot_g_mean_mag`).

## Cas d'usage

- **Calibration couleur photométrique** : fournir des magnitudes de référence B/V/g′/r′/i′ pour
  ajuster les coefficients colorimétriques d'une caméra à large bande.
- **Sélection d'étoiles de référence** pour la photométrie différentielle ou l'étalonnage d'un
  instrument.
- **Annotation de champ** : superposer sur l'image les positions et magnitudes des étoiles
  cataloguées (via `CatalogAnnotation`).
- **Validation croisée** d'un plate-solve : comparer les positions attendues des étoiles APASS
  aux positions mesurées dans l'image.

## Fonctionnement

Le process s'appuie sur la classe de base `_CatalogQuery`, partagée avec `GaiaCatalog` :

1. **Prérequis WCS** — la vue doit posséder une solution astrométrique (`view.window.wcs`),
   typiquement produite par `PlateSolve`. Sans WCS, l'exécution échoue explicitement.
2. **Requête réseau** — le centre du champ est calculé en projetant le WCS au centre de
   l'image (`w/2, h/2`), et un rayon de recherche est dérivé de la séparation angulaire entre ce
   centre et le coin `(0, 0)`, plafonné à 3°. Une requête `astroquery.vizier.Vizier` interroge
   la table `II/336` en cône autour de ce centre, filtrée sur `Vmag < mag_limit` et limitée à
   `max_stars` lignes.
3. **Projection en pixels** — chaque étoile retenue `(ra, dec, mag)` est convertie en coordonnées
   image via `wcs.world_to_pixel_values`, puis seules les étoiles dont la position projetée tombe
   **dans les limites de l'image** sont conservées.
4. **Résultat** — un dictionnaire `{"n_stars": int, "stars": [...]}` est stocké dans `.result`,
   chaque entrée portant `ra`, `dec`, `mag` (magnitude V) et les coordonnées pixel `x`, `y`.

Pour les tests headless ou un usage hors ligne, `set_catalog([(ra, dec, mag), ...])` permet
d'injecter directement une liste d'objets et de court-circuiter la requête réseau.

## Mathématiques

Le process n'implémente pas d'algorithme de traitement d'image ; sa seule composante
mathématique est la **géométrie de projection WCS** et le calcul du rayon de recherche.

Le rayon de la requête en cône est la séparation angulaire entre le centre du champ
$c$ (pixel $(w/2, h/2)$ projeté en ciel) et le coin $(0,0)$ également projeté, plafonnée à $3°$ :

$$ r = \min\big(\operatorname{sep}(c,\, \text{coin}_{0,0}),\ 3°\big). $$

Chaque étoile catalogue $(\alpha_i, \delta_i)$ (ascension droite, déclinaison) est reprojetée
en coordonnées pixel via la transformation WCS inverse $W^{-1}$ :

$$ (x_i, y_i) = W^{-1}(\alpha_i, \delta_i). $$

Une étoile est retenue si sa projection tombe dans le cadre image $(H, W)$ :

$$ 0 \le x_i < W \quad\text{et}\quad 0 \le y_i < H. $$

Le filtrage en magnitude est une simple inégalité appliquée côté serveur Vizier :
$V_i < \texttt{mag\_limit}$, ce qui borne la profondeur du catalogue interrogé plutôt que la
liste retournée après projection.

## Paramètres

- **`mag_limit`** — *real*, défaut `16.0`, plage `0`–`22`. Magnitude V limite : seules les
  étoiles APASS plus brillantes que ce seuil sont retenues par la requête Vizier.
- **`max_stars`** — *int*, défaut `1000`, plage `1`–`100000`. Nombre maximal d'étoiles renvoyées
  par la requête (`row_limit` Vizier), avant projection et filtrage sur le cadre image.

## Astuces & pièges

> **Attention** — sans WCS valide sur la fenêtre (`view.window.wcs`), l'appel lève une
> `ValueError` explicite invitant à lancer `PlateSolve` au préalable.

> **Note** — le rayon de recherche est plafonné à 3° : sur un champ très large (grand angle,
> objectif court), la requête peut ne couvrir qu'une partie du cadre. Vérifiez `n_stars` dans
> `.result` si la couverture semble incomplète.

- APASS fournit **B, V, g′, r′, i′** dans la table Vizier `II/336`, mais seule la colonne
  `Vmag` est récupérée ici : pour une calibration multi-bandes complète, adaptez la requête ou
  utilisez `set_catalog(...)` avec vos propres données.
- La requête dépend d'un accès réseau à Vizier ; en environnement hors-ligne ou pour les tests,
  injectez un catalogue explicite via `set_catalog([(ra, dec, mag), ...])`.
- Le résultat ne crée **aucune entrée d'historique** ni de fenêtre : c'est une mesure pure,
  cohérente avec le principe « lecture seule » des process de catalogue.

## Voir aussi

- [PlateSolve](retina-doc://PlateSolve) — calcule le WCS requis avant toute requête catalogue.
- [GaiaCatalog](retina-doc://GaiaCatalog) — équivalent Gaia DR3, une seule bande photométrique large.
- [PhotometricColorCalibration](retina-doc://PhotometricColorCalibration) — calibration couleur
  s'appuyant sur des références catalogue.
- [CatalogAnnotation](retina-doc://CatalogAnnotation) — superpose les étoiles cataloguées sur l'image.

## Références

- Henden, A. A. et al. — *The AAVSO Photometric All-Sky Survey (APASS)*, DR9.
- Vizier catalogue *II/336* — APASS DR9.
- astroquery.vizier — interface de requête Vizier.
