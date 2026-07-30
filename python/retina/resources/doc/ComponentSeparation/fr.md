---
id: ComponentSeparation
category: ColorCalibration
title: Séparation de composantes
brief: Décompose les canaux en composantes PCA/ICA décorrélées ou indépendantes, pixel par pixel.
keywords: [PCA, ICA, décorrélation, canaux, narrowband, gradient, scikit-learn, blanchiment]
related: [ChannelExtraction, ChannelCombination, LRGBCombination, GradientCorrection]
icon: arrows-split
references:
  - "scikit-learn — sklearn.decomposition.PCA / FastICA."
  - "Hyvärinen, A., Oja, E. — Independent Component Analysis: Algorithms and Applications (2000)."
  - "Jolliffe, I.T. — Principal Component Analysis (2002)."
---

## Résumé

`ComponentSeparation` traite les `C` canaux d'une image couleur comme un ensemble de signaux
mélangés et en extrait une nouvelle base de `C` composantes, via **analyse en composantes
principales (PCA)** ou **analyse en composantes indépendantes (ICA)**. Contrairement à une
transformation par canal (STF, courbes…), l'opérateur regarde la **corrélation entre canaux**
pixel par pixel et recombine l'information plutôt que de l'étirer canal par canal. Il sert
typiquement à isoler un gradient ou un signal commun à toutes les couches, ou à séparer un
continuum d'une raie étroite en imagerie narrowband.

## Cas d'usage

- **Isoler un gradient corrélé** (pollution lumineuse, vignettage résiduel) présent de façon
  similaire sur R, G et B : la 1ʳᵉ composante PCA le capture souvent presque intégralement.
- **Décorréler une combinaison LRGB** ou une image bi/tri-bande narrowband (Hα/OIII/SII) pour
  séparer le continuum stellaire du signal de raie spécifique à chaque filtre.
- **Explorer la structure du signal** avant un traitement ciblé : la composante dominante
  concentre le signal/bruit commun, les suivantes isolent des résidus plus fins (chrominance,
  artefacts spécifiques à un canal).
- **Préparer un masque ou une combinaison** à partir d'une composante isolée plutôt que d'un
  canal brut, quand celui-ci mélange plusieurs sources de signal.

## Fonctionnement

Chaque pixel `(x, y)` est vu comme un **vecteur de dimension `C`** (un échantillon), l'image
entière formant un nuage de `H×W` échantillons dans cet espace à `C` dimensions. Le process :

1. **Aplati** l'image `(H, W, C)` en une matrice `(N, C)` avec `N = H·W`.
2. **Ajuste un modèle** scikit-learn sur cette matrice selon `method` :
   - `pca` — `sklearn.decomposition.PCA(n_components=C, whiten=whiten)` : diagonalise la
     covariance entre canaux et projette sur ses axes propres, ordonnés par variance
     décroissante.
   - `ica` — `sklearn.decomposition.FastICA(n_components=C, whiten="unit-variance")` : recherche
     une base qui maximise la **non-gaussianité** (donc l'indépendance statistique) des
     composantes, sans ordre de variance imposé.
3. **Reprojette** les composantes obtenues `(N, C)` dans la géométrie `(H, W, C)` de l'image.
4. **Renormalise chaque composante indépendamment** dans `[0, 1]` (min-max par bande), pour que
   le résultat reste affichable et enchaînable avec d'autres process.

Le nombre de canaux en sortie est **inchangé** (`C` composantes pour `C` canaux d'entrée) — seule
leur signification change : ce ne sont plus R/G/B mais des axes de variance ou d'indépendance.
L'opérateur nécessite **au moins 2 canaux** ; sur une image mono-canal, il renvoie les données
inchangées. Le module importe `sklearn` en paresseux, uniquement à l'exécution.

## Mathématiques

**PCA.** Soit $X \in \mathbb{R}^{N \times C}$ la matrice des pixels centrés (chaque colonne de
moyenne nulle). La covariance inter-canaux est :

$$ \Sigma = \frac{1}{N-1} X^{\top} X \in \mathbb{R}^{C \times C}. $$

PCA diagonalise $\Sigma$ en vecteurs et valeurs propres $\Sigma v_k = \lambda_k v_k$, avec
$\lambda_1 \ge \lambda_2 \ge \dots \ge \lambda_C \ge 0$. La $k$-ième composante est la projection
$c_k = X v_k$, de variance $\lambda_k$ : la composante 1 concentre la plus grande part de la
variance commune aux canaux (typiquement le signal/gradient corrélé), les suivantes les résidus
orthogonaux. Avec `whiten = True`, chaque composante est en outre normalisée par
$\sqrt{\lambda_k}$ pour obtenir une variance unité — utile quand les composantes doivent ensuite
alimenter un traitement sensible à l'échelle (ex. ICA en cascade).

**ICA.** FastICA cherche une matrice de démélange $W$ telle que $S = XW$ ait des composantes
**statistiquement indépendantes**, en maximisant un proxy de non-gaussianité (négentropie) plutôt
que la seule variance :

$$ J(w) \approx \big[\, \mathbb{E}\{G(w^{\top}x)\} - \mathbb{E}\{G(\nu)\} \,\big]^2, $$

où $\nu$ est une gaussienne standard et $G$ une fonction non quadratique (par défaut `logcosh`
dans scikit-learn). L'algorithme itère par point fixe sous contrainte de blanchiment
(`whiten="unit-variance"`), qui pré-décorrèle et normalise les canaux avant la recherche
d'indépendance — d'où l'absence d'ordre de variance imposé entre composantes ICA, à la différence
de PCA. Par construction, le théorème central limite justifie l'approche : un mélange de sources
indépendantes est *plus* gaussien que chaque source prise séparément, donc maximiser la
non-gaussianité de $w^\top x$ tend à isoler une source originale.

Dans les deux cas, la sortie par bande $k$ est enfin renormalisée :

$$ \hat{c}_k(x,y) = \frac{c_k(x,y) - \min c_k}{\max c_k - \min c_k}, $$

(ou $0$ partout si $\max c_k = \min c_k$, cas dégénéré d'une composante constante).

## Paramètres

- **`method`** — *enum*, défaut `pca`, choix `pca` / `ica`. Algorithme de décomposition : `pca`
  pour une base orthogonale ordonnée par variance (rapide, déterministe), `ica` pour une base
  qui maximise l'indépendance statistique (plus coûteux, légèrement stochastique via
  `random_state` fixé en interne, mais reproductible).
- **`whiten`** — *bool*, défaut `True`. Blanchiment appliqué **uniquement en mode PCA** (ICA
  blanchit toujours en interne, indépendamment de ce paramètre) : normalise chaque composante à
  variance unité avant renormalisation `[0,1]`, ce qui égalise le contraste entre composantes de
  variance très différente.

## Astuces & pièges

> **Attention** — les composantes de sortie ne correspondent **plus** aux canaux R/G/B d'origine :
> ne recombinez pas naïvement en `ChannelCombination` en espérant retrouver une image couleur
> fidèle. Utilisez ce process pour l'**inspection** ou pour isoler une composante spécifique
> (ex. via `ChannelExtraction` sur le résultat), pas comme étape neutre d'un pipeline colorimétrique.

> **Note** — PCA n'a pas de garantie de signe ni d'échelle absolue par composante : la
> renormalisation min-max peut inverser visuellement le contraste d'une composante d'une exécution
> à l'autre selon le signe du vecteur propre retenu par l'implémentation.

- Sur une image RGB classique bien calibrée, la composante 1 en PCA ressemble souvent à une
  version en niveaux de gris (luminance) ; les composantes 2/3 mettent en évidence des différences
  chromatiques fines, utiles pour repérer un gradient de couleur résiduel.
- En narrowband, tentez `ica` plutôt que `pca` pour chercher une séparation continuum/raie plus
  proche d'une indépendance physique réelle des sources ; comparez les deux méthodes, le résultat
  dépend fortement du degré de mélange réel des canaux.
- Le calcul opère sur `float64` en interne pour la stabilité numérique de la décomposition, puis
  reconvertit en `float32` — coût mémoire à anticiper sur de très grandes images.

## Voir aussi

- [ChannelExtraction](retina-doc://ChannelExtraction) — isoler une composante ou un canal après
  décomposition.
- [ChannelCombination](retina-doc://ChannelCombination) — recomposer une image couleur à partir
  de canaux ou de composantes.
- [LRGBCombination](retina-doc://LRGBCombination) — combinaison inverse, à base de luminance
  explicite plutôt que d'axes statistiques.
- [GradientCorrection](retina-doc://GradientCorrection) — retrait direct d'un gradient global,
  alternative plus simple quand la corrélation inter-canaux n'est pas exploitée.

## Références

- scikit-learn — *sklearn.decomposition.PCA* / *FastICA*.
- Hyvärinen, A., Oja, E. — *Independent Component Analysis: Algorithms and Applications* (2000).
- Jolliffe, I.T. — *Principal Component Analysis* (2002).
