---
id: B3Estimator
category: ColorCalibration
title: Estimateur B3 — soustraction de continuum
brief: Isole le signal de raie d'émission (p. ex. Hα) en soustrayant un continuum large bande mis à l'échelle par un facteur k estimé robustement.
keywords: [Hα, continuum, narrowband, soustraction, raie d'émission, sigma-clipping, nébuleuse]
related: [PixelMath, LinearFit, StarAlignment, ChannelCombination]
icon: database
references:
  - "PixInsight — B3Estimator process reference (continuum subtraction)."
  - "astropy.stats.sigma_clipped_stats — estimation robuste centre/échelle par sigma-clipping itératif."
---

## Résumé

`B3Estimator` reproduit l'idée du `B3Estimator` de PixInsight : combiner deux images du même
champ — une **bande étroite** (p. ex. Hα) et une **bande large de référence** (« continuum »,
p. ex. le rouge ou une luminance) — pour **isoler le signal de raie**. Le continuum, mis à
l'échelle par un facteur `k`, est soustrait de la bande étroite : les étoiles et le fond
« s'annulent », ne laissant que l'excès d'émission propre à la raie. `k` peut être fixé
manuellement ou estimé automatiquement par un ratio médian robuste (sigma-clippé) sur les
zones brillantes du continuum.

## Cas d'usage

- **Isoler l'émission Hα pure** d'une image narrowband en la comparant à un filtre continuum
  voisin, pour produire une carte de raie sans la contribution stellaire large bande.
- **Renforcer le piqué nébulaire** : les étoiles, dominées par le continuum, disparaissent
  presque entièrement après soustraction, ne laissant que la nébulosité émissive.
- **Préparer une couche « boost Hα »** à réinjecter dans le canal rouge d'une image LRGB via
  `PixelMath`, pour un rendu type HOO/SHO/HaRGB.
- **Calibrer manuellement `factor`** quand l'estimation automatique échoue (champ pauvre en
  étoiles, saturation, filtre continuum inadapté).

## Fonctionnement

Le process s'applique à la **vue active** (la bande étroite) et référence une seconde vue par
son nom via le paramètre `continuum`. Les deux images sont d'abord réduites à une intensité
monochrome (moyenne des canaux si l'image est couleur). Le continuum est ensuite analysé par
sigma-clipping pour repérer ses pixels brillants (étoiles + fond structuré), qui servent
d'ancrage pour estimer le rapport d'échelle `k` entre les deux bandes — sauf si `factor` est
fixé explicitement (`> 0`), auquel cas ce `k` fourni est utilisé tel quel. Le continuum mis à
l'échelle est alors soustrait de la bande étroite, un piédestal est ajouté pour éviter un fond
négatif, et le résultat est écrêté dans `[0, 1]`.

> **Note** — si `continuum` est vide, ne correspond à aucune vue existante, ou a des dimensions
> différentes de la vue active, le process est un **no-op silencieux** : il renvoie une copie
> inchangée des pixels, sans erreur. Vérifiez le nom exact de la vue continuum.

Le facteur `k` effectivement utilisé (fourni ou estimé) est mémorisé dans l'attribut `.k` de
l'instance après exécution — utile en script pour l'inspecter ou le réutiliser sur une autre vue.

## Mathématiques

Soit $N(x,y)$ l'intensité de la bande étroite (vue active, moyennée sur les canaux si couleur)
et $C(x,y)$ celle du continuum (`continuum`), échantillonnées sur la même grille de pixels. Si
`factor` = 0 (mode auto), on calcule d'abord la statistique robuste du continuum par
sigma-clipping itératif ($\sigma = 3$) :

$$ \tilde C = \operatorname{med}_\sigma(C), \qquad \sigma_C = \operatorname{std}_\sigma(C) $$

Le masque des pixels « de référence » — essentiellement les étoiles et le continuum brillant —
est défini par :

$$ M = \{(x,y) \;:\; C(x,y) > \tilde C + \sigma_C\} $$

Sur ce masque, on calcule le rapport pixel à pixel $r(x,y) = N(x,y) / \max(C(x,y),\, 10^{-6})$,
et le facteur d'échelle retenu est sa **médiane** :

$$ k = \operatorname{med}_{(x,y)\in M}\; r(x,y) $$

L'hypothèse sous-jacente est que ces pixels brillants correspondent majoritairement à des
étoiles dont le flux dans la bande étroite et dans le continuum est proportionnel avec le même
rapport `k` — leur soustraction doit donc s'annuler. Si `factor` > 0, cette estimation est
court-circuitée et $k = \texttt{factor}$ directement.

Le résultat final est :

$$ E(x,y) = \operatorname{clip}\big(N(x,y) - k\,C(x,y) + p,\; 0,\; 1\big), \qquad p = \texttt{pedestal} $$

Si l'image d'entrée possède plusieurs canaux, $E$ (monochrome) est **répliqué à l'identique**
sur chacun d'eux.

## Paramètres

- **`continuum`** — *str*, défaut `""`. Nom de la vue continuum (bande large) à soustraire de la
  vue active. Doit référencer une vue existante de mêmes dimensions ; sinon le process ne fait
  rien (voir note ci-dessus).
- **`factor`** — *real*, défaut `0.0`, plage `0`–`100`. Facteur d'échelle `k` appliqué au
  continuum avant soustraction. `0` déclenche l'estimation automatique par ratio médian
  sigma-clippé ; toute valeur `> 0` fixe `k` manuellement et désactive l'estimation.
- **`pedestal`** — *real*, défaut `0.05`, plage `0`–`1`. Décalage additif appliqué après
  soustraction, pour éviter que le fond (où $N \approx k\,C$) ne tombe à zéro ou en négatif et
  soit écrêté.

## Astuces & pièges

> **Attention** — les deux vues doivent être **parfaitement alignées pixel à pixel** (mêmes
> dimensions, même échantillonnage). `B3Estimator` ne recale rien : passez par
> `StarAlignment` en amont si les images proviennent de poses/instruments différents.

- Le résultat est **monochrome** (moyenne des canaux), répliqué sur tous les canaux de sortie
  même si l'image d'entrée était en couleur : l'information colorimétrique d'origine est perdue
  sur cette vue.
- L'estimation automatique de `k` suppose un champ suffisamment riche en étoiles pour ancrer le
  ratio. Sur un champ dominé par une grande galaxie ou une nébuleuse étendue (peu d'étoiles
  isolées dans le masque), le ratio auto peut être biaisé — fixez `factor` manuellement après
  une première estimation visuelle.
- Travaillez toujours sur des données **linéaires** (avant tout étirement) : la relation
  proportionnelle entre bandes suppose une réponse linéaire du capteur.
- Le process est maskable : appliquez un masque d'étoiles ou de région pour protéger certaines
  zones de la soustraction si besoin.

## Voir aussi

- [PixelMath](retina-doc://PixelMath) — combinaison libre des canaux/vues, alternative générale
  à une soustraction de continuum fixe.
- [LinearFit](retina-doc://LinearFit) — ajustement linéaire d'une vue sur une référence,
  principe voisin de l'estimation de `k`.
- [StarAlignment](retina-doc://StarAlignment) — recalage préalable indispensable si les deux
  bandes ne sont pas déjà pixel-alignées.
- [ChannelCombination](retina-doc://ChannelCombination) — recombiner la raie isolée dans une
  composition couleur (HOO, SHO, HaRGB…).

## Références

- PixInsight — *B3Estimator* process reference (continuum subtraction).
- astropy.stats — *sigma_clipped_stats*, estimation robuste centre/échelle par sigma-clipping
  itératif.
