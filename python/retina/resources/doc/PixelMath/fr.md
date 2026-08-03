---
id: PixelMath
category: PixelMath
title: PixelMath
brief: Évalue une expression Python (numpy) pixel à pixel sur une ou plusieurs images.
keywords: [pixelmath, expression, numpy, arithmétique, combinaison]
related: [Invert, ChannelCombination, Rescale]
icon: math-function
references:
  - "PixInsight — PixelMath tool reference."
  - "asteval — safe Python expression evaluation."
---

## Résumé

`PixelMath` évalue une **expression Python** sur les tableaux numpy des images. Fidèle au
pilier « pas de langage maison » de Retina, il n'y a **aucun DSL** : l'expression est du
Python évalué en bac à sable (asteval), avec toute la puissance de numpy disponible
(`sqrt`, `log`, `clip`, `where`, opérateurs élément par élément…). C'est l'outil universel de
combinaison, de correction et de création d'images.

![Avant — PixelMath](figures/before.webp)
![Après — PixelMath](figures/after.webp)

*Avant, et après évaluation de `img ** 0.5` — un étirement écrit en arithmétique plutôt que choisi dans un menu.*

## Cas d'usage

- **Arithmétique d'images** : `img_a - 0.9*img_b` (soustraction de gradient, différences).
- **Composition conditionnelle** : `where(img > 0.8, img, 0)` (masquage par seuil).
- **Corrections non linéaires** : `img**0.5`, `log1p(img)/log1p(1.0)`.
- **Génération** : image de bruit, rampe, motif, à partir de `x`, `y`, fonctions numpy.

## Fonctionnement

L'expression est évaluée dans un espace de noms qui contient l'image courante (`img`), les
autres vues référencées par identifiant, et les fonctions numpy usuelles. Le champ
**`symbols`** permet de définir des lignes préalables (variables intermédiaires) exécutées
avant l'expression finale. Après évaluation, deux post-traitements optionnels s'appliquent :

1. **`truncate`** borne le résultat dans `[range_low, range_high]`.
2. **`rescale`** étire ensuite linéairement la plage occupée vers `[range_low, range_high]`.

Le résultat remplace la vue courante, ou crée une nouvelle image si `create_new_image` est vrai.

## Mathématiques

Soit $E(\cdot)$ l'expression saisie et $I$ l'image d'entrée. La sortie brute est
$Y = E(I, \dots)$. Le bornage (`truncate`) donne :

$$ Y_t = \operatorname{clip}(Y,\; r_\text{low},\; r_\text{high}) $$

et la remise à l'échelle (`rescale`), si activée, applique :

$$ Y_r = r_\text{low} + (r_\text{high} - r_\text{low}) \,
        \frac{Y_t - \min(Y_t)}{\max(Y_t) - \min(Y_t)} $$

Les fonctions aléatoires (`rand`, `gauss`) sont déterministes pour une même **graine**
`seed`, garantissant la reproductibilité d'une recette.

## Paramètres

- **`expression`** — *text*, défaut `img`. Expression Python évaluée sur les tableaux.
- **`symbols`** — *text*, défaut vide. Lignes préalables (définitions de variables).
- **`rescale`** — *bool*, défaut `False`. Étire la plage occupée vers `[range_low, range_high]`.
- **`truncate`** — *bool*, défaut `True`. Borne le résultat dans `[range_low, range_high]`.
- **`range_low`** — *real*, défaut `0.0`, plage `0`–`1`. Borne basse.
- **`range_high`** — *real*, défaut `1.0`, plage `0`–`1`. Borne haute.
- **`create_new_image`** — *bool*, défaut `False`. Crée une nouvelle image au lieu de remplacer.
- **`new_image_id`** — *str*, défaut vide. Identifiant de la nouvelle image.
- **`seed`** — *int*, défaut `0`. Graine des générateurs aléatoires (reproductibilité).

## Astuces & pièges

> **Note** — l'évaluation est en bac à sable : ni entrées/sorties fichier, ni imports
> arbitraires. Restez dans numpy et les vues exposées.

- Désactivez `truncate` pour inspecter des résultats hors `[0,1]` (différences signées).
- Pour combiner plusieurs images, référencez-les par leur identifiant de vue dans l'expression.

## Voir aussi

- [Invert](retina-doc://Invert) — cas particulier `1 - img`.
- [ChannelCombination](retina-doc://ChannelCombination) — recomposer des canaux.
- [Rescale](retina-doc://Rescale) — remise à l'échelle seule.

## Références

- PixInsight — *PixelMath* tool reference.
- *asteval* — safe Python expression evaluation.
