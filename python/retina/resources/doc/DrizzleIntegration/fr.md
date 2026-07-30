---
id: DrizzleIntegration
category: ImageIntegration
title: Intégration drizzle
brief: Sur-échantillonne et combine des frames dithered pour reconstruire du détail sous-pixel.
keywords: [drizzle, sur-échantillonnage, pixfrac, dithering, intégration, sous-pixel]
related: [Integration, StarAlignment, FastIntegration, Resample]
icon: droplet
references:
  - "Fruchter, A. S. & Hook, R. N. — Drizzle: A Method for the Linear Reconstruction of Undersampled Images (2002)."
  - "PixInsight — ImageIntegration (mode drizzle) / DrizzleIntegration tool reference."
  - "scikit-image — skimage.transform.resize."
---

## Résumé

`DrizzleIntegration` reconstruit une image à une résolution **supérieure** à celle des poses
individuelles en combinant plusieurs frames légèrement décalées les unes par rapport aux
autres (technique du **dithering**). C'est un process **global** : il lit une liste de
fichiers déjà recalés et crée une nouvelle fenêtre, à la manière d'`Integration`, mais sur
une grille sur-échantillonnée d'un facteur `scale`.

## Cas d'usage

- **Récupérer du détail sous-pixel** sur une série d'images acquises avec un léger décalage
  de monture entre chaque pose (dithering volontaire).
- **Compenser un sous-échantillonnage** (pixels trop gros par rapport à la turbulence/optique,
  ou binning) en reconstruisant une image finale plus fine que les poses de départ.
- **Mosaïques et grands champs** où l'on souhaite une sortie à résolution accrue à partir de
  nombreuses poses courtes.

## Fonctionnement

Chaque frame de la liste `frames` est chargée, puis **projetée sur une grille agrandie** d'un
facteur `scale` dans chaque dimension (une image `H×W` devient `sH×sW`). Cette implémentation
utilise un ré-échantillonnage par **plus proche voisin** (`skimage.transform.resize`, `order=0`,
sans anti-aliasing) : chaque pixel source est simplement répliqué en un bloc `scale×scale` sur
la grille de sortie — c'est la variante *pragmatique* du drizzle, sans calcul explicite de
footprint (empreinte) du « drop » à une position sous-pixel arbitraire.

Chaque frame agrandie reçoit un **poids** égal à `pixfrac²` (l'aire du drop rétréci est
proportionnelle au carré de la fraction de pixel). Les frames pondérées sont accumulées puis
divisées par la somme des poids : le résultat est une **moyenne pondérée** sur la grille
sur-échantillonnée.

> **Note** — le procédé suppose les frames **déjà recalées** (voir `StarAlignment`) avec une
> précision sous-pixel réelle entre les poses (dithering). Sans variation sous-pixel du
> pointage d'une pose à l'autre, l'agrandissement par plus-proche-voisin ne fait
> qu'agrandir le pixel — aucun détail nouveau n'apparaît, contrairement au drizzle classique
> qui redistribue chaque pixel source à sa position sous-pixel exacte sur la grille de sortie.

## Mathématiques

Soit $s$ le facteur `scale` et $f$ la fraction de pixel `pixfrac` $\in [0.1, 1.0]$. Pour une
frame source $I_i$ de taille $H \times W$, l'opérateur d'agrandissement plus-proche-voisin
produit $U_i$ de taille $sH \times sW$ :

$$ U_i(y, x) = I_i\!\left(\left\lfloor \frac{y}{s} \right\rfloor,\ \left\lfloor \frac{x}{s} \right\rfloor\right). $$

Le poids attribué à la frame $i$ est l'aire du drop rétréci :

$$ w_i = f^2. $$

L'image intégrée est la moyenne pondérée des frames agrandies :

$$ D(y, x) = \frac{\sum_{i=1}^{N} w_i\, U_i(y, x)}{\sum_{i=1}^{N} w_i}
           = \frac{\sum_{i=1}^{N} U_i(y, x)}{N} \quad \text{(tous les poids étant égaux ici),} $$

le dénominateur étant plancherisé à $10^{-6}$ pour éviter une division par zéro. Dans le
drizzle original de Fruchter & Hook, $w_i$ et la position d'accumulation varient **par pixel
de sortie** selon le recouvrement géométrique exact entre le drop rétréci (taille $f \times f$
pixel source) et chaque cellule de la grille de sortie ; ici, faute de transformation
sous-pixel explicite par frame, le poids est **constant** et uniforme sur toute l'image — d'où
une reconstruction de détail qui dépend entièrement de la qualité du recalage sous-pixel en amont.

## Paramètres

- **`frames`** — *pathlist*, défaut `[]`. Liste des fichiers de frames déjà recalées
  (voir `StarAlignment`) à intégrer.
- **`scale`** — *int*, défaut `2`, plage `1`–`4`. Facteur de sur-échantillonnage de la grille
  de sortie par rapport aux frames d'entrée (2 = image de sortie deux fois plus grande en
  largeur et hauteur).
- **`pixfrac`** — *real*, défaut `1.0`, plage `0.1`–`1.0`. Fraction de pixel (taille du drop
  rétréci) ; pondère chaque frame par `pixfrac²`. Une valeur proche de `1.0` équivaut à un
  simple sur-échantillonnage moyenné ; des valeurs plus faibles concentrent davantage le poids
  (utile en drizzle classique pour affiner la résolution, avec plus de bruit).
- **`new_image_id`** — *str*, défaut `"drizzle"`. Identifiant de la fenêtre image créée.

## Astuces & pièges

> **Attention** — cette implémentation n'effectue **pas** de splatting sous-pixel par pixel de
> sortie : elle agrandit chaque frame par plus-proche-voisin puis moyenne. Le gain réel de
> résolution dépend donc entièrement du **dithering** effectif entre poses et de la précision
> du recalage (`StarAlignment`), pas uniquement du réglage de `scale`/`pixfrac`.

- Sans dithering (frames alignées sur la même grille de pixels entiers), préférez `Integration`
  suivie d'un `Resample` classique : le drizzle n'apportera rien de plus.
- Un `scale` élevé (3 ou 4) sur peu de frames dilue le signal par pixel de sortie et amplifie
  le bruit visible ; réservez-le aux séries comportant de nombreuses poses bien ditherées.
- `pixfrac` bas nécessite davantage de frames pour combler uniformément la grille de sortie,
  sous peine de trous ou de bruit de couverture irrégulier.

## Voir aussi

- [Integration](retina-doc://Integration) — empilement classique avec rejet sigma robuste.
- [StarAlignment](retina-doc://StarAlignment) — recalage préalable indispensable au drizzle.
- [FastIntegration](retina-doc://FastIntegration) — variante rapide d'empilement sans drizzle.
- [Resample](retina-doc://Resample) — redimensionnement générique d'une image déjà intégrée.

## Références

- Fruchter, A. S. & Hook, R. N. — *Drizzle: A Method for the Linear Reconstruction of
  Undersampled Images* (2002).
- PixInsight — *ImageIntegration* (mode drizzle) / *DrizzleIntegration* tool reference.
- scikit-image — *skimage.transform.resize*.
