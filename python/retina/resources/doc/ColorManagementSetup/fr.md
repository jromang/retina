---
id: ColorManagementSetup
category: ColorManagement
title: Configuration de la gestion des couleurs
brief: Fixe les réglages globaux de gestion des couleurs (profil de travail, intention de rendu) utilisés par les autres process ICC.
keywords: [ICC, couleur, profil colorimétrique, gestion des couleurs, rendu, sRGB, littlecms]
related: [AssignICCProfile, ICCProfileTransformation, ConvertToRGBColor, RGBWorkingSpace]
icon: settings
references:
  - "PixInsight — ColorManagementSetup process reference."
  - "International Color Consortium — ICC.1:2022 specification."
  - "Pillow — PIL.ImageCms (littlecms bindings)."
---

## Résumé

`ColorManagementSetup` est un process **global** et **sans pixels** : il ne touche à aucune
image, mais fixe les **réglages par défaut** de gestion des couleurs (ICC) utilisés ensuite par
les autres outils de la catégorie `ColorManagement` — au premier chef `ICCProfileTransformation`
et, indirectement, l'export raster (TIFF/PNG/JPEG). C'est l'équivalent du dialogue de
configuration globale de PixInsight : on le lance une fois (ou à chaque changement de contexte
de travail), pas par fenêtre.

## Cas d'usage

- **Définir une fois pour toutes le profil de travail** (`working_profile`) d'une session,
  typiquement `sRGB` pour un rendu web/partage, ou un profil élargi (Adobe RGB, ProPhoto RGB)
  pour un flux d'édition haute gamme destiné à l'impression.
- **Choisir l'intention de rendu par défaut** (`rendering_intent`) appliquée par les conversions
  ICC ultérieures qui ne précisent pas explicitement la leur.
- **Désactiver temporairement la gestion des couleurs** (`enabled = False`) pour un flux purement
  scientifique où les valeurs de pixels ne doivent subir aucune réinterprétation colorimétrique.
- **Scripter un contexte reproductible** : appeler `ColorManagementSetup(...).execute_global(app)`
  en tête de recette pour garantir que tous les exports suivants partagent le même réglage.

## Fonctionnement

Retina travaille en interne en données **scene-linear** float 32 bits ; la gestion ICC n'a de
sens que pour le **rendu et l'export** 8/16 bits, où elle s'appuie sur `PIL.ImageCms`
(bindings Python de la bibliothèque **littlecms**).

`ColorManagementSetup` ne fait qu'écrire trois valeurs dans un dictionnaire de configuration
**global au module** (`_CMS_SETTINGS`), partagé par tout le processus Python en cours : le nom du
profil de travail, l'intention de rendu par défaut, et un indicateur d'activation. Il n'ouvre, ne
charge et ne modifie aucune image — c'est pourquoi `is_global = True` et qu'il n'a pas de fenêtre
de sortie (`creates_window = False`). Son unique effet de bord est de préparer le contexte que
liront ensuite les autres process ICC (via `_load_profile`, qui résout `"sRGB"` en un profil
littlecms généré à la volée, ou tout autre nom en un chemin vers un fichier `.icc`/`.icm`).

## Mathématiques

Ce process ne définit aucune transformation numérique sur les pixels — il n'a donc pas
d'expression mathématique propre. Les formules pertinentes (matrices de conversion d'espace
colorimétrique, courbes de tonalité, calculs d'intention de rendu perceptuelle / colorimétrique
relative / saturation / colorimétrique absolue au sens ICC) sont mises en œuvre par littlecms au
moment où `ICCProfileTransformation` consomme ces réglages, pas ici.

## Paramètres

- **`working_profile`** — *str*, défaut `sRGB`. Nom du profil de travail global (`"sRGB"` pour le
  profil sRGB standard généré à la volée, ou chemin vers un fichier `.icc`/`.icm` pour un profil
  personnalisé, p. ex. Adobe RGB ou ProPhoto RGB).
- **`rendering_intent`** — *enum*, défaut `perceptual`, choix : `perceptual`, `relative`,
  `saturation`, `absolute`. Intention de rendu ICC par défaut appliquée par les conversions de
  profil ultérieures : `perceptual` préserve les relations visuelles entre teintes (usage
  photographique général), `relative` (colorimétrique relative) préserve les couleurs dans la
  gamme et remappe le point blanc, `saturation` privilégie la vivacité des couleurs (graphiques),
  `absolute` (colorimétrique absolue) préserve les valeurs exactes sans remapper le point blanc
  (usage épreuvage/soft-proofing).
- **`enabled`** — *bool*, défaut `True`. Active globalement la gestion des couleurs. À `False`,
  les conversions ICC en aval peuvent être court-circuitées pour un flux purement numérique sans
  réinterprétation colorimétrique.

## Astuces & pièges

> **Note** — ce process ne modifie **aucun pixel** et ne crée **aucune fenêtre** : c'est un
> réglage global de session, à l'image d'une préférence d'application plutôt que d'un traitement
> d'image. Appelez-le en début de script pour fixer le contexte avant tout export ou toute
> `ICCProfileTransformation`.

- Les réglages écrits ici vivent dans un état **partagé au niveau du module Python** — ils ne sont
  pas sérialisés dans l'historique d'une vue ni dans un fichier XISF/FITS. Pour une recette
  reproductible, appelez explicitement `ColorManagementSetup` au début du script plutôt que de
  compter sur un état laissé par une session précédente.
- Pour attacher un profil à **une fenêtre en particulier** (métadonnée, sans conversion de
  pixels), utilisez plutôt [AssignICCProfile](retina-doc://AssignICCProfile).
- Pour **convertir réellement les pixels** d'un espace colorimétrique à un autre, utilisez
  [ICCProfileTransformation](retina-doc://ICCProfileTransformation), qui peut consommer les
  réglages posés ici comme valeurs par défaut.

## Voir aussi

- [AssignICCProfile](retina-doc://AssignICCProfile) — attache un profil ICC à une fenêtre sans
  toucher aux pixels.
- [ICCProfileTransformation](retina-doc://ICCProfileTransformation) — convertit réellement les
  pixels d'un profil source vers un profil cible.
- [ConvertToRGBColor](retina-doc://ConvertToRGBColor) — conversion d'espace colorimétrique niveau
  pixel (niveaux de gris vers RVB).
- [RGBWorkingSpace](retina-doc://RGBWorkingSpace) — définit l'espace de travail RVB (pondérations
  des canaux) utilisé par les conversions luminance.

## Références

- PixInsight — *ColorManagementSetup* process reference.
- International Color Consortium — *ICC.1:2022* specification.
- Pillow — *PIL.ImageCms* (bindings littlecms).
