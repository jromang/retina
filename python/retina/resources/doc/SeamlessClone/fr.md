---
id: SeamlessClone
category: Painting
title: Clonage à fondu invisible
brief: Copie un disque de pixels source vers une destination en fondant les gradients (mélange de Poisson OpenCV), sans raccord visible.
keywords: [clonage, tampon, Poisson, seamlessClone, retouche, fusion de gradients, inpainting]
related: [CloneStamp, Inpaint, StarRemoval, CosmeticCorrection]
icon: copy
references:
  - "Pérez, P., Gangnet, M., Blake, A. (2003) — Poisson Image Editing, ACM SIGGRAPH."
  - "OpenCV — cv2.seamlessClone (module Photo, mode NORMAL_CLONE)."
---

## Résumé

`SeamlessClone` copie un disque de pixels prélevé autour d'un point **source** vers un point
**destination**, mais au lieu de mélanger les couleurs par un simple fondu alpha comme
`CloneStamp`, il recompose le patch par **mélange de gradients** (algorithme de Poisson
d'OpenCV, `cv2.seamlessClone`). Le résultat conserve la texture et les hautes fréquences du
patch source tout en épousant exactement la couleur moyenne et l'éclairage du fond de
destination : la jointure devient indétectable, même sur un fond structuré (nébulosité,
gradient de fond de ciel, vignettage résiduel).

## Cas d'usage

- **Effacer un défaut étendu** (artefact de capteur, trainée de satellite non couverte par
  `CosmeticCorrection`, reflet d'optique) en le recouvrant d'un patch pris ailleurs dans le
  même fond de ciel.
- **Dupliquer une zone de fond propre** sur une zone polluée (halo de réflexion, gradient
  local) sans laisser de bord visible, contrairement à un simple copier-coller.
- **Réparer une grande région** après un retrait d'étoiles agressif, quand `Inpaint` produit un
  aplat trop lisse et qu'on préfère réinjecter de la texture de fond réelle.
- **Prétraiter une zone avant mosaïquage/composite** pour homogénéiser une jonction de panneaux
  sur une petite zone de recouvrement.

## Fonctionnement

1. Un **patch carré** de côté $2r+1$ est extrait autour du point source $(src\_x, src\_y)$,
   où $r$ = `radius`. Si ce carré déborde de l'image, l'opération est un **no-op** (image
   inchangée) : la source doit être entièrement contenue.
2. Un **masque circulaire** plein (rayon $r$, centré sur le patch) délimite la région à cloner :
   seul le disque intérieur au carré est effectivement fondu, ce qui évite d'imposer une
   frontière carrée artificielle au solveur.
3. Les pixels sont convertis en **8 bits sur 3 canaux** (OpenCV l'exige) ; une image
   monochrome est répliquée sur 3 canaux avant l'appel, puis le résultat est ramené à 1 canal
   par moyenne des 3 canaux fondus.
4. `cv2.seamlessClone` est appelé en mode **`NORMAL_CLONE`** : il résout une équation de
   Poisson qui impose au patch collé de reproduire les **gradients internes** du patch source,
   tout en forçant sa **bordure** à coïncider avec le fond de destination existant. Le centre
   de collage doit être à au moins $r$ pixels de chaque bord de l'image, faute de quoi l'appel
   est aussi un no-op (le solveur a besoin d'un voisinage complet autour du disque).
5. Le patch fondu remplace la zone correspondante à `(dst_x, dst_y)` ; le reste de l'image est
   inchangé.

## Mathématiques

Soit $\Omega$ le disque de rayon $r$ centré sur la destination, $\partial\Omega$ sa frontière,
$g$ le patch source (vu comme fonction continue sur $\Omega$) et $f^*$ le fond de destination
existant. Le mélange de Poisson (Pérez, Gangnet & Blake, 2003) cherche la fonction $f$ définie
sur $\Omega$ qui **minimise l'écart de gradient** avec la source tout en **recollant**
exactement le fond à la frontière :

$$
f = \arg\min_{f} \iint_{\Omega} \big|\nabla f - \nabla g\big|^2 \, \mathrm{d}\Omega,
\qquad \text{sous } f\big|_{\partial\Omega} = f^*\big|_{\partial\Omega}.
$$

L'équation d'Euler–Lagrange associée à ce problème variationnel est une **équation de
Poisson** avec condition aux limites de Dirichlet :

$$
\Delta f = \Delta g \ \text{ sur } \Omega, \qquad f\big|_{\partial\Omega} = f^*\big|_{\partial\Omega},
$$

où $\Delta$ est le laplacien discret (somme des différences avec les 4 voisins). En mode
`NORMAL_CLONE`, le champ guide est exactement $\nabla g$ (les gradients internes du patch
source sont intégralement transportés) ; OpenCV résout ce système linéaire creux canal par
canal. Le résultat $f$ a donc la **texture et le contraste locaux** de la source, mais un
**niveau moyen** qui se raccorde continûment au fond de destination — c'est ce qui rend la
jointure invisible là où un simple $\alpha$-blend (comme `CloneStamp`) laisse un halo dès que
les luminosités moyennes des deux zones diffèrent.

## Paramètres

- **`src_x`** — *int*, défaut `0`, plage `0`–`1 000 000`. Coordonnée X (pixels) du centre de la
  zone source à copier.
- **`src_y`** — *int*, défaut `0`, plage `0`–`1 000 000`. Coordonnée Y (pixels) du centre de la
  zone source.
- **`dst_x`** — *int*, défaut `0`, plage `0`–`1 000 000`. Coordonnée X (pixels) du centre de la
  zone de destination où coller le patch fondu.
- **`dst_y`** — *int*, défaut `0`, plage `0`–`1 000 000`. Coordonnée Y (pixels) du centre de la
  destination.
- **`radius`** — *int*, défaut `12`, plage `2`–`500`. Rayon (pixels) du disque cloné. Détermine
  aussi la taille du patch carré extrait ($2r+1$ de côté) et la marge minimale requise entre le
  centre de destination et les bords de l'image.

## Astuces & pièges

> **Attention** — si la source ou la destination sont trop proches d'un bord (moins de
> `radius` pixels), le process est un **no-op silencieux** : l'image ressort inchangée sans
> erreur. Vérifiez toujours le résultat, surtout avec un grand rayon près des coins.

> **Note** — contrairement à `CloneStamp`, il n'y a pas de paramètre `softness` : le fondu est
> assuré par la résolution de Poisson elle-même, pas par un dégradé alpha au bord du disque.

- Choisissez une source dont la **texture** (bruit, granularité de fond) ressemble à celle de
  la destination : le mélange de Poisson corrige la luminosité moyenne, pas le grain.
- Pour de petites retouches ponctuelles (points chauds, pixels isolés), `CloneStamp` avec un
  petit rayon est souvent suffisant et moins coûteux ; réservez `SeamlessClone` aux zones plus
  grandes où un raccord de niveau moyen doit être invisible.
- Un rayon trop grand peut englober des structures (étoiles, filaments) dans le patch source,
  qui seront alors dupliquées de façon reconnaissable dans la destination.

## Voir aussi

- [CloneStamp](retina-doc://CloneStamp) — tampon de clonage simple avec fondu alpha, plus rapide.
- [Inpaint](retina-doc://Inpaint) — comblement d'une zone masquée par propagation de gradients,
  sans source explicite.
- [StarRemoval](retina-doc://StarRemoval) — retrait d'étoiles, avec comblement par inpainting.
- [CosmeticCorrection](retina-doc://CosmeticCorrection) — correction automatique de défauts
  ponctuels (pixels chauds/morts).

## Références

- Pérez, P., Gangnet, M., Blake, A. (2003) — *Poisson Image Editing*, ACM SIGGRAPH.
- OpenCV — *cv2.seamlessClone* (module Photo, mode `NORMAL_CLONE`).
