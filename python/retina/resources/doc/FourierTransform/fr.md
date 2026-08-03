---
id: FourierTransform
category: Fourier
title: Transformée de Fourier
brief: Bascule l'image dans le domaine fréquentiel — spectre d'amplitude pour l'inspection ou représentation complexe réversible.
keywords: [Fourier, FFT, spectre, fréquence, domaine fréquentiel, motifs périodiques, phase]
related: [InverseFourierTransform, Convolution, Deconvolution, MultiscaleLinearTransform]
icon: wave-sine
references:
  - "PixInsight — FourierTransform / InverseFourierTransform tool reference."
  - "numpy.fft — Discrete Fourier Transform (fft2, fftshift)."
  - "Cooley, J. W. & Tukey, J. W. (1965) — An algorithm for the machine calculation of complex Fourier series."
---

## Résumé

`FourierTransform` calcule la **transformée de Fourier discrète 2D** de chaque canal de
l'image, via `numpy.fft`. Deux sorties possibles selon `mode` : un **spectre d'amplitude**
log-normalisé et centré, pensé pour l'**inspection visuelle** (repérage de motifs périodiques,
trames, artefacts de lecture capteur) ; ou une représentation **complexe complète**
(parties réelle et imaginaire empilées comme canaux) qui permet une reconstruction exacte
via `InverseFourierTransform`. C'est l'équivalent du couple FourierTransform /
InverseFourierTransform de PixInsight.

![Image source — FourierTransform](figures/source.webp)
![Spectre d'amplitude — FourierTransform](figures/spectrum.webp)

*La pose, et son spectre d'amplitude. Ce n'est pas un avant/après : le spectre est une autre façon de regarder les mêmes données, où la structure périodique ressort.*

## Cas d'usage

- **Diagnostiquer des motifs périodiques** : bandes de lecture (banding), trames de flat mal
  calibré, moiré d'un filtre, oscillations d'auto-guidage — tous se manifestent par des pics ou
  des raies caractéristiques dans le spectre d'amplitude.
- **Préparer un filtrage fréquentiel** : passer en `mode="complex"`, manipuler manuellement le
  spectre (atténuer une bande, un pic), puis revenir dans le domaine spatial avec
  `InverseFourierTransform` pour un round-trip exact.
- **Analyser la texture du bruit** ou la fonction d'étalement du point (PSF) par examen de la
  décroissance spectrale, en amont d'une `Deconvolution` ou d'une `RestorationFilter`.
- **Pédagogie / vérification** : confirmer qu'un traitement dans le domaine spatial correspond
  bien à l'opération attendue dans le domaine fréquentiel (théorème de convolution).

## Fonctionnement

Pour chaque canal $k$ de l'image, l'opérateur calcule la FFT 2D via `numpy.fft.fft2`, puis
recentre les basses fréquences au milieu du spectre avec `numpy.fft.fftshift` (sans ce
recentrage, la fréquence nulle se trouverait dans le coin supérieur gauche, peu lisible).

- En mode `magnitude` : on prend le module du spectre complexe, on applique un `log1p` (pour
  compresser l'énorme dynamique entre la composante continue et les hautes fréquences), puis on
  normalise par le maximum du canal pour ramener le résultat dans `[0, 1]`, directement affichable.
- En mode `complex` : on conserve séparément partie réelle et partie imaginaire du spectre
  fftshifté, empilées canal par canal pour former une image à `2·C` canaux : `[re₀…re_{C-1},
  im₀…im_{C-1}]`. Aucune information n'est perdue — `InverseFourierTransform` défait exactement
  ce montage (`ifftshift` puis `ifft2`, partie réelle du résultat) pour retrouver l'image
  spatiale d'origine au bruit d'arrondi flottant près.

## Mathématiques

Pour un canal image $I(x, y)$ de taille $H \times W$, la transformée de Fourier discrète 2D est :

$$ F(u, v) = \sum_{x=0}^{H-1} \sum_{y=0}^{W-1} I(x, y)\, e^{-2i\pi \left(\frac{ux}{H} + \frac{vy}{W}\right)} $$

$F(u, v)$ est en général **complexe** : $F = \Re(F) + i\,\Im(F)$. Le spectre d'amplitude affiché
en mode `magnitude` est :

$$ M(u, v) = \frac{\log\!\big(1 + |F(u, v)|\big)}{\max_{u,v} \log\!\big(1 + |F(u, v)|\big)}, \qquad
   |F(u, v)| = \sqrt{\Re(F)^2 + \Im(F)^2}. $$

Le `log1p` compresse la dynamique : la composante continue $F(0,0)$ (proportionnelle à la
moyenne des pixels) domine typiquement de plusieurs ordres de grandeur les fréquences élevées,
et resterait invisible sans compression logarithmique.

En mode `complex`, l'image produite encode intégralement $\Re(F)$ et $\Im(F)$ (après
`fftshift`), ce qui permet la reconstruction exacte par transformée inverse :

$$ I(x, y) = \frac{1}{HW} \sum_{u=0}^{H-1} \sum_{v=0}^{W-1} F(u, v)\, e^{+2i\pi \left(\frac{ux}{H} + \frac{vy}{W}\right)}. $$

`InverseFourierTransform` recompose $F = \Re(F) + i\,\Im(F)$, applique `ifftshift` (annule le
recentrage), puis `ifft2`, et ne conserve que la partie réelle du résultat (théoriquement nulle
côté imaginaire pour une image d'origine réelle, aux erreurs d'arrondi près).

## Paramètres

- **`mode`** — *enum*, défaut `magnitude`, choix `magnitude` / `complex`. Sélectionne la sortie :
  `magnitude` produit un spectre d'amplitude log-normalisé dans `[0,1]`, borné, destiné à
  l'inspection visuelle (même nombre de canaux que l'entrée). `complex` produit une image à
  `2·C` canaux (réel puis imaginaire, non bornée) destinée à un traitement fréquentiel suivi
  d'une reconstruction via `InverseFourierTransform`.

## Astuces & pièges

> **Attention** — le mode `complex` produit une image aux valeurs **non bornées** (amplitudes du
> spectre, potentiellement très grandes ou négatives). Ne l'affichez pas directement comme une
> image normale et ne l'enregistrez pas comme résultat final : c'est un format d'échange
> intermédiaire destiné à `InverseFourierTransform`.

> **Note** — le spectre d'amplitude en mode `magnitude` est **irréversible** : la phase (portée
> par le rapport partie réelle / partie imaginaire) est perdue, or c'est elle qui contient
> l'essentiel de l'information structurelle de l'image. N'utilisez `magnitude` que pour
> l'inspection, jamais pour retrouver l'image d'origine.

- Les motifs périodiques (banding, moiré) apparaissent comme des **pics ou raies isolés**
  hors du lobe central du spectre — repérez-les en zoomant sur le spectre affiché.
- La composante continue (fréquence nulle) est toujours au **centre exact** de l'image après
  `fftshift` : c'est le point le plus lumineux du spectre, sans intérêt diagnostique en soi.
- Pour un filtrage fréquentiel manuel (atténuer une bande), travaillez sur la sortie `complex`
  avec `PixelMath` ou en console avant de repasser par `InverseFourierTransform`.

## Voir aussi

- [InverseFourierTransform](retina-doc://InverseFourierTransform) — reconstruction exacte depuis la sortie `complex`.
- [Convolution](retina-doc://Convolution) — opération spatiale équivalente à une multiplication fréquentielle.
- [Deconvolution](retina-doc://Deconvolution) — restauration s'appuyant sur le domaine fréquentiel.
- [MultiscaleLinearTransform](retina-doc://MultiscaleLinearTransform) — décomposition en échelles, alternative au filtrage de Fourier.

## Références

- PixInsight — *FourierTransform* / *InverseFourierTransform* tool reference.
- numpy.fft — *Discrete Fourier Transform* (`fft2`, `fftshift`).
- Cooley, J. W. & Tukey, J. W. (1965) — *An algorithm for the machine calculation of complex Fourier series*.
