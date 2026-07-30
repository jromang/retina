---
id: CloneStamp
category: Painting
title: Tampon de clonage
brief: "Copie un disque de pixels (source → destination) avec bord adouci."
keywords: [tampon de clonage, retouche, clonage, alpha blending, artefact, fusion]
related: [SeamlessClone, Inpaint, CosmeticCorrection, PixelMath]
icon: rubber-stamp
references:
  - "PixInsight — CloneStamp process reference."
  - "Alpha blending / feathering — mélange linéaire pondéré aux bords."
---

## Résumé

`CloneStamp` copie un disque de pixels d'une **zone source** vers une **zone destination**,
en fondant le raccord par un dégradé alpha au bord du disque. C'est le cœur scriptable et
rejouable du tampon de clonage : là où l'outil GUI de PixInsight est un geste souris continu,
ici chaque « coup de tampon » est une opération explicite (coordonnées entières, rayon,
adoucissement), enregistrable dans l'historique et empilable en script pour reconstituer un
geste de retouche complet.

## Cas d'usage

- **Effacer un satellite, un avion ou un rayon cosmique** isolé en copiant un patch de fond de
  ciel voisin par-dessus le défaut.
- **Masquer un artefact de capteur** (pixel chaud groupé, colonne défectueuse localisée, reflet
  optique) non couvert par `CosmeticCorrection` (qui opère pixel à pixel, pas par patch).
- **Reconstruire visuellement** une petite zone (jonction de mosaïque, bord de champ) en
  puisant dans une zone de texture similaire de la même image.
- **Scripter une séquence de retouches** reproductible : un script Python enchaîne plusieurs
  `CloneStamp` avec des coordonnées précises, rejouable sur une image recalibrée.

## Fonctionnement

L'opérateur travaille sur un voisinage carré de côté `2·radius + 1` centré alternativement sur
la source et la destination :

1. Pour chaque décalage `(dx, dy)` dans ce carré, on calcule la **distance radiale** au centre
   du disque.
2. On en déduit un **poids alpha** qui vaut 1 au centre et décroît linéairement vers 0 à mesure
   qu'on s'approche du bord du disque, sur une largeur de transition proportionnelle à
   `softness` (0 = coupure franche à `radius`, 1 = dégradé couvrant tout le disque).
3. Le pixel de destination est remplacé par un **mélange linéaire** (alpha blending) entre sa
   valeur d'origine et la valeur du pixel source correspondant, pondéré par ce poids.
4. Les couples de pixels dont la source **ou** la destination sortent de l'image sont ignorés
   (le pixel de destination garde alors sa valeur d'origine) — pas d'accès hors-bornes, pas de
   report cyclique.

Une même instance peut porter un **trait** entier : `points` liste les positions de destination
successives du geste, `[x0, y0, x1, y1, …]`. L'écart source→destination est alors *constant*,
pris sur le premier point (`src − (x0, y0)`), et la zone lue suit le pinceau — c'est la
sémantique classique d'un tampon. Chaque point est déposé dans l'image **déjà modifiée** par les
précédents : un trait de N points donne donc exactement le même résultat que N instances
mono-disque enchaînées, y compris quand il repasse sur sa propre zone source. Il ne coûte en
revanche qu'une entrée d'historique, ce qui est le bon grain pour un geste — on veut défaire
*un trait*, pas cinquante disques.

Le résultat est un disque de pixels source « collé » sur la destination, avec un bord fondu
plutôt qu'une découpe nette, ce qui réduit la visibilité de la jonction sur un fond à peu près
uniforme (fond de ciel, nébulosité diffuse). Pour des fonds structurés où même un bord fondu
laisse un raccord visible, préférer `SeamlessClone`, qui fusionne les **gradients** (mélange de
Poisson) plutôt que les valeurs de pixels.

## Mathématiques

Soit $r$ = `radius`, $(x_s, y_s)$ le centre de la source, $(x_d, y_d)$ le centre de la
destination, et $I$ l'image d'entrée. Pour tout décalage entier $(dx, dy)$ avec
$-r \le dx, dy \le r$, on définit la distance au centre du disque :

$$ d(dx, dy) = \sqrt{dx^2 + dy^2} $$

et la largeur de la zone de transition, proportionnelle au rayon :

$$ w = \max(\texttt{softness},\, \varepsilon)\cdot r $$

Le poids de mélange (1 au centre, 0 au-delà du disque) est :

$$ \alpha(d) = \operatorname{clip}\!\left(\frac{r - d}{w},\; 0,\; 1\right) $$

Le pixel de destination est mis à jour par interpolation linéaire entre sa valeur d'origine et
la valeur du pixel source au même décalage :

$$ I'(x_d + dx,\, y_d + dy) = \big(1 - \alpha(d)\big)\, I(x_d + dx,\, y_d + dy)
   \;+\; \alpha(d)\, I(x_s + dx,\, y_s + dy) $$

pour chaque couple de coordonnées restant à l'intérieur de l'image ; sinon le pixel de
destination n'est pas modifié. Quand `softness → 0`, $w$ tend vers un $\varepsilon$
négligeable et $\alpha(d)$ bascule presque abruptement de 1 à 0 en $d = r$ : le disque devient un
pochoir à bord franc. Quand `softness = 1`, $w = r$ et $\alpha$ décroît **linéairement** sur
tout le rayon, du centre ($\alpha=1$) jusqu'au bord ($\alpha=0$) : le fondu est maximal.

## Paramètres

- **`src_x`** — *int*, défaut `0`, plage `0`–`1000000`. Coordonnée X (en pixels) du centre de
  la zone source à copier.
- **`src_y`** — *int*, défaut `0`, plage `0`–`1000000`. Coordonnée Y (en pixels) du centre de
  la zone source.
- **`dst_x`** — *int*, défaut `0`, plage `0`–`1000000`. Coordonnée X (en pixels) du centre de
  la zone destination à recouvrir.
- **`dst_y`** — *int*, défaut `0`, plage `0`–`1000000`. Coordonnée Y (en pixels) du centre de
  la zone destination.
- **`radius`** — *int*, défaut `8`, plage `1`–`1000`. Rayon (en pixels) du disque copié. Doit
  couvrir largement le défaut à masquer sans empiéter sur du signal utile voisin.
- **`softness`** — *real*, défaut `0.3`, plage `0.0`–`1.0`. Largeur relative du dégradé au bord
  du disque : `0` = découpe franche, `1` = fondu linéaire sur tout le rayon. Une valeur
  intermédiaire (0,2–0,4) suffit généralement à rendre la jonction invisible sur un fond calme.
- **`points`** — *floatlist*, défaut vide. Trajectoire du trait : liste plate des positions de
  **destination**, `[x0, y0, x1, y1, …]`, en pixels. Vide, le process retombe sur le coup unique
  décrit par `dst_x`/`dst_y`. Non vide, `dst_x`/`dst_y` ne servent plus qu'à fixer l'écart
  source, mesuré sur le premier point. Il n'y a délibérément pas de paramètre d'espacement : le
  process tamponne les points qu'on lui donne, et c'est à l'appelant (l'outil, ou votre script)
  de les semer — un quart de rayon donne un trait lisse sans multiplier les tampons.

## Astuces & pièges

> **Attention** — si la zone source ou la zone destination dépasse partiellement les bords de
> l'image, l'opération **ne s'applique pas du tout** sur les décalages concernés (ni la source
> ni la destination hors-bornes ne sont traitées) : le résultat peut sembler « manquer » un
> croissant du disque. Vérifiez que `radius` laisse assez de marge par rapport aux bords.

- Choisissez une **source** dans une zone de texture et de niveau de fond similaires à la
  destination : `CloneStamp` fait un simple mélange de valeurs, sans adaptation colorimétrique.
- Sur un fond fortement structuré (nébulosité brillante, gradient marqué), un bord fondu ne
  suffit pas toujours à masquer la jonction ; utilisez `SeamlessClone` qui fusionne les
  gradients plutôt que les valeurs brutes.
- Pour des défauts ponctuels très nombreux et petits (pixels chauds épars), `CosmeticCorrection`
  est plus adapté et plus rapide qu'un enchaînement de `CloneStamp`.
- Pour un « coup de tampon » glissé, employez `points` plutôt qu'une pile d'instances : même
  résultat au pixel près, une seule entrée d'historique, et un coût bien moindre (le noyau alpha
  n'est calculé qu'une fois pour tout le trait).

## Voir aussi

- [SeamlessClone](retina-doc://SeamlessClone) — clonage à fondu invisible par mélange de
  Poisson, pour les fonds structurés.
- [Inpaint](retina-doc://Inpaint) — comblement par propagation de gradients à partir d'une
  carte de masque, sans zone source explicite.
- [CosmeticCorrection](retina-doc://CosmeticCorrection) — correction pixel à pixel des défauts
  capteur (hot/cold pixels, colonnes).
- [PixelMath](retina-doc://PixelMath) — expressions arbitraires pour des retouches plus
  générales.

## Références

- PixInsight — *CloneStamp* process reference.
- Alpha blending / feathering — mélange linéaire pondéré aux bords.
