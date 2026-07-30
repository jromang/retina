---
id: CosmeticCorrection
category: CosmeticCorrection
title: Correction cosmétique
brief: "Corrige les pixels chauds/froids par écart au médian local (façon auto CC)."
keywords: [pixels chauds, pixels froids, défauts capteur, médian local, MAD, cosmétique]
related: [DefectMap, CosmicClip, Superbias, NoiseReduction]
icon: bandage
references:
  - "PixInsight — CosmeticCorrection tool reference (Auto Detect)."
  - "scipy.ndimage.median_filter — filtre médian local."
---

## Résumé

`CosmeticCorrection` élimine les **pixels chauds et froids statiques** du capteur — ces
photosites défectueux qui donnent toujours une valeur trop haute ou trop basse, indépendamment
du signal réel. Pour chaque pixel, l'algorithme compare sa valeur au **médian de son voisinage
3×3** ; si l'écart dépasse un seuil exprimé en écarts robustes (σ via MAD), le pixel est
remplacé par ce médian local. C'est l'équivalent du mode « Auto Detect » de l'outil
CosmeticCorrection de PixInsight, sans carte de défauts préalable.

## Cas d'usage

- **Nettoyer un master dark/flat ou une brute** de ses pixels chauds/froids avant intégration,
  quand aucune carte de défauts n'est disponible.
- **Compléter la calibration** (`ImageCalibration`) : la soustraction de dark n'élimine pas
  toujours parfaitement les pixels défectueux dont le comportement dérive avec la température
  ou le temps de pose.
- **Prétraiter avant `StarAlignment`/`Integration`** pour éviter que des pixels aberrants isolés
  ne faussent les statistiques de rejet.

## Fonctionnement

Le traitement s'exécute indépendamment sur chaque canal :

1. Un **filtre médian 3×3** (`scipy.ndimage.median_filter`, mode `reflect` aux bords) donne, pour
   chaque pixel, l'estimation locale du signal attendu en l'absence de défaut.
2. L'écart entre la valeur du pixel et ce médian local (`diff = ch - med`) est calculé sur tout
   le canal.
3. Une **échelle robuste** de cet écart est estimée par MAD (Median Absolute Deviation), mise à
   l'échelle par le facteur $1{,}4826$ pour être comparable à un écart-type gaussien.
4. Un pixel est déclaré **chaud** si son écart dépasse `hot_sigma` fois cette échelle, **froid**
   s'il est inférieur à `-cold_sigma` fois cette échelle.
5. Les pixels marqués sont **remplacés par le médian local** ; les autres sont inchangés.

Contrairement à `CosmicClip` (modèle LA Cosmic, pensé pour les rayons cosmiques ponctuels et
aléatoires d'une exposition à l'autre), `CosmeticCorrection` cible les défauts **statiques** du
capteur — mêmes pixels défectueux d'une pose à l'autre — via un simple écart au voisinage local,
sans modèle de PSF ni détection de bord de trace.

## Mathématiques

Pour un canal $I$, soit $M$ son médian local 3×3 : $M(x,y) = \operatorname{med}_{(u,v) \in
\mathcal{N}_{3\times3}(x,y)} I(u,v)$. On forme le résidu $D = I - M$, puis son échelle robuste
sur l'ensemble de l'image :

$$ s = 1{,}4826 \cdot \operatorname{med}\big(\,|D - \operatorname{med}(D)|\,\big). $$

Le facteur $1{,}4826$ rend $s$ cohérent avec un écart-type pour une distribution gaussienne,
ce qui permet d'exprimer les seuils `hot_sigma`/`cold_sigma` en unités de $\sigma$ interprétables.
Un pixel $(x,y)$ est corrigé selon :

$$
I'(x,y) =
\begin{cases}
M(x,y) & \text{si } D(x,y) > h \cdot s \quad \text{(chaud)} \\
M(x,y) & \text{si } D(x,y) < -c \cdot s \quad \text{(froid)} \\
I(x,y) & \text{sinon}
\end{cases}
$$

où $h$ = `hot_sigma` et $c$ = `cold_sigma`. Si $s$ s'annule (image parfaitement plate), un
plancher de $10^{-6}$ évite une division par zéro et empêche toute correction spurieuse.

## Paramètres

- **`hot_sigma`** — *real*, défaut `3.0`, plage `0.5`–`20.0`. Seuil de détection des pixels
  chauds, en écarts robustes (σ) au-dessus du médian local. Plus la valeur est basse, plus la
  détection est agressive (risque de corriger du vrai signal fin, comme le cœur d'une étoile).
- **`cold_sigma`** — *real*, défaut `3.0`, plage `0.5`–`20.0`. Seuil de détection des pixels
  froids, symétrique de `hot_sigma` en dessous du médian local.

## Astuces & pièges

> **Attention** — un seuil trop bas (proche de 0,5) traite le bruit de photon normal ou les
> étoiles fines comme des défauts et les écrase en un médian local, ce qui dégrade la finesse
> de l'image. Commencez autour de 3–5σ et affinez visuellement.

> **Note** — le filtre étant appliqué canal par canal sans tenir compte de la structure de
> Bayer, exécutez `CosmeticCorrection` **avant** `Debayer` sur des brutes CFA, ou sur des
> sous-images séparées via `SplitCFA` si le motif capteur doit être respecté.

- Si les pixels défectueux sont connus et stables (carte issue d'un master dark), préférez
  `DefectMap`, plus sûr car il ne touche que les positions marquées, sans faux positifs.
- Combiné à `Superbias`, `CosmeticCorrection` sur les masters de calibration limite la
  propagation de pixels défectueux dans toute la pile d'images calibrées.

## Voir aussi

- [DefectMap](retina-doc://DefectMap) — correction ciblée via une carte de défauts fournie.
- [CosmicClip](retina-doc://CosmicClip) — rejet de rayons cosmiques (modèle LA Cosmic).
- [Superbias](retina-doc://Superbias) — modélisation du bias, autre étape de calibration.
- [NoiseReduction](retina-doc://NoiseReduction) — débruitage général, à ne pas confondre avec
  la correction de défauts ponctuels.

## Références

- PixInsight — *CosmeticCorrection* tool reference (mode Auto Detect).
- scipy.ndimage — *median_filter*, filtre médian local.
