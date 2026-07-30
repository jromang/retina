---
id: Statistics
category: Image
title: Statistiques
brief: Lit des estimateurs robustes (moyenne, médiane, mad_std, biweight) par canal, sans modifier l'image.
keywords: [statistiques, médiane, mad_std, biweight, estimateur robuste, inspection, bruit]
related: [SubframeSelector, LinearFit, Integration, HistogramTransformation]
icon: chart-dots
references:
  - "astropy.stats — mad_std, biweight_location."
  - "PixInsight — Statistics process reference."
---

## Résumé

`Statistics` calcule un jeu d'**estimateurs robustes** (moyenne, médiane, écart-type robuste
`mad_std`, position biweight, minimum, maximum) pour chaque canal de l'image active, et les
range dans `self.result`. C'est un process de **lecture pure** : il n'écrit aucun pixel, ne
pousse aucune entrée d'historique, et sert d'outil d'inspection — l'équivalent du panneau
*Statistics* de PixInsight, appuyé ici sur `astropy.stats` plutôt que sur une implémentation
maison.

## Cas d'usage

- **Diagnostiquer le niveau de fond de ciel** avant `BackgroundExtraction` ou
  `BackgroundNeutralization` (médiane par canal).
- **Estimer le bruit** d'une image ou d'une pose individuelle (`mad_std`) pour comparer des
  frames avant intégration, ou calibrer des seuils de rejet (`Integration`).
- **Vérifier un étirement** (`HistogramTransformation`, `AutoHistogram`) : la médiane doit se
  situer dans une plage cible après stretch, sans écrêtage visible en min/max.
- **Scripter des contrôles qualité** : la console peut lire `Statistics().execute_on(view).result`
  et enchaîner une décision (rejet de frame, alerte de saturation) sans jamais passer par la GUI.

## Fonctionnement

Le process lit les données de l'image (`image.data`, tableau `(H, W, C)`), puis, **canal par
canal**, calcule six quantités avec `numpy` et `astropy.stats` :

1. `mean` et `median` — centre classique et centre robuste (`numpy.mean` / `numpy.median`).
2. `mad_std` — écart-type robuste dérivé de l'écart absolu médian (`astropy.stats.mad_std`).
3. `biweight` — estimateur de position bipoids de Tukey (`astropy.stats.biweight_location`),
   qui pondère les échantillons en fonction de leur distance au centre et ignore les valeurs
   extrêmes de façon plus souple qu'un simple écrêtage.
4. `min` / `max` — bornes brutes du canal (utiles pour repérer saturation ou valeurs négatives).

Le résultat est un dictionnaire `{"channels": {0: {...}, 1: {...}, ...}}` stocké dans
`self.result` ; rien d'autre n'est modifié. `execute_on(view)` ne délimite pas de
`begin_process()/end_process()` — conformément au commentaire du code, une lecture ne crée pas
d'entrée d'historique. `execute_on_image(image)` fait l'équivalent en mode headless pur, sans
`View`, et renvoie l'image inchangée (utile en pipeline `app.run`).

## Mathématiques

Pour un canal $\{x_i\}_{i=1}^{N}$, le process rapporte le centre classique et le centre robuste :

$$ \bar{x} = \frac{1}{N}\sum_{i=1}^{N} x_i, \qquad \tilde{x} = \operatorname{med}(x_i). $$

L'écart-type robuste `mad_std` s'appuie sur l'écart absolu médian (MAD), mis à l'échelle par le
facteur $1.4826$ qui le rend cohérent avec l'écart-type d'une loi normale :

$$ s = \operatorname{mad\_std}(x_i) = 1.4826 \cdot \operatorname{med}\!\big(|x_i - \tilde{x}|\big). $$

L'estimateur biweight de Tukey affine encore la position centrale en atténuant progressivement
le poids des points éloignés. Avec $u_i = (x_i - \tilde{x}) / (c\,s)$ ($c = 6$ par défaut dans
`astropy`) et en ne retenant que les $i$ tels que $|u_i| < 1$ :

$$ \operatorname{biweight}(x_i) = \tilde{x} +
   \frac{\sum_i (x_i - \tilde{x})\,(1 - u_i^2)^2}{\sum_i (1 - u_i^2)^2}. $$

Contrairement à la moyenne, `mad_std` et `biweight` restent stables en présence d'étoiles
saturées, de pixels chauds ou de traînées de satellite : une poignée d'échantillons extrêmes ne
fait pas dériver ces estimateurs, contrairement à la moyenne ou à l'écart-type classiques.

## Paramètres

Ce process n'a **aucun paramètre**. Il agit uniquement sur l'image de la vue ciblée et calcule
toujours le même jeu d'estimateurs, canal par canal.

## Astuces & pièges

> **Note** — les statistiques sont calculées sur les **valeurs brutes** de l'image, en linéaire
> ou étirées selon l'état courant de la vue. Comparer des médianes entre une image linéaire et
> une image étirée n'a pas de sens : relancez `Statistics` après chaque étirement significatif.

- `mad_std` est un bien meilleur indicateur de bruit que l'écart-type classique dès qu'il y a des
  étoiles ou des artefacts dans le champ — c'est le même estimateur qu'utilise `Integration` pour
  son rejet sigma.
- Un `max` proche de 1.0 (image normalisée) sur plusieurs canaux signale une saturation à
  surveiller avant intégration ou calibration colorimétrique.
- Pour une inspection région par région plutôt que sur l'image entière, exécutez `Statistics` sur
  une `Preview` : l'API est strictement identique (une `Preview` **est** une `View`).

## Voir aussi

- [SubframeSelector](retina-doc://SubframeSelector) — métriques qualité par frame (bruit, FWHM, excentricité).
- [LinearFit](retina-doc://LinearFit) — ajustement d'échelle entre images à partir de statistiques robustes.
- [Integration](retina-doc://Integration) — utilise médiane et mad_std pour le rejet sigma.
- [HistogramTransformation](retina-doc://HistogramTransformation) — étirement à contrôler via ces statistiques.

## Références

- astropy.stats — *mad_std*, *biweight_location*.
- PixInsight — *Statistics* process reference.
