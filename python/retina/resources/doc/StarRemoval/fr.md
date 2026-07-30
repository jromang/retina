---
id: StarRemoval
category: MaskGeneration
title: Retrait d'étoiles
brief: Retire les étoiles d'une image (starless) par inpainting, réseau IA ONNX (StarNet/GraXpert) ou outil externe.
keywords: [étoiles, starless, inpainting, StarNet, GraXpert, masque, ONNX]
related: [StarMask, Inpaint, CloneStamp, SeamlessClone]
icon: star-off
references:
  - "Kniazev, N. — StarNet++ (star removal neural network)."
  - "GraXpert — background extraction & AI star removal tool."
  - "scikit-image — restoration.inpaint_biharmonic."
  - "photutils — DAOStarFinder source detection algorithm."
  - "ONNX Runtime — cross-platform neural network inference."
---

## Résumé

`StarRemoval` produit une version **starless** de l'image : les étoiles sont détectées puis
effacées, en reconstruisant le fond (ciel, nébulosité) à leur emplacement. Trois **backends**
interchangeables partagent la même interface : `inpaint` (défaut, sans dépendance IA, basé
photutils + scikit-image), `onnx` (réseau de neurones StarNet/GraXpert exporté en ONNX, exécuté
localement via onnxruntime) et `external` (délégation à un exécutable StarNet++/GraXpert en ligne
de commande). Le résultat sert aussi bien de finalité (image starless artistique) que d'outil
intermédiaire pour traiter nébulosité et étoiles séparément puis les recombiner.

## Cas d'usage

- **Isoler la nébulosité** d'un champ riche en étoiles pour l'étirer ou la traiter (débruitage,
  rehaussement) sans que les étoiles ne saturent ou ne se déforment.
- **Recomposer** ensuite étoiles + starless (via `PixelMath` ou `ChannelCombination`) avec un
  contrôle indépendant du contraste de chacune — technique standard en post-traitement moderne.
- **Réduire la taille apparente des étoiles** en fond de champ dense, en amont d'un montage.
- **Préparer un masque de fond** propre pour `BackgroundExtraction` ou `ColorCalibration`, non
  contaminé par les cœurs d'étoiles.

## Fonctionnement

Le backend `inpaint` (par défaut) enchaîne trois étapes :

1. **Détection** : la luminance (moyenne des canaux) est passée à `DAOStarFinder` (photutils)
   après estimation robuste du fond (`sigma_clipped_stats`) ; le seuil de détection est
   `threshold_sigma` écarts-types au-dessus de la médiane locale, avec une FWHM de recherche
   `fwhm`.
2. **Masquage** : chaque étoile détectée génère un disque de rayon `radius` (en pixels) autour de
   son centroïde ; l'union de ces disques forme le masque binaire des régions à reconstruire.
3. **Reconstruction** : `inpaint_biharmonic` (scikit-image) comble le masque en résolvant une
   équation biharmonique sur chaque canal, en s'appuyant sur les pixels environnants non masqués.

Le backend `onnx` délègue tout le travail à un réseau de neurones pré-entraîné (StarNet ou
GraXpert exporté en `.onnx`). Comme ces réseaux attendent une taille d'entrée fixe, l'image est
découpée en tuiles de côté `tile_size` avec un recouvrement `overlap`, chaque tuile est inférée
séparément puis les résultats sont **refondus** par pondération linéaire (feathering) pour éviter
les coutures visibles aux jonctions.

Le backend `external` sauvegarde l'image en FITS temporaire, invoque `command` (avec `{input}` et
`{output}` substitués), puis recharge le résultat produit par l'outil — utile pour piloter un
StarNet++/GraXpert déjà installé sur la machine sans réimplémenter son pipeline.

## Mathématiques

**Détection (DAOStarFinder).** Le fond local est estimé par statistiques robustes à rejet
sigma : médiane $\tilde b$ et écart-type $\sigma_b$ de l'image après clipping itératif à
$3\sigma$. Un pixel candidat est retenu comme pic d'étoile si son intensité, après soustraction
du fond, dépasse le seuil :

$$ I(x,y) - \tilde b \;>\; \texttt{threshold\_sigma}\cdot \sigma_b . $$

L'algorithme ajuste ensuite un profil gaussien 2D de largeur `fwhm` autour de chaque pic pour en
affiner le centroïde $(x_c, y_c)$.

**Masque.** Pour chaque étoile détectée, tout pixel $(x,y)$ tel que

$$ (x - x_c)^2 + (y - y_c)^2 \;\le\; \texttt{radius}^2 $$

est marqué à reconstruire. Le masque global est l'union booléenne de ces disques.

**Inpainting biharmonique.** Sur la région masquée $\Omega$, chaque canal $u$ est prolongé en
résolvant l'équation biharmonique homogène avec conditions de bord sur $\partial\Omega$ (les
pixels connus adjacents) :

$$ \nabla^4 u = 0 \quad \text{sur } \Omega, \qquad u|_{\partial\Omega} = I|_{\partial\Omega}. $$

Cette PDE d'ordre 4 produit une extension **lisse en courbure** (continuité de $u$ et de son
gradient) plutôt qu'une simple diffusion, ce qui évite les artefacts en « pâté » d'un inpainting
harmonique classique sur de petites lacunes comme des disques d'étoiles.

**Fusion des tuiles (backend `onnx`).** Chaque tuile est pondérée par une fenêtre 2D séparable
$w(i,j) = r(i)\,r(j)$, où $r$ vaut $1$ au centre et décroît linéairement sur `overlap` pixels aux
bords. La reconstruction finale est la moyenne pondérée des tuiles chevauchantes :

$$ I_{\text{out}}(x,y) = \frac{\sum_t w_t(x,y)\, T_t(x,y)}{\sum_t w_t(x,y)} . $$

## Paramètres

- **`mode`** — *enum*, défaut `inpaint`, choix `inpaint` / `onnx` / `external`. Backend utilisé
  pour le retrait : reconstruction classique sans dépendance IA, réseau ONNX local, ou outil
  externe piloté en sous-processus.
- **`fwhm`** — *real*, défaut `3.0`, plage `1`–`20`. Largeur à mi-hauteur (en pixels) attendue des
  étoiles pour la détection ; à adapter à l'échantillonnage et au seeing.
- **`threshold_sigma`** — *real*, défaut `5.0`, plage `1`–`50`. Seuil de détection en écarts-types
  robustes au-dessus du fond ; plus haut = moins d'étoiles faibles détectées.
- **`radius`** — *real*, défaut `5.0`, plage `1`–`50`. Rayon (en pixels) du disque masqué autour
  de chaque étoile détectée, avant reconstruction.
- **`model`** — *path*, défaut vide. Chemin du modèle `.onnx` (StarNet ou GraXpert exporté),
  requis en mode `onnx`.
- **`tile_size`** — *int*, défaut `256`, plage `32`–`2048`. Côté (en pixels) des tuiles soumises
  au réseau ONNX ; doit correspondre à la taille d'entrée attendue par le modèle.
- **`overlap`** — *int*, défaut `32`, plage `0`–`512`. Recouvrement entre tuiles adjacentes, en
  pixels, utilisé pour fondre les jonctions et éviter les coutures.
- **`command`** — *str*, défaut vide. Commande shell exécutée en mode `external`, avec les
  jetons `{input}` et `{output}` remplacés par les chemins des fichiers FITS temporaires.

## Astuces & pièges

> **Attention** — le backend `inpaint` par défaut ne « comprend » pas l'image : sur un champ
> d'étoiles très dense, les disques masqués se chevauchent et la reconstruction biharmonique peut
> laisser des zones plates ou des halos résiduels. Pour un rendu de qualité proche des réseaux
> spécialisés, préférez `onnx` ou `external` avec un modèle StarNet/GraXpert entraîné.

> **Note** — le mode `external` exécute la commande fournie via le shell (`subprocess.run(...,
> shell=True)`) : ne jamais y injecter une chaîne non fiable ; `command` doit rester sous le
> contrôle de l'utilisateur.

- Augmentez `radius` légèrement au-delà du rayon visuel des étoiles pour effacer aussi leurs
  ailes de diffraction, au prix d'une zone reconstruite plus large.
- En mode `onnx`, un `overlap` trop faible produit des coutures visibles entre tuiles ; 32–64 px
  suffit généralement pour des tuiles de 256 px.
- Travaillez sur une copie : la version starless perd de l'information (les étoiles) qui n'est
  récupérable qu'en recombinant avec l'image d'origine ou un `StarMask` dédié.

## Voir aussi

- [StarMask](retina-doc://StarMask) — génère le masque d'étoiles seul, sans reconstruction, pour
  un traitement combiné manuel.
- [Inpaint](retina-doc://Inpaint) — inpainting générique sur une région quelconque, base du
  backend `inpaint`.
- [CloneStamp](retina-doc://CloneStamp) — retouche manuelle point par point, alternative locale
  et précise au retrait automatique.
- [SeamlessClone](retina-doc://SeamlessClone) — clonage à fusion de gradient pour des retouches
  plus étendues.

## Références

- Kniazev, N. — *StarNet++* (star removal neural network).
- GraXpert — *background extraction & AI star removal tool*.
- scikit-image — *restoration.inpaint_biharmonic*.
- photutils — *DAOStarFinder* source detection algorithm.
- ONNX Runtime — cross-platform neural network inference.
