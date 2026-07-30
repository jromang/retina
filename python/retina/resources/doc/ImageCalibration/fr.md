---
id: ImageCalibration
category: Calibration
title: Calibration d'image
brief: Soustrait bias/dark et corrige le flat d'une image à partir de masters fournis par chemin de fichier.
keywords: [calibration, bias, dark, flat, master, prétraitement, CCD]
related: [Integration, Superbias, CosmeticCorrection, StarAlignment]
icon: adjustments
references:
  - "PixInsight — ImageCalibration tool reference."
  - "Howell, S. B. — Handbook of CCD Astronomy (calibration frames)."
  - "ccdproc — CCD data reduction (ccd_process)."
---

## Résumé

`ImageCalibration` applique à la vue active les trois corrections fondamentales du
prétraitement CCD/CMOS : **soustraction du bias**, **soustraction du dark** et **correction du
flat**. Contrairement à l'`ImageCalibration` de PixInsight (qui gère unités, temps de pose et
mise à l'échelle du dark via `ccdproc`), c'est ici une version **pragmatique par arithmétique de
tableaux** : les masters sont fournis comme chemins de fichiers et combinés directement, sans
gestion d'unités. Elle est suffisante pour un pipeline de calibration standard où darks et
lights partagent le même temps de pose et la même température de capteur.

## Cas d'usage

- **Prétraiter une session complète** de lights avant alignement et intégration, en une passe
  par image (bias → dark → flat).
- **Retirer le courant d'obscurité et le bruit de lecture** grâce à un master dark construit à
  la même exposition/température que les lights (voir `Integration`).
- **Homogénéiser la réponse du capteur et corriger le vignettage** grâce au master flat.
- **Calibrer sans dark** (flat-only) sur des poses courtes où le courant d'obscurité est
  négligeable, en laissant `master_dark` vide.

## Fonctionnement

Le process traite l'image en trois étapes séquentielles, chacune optionnelle (activée dès que
le chemin correspondant n'est pas vide) :

1. **Bias** : si `master_bias` est renseigné, le master est chargé (`load_image_array`, qui
   déduit le format depuis l'extension — FITS/XISF/raster/RAW) et **soustrait** tel quel de
   l'image, en float32.
2. **Dark** : si `master_dark` est renseigné, il est soustrait de la même façon. Aucune mise à
   l'échelle par temps de pose n'est appliquée : le master dark doit avoir été acquis à
   l'**exposition et la température** des lights à calibrer.
3. **Flat** : si `master_flat` est renseigné, il est chargé puis **normalisé par sa moyenne**
   (pour ne pas modifier le niveau global de l'image), et l'image est **divisée** par ce flat
   normalisé. Les pixels du flat inférieurs ou égaux à zéro sont neutralisés (remplacés par 1)
   pour éviter une division par zéro ou négative.

Le résultat est enfin **écrêté** dans `[0, 1]` pour rester compatible avec la convention de
plage flottante normalisée de Retina.

## Mathématiques

Soit $I(x,y)$ l'image d'entrée, $B(x,y)$ le master bias, $D(x,y)$ le master dark et
$F(x,y)$ le master flat brut. La calibration procède par étapes successives :

$$ I_1 = I - B \qquad\text{(si bias fourni)} $$

$$ I_2 = I_1 - D \qquad\text{(si dark fourni)} $$

Le flat est d'abord normalisé par sa valeur moyenne $\bar F$ :

$$ \hat F(x,y) = \frac{F(x,y)}{\max(\bar F,\, \varepsilon)}, \qquad
   \bar F = \frac{1}{HW}\sum_{x,y} F(x,y), $$

avec $\varepsilon = 10^{-6}$ pour éviter une division par zéro si le flat est quasi nul. La
correction de champ plat divise l'image par ce flat normalisé, en neutralisant les pixels non
positifs :

$$ I_3(x,y) = \frac{I_2(x,y)}{\hat F'(x,y)}, \qquad
   \hat F'(x,y) = \begin{cases} 1 & \text{si } \hat F(x,y) \le 0 \\ \hat F(x,y) & \text{sinon} \end{cases}. $$

La sortie finale est écrêtée : $I_{\text{out}} = \operatorname{clip}(I_3,\, 0,\, 1)$.

Diviser par un flat **normalisé par sa moyenne** (plutôt que par le flat brut) préserve le
niveau de fond global de l'image tout en corrigeant les variations relatives de sensibilité
pixel à pixel et le vignettage.

## Paramètres

- **`master_bias`** — *path*, défaut `""`. Chemin du master bias (offset électronique + bruit de
  lecture). Laissé vide, aucune soustraction de bias n'est effectuée.
- **`master_dark`** — *path*, défaut `""`. Chemin du master dark (courant d'obscurité). Doit être
  acquis à la même exposition et température que les lights ; laissé vide, aucune soustraction
  de dark n'est effectuée.
- **`master_flat`** — *path*, défaut `""`. Chemin du master flat (réponse du capteur/optique).
  Normalisé automatiquement par sa moyenne avant division ; laissé vide, aucune correction de
  flat n'est effectuée.

## Astuces & pièges

> **Attention** — aucune mise à l'échelle par temps de pose n'est appliquée au dark : si le
> master dark n'a pas la même exposition que les lights, la soustraction sera incorrecte
> (sur- ou sous-soustraction du courant d'obscurité). Utilisez des darks à exposition adaptée,
> ou un dark à échelle (« dark scaling ») en amont.

> **Note** — les masters sont supposés déjà construits (par `Integration` avec rejet sigma sur
> une pile de bias/darks/flats bruts) et de même géométrie que l'image à calibrer.

- Construisez toujours vos masters par **empilement robuste** (`Integration`) plutôt qu'à partir
  d'une seule brute, pour réduire le bruit résiduel.
- Un flat avec des poussières ou du vignettage mal capturé laisse des artefacts circulaires
  après division : vérifiez le flat isolément avant de calibrer toute la session.
- Cette version ne gère pas les **unités physiques** (`ccdproc.ccd_process`) : si le pipeline
  exige une gestion rigoureuse du gain/lecture-bruit en électrons, ce process est à voir comme
  une étape pragmatique, pas une calibration photométrique complète.

## Voir aussi

- [Integration](retina-doc://Integration) — construire les masters bias/dark/flat par moyenne robuste.
- [Superbias](retina-doc://Superbias) — modèle de bias lissé pour réduire le bruit résiduel.
- [CosmeticCorrection](retina-doc://CosmeticCorrection) — nettoyage des pixels chauds/morts après calibration.
- [StarAlignment](retina-doc://StarAlignment) — étape suivante du pipeline, avant intégration.

## Références

- PixInsight — *ImageCalibration* tool reference.
- Howell, S. B. — *Handbook of CCD Astronomy* (calibration frames).
- ccdproc — *CCD data reduction* (`ccd_process`).
