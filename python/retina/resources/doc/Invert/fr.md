---
id: Invert
category: PixelMath
title: Inversion
brief: Calcule le négatif photographique d'une image en remplaçant chaque échantillon x par 1 − x.
keywords: [inversion, négatif, complément, photographique, pixel math, symétrie]
related: [Rescale, Binarize, PixelMath, CurvesTransformation]
icon: contrast
references:
  - "PixInsight — Invert tool reference."
  - "Photographie argentique — inversion négatif/positif."
---

## Résumé

`Invert` transforme chaque échantillon de l'image en son **complément à 1** : les tons clairs
deviennent sombres et inversement, exactement comme le négatif d'une pellicule argentique. C'est
l'opérateur pixel-à-pixel le plus simple du catalogue — aucun paramètre, aucun voisinage, un coût
de calcul quasi nul — mais il reste un outil de travail précieux, en particulier pour l'inspection
visuelle des détails faibles.

## Cas d'usage

- **Traquer les gradients de fond de ciel** : sur une image inversée, les variations douces de
  fond (pollution lumineuse, vignettage résiduel) sautent aux yeux en tant que zones sombres sur
  fond clair, plus faciles à juger que sur l'image directe.
- **Repérer les artefacts** : poussières, halos, colonnes de pixels chauds ou traînées de
  satellites ressortent souvent mieux en négatif, un réflexe hérité du contrôle qualité sur
  planches argentiques.
- **Étape intermédiaire dans une chaîne PixelMath** : combiner `Invert` avec `Rescale` ou
  `Binarize` pour construire des masques (ex. masque d'étoiles inversé en masque de fond).
- **Effet artistique ou pédagogique** : visualiser une image sous un jour inhabituel pour
  détecter des structures autrement invisibles à l'œil.

## Fonctionnement

Le process lit le tableau numpy `(H, W, C)` de la vue, en float32 normalisé sur `[0, 1]`
(convention interne de Retina), et retourne `1.0 - data` calculé terme à terme sur l'ensemble
des canaux. Aucun état, aucune dépendance de voisinage : chaque pixel est traité indépendamment,
ce qui rend l'opération triviale à paralléliser et sans coût mémoire additionnel notable au-delà
du tableau de sortie. L'opération est involutive : appliquer `Invert` deux fois de suite restitue
exactement l'image d'origine (aux arrondis flottants près).

## Mathématiques

Soit $x$ la valeur d'un échantillon dans $[0,1]$ (par canal, indépendamment). L'inversion calcule :

$$ y = 1 - x $$

appliquée composante par composante sur le tenseur $(H, W, C)$. Cette transformation est :

- **affine et bijective** sur $[0,1]$, de pente $-1$ : elle préserve les écarts relatifs entre
  pixels (contraste local inchangé en valeur absolue) tout en inversant leur sens ;
- **involutive** : $y = 1-x \Rightarrow 1-y = x$, donc $\operatorname{Invert}\circ\operatorname{Invert} = \operatorname{id}$ ;
- **sans effet sur la dynamique** : min et max échangent leurs rôles ($\min(y) = 1-\max(x)$,
  $\max(y) = 1-\min(x)$), donc une image bien étirée avant inversion reste bien étirée après.

Il n'y a pas de seuil, de noyau ni de statistique impliqués : c'est une symétrie ponctuelle
autour de $x = 0{,}5$.

## Paramètres

Ce process n'a aucun paramètre : `Invert` ne fait que calculer $1 - x$ sur chaque échantillon,
sans réglage exposé.

## Astuces & pièges

> **Attention** — `Invert` suppose des données normalisées dans `[0, 1]`. Sur une image non
> étirée (données linéaires très concentrées près de 0), le négatif obtenu paraîtra presque
> uniformément blanc : appliquez d'abord un étirement (`HistogramTransformation`, `AutoHistogram`)
> ou travaillez avec la STF active pour juger visuellement du résultat.

- Combiné à un masque, `Invert` permet de retourner rapidement un masque d'étoiles en masque de
  fond de ciel (ou l'inverse) sans recalculer l'extraction.
- Comme l'opération est involutive, elle est idéale pour des comparaisons A/B rapides en console :
  `Invert().execute_on(view)` deux fois de suite ne laisse aucune trace dans les pixels (mais deux
  entrées dans l'historique).
- Ne pas confondre avec l'inversion d'un **masque** (`invert_mask` sur `ImageWindow`), qui inverse
  le rôle protecteur/révélateur du masque sans toucher aux pixels de l'image elle-même.

## Voir aussi

- [Rescale](retina-doc://Rescale) — remappage linéaire de plage, complémentaire pour ajuster la
  dynamique avant ou après inversion.
- [Binarize](retina-doc://Binarize) — seuillage en tout-ou-rien, souvent utilisé avec `Invert`
  pour fabriquer des masques.
- [PixelMath](retina-doc://PixelMath) — pour des expressions arbitraires incluant l'inversion
  comme cas particulier (`1 - $T`).
- [CurvesTransformation](retina-doc://CurvesTransformation) — transformation tonale libre, dont
  l'inversion est un cas limite (courbe en diagonale décroissante).

## Références

- PixInsight — *Invert* tool reference.
- Photographie argentique — inversion négatif/positif.
