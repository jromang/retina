---
id: TGVDenoise
category: NoiseReduction
title: Débruitage TGV (Total Generalized Variation)
brief: Débruitage TGV² primal-dual (Bredies-Kunisch-Pock) — préserve bords et dégradés lisses sans effet d'escalier.
keywords: [débruitage, TGV, total generalized variation, primal-dual, Chambolle-Pock, staircasing, régularisation]
related: [NonLocalMeansDenoise, ACDNR, WaveletDenoise, NoiseReduction]
icon: sparkles
references:
  - "Bredies, K., Kunisch, K., Pock, T. — Total Generalized Variation, SIAM J. Imaging Sciences, 2010."
  - "Chambolle, A., Pock, T. — A First-Order Primal-Dual Algorithm for Convex Problems with Applications to Imaging, JMIV, 2011."
---

## Résumé

`TGVDenoise` débruite l'image en minimisant une énergie de **Variation Généralisée Totale
du second ordre (TGV²)**, résolue par un algorithme **primal-dual** (Chambolle-Pock). Contrairement
à un débruitage par Variation Totale (TV) classique, qui ne pénalise que le gradient de l'image et
produit des zones plates séparées par des marches (effet « escalier », *staircasing*), la TGV²
introduit un champ auxiliaire qui absorbe les **rampes lisses** (dégradés de luminosité continus,
typiques des nébuleuses et des halos d'étoiles) tout en gardant les bords nets. C'est une
implémentation **numpy pure, sans dépendance externe**, de l'algorithme de Bredies-Kunisch-Pock.

![Avant — TGVDenoise](figures/before.webp)
![Après — TGVDenoise](figures/after.webp)

*Avant, et après 100 itérations TGV à 0,15 : le grain part, les dégradés restent.*

## Cas d'usage

- **Débruiter le fond de ciel et les nébulosités faibles** sans écraser les dégradés lumineux subtils
  en zones plates artificielles (contrairement à un TV pur).
- **Nettoyer une image linéaire bruitée** avant étirement, quand on veut préserver à la fois les
  bords fins (bras spiraux, filaments) et les transitions douces (halos, gradients de nébuleuse).
- Alternative « sans réglage de patch » aux méthodes Non-Local Means quand le bruit est
  relativement uniforme et que l'on privilégie la fidélité aux dégradés lisses.

## Fonctionnement

Le process traite chaque canal séparément, en float64 pour la stabilité numérique du schéma
itératif. À chaque itération de l'algorithme primal-dual de Chambolle-Pock :

1. **Mise à jour des variables duales `p`** : elles portent sur l'écart entre le gradient de
   l'image lissée `u` et un champ auxiliaire `w`, puis sont projetées dans la boule de rayon `α1`
   (le paramètre `strength`).
2. **Mise à jour des variables duales `q`** : elles portent sur le gradient symétrisé de `w` (qui
   capture ses variations du second ordre), projetées dans la boule de rayon `α0 = 2·α1`.
3. **Mise à jour des variables primales `u` et `w`** : `u` est rapproché de l'image bruitée
   d'origine `f` via un opérateur proximal du terme d'attache aux données, pondéré par la divergence
   de `p` ; `w` absorbe les composantes de gradient que `u` seul ne peut représenter sans créer de
   marches.
4. **Extrapolation** (`u̅ = 2u - u_old`, etc.) qui accélère la convergence du schéma.

Le nombre d'`iterations` fixe la précision de convergence : plus il est élevé, plus le résultat se
rapproche du minimum exact de l'énergie TGV², au prix du temps de calcul. Les opérateurs de
gradient/divergence utilisent des différences finies avec conditions de bord de Neumann (bords
gelés). Le résultat est écrêté dans `[0, 1]`.

## Mathématiques

Soit $f$ l'image bruitée (par canal) et $u$ l'image débruitée recherchée. La TGV² minimise
l'énergie :

$$ \min_{u,\,w} \; \tfrac{1}{2}\lVert u - f \rVert_2^2 \;+\; \alpha_1 \lVert \nabla u - w \rVert_1
\;+\; \alpha_0 \lVert \mathcal{E}(w) \rVert_1 $$

où $w$ est un champ vectoriel auxiliaire et $\mathcal{E}(w) = \tfrac{1}{2}(\nabla w + \nabla w^{\mathsf T})$
est le **gradient symétrisé** (tenseur de déformation) de $w$, qui pénalise ses variations du
second ordre. Le premier terme est l'attache aux données (fidélité à l'image bruitée), le deuxième
force $\nabla u$ à rester proche du champ lisse $w$ plutôt que d'être pénalisé directement (ce qui
autorise des gradients non nuls sans coût, d'où l'absence d'effet d'escalier), le troisième
régularise $w$ pour qu'il reste lui-même lisse. Le ratio standard $\alpha_0 = 2\alpha_1$ est utilisé
ici, conformément à la recommandation de Bredies-Kunisch-Pock.

Le problème est résolu par sa formulation **primal-dual** : les termes $\ell_1$ sont réécrits comme
des transformées de Legendre-Fenchel, faisant apparaître les variables duales $p$ (associée à
$\nabla u - w$) et $q$ (associée à $\mathcal{E}(w)$), chacune projetée à chaque itération sur une
boule de rayon $\alpha_1$, resp. $\alpha_0$ :

$$ p \leftarrow \frac{p}{\max\!\big(1,\; \lVert p \rVert_2 / \alpha_1\big)}, \qquad
   q \leftarrow \frac{q}{\max\!\big(1,\; \lVert q \rVert_2 / \alpha_0\big)} $$

Les pas primal et dual sont fixés à $\tau = \sigma = 1/\sqrt{12}$, une valeur garantissant la
convergence puisque $\tau\sigma\lVert L \rVert^2 \le 1$ pour l'opérateur linéaire combiné $L$ du
système (dont la norme est bornée par $12$). La mise à jour primale de $u$ s'écrit comme un
opérateur proximal explicite du terme quadratique d'attache aux données :

$$ u \leftarrow \frac{u + \tau\,\operatorname{div}(p) + \tau f}{1 + \tau} $$

et l'extrapolation de Chambolle-Pock ($\bar u = 2u - u_{\text{old}}$) accélère la convergence vers
le point-selle de l'énergie.

## Paramètres

- **`strength`** — *real*, défaut `0.1`, plage `0.001`–`5.0`. Poids de régularisation `α1` (le
  poids du second ordre `α0` est dérivé automatiquement comme `2·α1`). Plus la valeur est élevée,
  plus le lissage est fort (bruit réduit, mais risque d'atténuer les détails fins) ; plus elle est
  basse, plus le débruitage est subtil.
- **`iterations`** — *int*, défaut `100`, plage `1`–`2000`. Nombre d'itérations du schéma
  primal-dual. Plus d'itérations = convergence plus proche de l'optimum, au prix d'un temps de
  calcul proportionnel (l'algorithme est en pur numpy et ne relâche pas le GIL nativement).

## Astuces & pièges

> **Attention** — la complexité est linéaire en `iterations` et le calcul se fait en float64
> canal par canal : sur de grandes images (>20 mégapixels) avec beaucoup d'itérations, le temps
> de traitement peut devenir significatif. Commencez avec `iterations` modéré (50–150) pour juger
> visuellement de la convergence avant d'augmenter.

- Une valeur de `strength` trop élevée peut légèrement flouter les étoiles les plus faibles :
  travaillez sous masque (masque d'étoiles inversé) si vous voulez protéger les points fins.
- Contrairement à un flou gaussien ou un TV classique, la TGV² ne « plate-ifie » pas les
  dégradés lumineux : c'est le choix à privilégier sur des images avec nébulosité étendue et
  transitions douces (halos galactiques, IFN).
- Si le résultat semble sous-débruité malgré une `strength` élevée, augmentez plutôt `iterations` :
  le schéma primal-dual converge lentement pour les hautes valeurs de régularisation.

## Voir aussi

- [NonLocalMeansDenoise](retina-doc://NonLocalMeansDenoise) — débruitage par patchs similaires,
  meilleur sur la texture fine et les étoiles faibles.
- [ACDNR](retina-doc://ACDNR) — lissage adaptatif rapide guidé par le gradient local.
- [WaveletDenoise](retina-doc://WaveletDenoise) — débruitage multi-échelle par seuillage d'ondelettes.
- [NoiseReduction](retina-doc://NoiseReduction) — autres méthodes de réduction de bruit génériques.

## Références

- Bredies, K., Kunisch, K., Pock, T. — *Total Generalized Variation*, SIAM Journal on Imaging
  Sciences, 2010.
- Chambolle, A., Pock, T. — *A First-Order Primal-Dual Algorithm for Convex Problems with
  Applications to Imaging*, Journal of Mathematical Imaging and Vision, 2011.
