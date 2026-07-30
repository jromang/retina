---
id: Blink
category: ImageInspection
title: Blink
brief: Fait défiler une séquence de frames avec des statistiques rapides par image, pour trier visuellement les brutes.
keywords: [blink, inspection, tri, séquence, défilement, statistiques rapides, sélection de brutes]
related: [SubframeSelector, Statistics, ImageIdentifier, CosmeticCorrection]
icon: eye
references:
  - "PixInsight — Blink process reference."
---

## Résumé

`Blink` est le **cœur headless de l'inspecteur de séquence** : il charge une liste de fichiers,
calcule pour chacun quelques statistiques rapides (médiane, min, max, dimensions) et permet de
naviguer d'une frame à l'autre par un index courant. C'est l'équivalent scriptable du panneau
« Blink » de PixInsight, qui fait défiler une pile de brutes pour un tri visuel — ici toute la
logique de chargement et de navigation est testable sans Qt ; un panneau GUI n'a qu'à afficher
`current_image()` et appeler `step()`.

## Cas d'usage

- **Trier une série de brutes** avant calibration : repérer les poses floues, nuageuses, avec
  satellite ou avion, bougées par le suivi.
- **Contrôler visuellement une session** en enchaînant rapidement les vues, à la manière d'un
  film image par image.
- **Préparer un tri automatique** en s'appuyant sur les statistiques (`median`, `min`, `max`)
  calculées par frame, en amont d'un filtrage plus poussé avec `SubframeSelector`.
- **Vérifier la cohérence géométrique** d'une pile (même `shape`) avant intégration.

## Fonctionnement

`load()` parcourt la liste `frames`, charge chaque fichier via le chargeur d'image générique
(FITS, XISF, TIFF/PNG/JPEG, RAW…), le convertit en `float32`, et calcule pour chacun un petit
dictionnaire de statistiques : médiane, minimum, maximum et forme `(H, W, C)`. Ces dictionnaires
sont accumulés dans `self.stats`, dans l'ordre des fichiers, et l'index courant est remis à 0.

`current_image()` renvoie l'`Image` correspondant à l'index courant (chargeant la séquence au
besoin si elle ne l'a pas encore été). `step(delta)` déplace l'index courant de `delta` positions,
avec **rebouclage** (`modulo` la longueur de la séquence) : `step(1)` avance d'une frame,
`step(-1)` recule, et l'on ne sort jamais des bornes de la liste.

En tant que process **global** (`is_global = True`), `execute_global(app)` se contente d'appeler
`load()` — il ne crée pas de nouvelle fenêtre (`creates_window = False`) : Blink ne produit pas
d'image de sortie, il **inspecte** une séquence existante. Le défilement effectif (affichage,
raccourcis clavier, aperçu miniature) est piloté par la GUI, qui s'appuie uniquement sur
`current_image()` et `step()`.

## Mathématiques

Ce process n'a pas de fondement mathématique propre : c'est un outil d'**inspection et de
navigation**, sans transformation de pixels. Les seules quantités calculées sont des statistiques
élémentaires par frame — médiane $\operatorname{med}(x)$, minimum $\min(x)$ et maximum $\max(x)$
sur l'ensemble des échantillons $x$ de l'image — utilisées comme repères rapides pour le tri, et
non comme des estimateurs robustes destinés à un traitement ultérieur (contrairement au mad_std
utilisé par `Integration`, voir [Integration](retina-doc://Integration)).

## Paramètres

- **`frames`** — *pathlist*, défaut `[]`. Séquence de chemins de fichiers à charger et à faire
  défiler (bruts ou toute autre pile d'images de même nature). L'ordre de la liste détermine
  l'ordre de navigation.

## Astuces & pièges

> **Attention** — `load()` charge **toute la séquence en mémoire** avant de calculer les
> statistiques : sur une très longue série de brutes en pleine résolution, cela peut consommer
> beaucoup de RAM. Pour de gros lots, préférez traiter par sous-groupes.

- Le `median`/`min`/`max` par frame permet de repérer d'un coup d'œil une pose anormalement
  claire (nuage, lune) ou anormalement sombre (obturateur, capuchon oublié) sans ouvrir chaque
  image.
- Les frames de `shape` différente d'un lot par ailleurs homogène signalent souvent un mauvais
  binning ou un recadrage accidentel — à corriger avant `StarAlignment`/`Integration`.
- `step()` reboucle sur la séquence : appeler `step(1)` en boucle permet de tout parcourir sans
  gérer les bornes soi-même.

## Voir aussi

- [SubframeSelector](retina-doc://SubframeSelector) — filtrage/notation automatique des brutes
  (FWHM, seuil de détection).
- [Statistics](retina-doc://Statistics) — statistiques détaillées sur une image unique.
- [ImageIdentifier](retina-doc://ImageIdentifier) — identification/renommage de fenêtres.
- [CosmeticCorrection](retina-doc://CosmeticCorrection) — correction des pixels défectueux
  repérés lors de l'inspection.

## Références

- PixInsight — *Blink* process reference.
