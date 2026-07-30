---
id: CometAlignment
category: ImageRegistration
title: Alignement sur une comète
brief: Empile des frames en compensant le déplacement linéaire propre du noyau cométaire, pour que la comète reste nette pendant que les étoiles filent.
keywords: [comète, alignement, empilement, décalage linéaire, noyau cométaire, registration, mouvement propre]
related: [LarsonSekanina, StarAlignment, Integration, PhaseCorrelationAlignment]
icon: comet
references:
  - "PixInsight — CometAlignment tool reference."
  - "scipy.ndimage.shift — interpolation par spline pour le décalage sous-pixel."
---

## Résumé

`CometAlignment` est un process **global** qui empile une série de frames en suivant le
**déplacement propre du noyau cométaire** plutôt que le fond étoilé. Une comète se déplace sur
le fond de ciel d'une pose à l'autre (mouvement orbital réel), à une vitesse quasi constante sur
la durée d'une session : en compensant ce déplacement linéaire avant de moyenner, le noyau et la
chevelure ressortent nets, au prix d'un filé des étoiles. C'est l'exact opposé de
`StarAlignment`, qui fige les étoiles et laisse filer la comète.

## Cas d'usage

- **Isoler une comète** dans un champ dense en étoiles, pour révéler la chevelure et les jets
  sans qu'elle soit noyée dans le bruit d'une seule pose.
- **Combiner** avec un empilement classique (aligné sur les étoiles) : on produit une image
  « comète nette / étoiles filées » et une image « étoiles nettes / comète filée », puis on les
  fusionne (masque, `PixelMath`) pour obtenir un résultat propre sur les deux plans.
- **Mesurer ou confirmer** la vitesse apparente d'une comète en ajustant `vx/vy` jusqu'à ce que
  le noyau paraisse ponctuel sur l'empilement.

## Fonctionnement

1. Les frames listées dans `frames` sont chargées **dans l'ordre temporel** (l'ordre de la
   liste fait foi, index `i = 0, 1, 2, …`).
2. Chaque frame `i` est décalée de `(-i·vx, -i·vy)` pixels (interpolation bilinéaire, remplissage
   à 0 hors cadre) : la frame `0` sert de référence immobile, les suivantes sont ramenées en
   arrière proportionnellement à leur rang, annulant ainsi le déplacement du noyau supposé
   linéaire et uniforme entre poses consécutives.
3. Les frames décalées sont **moyennées simplement** (pas de rejet sigma ici, contrairement à
   `Integration`) pour produire l'image finale, publiée dans une nouvelle fenêtre nommée
   `new_image_id`.

Le décalage compense le mouvement de la comète, donc les étoiles — immobiles dans le référentiel
du capteur — se retrouvent décalées de façon croissante d'une frame à l'autre : elles apparaissent
comme des traînées dans le résultat, pendant que le noyau cométaire, lui, reste superposé à
lui-même.

## Mathématiques

Soit $I_i(x,y)$ la frame d'indice $i \in \{0,\dots,N-1\}$ (ordre chronologique de `frames`), et
$(v_x, v_y)$ la vitesse apparente du noyau en pixels/frame (`vx`, `vy`). On suppose un
déplacement **linéaire et uniforme** : la position du noyau à la frame $i$ diffère de sa position
à la frame $0$ de $(i\,v_x,\, i\,v_y)$ pixels.

Chaque frame est recalée par interpolation (spline d'ordre 1, remplissage constant à 0), d'un
vecteur $(-i\,v_x, -i\,v_y)$ qui annule le déplacement supposé du noyau et le ramène à sa position
dans $I_0$ :

$$ J_i(x, y) = I_i\big(x + i\,v_x,\; y + i\,v_y\big). $$

L'image de sortie est la **moyenne simple** des frames recalées :

$$ C(x,y) = \frac{1}{N} \sum_{i=0}^{N-1} J_i(x,y). $$

Le noyau, désormais superposé à lui-même sur toutes les frames, gagne en rapport signal/bruit
comme une intégration classique ($\propto \sqrt{N}$). Une étoile fixe du champ, en revanche, se
retrouve à des positions différentes dans chaque $J_i$ (décalée de $i\,(v_x, v_y)$ par rapport à
sa position d'origine) : sa lumière est étalée sur une traînée d'environ $(N-1)\,\|(v_x,v_y)\|$
pixels, diluant son pic d'intensité d'autant.

## Paramètres

- **`frames`** — *pathlist*, défaut `[]`. Liste des fichiers image à empiler, **dans l'ordre
  chronologique d'acquisition** (l'index dans la liste sert directement au calcul du décalage).
- **`vx`** — *real*, défaut `0.0`, plage `-1000`–`1000`. Vitesse apparente du noyau selon X, en
  pixels par frame.
- **`vy`** — *real*, défaut `0.0`, plage `-1000`–`1000`. Vitesse apparente du noyau selon Y, en
  pixels par frame.
- **`new_image_id`** — *str*, défaut `"comet"`. Identifiant de la fenêtre créée pour accueillir
  le résultat de l'empilement.

## Astuces & pièges

> **Attention** — l'ordre de `frames` **est** l'horloge du process : intervertir deux poses ou
> mélanger des sessions non contiguës fausse totalement le décalage appliqué, même avec un
> `vx/vy` correct.

> **Note** — `vx`/`vy` à `0.0` (valeurs par défaut) revient à un empilement simple sans aucun
> recalage : utile pour vérifier d'abord le filé des étoiles avant d'estimer la vitesse du noyau.

- Estimez `vx/vy` en mesurant la position du noyau (ex. via `DynamicPSF` ou un pointé manuel) sur
  la première et la dernière frame, puis en divisant le déplacement total par `N - 1`.
- Contrairement à `Integration`, il n'y a **aucun rejet d'aberrants** : un satellite ou un rayon
  cosmique traversant une frame reste visible (atténué seulement par le facteur $1/N$).
- Pour combiner comète nette et étoiles nettes dans une même image, produisez les deux
  empilements (celui-ci, puis un `StarAlignment` + `Integration` classique) et fusionnez-les
  sous masque.

## Voir aussi

- [LarsonSekanina](retina-doc://LarsonSekanina) — filtre de gradient rotationnel pour révéler
  jets et structures de la chevelure, une fois la comète isolée.
- [StarAlignment](retina-doc://StarAlignment) — alignement classique sur les étoiles (l'opposé
  fonctionnel de ce process).
- [Integration](retina-doc://Integration) — empilement avec rejet sigma robuste, à utiliser en
  aval sur les frames alignées étoiles.
- [PhaseCorrelationAlignment](retina-doc://PhaseCorrelationAlignment) — recalage global sans
  étoiles, utile pour estimer un décalage entre deux poses.

## Références

- PixInsight — *CometAlignment* tool reference.
- scipy.ndimage.shift — interpolation par spline pour le décalage sous-pixel.
