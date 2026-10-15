# engine/ops : bus d'opérations (T16, M6)

`Operation` (format v1, 48 octets, petit-boutiste), `OperationBus` (file ordonnée thread-safe, tri total
`(tick, author, decision_seq, k, kind, charge)`, `op_id` et `seq` attribués au `flush`), `Applier` (interface
des abonnés ; T17 y branchera `VoxelOpApplier`), `OpJournal` (blocs de 4 096 opérations, CRC32, reprise
après crash). Tests : `test_ops`. Banc : `bench_ops [n]`.

Débit mesuré [Mesuré, 15 oct., Release, 1 000 000 d'opérations de 64 octets, 500 auteurs, ordre d'arrivée
mélangé, journal sur disque] : `submit` ≈ 12 M ops/s ; `flush` (tri + attribution + écriture du journal avec
CRC) ≈ 2,4 M ops/s ; total ≈ 2,0 M ops/s ; fichier 61 Mio (≈ 64 octets/opération). Trois mesures concordantes.

Journal : un bloc avec CRC faux, une opération de version ou de sorte inconnue, un `op_id` non croissant,
une version de format future : refusés (le fichier n'est pas modifié). Une queue tronquée (crash) est coupée
à l'ouverture, puis le bus reprend à `last_op_id() + 1`. Limite connue : `fsync` à chaque `flush()` du journal
(POSIX seulement) ; un bloc final complet mais corrompu par un crash est refusé, pas réparé.
