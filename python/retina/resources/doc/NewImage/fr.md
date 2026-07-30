---
id: NewImage
category: Image
title: Nouvelle image
brief: Crée une nouvelle fenêtre image vierge ou remplie d'une valeur uniforme.
keywords: [nouvelle image, création, canevas, vierge, remplissage, test, synthétique]
related: [SimplexNoise, NoiseGenerator, ImageIdentifier, ChannelCombination]
icon: photo
references:
  - "PixInsight — NewImage process reference."
  - "numpy.full — création d'un tableau rempli d'une valeur constante."
---

## Résumé

`NewImage` crée une **fenêtre image vide** (ou remplie d'une valeur uniforme), sans lire aucun
fichier. C'est le process le plus simple du catalogue — l'équivalent d'un « nouveau document » —
mais il joue un rôle utilitaire important : produire un canevas de dimensions et de nombre de
canaux choisis, prêt à être peuplé par `PixelMath`, `SimplexNoise`, `NoiseGenerator`, ou toute
autre opération qui écrit des pixels de toutes pièces plutôt que d'en charger.

C'est un **process global** : il ne s'applique pas à une vue existante mais crée directement une
nouvelle fenêtre dans l'application, exactement comme `app.new_window(...)` en console.

## Cas d'usage

- **Créer un fond de travail** pour composer une image synthétique (mires de test, dégradés,
  masques dessinés à la main via `PixelMath`).
- **Générer un canevas de bruit** en préparation d'un `NoiseGenerator` ou `SimplexNoise`.
- **Fabriquer une image de référence** (plage uniforme) pour valider un pipeline ou déboguer un
  process (vérifier qu'une transformation laisse une plage constante inchangée).
- **Initialiser un masque manuel** rempli à une valeur donnée, à retoucher ensuite pixel par pixel.

## Fonctionnement

Le process alloue un tableau numpy `float32` de forme `(height, width, channels)`, entièrement
rempli de la valeur `fill`, puis l'enveloppe dans un objet `Image` et l'enregistre comme nouvelle
fenêtre applicative via `app.new_window(...)`, avec l'identifiant `new_image_id`. Aucune lecture
disque, aucune dépendance à une vue active : l'opération est purement génératrice.

## Mathématiques

Il n'y a pas de transformée ni de statistique impliquée : l'image produite est une **fonction
constante** sur le plan image. Pour tout pixel de coordonnées $(x, y)$ et tout canal $c$ :

$$ I(x, y, c) = f, \qquad 0 \le x < W,\; 0 \le y < H,\; 0 \le c < C, $$

où $f$ = `fill`, $W$ = `width`, $H$ = `height` et $C$ = `channels`. Le tableau résultant a
$W \times H \times C$ échantillons identiques, stockés en simple précision (`float32`), l'espace
d'échange numérique standard du cœur Retina.

## Paramètres

- **`width`** — *int*, défaut `256`, plage `1`–`100000`. Largeur de l'image créée, en pixels.
- **`height`** — *int*, défaut `256`, plage `1`–`100000`. Hauteur de l'image créée, en pixels.
- **`channels`** — *int*, défaut `1`, plage `1`–`4`. Nombre de canaux (1 = niveaux de gris,
  3 = RGB, 4 = RGB + alpha selon l'usage qui en est fait en aval).
- **`fill`** — *real*, défaut `0.0`, plage `0.0`–`1.0`. Valeur uniforme de remplissage appliquée
  à tous les pixels et tous les canaux.
- **`new_image_id`** — *str*, défaut `'new_image'`. Identifiant de la fenêtre créée ; s'il est
  vide, un identifiant est attribué automatiquement par l'application.

## Astuces & pièges

> **Attention** — `width` et `height` acceptent jusqu'à 100 000 pixels par côté ; une taille
> excessive combinée à `channels = 4` peut allouer plusieurs dizaines de gigaoctets de RAM. Restez
> raisonnable pour un simple canevas de test.

- Pour un canevas noir de départ, laissez `fill` à `0.0` (défaut) ; pour un canevas
  blanc/saturé, utilisez `1.0`.
- Le résultat est toujours en simple précision flottante `[0, 1]` — pas d'espace colorimétrique
  particulier tant qu'aucun profil ICC n'est assigné (voir `AssignICCProfile`).
- Si `new_image_id` correspond à un identifiant déjà utilisé, la fenêtre existante n'est pas
  écrasée : une nouvelle fenêtre distincte est créée avec ce même id logique.

## Voir aussi

- [SimplexNoise](retina-doc://SimplexNoise) — générateur de bruit cohérent, utile après `NewImage`.
- [NoiseGenerator](retina-doc://NoiseGenerator) — bruit gaussien/poisson pour tests ou simulation.
- [ImageIdentifier](retina-doc://ImageIdentifier) — renommer une fenêtre après coup.
- [ChannelCombination](retina-doc://ChannelCombination) — assembler des canaux, y compris issus de `NewImage`.

## Références

- PixInsight — *NewImage* process reference.
- numpy — *numpy.full*, création d'un tableau rempli d'une valeur constante.
