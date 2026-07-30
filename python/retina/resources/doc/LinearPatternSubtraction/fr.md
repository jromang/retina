---
id: LinearPatternSubtraction
category: CosmeticCorrection
title: Soustraction de motif linéaire (LPS)
brief: Retire le banding de colonnes ou de lignes des capteurs CMOS, sans toucher au gradient de fond.
keywords: [banding, colonnes, lignes, CMOS, LPS, WBPP, motif, cosmétique, CFA]
related: [LinearDefectDetection, CosmeticCorrection, DefectMap, Overscan]
icon: line
references:
  - "PixInsight — scripts LinearDefectDetection / LinearPatternSubtraction (étape LPS de WBPP)."
---

## Résumé

Beaucoup de capteurs CMOS montrent un **banding** : des colonnes — parfois des lignes — dont le
niveau s'écarte de leurs voisines de quelques ADU. Sur une pose isolée c'est invisible.

Sur cent poses empilées, ça ne l'est plus, et pour une raison qui mérite d'être dite : le motif
est **fixe**, donc il s'additionne d'une pose à l'autre, quand le bruit, lui, se moyenne. Le
rapport signal/bruit du motif *augmente* avec le nombre de poses. C'est l'étape **LPS** de WBPP.

## Comment le motif est séparé du ciel

Pour chaque colonne, on prend la **médiane** de ses pixels. La médiane d'une colonne d'image
astronomique, c'est le fond de ciel à cet endroit : étoiles et nébuleuses y sont minoritaires
et n'y pèsent rien.

Reste à séparer, dans cette suite de médianes, ce qui varie **lentement** — le vrai gradient de
fond, qu'il ne faut surtout pas toucher — de ce qui **saute** d'une colonne à l'autre, qui est
le motif. Un filtre médian le long de l'axe fait ce partage : la tendance suit le gradient, et
l'écart à la tendance est le motif.

Sur un champ de test portant un motif de 0,03 et un gradient réel, la correction laisse un
résidu de 0,0002 sur les colonnes fautives — et la pente du gradient est inchangée à 2 % près.

## Le mode CFA, et pourquoi LPS passe avant le debayer

Sur une image **non débayerisée**, une colonne sur deux voit un filtre différent. Leurs médianes
n'ont aucune raison d'être égales, et corriger cet écart reviendrait à **effacer la mosaïque**,
c'est-à-dire l'information couleur. Le mode `cfa` traite les quatre sous-plans séparément.

C'est aussi pourquoi l'étape se place **avant** le debayer : après, l'interpolation a mélangé le
motif entre couleurs et il n'est plus séparable. Dans le pipeline, le drapeau `cfa` est posé
automatiquement selon qu'un debayer suit ou non.

## Les deux modes

- **`auto`** (défaut) : chaque colonne est ramenée sur la tendance de ses voisines. Rien à
  mesurer d'avance, rien à transmettre d'une pose à l'autre. Un faux positif ne coûte rien —
  on décale alors une colonne saine d'une valeur inférieure au bruit.
- **`defect_list`** : seules les colonnes listées dans un JSON produit par
  [LinearDefectDetection](retina-doc://LinearDefectDetection) sont corrigées, et **rien
  d'autre**. C'est le mode conservateur, et celui qui a du sens dans un pipeline : le motif est
  une propriété du **capteur**, mesurée une fois.

## Ce qu'il n'y a pas, et pourquoi

Il n'y a **pas** de rejet des écarts extrêmes. Un premier essai en comportait un, pour se
prémunir d'une trace de satellite alignée sur une colonne. Il écartait en fait exactement les
défauts à corriger — qui sont, par construction, les plus grands écarts de la distribution — et
le process ne faisait plus rien. La protection contre une structure alignée est ailleurs : dans
la **médiane** de la colonne, qu'une trace traversant quelques pixels ne déplace pas.

## Paramètres

- **`columns`** / **`rows`** — *bool*, défauts `True` / `False`. Quel axe corriger. Le banding
  CMOS est presque toujours en colonnes ; les lignes trahissent plutôt une alimentation.
- **`mode`** — *enum* `auto` | `defect_list`, défaut `auto`.
- **`defects_path`** — *path*. Le JSON de `LinearDefectDetection` (mode `defect_list`).
- **`cfa`** — *bool*, défaut `False`. Image CFA non débayerisée.

## Astuces & pièges

> **Ne l'appliquez pas après le debayer.** Le motif y est mélangé entre couleurs et la
> correction laisserait des franges colorées.

- Vérifiez d'abord qu'il y a un motif : `LinearDefectDetection` sur une pose calibrée le dit en
  une seconde. Corriger un motif inexistant ne casse rien mais n'apporte rien.
- Sur une image très structurée (grande nébuleuse couvrant tout le champ), la médiane de colonne
  n'est plus le fond de ciel. Le résultat reste borné, mais l'hypothèse ne tient plus.

## Voir aussi

- [LinearDefectDetection](retina-doc://LinearDefectDetection) — trouver les colonnes fautives.
- [CosmeticCorrection](retina-doc://CosmeticCorrection) — pixels chauds et froids, isolés.
- [Overscan](retina-doc://Overscan) — l'autre correction qui se fait tout en amont.

## Références

- PixInsight — scripts *LinearDefectDetection* / *LinearPatternSubtraction*, étape LPS de WBPP.
