# Situations d'amorçage

Fabrique des moments plausibles de la vie d'un PNJ : ce qu'il voit, croit, se rappelle et veut. Ils servent au pilote du professeur et au premier entraînement, en attendant que le moteur C++ produise de vraies situations (DAgger).

- **`scene.py`** : la vérité de la scène (lieu, heure, personnes et leurs liens au PNJ, objets, bêtes).
- **`mind.py`** : l'esprit du PNJ tiré de la scène, avec erreur et ignorance (âges devinés, propriétaires crus, absents remémorés). Un champ dont la scène ne dit rien reçoit une valeur plausible tirée de son échelle seule.
- **`propositions.py`** : croyances, objectifs, souvenirs et demandes, faits de prédicats généraux du catalogue. Chacun est validé par la langue ; 8 % sont rejetés (mesuré).
- **`audit.py`** : contrôle D10 indépendant de chaque situation. Aucun mot intime dans une proposition ; liens et champs intimes seulement entre adultes nets.

Rien n'est écrit à la main hors des archétypes de lieux : tous les mots viennent du catalogue. L'échantillonneur ne décide jamais à la place du PNJ.

Mesuré (11 oct.) : 2,9 ms par situation, 41 jetons en moyenne (21 à 60).

Limites : pas encore de mots pour les tenues, les marques, la météo vue ni les sortes de lieux (trous H et C de l'étape 18) ; les affordances des objets ne sont données que quand elles sont sûres.

```
cd ai && python3 -m situations.sampler --n 300     # statistiques
cd ai && python3 -m situations.sampler --show 3    # une situation
python3 -m unittest discover -s ai/situations/tests -t ai
```
