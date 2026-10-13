# Vision : Emergence

Jeu médiéval-fantastique pour Steam, dans un monde de voxels de 2 cm entièrement destructible, avec physique simulée, eau, feu et effondrements, un rendu soigné et attirant, et surtout une simulation sociale de PNJ assez poussée pour que n'importe quelle situation ou société puisse émerger.

## Ce que le joueur doit vivre

- Un monde qu'on peut creuser, bâtir, brûler, inonder, où chaque modification reste et a des conséquences.
- Des villageois qui se souviennent, mentent, se méfient, s'aiment, s'associent, se disputent un champ, élisent un maire ou le renversent, transmettent leur métier ou l'emportent dans la tombe.
- Un monde qui semble continuer au-delà de l'horizon : la mer, la forêt profonde, les montagnes et le désert promettent un ailleurs magique, toujours entrevu, jamais atteint.

## Les choix de Monsieur (porteur du projet)

| Date | Choix |
|---|---|
| 7 oct. 2026 | Priorité numéro 1 : la performance. Le rendu doit tenir sur un GPU intégré à très faible VRAM pour que le GPU dédié reste réservé à l'IA. Machine de Monsieur : portable avec GPU intégré et RTX série 3000 de 6 Go. |
| 7 oct. 2026 | Voxels de 2 cm, monde entièrement destructible, eau, feu, effondrements ; approche hiérarchique, clairsemée, multi-échelle ; « ne jamais calculer au-delà de la précision nécessaire ». |
| 7 oct. 2026 | Monde généré de façon déterministe depuis une seed ; seuls les deltas sont sauvegardés. |
| 7 oct. 2026 | Contenu : la génération procédurale est la voie principale ; un convertisseur de fichiers 3D en voxels permet de retoucher des modèles faits à la main. |
| 7 oct. 2026 | Les savoir-faire se transmettent de personne à personne (apprentissage, baguettes limitées) et peuvent se perdre. |
| 7 oct. 2026 | On ne se contente pas de lister les blocages : il faut trouver ou inventer des solutions. |
| 7 oct. 2026 | 500 m de profondeur, montagnes jusqu'à 3 km, horizon lointain, monde léger. |
| 8 oct. 2026 | 500 PNJ au total en environ 5 villages, pour que la gestion de l'espace et des déplacements soit réelle. |
| 8 oct. 2026 | Frontières : un côté mer, un côté forêt, un côté montagne, un désert ; difficulté exponentielle, le joueur doit toujours croire qu'il peut aller derrière. |
| 8 oct. 2026 | Carte « peut-être » réduite à 20 × 20 km (défaut retenu, à confirmer). |

## Ambition réaliste

Rivaliser avec GTA 6 sur le rendu brut est impossible avec un budget de GPU intégré. La concurrence crédible se joue sur la profondeur systémique (personne ne fait une société de 500 individus qui se souviennent, dans un monde entièrement modifiable) et sur une direction artistique forte, qui coûte peu.
