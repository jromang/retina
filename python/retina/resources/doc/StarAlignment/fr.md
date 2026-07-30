---
id: StarAlignment
category: ImageRegistration
title: Alignement stellaire
brief: Recale automatiquement une vue sur une référence en appariant des triangles d'étoiles (astroalign).
keywords: [recalage, alignement, astéristes, astroalign, similarité, stacking]
related: [Integration, DynamicAlignment, PhaseCorrelationAlignment, FeatureAlignment]
icon: stars
references:
  - "Beroiz, M. et al. — astroalign: A Python module for astronomical image registration."
  - "PixInsight — StarAlignment tool reference."
---

## Résumé

`StarAlignment` recale géométriquement la vue active sur une **image de référence** (une autre
vue ouverte, désignée par `reference_id`, ou un fichier sur disque via `reference_path`), sans
utiliser d'information WCS. La transformation est estimée automatiquement à partir des étoiles
détectées dans les deux images, via la bibliothèque `astroalign`. C'est l'étape indispensable
avant toute `Integration` : sans recalage précis, l'empilement produit des étoiles dédoublées
ou floues au lieu d'un vrai gain de signal/bruit.

## Cas d'usage

- **Aligner une série de brutes** avant `Integration`, quand la monture a dérivé (dithering,
  suivi imparfait, méridian flip) entre les poses.
- **Recaler des poses prises à des dates différentes** (même objet, cadrage proche) pour
  comparer ou combiner des sessions distinctes.
- **Réaligner un canal ou un filtre** (LRGB, narrowband) capturé séparément, sans dépendre
  d'une solution astrométrique (WCS) préexistante.
- Constituer la brique de base d'un pipeline de **prétraitement batch** scriptable (référence
  fixée une fois, appliquée à tout un lot en console).

## Fonctionnement

1. **Chargement de la référence** — via `_reference()` : soit le tableau pixel d'une autre vue
   déjà ouverte (`reference_id`, résolu via `context.resolve_image_full`), soit un fichier chargé
   depuis le disque (`reference_path`). Une erreur est levée si ni l'un ni l'autre n'est fourni.
2. **Réduction en luminance** — la vue source et la référence sont chacune moyennées sur les
   canaux (`data.mean(axis=2)`) pour obtenir une image 2D en niveaux de gris : la détection
   d'étoiles et l'estimation de la transformation se font sur cette luminance, indépendamment
   de la couleur.
3. **Détection d'étoiles et appariement par astérismes** — `astroalign.find_transform` détecte
   les sources dans les deux luminances, construit pour chaque étoile des **triangles**
   (astérismes) avec ses plus proches voisines, encode chaque triangle par un invariant
   géométrique (rapports de côtés), puis apparie les triangles source/cible dont les invariants
   sont proches. Un schéma type RANSAC filtre les appariements aberrants et ajuste la meilleure
   **transformation de similarité** (rotation + échelle + translation) au sens des moindres
   carrés sur les correspondances retenues.
4. **Rééchantillonnage** — la transformation trouvée est appliquée indépendamment à **chaque
   canal** de l'image source (`astroalign.apply_transform`), qui est rééchantillonnée sur la
   géométrie de la référence. Le résultat est écrêté à `[0, 1]` et renvoyé en `float32`.

> **Note** — la méthode ne requiert **aucune information WCS ni astrométrie préalable** : elle
> fonctionne par reconnaissance de motifs stellaires, comme le ferait un œil humain comparant
> deux champs d'étoiles.

## Mathématiques

`astroalign` représente chaque triplet d'étoiles $(P_1, P_2, P_3)$ par un **invariant** construit
à partir des longueurs de côtés du triangle, ordonnées de façon canonique (côté le plus long en
référence) :

$$ \operatorname{inv}(P_1,P_2,P_3) = \left(\frac{\ell_2}{\ell_1},\ \frac{\ell_3}{\ell_1}\right),
\qquad \ell_1 \ge \ell_2 \ge \ell_3, $$

où $\ell_1,\ell_2,\ell_3$ sont les trois longueurs de côtés. Cet invariant est **indépendant de
la rotation, de la translation et de l'échelle** : deux triangles correspondant à la même
configuration stellaire, vue dans deux images différentes, ont des invariants quasi identiques
même si le champ a tourné ou zoomé entre les deux poses. Les triangles source et cible sont
appariés par recherche de plus proches voisins dans cet espace d'invariants (tolérance $r$), puis
un algorithme robuste de type RANSAC sélectionne le plus grand ensemble d'appariements cohérents
entre eux (erreur de reprojection sous un seuil `PIXEL_TOL`).

La transformation estimée est une **similarité** 2D, qui envoie un point source $\mathbf{x} =
(x, y)$ sur $\mathbf{x}' = (x', y')$ dans le repère de la référence :

$$ \begin{pmatrix} x' \\ y' \end{pmatrix}
   = s \begin{pmatrix} \cos\theta & -\sin\theta \\ \sin\theta & \cos\theta \end{pmatrix}
     \begin{pmatrix} x \\ y \end{pmatrix} + \begin{pmatrix} t_x \\ t_y \end{pmatrix}, $$

avec un facteur d'échelle $s$, un angle de rotation $\theta$ et une translation $(t_x, t_y)$
communs à toute l'image (4 degrés de liberté). Les paramètres sont ajustés au sens des moindres
carrés sur l'ensemble des correspondances d'étoiles retenues comme inliers par RANSAC. Cette
transformation, une fois inversée, est appliquée par interpolation à chaque canal de l'image
source pour produire la sortie sur la grille de la référence.

> **Attention** — une **similarité** ne modèle ni distorsion optique ni projection (pas de
> cisaillement ni de perspective) : pour des champs très larges ou des optiques à forte
> distorsion de bord de champ, un léger désalignement résiduel peut subsister en périphérie.
> `DynamicAlignment` (transformation `affine`/`projective` sur points choisis à la main) permet
> de traiter ces cas.

## Paramètres

- **`reference_id`** — *str*, défaut `""`. Identifiant d'une vue déjà ouverte à utiliser comme
  référence de recalage, résolu via le contexte d'exécution (`context.resolve_image_full`).
- **`reference_path`** — *path*, défaut `""`. Chemin d'un fichier image à charger comme
  référence, utilisé à la place d'une vue ouverte. A priorité sur `reference_id` s'il est renseigné.

> **Note** — l'un des deux paramètres doit être fourni ; si `reference_id` et `reference_path`
> sont tous deux vides, le process lève une `ValueError` explicite.

## Astuces & pièges

> **Attention** — `astroalign` échoue (`MaxIterError` ou `ValueError`) si moins de 3 étoiles
> nettes sont détectées dans l'une des deux images (champ trop pauvre, image trop bruitée ou
> nébulosité sans étoiles ponctuelles). Dans ce cas, préférez `PhaseCorrelationAlignment` (sans
> détection de sources) ou `DynamicAlignment` (points cliqués à la main).

- Choisissez comme référence la pose la **plus nette et la mieux exposée** du lot (meilleur
  FWHM, star trailing minimal) : la qualité des étoiles détectées dans la référence conditionne
  la précision de tout l'appariement.
- La détection et l'estimation se font sur la **luminance** : un fond de ciel très dégradé ou un
  gradient fort peut créer de fausses détections ; un `BackgroundExtraction` préalable (sur une
  copie) améliore parfois la robustesse.
- Le recalage change la géométrie de sortie (dimensions de la référence) : les bords de l'image
  source hors du cadre de la référence sont perdus, et les zones sans recouvrement sont remplies
  de zéros.

## Voir aussi

- [Integration](retina-doc://Integration) — empilement des poses une fois alignées.
- [DynamicAlignment](retina-doc://DynamicAlignment) — recalage manuel par points de contrôle
  (similarité/affine/projective), utile quand la détection automatique échoue.
- [PhaseCorrelationAlignment](retina-doc://PhaseCorrelationAlignment) — recalage par corrélation
  de phase, sans détection d'étoiles.
- [FeatureAlignment](retina-doc://FeatureAlignment) — recalage par points d'intérêt (hors champs
  purement stellaires).

## Références

- Beroiz, M. et al. — *astroalign: A Python module for astronomical image registration*.
- PixInsight — *StarAlignment* tool reference.
