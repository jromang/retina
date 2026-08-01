---
id: _guides/first-light
title: De l'empilement à l'image
brief: Que faire de l'image que le pré-traitement vient de produire — recadrage, gradient, couleur, netteté, étirement, export.
order: 20
icon: sparkles
keywords: [flux de travail, étirement, gradient, étalonnage couleur, déconvolution, export, linéaire]
related: [DynamicCrop, MultiscaleGradientCorrection, SpectrophotometricColorCalibration, GeneralizedHyperbolicStretch, StarRemoval]
---

## D'où l'on part

Vous avez lancé le pré-traitement et ouvert son résultat : un fichier sous
`retina_pipeline/integrated/`, par filtre. Cette image est **linéaire** — les pixels sont
encore proportionnels à la lumière tombée sur le capteur — et le pré-traitement n'est que la
moitié du chemin. Ce qui suit est l'autre moitié, et c'est là que l'image apparaît.

Tout ce qui suit est un process que vous pouvez aussi lancer depuis la console ; chaque clic
écrit sa ligne Python. Rien dans ce guide n'est un raccourci que l'interface aurait et qu'un
script n'aurait pas.

## L'ordre, et pourquoi c'est celui-là

On reste **linéaire** aussi longtemps que possible. Un étirement est une fonction non linéaire :
une fois appliqué, un gradient n'est plus un gradient, la couleur des étoiles n'est plus
proportionnelle au flux, et le bruit n'est plus uniforme — donc les outils qui supposent la
linéarité passent d'abord. C'est l'ordre sur lequel convergent tous les workflows publiés, quel
que soit le logiciel :

1. **Recadrer** les bords de recalage — `DynamicCrop`
2. **Retirer le gradient** — `MultiscaleGradientCorrection` ou `BackgroundExtraction`
3. **Étalonner la couleur** — `PlateSolve` puis `SpectrophotometricColorCalibration`
4. **Affiner et débruiter** — `Deconvolution`, `NoiseReduction`
5. **Étirer** — `GeneralizedHyperbolicStretch` ou `HistogramTransformation`
6. **Finir** — saturation, courbes, taille des étoiles
7. **Exporter**

Les quatre premières étapes vivent dans le domaine linéaire ; à partir de la cinquième on n'y
revient plus. D'où l'idée d'étirer **tard**.

## 0. Voir ce que l'on a

Une image linéaire affichée telle quelle paraît noire : un fond de ciel moyen se situe autour
de 0,001, et votre écran a 256 niveaux. Cliquez sur **Auto** dans le panneau *Étirement
d'écran* (ou lancez `app.compute_auto_stf()`).

Cela ne change **rien** aux pixels. C'est une transformation d'affichage, et c'est tout
l'intérêt : vous regardez la nébulosité faible pendant que les outils continuent de travailler
sur les vraies valeurs. Ouvrir un résultat de pipeline depuis le rapport le fait pour vous.

> **La distinction à garder** — l'étirement d'écran est la façon dont vous *regardez* ; un
> process d'étirement est ce que vous *faites*. Gardez-les séparés jusqu'à l'étape 5.

## 1. Recadrer les bords

Le recalage superpose toutes les poses sur une référence commune : les bords d'un empilement
sont donc couverts par moins de poses que le centre, parfois par aucune. Ces bords sont plus
bruités, et ils vont empoisonner toutes les mesures qui suivent — un modèle de gradient ajusté
à travers un coin noir, une estimation de fond, un étirement automatique.

Prenez `retina-doc://DynamicCrop`, tirez le cadre sur la zone saine, appliquez. Faites-le
**en premier** : tout ce qui suit mesure l'image, et doit mesurer celle que vous gardez.

## 2. Retirer le gradient

La pollution lumineuse, la Lune et le crépuscule laissent une rampe lente en travers du champ.
Elle ne fait pas partie de l'objet, et chaque étape ultérieure se comporte mieux sans elle.

- `retina-doc://MultiscaleGradientCorrection` ajuste les grandes échelles de votre image sur
  une référence et retranche la différence. Cette référence peut venir d'un relevé : lancez
  d'abord `retina-doc://SurveyReference`, qui interroge un survey all-sky sur votre solution
  astrométrique et ouvre le résultat comme une fenêtre ordinaire — regardable avant de s'en
  servir.
- `retina-doc://BackgroundExtraction` et `retina-doc://DynamicBackgroundExtraction` modélisent
  le fond depuis l'image elle-même, automatiquement ou à partir d'échantillons que vous posez
  au clic. À préférer sur un champ où l'objet remplit le cadre, ou si aucun survey n'aide.

Jugez le résultat sur le **fond**, pas sur l'objet : une correction qui aplatit le ciel en
éteignant la galaxie a emporté du signal avec elle.

## 3. Étalonner la couleur

C'est l'étape qui fait que la couleur veut dire quelque chose, au lieu d'avoir l'air plausible.

1. `retina-doc://PlateSolve` — la solution astrométrique. L'étalonnage couleur doit savoir
   quelles étoiles il regarde.
2. `retina-doc://SpectrophotometricColorCalibration` — il mesure le flux des étoiles du
   catalogue dans chaque canal, le compare à leurs **spectres** Gaia, et en tire les gains qui
   mettent vos canaux d'accord avec la physique. Choisissez vos filtres et votre capteur dans
   les listes : 54 courbes sont livrées, et nommer les bonnes est ce qui sépare un vrai
   étalonnage d'un étalonnage vraisemblable.
3. Sous filtres à bande étroite, cochez **Mode bande étroite** et donnez plutôt la longueur
   d'onde et la largeur de chaque canal.

`retina-doc://BackgroundNeutralization` au préalable met le fond de ciel au neutre, qui est la
référence par rapport à laquelle le reste se mesure.

## 4. Affiner et débruiter — toujours en linéaire

`retina-doc://Deconvolution` défait une partie du flou imposé par l'atmosphère et l'optique.
Elle travaille sur des données linéaires et nulle part ailleurs : la fonction d'étalement
qu'elle inverse est une *convolution*, ce qu'un étirement n'est pas. Mesurez la PSF sur les
étoiles elles-mêmes (`retina-doc://DynamicPSF` partage le même ajusteur) plutôt que de deviner
une largeur de gaussienne.

`retina-doc://NoiseReduction` et `retina-doc://TGVDenoise` lissent le fond. Travaillez sous
masque pour que l'objet garde son détail — voir plus bas.

Si vous avez installé un modèle ONNX, `retina-doc://AIDeconvolution` et `retina-doc://AIDenoise`
font le même travail avec un réseau ; le nom du modèle, sa version et son empreinte SHA-256
entrent dans l'historique et dans les mots-clés FITS, si bien que le résultat reste
reproductible.

## 5. Étirer — le passage

L'image devient maintenant une photo.

- `retina-doc://GeneralizedHyperbolicStretch` est celui qu'il faut apprendre. Il donne un
  contrôle indépendant sur *combien* étirer, *où* dans la plage tonale, et à quel point
  protéger les ombres — c'est ce qui permet de lever la nébulosité sans noyer le fond. Son
  panneau dessine la courbe et l'histogramme résultant en temps réel.
- `retina-doc://HistogramTransformation` est la voie directe : trois valeurs, point noir, tons
  moyens, point blanc. Le bouton *Appliquer* du panneau d'étirement d'écran grave dans les
  pixels l'auto-stretch que vous regardez, via ce process même — une entrée d'historique,
  annulable.
- `retina-doc://MaskedStretch` et `retina-doc://ArcsinhStretch` préservent mieux la couleur des
  étoiles sur les champs brillants.

Surveillez le point noir. Écrêter le fond à zéro est irréversible, et cela emporte le halo
externe faible de l'objet.

## 6. Finir

- **Masques.** Presque toute finition en demande un : affiner l'objet sans le fond, débruiter
  le fond sans l'objet. Lancez `retina-doc://StarMask`, `retina-doc://RangeSelection` ou
  `retina-doc://ColorMask` — chacun ouvre son résultat en fenêtre, et propose de le poser comme
  masque de la vue d'où il vient. La barre d'état affiche alors le masque, permet de l'inverser
  et de changer son rendu.
- **Couleur** — `retina-doc://ColorSaturation`, `retina-doc://CurvesTransformation`, et
  `retina-doc://SCNR` pour la dominante verte que les capteurs couleur laissent sur les
  nébuleuses.
- **Étoiles** — `retina-doc://StarRemoval` sépare l'image sans étoiles ; traitez les deux
  séparément puis recombinez, ou utilisez directement `retina-doc://StarReduction` pour les
  réduire.
- **Bande étroite** — `retina-doc://NBRGBCombination` et `retina-doc://NarrowbandNormalization`
  pour les palettes SHO et HOO.

## 7. Exporter

**Fichier ▸ Enregistrer sous**. Ce qu'il faut écrire dépend de l'usage :

| Pour | Format |
|---|---|
| Archiver, rouvrir ici ou dans une autre suite astro | **XISF** — flottant, mots-clés, WCS, compressé |
| Éditer ailleurs (Photoshop, GIMP, Affinity) | **TIFF** — flottant 32 bits, sans perte |
| Partager, publier, envoyer | **PNG** ou **JPEG** |

La dernière ligne s'accompagne d'un avertissement, qu'il vaut mieux comprendre que cliquer.
PNG et JPEG stockent 8 bits par canal. Si votre image est encore linéaire — parce que vous la
regardez à travers l'étirement d'écran —, alors ce que vous voyez et ce qui est dans les pixels
sont deux choses différentes, et le fichier sortira presque noir. Retina vous demande ce que
vous vouliez dire : appliquer l'étirement d'écran à la copie exportée, ou écrire les données
inchangées. Appliquez-le, sauf si vous savez que vous voulez les données linéaires.

## Tout rejouer

Tout ce que vous venez de faire est dans l'historique de la vue, et l'historique est une
recette. Le bouton **Recette depuis l'historique** du panneau d'historique en fait un
`ProcessContainer` que vous pouvez déposer sur une autre image — l'empilement OIII, la séance
du mois prochain sur le même objet. `app.recipe()` rend la même chose en Python.

C'est la vraie raison pour laquelle chaque étape est un process sérialisable plutôt qu'un
bouton : la deuxième image coûte une fraction de la première.

## Où aller ensuite

- `retina-doc://_guides/getting-started` — si vous ne l'avez pas lu : la console, l'écho, et le
  pré-traitement d'un dossier.
- Le catalogue de process, par catégorie, sur la page d'accueil de la documentation.
- `retina-doc://PixelMath` — de l'arithmétique sur les images, en expression Python.
