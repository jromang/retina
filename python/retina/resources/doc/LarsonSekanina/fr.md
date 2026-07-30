---
id: LarsonSekanina
category: Convolution
title: Filtre de Larson-Sekanina
brief: "Filtre de gradient rotationnel I − ½·(rot(+α) + rot(−α)) autour d'un centre, pour révéler les jets cométaires."
keywords: [comète, jets, gradient rotationnel, chevelure, asymétrie, rehaussement, coma]
related: [CometAlignment, RadialProfileMeasurement, RickerWaveletEnhance, UnsharpMask]
icon: windmill
references:
  - "Larson, S. M. & Sekanina, Z. (1984) — Coma morphology and dust-emission pattern of periodic comet Halley. Astronomical Journal, 89, 571."
  - "PixInsight — LarsonSekanina tool reference."
  - "scikit-image — skimage.transform.rotate."
---

## Résumé

`LarsonSekanina` est le **filtre de gradient rotationnel** classique de l'imagerie cométaire :
il fait apparaître les **jets et structures asymétriques** de la chevelure d'une comète en
retirant, à chaque pixel, la **composante à symétrie centrale** du signal. Concrètement,
l'image est comparée à la moyenne de deux copies d'elle-même tournées de `+angle` et `-angle`
degrés autour d'un centre (par défaut le centre géométrique de l'image, en pratique le
noyau/photocentre de la comète). Tout ce qui est **invariant par rotation** — la coma diffuse,
à peu près symétrique — s'annule dans la soustraction ; ce qui **dépend de l'angle** — jets,
éventails, structures en spirale — ressort en clair-obscur.

## Cas d'usage

- **Révéler les jets de poussière/gaz** d'une comète, invisibles dans l'image brute car noyés
  dans la brillance de la coma qui décroît fortement vers le noyau.
- **Étudier la rotation du noyau** : des jets en spirale et leur évolution image après image
  renseignent sur la période de rotation et l'activité du noyau.
- **Comparer plusieurs pas d'angle** (`angle` petit vs grand) pour séparer structures fines
  proches du noyau et structures larges dans la coma externe.
- Utilisation typique en aval de `CometAlignment` (empilement centré sur le noyau) et d'un
  centrage précis du photocentre avant filtrage.

## Fonctionnement

1. Le centre de rotation est fixé par `cx`/`cy`, ou par défaut au centre géométrique de l'image
   (`(w-1)/2, (h-1)/2`) — en pratique, il faut le placer sur le **photocentre du noyau**.
2. Pour chaque canal, l'image est tournée deux fois autour de ce centre avec
   `skimage.transform.rotate` (interpolation bilinéaire, bord en mode `edge`) : une fois de
   `+angle` degrés, une fois de `-angle` degrés.
3. La moyenne des deux rotations donne une estimation de la **composante symétrique locale**
   du signal autour du centre (ce qu'on verrait si la coma tournait sans changer de forme).
4. Cette moyenne est soustraite de l'image d'origine : le résultat est nul là où le signal est
   localement symétrique par rotation, et non nul là où une structure brise cette symétrie
   (jet, éventail, condensation).
5. Le résultat, centré sur 0 en théorie, est **recentré autour de 0,5** puis écrêté à `[0, 1]`
   pour rester affichable comme une image classique (les zones sans structure apparaissent en
   gris moyen, les jets en clair ou en sombre selon le sens du gradient).

## Mathématiques

Soit $I(x, y)$ l'image d'un canal et $R_\theta$ l'opérateur de rotation d'angle $\theta$ autour
du centre $(c_x, c_y)$ (interpolation bilinéaire). Le filtre calcule :

$$ G(x, y) = I(x, y) \;-\; \frac{1}{2}\Big( R_{+\alpha}[I](x, y) + R_{-\alpha}[I](x, y) \Big) $$

où $\alpha$ est le paramètre `angle`. Le terme $\tfrac{1}{2}\big(R_{+\alpha}[I] + R_{-\alpha}[I]\big)$
est une estimation locale de la partie de $I$ **invariante par rotation d'angle $\pm\alpha$** :
si $I$ est parfaitement à symétrie de révolution autour du centre, alors
$R_{+\alpha}[I] = R_{-\alpha}[I] = I$ et $G \equiv 0$. À l'inverse, une structure localisée à
une distance radiale $r$ du centre et à un angle azimutal donné se retrouve décalée
angulairement dans $R_{\pm\alpha}[I]$ ; la soustraction fait apparaître un **doublet
signé** (bord positif d'un côté, négatif de l'autre) dont l'amplitude croît avec le gradient
azimutal local de $I$ et avec $\alpha$ pour de petits angles.

L'image affichée est finalement :

$$ I'(x, y) = \operatorname{clip}\big(G(x, y) + 0{,}5,\; 0,\; 1\big) $$

Le décalage de $0{,}5$ recentre le zéro (absence de structure) sur le gris moyen, permettant de
lire aussi bien les excès (jets, plus clairs) que les déficits (ombres, plus sombres) autour du
photocentre.

## Paramètres

- **`angle`** — *real*, défaut `5.0`, plage `0.1`–`45`. Angle rotationnel `α` en degrés utilisé
  pour les deux rotations `+α`/`-α`. Petit angle → sensible aux structures fines proches du
  centre ; grand angle → révèle des structures plus larges mais atténue les détails fins et
  peut introduire des artefacts d'interpolation sur les bords.
- **`cx`** — *real*, défaut `-1.0`, plage `-1`–`1 000 000`. Coordonnée X du centre de rotation
  en pixels. La valeur spéciale `-1` signifie « milieu de l'image » (`(largeur-1)/2`).
- **`cy`** — *real*, défaut `-1.0`, plage `-1`–`1 000 000`. Coordonnée Y du centre de rotation
  en pixels. La valeur spéciale `-1` signifie « milieu de l'image » (`(hauteur-1)/2`).

## Astuces & pièges

> **Attention** — le résultat dépend **fortement** de la précision du centre `(cx, cy)`. Un
> centre décalé de quelques pixels par rapport au photocentre réel du noyau introduit un
> gradient parasite qui masque les vrais jets. Mesurez le centroïde du noyau (par exemple avec
> `RadialProfileMeasurement` ou une détection de source) avant d'appliquer le filtre.

> **Note** — l'image de sortie n'est **pas** une image photométrique : elle sert au
> diagnostic visuel des structures morphologiques, pas à la mesure de flux.

- Travaillez de préférence sur une image déjà étirée (STF ou `HistogramTransformation`) et
  centrée sur la coma, sinon les artefacts de rotation aux bords dominent le résultat.
- Essayez plusieurs valeurs d'`angle` (par exemple 5°, 15°, 30°) : les structures fines et les
  structures larges n'apparaissent pas au même angle.
- Sur une comète mal centrée dans le cadre, recadrez d'abord (`Crop`/`DynamicCrop`) pour que le
  centre par défaut (`cx = cy = -1`) coïncide approximativement avec le noyau, ou renseignez
  `cx`/`cy` explicitement.
- Le filtre est appliqué canal par canal ; sur une image couleur, envisagez de travailler sur
  une version en niveaux de gris (luminance) pour éviter les artefacts chromatiques aux bords
  des jets.

## Voir aussi

- [CometAlignment](retina-doc://CometAlignment) — empilement centré sur le noyau cométaire, en
  amont pour obtenir une chevelure nette avant filtrage.
- [RadialProfileMeasurement](retina-doc://RadialProfileMeasurement) — mesure du profil radial,
  utile pour localiser précisément le photocentre.
- [RickerWaveletEnhance](retina-doc://RickerWaveletEnhance) — rehaussement multi-échelle
  d'ondelette, complémentaire pour faire ressortir des structures fines.
- [UnsharpMask](retina-doc://UnsharpMask) — rehaussement de contraste local par masque flou,
  autre technique de mise en évidence de structures fines.

## Références

- Larson, S. M. & Sekanina, Z. (1984) — *Coma morphology and dust-emission pattern of periodic
  comet Halley*. Astronomical Journal, 89, 571.
- PixInsight — *LarsonSekanina* tool reference.
- scikit-image — *skimage.transform.rotate*.
