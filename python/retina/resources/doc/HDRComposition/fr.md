---
id: HDRComposition
category: ImageIntegration
title: Composition HDR
brief: Fusionne des poses de durées croissantes en une image à grande dynamique, en écartant les pixels saturés.
keywords: [HDR, grande dynamique, poses multiples, saturation, cœurs stellaires, mise à l'échelle]
related: [GradientHDRComposition, Integration, FastIntegration, HDRMultiscaleTransform]
icon: stack
references:
  - "PixInsight — HDRComposition tool reference."
  - "Debevec, P. & Malik, J. — Recovering High Dynamic Range Radiance Maps from Photographs (1997)."
---

## Résumé

`HDRComposition` combine une série de poses de **durées d'exposition croissantes** du même
cadrage en une seule image couvrant une **dynamique plus large** que n'importe quelle pose prise
isolément. Les poses courtes fournissent des cœurs non saturés (étoiles, noyau galactique, cœur
nébulaire brillant) tandis que les poses longues révèlent les extensions faibles ; le process
mesure les niveaux relatifs et exclut à chaque pixel les échantillons trop proches de la
saturation avant de moyenner ce qui reste. C'est un **process global** : il lit une liste de
fichiers et crée une nouvelle fenêtre, sans qu'une vue active soit requise.

## Cas d'usage

- **Cœurs stellaires ou galactiques brûlés** : combiner une pose courte (cœur préservé) avec une
  pose longue (fond et extensions) pour obtenir une image sans zone saturée bouchée.
- **Nébuleuses à fort contraste de brillance** (M42/Orion typiquement) : le trapèze central très
  lumineux et les volutes ténues périphériques ne tiennent pas dans une seule exposition linéaire.
- **Alternative rapide** à un traitement HDR en domaine de gradient
  (`GradientHDRComposition`) quand un simple mélange pondéré par le niveau de saturation suffit.

## Fonctionnement

1. Chaque fichier de `frames` est chargé et sa **médiane globale** est calculée ; cette médiane
   sert de **proxy de durée d'exposition relative** (en réponse linéaire du capteur, le niveau de
   fond de ciel croît à peu près proportionnellement au temps de pose).
2. La médiane la plus élevée — normalement celle de la pose la plus longue — sert de **référence
   d'échelle**. Chaque pose est mise à l'échelle vers ce niveau commun : les poses courtes sont
   amplifiées, la pose de référence reste inchangée.
3. À chaque pixel, une pose n'est retenue dans la moyenne que si sa valeur **brute** (avant mise à
   l'échelle) reste **sous le seuil `saturation`** ; les pixels proches ou au-dessus du seuil sont
   écartés pour cette pose, ce qui protège les cœurs des halos et artefacts de saturation.
4. La valeur finale du pixel est la **moyenne des poses non saturées mises à l'échelle** ; si
   aucune pose n'est valide à cet endroit (toutes saturées), on retombe sur la dernière pose de la
   liste. Le résultat est enfin **renormalisé** par son maximum pour rester dans `[0, 1]`.

## Mathématiques

Soit $f_1, \dots, f_N$ les $N$ poses (indexées par durée croissante), et pour chacune la médiane
globale $\tilde m_i = \operatorname{med}(f_i)$, utilisée comme proxy de durée d'exposition relative.
La référence d'échelle est la médiane la plus haute :

$$ t_{\text{ref}} = \max_i \tilde m_i . $$

Chaque pose est ramenée à cette échelle commune :

$$ \hat f_i(x) = f_i(x) \cdot \frac{t_{\text{ref}}}{\tilde m_i} . $$

Un poids binaire écarte les pixels proches de la saturation, évalué sur la valeur **brute** (non
mise à l'échelle), avec $s$ = `saturation` :

$$ w_i(x) = \mathbb{1}\big[\, f_i(x) < s \,\big] . $$

La composition est la moyenne pondérée des poses valides :

$$ C(x) = \begin{cases}
  \dfrac{\sum_{i=1}^{N} w_i(x)\, \hat f_i(x)}{\sum_{i=1}^{N} w_i(x)} & \text{si } \sum_i w_i(x) > 0 \\[1.2em]
  f_N(x) & \text{sinon}
\end{cases} $$

et l'image finale est renormalisée par son maximum global $M = \max_x C(x)$ :

$$ H(x) = \frac{C(x)}{M} . $$

Ce schéma est une version simplifiée (pensée pour des images déjà en unités relatives $[0,1]$,
sans courbe de réponse du capteur explicite) des méthodes classiques de fusion HDR photographique
(Debevec & Malik) : au lieu d'inverser une courbe de réponse radiométrique, on suppose une réponse
linéaire et on estime le facteur d'échelle par la médiane globale.

## Paramètres

- **`frames`** — *pathlist*, défaut `[]`. Liste des fichiers de poses à combiner, à fournir dans
  l'ordre des **durées croissantes**. Toutes les poses doivent avoir la même géométrie (même
  cadrage, idéalement recalées si l'instrument a bougé entre les prises).
- **`saturation`** — *real*, défaut `0.9`, plage `0.1`–`1.0`. Seuil (en unités normalisées `[0,1]`
  de la pose brute) au-delà duquel un pixel d'une pose est considéré comme saturé et exclu de la
  moyenne pour cette pose.
- **`new_image_id`** — *str*, défaut `hdr`. Identifiant de la fenêtre image créée par le process.

## Astuces & pièges

> **Attention** — les poses doivent être **du même cadrage** ; le process ne recale rien. Passez
> par `StarAlignment` en amont si le télescope a dérivé entre les prises.

> **Note** — l'estimation de la durée relative par la **médiane globale** suppose que le fond de
> ciel domine l'image et croît linéairement avec le temps de pose. Sur un cadrage très dominé par
> un objet ponctuel brillant (comète, planète), ce proxy peut être trompeur.

- Un `saturation` trop élevé (proche de 1.0) laisse passer des pixels presque saturés dans la
  moyenne, ce qui peut réintroduire une légère troncature du cœur. Un seuil trop bas (< 0.5) peut
  écarter presque toute la pose la plus courte sur les zones de fond, la rendant inutile.
- Si toutes les poses saturent au même pixel, la sortie retombe sur la dernière pose de la liste
  (supposée la plus longue) — vérifiez que `frames` est bien trié par durée croissante.
- Pour une fusion plus fine, sans seuil binaire ni hypothèse de réponse linéaire, voir
  `GradientHDRComposition`, qui travaille en domaine de gradient et sélectionne le détail le mieux
  exposé pixel par pixel.

## Voir aussi

- [GradientHDRComposition](retina-doc://GradientHDRComposition) — composition HDR en domaine de
  gradient, sans seuil binaire ni coutures.
- [Integration](retina-doc://Integration) — empilement classique avec rejet sigma robuste (poses
  de même durée).
- [FastIntegration](retina-doc://FastIntegration) — empilement rapide sans rejet, pour un aperçu.
- [HDRMultiscaleTransform](retina-doc://HDRMultiscaleTransform) — compression de dynamique
  multi-échelle sur une image déjà composée.

## Références

- PixInsight — *HDRComposition* tool reference.
- Debevec, P. & Malik, J. — *Recovering High Dynamic Range Radiance Maps from Photographs* (1997).
