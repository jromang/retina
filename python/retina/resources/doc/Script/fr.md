---
id: Script
category: Scripting
title: Script
brief: Une exécution de script Python, mémorisée comme instance de process — annulable, rangeable en bibliothèque et rejouable dans une recette.
keywords: [script, python, paramètres, reproductibilité, historique, recette, rejeu, empreinte]
related: [PixelMath, HistogramTransformation]
icon: file-code
references:
  - "PixInsight — Script process et objet PJSR Parameters."
  - "CLAUDE.md — piliers n°1 (Python-first) et n°4 (reproductibilité)."
---

## Résumé

`Script` est l'instance de process que laisse derrière elle l'exécution d'un script Python
ayant **exporté des paramètres**. Elle ne transforme aucun pixel : c'est un *marqueur
rejouable*, qui entre dans l'historique de la vue, s'annule, se range en icône de bibliothèque
et prend place dans une recette, exactement comme n'importe quel autre process.

On ne la construit pas à la main. Elle naît d'un `app.run_recipe(chemin)` dont le script a
appelé `retina.parameters.set(...)` au moins une fois.

## Cas d'usage

- **Rendre un traitement maison reproductible** : un script qui débruite selon trois réglages
  peut les exporter, et son exécution devient un objet qu'on rejoue sur une autre pose avec
  d'autres valeurs.
- **Mêler script et process dans une recette** : une étape `Script` s'insère dans un
  `ProcessContainer` entre deux process du catalogue.
- **Annuler un script** : l'entrée d'historique permet de revenir à l'état d'avant, sans avoir
  à savoir ce que le script a fait.
- **Conserver un réglage** : glisser l'instance en bibliothèque met de côté le couple
  « ce script, avec ces valeurs ».

## Fonctionnement

Un script déclare ses réglages par l'objet `retina.parameters`, équivalent de l'objet
`Parameters` de PJSR :

```python
p = retina.parameters
seuil = p.get_real('seuil', 0.5)   # relit la valeur d'un rejeu, ou son défaut
p.set('seuil', seuil)              # ← c'est ce geste qui rend le script rejouable

from retina import Binarize
Binarize(threshold=seuil).execute_on(app.active_view)
```

À la fin de l'exécution, si — et seulement si — au moins un paramètre a été exporté, une
instance `Script` est poussée dans l'historique de la vue cible. Rejouer l'instance réexécute
le fichier avec les valeurs mémorisées : le script relit alors ses propres réglages par
`get_real`, `get_int`, `get_bool` ou `get_str`.

Un script peut aussi interroger sa cible : `parameters.is_view_target`,
`parameters.target_view`, `parameters.is_global_target`.

## La règle qui évite le doublon

Un script qui se contente d'enchaîner des `app.apply(...)` **ne laisse pas** d'instance
`Script`. C'est délibéré, et c'est la règle de PixInsight : ce script a déjà produit un
historique étape par étape, entièrement annulable et rejouable ; y ajouter une entrée qui le
décrirait une seconde fois n'apporterait rien et rendrait l'annulation ambiguë.

Exporter un paramètre est donc la façon dont un script déclare : « mon unité de travail, c'est
moi, pas mes étapes ».

## Paramètres

- **Fichier** (`path`) — le script exécuté. C'est lui qui fait le travail ; l'instance n'en est
  que la trace. Le code n'est **pas** recopié dans l'instance : un script est un document qui
  vit sa vie, et le figer donnerait une copie qui divergerait en silence.
- **Paramètres** (`values`) — JSON des valeurs exportées. Les modifier puis rejouer, c'est
  relancer le script avec d'autres réglages.
- **Empreinte** (`digest`) — SHA-256 du fichier au moment de l'enregistrement.

## Astuces & pièges

> **Attention** — si le fichier a changé depuis l'enregistrement, le rejeu le **signale** dans
> la console mais s'exécute quand même : le script a très bien pu être corrigé volontairement.
> Se taire, en revanche, ferait exécuter autre chose que ce qui avait été enregistré.

- L'exécution récursive est refusée : une instance `Script` ne peut pas être rejouée depuis un
  script déjà en cours. Sans cette limite, un script qui se rejoue lui-même boucle sans fin.
  PixInsight pose la même.
- L'instance mémorise un **chemin**. Déplacer le fichier casse le rejeu — c'est le prix de ne
  pas embarquer le code.
- Hors exécution de script, `retina.parameters` est inerte : les écritures sont ignorées et les
  lectures rendent leur défaut. Appeler une fonction d'un script depuis la console ne lève donc
  jamais.

## Voir aussi

- [PixelMath](retina-doc://PixelMath) — l'autre porte d'entrée du Python dans le traitement,
  pour une expression plutôt qu'un fichier.
- [HistogramTransformation](retina-doc://HistogramTransformation) — un process du catalogue,
  tel qu'un script en appelle.

## Références

- PixInsight — *Script* process et objet PJSR *Parameters*.
- CLAUDE.md — piliers n°1 (Python-first) et n°4 (reproductibilité).
