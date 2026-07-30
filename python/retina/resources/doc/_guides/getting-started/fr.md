---
id: _guides/getting-started
title: Premiers pas
brief: Visite guidée de Retina — ouvrir une image, l'étirer, lire l'écho Python, puis pré-traiter un dossier de brutes entier.
order: 10
icon: list-check
keywords: [démarrage, visite, console, écho, étirement, pré-traitement, jeu d'exemple]
related: [HistogramTransformation, BackgroundExtraction, Integration, SubframeSelector, PixelMath]
---

## Ce qu'est Retina, en un paragraphe

Retina est un logiciel de traitement d'images astrophotographiques dont le **cœur est en
Python**. La fenêtre que vous avez sous les yeux n'est pas l'application : elle en est un
*client*. La console en est un autre. Les deux appellent exactement les mêmes fonctions, et
c'est pourquoi rien ici n'est réservé à l'interface : chaque entrée de menu, chaque bouton,
chaque icône de process déplacée peut aussi bien être tapée. Ce guide en fait le tour en un
quart d'heure.

Si vous préférez avoir des données sous la main avant de lire la suite, l'onglet **Accueil**
propose un jeu d'exemple libre (une vraie nuit au Palomar : bias, darks, flats et poses
d'objet, 162 Mo). Depuis la console, c'est une ligne :

```python
app.download_sample("example-cryo-lfc")
```

## 1. Ouvrir sa première image

**Fichier → Ouvrir**, ou le bouton *Votre première image…* de l'onglet Accueil. Les fichiers
FITS, XISF, TIFF, PNG, JPEG et les RAW d'appareil photo s'ouvrent tous.

Regardez la console pendant que vous le faites. Elle écrit :

```python
app.open('/data/M31/light_001.fits')
```

Ce n'est pas une ligne de journal : c'est l'appel qui vient d'être exécuté. Recopiez-le dans
un script, et il fera la même chose demain, sans coque, sans cette fenêtre.

L'image arrive **linéaire** : presque noire, avec quelques étoiles. C'est normal. Un capteur
enregistre un signal étalé sur quatre ordres de grandeur, votre écran en montre deux. Le
fichier n'a rien d'anormal — il n'a simplement pas encore été étiré.

## 2. La rendre visible — deux gestes très différents

Il y a deux façons d'éclaircir une image, et les confondre est l'erreur classique du début.

**La fonction de transfert d'écran (STF)** ne change que l'**affichage**. Les pixels ne sont
pas touchés, rien n'entre dans l'historique, et tout process que vous lancerez verra encore
les données linéaires — ce dont ont besoin l'extraction de fond, la calibration et la
détection d'étoiles. Cliquez le bouton d'auto-étirement de la barre du viewport, ou :

```python
app.compute_auto_stf()
```

**Un process d'étirement**, lui, réécrit les pixels. C'est une étape réelle et annulable de
l'historique de la vue, et c'est ce qu'on fait une fois le travail linéaire terminé :

```python
retina.HistogramTransformation(shadows=0.002, midtones=0.15).execute_on(app.active_view)
app.undo()          # …et retour en arrière, si l'on n'est pas d'accord
```

Règle valable pour toute la session : **rester linéaire aussi longtemps que possible**.
Calibrer, retirer le gradient, intégrer — puis étirer. Voir
`retina-doc://HistogramTransformation` pour la fonction de transfert elle-même, et
`retina-doc://GeneralizedHyperbolicStretch` pour l'alternative moderne.

## 3. La console, et pourquoi chaque clic y écrit

Ouvrez la console (**Vue → Console**, ou le panneau du même nom). C'est un vrai IPython qui
tourne *dans* l'application, avec deux noms déjà liés :

- `app` — l'application : fenêtres, vues, sélection active, historique, disposition,
  préférences ;
- `retina` — le paquet : toutes les classes de process, la couche d'entrées/sorties, le
  pré-traitement.

Essayez sur l'image que vous venez d'ouvrir :

```python
view = app.active_view
view.image.median(), view.image.mad()     # statistiques robustes
app.apply(retina.GaussianConvolution(sigma=2.0))
app.undo()
```

Faites maintenant quelque chose à la souris — bougez un curseur dans un panneau de process,
créez une preview, changez le zoom. Chaque geste écrit son équivalent Python. C'est la façon
la plus rapide d'apprendre l'API : on ne la lit pas, on la *regarde* s'écrire. C'est aussi
d'où viennent les recettes — reprenez les lignes qui ont marché, enregistrez-les en script,
rejouez-les sur la cible suivante.

La complétion par tabulation, `?` pour l'aide et `??` pour le code source fonctionnent : c'est
réellement IPython.

## 4. Pré-traiter un dossier de brutes

C'est la partie qui prend une soirée ailleurs. Désignez à Retina le dossier de votre session —
lights, darks, flats, bias, dans l'arrangement de sous-dossiers qu'a produit votre logiciel
d'acquisition — et il se débrouille du reste.

Depuis l'interface : le panneau **Pré-traitement** (*Commencer → Pré-traiter un dossier de
brutes…* sur l'onglet Accueil). Depuis la console, les trois mêmes étapes, qui sont aussi ce
que le panneau appelle :

```python
inventaire = retina.pipeline.scan("/data/M31")
print(inventaire.counts())                # ce qui a été trouvé, et comment c'est classé

plan = retina.pipeline.plan(inventaire, preset="auto")
print(plan.describe())                    # ce qui va tourner — à inspecter AVANT de lancer

rapport = retina.pipeline.run(plan)
print(rapport.describe())
```

Trois choses à savoir avant de lancer :

- **Le plan s'inspecte et se modifie.** `plan.describe()` imprime chaque étape dans l'ordre.
  Rien n'est décidé à l'exécution qui ne soit lisible avant — un plan rejoué donne le même
  résultat.
- **Tout est écrit sur disque**, sous `<dossier>/retina_pipeline/` (`masters/`, `calibrated/`,
  `registered/`, `integrated/`). Cent poses de 50 Mpx ne tiennent pas en mémoire, une
  exécution interrompue reprend gratuitement, et chaque intermédiaire s'ouvre ici.
- **Les poses sont mesurées, puis jugées.** `SubframeSelector` ajuste une PSF elliptique sur
  les étoiles de chaque light pour en tirer FWHM, excentricité et poids de signal. Écarter six
  poses sur cent ne relance que l'intégration — les mesures sont cachées par fichier.

Deux verbes qui se ressemblent et n'ont rien à voir : `retina.pipeline.exclude(...)` sort un
fichier du projet tout entier (mauvaise cible, corrompu, mauvais type), tandis que
`retina.pipeline.set_rejects(...)` continue de calibrer et de recaler la pose mais lui donne
un poids nul dans l'empilement. Le premier invalide le cache de calibration, le second non.

## 5. Où aller ensuite

- **Le catalogue de process** — la page d'accueil de la documentation liste les 136 process
  par catégorie. Chaque page dit ce que fait le process, ses paramètres et leurs valeurs par
  défaut.
- **L'ordre naturel d'une session** : `retina-doc://ImageCalibration` →
  `retina-doc://StarAlignment` → `retina-doc://Integration` →
  `retina-doc://BackgroundExtraction` → `retina-doc://PhotometricColorCalibration` → étirement
  → `retina-doc://NoiseReduction`.
- **`retina-doc://PixelMath`** si vous aimez faire de l'arithmétique sur vos images :
  l'expression est du Python évalué sur des tableaux numpy, donc toute la pile scientifique y
  est disponible.
- **Les scripts** — l'éditeur de scripts exécute un fichier contre la session vivante, et
  `retina-doc://Script` fait de cette exécution une unique étape d'historique annulable.
- **`python -m retina.run recette.py`** exécute le même script sans aucune fenêtre, sur une
  machine sans affichage. C'est le vrai test de la promesse : ce qui marche en console marche
  en headless.
