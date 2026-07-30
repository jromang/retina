---
id: FITSHeader
category: Image
title: En-tête FITS
brief: Ajoute, modifie ou commente un mot-clé FITS dans les métadonnées de la fenêtre cible.
keywords: [FITS, en-tête, mot-clé, métadonnées, keyword, header]
related: [ImageIdentifier, NewImage, SampleFormatConversion]
icon: file-info
references:
  - "PixInsight — FITSHeader tool reference."
  - "Pence, W. et al. — Definition of the Flexible Image Transport System (FITS), version 3.0."
  - "astropy.io.fits — Header cards and keyword conventions."
---

## Résumé

`FITSHeader` écrit un mot-clé (**keyword**), sa valeur et un commentaire optionnel dans le
dictionnaire `window.keywords` de la fenêtre cible — les métadonnées FITS associées à l'image,
distinctes des pixels. C'est un process **utilitaire technique** au sens PixInsight (catégorie
`Image`, aux côtés de `NewImage`, `ImageIdentifier`, `SampleFormatConversion`) : il n'effectue
aucune opération numérique sur l'image, il annote ou corrige l'en-tête qui sera réécrit sur
disque par `save_fits`. Contrairement aux mots-clés chargés depuis un FITS existant (typés
automatiquement par astropy — entier, flottant, booléen…), toute valeur écrite par ce process
reste une **chaîne de caractères**.

## Cas d'usage

- Ajouter un mot-clé absent après un traitement (p. ex. `OBJECT`, `TELESCOP`, `FILTER`) quand la
  source ne le fournissait pas.
- Corriger un mot-clé erroné avant intégration (p. ex. un `EXPTIME` mal renseigné par
  l'acquisition).
- Documenter dans l'en-tête le traitement appliqué, via un mot-clé personnalisé, pour tracer une
  recette dans le fichier de sortie.
- Injecter des mots-clés synthétiques exploités en aval par d'autres process ou scripts (p. ex.
  un identifiant de session ou de filtre relu par un tri automatique).

## Fonctionnement

Le process ne touche jamais aux pixels : `execute_on_image` est un no-op qui retourne l'`Image`
inchangée, car les mots-clés vivent sur `ImageWindow`, pas sur `Image`. L'opération réelle a
lieu dans `execute_on(view)` :

1. Si `keyword` est vide, ou si la vue n'a pas de fenêtre associée (`view.window is None`), rien
   n'est écrit ; le process retourne néanmoins succès (`True`), silencieusement.
2. Sinon, `view.window.keywords[keyword]` est fixé à `value` seul, ou au tuple `(value,
   comment)` si `comment` est non vide — la convention utilisée par `astropy.io.fits.Header`
   pour porter un commentaire de carte FITS.
3. `window` étant partagé par la vue principale et toutes ses previews, l'écriture s'applique à
   **l'en-tête entier de l'image**, jamais à une seule preview.

L'écriture reste en mémoire dans `window.keywords` jusqu'à un `save_fits(path, image,
window.keywords)`, qui recopie chaque entrée dans le `Header` astropy avant écriture sur disque.

## Mathématiques

Process purement métadonnées : aucune transformation numérique des pixels n'est impliquée,
donc aucune formule ne s'applique ici.

## Paramètres

- **`keyword`** — *str*, défaut `""`. Nom du mot-clé FITS (p. ex. `OBJECT`, `FILTER`). Norme
  FITS : 8 caractères max, majuscules ; au-delà, `astropy` requiert la convention `HIERARCH`.
  Une valeur vide désactive le process (no-op).
- **`value`** — *str*, défaut `""`. Valeur associée au mot-clé, toujours enregistrée comme
  chaîne de caractères — même si elle représente un nombre.
- **`comment`** — *str*, défaut `""`. Commentaire optionnel de la carte FITS. Laissé vide, seule
  la valeur est stockée (pas de tuple).

## Astuces & pièges

> **Attention** — `value` est toujours stocké comme chaîne de caractères. Un mot-clé numérique
> existant chargé depuis un FITS (ex. `EXPTIME` en `float`) redeviendra une carte **string**
> après passage par `FITSHeader`, ce qui peut perturber des outils avals attendant un type
> numérique.

> **Note** — respectez la norme FITS pour `keyword` : majuscules, 8 caractères maximum. Un nom
> plus long ou en minuscules peut être rejeté ou mal interprété par `astropy` lors de l'écriture.

- Le process modifie `window.keywords` immédiatement, mais rien n'est écrit sur disque tant
  qu'un `save_fits` n'est pas exécuté.
- Appliqué depuis une preview, l'écriture affecte l'en-tête de la fenêtre entière (les previews
  n'ont pas de métadonnées FITS propres).
- Pour lire une valeur plutôt que l'écrire, consultez directement `view.window.keywords[...]`
  en console — il n'existe pas de process de lecture dédié.

## Voir aussi

- [ImageIdentifier](retina-doc://ImageIdentifier) — renomme l'identifiant interne de la fenêtre.
- [NewImage](retina-doc://NewImage) — crée une fenêtre vierge à annoter.
- [SampleFormatConversion](retina-doc://SampleFormatConversion) — autre utilitaire technique du
  même module.

## Références

- PixInsight — *FITSHeader* tool reference.
- Pence, W. et al. — *Definition of the Flexible Image Transport System (FITS)*, version 3.0.
- astropy.io.fits — *Header* cards and keyword conventions.
