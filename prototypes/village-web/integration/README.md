# Village jouable avec ses villageois (intégration)

Le prototype du fil « Village voxelisé jouable » (`../jeu/`) et les villageois du fil « Skins des villageois » (`/characters` : générateur et données ; les .glb d'exemple, 19 à 29 Mo, ne sont pas versés, `node characters/tools/export.mjs <graine> <dossier> <village>` les régénère) assemblés en un seul jeu dans le navigateur.

## Jouer depuis le dépôt

```
python3 -m http.server 8000          # à la racine du dépôt
# puis ouvrir http://localhost:8000/prototypes/village-web/jeu/index.html
```

Options dans l'adresse : `?npc=48` (nombre de villageois, 120 au plus), `?village=bourg` (mer, foret, montagne, desert, bourg).

## Ce qui se passe

- `jeu/villagers.js` se branche sur les crochets d'`engine.js` (`addDrawHook`, `addUpdate`) ; sans lui, le village tourne seul.
- `jeu/villager_worker.js` lance le générateur `characters/gen` dans 1 à 4 workers, à partir des graines de `characters/data/villagers.json` : le jeu ne stocke que la graine et la garde-robe. Le maillage loin (5 cm) est produit pour tous d'abord, le maillage proche (2,5 cm) à l'approche du joueur.
- Chaque villageois a son squelette humanoïde Godot (43 os), son atlas, ses tenues : il passe en tenue de travail quand il travaille, et revient à sa tenue du jour ensuite (la tenue est générée à la demande).
- Comportement provisoire, en attendant le moteur de décision : marcher, courir (enfants), travailler, discuter à deux, s'asseoir, saluer le joueur qui s'approche. Le nom, le métier et l'action s'affichent sous le viseur.
- Rendu : matrices d'os dans une texture (aucune limite d'uniformes sur GPU intégré), ombres reçues et portées, brouillard et étalonnage du village, animation à 10 Hz au-delà de 25 m.

## Mesures (conteneur, GPU logiciel SwiftShader : images/s non significatives)

48 villageois : génération 1,4 à 1,6 s par villageois et par worker (3 workers), 120 à 130 k triangles dessinés, 18 à 26 Mo de mémoire GPU. La touche B du jeu mesure les images/s sur la vraie machine.

`make_test_villager.py` produit le villageois de test du premier branchement (boîtes, 7 animations), gardé comme exemple minimal de .glb skinné au contrat.
