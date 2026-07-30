---
id: DefectMap
category: CosmeticCorrection
title: Carte de défauts (DefectMap)
brief: Remplace les pixels marqués défectueux par une carte externe avec la médiane locale de leur voisinage.
keywords: [pixels chauds, pixels froids, capteur, colonnes défectueuses, médiane locale, carte de défauts]
related: [CosmeticCorrection, PixelInterpolation, CosmicClip, Superbias]
icon: grid-pattern
references:
  - "PixInsight — CosmeticCorrection tool reference (Defect List / Master Dark based detection)."
  - "scipy.ndimage.median_filter — filtre médian glissant."
---

## Résumé

`DefectMap` corrige les pixels défectueux d'un capteur (chauds, froids, colonnes ou lignes mortes)
en s'appuyant sur une **carte de défauts externe** fournie par l'utilisateur, plutôt que sur une
détection statistique automatique. Chaque pixel marqué non nul dans la carte est remplacé par la
**médiane locale** de son voisinage dans l'image traitée. C'est le pendant « carte fixe » de
`CosmeticCorrection` : utile quand la position des défauts est connue à l'avance (analyse d'un
master dark, cartographie constructeur) et doit être appliquée identiquement à toute une série
d'images, indépendamment du bruit ou du signal présents dans chaque frame.

## Cas d'usage

- **Corriger des pixels chauds/froids récurrents** d'un capteur donné, identifiés une fois pour
  toutes sur un master dark ou un bias, et réutilisés sur toute une session ou tout un instrument.
- **Masquer une colonne ou une ligne défectueuse connue** (défaut de fabrication) sans dépendre
  d'un seuil statistique qui pourrait la manquer sur certaines poses.
- **Traiter un lot homogène** (même caméra, même configuration) avec une correction reproductible
  et identique frame après frame, contrairement à une détection au cas par cas.

## Fonctionnement

1. La **carte de défauts** (`map_path`) est chargée via le même chargeur générique que les images
   (`load_image_array`, formats FITS/XISF/TIFF/PNG/JPEG/BMP). Si l'image chargée est en couleur,
   seul son premier canal sert de masque.
2. Un pixel est considéré **défectueux** si sa valeur dans la carte est **non nulle** — la carte
   est donc typiquement une image binaire (0 = sain, 1 ou 255 = défectueux) produite manuellement
   ou par un autre outil de détection.
3. Pour chaque canal de l'image à traiter, un **filtre médian glissant** de taille
   $2\cdot\texttt{radius}+1$ est calculé sur toute l'image (mode de bord « reflect »).
4. Le résultat final ne remplace **que** les pixels marqués défectueux par la valeur du filtre
   médian à cette position ; tous les autres pixels restent inchangés à l'identique.

Si `map_path` est vide, le process est un **passe-plat** : l'image est renvoyée inchangée (copie).

## Mathématiques

Soit $D(x,y) \in \{0,1\}$ l'indicatrice de défaut tirée de la carte (`dmap[x,y] \neq 0`), et
$I_c(x,y)$ l'image d'entrée pour le canal $c$. On calcule d'abord la médiane glissante sur une
fenêtre carrée de côté $n = 2r + 1$ (avec $r$ = `radius`) :

$$ M_c(x,y) = \operatorname{med}\Big(\, I_c(x', y') \;:\; (x',y') \in W_n(x,y) \,\Big), $$

où $W_n(x,y)$ désigne le voisinage $n \times n$ centré en $(x,y)$ (repliement en miroir aux bords).
La sortie est un remplacement conditionnel pixel par pixel :

$$ I'_c(x,y) = \begin{cases} M_c(x,y) & \text{si } D(x,y) = 1 \\ I_c(x,y) & \text{sinon.} \end{cases} $$

Le filtre médian est utilisé — plutôt qu'une moyenne — car il est **robuste** : même si le
voisinage immédiat contient d'autres pixels défectueux ou du bruit impulsionnel, la médiane ne
s'en trouve affectée que si plus de la moitié de la fenêtre est corrompue.

## Paramètres

- **`map_path`** — *path*, défaut `""` (vide). Chemin vers la carte de défauts : une image où tout
  pixel **non nul** (sur son premier canal) désigne un pixel à corriger. Si vide, aucune correction
  n'est appliquée.
- **`radius`** — *int*, défaut `1`, plage `1`–`10`. Rayon du voisinage médian utilisé pour
  reconstruire chaque pixel défectueux ; la fenêtre effective fait $2\cdot\texttt{radius}+1$
  pixels de côté.

## Astuces & pièges

> **Attention** — la carte de défauts doit avoir **exactement les mêmes dimensions** que les
> images à corriger. Un décalage de géométrie (recadrage, binning différent) déplace la correction
> sur des pixels sains.

> **Note** — contrairement à `CosmeticCorrection`, aucun seuil statistique n'entre en jeu ici : la
> carte fait foi. Une carte trop généreuse (trop de pixels marqués) lisse localement l'image au-delà
> du nécessaire.

- Une carte de défauts se construit typiquement en seuillant un master dark ou un master bias
  (pixels très au-dessus ou très en dessous de la médiane globale), puis en la binarisant.
- Un `radius` trop grand dilue le remplacement dans un voisinage large, ce qui peut lisser un fin
  détail voisin d'un défaut ; commencez à `1` et n'augmentez que si des artefacts subsistent.
- Pour une correction adaptative pixel par pixel sans carte préétablie, voir `CosmeticCorrection`.

## Voir aussi

- [CosmeticCorrection](retina-doc://CosmeticCorrection) — détection statistique et correction
  automatique des pixels chauds/froids.
- [PixelInterpolation](retina-doc://PixelInterpolation) — comble les NaN / pixels morts par
  convolution gaussienne pondérée.
- [CosmicClip](retina-doc://CosmicClip) — rejet des rayons cosmiques (astroscrappy).
- [Superbias](retina-doc://Superbias) — modélisation d'un master bias lissé.

## Références

- PixInsight — *CosmeticCorrection* tool reference (détection par liste de défauts / master dark).
- scipy.ndimage — *median_filter*, filtre médian glissant.
