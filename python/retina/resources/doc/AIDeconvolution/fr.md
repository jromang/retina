---
id: AIDeconvolution
category: Deconvolution
title: Déconvolution IA
brief: Déconvolution par réseau de neurones, objet étendu ou étoiles, sur modèle ONNX local.
keywords: [IA, déconvolution, réseau de neurones, ONNX, netteté, traçabilité]
related: [Deconvolution, AIDenoise, DynamicPSF, StarRemoval]
icon: sparkles
references:
  - "ONNX Runtime — exécution locale de modèles, sans service distant."
---

## Résumé

`AIDeconvolution` restaure la netteté avec un **réseau de neurones** exécuté sur votre machine.
Contrairement à [Deconvolution](retina-doc://Deconvolution), qui inverse explicitement une PSF
mesurée ou paramétrique, le réseau a appris la relation flou → net sur un corpus : il ne demande
aucune PSF, mais il ne rend pas non plus compte de ce qu'il fait.

Le paramètre `target` choisit la famille de modèle : `object` pour les structures étendues
(galaxies, nébuleuses), `stellar` pour resserrer les étoiles. Ce sont deux réseaux distincts —
les appliquer à l'envers donne des résultats médiocres, pas une erreur.

L'image est traitée par **tuiles recouvrantes fondues**, avec progression et annulation par
tuile.

## Il faut d'abord fournir un modèle

Retina **ne livre aucun modèle** : aucun modèle du domaine n'est liable (bucket S3 privé chez
GraXpert, licence propriétaire chez StarNet). Les modèles GraXpert sont par ailleurs sous
**CC BY-NC-SA 4.0** — gratuits, mais d'usage **commercial interdit** ; voir **Aide → Licences**.
**Installez GraXpert et laissez-le télécharger ses modèles : Retina les trouve tout seul**, et
les propose dans `model_id` sous la forme `graxpert-deconv-object-<version>` et
`graxpert-deconv-stellar-<version>`. Rien n'est recopié. Une installation hors emplacement
standard se désigne par `RETINA_GRAXPERT_DIR`, et `model` accepte toujours un chemin direct.

Le catalogue embarqué (`model_id`) porte ces mêmes modèles, ré-hébergés inchangés sur
`huggingface.co/jromanghf/graxpert-models` et téléchargés à la demande, empreinte SHA-256
vérifiée. L'installation locale, si elle existe, prime sur le téléchargement.

## Traçabilité

Le modèle employé est inscrit dans les **paramètres de l'instance** — donc dans l'historique,
l'écho Python, les recettes et le projet `.retina` — et dans les **mots-clés FITS** de la
fenêtre (`AIMODEL`, `AIMODVER`, `AIMODSHA`). Au rejeu, une empreinte qui ne correspond plus
n'interrompt rien mais vous en avertit.

C'est la réponse concrète au reproche fait à ces outils : non pas « faites-nous confiance »,
mais *voici quel fichier, de quelle empreinte, a produit ces pixels*.

## Paramètres

- **`target`** — *enum* `object` | `stellar`, défaut `object`. Famille de modèle.
- **`model`** — *path*. Le fichier `.onnx` à employer.
- **`model_id`** — *str*. Identifiant d'un modèle du catalogue : `graxpert-deconv-object-<version>`
  ou `graxpert-deconv-stellar-<version>`, local (install GraXpert) ou téléchargé depuis le miroir HF.
- **`strength`** — *real*, défaut `1.0`, plage `0`–`1`. Dose l'effet.
- **`tile_size`** — *int*, défaut `256`. **`overlap`** — *int*, défaut `32`.
- **`model_version`**, **`model_sha256`** — *str*, **renseignés à l'exécution**.

## Astuces & pièges

> **Sur données linéaires**, avant étirement — comme la déconvolution classique.

- Un réseau ne conserve pas le flux : contrairement à Richardson-Lucy, rien ne garantit que la
  photométrie de vos étoiles survive. Pour un travail photométrique, préférez
  [Deconvolution](retina-doc://Deconvolution).
- Appliquer un modèle `object` à un champ stellaire dense ne lève pas d'erreur ; cela produit
  simplement un résultat médiocre. Vérifiez `target`.

## Voir aussi

- [Deconvolution](retina-doc://Deconvolution) — Richardson-Lucy régularisé, PSF mesurée ou
  paramétrique, conservation du flux.
- [AIDenoise](retina-doc://AIDenoise) — débruitage par réseau, même mécanique.
- [DynamicPSF](retina-doc://DynamicPSF) — mesure de la PSF, si vous préférez la voie explicite.

## Références

- ONNX Runtime — exécution locale de modèles, sans service distant.
