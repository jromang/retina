---
id: FeatureAlignment
category: ImageRegistration
title: Recalage par points d'intérêt (ORB)
brief: Recale une vue sur une référence par appariement de descripteurs ORB et homographie RANSAC — sans catalogue stellaire.
keywords: [recalage, ORB, homographie, RANSAC, OpenCV, mosaïque, non stellaire]
related: [StarAlignment, PhaseCorrelationAlignment, DynamicAlignment, MosaicReproject]
icon: target
references:
  - "Rublee, E. et al. — ORB: An efficient alternative to SIFT or SURF (ICCV 2011)."
  - "OpenCV — ORB, BFMatcher, findHomography (RANSAC), warpPerspective."
  - "Fischler, M. A. & Bolles, R. C. — Random Sample Consensus (RANSAC), 1981."
---

## Résumé

`FeatureAlignment` recale la vue active sur une image de référence en détectant des **points
d'intérêt ORB** (Oriented FAST and Rotated BRIEF), en appariant leurs descripteurs binaires puis
en estimant une **homographie robuste** (RANSAC) qui ramène la géométrie de la source sur celle
de la référence. Contrairement à `StarAlignment` (astroalign, basé sur des triangles d'étoiles),
il ne suppose **aucun catalogue d'étoiles ponctuelles** : il fonctionne sur n'importe quelle
texture contrastée — paysages, panoramas terrestres, mosaïques planétaires ou tout champ où le
recalage stellaire échoue faute d'amers exploitables.

## Cas d'usage

- **Champs non stellaires** : paysages nocturnes, éléments de premier plan, cibles planétaires
  étendues, où `StarAlignment` n'a pas de motif stellaire à apparier.
- **Mosaïques terrestres ou proches** dont le chevauchement contient des détails texturés
  (reliefs, structures) plutôt que des étoiles ponctuelles.
- **Secours** quand `StarAlignment` échoue (champ trop pauvre en étoiles, forte distorsion,
  rotation/zoom entre poses) : l'homographie ORB tolère rotation, échelle et perspective.
- Recalage de vues issues d'**instruments ou d'optiques différents** produisant une déformation
  projective entre la source et la référence.

## Fonctionnement

Le traitement se déroule en quatre étapes, sur les luminances (moyenne des canaux) converties en
niveaux de gris 8 bits :

1. **Détection ORB** : le détecteur ORB extrait jusqu'à `max_features` points d'intérêt dans la
   vue source et dans la référence, chacun assorti d'un descripteur binaire (256 bits) invariant
   en rotation.
2. **Appariement** : un `BFMatcher` en distance de Hamming, avec `crossCheck` (un point source
   n'est retenu que si son meilleur match référence le désigne aussi en retour), apparie les
   descripteurs des deux images ; les paires sont triées par distance croissante.
3. **Estimation d'homographie** : `cv2.findHomography` avec RANSAC (seuil de reprojection 5 px)
   cherche la transformation projective $3\times3$ qui explique le plus grand sous-ensemble
   cohérent d'appariements, en écartant les faux positifs (outliers).
4. **Rééchantillonnage** : `cv2.warpPerspective` applique l'homographie à chaque canal
   indépendamment (interpolation bilinéaire), en sortie à la géométrie de la référence.

Le process échoue explicitement (erreur) si moins de 4 points sont détectés dans l'une des deux
images, ou si moins de 4 appariements survivent, ou si l'homographie n'est pas estimable — 4
correspondances non colinéaires sont le minimum théorique pour fixer une transformation
projective à 8 degrés de liberté.

## Mathématiques

Une **homographie** est une transformation projective $3\times3$ à échelle près, qui envoie un
point image $(x, y)$ de la source sur $(x', y')$ dans la référence via des coordonnées
homogènes :

$$
\begin{pmatrix} x' \\ y' \\ 1 \end{pmatrix} \sim
H \begin{pmatrix} x \\ y \\ 1 \end{pmatrix}, \qquad
H = \begin{pmatrix} h_{11} & h_{12} & h_{13} \\ h_{21} & h_{22} & h_{23} \\
h_{31} & h_{32} & 1 \end{pmatrix}
$$

soit, après division par la coordonnée homogène :

$$
x' = \frac{h_{11}x + h_{12}y + h_{13}}{h_{31}x + h_{32}y + 1}, \qquad
y' = \frac{h_{21}x + h_{22}y + h_{23}}{h_{31}x + h_{32}y + 1}.
$$

$H$ possède 8 degrés de liberté (le facteur d'échelle global est fixé), donc **4 correspondances
de points non colinéaires** suffisent en théorie à la déterminer. En pratique, les appariements
ORB contiennent des faux positifs : **RANSAC** tire répétitivement des échantillons minimaux de
4 paires, calcule l'homographie candidate, puis compte les appariements dont l'erreur de
reprojection reste sous le seuil $\tau$ (ici 5 pixels) :

$$
\text{inliers}(H) = \Big\{\, i \;:\; \big\lVert \pi(H\, \mathbf{p}_i) - \mathbf{p}_i' \big\rVert_2
\le \tau \,\Big\}
$$

où $\pi(\cdot)$ est la projection homogène → cartésienne. L'homographie retenue est celle qui
maximise $|\text{inliers}(H)|$, éventuellement raffinée par moindres carrés sur ces seuls
inliers. Le rééchantillonnage final applique $H^{-1}$ pixel par pixel (par canal) avec
interpolation bilinéaire pour peupler la grille de sortie.

## Paramètres

- **`reference_id`** — *str*, défaut `""`. Identifiant de la vue de référence ouverte sur laquelle
  aligner la vue active. Ignoré si `reference_path` est renseigné.
- **`reference_path`** — *path*, défaut `""`. Chemin d'un fichier de référence à charger
  directement (prioritaire sur `reference_id`). Pratique pour aligner sur un fichier hors session.
- **`max_features`** — *int*, défaut `2000`, plage `50`–`20000`. Nombre maximal de points ORB
  extraits par image. Plus de points augmente les chances de trouver assez d'appariements fiables
  sur des champs pauvres en texture, au prix d'un calcul plus long.

## Astuces & pièges

> **Attention** — le seuil RANSAC (5 px, fixe) et `max_features` sont les seuls leviers exposés :
> sur une image très bruitée ou peu texturée, augmentez `max_features` avant de conclure à un
> échec d'alignement.

> **Note** — l'homographie est une transformation **projective générale** (elle peut modéliser
> une perspective), contrairement à la similarité rigide implicite de `StarAlignment`. Sur un champ
> purement stellaire sans distorsion perspective, préférez `StarAlignment`, plus robuste et
> spécifiquement calibrée sur des triangles d'étoiles.

- Convertissez d'abord en niveaux de gris cohérents : le process moyenne les canaux en interne,
  donc un fond de ciel très coloré ou un canal saturé peut dégrader le contraste utile à ORB.
- Si l'erreur « pas assez de points ORB appariables » survient sur un champ stellaire, essayez
  plutôt `StarAlignment` (triangles d'étoiles) ou `PhaseCorrelationAlignment` (translation pure).
- Pour des correspondances saisies manuellement (cas où ORB échoue franchement), voir
  `DynamicAlignment`.

## Voir aussi

- [StarAlignment](retina-doc://StarAlignment) — recalage automatique par triangles d'étoiles (astroalign).
- [PhaseCorrelationAlignment](retina-doc://PhaseCorrelationAlignment) — recalage en translation pure, sous-pixel, sans étoiles.
- [DynamicAlignment](retina-doc://DynamicAlignment) — recalage par points de contrôle saisis manuellement.
- [MosaicReproject](retina-doc://MosaicReproject) — assemblage de mosaïques via reprojection WCS.

## Références

- Rublee, E. et al. — *ORB: An efficient alternative to SIFT or SURF* (ICCV 2011).
- OpenCV — *ORB*, *BFMatcher*, *findHomography* (RANSAC), *warpPerspective*.
- Fischler, M. A. & Bolles, R. C. — *Random Sample Consensus* (RANSAC), 1981.
