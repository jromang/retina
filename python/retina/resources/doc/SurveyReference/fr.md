---
id: SurveyReference
category: BackgroundModelization
title: Référence de survey
brief: Synthétise une image de référence sans gradient du champ, depuis un survey all-sky (HiPS / hips2fits).
keywords: [survey, HiPS, hips2fits, DSS2, Pan-STARRS, gradient, fond de ciel, référence, CDS, MARS]
related: [MultiscaleGradientCorrection, PlateSolve, GradientCorrection, BackgroundExtraction]
icon: stars
references:
  - "Fernique, P. et al. — HiPS: Hierarchical Progressive Survey (recommandation IVOA)."
  - "CDS Strasbourg — service hips2fits : https://alasky.cds.unistra.fr/hips-image-services/hips2fits"
  - "Second Palomar Observatory Sky Survey (POSS-II) / Digitized Sky Survey — STScI / AURA."
---

## Résumé

`SurveyReference` construit une **image sans gradient du champ exact sur lequel vous
travaillez**, tirée d'un survey couvrant tout le ciel, et l'ouvre dans une nouvelle fenêtre.
Cette image ayant été observée depuis un autre site, une autre nuit et par une autre optique,
elle ne partage pas votre gradient — mais elle partage la *forme* du ciel réel. C'est
précisément ce dont `MultiscaleGradientCorrection` a besoin pour distinguer une vraie
nébulosité d'une pollution lumineuse.

Le process est **global** : il ne touche pas aux pixels de la fenêtre source. Il exige une
**solution astrométrique** sur celle-ci (`PlateSolve`, ou un fichier qui porte déjà son WCS —
Retina le lit à l'ouverture).

## Cas d'usage

- Corriger un gradient de pollution lumineuse **sans éroder une nébulosité étendue**, un IFN
  ou le halo externe d'une galaxie — le défaut de toute extraction de fond sans référence.
- Vérifier qu'une structure grande échelle suspecte dans votre intégration est **réelle**
  plutôt qu'un artefact de calibration : si elle est dans le survey, elle est dans le ciel.
- Identifier rapidement le champ (galaxies voisines, bandes de poussière) à la même échelle
  et dans la même orientation que votre image, le WCS étant partagé.

## Fonctionnement

Le WCS de la fenêtre est **sous-échantillonné** à `max_size` pixels au plus sur son grand
côté, en conservant exactement la même empreinte céleste. Ce WCS réduit est envoyé au service
**`hips2fits`** du CDS, qui rend le survey HiPS choisi directement sur cette grille et
retourne une image FITS — il n'y a donc ni base de survey à télécharger, ni reprojection à
faire localement.

La plaque obtenue est normalisée dans `[0, 1]` par percentiles robustes, puis ouverte en
fenêtre portant le WCS réduit : elle se superpose donc à la source (vues liées, readout
céleste). Le résultat est mis en cache sur le disque, sous le dossier de cache utilisateur,
avec pour clé le survey et la grille céleste : ajuster dix fois la correction ne coûte
qu'une seule requête réseau.

## Paramètres

- **`view_id`** — *str*, défaut vide. Fenêtre source (vide = l'active). C'est sa solution
  astrométrique qui définit le champ à demander.
- **`survey`** — *enum*, défaut `dss2-red`. Le survey :
  - `dss2-red`, `dss2-blue` — Digitized Sky Survey 2. **Couverture totale du ciel**, ce qui
    fait du rouge le défaut.
  - `panstarrs-g`, `panstarrs-r`, `panstarrs-i` — Pan-STARRS DR1 : plus profond et mieux
    échantillonné, mais rien sous la déclinaison ≈ −30°.
  - `halpha` — carte Hα de tout le ciel (Finkbeiner), la seule référence pertinente pour une
    pose en bande étroite, où le continuum d'un survey large ne dit rien de votre signal.
  - `custom` — n'importe quel identifiant HiPS du registre CDS, donné dans `hips_id`.
- **`hips_id`** — *str*, uniquement avec `survey = custom`. Ex. `CDS/P/AllWISE/W1`.
- **`max_size`** — *int*, défaut `1024`, `0` = pleine résolution. Grand côté de la référence
  demandée.
- **`use_cache`** — *bool*, défaut `true`. Réutilise une référence déjà obtenue pour le même
  survey et le même champ.
- **`new_image_id`** — *str*, défaut vide (`<source>_<survey>`).

## Astuces & pièges

> **Attention** — seuls les surveys HiPS stockés en **tuiles FITS** peuvent être rendus en
> FITS. L'identifiant le plus connu, `CDS/P/DSS2/color`, est stocké en JPEG : il rendrait du
> 8 bits déjà étiré, inutilisable pour mesurer un fond. Les préréglages ci-dessus sont tous
> en FITS ; avec `custom`, vérifiez que c'est aussi le cas.

> **Note** — une plaque de survey n'est **ni linéaire ni photométrique**. Rien n'y est
> calibré, et rien n'a besoin de l'être : `MultiscaleGradientCorrection` ajuste une relation
> affine par canal, qui absorbe échelle et décalage. N'employez pas cette image pour de la
> photométrie.

- `max_size` n'a pas besoin d'être grand. Seules les grandes échelles sont consommées : une
  référence autour de 1024 px suffit largement, même pour une intégration de 50 mégapixels —
  et cela garde les requêtes rapides et le cache léger.
- Si le survey ne couvre pas votre champ (Pan-STARRS très au sud), le process le dit
  explicitement au lieu de rendre une image pleine de trous.
- La référence est une fenêtre ordinaire : regardez-la, comparez-la à votre image au Blink,
  et corrigez seulement ensuite.

## Console

```python
app.open("/data/M31/integration.fits")     # un fichier résolu porte déjà son WCS
SurveyReference(survey="dss2-red").execute_global(app)
MultiscaleGradientCorrection(reference="M31_dss2-red").execute_on(app.active_view)
```

## Voir aussi

- [MultiscaleGradientCorrection](retina-doc://MultiscaleGradientCorrection) — le
  consommateur de cette référence.
- [PlateSolve](retina-doc://PlateSolve) — obtenir la solution astrométrique qu'exige ce
  process.
- [GradientCorrection](retina-doc://GradientCorrection) — retrait de gradient polynomial,
  sans donnée externe.
- [BackgroundExtraction](retina-doc://BackgroundExtraction) — modèle de fond par grille de
  cases.

## Références

- Fernique, P. et al. — *HiPS: Hierarchical Progressive Survey* (recommandation IVOA).
- CDS Strasbourg — service `hips2fits`.
- Digitized Sky Survey — STScI / AURA ; Pan-STARRS1 Surveys — Chambers, K. C. et al.
