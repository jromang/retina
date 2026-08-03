---
id: GradientHDRCompression
category: MultiscaleProcessing
title: Compression HDR en domaine de gradient
brief: "Comprime la dynamique en atténuant les grands gradients du log-luminance, puis reconstruit par résolution de Poisson."
keywords: [HDR, domaine de gradient, Fattal, Poisson, dynamique, compression de tons, log-luminance]
related: [HDRMultiscaleTransform, GradientHDRComposition, HDRComposition, MultiscaleLinearTransform]
icon: stack
references:
  - "Fattal, R., Lischinski, D., Werman, M. — Gradient Domain High Dynamic Range Compression, SIGGRAPH 2002."
  - "Pérez, P., Gangnet, M., Blake, A. — Poisson Image Editing, SIGGRAPH 2003."
  - "PixInsight — HDRMultiscaleTransform tool reference (approche apparentée)."
---

## Résumé

`GradientHDRCompression` comprime la dynamique d'une image en travaillant non pas sur les
pixels mais sur leurs **gradients**, dans une version simplifiée de la méthode de Fattal et
al. (2002). Elle atténue les **grands** gradients — les transitions brutales entre un noyau
brillant et le fond de ciel qui saturent le contraste local — tout en préservant les **petits**
gradients porteurs de détail fin. L'image finale est reconstruite en résolvant une équation de
Poisson sur le champ de gradients modifié. Contrairement à `HDRMultiscaleTransform`, qui opère
par décomposition multi-échelle, cette approche ne produit pas de halo en anneau autour des
objets brillants.

![Avant — GradientHDRCompression](figures/before.webp)
![Après — GradientHDRCompression](figures/after.webp)

*Avant, et après compression de la dynamique dans le domaine du gradient (bêta 0,6).*

## Cas d'usage

- **Révéler simultanément noyau et extensions faibles** d'un objet à très forte dynamique
  (noyau galactique, étoile centrale de nébuleuse planétaire, cœur de M42) sans écraser l'un
  au profit de l'autre.
- **Alternative sans halo** à `HDRMultiscaleTransform` lorsque celui-ci produit des anneaux
  clairs/sombres autour des étoiles ou du bulbe galactique.
- **Préparer une image linéaire à forte dynamique** avant un étirement classique
  (`HistogramTransformation`, `ArcsinhStretch`), en réduisant l'écart entre tons extrêmes que
  l'étirement final devra gérer.

## Fonctionnement

Le traitement s'effectue canal par canal, indépendamment :

1. **Passage au log-luminance** : `data` est d'abord bornée à une petite valeur positive
   (évite `log(0)`), puis on prend le logarithme — l'espace naturel pour manipuler des rapports
   de dynamique plutôt que des différences absolues.
2. **Gradients avant** ($g_x$, $g_y$) du log-luminance, calculés par différences finies
   (bord droit/bas mis à zéro).
3. **Seuil adaptatif** $\alpha$ = paramètre `alpha` × magnitude moyenne des gradients de
   l'image — le seuil s'adapte donc au contenu plutôt que d'être une valeur absolue fixe.
4. **Atténuation** : chaque composante du gradient est multipliée par un facteur $\Phi$ qui
   vaut ≈1 près du seuil, compresse les gradients bien au-dessus (transitions brutales) et
   relève relativement les gradients bien en-dessous (détail fin) — voir la formule ci-dessous.
5. **Reconstruction par résolution de Poisson** : le champ de gradients atténué n'est en général
   plus un gradient exact (il n'est plus intégrable) ; on cherche l'image dont le gradient
   *l'approche au mieux* au sens des moindres carrés, ce qui revient à résoudre
   $\nabla^2 I = \operatorname{div}(g_x', g_y')$ avec conditions de bord de **Neumann**. La
   résolution utilise une DCT-II (le laplacien discret à 5 points est diagonal dans cette base),
   le mode constant (DC) étant indéterminé et fixé arbitrairement à 0.
6. **Retour à l'espace linéaire** (exponentielle), puis **renormalisation** canal par canal
   sur `[min, max] → [0, 1]` et écrêtage final.

## Mathématiques

Soit $L = \log(\max(I, 10^{-4}))$ le log-luminance d'un canal, et $\nabla L = (g_x, g_y)$ son
gradient discret (différences avant). Le seuil adaptatif est :

$$ \alpha = \max\!\big(\texttt{alpha} \cdot \overline{|\nabla L|},\; 10^{-6}\big) $$

où $\overline{|\nabla L|}$ est la magnitude moyenne des gradients sur l'image entière. Le
facteur d'atténuation appliqué à un gradient de magnitude $g = |\nabla L|$ est :

$$ \Phi(g) = \left(\frac{\alpha}{g}\right)\left(\frac{g}{\alpha}\right)^{\beta}
           = \left(\frac{g}{\alpha}\right)^{\beta - 1}, $$

avec $\beta$ = paramètre `beta`. Le gradient atténué est $g' = \Phi(g)\, g$, ce qui se réécrit :

$$ g' = \alpha \left(\frac{g}{\alpha}\right)^{\beta} . $$

Comme $\beta < 1$, cette loi de puissance est **concave** : au point fixe $g = \alpha$,
$g' = \alpha$ (pas de changement) ; pour $g \gg \alpha$ (grande transition), $g'$ croît
beaucoup plus lentement que $g$ — c'est la **compression** ; pour $g \ll \alpha$ (détail fin),
$g'$ est relevé proportionnellement plus haut que $g$ — c'est le **rehaussement local**. Plus
$\beta$ est petit, plus l'effet (compression des grands gradients / accentuation des petits)
est marqué.

L'image reconstruite $I'$ résout ensuite, au sens des moindres carrés,

$$ \nabla^2 I' = \operatorname{div}(g_x', g_y'), $$

diagonalisée par la DCT-II : si $\hat{d}$ est la transformée de la divergence et
$\lambda_{u,v} = 2\cos(\pi u / H) - 2 + 2\cos(\pi v / W) - 2$ les valeurs propres du laplacien
discret 5-points avec bord de Neumann, alors $\hat{I}'_{u,v} = \hat{d}_{u,v} / \lambda_{u,v}$
(mode $u=v=0$ fixé à 0). Le résultat final est $\exp(I')$, renormalisé linéairement dans
$[0,1]$ par canal.

## Paramètres

- **`beta`** — *real*, défaut `0.85`, plage `0.1`–`1.0`. Exposant de compression. Plus il est
  proche de `0.1`, plus la compression des grands gradients (et le rehaussement des petits)
  est forte ; à `1.0`, $\Phi \equiv 1$ et l'opérateur devient (quasi) neutre.
- **`alpha`** — *real*, défaut `0.1`, plage `0.01`–`1.0`. Seuil de gradient, exprimé comme
  fraction de la magnitude moyenne des gradients de l'image. Un `alpha` petit qualifie plus de
  gradients de « grands » (davantage de zones compressées) ; un `alpha` grand restreint la
  compression aux transitions les plus violentes.

## Astuces & pièges

> **Attention** — le process renormalise chaque canal sur son propre `[min, max]` après
> reconstruction : le niveau de noir et le point blanc absolus ne sont pas préservés d'une
> application à l'autre. Revérifiez toujours la STF/l'histogramme après coup.

> **Note** — les canaux sont traités **indépendamment** en log-domaine puis renormalisés
> séparément ; sur une image couleur, cela peut légèrement déplacer la balance des couleurs.
> Sur une cible où la teinte doit rester fidèle, envisagez d'appliquer le process sur un canal
> de luminance séparé (`ComponentSeparation`) puis de recombiner.

- Nécessite des pixels strictement positifs après clip à $10^{-4}$ : appliquez d'abord une
  correction de fond (`BackgroundExtraction`) pour éviter un fond de ciel écrasé à zéro qui
  fausserait le log-luminance.
- Comparé à `HDRMultiscaleTransform`, cette méthode agit sur le gradient à pleine résolution
  (pas de pyramide multi-échelle) : c'est ce qui évite les halos en anneau, au prix d'un effet
  plus « global » et moins réglable finement par échelle.
- Sur des images déjà bien étirées, l'effet peut sembler agressif : partez de données proches
  du linéaire et faites suivre d'un étirement doux (`HistogramTransformation`,
  `ArcsinhStretch`).

## Voir aussi

- [HDRMultiscaleTransform](retina-doc://HDRMultiscaleTransform) — compression HDR par
  décomposition multi-échelle (peut produire des halos).
- [GradientHDRComposition](retina-doc://GradientHDRComposition) — composition multi-poses en
  domaine de gradient (process global, même solveur de Poisson).
- [HDRComposition](retina-doc://HDRComposition) — composition HDR classique par pondération
  de poses de durées croissantes.
- [MultiscaleLinearTransform](retina-doc://MultiscaleLinearTransform) — décomposition en
  ondelettes à trous, base d'autres traitements multi-échelle.

## Références

- Fattal, R., Lischinski, D., Werman, M. — *Gradient Domain High Dynamic Range Compression*,
  SIGGRAPH 2002.
- Pérez, P., Gangnet, M., Blake, A. — *Poisson Image Editing*, SIGGRAPH 2003.
- PixInsight — *HDRMultiscaleTransform* tool reference (approche apparentée).
