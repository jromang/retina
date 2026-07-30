---
id: FastNLMeansDenoise
category: NoiseReduction
title: Débruitage Non-Local Means rapide
brief: Débruitage Non-Local Means accéléré (OpenCV, pipeline 8 bits) pour les grands champs.
keywords: [débruitage, non-local means, OpenCV, bruit, patch, grand champ]
related: [NonLocalMeansDenoise, TGVDenoise, WaveletDenoise, NoiseReduction]
icon: sparkles
references:
  - "Buades, A., Coll, B., Morel, J.-M. — A non-local algorithm for image denoising (CVPR 2005)."
  - "OpenCV — cv2.fastNlMeansDenoising / fastNlMeansDenoisingColored documentation."
---

## Résumé

`FastNLMeansDenoise` applique l'algorithme **Non-Local Means** via l'implémentation optimisée
d'OpenCV (`cv2.fastNlMeansDenoising`). Comme `NonLocalMeansDenoise`, il moyenne chaque pixel avec
les pixels d'autres régions de l'image dont le voisinage (« patch ») est similaire — un débruitage
qui respecte mieux les structures fines que le flou gaussien. La version OpenCV troque un peu de
précision (traitement en 8 bits) contre une **vitesse nettement supérieure**, ce qui la rend
adaptée aux images de grand champ où la version scikit-image devient trop lente.

## Cas d'usage

- **Débruiter rapidement une mosaïque ou un champ large** où `NonLocalMeansDenoise` (scikit-image,
  en float) serait trop coûteux en temps de calcul.
- **Aperçu rapide** de l'effet d'un Non-Local Means avant un passage plus fin et plus lent.
- **Lisser le bruit de fond** d'une image déjà étirée sans écraser les étoiles faibles ni les
  détails de nébulosité, grâce à la nature non locale du filtre.
- **Traitement par lots** de nombreuses sous-images (mosaïque, tuiles) où le temps d'exécution
  cumulé compte.

## Fonctionnement

Le process convertit d'abord chaque canal de l'image linéaire `[0, 1]` en entiers 8 bits
`[0, 255]` (quantification, avec écrêtage), car `cv2.fastNlMeansDenoising` n'opère que sur des
images entières non signées. Pour chaque canal :

1. Un **patch de référence** de côté `template_size` est centré sur le pixel à débruiter.
2. L'algorithme le compare aux patchs de même taille centrés sur tous les pixels d'une **fenêtre
   de recherche** de côté `search_size` autour de lui (au lieu de toute l'image, pour rester
   praticable).
3. Chaque pixel candidat reçoit un **poids** décroissant avec la dissimilarité de son patch au
   patch de référence, contrôlée par la force `strength` (le paramètre *h* d'OpenCV).
4. Le pixel de sortie est la **moyenne pondérée** de tous les pixels candidats.

Le résultat 8 bits est ensuite reconverti en float32 `[0, 1]`. Les tailles de patch/fenêtre
impaires sont imposées en interne (`| 1`) car OpenCV l'exige. Contrairement à
`NonLocalMeansDenoise`, il n'y a pas d'estimation automatique du bruit par canal : `strength`
est un réglage manuel absolu.

## Mathématiques

Soit $I$ l'image quantifiée sur 8 bits et $p$ un pixel à débruiter. Pour tout pixel candidat $q$
dans la fenêtre de recherche $\Omega(p)$ (de côté `search_size`), on compare les patchs de côté
`template_size` centrés en $p$ et $q$ via une distance quadratique :

$$ d(p, q) = \sum_{k \in \mathcal{N}} \big( I(p+k) - I(q+k) \big)^2 $$

où $\mathcal{N}$ parcourt les décalages du patch. Le poids attribué à $q$ décroît
exponentiellement avec cette distance, normalisée par le paramètre de force $h$ = `strength` :

$$ w(p, q) = \exp\!\left( -\frac{\max(d(p,q) - 2\sigma^2,\, 0)}{h^2} \right) $$

et le pixel restauré est la moyenne pondérée normalisée :

$$ \hat{I}(p) = \frac{1}{Z(p)} \sum_{q \in \Omega(p)} w(p, q)\, I(q),
   \qquad Z(p) = \sum_{q \in \Omega(p)} w(p, q). $$

Un $h$ petit préserve les détails mais laisse passer plus de bruit résiduel ; un $h$ grand lisse
fortement au risque d'aplatir la texture et les étoiles les plus faibles. OpenCV implémente cette
somme efficacement (image intégrale des différences de patchs), d'où le gain de vitesse par
rapport à une implémentation naïve.

## Paramètres

- **`strength`** — *real*, défaut `3.0`, plage `0.1`–`50.0`. Force du filtrage (paramètre *h*
  d'OpenCV). Plus la valeur est élevée, plus le bruit est éliminé, mais au prix d'un lissage
  croissant des détails fins.
- **`template_size`** — *int*, défaut `7`, plage `3`–`21`. Taille (en pixels) du patch comparé
  autour de chaque pixel. Un patch plus grand moyenne des zones plus étendues, plus robuste au
  bruit mais moins sensible aux petites structures.
- **`search_size`** — *int*, défaut `21`, plage `5`–`51`. Taille de la fenêtre dans laquelle sont
  cherchés les patchs similaires. Une fenêtre plus grande trouve de meilleures correspondances
  mais augmente sensiblement le temps de calcul.

## Astuces & pièges

> **Attention** — la quantification interne en 8 bits limite la précision : sur une image très
> peu bruitée ou à très faible dynamique, ce process peut introduire un **banding** visible que
> `NonLocalMeansDenoise` (traitement en float) évite.

> **Note** — `template_size` et `search_size` sont forcés à des valeurs impaires en interne ; une
> valeur paire saisie sera silencieusement incrémentée de 1.

- Commencez avec une `strength` modérée (2–4) et augmentez progressivement en surveillant la
  perte de détail sur les étoiles faibles et les structures fines de nébulosité.
- Pour un débruitage plus fidèle sur une image de taille raisonnable, `NonLocalMeansDenoise`
  (scikit-image) offre un contrôle plus fin (force relative au bruit estimé par canal) au prix
  d'un temps de calcul plus long.
- Travailler sous **masque** (étoiles ou fond de ciel) permet de concentrer le débruitage là où
  il est utile sans affecter les zones à fort signal.

## Voir aussi

- [NonLocalMeansDenoise](retina-doc://NonLocalMeansDenoise) — variante scikit-image en float,
  plus précise mais plus lente.
- [TGVDenoise](retina-doc://TGVDenoise) — débruitage par variation totale généralisée.
- [WaveletDenoise](retina-doc://WaveletDenoise) — débruitage multi-échelle par ondelettes.
- [NoiseReduction](retina-doc://NoiseReduction) — boîte à outils de débruitage générique.

## Références

- Buades, A., Coll, B., Morel, J.-M. — *A non-local algorithm for image denoising* (CVPR 2005).
- OpenCV — *cv2.fastNlMeansDenoising* / *fastNlMeansDenoisingColored* documentation.
