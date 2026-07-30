---
id: SEPSourceExtraction
category: ImageInspection
title: Extraction de sources SEP
brief: Catalogue de sources ultra-rapide (fond + détection) via la bibliothèque sep (Source-Extractor natif).
keywords: [détection de sources, catalogue, SExtractor, sep, étoiles, photométrie isophotale, contrôle qualité]
related: [SEPBackground, SourceExtraction, StarMask, DynamicPSF]
icon: scan
references:
  - "Bertin, E. & Arnouts, S. (1996) — SExtractor: Software for source extraction."
  - "Barbary, K. — sep: Source Extraction and Photometry (documentation Python)."
  - "PixInsight — DynamicPSF / StarAlignment (détection d'étoiles)."
---

## Résumé

`SEPSourceExtraction` construit un **catalogue de sources** (position, flux, aire) en s'appuyant
sur la bibliothèque `sep` — le portage Python/C du moteur natif de **SExtractor**. C'est la voie
« Tier B » de la détection de sources dans Retina : bien plus rapide que `SourceExtraction`
(photutils), au prix d'un modèle de fond et d'un déblending plus rudimentaires. Le process est en
**lecture seule** : il ne modifie jamais les pixels de l'image, seulement `self.result`.

## Cas d'usage

- **Contrôle qualité rapide** d'une pile de brutes (nombre d'étoiles détectées, densité du champ)
  sans payer le coût d'un modèle de fond photutils complet.
- **Prétraitement** avant recalage ou empilement : fournir une liste de positions candidates à
  `StarAlignment` ou à un `StarMask` externe.
- **Suivi de séance** : comparer le nombre de sources détectées image par image pour repérer les
  poses dégradées (passage nuageux, mise au point dérivée, bruit excessif).
- Champs **très denses ou très grands** où `SourceExtraction` (photutils) devient trop lent.

## Fonctionnement

1. L'image est réduite à une **luminance** 2D (moyenne des canaux si couleur) et convertie en
   `float32` contigu, format exigé par `sep`.
2. `sep.Background` estime un **fond de ciel** sur une grille de mesh (paramètres par défaut de
   `sep` : cases de 64×64 px, filtre médian 3×3), avec rejet des pixels aberrants façon
   SExtractor, puis interpolation en une surface lisse.
3. Le fond est soustrait de la luminance (`sub = lum - bkg.back()`), et son écart-type global
   (`bkg.globalrms`) sert de mesure de bruit de référence.
4. `sep.extract` seuille l'image soustraite à `threshold_sigma` fois ce bruit, regroupe les pixels
   connexes en objets (aire minimale `min_area`), et **déblende** automatiquement les sources
   fusionnées par seuillage multi-niveaux (algorithme SExtractor standard).
5. Pour chaque objet retenu, la position est le **centroïde pondéré par l'intensité**, le flux est
   la somme isophotale des pixels au-dessus du seuil, et l'aire est le nombre de pixels du segment.
   Le résultat est stocké dans `self.result = {"n_sources": ..., "sources": [...]}`.

## Mathématiques

Soit $I(x,y)$ la luminance et $B(x,y)$ le modèle de fond produit par `sep.Background`. L'image
soustraite est $S(x,y) = I(x,y) - B(x,y)$, et $\sigma$ (`bkg.globalrms`) l'écart-type global estimé
sur cette même surface. Un pixel est **détecté** s'il dépasse le seuil :

$$ S(x,y) > t \cdot \sigma, \qquad t = \texttt{threshold\_sigma} $$

Les pixels détectés adjacents (connexité 8) forment un objet si son nombre de pixels
$N \ge \texttt{min\_area}$. Pour un objet de pixels $\{(x_i, y_i)\}_{i=1}^{N}$, le flux isophotal
et le centroïde pondéré par l'intensité sont :

$$ F = \sum_{i=1}^{N} S(x_i, y_i), \qquad
   \bar{x} = \frac{\sum_i x_i\, S(x_i, y_i)}{\sum_i S(x_i, y_i)}, \qquad
   \bar{y} = \frac{\sum_i y_i\, S(x_i, y_i)}{\sum_i S(x_i, y_i)} $$

Quand deux sources se touchent, `sep.extract` reteste chaque objet à une série de sous-seuils
exponentiellement espacés entre le pic et $t\sigma$ ; une branche est scindée en objet séparé dès
que son flux dépasse une fraction (par défaut 0,5 %) du flux total de la branche parente — c'est le
**déblending multi-seuils** hérité de SExtractor.

## Paramètres

- **`threshold_sigma`** — *real*, défaut `3.0`, plage `0.5`–`50.0`. Seuil de détection exprimé en
  multiples de l'écart-type global du fond (`bkg.globalrms`). Plus il est bas, plus on détecte de
  sources faibles, au prix de faux positifs dans le bruit.
- **`min_area`** — *int*, défaut `5`, plage `1`–`1000`. Nombre minimal de pixels connexes
  au-dessus du seuil pour qu'un groupe soit retenu comme source. Filtre le bruit à un pixel et les
  rayons cosmiques ponctuels.

## Astuces & pièges

> **Attention** — le fond `sep.Background` par défaut utilise des cases de 64 px sans réglage
> exposé ici : sur un champ à fort gradient (vignettage, pollution lumineuse marquée), préférez
> d'abord `SEPBackground` ou `BackgroundExtraction` en amont, puis relancez l'extraction sur
> l'image déjà aplanie pour un fond résiduel plus fiable.

> **Note** — `bkg.globalrms` est un bruit **global** unique pour toute l'image : contrairement à
> `SourceExtraction` (photutils), aucune carte de bruit locale n'est utilisée. Sur une image à
> bruit très hétérogène (mosaïque, empilement partiel), le seuil peut être trop permissif dans les
> zones bruitées et trop strict dans les zones calmes.

- Le résultat n'inclut ni ellipticité ni orientation (contrairement à `SourceExtraction`) : pour un
  masque d'étoiles ou une mesure de forme, utilisez plutôt `StarMask` ou `DynamicPSF`.
- Pour un simple comptage rapide sur de très grandes images (mosaïques, champ large), c'est la
  voie la plus économique du catalogue Retina.

## Voir aussi

- [SEPBackground](retina-doc://SEPBackground) — même bibliothèque `sep`, pour aplanir le fond en amont.
- [SourceExtraction](retina-doc://SourceExtraction) — catalogue équivalent via photutils (déblending et ellipticité).
- [StarMask](retina-doc://StarMask) — masque binaire des étoiles à partir d'une détection similaire.
- [DynamicPSF](retina-doc://DynamicPSF) — mesure de profil (FWHM, forme) étoile par étoile.

## Références

- Bertin, E. & Arnouts, S. (1996) — *SExtractor: Software for source extraction*.
- Barbary, K. — *sep: Source Extraction and Photometry* (documentation Python).
- PixInsight — *DynamicPSF* / *StarAlignment* (détection d'étoiles).
