---
id: SCNR
category: ColorCalibration
title: SCNR (réduction du bruit chromatique soustractif)
brief: Retire la dominante verte (ou d'un autre canal) par protection neutre, sans casser l'équilibre colorimétrique global.
keywords: [SCNR, dominante verte, bande étroite, protection neutre, couleur, canal, calibration couleur]
related: [ColorSaturation, BackgroundNeutralization, ColorCalibration, PhotometricColorCalibration]
icon: color-swatch
references:
  - "PixInsight — SCNR (Subtractive Chromatic Noise Reduction) tool reference."
  - "Rusnak, T. — Subtractive Chromatic Noise Reduction, original PixInsight forum algorithm."
---

## Résumé

`SCNR` (*Subtractive Chromatic Noise Reduction*) corrige une **dominante de couleur excessive
sur un canal**, typiquement le vert produit par des capteurs CMOS/CCD couleur ou par la
combinaison de filtres à bande étroite. Plutôt que de désaturer toute l'image, l'algorithme
**plafonne** le canal ciblé par une référence « neutre » calculée à partir des deux autres
canaux, préservant les étoiles et les teintes naturelles ailleurs dans l'image.

## Cas d'usage

- **Éliminer la dominante verte** typique des capteurs Bayer après démosaïçage ou d'une
  combinaison RVB mal équilibrée.
- **Composer une image bicolore/tricolore en bande étroite** (SHO, HOO) où le canal Hα ou OIII
  déborde en vert sur les nébuleuses.
- **Nettoyer les artefacts de canal** avant `ColorCalibration` ou `PhotometricColorCalibration`,
  pour ne pas fausser la calibration sur une teinte parasite.
- **Neutraliser un flat ou un gradient résiduel** teinté sur un seul canal, en complément de
  `BackgroundNeutralization`.

## Fonctionnement

Pour chaque pixel, l'algorithme calcule une **valeur neutre de référence** à partir des deux
canaux non ciblés (`channel` désigne le canal à traiter, par défaut `G`) :

- `protection = "average"` : la moyenne des deux autres canaux — protection douce, plus proche
  du comportement historique de Photoshop.
- `protection = "maximum"` : le maximum des deux autres canaux — protection plus agressive,
  identique au mode « Maximum Mask » de PixInsight.

Le canal ciblé est ensuite **écrêté** à cette référence neutre partout où il la dépasse (c'est
la composante « soustractive » : on ne peut que réduire le canal, jamais l'augmenter). Le
paramètre `amount` interpole ensuite entre l'image d'origine et cette version corrigée, pour
doser l'effet. Les images avec moins de trois canaux (mono) sont retournées inchangées.

## Mathématiques

Soit un pixel de composantes $(r, g, b) \in [0,1]^3$, et soit $t$ la composante du canal ciblé
(`channel`), $u, v$ les deux autres composantes. On calcule la référence neutre $n$ :

$$
n =
\begin{cases}
\dfrac{u + v}{2} & \text{si } \texttt{protection} = \text{average} \\[6pt]
\max(u, v) & \text{si } \texttt{protection} = \text{maximum}
\end{cases}
$$

La valeur plafonnée (composante « soustractive pure ») est :

$$ t_{\text{cap}} = \min(t, n) $$

et la sortie finale mélange l'original et le plafonnement selon `amount` $\in [0,1]$ :

$$ t' = t + \texttt{amount} \cdot (t_{\text{cap}} - t) = (1-\texttt{amount})\,t + \texttt{amount}\,t_{\text{cap}} $$

Comme $t_{\text{cap}} \le t$ par construction, on a toujours $t' \le t$ : le canal ne peut être
que réduit, jamais amplifié — d'où le nom « soustractif ». Avec `amount = 1`, $t' = \min(t, n)$
(SCNR plein) ; avec `amount = 0`, l'image est inchangée. Les deux autres canaux $u, v$ ne sont
jamais modifiés. Le résultat est enfin écrêté dans $[0,1]$.

## Paramètres

- **`channel`** — *enum*, défaut `G`, choix `R`, `G`, `B`. Canal à corriger. `G` (vert) est de
  loin le cas le plus courant (dominante verte des capteurs couleur), mais `R` ou `B` peuvent
  servir pour d'autres artefacts de canal.
- **`protection`** — *enum*, défaut `average`, choix `average`, `maximum`. Méthode de calcul de
  la référence neutre à partir des deux autres canaux : `average` (protection douce) ou
  `maximum` (protection agressive, écrête davantage).
- **`amount`** — *real*, défaut `1.0`, plage `0`–`1`. Force du mélange entre l'image d'origine
  et la version plafonnée. `1.0` = SCNR plein ; valeurs intermédiaires pour un effet partiel qui
  atténue la dominante sans l'éliminer totalement.

## Astuces & pièges

> **Attention** — sur une image en bande étroite où le canal ciblé porte un vrai signal
> (ex. OIII mappé sur le vert dans une palette non-Hubble), un SCNR à `amount = 1.0` peut
> supprimer des détails réels, pas seulement une dominante. Réduisez `amount` ou travaillez sous
> masque de protection.

- Appliquez `SCNR` **avant** l'étirement (stretch) : sur une image linéaire, la dominante est
  plus facile à corriger proprement qu'après un fort étirement non linéaire.
- `protection = "maximum"` traite plus agressivement les pixels où un seul des deux autres
  canaux est fort (ex. étoiles bleues ou rouges saturées) ; préférez `average` si cela produit
  des halos ou des teintes ternes sur les étoiles.
- Un `amount` autour de `0.5`–`0.8` donne souvent un résultat plus naturel qu'un SCNR plein,
  notamment sur des images couleur classique (RVB) plutôt qu'en bande étroite.

## Voir aussi

- [ColorSaturation](retina-doc://ColorSaturation) — ajustement global de la saturation, pour un
  contrôle complémentaire de la couleur.
- [BackgroundNeutralization](retina-doc://BackgroundNeutralization) — neutralise la teinte du
  fond de ciel plutôt qu'un canal entier.
- [ColorCalibration](retina-doc://ColorCalibration) — calibration colorimétrique globale, à
  appliquer typiquement après SCNR.
- [PhotometricColorCalibration](retina-doc://PhotometricColorCalibration) — calibration couleur
  basée catalogue, sensible aux dominantes résiduelles.

## Références

- PixInsight — *SCNR (Subtractive Chromatic Noise Reduction)* tool reference.
- Rusnak, T. — *Subtractive Chromatic Noise Reduction*, algorithme original du forum PixInsight.
