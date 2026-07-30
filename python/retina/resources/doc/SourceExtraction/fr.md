---
id: SourceExtraction
category: ImageInspection
title: Extraction de sources
brief: "Catalogue de sources (segmentation + déblending, photutils) — lecture seule."
keywords: [détection d'étoiles, segmentation, déblending, catalogue, SExtractor, photométrie, masque d'étoiles]
related: [SEPSourceExtraction, StarMask, DynamicPSF, Statistics]
icon: scan
references:
  - "Bertin, E. & Arnouts, S. (1996) — SExtractor: Software for source extraction."
  - "photutils — Image Segmentation (detect_sources, deblend_sources, SourceCatalog)."
---

## Résumé

`SourceExtraction` construit un **catalogue de sources** à partir d'une image, façon
SExtractor : segmentation par seuillage du fond, **déblending** des sources fusionnées,
puis mesure des propriétés de chaque objet (position, flux, aire, ellipticité). C'est un
process **de lecture seule** — comme `Statistics` — qui ne modifie jamais les pixels : il
dépose son résultat dans l'attribut `.result` de l'instance, pas dans l'historique de la vue.
Le moteur est `photutils` (segmentation par régions connexes), robuste et bien documenté,
au prix d'un coût de calcul plus élevé que la voie native `sep` (voir `SEPSourceExtraction`).

## Cas d'usage

- **Construire un masque d'étoiles** en champ dense, en base de départ pour `StarMask` ou
  pour isoler manuellement les sources ponctuelles avant retrait d'étoiles.
- **Contrôle qualité d'une pose** : compter les sources détectées, vérifier leur ellipticité
  moyenne (suivi/mise au point) ou repérer un champ trop pauvre en étoiles pour l'alignement.
- **Point de départ photométrique** : obtenir rapidement flux et centroïdes avant un traitement
  plus poussé (`DynamicPSF` pour un modèle de PSF, ou un calibrateur photométrique dédié).
- **Diagnostiquer un fond mal soustrait** : un nombre de sources anormalement élevé après
  `BackgroundExtraction` trahit souvent un bruit de fond résiduel pris pour du signal.

## Fonctionnement

1. L'image est réduite à une **carte de luminance** (moyenne des canaux si couleur).
2. Le fond et son bruit sont estimés par **sigma-clipping robuste**
   (`astropy.stats.sigma_clipped_stats`), donnant une médiane et un écart-type peu sensibles
   aux étoiles elles-mêmes.
3. Un **seuil de détection** est fixé à `threshold_sigma` écarts-types au-dessus de la
   médiane du fond ; `detect_sources` (photutils) segmente l'image en régions connexes de
   pixels dépassant ce seuil, chaque région devant compter au moins `npixels` pixels adjacents.
4. Si `deblend` est activé, `deblend_sources` sépare les régions correspondant en réalité à
   plusieurs sources se recouvrant (étoiles serrées, cœur de galaxie) — par ré-analyse
   multi-seuils de chaque blob. En cas d'échec de convergence, la segmentation brute est
   conservée sans interrompre le traitement.
5. `SourceCatalog` mesure, pour chaque région, le **centroïde**, le **flux intégré** (somme
   des pixels du segment, fond soustrait), l'**aire** et l'**excentricité** de l'ellipse
   équivalente.
6. Le résultat est stocké dans `self.result` : `{"n_sources": int, "sources": [...]}`, chaque
   entrée étant un dict `{x, y, flux, area, eccentricity}`. Aucune entrée d'historique n'est
   créée — la vue n'est pas modifiée.

## Mathématiques

Le seuil de détection par pixel est linéaire par rapport au fond robuste :

$$ T = \tilde{b} + \kappa \cdot \sigma_b, $$

où $\tilde{b}$ et $\sigma_b$ sont la médiane et l'écart-type du fond après élimination
itérative des valeurs aberrantes (sigma-clipping à $3\sigma$), et $\kappa$ =
`threshold_sigma`. Un pixel appartient à une **source candidate** si sa valeur dépasse $T$ ;
une région connexe de pixels au-dessus du seuil ne forme un segment valide que si son
cardinal atteint `npixels`.

Pour une source segmentée occupant l'ensemble de pixels $\Omega$, le flux mesuré est la
somme du signal après soustraction du fond :

$$ F = \sum_{(x,y)\,\in\,\Omega} \big(I(x,y) - \tilde{b}\big). $$

Le centroïde d'intensité est la moyenne pondérée par le flux :

$$ \bar{x} = \frac{1}{F}\sum_{(x,y)\in\Omega} x\,\big(I(x,y)-\tilde b\big), \qquad
   \bar{y} = \frac{1}{F}\sum_{(x,y)\in\Omega} y\,\big(I(x,y)-\tilde b\big). $$

L'**excentricité** dérive des moments du second ordre de la distribution d'intensité (matrice
de covariance $2\times2$ des positions pondérées par flux) : notant $\lambda_1 \ge \lambda_2$
ses valeurs propres (variances le long des axes principaux de l'ellipse équivalente),

$$ e = \sqrt{1 - \frac{\lambda_2}{\lambda_1}}. $$

$e = 0$ correspond à une source parfaitement ronde (PSF stellaire idéale), $e \to 1$ à une
forme très allongée (étoile filée, trace de satellite, galaxie de profil).

## Paramètres

- **`threshold_sigma`** — *real*, défaut `3.0`, plage `0.5`–`50.0`. Seuil de détection en
  écarts-types robustes au-dessus de la médiane du fond. Trop bas : bruit de fond détecté
  comme sources ; trop haut : seules les sources les plus brillantes survivent.
- **`npixels`** — *int*, défaut `5`, plage `1`–`1000`. Nombre minimal de pixels connectés
  au-dessus du seuil pour valider une détection. Filtre les pixels chauds isolés et le bruit
  ponctuel ; une valeur trop élevée élimine les étoiles les plus faibles ou sous-échantillonnées.
- **`deblend`** — *bool*, défaut `True`. Sépare les sources fusionnées en une même région
  segmentée (étoiles serrées, amas). Coûteux en calcul sur les champs très denses ; peut être
  désactivé pour un contrôle qualité rapide où le comptage précis importe peu.

## Astuces & pièges

> **Attention** — `SourceExtraction` ne modifie **jamais** l'image et **n'ouvre pas
> d'entrée d'historique** : c'est un process de mesure pure. Le résultat vit uniquement
> dans `.result` de l'instance qui l'a exécuté ; il n'est pas persisté ailleurs.

> **Note** — sur de grands champs ou en traitement par lots, `SEPSourceExtraction` (basé sur
> la lib `sep`, portage natif de Source-Extractor) est nettement plus rapide pour un résultat
> qualitativement proche, au prix d'une table de sortie plus restreinte (pas d'ellipticité).

- Exécutez toujours sur une image dont le fond est déjà raisonnablement plat
  (`BackgroundExtraction`) : un gradient résiduel biaise le sigma-clipping et gonfle ou
  réduit artificiellement le nombre de détections.
- Pour un masque d'étoiles de qualité, préférez `StarMask`, qui encapsule une détection
  similaire mais produit directement un masque image plutôt qu'un catalogue.
- L'excentricité seule ne distingue pas une étoile filée d'une galaxie allongée : croisez avec
  l'aire et, si besoin, une inspection visuelle des sources les plus excentriques.

## Voir aussi

- [SEPSourceExtraction](retina-doc://SEPSourceExtraction) — détection équivalente, moteur `sep` très rapide.
- [StarMask](retina-doc://StarMask) — masque d'étoiles binaire dérivé d'une détection similaire.
- [DynamicPSF](retina-doc://DynamicPSF) — modélisation fine de la PSF sur des étoiles choisies.
- [Statistics](retina-doc://Statistics) — autre process de mesure pure, lecture seule.

## Références

- Bertin, E. & Arnouts, S. (1996) — *SExtractor: Software for source extraction*.
- photutils — *Image Segmentation* (`detect_sources`, `deblend_sources`, `SourceCatalog`).
