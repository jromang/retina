---
id: MultiscaleMedianTransform
category: MultiscaleProcessing
title: Transformée médiane multi-échelle
brief: "Décomposition non linéaire par filtres médians à trous (MMT) : débruitage et rehaussement préservant mieux les bords que la transformée en ondelettes linéaire."
keywords: [multi-échelle, médiane, à trous, ondelettes, débruitage, préservation des bords, MMT]
related: [MultiscaleLinearTransform, WaveletDenoise, ACDNR, NoiseReduction]
icon: stack
references:
  - "PixInsight — MultiscaleMedianTransform tool reference."
  - "Starck, J.-L., Murtagh, F. — Astronomical Image and Data Analysis (median multiresolution)."
---

## Résumé

`MultiscaleMedianTransform` (MMT) décompose l'image en une pile de couches de détail plus un
résidu, exactement comme `MultiscaleLinearTransform` (la transformée starlet), mais en
remplaçant la convolution linéaire à noyau B3-spline par un **filtre médian « à trous »** à
chaque échelle. Le filtre médian étant non linéaire et résistant aux valeurs extrêmes, la
décomposition qui en résulte **préserve mieux les bords nets** (contours d'étoiles, jonctions
de structures) et produit **moins d'artefacts en anneau** (ringing) autour des objets contrastés
que son équivalent linéaire. C'est l'outil de choix quand le débruitage ou le rehaussement par
ondelettes classique laisse des halos visibles.

## Cas d'usage

- **Débruiter le fond de ciel** en atténuant/seuillant la couche de détail la plus fine (bruit
  pixel-à-pixel) sans flouter les bords des étoiles, contrairement à un flou gaussien global.
- **Rehausser des structures à une échelle donnée** (filaments de nébuleuse, bras de galaxie) en
  amplifiant sélectivement une couche via `bias`, sans faire ressortir le bruit des autres échelles.
- **Alternative à `MultiscaleLinearTransform`** quand celle-ci produit des anneaux clairs/sombres
  autour des étoiles saturées ou des bords très contrastés.
- **Préparer une base propre** avant un étirement (`AdaptiveStretch`, `HistogramTransformation`)
  en retirant le bruit de la couche fine dès l'espace linéaire.

## Fonctionnement

Pour chaque canal, l'algorithme construit une pyramide **« à trous »** (non décimée, comme la
starlet) mais en médiane plutôt qu'en convolution :

1. À l'échelle $j$ (partant de $j=0$), on filtre l'image courante $c_j$ par un **filtre médian
   dilaté** : le support du filtre a une empreinte de taille $(2s+1)\times(2s+1)$ avec
   $s = 2^{j}$, mais seuls les pixels espacés de $s$ (les « trous ») participent réellement au
   calcul de la médiane — exactement l'astuce à trous de la starlet, appliquée ici à un
   estimateur médian plutôt qu'à une convolution.
2. La **couche de détail** $j$ est la différence entre l'image avant et après ce filtrage
   médian : $w_j = c_j - c_{j+1}$.
3. On répète `scales` fois, en doublant le pas de dilatation à chaque itération, ce qui sonde des
   structures de taille croissante sans jamais sous-échantillonner l'image (la résolution reste
   pleine à toutes les échelles).
4. Il reste un **résidu** $c_J$ (l'image lissée à la plus grande échelle), qui porte la tonalité
   globale.
5. Optionnellement, la couche la plus fine ($j=0$, dominée par le bruit de lecture/photonique)
   subit un **seuillage doux** piloté par `noise_threshold`, puis chaque couche est multipliée
   par son **biais** (`bias`) avant recombinaison.
6. La **reconstruction** est une simple somme télescopique : détails pondérés + résidu redonnent
   l'image (à l'identité près si biais = 1 et seuil = 0).

## Mathématiques

Notons $M_s$ l'opérateur de filtrage médian « à trous » de pas $s$ (empreinte dilatée de taille
$2s+1$, échantillonnée tous les $s$ pixels). La pyramide se construit récursivement :

$$ c_0 = I, \qquad c_{j+1} = M_{2^{j}}(c_j), \qquad w_j = c_j - c_{j+1}, \quad j = 0,\dots,J-1, $$

où $J$ = `scales`. Contrairement à la starlet (où $M$ est une convolution linéaire et donc la
somme se justifie algébriquement de façon triviale), la médiane est non linéaire — la
reconstruction reste néanmoins **exacte par construction**, car chaque $w_j$ est défini comme
une différence télescopique :

$$ I = \sum_{j=0}^{J-1} w_j + c_J. $$

Le débruitage applique un **seuillage doux** (soft-threshold) sur la couche la plus fine, avec
un seuil dérivé de l'écart-type robuste (`mad_std`, cohérent avec une loi normale via le facteur
$1{,}4826$) :

$$ t = \texttt{noise\_threshold} \cdot \operatorname{mad\_std}(w_0), \qquad
   \tilde w_0 = \operatorname{sign}(w_0)\cdot \max\!\big(|w_0| - t,\; 0\big). $$

Chaque couche est ensuite pondérée par son biais $b_j$ (`bias[j]`, ou $1$ par défaut) avant
recombinaison :

$$ I' = \sum_{j=0}^{J-1} b_j\, \tilde w_j \;+\; c_J, \qquad \text{puis écrêtage dans } [0,1]. $$

Prendre $b_j = 0$ pour toutes les couches fines et $b_j = 1$ pour les grandes revient à un
lissage médian multi-échelle pur ; augmenter un $b_j > 1$ amplifie sélectivement l'échelle $j$.

## Paramètres

- **`scales`** — *int*, défaut `4`, plage `1`–`10`. Nombre de couches de détail (donc de passes
  de filtrage médian à trous). Plus de couches sondent des structures plus grandes, au prix d'un
  temps de calcul croissant (empreinte du filtre médian de plus en plus grande).
- **`bias`** — *floatlist*, défaut `[]`. Multiplicateur appliqué à chaque couche de détail avant
  recombinaison (`bias[0]` pour la couche la plus fine, etc.). Les échelles au-delà de la
  longueur de la liste gardent un biais de `1.0` (reconstruction fidèle). Une liste vide laisse
  toutes les couches inchangées.
- **`noise_threshold`** — *real*, défaut `0.0`, plage `0`–`10`. Seuil de débruitage (en multiples
  de `mad_std`) appliqué **uniquement à la couche la plus fine** (échelle 1, dominée par le
  bruit). `0` désactive le seuillage ; des valeurs typiques utiles vont de `1` à `4`.

## Astuces & pièges

> **Attention** — le filtre médian est nettement plus coûteux qu'une convolution : sur de
> grandes images et avec beaucoup d'échelles, `MultiscaleMedianTransform` est plus lent que
> `MultiscaleLinearTransform`. Réservez-le aux cas où les anneaux linéaires posent réellement
> problème.

- Le seuillage doux n'agit que sur la première couche (`j=0`) : pour débruiter des échelles plus
  grossières, ajustez plutôt leur `bias` directement (par exemple `bias=[1, 0.5]` atténue la
  deuxième couche de moitié).
- Comparez toujours avec `MultiscaleLinearTransform` sur la même image : la médiane gagne sur les
  bords nets (étoiles, limbe planétaire) mais peut légèrement moins bien lisser les zones de
  bruit gaussien pur, où la moyenne pondérée B3-spline est optimale.
- Pour un rehaussement ciblé d'une seule structure (filaments, dentelles), isolez sa couche en
  mettant les autres biais à `0` afin de visualiser précisément ce qu'elle contient avant de
  choisir le gain final.

## Voir aussi

- [MultiscaleLinearTransform](retina-doc://MultiscaleLinearTransform) — la même décomposition à
  trous, mais avec un noyau B3-spline linéaire (starlet).
- [WaveletDenoise](retina-doc://WaveletDenoise) — débruitage par ondelettes discrètes classiques.
- [ACDNR](retina-doc://ACDNR) — réduction de bruit adaptative avec préservation de contours.
- [NoiseReduction](retina-doc://NoiseReduction) — débruitage générique mono-échelle.

## Références

- PixInsight — *MultiscaleMedianTransform* tool reference.
- Starck, J.-L., Murtagh, F. — *Astronomical Image and Data Analysis* (median multiresolution).
