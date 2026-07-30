---
id: ImageIdentifier
category: Image
title: Identifiant d'image
brief: Renomme la vue/fenêtre cible en changeant son identifiant (id) de manière scriptable.
keywords: [identifiant, renommer, id, fenêtre, vue, métadonnée, console]
related: [FITSHeader, NewImage, SampleFormatConversion]
icon: id
references:
  - "PixInsight — ImageIdentifier process reference."
  - "PJSR — ImageWindow.mainView.id / View.id."
---

## Résumé

`ImageIdentifier` est un process utilitaire qui **renomme** une vue : il remplace son
identifiant (`view.id`) — et, si la vue est la vue principale d'une fenêtre, l'identifiant de
la fenêtre elle-même (`window.id`) — par la valeur fournie. C'est l'équivalent scriptable du
double-clic sur le nom d'une fenêtre dans PixInsight : aucune donnée pixel n'est touchée, seule
l'étiquette qui sert à désigner la vue dans la console, les recettes et les autres process
(`PixelMath`, `LRGBCombination`, `ChannelCombination`…) change.

## Cas d'usage

- **Nommer explicitement** le résultat d'une opération globale (`Integration`, `NewImage`…) qui
  reçoit par défaut un identifiant générique du type `Image01`.
- **Préparer des identifiants stables** avant un `PixelMath` ou une combinaison de canaux qui
  référencent les vues par leur `id` (ex. `L`, `R`, `G`, `B`, `Ha`, `OIII`).
- **Renommer par lot** dans une recette : parcourir une liste de fenêtres et leur attribuer un
  identifiant dérivé du nom de fichier ou du filtre, de façon reproductible.
- **Clarifier un pipeline** en console : donner des noms lisibles (`master_dark`, `light_stacked`)
  plutôt que de garder les identifiants auto-générés.

## Fonctionnement

Le process est un simple renommage, exécuté via `execute_on(view)` :

1. Si le paramètre `new_id` est non vide, `view.id` est remplacé par sa valeur.
2. Si la vue est rattachée à une fenêtre (`view.window is not None`), l'identifiant de la
   fenêtre (`window.id`) est aligné sur le même nom, pour rester cohérent avec la vue principale.
3. Si `new_id` est vide, l'opération est un no-op : l'identifiant courant est conservé.

Contrairement aux process qui transforment les pixels, `ImageIdentifier` ne pousse **aucune
entrée d'historique image** (`begin_process()/end_process()` n'encadrent pas une modification de
données) : c'est un changement de métadonnée pure, et il n'est pas masquable (`is_maskable =
False`) puisqu'il n'y a rien à masquer. Appliqué sans vue (`execute_on_image`), il ne fait rien —
il n'existe pas d'identifiant à changer sur une `Image` nue, détachée de toute fenêtre.

## Mathématiques

Ce process n'a pas de fondement mathématique : il ne lit ni ne modifie les échantillons de
pixels, il se contente de réécrire une chaîne de caractères servant de clé d'adressage pour la
vue et sa fenêtre. Il n'y a donc ni transformée, ni statistique, ni noyau à documenter ici.

## Paramètres

- **`new_id`** — *str*, défaut `""`. Nouvel identifiant à attribuer à la vue (et à la fenêtre
  associée le cas échéant). Une chaîne vide laisse l'identifiant inchangé (no-op) plutôt que
  de vider le nom.

## Astuces & pièges

> **Attention** — Retina ne garantit pas l'unicité des identifiants : renommer deux fenêtres
> avec le même `new_id` ne provoque pas d'erreur, mais rend les références ultérieures par `id`
> ambiguës (dans la console, dans `PixelMath`, dans une recette rejouée plus tard). Vérifiez
> `app.windows` pour vous assurer qu'un nom n'est pas déjà pris.

- Un identifiant vide n'efface pas le nom : c'est délibérément un no-op pour éviter de perdre
  la trace d'une fenêtre par erreur de script.
- Comme le changement n'ouvre pas d'entrée d'historique image, `undo()`/`redo()` sur la vue ne
  reviennent pas sur un renommage : gérez le nommage en amont plutôt que de compter dessus pour
  « annuler » un mauvais choix d'`id`.
- En console, l'écho Python de cette action (`ImageIdentifier(new_id=...).execute_on(view)`) est
  la façon la plus simple d'automatiser un renommage cohérent sur toute une recette de traitement.

## Voir aussi

- [FITSHeader](retina-doc://FITSHeader) — écrit un mot-clé FITS sur la fenêtre cible, autre
  process de métadonnée sans impact sur les pixels.
- [NewImage](retina-doc://NewImage) — crée une fenêtre vierge ou remplie, à laquelle on assigne
  souvent un identifiant explicite juste après via `ImageIdentifier`.
- [SampleFormatConversion](retina-doc://SampleFormatConversion) — autre utilitaire technique du
  module `Image`, à la différence près qu'il agit sur les échantillons plutôt que la métadonnée.

## Références

- PixInsight — *ImageIdentifier* process reference.
- PJSR — *ImageWindow.mainView.id* / *View.id*.
