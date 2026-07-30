---
id: GradientHDRComposition
category: ImageIntegration
title: Composition HDR en domaine de gradient
brief: Fusionne plusieurs poses recalées en retenant à chaque pixel le gradient de plus forte magnitude, puis reconstruit par résolution de Poisson.
keywords: [HDR, domaine de gradient, Poisson, gradient, dynamique, fusion, recalage]
related: [HDRComposition, GradientHDRCompression, StarAlignment, Integration]
icon: stack
references:
  - "Fattal, R., Lischinski, D., Werman, M. — Gradient Domain High Dynamic Range Compression (SIGGRAPH 2002)."
  - "PixInsight — HDRComposition tool reference."
  - "scipy.fft — dctn/idctn (transformée en cosinus discrète)."
---

## Résumé

`GradientHDRComposition` est un process **global** qui combine plusieurs poses **recalées**
(même grille de pixels, durées d'exposition différentes) en une seule image à grande gamme
dynamique. Plutôt que de mélanger les intensités pixel par pixel, l'algorithme travaille dans
le **domaine du gradient** : à chaque position, il retient le vecteur gradient de plus forte
magnitude parmi toutes les poses (donc le détail le mieux exposé — cœur net d'une pose courte
ou extension faible d'une pose longue), puis reconstruit l'image en résolvant une équation de
Poisson sur le champ de gradients fusionné. Le résultat ne présente ni coutures ni saturation
visible, sans les halos en anneau typiques des compositions multi-échelle classiques.

## Cas d'usage

- **Fusionner une série de poses courtes/longues** d'un même objet (recalées au préalable, p.
  ex. via `StarAlignment`) pour révéler simultanément le cœur brillant d'une galaxie ou d'un
  amas globulaire et ses extensions ténues, sans qu'aucune pose ne domine.
- **Composer un HDR de nébuleuse** où les poses courtes protègent les étoiles centrales
  saturées et les poses longues apportent le signal faible des volutes externes.
- Alternative à `HDRComposition` (fusion par pondération d'intensité) quand on veut préserver
  le **détail structurel local** plutôt qu'une simple moyenne pondérée par exposition.

## Fonctionnement

Pour chaque pose et chaque canal :

1. L'image est passée au **logarithme** (après écrêtage à une valeur plancher, pour éviter
   `log(0)`), ce qui linéarise la perception des contrastes sur plusieurs ordres de grandeur.
2. Le **gradient avant** `(gx, gy)` est calculé par différences finies simples (bord droit/bas
   mis à zéro).
3. À chaque pixel, on compare la **magnitude au carré** du gradient de la pose courante à la
   meilleure magnitude retenue jusqu'ici, et on garde le vecteur gagnant — la pose qui exprime
   le plus fort contraste local à cet endroit l'emporte.

Une fois toutes les poses parcourues, le champ de gradients fusionné `(best_gx, best_gy)` est
intégré : sa **divergence** est calculée (adjoint discret des différences avant), puis une
**équation de Poisson** à conditions de bord de Neumann est résolue par transformée en cosinus
discrète (DCT), qui diagonalise le laplacien 5-points sur grille régulière. Le résultat en
log-luminance est ensuite exponentié puis renormalisé linéairement dans `[0, 1]` par canal, et
la nouvelle image est publiée sous l'identifiant `new_image_id`.

> **Note** — le champ de gradients fusionné n'est en général pas un gradient exact (il ne
> dérive pas forcément d'un unique potentiel scalaire). La résolution de Poisson en donne la
> **reconstruction au sens des moindres carrés**, ce qui explique l'absence de coutures même
> quand des poses différentes contribuent à des régions voisines.

## Mathématiques

Soit $I_k(x,y)$ la $k$-ième pose (sur $N$ poses recalées), et $L_k = \log(\max(I_k, \varepsilon))$
sa log-luminance par canal. Le gradient avant discret est :

$$ \nabla L_k(x,y) = \big(L_k(x{+}1,y) - L_k(x,y),\; L_k(x,y{+}1) - L_k(x,y)\big) = (g_x^k, g_y^k). $$

À chaque pixel, on sélectionne la pose de plus forte magnitude de gradient :

$$ k^\star(x,y) = \arg\max_k \; \big(g_x^k(x,y)\big)^2 + \big(g_y^k(x,y)\big)^2, \qquad
   (G_x, G_y) = \big(g_x^{k^\star}, g_y^{k^\star}\big). $$

On cherche ensuite le champ scalaire $L$ dont le gradient approche au mieux $(G_x, G_y)$ au
sens des moindres carrés, ce qui conduit à l'**équation de Poisson** :

$$ \nabla^2 L = \operatorname{div}(G_x, G_y), $$

avec conditions de bord de **Neumann** (flux nul aux bords). Discrétisée sur grille régulière,
cette équation se diagonalise dans la base des cosinus (DCT-II) : le laplacien 5-points devient
multiplicatif par fréquence,

$$ \lambda(u,v) = 2\cos\!\Big(\frac{\pi u}{H}\Big) - 2 + 2\cos\!\Big(\frac{\pi v}{W}\Big) - 2, $$

et la solution s'obtient par $L = \operatorname{DCT}^{-1}\!\big(\operatorname{DCT}(\operatorname{div}
(G_x,G_y)) / \lambda\big)$, le mode constant ($u=v=0$, indéterminé car $\lambda(0,0)=0$) étant
fixé à zéro puisque seul un offset global de $L$ est indéterminé. L'image finale est
$I' = \exp(L)$, renormalisée linéairement par canal dans $[0,1]$.

## Paramètres

- **`frames`** — *pathlist*, défaut `[]`. Liste des chemins des poses **recalées** (même
  grille pixel) à combiner. Au moins une pose est requise ; une liste vide lève une erreur.
- **`new_image_id`** — *str*, défaut `gradient_hdr`. Identifiant de la fenêtre créée pour
  accueillir le résultat de la fusion.

## Astuces & pièges

> **Attention** — les poses doivent être **précisément recalées** avant l'appel (même
> résolution, même orientation, pixels alignés). Un désalignement, même sous-pixellique,
> produit des artefacts de gradient (dédoublement de contours, franges) dans la reconstruction.

- Le résultat dépend fortement du **contraste relatif** des poses en entrée : des poses trop
  bruitées peuvent localement « gagner » la sélection du gradient et injecter du bruit dans la
  reconstruction. Un léger débruitage préalable (`NonLocalMeansDenoise`, `WaveletDenoise`) sur
  les poses les plus faibles limite ce risque.
- La renormalisation finale par canal dans `[0, 1]` peut légèrement décorréler les gains entre
  canaux couleur ; vérifiez la balance des blancs après fusion (`ColorCalibration` ou
  `BackgroundNeutralization`).
- Pour une simple pondération d'intensité par exposition sans passage par le domaine de
  gradient (plus rapide, moins fin sur le détail local), voir `HDRComposition`.
- Le même moteur Poisson/DCT sert à `GradientHDRCompression`, qui compresse la dynamique d'une
  **image unique** plutôt que de fusionner plusieurs poses.

## Voir aussi

- [HDRComposition](retina-doc://HDRComposition) — fusion HDR par pondération d'intensité (sans domaine de gradient).
- [GradientHDRCompression](retina-doc://GradientHDRCompression) — compression de dynamique en domaine de gradient sur une image unique.
- [StarAlignment](retina-doc://StarAlignment) — recalage préalable des poses (prérequis).
- [Integration](retina-doc://Integration) — empilement classique avec rejet sigma (SNR, pas de HDR).

## Références

- Fattal, R., Lischinski, D., Werman, M. — *Gradient Domain High Dynamic Range Compression* (SIGGRAPH 2002).
- PixInsight — *HDRComposition* tool reference.
- scipy.fft — *dctn*/*idctn* (transformée en cosinus discrète).
