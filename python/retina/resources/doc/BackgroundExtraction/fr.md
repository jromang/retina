---
id: BackgroundExtraction
category: BackgroundModelization
title: Extraction de fond
brief: Estime et soustrait le fond de ciel / gradient par un modèle 2D robuste (photutils) ou un réseau de neurones (GraXpert).
keywords: [fond de ciel, gradient, ABE, DBE, background, pollution lumineuse, IA, GraXpert, réseau de neurones]
related: [DynamicBackgroundExtraction, GradientCorrection, BackgroundNeutralization, RollingBallBackground]
icon: layers-subtract
references:
  - "PixInsight — AutomaticBackgroundExtractor / DynamicBackgroundExtraction."
  - "photutils — Background2D and 2D background estimation."
---

## Résumé

`BackgroundExtraction` modélise le **fond de ciel** (gradients de pollution lumineuse, vignetage
résiduel, dégradés de lune) sur une grille robuste, puis le **soustrait**. C'est l'équivalent de
l'ABE de PixInsight : indispensable pour aplatir le fond avant l'étirement et l'étalonnage couleur.

## Cas d'usage

- **Retirer un gradient** de pollution lumineuse ou de lune sur un champ large.
- **Corriger un vignetage résiduel** mal calibré par les flats.
- Préparer une image **plate** avant `BackgroundNeutralization` et l'étalonnage couleur.

## Fonctionnement

Deux moteurs produisent la surface de fond $B$ ; tous deux obéissent ensuite au même contrat
`subtract` / `pedestal`.

**`photutils`** (défaut) — l'image est découpée en boîtes de côté `box_size`. Dans chaque boîte,
une statistique de fond **résistante aux étoiles** est estimée après sigma-clipping (médiane,
`SExtractorBackground` ou `MMMBackground` selon `estimator`). Ces estimations locales forment une
grille basse résolution interpolée en une **surface de fond** $B$ lisse à la taille de l'image.

**`ai`** — le réseau d'extraction de fond de **GraXpert**. Le fond étant lisse par hypothèse,
l'image *entière* est réduite à 256×256, le réseau y estime le fond en une passe, puis le résultat
est lissé et ré-agrandi à pleine résolution — pas de tuilage. Une image mono est répliquée en trois
canaux pour le réseau, puis son fond est rediffusé sur tous ses canaux. Le modèle réellement employé
(nom, version, SHA-256) entre dans l'historique et dans les mots-clés FITS `AIMODEL`, `AIMODVER`,
`AIMODSHA`.

Selon `subtract`, on soustrait cette surface (en réajoutant un petit **piédestal** pour éviter les
valeurs négatives), ou on sort directement le modèle $B$ pour inspection.

> **Les modèles GraXpert sont sous licence CC BY-NC-SA 4.0** — d'usage libre à des fins
> **non commerciales** seulement. Cette restriction vient de GraXpert, pas de Retina. Voir l'écran
> *Licences*. Les modèles sont téléchargés à la demande (ou découverts dans une installation
> GraXpert locale).

## Mathématiques

Sur chaque boîte $b$, l'estimateur robuste $\mu_b$ est calculé après rejet itératif des pixels
à plus de $k\sigma$ de la médiane (les étoiles). L'estimateur SExtractor combine médiane et
moyenne clippées :

$$ \mu_b^{\text{sex}} = 2.5\,\operatorname{med}_b - 1.5\,\overline{x}_b $$

valable quand médiane et moyenne sont proches (fond peu contaminé). La surface de fond $B(x,y)$
interpole les $\{\mu_b\}$. L'image corrigée est :

$$ I'(x,y) = I(x,y) - B(x,y) + p, \qquad p = \texttt{pedestal}, $$

où le piédestal $p$ décale le résultat vers le positif. Avec `subtract = False`, la sortie est
directement $B(x,y)$.

## Paramètres

- **`backend`** — *enum*, défaut `photutils`, choix : `photutils`, `ai`. Le moteur d'estimation.
- **`box_size`** — *int*, défaut `64`, plage `4`–`1024`. *(photutils)* Côté (pixels) des boîtes
  d'estimation. Grand = fond très lisse (grands gradients) ; petit = suit les variations fines
  (risque de mordre sur les nébulosités étendues).
- **`subtract`** — *bool*, défaut `True`. Soustraire le modèle (sinon : produire le modèle seul).
- **`pedestal`** — *real*, défaut `0.1`, plage `0`–`1`. Décalage ajouté après soustraction.
- **`estimator`** — *enum*, défaut `median`, choix : `median`, `sextractor`, `mmm`. *(photutils)*
  Statistique de fond par boîte.
- **`model_id`** — *enum*, défaut `latest`. *(ai)* Le modèle du catalogue à employer ; le menu se
  remplit à la volée depuis le manifeste et toute installation GraXpert locale. `latest` prend le
  plus récent.
- **`model`** — *path*, défaut vide. *(ai)* Un fichier `.onnx` local, prioritaire sur `model_id`.
- **`model_version`**, **`model_sha256`** — *str*, renseignés à l'exécution pour tracer le modèle.

## Astuces & pièges

> **Attention** — une `box_size` trop petite modélise la nébulosité étendue comme du fond et
> l'aspire. Sur objets étendus, augmentez la boîte ou protégez-les par un masque.

- Sortez d'abord le **modèle** (`subtract = False`) pour vérifier qu'il ne contient pas de signal.
- Pour un contrôle par points d'échantillonnage manuels, préférez
  [DynamicBackgroundExtraction](retina-doc://DynamicBackgroundExtraction).

## Voir aussi

- [DynamicBackgroundExtraction](retina-doc://DynamicBackgroundExtraction) — fond par points choisis (≈DBE).
- [GradientCorrection](retina-doc://GradientCorrection) — retrait de gradient global.
- [BackgroundNeutralization](retina-doc://BackgroundNeutralization) — neutralisation colorimétrique du fond.

## Références

- PixInsight — *AutomaticBackgroundExtractor* / *DynamicBackgroundExtraction*.
- photutils — *Background2D* and 2D background estimation.
