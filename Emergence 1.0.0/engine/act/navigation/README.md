# engine/act/navigation : la carte mentale et les itinéraires (T23b)

Un PNJ se déplace avec **ce qu'il sait** (P51, docs/14 § 4.8), jamais avec la grille vraie. Le monde voxel est confié à
une autre équipe : il répond derrière `ViewProbe` (« la marche de A à B rencontre-t-elle un obstacle ? »), et le
`Navigator` ne l'interroge que **dans le champ de vision** de l'acteur (24 m par défaut). `FlatTerrain` (grille plate) sert aux tests.

| Classe | Rôle |
|---|---|
| `MentalMap` | par PNJ, ~1 Kio (1 144 octets pleine) : tuiles de 256 m parcourues (6 084 bits), tronçons de route connus (512 bits), 16 lieux (position crue + certitude qui s'efface), 8 obstacles rencontrés ou entendus (oubliés après 30 jours). Oubli borné, déterministe. Sérialisable (`serialize`/`deserialize`, refus fermé), empreinte FNV-1a |
| `RoadPlan` | routes du plan du monde (géométrie partagée) ; le planificateur ne lit que les tronçons que la carte dit connus |
| `RoutePlanner` | A* entiers sur la carte seule : route connue 1, tuile parcourue 2, inconnu 6 par mm ; un obstacle connu retire le passage ; au-delà du connu il marche vers la position crue (explore). Aucun accès au monde (ctest `navigation_planner_no_world`) |
| `NavigationQuery` | pour T22 : `next_step(npc, NavRequest) -> NavStep` (`Moving`, `Exploring`, `Arrived`, `Blocked`), `cancel(npc)`. `Blocked` n'est rendu que sur place, obstacle en vue |
| `NavigationFeed` | pour T23 (`see_position`, `see_place`) et T24 (`hear_place` avec certitude, `hear_segment`, `hear_obstacle`) |
| `Navigator` | implémente les deux ; une carte et un trajet par PNJ (`add_npc` avant les fils) |
| `MentalMapCodec` | écrit/lit les octets de `NpcBundle::mental_map` (la place réservée de la section NPCS, T04) |

Contournement local : un obstacle en vue est longé (pas de côté de 3 à 12 m, 300 m marchés au plus) ; si tout est fermé, le passage est noté
comme obstacle, l'itinéraire est replanifié (6 fois au plus), puis `Blocked`.
Mesures : `build/act/bench_navigation` ; `test_navigation`.

## Sauvegarde, parole, honnêteté

- La carte vivante est dans `Navigator` : appeler `sync_to_bundle(npc, bundle.mental_map)` avant chaque sauvegarde et
  `sync_from_bundle` après chaque chargement. Le trajet n'est pas sauvé : à la reprise le PNJ **replanifie** depuis sa carte
  (même destination, même connaissance ; test `save_mid_journey_then_resume_replans_to_the_same_arrival`).
- `Blocked` seulement sur place, obstacle en vue. Un PNJ inconnu du navigateur ou sans route trouvée (budget) rend `Exploring` vers la position crue.
- Un obstacle seulement **entendu** ne ferme pas le passage : surcoût borné (8 tuiles), 4 au plus, jamais au détriment d'un obstacle vu,
  non rafraîchi par répétition, effacé s'il est vu ouvert. Un lieu vu **et** protégé n'est jamais écrasé par du ouï-dire.
- Garde contre la lecture de la vérité : le grep `navigation_planner_no_world` (contournable) et des tests de comportement
  (`world_is_asked_only_in_view_on_rough_ground` : terrain piège sur relief, requêtes toujours partant de l'acteur et à moins de la vue ;
  même route sur monde plat et accidenté tant que rien n'est en vue).

## Dette : constantes hors catalogue (à passer dans une table du catalogue plus tard, non externalisées)

| Constante | Valeur | Où |
|---|---|---|
| tuile de connaissance / côté du plan | 256 m / 78 tuiles | `navigation_types.h` |
| portée de vue | 24 m | `NavigatorConfig::view_mm` |
| rayon d'atteinte d'un nœud de route | 8 m | `NavigatorConfig::reach_mm` |
| coûts par mm : route / tuile parcourue / inconnu / heuristique pondérée | 1 / 2 / 6 / 4 | `route_planner.cpp` |
| surcoût d'un obstacle entendu | 8 tuiles ; 4 obstacles entendus au plus sur 8 | `route_planner.cpp`, `mental_map.h` |
| vie d'un obstacle | 30 jours | `kObstacleLifeDays` |
| oubli de certitude d'un lieu | 1 point / 4 jours, plancher 8 | `MentalMap::place_certainty` |
| plafond de la parole / certitude du vu | 200 / 255 | `mental_map.h` |
| lieux / tronçons / obstacles | 16 / 512 / 8 | `mental_map.h`, `road_plan.h` |
| replanifications avant `Blocked` | 6 | `NavigatorConfig::max_replans` |
| détour le long d'un obstacle | 300 m marchés (pas de 3 à 12 m) | `NavigatorConfig::max_detour_mm` |
| expansions de l'A* | 8192 | `PlannerLimits::max_expansions` |
