//! Identifiants de générateur des familles bâtiments (48 à 79), props (80 à 111) et rochers (112 à 127). Registre en
//! AJOUT SEUL : on ne renumérote jamais.

use crate::generator::GeneratorId;

/// La maison de Monsieur, port Rust (L35).
pub const HOUSE: GeneratorId = GeneratorId::from_raw(48);

/// Les bâtiments du village hors maison (L35) : grange, forge, moulins, église, ponts...
pub const BUILDING: GeneratorId = GeneratorId::from_raw(49);

/// Les props (L36) : tonneaux, caisses, étals, clôtures, petits objets...
pub const PROP: GeneratorId = GeneratorId::from_raw(80);

/// Les rochers et le relief ponctuel (L37) : blocs, falaises, menhirs, ruines, grottes, arches.
pub const ROCK: GeneratorId = GeneratorId::from_raw(112);
