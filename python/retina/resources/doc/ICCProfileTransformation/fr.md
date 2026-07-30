---
id: ICCProfileTransformation
category: ColorManagement
title: Transformation de profil ICC
brief: Convertit les pixels d'un espace colorimétrique source vers un profil cible via la chaîne ICC (littlecms/PIL.ImageCms).
keywords: [ICC, gestion des couleurs, littlecms, profil colorimétrique, intention de rendu, sRGB, PCS]
related: [AssignICCProfile, ColorManagementSetup, ColorCalibration, ConvertToRGBColor]
icon: transform
references:
  - "International Color Consortium — ICC.1:2022 Specification (format de profil ICC)."
  - "Pillow — module ImageCms (bindings Little CMS 2)."
  - "Little CMS project — documentation sur les intentions de rendu (rendering intents)."
---

## Résumé

`ICCProfileTransformation` convertit réellement les valeurs de pixels d'un espace colorimétrique
**source** vers un espace **cible**, en s'appuyant sur la chaîne de gestion des couleurs
**littlecms** embarquée dans Pillow (`PIL.ImageCms`). Contrairement à `AssignICCProfile`, qui se
contente d'attacher un profil comme métadonnée de fenêtre, ce process **réécrit les pixels** : c'est
l'outil à utiliser quand on veut faire correspondre le rendu d'une image à un espace colorimétrique
précis (sRGB pour le web, Adobe RGB/ProPhoto pour l'impression, profil custom d'un capteur…).

Nos données internes sont *scene-linear* en float 32 bits et ne portent normalement pas de profil ICC
tant qu'elles restent dans le pipeline de traitement ; cette transformation intervient plutôt en aval,
au moment du rendu ou de l'export.

## Cas d'usage

- **Exporter vers le web** : convertir une image étirée vers sRGB avant un export JPEG/PNG, pour un
  rendu cohérent sur tous les écrans standards.
- **Préparer une impression** : adapter vers un espace plus large (Adobe RGB, ProPhoto RGB) avec une
  intention de rendu colorimétrique adaptée au support.
- **Aligner une image importée** dont le profil ICC diffère du pipeline de travail (photo DSLR, scan,
  export d'un autre logiciel) sur le profil de travail courant.
- **Convertir le rendu d'un capteur** dont un profil custom a été attaché via `AssignICCProfile`, avant
  de repasser en sRGB pour diffusion.

## Fonctionnement

1. Les trois premiers canaux de l'image (`RGB`) sont extraits ; si l'image est monochrome, le canal
   unique est dupliqué trois fois pour obtenir une image RGB (la gestion des couleurs ICC opère sur un
   espace colorimétrique, pas sur un canal de luminance isolé).
2. Les valeurs flottantes `[0, 1]` sont **quantifiées en 8 bits** (`uint8`, `0`–`255`) pour former une
   image PIL, format d'entrée attendu par `ImageCms.profileToProfile`.
3. Les deux profils (`from_profile`, `to_profile`) sont chargés : le nom `"sRGB"` instancie le profil
   sRGB standard créé par littlecms, toute autre valeur est interprétée comme un chemin vers un fichier
   `.icc`/`.icm` sur disque.
4. `ImageCms.profileToProfile` applique la conversion via l'espace de connexion des profils (PCS),
   selon l'intention de rendu choisie (`intent`).
5. Le résultat 8 bits est reconverti en float32 `[0, 1]` par division par 255. Sur une image
   monochrome à l'origine, la sortie RGB est ramenée à un canal par moyenne des trois composantes.

## Mathématiques

La conversion ICC ne relie jamais deux profils directement : elle passe par un espace **indépendant
du périphérique**, le *Profile Connection Space* (PCS, typiquement CIEXYZ ou CIELAB). Pour un profil
« matriciel » simple (cas courant de sRGB et des espaces RGB standards), la chaîne se décompose en une
**courbe de transfert** (TRC) par canal suivie d'une **matrice** vers le PCS :

$$ C_{\text{lin}} =
\begin{cases}
C / 12.92 & C \le 0.04045 \\[4pt]
\left(\dfrac{C + 0.055}{1.055}\right)^{2.4} & C > 0.04045
\end{cases}
\qquad\qquad
\begin{pmatrix} X \\ Y \\ Z \end{pmatrix} = M_{\text{src}}
\begin{pmatrix} R_{\text{lin}} \\ G_{\text{lin}} \\ B_{\text{lin}} \end{pmatrix} $$

La conversion vers le profil cible applique la transformation inverse — matrice $M_{\text{dst}}^{-1}$
puis TRC inverse — avec, entre les deux, une **adaptation chromatique** (transformée de Bradford $A$)
si les points blancs des profils source et cible diffèrent :

$$ \begin{pmatrix} R'_{\text{lin}} \\ G'_{\text{lin}} \\ B'_{\text{lin}} \end{pmatrix}
= M_{\text{dst}}^{-1}\, A_{W_{\text{src}} \to W_{\text{dst}}}\, M_{\text{src}}
\begin{pmatrix} R_{\text{lin}} \\ G_{\text{lin}} \\ B_{\text{lin}} \end{pmatrix} $$

L'**intention de rendu** (`intent`) détermine comment les couleurs hors gamut du profil cible sont
traitées :

- **`perceptual`** — compresse l'ensemble du gamut de façon non linéaire pour préserver les relations
  relatives entre couleurs ; aucun écrêtage brutal, rendu perçu comme naturel (recommandé pour la
  photo/astrophoto grand public).
- **`relative`** (colorimétrique relatif) — adapte le point blanc puis **écrête** au bord du gamut
  cible les couleurs hors gamme ; fidélité colorimétrique pour les tons dans le gamut.
- **`saturation`** — privilégie la saturation perçue au détriment de la précision colorimétrique
  (graphiques, présentations).
- **`absolute`** — comme `relative` mais **sans** adaptation du point blanc : simule le rendu exact du
  périphérique cible, y compris son propre blanc (utilisé en épreuvage/proofing).

La quantification intermédiaire en 8 bits introduit une erreur de discrétisation d'au plus
$1/510 \approx 0{,}2\%$ en valeur normalisée par canal, négligeable pour un rendu final mais à garder
en tête sur des gradients très doux (voir Astuces).

## Paramètres

- **`from_profile`** — *str*, défaut `sRGB`. Profil colorimétrique source. `"sRGB"` charge le profil
  sRGB standard ; toute autre chaîne est traitée comme un chemin vers un fichier `.icc`/`.icm`.
- **`to_profile`** — *str*, défaut `sRGB`. Profil colorimétrique cible, mêmes règles de résolution que
  `from_profile`.
- **`intent`** — *enum*, défaut `perceptual`, choix : `perceptual`, `relative`, `saturation`,
  `absolute`. Intention de rendu appliquée par littlecms pour gérer les couleurs hors gamut.

## Astuces & pièges

> **Attention** — l'implémentation actuelle quantifie l'image en **8 bits** (`0`–`255`) pendant la
> transformation, malgré ce que suggère la documentation interne du process. Sur un dégradé de fond
> de ciel très doux, cela peut introduire un léger banding ; si c'est visible, appliquez un léger
> dithering/bruit après conversion, ou reportez la conversion ICC en toute fin de pipeline export.

> **Note** — sur une image monochrome, la conversion passe par une image RGB dupliquée puis retombe
> sur un canal par moyenne des trois sorties. Les profils ICC purement « Gray » ne sont donc pas
> gérés nativement par ce process.

- Utilisez l'intention **`perceptual`** pour un export web/JPEG au rendu agréable, **`relative`**
  quand la fidélité colorimétrique compte (comparaison photométrique, calibration croisée).
- `ICCProfileTransformation` ne remplace pas `ColorCalibration` / `PhotometricColorCalibration`, qui
  équilibrent la couleur à partir du **signal astronomique** lui-même (étoiles, catalogues). Ce process
  agit en aval, sur la **présentation finale** de l'image, une fois la balance des couleurs établie.
- Pour attacher un profil à une fenêtre sans toucher aux pixels (juste une métadonnée d'export),
  utilisez `AssignICCProfile` ; pour fixer le profil de travail global de l'application, voir
  `ColorManagementSetup`.

## Voir aussi

- [AssignICCProfile](retina-doc://AssignICCProfile) — attache un profil ICC comme métadonnée, sans modifier les pixels.
- [ColorManagementSetup](retina-doc://ColorManagementSetup) — réglages globaux de gestion des couleurs.
- [ColorCalibration](retina-doc://ColorCalibration) — équilibrage colorimétrique basé sur le signal astro.
- [ConvertToRGBColor](retina-doc://ConvertToRGBColor) — conversion d'espace colorimétrique interne (mono → RGB).

## Références

- International Color Consortium — *ICC.1:2022 Specification* (format de profil ICC).
- Pillow — module *ImageCms* (bindings Little CMS 2).
- Little CMS project — documentation sur les intentions de rendu (*rendering intents*).
