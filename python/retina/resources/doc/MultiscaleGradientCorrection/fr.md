---
id: MultiscaleGradientCorrection
category: BackgroundModelization
title: Correction de gradient multi-échelle
brief: Retire le gradient grande échelle (résidu starlet) en préservant les détails fins de l'image.
keywords: [gradient, fond de ciel, starlet, à trous, multi-échelle, pollution lumineuse, survey, référence]
related: [SurveyReference, GradientCorrection, MultiscaleLinearTransform, BackgroundExtraction, RollingBallBackground]
icon: stack
references:
  - "Starck, J.-L. & Murtagh, F. — Astronomical Image and Data Analysis (transformée en ondelettes à trous / starlet)."
  - "PixInsight — MultiscaleLinearTransform / gradient removal notes."
---

## Résumé

`MultiscaleGradientCorrection` retire le **gradient de fond grande échelle** (pollution
lumineuse, lueur lunaire, vignetage résiduel) en s'appuyant sur une **décomposition en
ondelettes starlet** (transformée « à trous »). Contrairement à un simple ajustement de
surface polynomiale, la séparation se fait dans le domaine des échelles spatiales : toutes
les structures fines (étoiles, nébulosités, bruit) sont conservées intactes, seul le résidu
de très basse fréquence — l'échelle la plus grossière de la décomposition, qui porte le
gradient — est aplati.

## Cas d'usage

- Retirer un **gradient de pollution lumineuse** sur un champ large sans risquer d'éroder
  les nébulosités étendues, contrairement à une extraction de fond par grille de cases.
- Corriger un **vignetage résiduel** mal calibré par les flats, quand sa forme n'est pas
  bien décrite par un simple polynôme de bas degré.
- Préparer un fond homogène avant `BackgroundNeutralization` ou une calibration colorimétrique,
  sur des images où le gradient est doux et à grande échelle plutôt que localisé.

## Fonctionnement

Pour chaque canal, l'image est décomposée par la **transformée starlet** (`starlet_transform`,
noyau B3-spline « à trous ») en `scale` couches de détails $w_1, \dots, w_n$ plus un
**résidu** de basse résolution $c_n$ qui contient les variations les plus lentes de l'image —
en pratique le gradient de fond. Le process **remplace ce résidu par sa médiane** (une
constante scalaire), ce qui élimine sa structure spatiale tout en préservant son niveau
moyen, puis reconstruit l'image en resommant les couches de détails inchangées avec ce
résidu aplati et un **piédestal**. Le résultat est reclippé dans `[0, 1]`.

Plus `scale` est grand, plus le résidu final correspond à une échelle spatiale large (le
support effectif du filtre double à chaque niveau), donc plus la correction cible
spécifiquement les gradients très étendus en épargnant les structures de taille moyenne.

## Mathématiques

La décomposition starlet reconstruit exactement l'image d'origine comme somme des détails et
du résidu :

$$ I = \sum_{j=1}^{n} w_j + c_n, \qquad w_j = c_{j-1} - c_j, $$

où $c_0 = I$ et $c_j$ est obtenu par convolution séparable de $c_{j-1}$ avec le noyau
B3-spline dilaté d'un facteur $2^{j-1}$ :

$$ B_3 = \tfrac{1}{16}(1, 4, 6, 4, 1), \qquad c_j = c_{j-1} * B_3^{(2^{j-1})}. $$

Chaque couche $w_j$ capture les variations spatiales de fréquence décroissante avec $j$, et le
résidu final $c_n$ (après $n$ = `scale` niveaux) ne contient que les variations dont l'échelle
caractéristique dépasse $\sim 2^{n}$ pixels — le gradient de fond en est l'archétype.

La correction remplace $c_n$ par sa médiane globale $\tilde{c}_n = \operatorname{med}(c_n)$ et
ajoute un piédestal $p$ :

$$ I' = \sum_{j=1}^{n} w_j + \tilde{c}_n + p = I - \big(c_n - \tilde{c}_n\big) + p. $$

Le terme $c_n - \tilde{c}_n$ est exactement le **modèle de gradient soustrait** : la carte du
résidu recentrée sur son propre niveau médian. Utiliser la médiane plutôt que la moyenne rend
l'estimation du niveau de fond résistante aux zones où le résidu basse fréquence est
localement contaminé par un objet très étendu.

## Avec une référence externe

Remplacer le résidu par une constante suppose que **tout** ce qui est grande échelle est du
gradient. Cette hypothèse est fausse dès que le champ porte un vrai signal étendu :
nébulosité, IFN, halo externe d'une galaxie. Eux aussi sont grande échelle, et ils sont
aplatis avec la pollution lumineuse.

Donnez au process une **référence** — une image du même champ, connue pour être exempte de
votre gradient, typiquement produite par [SurveyReference](retina-doc://SurveyReference)
depuis un survey couvrant tout le ciel — et l'ambiguïté disparaît. Au lieu d'une constante,
le ciel à grande échelle est modélisé par un **ajustement affine** robuste du propre résidu
starlet de la référence :

$$ \text{ciel} = a\,c_n^{\text{ref}} + b, \qquad I' = \sum_{j=1}^{n} w_j + \text{ciel} + p, $$

où $(a, b)$ sont estimés par moindres carrés sous sigma-clipping. Ce que l'image porte *en
plus* de la forme de la référence est le gradient, et lui seul.

C'est l'ajustement affine qui rend la méthode robuste à la référence elle-même : une plaque
de survey n'est ni linéaire ni photométrique, et n'a pas besoin de l'être — tout facteur
d'échelle et tout décalage sont absorbés par $a$ et $b$. Les étoiles de la référence vivent
dans les couches de détail, qui sont jetées, donc elles n'entrent jamais dans l'ajustement.
Si la référence est plate, ou si l'ajustement rend une pente négative ou nulle (mauvais
champ, survey ne couvrant pas la zone, image déjà corrigée), le process **retombe** sur le
comportement sans référence et le dit dans le centre de notifications — un repli muet
ressemblerait à une correction qui a marché.

C'est l'idée du *MARS* de PixInsight, sans le survey propriétaire : l'écart était un écart
de données, pas d'algorithme.

## Paramètres

- **`scale`** — *int*, défaut `7`, plage `3`–`12`. Nombre de couches de la décomposition
  starlet (échelle du gradient). Plus la valeur est grande, plus la correction cible un
  gradient à support spatial large ; une valeur trop faible risque d'aplatir aussi des
  structures de taille moyenne (nébulosités diffuses).
- **`pedestal`** — *real*, défaut `0.1`, plage `0`–`1`. Décalage additif appliqué après
  correction, pour éviter que le nouveau fond de ciel ne soit trop proche de 0 (valeurs
  négatives écrêtées).
- **`reference`** — *str*, défaut vide. Id d'une vue portant une image sans gradient du même
  champ. Les deux paramètres de référence vides = comportement classique, sans référence.
- **`reference_path`** — *str*, défaut vide. La même chose depuis un fichier, prioritaire.
  N'importe quel FITS aligné convient — une référence de survey, mais aussi une pose grand
  champ de votre cru.

## Astuces & pièges

> **Attention** — une `scale` trop petite (proche de 3) traite des nébulosités étendues comme
> du gradient et les aplatit avec le fond : elles perdent leur variation lente naturelle.
> Augmentez `scale` ou passez par un masque protégeant l'objet.

> **Note** — le résidu remplacé est une **constante par canal** (la médiane globale), pas une
> surface interpolée : `MultiscaleGradientCorrection` corrige donc un gradient déjà relativement
> doux et symétrique. Pour un gradient fortement asymétrique ou localisé, préférez
> `GradientCorrection` (polynôme 2D) ou `BackgroundExtraction` (grille de cases).

- Comparez toujours le résultat avec `GradientCorrection` sur la même image : les deux méthodes
  ciblent le même problème par des voies différentes (échelle spatiale vs surface polynomiale),
  et l'une peut mieux convenir selon la forme réelle du gradient.
- Appliquer avant l'étirement (sur données linéaires) donne les meilleurs résultats, comme pour
  toute extraction de fond.

## Voir aussi

- [SurveyReference](retina-doc://SurveyReference) — produit la référence sans gradient que
  ce process sait consommer.
- [GradientCorrection](retina-doc://GradientCorrection) — retrait de gradient par surface
  polynomiale robuste.
- [MultiscaleLinearTransform](retina-doc://MultiscaleLinearTransform) — décomposition starlet
  générale (débruitage, rehaussement par échelle).
- [BackgroundExtraction](retina-doc://BackgroundExtraction) — modèle de fond par grille de cases
  (photutils).
- [RollingBallBackground](retina-doc://RollingBallBackground) — extraction de fond par
  algorithme rolling-ball.

## Références

- Starck, J.-L. & Murtagh, F. — *Astronomical Image and Data Analysis* (transformée en
  ondelettes à trous / starlet).
- PixInsight — notes sur *MultiscaleLinearTransform* et le retrait de gradient.
