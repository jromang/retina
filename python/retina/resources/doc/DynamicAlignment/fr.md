---
id: DynamicAlignment
category: ImageRegistration
title: Alignement dynamique
brief: Recalage manuel par points de contrôle source/cible, avec estimation de transformation géométrique et rééchantillonnage.
keywords: [recalage, points de contrôle, homographie, affine, projective, mosaïque, rééchantillonnage]
related: [StarAlignment, PhaseCorrelationAlignment, FeatureAlignment, MosaicReproject]
icon: target
references:
  - "PixInsight — DynamicAlignment tool reference."
  - "scikit-image — skimage.transform.estimate_transform / warp."
  - "Hartley, R. & Zisserman, A. — Multiple View Geometry in Computer Vision (transformations projectives, DLT)."
---

## Résumé

`DynamicAlignment` est le cœur scriptable du recalage **manuel** : au lieu de détecter des
étoiles automatiquement, il prend des paires de points de contrôle **source → cible** fournies
explicitement (typiquement saisies à la souris par l'outil GUI dynamique du même nom), en
déduit la transformation géométrique qui les fait correspondre, puis rééchantillonne toute
l'image source selon cette transformation. C'est la solution de repli quand `StarAlignment`
échoue — champ pauvre en étoiles, mosaïque avec faible recouvrement, image non stellaire.

## Cas d'usage

- **Recalage de champs pauvres en étoiles** (nébuleuses très étendues, comètes proches du
  premier plan, images planétaires) où la détection automatique manque d'amers fiables.
- **Assemblage de mosaïques** en pointant à la main quelques amers communs entre panneaux
  qui se chevauchent peu.
- **Correction fine après un recalage automatique imparfait** : quelques points ajoutés à la
  main sur des zones mal alignées.
- **Alignement d'images non astronomiques** dans le même pipeline (calibration terrain, cadrage
  d'instruments) où aucun catalogue d'étoiles n'a de sens.

## Fonctionnement

1. Les points `source` et `target` sont fournis comme listes plates `[x0, y0, x1, y1, …]` en
   coordonnées pixels ; ils sont reformés en tableaux `(N, 2)`. Il faut au moins deux paires,
   et autant de points source que de points cible.
2. `skimage.transform.estimate_transform(mode, src, dst)` ajuste, au sens des moindres carrés
   (ou par DLT pour le mode projectif), la transformation qui envoie les points `source` sur
   les points `target`.
3. Si `reference` désigne une vue existante, la géométrie de sortie (largeur/hauteur) est celle
   de cette vue ; sinon on conserve la géométrie de l'image source.
4. Chaque canal est rééchantillonné indépendamment par `skimage.transform.warp` en utilisant la
   **transformation inverse** (cible → source), interpolation bilinéaire (`order=1`), et
   remplissage à zéro (`mode="constant", cval=0.0`) hors du cadre source.
5. Le résultat est écrêté dans `[0, 1]` et reconverti en `float32`.

> **Note** — le recalage s'applique à l'**image entière**, pas seulement à la zone couverte
> par les points : les points ne servent qu'à estimer les paramètres du modèle géométrique.

## Mathématiques

Soient les points source $\{(x_i, y_i)\}_{i=1}^N$ et cible $\{(x_i', y_i')\}_{i=1}^N$. Selon
`mode`, on estime un modèle de transformation homogène $T$ tel que $T(x_i, y_i) \approx (x_i', y_i')$ :

- **`similarity`** (4 degrés de liberté — rotation $\theta$, échelle uniforme $s$, translation
  $(t_x, t_y)$), $N \ge 2$ :
  $$
  \begin{pmatrix} x' \\ y' \end{pmatrix} =
  s \begin{pmatrix} \cos\theta & -\sin\theta \\ \sin\theta & \cos\theta \end{pmatrix}
  \begin{pmatrix} x \\ y \end{pmatrix} + \begin{pmatrix} t_x \\ t_y \end{pmatrix}
  $$
- **`affine`** (6 degrés de liberté), $N \ge 3$ :
  $$
  \begin{pmatrix} x' \\ y' \\ 1 \end{pmatrix} =
  \begin{pmatrix} a_0 & a_1 & a_2 \\ b_0 & b_1 & b_2 \\ 0 & 0 & 1 \end{pmatrix}
  \begin{pmatrix} x \\ y \\ 1 \end{pmatrix}
  $$
- **`projective`** (8 degrés de liberté, homographie), $N \ge 4$ :
  $$
  \begin{pmatrix} x' \\ y' \\ 1 \end{pmatrix} \sim
  \begin{pmatrix} h_0 & h_1 & h_2 \\ h_3 & h_4 & h_5 \\ h_6 & h_7 & 1 \end{pmatrix}
  \begin{pmatrix} x \\ y \\ 1 \end{pmatrix}
  $$
  (coordonnées homogènes, division par la troisième composante après multiplication).

Les paramètres sont estimés au sens des moindres carrés linéaires (`similarity`, `affine`) ou
par la méthode DLT (*Direct Linear Transform*, `projective`). Une fois $T$ connue, le
rééchantillonnage utilise $T^{-1}$ : pour chaque pixel de sortie $(x', y')$, on évalue
$(x, y) = T^{-1}(x', y')$ dans l'image source et on interpole bilinéairement :

$$ I_\text{out}(x', y') = \operatorname{bilerp}\big(I_\text{src},\ T^{-1}(x', y')\big). $$

Avec exactement $N$ égal au minimum requis, l'ajustement est **exact** (résidu nul aux points) ;
au-delà, il est **au sens des moindres carrés** et lisse les imprécisions de pointé.

## Paramètres

- **`source`** — *floatlist*, défaut `[]`. Points source en pixels, liste plate
  `[x0, y0, x1, y1, …]`, dans le système de coordonnées de l'image traitée.
- **`target`** — *floatlist*, défaut `[]`. Points cible correspondants, même format et même
  nombre de points que `source` (appariement par index).
- **`mode`** — *enum*, défaut `affine`, choix `similarity` / `affine` / `projective`. Modèle de
  transformation géométrique à estimer à partir des correspondances.
- **`reference`** — *str*, défaut `""`. Id d'une vue de référence qui fixe la géométrie
  (largeur/hauteur) de l'image de sortie ; si vide, la géométrie de l'image source est conservée.

## Astuces & pièges

> **Attention** — il faut un nombre de points cohérent avec le modèle choisi : 2 minimum pour
> `similarity`, 3 pour `affine`, 4 pour `projective`. En dessous, `estimate_transform` produit
> une transformation mal posée ou lève une erreur.

> **Attention** — les listes `source` et `target` doivent avoir exactement le même nombre de
> points ; un déséquilibre lève une `ValueError` explicite avant tout calcul.

- Répartissez les points sur toute l'image plutôt que dans un coin : cela stabilise
  l'estimation et limite l'erreur d'extrapolation loin des amers.
- Pour un recalage purement stellaire automatique, préférez `StarAlignment` ; réservez
  `DynamicAlignment` aux cas où l'automatique échoue ou où un contrôle point par point est requis.
- Le mode `projective` corrige la perspective (utile en mosaïque grand champ) mais amplifie le
  bruit d'estimation si les points sont peu nombreux ou mal répartis — préférez `affine` quand
  la géométrie le permet.

## Voir aussi

- [StarAlignment](retina-doc://StarAlignment) — recalage automatique par détection d'étoiles.
- [PhaseCorrelationAlignment](retina-doc://PhaseCorrelationAlignment) — recalage sous-pixel sans
  étoiles par corrélation de phase.
- [FeatureAlignment](retina-doc://FeatureAlignment) — recalage robuste par descripteurs ORB et
  RANSAC, sans catalogue.
- [MosaicReproject](retina-doc://MosaicReproject) — assemblage de mosaïques par reprojection WCS.

## Références

- PixInsight — *DynamicAlignment* tool reference.
- scikit-image — *skimage.transform.estimate_transform / warp*.
- Hartley, R. & Zisserman, A. — *Multiple View Geometry in Computer Vision* (transformations
  projectives, DLT).
