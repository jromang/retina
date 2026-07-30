---
id: IntegerResample
category: Geometry
title: Rééchantillonnage entier
brief: Réduit ou agrandit l'image par un facteur entier via binning moyenné/sommé ou réplication de pixels.
keywords: [binning, sous-échantillonnage, sur-échantillonnage, block_reduce, flux conservé, résolution]
related: [Resample, Crop, Integration, BackgroundExtraction]
icon: grid-4x4
references:
  - "PixInsight — IntegerResample tool reference."
  - "astropy.nddata.block_reduce — block reduction by integer factor."
---

## Résumé

`IntegerResample` change la résolution d'une image d'un **facteur entier exact** `factor`,
dans un sens ou dans l'autre : en réduction (*downsample*), il regroupe des blocs de
`factor × factor` pixels en un seul, par **binning** (moyenne ou somme) ; en agrandissement
(*upsample*), il **réplique** chaque pixel en un bloc `factor × factor` identique (nearest
neighbor pur, aucune interpolation). Contrairement à `Resample`, qui accepte un facteur
d'échelle réel quelconque avec interpolation, `IntegerResample` ne traite que des rapports
entiers — c'est l'outil du **binning logiciel** classique en astrophotographie.

## Cas d'usage

- **Simuler un binning capteur** (2×2, 3×3…) a posteriori sur des données acquises en 1×1,
  pour réduire le bruit de lecture apparent et la taille de fichier au prix de la résolution.
- **Prévisualiser rapidement** une image très grande (mosaïque, master haute résolution) en
  la réduisant d'un facteur entier avant un traitement lourd ou un export web.
- **Regrouper les pixels avant intégration** de frames très bruitées (SNR faible par pixel),
  quand la résolution native n'apporte pas d'information exploitable.
- **Agrandir un masque ou une carte de defect map** binnée pour la ré-aligner sur une image
  pleine résolution, sans lisser les bords (réplication exacte).

## Fonctionnement

Le traitement dépend de `mode` :

- **`upsample`** — chaque pixel est dupliqué `factor` fois selon les deux axes
  (`numpy.repeat` sur les lignes puis les colonnes), produisant une image `factor` fois plus
  grande en largeur et en hauteur, sans aucun lissage.
- **`downsample`** — l'image est d'abord **recadrée** au plus grand multiple de `factor`
  inférieur ou égal à ses dimensions (les derniers pixels excédentaires sont abandonnés), puis
  divisée en blocs de `factor × factor` pixels agrégés selon `downsample_op` :
  - `average` — moyenne du bloc (implémentation par reshape + `mean` sur les axes de bloc) ;
    c'est l'équivalent radiométrique d'un binning capteur, qui **réduit le bruit** par pixel
    de sortie sans changer l'échelle des valeurs.
  - `sum` — somme du bloc (via `astropy.nddata.block_reduce`), qui **conserve le flux total**
    — la bonne option pour des données destinées à une mesure photométrique — avec un
    écrêtage final à `[0, 1]` puisque la somme peut dépasser la plage d'une image normalisée.

Si `factor = 1`, l'opération est un no-op (copie de l'image).

## Mathématiques

Soit $I$ l'image d'entrée et $n$ = `factor`. Pour le **downsample**, on recadre d'abord aux
dimensions $H' = \lfloor H/n \rfloor \cdot n$, $W' = \lfloor W/n \rfloor \cdot n$, puis chaque
pixel de sortie $(i,j)$ agrège le bloc source $B_{i,j} = \{(y,x) : ni \le y < n(i+1),\;
nj \le x < n(j+1)\}$ :

$$
O_{\text{average}}(i,j) = \frac{1}{n^2} \sum_{(y,x) \in B_{i,j}} I(y,x), \qquad
O_{\text{sum}}(i,j) = \operatorname{clip}\!\left(\sum_{(y,x) \in B_{i,j}} I(y,x),\; 0,\; 1\right).
$$

Le binning moyen agit comme un filtre passe-bas suivi d'une décimation : si le bruit par
pixel d'entrée est $\sigma$ et non corrélé, le bruit par pixel de sortie devient
$\sigma / n$ (facteur $\sqrt{n^2} = n$), au prix d'une résolution spatiale divisée par $n$ —
c'est le compromis fondamental du binning.

Pour l'**upsample**, chaque pixel source $(y,x)$ est répliqué sur le bloc de sortie :

$$
O(ni + k,\; nj + l) = I(y,x), \qquad 0 \le k, l < n,
$$

ce qui est une interpolation d'ordre 0 (plus proche voisin) : aucune nouvelle information
n'est créée, seule la grille de pixels est densifiée.

## Paramètres

- **`factor`** — *int*, défaut `2`, plage `1`–`16`. Facteur entier de réduction ou
  d'agrandissement appliqué identiquement aux deux axes.
- **`mode`** — *enum*, défaut `downsample`, choix `downsample` / `upsample`. Sens de
  l'opération : réduction par binning ou agrandissement par réplication.
- **`downsample_op`** — *enum*, défaut `average`, choix `average` / `sum`. Opérateur
  d'agrégation en mode réduction : `average` pour un binning radiométrique classique (réduit
  le bruit, garde l'échelle des valeurs), `sum` pour conserver le flux total (usage
  photométrique), avec écrêtage à `[0, 1]`. Ignoré en mode `upsample`.

## Astuces & pièges

> **Attention** — en `downsample`, les pixels situés au-delà du dernier multiple entier de
> `factor` sont **silencieusement abandonnés** (pas de padding). Sur une image 4001×3000 avec
> `factor=2`, la dernière colonne est perdue. Sans conséquence visuelle sur de grandes images,
> mais à garder en tête pour un recadrage précis.

> **Note** — `downsample_op = sum` peut faire dépasser `1.0` un fond de ciel non nul multiplié
> par `factor²` termes ; l'écrêtage final préserve la plage `[0, 1]` mais peut saturer des
> données déjà proches du blanc. Préférez `average` pour un usage purement visuel.

- `upsample` ne fait que répliquer les pixels : pour un agrandissement lissé avec
  interpolation, utilisez plutôt [Resample](retina-doc://Resample).
- Après un `downsample`, l'échantillonnage (arcsec/pixel) est multiplié par `factor` : pensez
  à corriger l'astrométrie (WCS) si l'image doit rester exploitable scientifiquement.
- `is_maskable = False` : la géométrie change, donc aucun masque de blend ne s'applique — le
  process s'exécute toujours sur l'image entière.

## Voir aussi

- [Resample](retina-doc://Resample) — rééchantillonnage à facteur réel avec interpolation.
- [Crop](retina-doc://Crop) — recadrage sans changement d'échelle.
- [Integration](retina-doc://Integration) — combine plusieurs frames, parfois après binning.
- [BackgroundExtraction](retina-doc://BackgroundExtraction) — modélisation de fond, souvent
  effectuée à résolution réduite pour la vitesse.

## Références

- PixInsight — *IntegerResample* tool reference.
- astropy.nddata — *block_reduce*, réduction par bloc à facteur entier.
