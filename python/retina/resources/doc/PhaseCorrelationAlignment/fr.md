---
id: PhaseCorrelationAlignment
category: ImageRegistration
title: Alignement par corrélation de phase
brief: Recalage sous-pixel sans étoiles par corrélation de phase dans le domaine de Fourier (skimage + scipy).
keywords: [corrélation de phase, recalage, sous-pixel, FFT, planétaire, lucky imaging, translation]
related: [StarAlignment, FeatureAlignment, CometAlignment, DynamicAlignment]
icon: target
references:
  - "Guizar-Sicairos, M., Thurman, S. T., & Fienup, J. R. (2008). Efficient subpixel image registration algorithms. Optics Letters, 33(2), 156–158."
  - "scikit-image — skimage.registration.phase_cross_correlation documentation."
---

## Résumé

`PhaseCorrelationAlignment` estime la **translation globale** entre la vue active et une
référence par corrélation de phase dans le domaine de Fourier
(`skimage.registration.phase_cross_correlation`), avec une précision sous-pixel réglable, puis
translate chaque canal (`scipy.ndimage.shift`). Contrairement à `StarAlignment`, qui apparie des
triangles d'étoiles (astroalign), ce process ne détecte aucun amer : il compare directement les
luminances des deux images, ce qui le rend adapté aux champs **sans étoiles ponctuelles nettes**
(planétaire, lucky imaging) ou trop pauvres en étoiles pour un recalage astrométrique classique.

## Cas d'usage

- Recaler une série d'images ou des frames vidéo planétaires (Jupiter, Saturne, Lune) en lucky
  imaging, où aucune étoile ponctuelle n'est disponible pour un appariement.
- Aligner des poses centrées sur un objet étendu (gros plan de comète, paysage terrestre) sans
  catalogue d'étoiles.
- Corriger une dérive de monture purement translationnelle entre poses consécutives, avec un
  calcul rapide basé sur la FFT.
- Servir de passe de recalage grossière et rapide en amont d'un affinage par `StarAlignment` sur
  un champ mixte.

## Fonctionnement

1. **Résolution de la référence** : le fichier `reference_path` est prioritaire, sinon la vue
   ouverte identifiée par `reference_id` est utilisée (`_resolve_reference`).
2. **Réduction en luminance** : la référence et la vue active sont converties en niveaux de gris
   par moyenne des canaux (`.mean(axis=2)`).
3. **Estimation du décalage global** $(\delta_y,\delta_x)$ via `phase_cross_correlation`, en deux
   temps : un pic entier est d'abord localisé par corrélation de phase FFT, puis affiné par une
   DFT locale suréchantillonnée d'un facteur `upsample` (algorithme de Guizar-Sicairos) pour
   atteindre une précision de $1/\text{upsample}$ pixel sans calculer de FFT complète
   suréchantillonnée.
4. **Translation** du même décalage à chaque canal via `scipy.ndimage.shift` (interpolation
   linéaire, ordre 1, remplissage à 0 hors cadre).
5. **Écrêtage** final des valeurs dans $[0, 1]$.

> **Note** — le modèle est une **translation pure** : il n'y a ni rotation, ni changement
> d'échelle, ni correction de distorsion. Adapté à une dérive de monture ou de turbulence
> atmosphérique, pas à une rotation de champ ou une distorsion optique.

## Mathématiques

Soit $I_1$ la luminance de référence et $I_2$ la luminance de la vue à recaler, de même taille
$N \times N$. Notons $F_1 = \mathcal{F}\{I_1\}$ et $F_2 = \mathcal{F}\{I_2\}$ leurs transformées
de Fourier 2D. Le **spectre de puissance croisée normalisé** est :

$$ R(u,v) = \frac{F_1(u,v)\,\overline{F_2(u,v)}}{\left|F_1(u,v)\,\overline{F_2(u,v)}\right|} $$

Si $I_2$ est une version de $I_1$ translatée de $(\delta_y, \delta_x)$ (à un bruit près), le
théorème du décalage donne $F_2(u,v) = F_1(u,v)\, e^{-2\pi i (u\delta_x + v\delta_y)/N}$, donc
$R$ se réduit à un pur terme de phase, et sa transformée de Fourier inverse

$$ r(x,y) = \mathcal{F}^{-1}\{R\}(x,y) $$

présente un pic quasi-Dirac localisé en $(\delta_y, \delta_x)$. La position du maximum de $|r|$
donne d'abord le **décalage entier**.

Pour la précision sous-pixel (paramètre `upsample`), l'algorithme ne réinterpole pas $I_1$ et
$I_2$ mais recalcule $r$ sur une grille suréchantillonnée d'un facteur $k = \text{upsample}$,
restreinte à un petit voisinage du pic entier, via une **DFT matricielle** (Guizar-Sicairos et
al., 2008) :

$$ r_k(x,y) = \sum_{u,v} R(u,v)\, e^{\,2\pi i \left(\frac{ux}{kN} + \frac{vy}{kN}\right)} $$

évaluée sur quelques points seulement autour du pic entier — coût $O(N^2 \log N + k^2)$ au lieu
de $O(k^2 N^2 \log(kN))$ pour une FFT complète suréchantillonnée. La position du nouveau maximum,
divisée par $k$, donne le décalage $(\delta_y, \delta_x)$ à $1/k$ pixel près.

## Paramètres

- **`reference_id`** — *str*, défaut `""`. Identifiant d'une autre vue ouverte à utiliser comme
  référence de recalage ; ignoré si `reference_path` est renseigné.
- **`reference_path`** — *path*, défaut `""`. Chemin vers un fichier image à charger comme
  référence, **prioritaire** sur `reference_id`.
- **`upsample`** — *int*, défaut `10`, plage `1`–`100`. Facteur de suréchantillonnage de la DFT
  locale : la précision du recalage est de $1/\text{upsample}$ pixel. `upsample = 1` donne un
  recalage au pixel entier (le plus rapide) ; l'augmenter (20–50) améliore la précision
  sous-pixel au prix d'un calcul un peu plus lourd sur le voisinage du pic.

## Astuces & pièges

> **Attention** — toute rotation de champ, tout changement d'échelle ou distorsion résiduelle
> entre les deux images n'est **pas corrigé** par ce process et peut élargir le pic de
> corrélation, dégradant la fiabilité de l'estimation.

> **Note** — `reference_path` et `reference_id` ne se combinent pas utilement : le fichier est
> toujours prioritaire. Si aucun des deux n'est renseigné, le process lève une erreur.

- Fonctionne mieux sur des champs à fort contenu fréquentiel (détails fins, bord net d'un disque
  planétaire) ; une image très floue ou saturée aplatit le pic de corrélation et dégrade
  l'estimation.
- Sur du ciel profond pauvre en structure mais riche en étoiles ponctuelles, `StarAlignment`
  reste généralement plus robuste, et gère nativement rotation et échelle.
- Un `upsample` très élevé (proche de 100) n'apporte un gain réel que si le rapport signal/bruit
  le permet ; au-delà d'un certain seuil, la précision est limitée par le bruit, pas par
  `upsample`.

## Voir aussi

- [StarAlignment](retina-doc://StarAlignment) — recalage stellaire par triangles d'étoiles
  (astroalign), gère rotation et échelle.
- [FeatureAlignment](retina-doc://FeatureAlignment) — recalage par points d'intérêt ORB et
  homographie, sans catalogue d'étoiles.
- [CometAlignment](retina-doc://CometAlignment) — recalage sur un noyau cométaire en mouvement
  propre.
- [DynamicAlignment](retina-doc://DynamicAlignment) — recalage manuel par points de contrôle.

## Références

- Guizar-Sicairos, M., Thurman, S. T., & Fienup, J. R. (2008). *Efficient subpixel image
  registration algorithms*. Optics Letters, 33(2), 156–158.
- scikit-image — *skimage.registration.phase_cross_correlation* documentation.
