---
id: AIDenoise
category: NoiseReduction
title: Débruitage IA
brief: Débruitage par réseau de neurones, sur un modèle ONNX exécuté localement.
keywords: [IA, débruitage, réseau de neurones, ONNX, GraXpert, traçabilité]
related: [NoiseReduction, AIDeconvolution, StarRemoval, TGVDenoise]
icon: wand
references:
  - "ONNX Runtime — exécution locale de modèles, sans service distant."
---

## Résumé

`AIDenoise` débruite l'image avec un **réseau de neurones** exécuté sur votre machine. Rien
n'est envoyé nulle part : le modèle est un fichier `.onnx` local, lu par onnxruntime.

L'image est traitée par **tuiles recouvrantes fondues**, ce qui permet de débruiter une pose de
50 Mpx sans la charger d'un bloc dans le réseau. Chaque tuile rapporte sa progression et
constitue un point d'annulation.

## Il faut d'abord fournir un modèle

Retina **ne livre aucun modèle**, et ce n'est pas un oubli. Aucun modèle du domaine n'est
liable : GraXpert sert les siens depuis un bucket S3 privé, dont les identifiants sont
embarqués dans son paquet, et la licence de StarNet n'autorise ni la redistribution ni le lien
direct. Inscrire dans Retina des URL invérifiables aurait produit la panne qu'on ne diagnostique
pas — un téléchargement qui échoue chez vous, six mois plus tard.

> **Les modèles GraXpert sont sous CC BY-NC-SA 4.0** — distincte de la GPL-3 de leur code.
> Gratuits et partageables, mais l'usage **commercial** en est interdit. Retina, lui, ne
> restreint rien : si vous vendez des tirages ou travaillez sur commande, cette restriction est
> entre vous et GraXpert. Le panneau **Aide → Licences** la rappelle.

**En pratique, installez GraXpert et laissez-le télécharger ses modèles : Retina les trouve
tout seul.** Ses dossiers de données sont inspectés à chaque ouverture du panneau, et les
modèles y apparaissent dans `model_id` sous la forme `graxpert-denoise-<version>`. Rien n'est
recopié — le fichier est employé là où il est, ce qui évite de dupliquer des centaines de
mégaoctets et de faire diverger les deux copies à la prochaine mise à jour.

Si votre installation n'est pas à l'emplacement standard (version portable, dossier partagé),
la variable d'environnement `RETINA_GRAXPERT_DIR` la désigne. Et `model` accepte toujours un
chemin direct vers un `.onnx`, quelle qu'en soit l'origine.

Le paramètre `model_id` désignera une entrée du catalogue embarqué le jour où celui-ci en
portera ; le mécanisme (téléchargement vérifié par empreinte SHA-256, cache sous
`~/.cache/retina/models/`, progression et annulation) est en place et testé.

## Traçabilité

C'est le point qui distingue ce process d'un filtre de retouche. Le modèle réellement employé
est inscrit :

- dans les **paramètres de l'instance** — donc dans l'historique, dans l'écho Python, dans les
  recettes et dans le projet `.retina` ;
- dans les **mots-clés FITS** de la fenêtre : `AIMODEL` (nom ou fichier), `AIMODVER` (version)
  et `AIMODSHA` (empreinte tronquée).

Au rejeu d'une recette, si l'empreinte du modèle ne correspond plus à celle enregistrée, rien
n'est interrompu — mais vous en êtes **averti** : le résultat ne sera pas identique, et il vaut
mieux l'apprendre là qu'en comparant deux images.

## Paramètres

- **`model`** — *path*. Le fichier `.onnx` à employer.
- **`model_id`** — *str*. Identifiant d'un modèle du catalogue : soit `graxpert-denoise-<version>`
  trouvé dans une installation GraXpert locale, soit le même téléchargé à la demande depuis le
  miroir Hugging Face. Le local prime — rien n'est retéléchargé s'il est déjà là.
- **`strength`** — *real*, défaut `1.0`, plage `0`–`1`. Dose l'effet : à `1` le réseau décide
  seul, en deçà on garde une part de l'image d'origine.
- **`tile_size`** — *int*, défaut `256`. Côté des tuiles envoyées au réseau.
- **`overlap`** — *int*, défaut `32`. Recouvrement, fondu par rampe linéaire. Trop faible, les
  jointures de tuiles se voient.
- **`model_version`**, **`model_sha256`** — *str*, **renseignés à l'exécution**. Ne les
  remplissez pas à la main ; ils portent la trace du modèle employé.

## Astuces & pièges

> **Le débruitage IA s'applique sur données linéaires**, avant étirement, comme les autres
> réductions de bruit. Après étirement, le réseau voit une distribution qu'il n'a pas apprise.

- Un modèle entraîné en RGB reçoit un plan mono **répliqué en trois canaux**, et la sortie est
  remoyennée. C'est transparent, mais cela veut dire qu'un mono coûte le même temps qu'un RGB.
- Au-delà de trois canaux, seuls les trois premiers passent : l'alpha n'a rien à faire dans un
  réseau de débruitage.

## Voir aussi

- [NoiseReduction](retina-doc://NoiseReduction) — débruitage classique, sans modèle à fournir.
- [AIDeconvolution](retina-doc://AIDeconvolution) — déconvolution par réseau, même mécanique.
- [StarRemoval](retina-doc://StarRemoval) — retrait d'étoiles, également en backend ONNX.

## Références

- ONNX Runtime — exécution locale de modèles, sans service distant.
