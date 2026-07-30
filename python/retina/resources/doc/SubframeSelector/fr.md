---
id: SubframeSelector
category: ImageInspection
title: Sélecteur de sous-poses
brief: Mesure FWHM, nombre d'étoiles, bruit de fond et SNR proxy de chaque frame pour calculer un poids relatif.
keywords: [qualité, FWHM, tri de frames, pondération, DAOStarFinder, bruit de fond, sélection]
related: [StarAlignment, Integration, DynamicPSF, RadialProfileMeasurement]
icon: list-check
references:
  - "PixInsight — SubframeSelector process reference."
  - "photutils.detection.DAOStarFinder — DAOPHOT-like source detection."
  - "astropy.stats — sigma_clipped_stats, mad_std."
---

## Résumé

`SubframeSelector` inspecte un ensemble de fichiers bruts (frames lumière) et mesure, pour
chacun, des indicateurs de qualité objectifs : nombre d'étoiles détectées, taille apparente
des étoiles (FWHM), niveau de bruit de fond et un rapport signal/bruit proxy. À partir de ces
mesures, il dérive un **poids relatif** par frame, exploitable pour trier, rejeter ou pondérer
les poses avant recalage (`StarAlignment`) et empilement (`Integration`). C'est un process
**global en lecture seule** : il ne crée aucune fenêtre et n'altère aucune image ; les résultats
sont exposés dans `.measurements` (liste de dictionnaires, un par frame) après appel de
`measure()` (ou de `execute_global`, déclenché par `app.run(...)`).

## Cas d'usage

- **Trier une nuit d'acquisition** avant intégration : repérer les poses floues (passage
  nuageux, mise au point dérivée, suivi défaillant) sans les ouvrir une à une dans un viewer.
- **Rejeter les frames indésirables** en filtrant sur `fwhm`, `stars` ou `snr` avant de
  construire la liste passée à `Integration`.
- **Pondérer une intégration** : utiliser `weight` comme poids par frame dans un schéma
  d'empilement pondéré plutôt qu'une simple moyenne.
- **Auditer une session** : générer un rapport tabulaire (FWHM médiane, bruit, nombre
  d'étoiles) pour comparer plusieurs nuits ou plusieurs réglages d'acquisition.

## Fonctionnement

Pour chaque chemin de `frames`, l'image est chargée puis convertie en luminance (`data.mean`
sur les canaux si l'image est couleur, canal unique sinon). Le traitement enchaîne :

1. **Statistiques de fond robustes** via `astropy.stats.sigma_clipped_stats` (sigma = 3) :
   médiane et écart-type du fond de ciel, insensibles aux pics d'étoiles.
2. **Estimation du bruit** via `mad_std` (écart-type dérivé de l'écart absolu médian),
   indépendante de la médiane calculée à l'étape précédente.
3. **Détection d'étoiles** avec `photutils.detection.DAOStarFinder`, appliqué à l'image
   soustraite de son fond (`luminance − médiane`), avec un seuil de détection absolu égal à
   `threshold_sigma × écart-type` et une échelle de recherche donnée par `fwhm`.
4. **Proxy de FWHM** : DAOStarFinder n'ajuste pas de profil gaussien complet ; la FWHM
   effective est donc approchée à partir de la colonne `sharpness` renvoyée (médiane des
   sources) rapportée au paramètre `fwhm` d'entrée. En l'absence de source détectée, le
   paramètre `fwhm` lui-même sert de repli.
5. **SNR proxy** : rapport de la médiane du fond à l'écart-type robuste (`mad_std`) — un
   indicateur global de contraste fond/bruit, pas une mesure de SNR stellaire par étoile.
6. **Poids relatif** : combinaison du nombre d'étoiles, de la FWHM et du bruit, normalisée
   pour que la somme des poids de toutes les frames vaille 1.

## Mathématiques

Soit $L$ la luminance d'une frame. Les statistiques de fond robustes (médiane $\tilde{L}$ et
écart-type sigma-clippé) sont estimées par rejet itératif à $3\sigma$, puis le bruit est estimé
indépendamment par :

$$ \sigma = \operatorname{mad\_std}(L) = 1.4826 \cdot \operatorname{med}\!\big(|L - \operatorname{med}(L)|\big). $$

La détection d'étoiles s'exécute sur l'image soustraite de son fond, $L - \tilde{L}$, avec un
seuil absolu :

$$ T = \texttt{threshold\_sigma} \times \sigma. $$

Le nombre d'étoiles $n$ est le nombre de sources retournées par DAOStarFinder. Le SNR proxy et
le poids relatif de la frame $i$ (parmi $N$) s'écrivent :

$$ \mathrm{snr}_i = \frac{\tilde{L}_i}{\sigma_i}, \qquad
   w_i = \frac{\dfrac{n_i}{\mathrm{FWHM}_i \cdot \sigma_i}}
              {\displaystyle\sum_{j=1}^{N} \dfrac{n_j}{\mathrm{FWHM}_j \cdot \sigma_j}}. $$

Cette formule favorise les frames à **beaucoup d'étoiles**, **FWHM faible** (bonne netteté) et
**faible bruit** — cohérent avec l'intuition qu'une bonne pose doit être piquée, peu bruitée et
riche en signal détectable. Si aucune frame n'est fournie, `raw.sum()` retombe sur 1 pour éviter
une division par zéro.

## Paramètres

- **`frames`** — *pathlist*, défaut `[]`. Liste des chemins des fichiers frame à mesurer
  (lumière brutes, généralement avant calibration/alignement).
- **`fwhm`** — *real*, défaut `3.0`, plage `1.0`–`20.0`. FWHM approximative (en pixels) des
  étoiles attendue, transmise à `DAOStarFinder` comme échelle de détection et utilisée comme
  valeur de repli du proxy FWHM.
- **`threshold_sigma`** — *real*, défaut `5.0`, plage `1.0`–`50.0`. Seuil de détection exprimé
  en multiples de l'écart-type robuste du fond (`mad_std`) ; plus il est élevé, plus seules les
  étoiles nettement au-dessus du bruit sont comptées.

## Astuces & pièges

> **Attention** — la FWHM renvoyée est un **proxy**, dérivé heuristiquement de la « sharpness »
> DAOStarFinder et non d'un ajustement gaussien réel des profils d'étoiles. Pour une FWHM
> précise par étoile (PSF réellement ajustée), utilisez plutôt `DynamicPSF` ou
> `RadialProfileMeasurement`.

> **Note** — le SNR proxy compare la médiane du fond à son bruit ; ce n'est **pas** le SNR
> d'une étoile ou d'un objet cible. Ne l'interprétez pas comme une mesure de profondeur du signal.

- Une frame sans étoile détectée (nuage, défocalisation extrême) reçoit un poids de 0 dans la
  formule : ajustez `threshold_sigma` ou `fwhm` si des poses par ailleurs exploitables sont
  éliminées à tort.
- Les frames comparées doivent avoir une exposition/gain comparables : la médiane et le bruit
  ne sont pas normalisés par le temps de pose.
- Ce process **ne crée pas de fenêtre** ; consommez `.measurements` en script (console) pour
  filtrer la liste de `frames` avant de la passer à `StarAlignment`/`Integration`.

## Voir aussi

- [DynamicPSF](retina-doc://DynamicPSF) — ajustement de profil PSF étoile par étoile.
- [RadialProfileMeasurement](retina-doc://RadialProfileMeasurement) — mesure de profil radial d'étoile.
- [StarAlignment](retina-doc://StarAlignment) — étape suivante typique : recalage des frames retenues.
- [Integration](retina-doc://Integration) — empilement, éventuellement pondéré par `weight`.

## Références

- PixInsight — *SubframeSelector* process reference.
- photutils.detection — *DAOStarFinder* (détection de sources façon DAOPHOT).
- astropy.stats — *sigma_clipped_stats*, *mad_std*.
