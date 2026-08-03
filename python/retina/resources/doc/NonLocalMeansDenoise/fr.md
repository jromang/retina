---
id: NonLocalMeansDenoise
category: NoiseReduction
title: Débruitage Non-Local Means
brief: Débruitage par moyennage de patches similaires (skimage) — préserve étoiles faibles et texture fine.
keywords: [débruitage, non-local means, patch, bruit, skimage, texture, étoiles faibles]
related: [FastNLMeansDenoise, TGVDenoise, NoiseReduction, WaveletDenoise]
icon: sparkles
references:
  - "Buades, A., Coll, B., Morel, J.-M. — A non-local algorithm for image denoising (2005)."
  - "scikit-image — skimage.restoration.denoise_nl_means / estimate_sigma."
---

## Résumé

`NonLocalMeansDenoise` réduit le bruit en remplaçant chaque pixel par une **moyenne pondérée
de pixels similaires**, cherchés dans tout un voisinage plutôt que dans un simple filtre de
convolution local. La similarité se mesure entre **patches** (petites fenêtres autour de
chaque pixel) : deux pixels dont les patches se ressemblent — qu'ils soient contigus ou non —
contribuent fortement l'un à l'autre. Ce principe « non local » permet de lisser le bruit de
fond tout en respectant les structures répétitives et **ponctuelles**, en particulier les
étoiles faibles, que les filtres classiques (gaussien, médian) tendent à écraser.

![Avant — NonLocalMeansDenoise](figures/before.webp)
![Après — NonLocalMeansDenoise](figures/after.webp)

*Avant, et après moyennes non locales par patchs, sur un recadrage à l'échelle du pixel.*

## Cas d'usage

- **Débruiter le fond de ciel** d'une image empilée sans éroder les étoiles faibles ni le
  piqué des nébulosités fines.
- **Nettoyer un signal bruité** avant un étirement agressif, qui amplifierait sinon le bruit
  résiduel en artefacts visibles.
- **Préserver la texture** (poussières sombres, filaments) là où un flou gaussien ou un filtre
  médian lisserait indistinctement bruit et détail.
- Alternative plus fidèle mais plus lente à [FastNLMeansDenoise](retina-doc://FastNLMeansDenoise)
  quand le temps de calcul n'est pas contraint.

## Fonctionnement

Le process délègue à `skimage.restoration.denoise_nl_means`, appliqué **indépendamment sur
chaque canal** :

1. Le canal est écrêté dans `[0, 1]`.
2. L'écart-type du bruit `sigma` est estimé automatiquement par `estimate_sigma` (estimateur
   robuste basé sur la texture haute fréquence de l'image).
3. Pour chaque pixel, l'algorithme compare son **patch** (fenêtre `patch_size × patch_size`)
   à tous les patches situés dans une **fenêtre de recherche** de rayon `patch_distance`
   autour de lui, et calcule une moyenne pondérée par la ressemblance des patches (mode
   `fast_mode=True`, qui accélère le calcul des distances via une formulation intégrale).
4. La force du filtrage `h` est **mise à l'échelle du bruit estimé** (`h × sigma`) : le même
   réglage produit un effet cohérent quel que soit le niveau de bruit du canal.
5. Le résultat est ré-écrêté dans `[0, 1]` et reconverti en `float32`.

Comme le calcul du sigma et le filtrage sont faits canal par canal, un canal plus bruité
(souvent le bleu) est débruité plus fort qu'un canal propre, sans que l'utilisateur ait à
régler chaque canal séparément.

## Mathématiques

Pour un pixel $p$, la valeur filtrée $\mathrm{NL}[I](p)$ est une moyenne pondérée de tous les
pixels $q$ de la fenêtre de recherche $\Omega(p)$ :

$$ \mathrm{NL}[I](p) = \frac{1}{Z(p)} \sum_{q \in \Omega(p)} w(p, q)\, I(q), \qquad
   Z(p) = \sum_{q \in \Omega(p)} w(p, q). $$

Le poids $w(p, q)$ dépend de la distance entre les **patches** $N(p)$ et $N(q)$ (fenêtres de
taille `patch_size` centrées en $p$ et $q$), pondérée par un noyau gaussien $\mathcal{G}_a$ qui
privilégie les pixels proches du centre du patch :

$$ w(p, q) = \exp\!\left(- \frac{\lVert I(N(p)) - I(N(q)) \rVert^2_{2,\mathcal{G}_a}}{h_\text{eff}^2}\right), $$

où $h_\text{eff} = h \times \sigma$ contrôle la tolérance à la différence entre patches : plus
$h_\text{eff}$ est grand, plus des patches dissemblables sont autorisés à contribuer, donc plus
le lissage est fort (au risque de brouiller les détails fins). Le paramètre $\sigma$ (bruit
estimé) recentre ce réglage sur l'échelle réelle du bruit du canal, de sorte que `h` reste un
multiplicateur sans dimension. La fenêtre de recherche $\Omega(p)$ est limitée à un rayon
`patch_distance` autour de $p$ (au lieu de l'image entière) pour rendre le calcul tractable.

## Paramètres

- **`h`** — *real*, défaut `1.0`, plage `0.1`–`10.0`. Force du filtrage, exprimée en multiple de
  l'écart-type de bruit estimé par canal (σ). Plus `h` est élevé, plus le lissage est fort mais
  plus le risque d'effacer des détails fins ou des étoiles faibles augmente.
- **`patch_size`** — *int*, défaut `5`, plage `3`–`15`. Taille (en pixels) des patches comparés
  entre eux. Un patch plus grand rend la comparaison plus robuste au bruit mais moins sensible
  aux petites structures.
- **`patch_distance`** — *int*, défaut `6`, plage `1`–`30`. Rayon de la fenêtre de recherche
  autour de chaque pixel. Plus grand = plus de candidats similaires trouvés (meilleur lissage)
  mais coût de calcul fortement croissant.

## Astuces & pièges

> **Attention** — le coût de calcul augmente rapidement avec `patch_distance` (fenêtre de
> recherche) : doubler ce paramètre peut multiplier le temps de traitement par un facteur
> proche de 4. Sur de grands champs, préférez d'abord [FastNLMeansDenoise](retina-doc://FastNLMeansDenoise)
> ou réduisez `patch_distance`.

- Commencez avec `h` proche de `1.0` : au-delà de `2`–`3`, le lissage devient visible sur les
  structures fines et les étoiles faibles peuvent perdre en netteté.
- Appliqué sous **masque** (fond de ciel uniquement, étoiles protégées), le débruitage peut être
  poussé plus fort sans dégrader les objets ponctuels.
- Puisque `sigma` est estimé par canal, un canal déjà propre (souvent le canal luminance après
  combinaison LRVB) ne sera presque pas affecté même avec un `h` élevé.

## Voir aussi

- [FastNLMeansDenoise](retina-doc://FastNLMeansDenoise) — variante OpenCV, beaucoup plus rapide, en 8 bits.
- [TGVDenoise](retina-doc://TGVDenoise) — débruitage par variation totale généralisée, plus proche de PixInsight.
- [NoiseReduction](retina-doc://NoiseReduction) — filtres de débruitage génériques (ondelettes, TV).
- [WaveletDenoise](retina-doc://WaveletDenoise) — débruitage multi-échelle par ondelettes.

## Références

- Buades, A., Coll, B., Morel, J.-M. — *A non-local algorithm for image denoising* (2005).
- scikit-image — *skimage.restoration.denoise_nl_means* / *estimate_sigma*.
