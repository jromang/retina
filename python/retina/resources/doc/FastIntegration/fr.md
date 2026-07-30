---
id: FastIntegration
category: ImageIntegration
title: Intégration rapide (sans rejet)
brief: Empile plusieurs frames par simple moyenne ou médiane, sans rejet sigma — pour un aperçu rapide.
keywords: [intégration, stacking, empilement, moyenne, médiane, aperçu, sans rejet]
related: [Integration, StarAlignment, DrizzleIntegration, ImageCalibration]
icon: stack-2
references:
  - "PixInsight — ImageIntegration tool reference (mode sans rejet)."
  - "numpy.mean / numpy.median."
---

## Résumé

`FastIntegration` combine une liste de frames en une seule image par **moyenne** ou **médiane**
directe, **sans aucun rejet sigma**. C'est la version allégée d'`Integration` : elle sacrifie la
robustesse aux intrus (rayons cosmiques, satellites, avions) contre une vitesse d'exécution bien
supérieure. C'est un process **global** : il lit une liste de fichiers sur disque et crée une
nouvelle fenêtre, il ne s'applique pas à une vue déjà ouverte.

## Cas d'usage

- **Aperçu rapide** d'un empilement pendant une session d'acquisition, pour juger du cadrage ou
  du niveau de bruit sans attendre un rejet sigma complet.
- **Grand nombre de frames** (centaines) où le coût du rejet statistique pixel-par-pixel devient
  pénalisant et où un simple gain de SNR suffit.
- **Frames déjà propres** (peu ou pas d'intrus, par exemple studio/planétaire à cadence élevée)
  où le rejet sigma n'apporterait rien.
- Combinaison **médiane** rapide pour éliminer grossièrement quelques intrus isolés sans le coût
  d'une estimation robuste complète (médiane + mad_std).

## Fonctionnement

Chaque fichier de `frames` est chargé et converti en `float32`, puis toutes les frames sont
empilées en un cube $(N, H, W, C)$ — elles doivent donc avoir la **même géométrie** (déjà
calibrées et alignées, comme pour `Integration`). Selon `combine`, le résultat est soit la
**moyenne**, soit la **médiane** du cube le long de l'axe des frames ($N$), calculée directement
avec `numpy.mean`/`numpy.median` — aucune itération de rejet, aucune pondération, aucune
estimation de bruit par frame. Le résultat est ensuite placé dans une nouvelle fenêtre nommée
`new_image_id`.

## Mathématiques

Pour une pile de valeurs $\{x_i\}_{i=1}^{N}$ à une position de pixel donnée, le résultat vaut
selon `combine` :

$$ \bar{x}_{\text{mean}} = \frac{1}{N}\sum_{i=1}^{N} x_i
   \qquad\text{ou}\qquad
   \bar{x}_{\text{median}} = \operatorname{med}(x_i). $$

La moyenne minimise l'erreur quadratique et améliore le rapport signal/bruit d'un facteur
théorique $\sqrt{N}$ pour un bruit gaussien indépendant identiquement distribué, mais **aucune
valeur n'est écartée** : un seul pixel aberrant (rayon cosmique) contamine directement la
moyenne de ce pixel. La médiane est intrinsèquement plus résistante — elle tolère jusqu'à
$\lfloor N/2 \rfloor$ valeurs aberrantes sans être affectée — mais reste moins efficace que la
moyenne sur du bruit propre, et n'offre pas la finesse d'un rejet sigma adaptatif à la
dispersion locale (comme le mad_std d'`Integration`).

## Paramètres

- **`frames`** — *pathlist*, défaut `[]`. Liste des fichiers à empiler (déjà calibrés et
  alignés, même géométrie pour tous).
- **`combine`** — *enum*, défaut `mean`, choix : `mean`, `median`. Mode de combinaison : moyenne
  simple (meilleur SNR sur données propres) ou médiane (résiste mieux aux intrus isolés).
- **`new_image_id`** — *str*, défaut `fast_integration`. Identifiant de la fenêtre résultat.

## Astuces & pièges

> **Attention** — sans rejet sigma, un unique rayon cosmique ou une traînée de satellite sur une
> seule frame **survit** dans le résultat (atténué mais présent en `mean`, potentiellement visible
> tel quel si plus de la moitié des frames est contaminée à la même position en `median`). Pour
> un master final destiné au traitement définitif, préférez `Integration`.

- Les frames doivent être **alignées** au préalable (`StarAlignment`) : `FastIntegration`
  n'effectue aucun recalage et empile pixel à pixel.
- Utile en **prévisualisation rapide** pendant l'acquisition ; basculez sur `Integration` pour le
  master final une fois la session terminée.
- `combine = median` est un bon compromis quand quelques frames sont clairement mauvaises mais
  qu'on ne veut pas payer le coût du rejet sigma complet.

## Voir aussi

- [Integration](retina-doc://Integration) — empilement avec rejet sigma robuste (médiane +
  mad_std), pour le master final.
- [StarAlignment](retina-doc://StarAlignment) — recalage des frames, préalable indispensable.
- [DrizzleIntegration](retina-doc://DrizzleIntegration) — intégration drizzle (sur-échantillonnage).
- [ImageCalibration](retina-doc://ImageCalibration) — calibration bias/dark/flat en amont.

## Références

- PixInsight — *ImageIntegration* tool reference (mode sans rejet).
- numpy — *mean* / *median*.
