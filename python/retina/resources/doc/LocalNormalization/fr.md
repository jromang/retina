---
id: LocalNormalization
category: Calibration
title: Normalisation locale
brief: Aligne le fond et l'échelle d'une frame sur une vue de référence avant intégration.
keywords: [normalisation, intégration, fond de ciel, gradient, échelle, empilement, rejet]
related: [Integration, StarAlignment, ImageCalibration, BackgroundExtraction]
icon: adjustments-horizontal
references:
  - "PixInsight — LocalNormalization / ImageIntegration (local normalization) tool reference."
  - "scipy.ndimage.gaussian_filter — filtrage gaussien passe-bas."
---

## Résumé

`LocalNormalization` recale une frame sur une **vue de référence** commune avant intégration :
elle égalise à la fois le **fond de ciel** (composante basse fréquence — gradients, vignetage
résiduel, variations de pollution lumineuse d'une pose à l'autre) et l'**échelle** globale du
signal (transparence, temps de pose, gain). Sans cette étape, des frames dont le fond ou le
contraste diffèrent légèrement produisent, une fois empilées, des artefacts de gradient ou un
rejet d'outliers dégradé — `Integration` compare des pixels qui ne sont plus vraiment
homogènes d'une frame à l'autre.

## Cas d'usage

- **Avant `Integration`**, sur une série de poses prises par nuits ou conditions de ciel
  différentes (transparence variable, halo lunaire changeant), pour ramener chaque frame sur
  une base commune et améliorer le rejet sigma.
- **Corriger un léger déséquilibre de fond** entre sous-poses issu d'un flat imparfait ou d'une
  pollution lumineuse variable, sans repasser par un `BackgroundExtraction` complet par frame.
- **Uniformiser une mosaïque** ou un jeu de poses multi-sessions avant de les combiner, en
  choisissant comme référence la frame la plus propre du lot.

## Fonctionnement

Pour chaque canal de la frame à normaliser :

1. Le **fond basse fréquence** de la frame et celui de la référence sont estimés par un flou
   gaussien de grand rayon (`scale`), qui lisse les étoiles et le bruit pour ne garder que la
   variation lente du fond.
2. La **composante haute fréquence** (signal utile + bruit) de chaque image est obtenue en
   soustrayant son propre fond : `hp = image - fond`.
3. Un **gain multiplicatif global** est estimé par le rapport des dispersions (écart-type) des
   composantes haute fréquence de la frame et de la référence — une correction d'échelle simple
   et robuste au premier ordre, calculée au sens des moindres carrés.
4. La frame de sortie recombine la haute fréquence de la frame (mise à l'échelle par ce gain)
   avec le **fond de la référence**, ce qui aligne simultanément le niveau de fond et le
   contraste sur la référence commune.

Si aucune référence n'est renseignée, ou si elle ne peut pas être résolue (vue inexistante), le
process est un no-op : la frame est renvoyée inchangée.

> **Note** — la référence est résolue par son identifiant de vue (`reference`) via le contexte
> d'exécution du process (`context.resolve_image_full`) ; elle doit donc être une fenêtre déjà
> ouverte dans l'application au moment de l'exécution.

## Mathématiques

Soit $I$ la frame à normaliser et $R$ la référence, pour un canal donné. Le fond basse
fréquence de chacune est estimé par convolution gaussienne de paramètre $\sigma$ = `scale` :

$$ B_I = G_\sigma * I, \qquad B_R = G_\sigma * R. $$

Les composantes haute fréquence (signal + bruit, fond retiré) sont :

$$ H_I = I - B_I, \qquad H_R = R - B_R. $$

Le gain d'échelle est le rapport des écarts-types de ces composantes :

$$ g = \frac{\operatorname{std}(H_R)}{\operatorname{std}(H_I)}. $$

La frame normalisée recombine la structure haute fréquence de $I$, remise à l'échelle de $R$,
avec le fond de la référence :

$$ I'(x,y) = g \cdot H_I(x,y) + B_R(x,y), $$

puis le résultat est écrêté dans $[0,1]$. Ce modèle additif (fond) + multiplicatif (échelle)
est une version simplifiée du modèle de normalisation locale de PixInsight, qui estime
localement un couple $(\text{échelle}, \text{fond})$ par petites zones ; ici le gain est
**global** (un seul scalaire par canal) tandis que le fond reste **local** (une carte 2D
lissée), ce qui suffit à corriger l'essentiel des dérives entre poses tout en restant rapide
et purement numpy/scipy.

## Paramètres

- **`reference`** — *str*, défaut `""`. Identifiant de la vue de référence sur laquelle aligner
  fond et échelle. Vide ou vue introuvable → la frame est renvoyée inchangée (no-op).
- **`scale`** — *real*, défaut `128.0`, plage `4`–`1024`. Écart-type $\sigma$ (en pixels) du
  flou gaussien utilisé pour estimer le fond basse fréquence. Grande valeur = fond très lisse
  (ne capture que les gradients larges) ; petite valeur = suit des variations plus fines, au
  risque d'absorber du signal étendu (nébulosités).

## Astuces & pièges

> **Attention** — un `scale` trop petit traite la nébulosité étendue comme du fond et
> l'estompe partiellement à chaque frame normalisée. Choisissez une valeur nettement plus
> grande que la taille des structures d'intérêt.

- Choisissez comme `reference` la frame la plus propre et la mieux exposée du lot (peu de
  gradient, transparence stable), pas nécessairement la première de la série.
- Appliquez `LocalNormalization` sur des frames déjà **calibrées** (`ImageCalibration`) et
  **alignées** (`StarAlignment`) : la correction de fond/échelle n'a de sens que si les pixels
  comparés couvrent la même région du ciel.
- Le gain estimé est **global par canal**, pas local : il ne corrige pas un gradient de
  contraste variable dans le champ. Pour un gradient de fond complexe, un `BackgroundExtraction`
  par frame en amont reste complémentaire.

## Voir aussi

- [Integration](retina-doc://Integration) — étape suivante : empilement avec rejet robuste.
- [StarAlignment](retina-doc://StarAlignment) — recalage géométrique préalable des frames.
- [ImageCalibration](retina-doc://ImageCalibration) — calibration bias/dark/flat en amont.
- [BackgroundExtraction](retina-doc://BackgroundExtraction) — modélisation complète du fond, par frame.

## Références

- PixInsight — *LocalNormalization* / *ImageIntegration* (local normalization) tool reference.
- scipy.ndimage — *gaussian_filter*, filtrage gaussien passe-bas.
