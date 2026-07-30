---
id: NoiseEvaluation
category: ImageInspection
title: Évaluation du bruit
brief: Estime la dispersion du bruit par canal, sur les seuls pixels qui n'en contiennent que.
keywords: [bruit, sigma, MRS, support multirésolution, k-sigma, ondelettes, CFA, SNR]
related: [Statistics, NoiseReduction, SubframeSelector, MultiscaleLinearTransform]
icon: wave-sine
references:
  - "Starck, J.-L. & Murtagh, F. (1998) — Automatic noise estimation from the multiresolution support. PASP 110, 193."
  - "PixInsight — script NoiseEvaluation."
---

## Résumé

Sur une image qui porte des étoiles, une nébuleuse et un gradient, un écart-type robuste ne
mesure pas le bruit : il mesure la **structure**. La question à laquelle il faut répondre est
« quelle est la dispersion des pixels qui ne contiennent *que* du bruit », et elle demande de
distinguer d'abord les deux.

L'écart n'est pas marginal. Sur un champ synthétique à huit mille étoiles, avec un bruit injecté
de 0,0030 :

| Méthode | Estimation |
|---|---|
| Écart-type robuste global (MAD × 1,4826) | 0,0223 |
| Écrêtage k-sigma | 0,0066 |
| **Support multirésolution** | **0,0029** |

## Cas d'usage

- **Comparer deux poses**, deux traitements, deux réglages de débruitage — sur une grandeur
  qui veut dire quelque chose.
- **Régler un seuil** exprimé en σ (`MultiscaleLinearTransform`, régularisation de la
  déconvolution) : encore faut-il savoir ce que vaut σ.
- **Vérifier un empilement** : le bruit doit décroître comme la racine du nombre de poses.
  S'il stagne, quelque chose ne s'additionne pas.

## Fonctionnement

### k-sigma

On travaille sur la **première couche de la transformée starlet** — celle où le bruit domine —
et on y écrête itérativement à `k_sigma` dispersions, jusqu'à ce que le résultat cesse de
bouger. Robuste, et il rend toujours quelque chose.

### Support multirésolution (MRS)

On marque significatif tout coefficient d'ondelette dépassant `k_sigma` fois la dispersion
**attendue du bruit à son échelle**, on réunit ces marques, on dilate d'un pixel — une étoile
déborde du pixel qui la trahit — et l'on ne mesure que sur ce qui reste. L'estimation se
réinjecte dans le seuil, jusqu'à convergence.

Le support ne porte que sur les **deux premières échelles**, et c'est une mesure et non un
réglage : au-delà, un champ dense est significatif *partout* aux grandes échelles, ce qui est
vrai mais sans rapport avec le bruit à l'échelle du pixel — et l'estimation renonce. En deçà,
les ailes des étoiles restent comptées comme du fond et le bruit ressort 8 % trop haut sur deux
mille étoiles, 55 % sur huit mille.

Si le support ne laisse plus assez de pixels libres, le process **retombe sur k-sigma** et le
dit : `.result['method']` rend ce qui a *réellement* servi, pas ce qui a été demandé.

### Deux facteurs qu'on oublie

Les coefficients d'ondelette d'un bruit gaussien ne sont pas de même dispersion que le bruit :
la convolution B3-spline les atténue d'un facteur connu et tabulé (0,8907 à la première
échelle). Et mesurer l'écart-type des seuls pixels non écrêtés le sous-estime, puisqu'on a coupé
les queues de la gaussienne — 1,3 % à k = 3. Les deux corrections sont appliquées ; les ignorer
laisse un biais constant que rien ne révèle tant qu'on ne compare qu'à soi-même.

## Le mode CFA

Sur une image **non débayerisée**, les quatre sites de la matrice ont des niveaux différents.
Un filtre qui mélange deux pixels voisins mesure alors leur écart — c'est-à-dire la mosaïque, et
non le bruit. `cfa = True` estime sur les quatre sous-plans séparément.

## Paramètres

- **`method`** — *enum* `mrs` | `ksigma`, défaut `mrs`.
- **`k_sigma`** — *real*, défaut `3.0`, plage `1`–`10`. Seuil d'écrêtage et de significativité.
- **`scales`** — *int*, défaut `4`, plage `1`–`8`. Nombre d'échelles de la transformée.
- **`cfa`** — *bool*, défaut `False`. Image CFA non débayerisée.

Lecture seule. `.result` porte, par canal, `sigma`, `fraction` (la part des pixels ayant servi),
`method`, `background` et `snr`.

## Astuces & pièges

> **Une fraction basse est une information.** Si `fraction` tombe à quelques pour cent, il ne
> reste presque plus de fond : l'estimation tient encore statistiquement (un pour cent d'un
> mégapixel fait dix mille pixels) mais la marge s'amenuise.

- Le bruit se mesure sur données **linéaires**. Après étirement, σ n'est plus une constante de
  l'image : il varie avec le niveau.
- Un `snr` se compare entre poses d'une même série, pas dans l'absolu : il dépend du niveau de
  fond, donc de la pollution lumineuse et de la durée de pose.

## Voir aussi

- [Statistics](retina-doc://Statistics) — les statistiques ordinaires, y compris le MAD que ce
  process existe pour ne pas employer.
- [NoiseReduction](retina-doc://NoiseReduction) — pour agir sur ce qu'on vient de mesurer.
- [SubframeSelector](retina-doc://SubframeSelector) — le bruit d'un lot de poses.

## Références

- Starck, J.-L. & Murtagh, F. (1998). *Automatic noise estimation from the multiresolution
  support*. PASP 110, 193.
- PixInsight — script *NoiseEvaluation*.
