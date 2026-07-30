---
id: HDRMultiscaleTransform
category: MultiscaleProcessing
title: HDR Multiscale Transform
brief: Compresse la dynamique globale d'une image en atténuant le résidu starlet tout en préservant les couches de détail.
keywords: [HDR, multiscale, starlet, à trous, compression de dynamique, résidu, dynamique globale]
related: [MultiscaleLinearTransform, MultiscaleAdaptiveStretch, GradientHDRCompression, HDRComposition]
icon: stack
references:
  - "PixInsight — HDRMultiscaleTransform tool reference."
  - "Starck, J.-L. & Murtagh, F. — Astronomical Image and Data Analysis (transformée starlet / à trous)."
---

## Résumé

`HDRMultiscaleTransform` (HDRMT) compresse la **dynamique globale** d'une image tout en
préservant intégralement son **contraste local**. Le principe : décomposer l'image en
transformée starlet (couches de détail + résidu grande échelle), aplatir le résidu — qui porte
la dynamique de brillance globale — par une loi de puissance, puis reconstruire en rajoutant
les couches de détail sans les toucher. Résultat : les cœurs saturés d'une galaxie ou d'une
étoile brillante et les extensions faibles environnantes deviennent simultanément visibles,
sans le halo ni l'aplatissement du contraste local qu'un simple étirement de courbe produirait.

## Cas d'usage

- **Révéler le cœur et les extensions d'une galaxie** (bulbe brillant + bras spiraux faibles)
  dans une même image, sans masque ni composite manuel.
- **Dompter le cœur d'une nébuleuse très contrastée** (M42/Orion) en gardant les filaments
  ténus visibles autour.
- **Alternative locale à `GradientHDRCompression`** lorsque la scène ne présente pas de
  gradient franc mais une dynamique globale trop large pour un histogramme/courbe classique.
- **Étape de finition** avant un léger rehaussement de structures (`MultiscaleLinearTransform`,
  `UnsharpMask`), une fois la dynamique globale ramenée dans une plage exploitable.

## Fonctionnement

Pour chaque canal, canal par canal :

1. **Décomposition starlet** (`starlet_transform`, noyau B3-spline « à trous ») en `layers`
   couches de détail $w_1, \dots, w_J$ (des fines structures aux plus grandes) et un **résidu**
   $c_J$ qui porte la tendance de brillance à très grande échelle.
2. **Compression du résidu** : le résidu est normalisé dans $[0,1]$ puis passé par une loi de
   puissance dont l'exposant dépend d'`overdrive` — plus `overdrive` est élevé, plus la
   compression est forte (le résidu s'aplatit, réduisant l'écart entre zones brillantes et
   sombres à grande échelle).
3. **Reconstruction** : les couches de détail sont rajoutées **inchangées** au résidu compressé
   — le contraste local (bords, petites structures, granularité du bruit) n'est donc jamais
   altéré par la compression.
4. **Renormalisation min-max** du canal reconstruit vers `[0, 1]`, puis écrêtage final.

C'est cette séparation stricte entre échelle globale (compressée) et échelles locales
(préservées) qui distingue HDRMT d'un simple étirement d'histogramme ou d'une gamma globale :
seule la composante responsable de la « largeur » dynamique est touchée.

## Mathématiques

La décomposition starlet à $J$ = `layers` échelles s'obtient par filtrage « à trous »
récursif avec le noyau B3-spline séparable $h = \tfrac{1}{16}[1,4,6,4,1]$, dilaté d'un facteur
$2^{j}$ à l'échelle $j$ :

$$ c_0 = I, \qquad c_{j+1} = h_{2^{j}} * c_j, \qquad w_{j+1} = c_j - c_{j+1}, \quad j = 0,\dots,J-1 $$

où $c_J$ est le **résidu** (composante de plus grande échelle) et les $w_j$ les couches de
détail. La reconstruction exacte est la somme télescopique :

$$ I = \sum_{j=1}^{J} w_j + c_J . $$

HDRMT ne touche qu'au résidu. Après normalisation locale $r = (c_J - \min c_J)/(\max c_J -
\min c_J)$, on applique une compression en loi de puissance :

$$ r' = r^{\,\gamma}, \qquad \gamma = 1 - \tfrac{1}{2}\,\texttt{overdrive} \in [0.5,\ 1] $$

puis on redimensionne vers la plage d'origine et on reconstruit :

$$ I' = \sum_{j=1}^{J} w_j \;+\; \big(r' \cdot (\max c_J - \min c_J) + \min c_J\big). $$

Avec `overdrive = 0`, $\gamma = 1$ : le résidu n'est pas modifié et la transformation est
(quasi) l'identité. Avec `overdrive = 1`, $\gamma = 0{,}5$ (racine carrée) : les valeurs
faibles du résidu sont fortement relevées relativement aux valeurs fortes — la dynamique de
brillance à grande échelle se comprime. Une renormalisation min-max finale de $I'$ ramène le
résultat dans $[0,1]$, car la compression du résidu déplace l'échelle globale de luminosité.

## Paramètres

- **`layers`** — *int*, défaut `6`, plage `2`–`12`. Nombre de couches de détail de la
  décomposition starlet. Plus `layers` est élevé, plus le résidu compressé porte une échelle
  spatiale large (structures très étendues) et plus les couches préservées couvrent de détails
  fins ; un `layers` trop faible laisse des structures de taille moyenne dans le résidu, qui
  seront alors elles aussi compressées.
- **`overdrive`** — *real*, défaut `0.0`, plage `0.0`–`1.0`. Intensité de la compression du
  résidu (contraste global). `0` = pas de compression (identité) ; `1` = compression maximale
  (loi en racine carrée), qui égalise fortement les brillances à grande échelle.

## Astuces & pièges

> **Attention** — un `overdrive` élevé peut donner un rendu « plat » ou artificiel si l'image
> ne présente pas réellement une dynamique globale extrême : réservez les valeurs fortes aux
> cibles à fort contraste intrinsèque (noyaux galactiques, cœurs nébulaires saturés).

> **Note** — les couches de détail ne sont **jamais** atténuées par ce process : le bruit fin
> est donc préservé tel quel. Débruitez (`NoiseReduction`, `WaveletDenoise`) avant HDRMT plutôt
> qu'après, pour ne pas amplifier un bruit déjà présent dans les petites échelles.

- Augmentez progressivement `overdrive` par petits pas (0,1–0,2) et jugez sur l'histogramme :
  l'objectif est de gagner en lisibilité des extensions faibles, pas d'aplatir toute structure.
- Sur une image en couleur, HDRMT opère indépendamment sur chaque canal ; en cas de dérive de
  teinte visible, envisagez de l'appliquer sur la luminance seule (`ComponentSeparation` /
  `LRGBCombination`) plutôt que sur RVB directement.
- Pour un besoin voisin mais orienté « fusion multi-expositions », voir `HDRComposition` ; pour
  une compression de dynamique en domaine de gradient (utile en présence de forts gradients de
  fond de ciel), voir `GradientHDRCompression`.

## Voir aussi

- [MultiscaleLinearTransform](retina-doc://MultiscaleLinearTransform) — la même transformée
  starlet, exposée pour agir librement échelle par échelle (biais, seuillage de bruit).
- [MultiscaleAdaptiveStretch](retina-doc://MultiscaleAdaptiveStretch) — variante qui applique
  un étirement adaptatif (plutôt qu'une loi de puissance) à la composante grande échelle.
- [GradientHDRCompression](retina-doc://GradientHDRCompression) — compression de dynamique en
  domaine de gradient, alternative pour les scènes à fort gradient de fond.
- [HDRComposition](retina-doc://HDRComposition) — fusion multi-expositions pour étendre la
  dynamique capturée, en amont plutôt qu'en compression a posteriori.

## Références

- PixInsight — *HDRMultiscaleTransform* tool reference.
- Starck, J.-L. & Murtagh, F. — *Astronomical Image and Data Analysis* (transformée starlet / à trous).
