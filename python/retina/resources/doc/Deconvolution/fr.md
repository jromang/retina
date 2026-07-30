---
id: Deconvolution
category: Deconvolution
title: Déconvolution
brief: Restaure la netteté en inversant le flou de la PSF, par Richardson-Lucy régularisé.
keywords: [déconvolution, Richardson-Lucy, PSF, netteté, restauration, deringing, régularisation]
related: [RestorationFilter, UnsharpMask, DynamicPSF, StarMask, NoiseReduction]
icon: focus-centered
references:
  - "Richardson, W. H. (1972) — Bayesian-Based Iterative Method of Image Restoration."
  - "Lucy, L. B. (1974) — An iterative technique for the rectification of observed distributions."
  - "Starck, J.-L. & Murtagh, F. (1998) — Automatic noise estimation from the multiresolution support."
---

## Résumé

`Deconvolution` tente d'**inverser le flou** introduit par l'atmosphère et l'optique
(la *fonction d'étalement du point*, ou PSF) afin de restaurer les détails fins. Elle emploie
l'algorithme itératif de **Richardson-Lucy**, robuste au bruit de Poisson.

Trois choses la distinguent d'un Richardson-Lucy nu :

- la PSF peut être **paramétrique**, **mesurée sur les étoiles du champ** ou prise dans une
  **autre vue** ;
- une **régularisation** multi-échelle empêche le bruit de fond d'exploser quand on itère ;
- le **deringing** atténue les anneaux autour des sources brillantes.

## Cas d'usage

- **Resserrer les étoiles** et révéler la structure des galaxies sur des poses bien échantillonnées.
- **Récupérer du détail** sur une image floutée par la turbulence (seeing modéré).
- Étape de traitement **linéaire** (avant étirement).

## Fonctionnement

On modélise l'image observée $g$ comme la convolution de l'image « vraie » $f$ par la PSF $h$,
plus du bruit. Richardson-Lucy estime $f$ par itérations multiplicatives qui maximisent la
vraisemblance sous hypothèse de bruit poissonien :

$$ f^{(t+1)} = f^{(t)} \cdot \frac{1}{\hat h \circledast 1} \left( \hat h \circledast
   \frac{g}{\,h \circledast f^{(t)}\,} \right) $$

Le rapport $g / (h \circledast f^{(t)})$ mesure l'écart entre l'observation et la reprojection
de l'estimée courante ; sa rétro-convolution par $\hat h$ (la PSF retournée) corrige
multiplicativement $f^{(t)}$. Le facteur $1/(\hat h \circledast 1)$ compense le fait qu'au ras
du cadre le noyau ne voit qu'une partie de son voisinage : sans lui, un liseré sombre se creuse
aux bords et progresse vers l'intérieur à chaque tour. Il vaut exactement 1 dès qu'on est à
plus d'un rayon de PSF du bord.

### Les trois sources de PSF

| `psf_mode` | Ce qui sert de noyau |
|---|---|
| `parametric` | Une gaussienne — ou un Moffat si `psf_function = moffat` — d'écart-type `psf_sigma`. |
| `measured` | La PSF **réelle du champ** : les étoiles sont détectées et ajustées, puis on médiane leurs paramètres de forme (largeurs par axe, orientation, $\beta$) et l'on évalue le modèle. L'excentricité mesurée est donc restituée, ce qu'une gaussienne isotrope ne peut pas faire. |
| `external` | La vue dont l'identifiant est `psf_view` : une PSF synthétique, une étoile découpée, une PSF venue d'ailleurs. Le fond médian en est retiré et le noyau normalisé. |

### La régularisation

À chaque itération, la transformée « à trous » sépare les couches fines de l'estimée, et ce
qui n'y dépasse pas `regularization` dispersions robustes est mis à zéro. Le seuillage est
**dur** : un coefficient significatif passe intact, si bien que les étoiles — structures fines
mais significatives — ne sont pas rabotées.

Deux régularisateurs plus évidents ont été essayés puis écartés, mesure à l'appui : la
**variation totale** et l'**amortissement** de White ne font que ralentir la convergence — à
bruit de fond égal, un Richardson-Lucy nu arrêté plus tôt restitue davantage de flux
stellaire. Sur champ synthétique à vérité terrain, à 600 itérations :

| | RMS / vérité | bruit de fond | flux stellaire |
|---|---|---|---|
| RL nu, 30 itérations | 0,02581 | 0,00254 | 0,751 |
| RL nu, 600 itérations | 0,02598 | 0,00940 | 1,041 |
| régularisé, 600 itérations | **0,02313** | **0,00102** | 0,768 |

Le RL nu *se dégrade* en itérant : son bruit de fond est multiplié par 3,7, et son flux
stellaire dépasse la vérité — il fabrique du signal. Le régularisé garde le fond stable.

> **Ce chiffre est un chiffre de laboratoire.** Le bruit y est **blanc**, si bien que la
> couche fine ne contient rien d'autre et que le seuillage l'emporte presque entièrement. Sur
> une image réelle cette couche porte aussi de la structure : le gain mesuré tombe alors
> autour de 15–20 %. La régularisation ne dispense pas de réduire le bruit **avant** de
> déconvoluer — elle empêche seulement d'en fabriquer.

### Le deringing

Les anneaux naissent au voisinage des fortes transitions. `dering_dark` et `dering_bright`
atténuent la part sombre et la part claire du résidu, **pondérées par le gradient local** de
l'image d'entrée : l'atténuation se concentre là où le défaut apparaît au lieu d'éteindre le
gain de netteté partout. `star_protection` fait revenir l'entrée sur les étoiles elles-mêmes,
sur des disques proportionnels à `psf_sigma` et à bords adoucis.

## Paramètres

- **`psf_mode`** — *enum* `parametric` | `measured` | `external`, défaut `parametric`.
- **`psf_function`** — *enum* `gaussian` | `moffat`, défaut `gaussian`. Profil pour les modes
  `parametric` et `measured`. Le Moffat a des ailes plus longues, souvent plus fidèles au seeing réel.
- **`psf_sigma`** — *real*, défaut `2.0`, plage `0.1`–`20`. Écart-type (pixels) de la PSF
  paramétrique. Sert aussi d'estimation de départ en mode `measured`, et fixe le rayon de
  protection des étoiles. À caler sur la FWHM mesurée (voir `DynamicPSF`) : $\sigma \approx$ FWHM / 2,355.
- **`psf_beta`** — *real*, défaut `2.5`, plage `1.05`–`10`. Exposant du Moffat.
- **`psf_view`** — *str*. Identifiant de la vue tenant lieu de PSF (mode `external`).
- **`star_threshold`** — *real*, défaut `5.0`. Seuil de détection des étoiles, en σ du fond.
  Utilisé par le mode `measured` et par `star_protection`.
- **`iterations`** — *int*, défaut `20`, plage `1`–`500`. Sans régularisation, au-delà de
  quelques dizaines on n'amplifie plus guère que le bruit.
- **`regularization`** — *real*, défaut `0.0`, plage `0`–`10`. Seuil de significativité des
  couches fines, en dispersions robustes. `0` désactive ; `3` est une valeur de travail.
- **`dering_dark`** / **`dering_bright`** — *real*, défaut `0.0`, plage `0`–`1`.
- **`star_protection`** — *real*, défaut `0.0`, plage `0`–`1`.
- **`luminance_only`** — *bool*, défaut `False`. Déconvolue la seule luminance et réapplique le
  rapport aux trois canaux : trois fois moins de travail, et surtout aucune dérive chromatique
  (déconvoluer les canaux séparément les fait converger à des vitesses différentes, ce qui
  colore les bords d'étoiles).

## Astuces & pièges

> **Attention** — la déconvolution amplifie le bruit de fond et provoque des anneaux sombres
> autour des étoiles. Sur données linéaires et peu bruitées, activez `regularization` plutôt
> que de réduire les itérations.

- Mesurez la PSF plutôt que de la deviner : `psf_mode = measured` évite le double risque d'une
  PSF trop large (sur-correction, anneaux) et trop étroite (aucun gain).
- La sortie **n'est pas écrêtée au blanc** : Richardson-Lucy concentre le flux, et rogner le
  cœur des étoiles à 1,0 détruirait leur photométrie.
- Un masque de fenêtre reste utilisable comme toujours ; `star_protection` fait le même travail
  sans avoir à construire le masque.

## Voir aussi

- [DynamicPSF](retina-doc://DynamicPSF) — mesure de la PSF/FWHM des étoiles.
- [RestorationFilter](retina-doc://RestorationFilter) — déconvolution de Wiener (non itérative).
- [StarMask](retina-doc://StarMask) — masque d'étoiles, si vous préférez le poser vous-même.
- [UnsharpMask](retina-doc://UnsharpMask) — accentuation locale, alternative douce.

## Références

- Richardson, W. H. (1972). *Bayesian-Based Iterative Method of Image Restoration*. JOSA.
- Lucy, L. B. (1974). *An iterative technique for the rectification of observed distributions*. AJ.
- Starck, J.-L. & Murtagh, F. (1998). *Automatic noise estimation from the multiresolution support*. PASP.
