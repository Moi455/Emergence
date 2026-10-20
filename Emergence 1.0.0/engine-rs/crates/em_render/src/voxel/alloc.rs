//! Allocateurs de la mémoire GPU des briques (docs/19a § 5.1) : cases de brique et tas de mots par classe de
//! taille. Les listes libres sont des piles : l'ordre d'allocation ne dépend que de l'ordre des appels, donc
//! deux chargements identiques donnent des cases identiques.

use crate::error::WorldError;

/// Allocateur de cases numérotées de 0 à `capacite - 1` : pointeur de remplissage puis liste libre.
#[derive(Debug)]
pub struct SlotAllocator {
    capacite: u32,
    suivant: u32,
    libres: Vec<u32>,
    nom: &'static str,
}

impl SlotAllocator {
    /// Allocateur de `capacite` cases ; `nom` apparaît dans l'erreur de saturation.
    pub fn new(nom: &'static str, capacite: u32) -> Self {
        Self {
            capacite,
            suivant: 0,
            libres: Vec::new(),
            nom,
        }
    }

    /// Prend une case (la dernière libérée d'abord).
    pub fn allouer(&mut self) -> Result<u32, WorldError> {
        if let Some(c) = self.libres.pop() {
            return Ok(c);
        }
        if self.suivant >= self.capacite {
            return Err(WorldError::Sature {
                ressource: self.nom,
                capacite: u64::from(self.capacite),
            });
        }
        self.suivant += 1;
        Ok(self.suivant - 1)
    }

    /// Rend une case. Panique en débogage si la case n'a jamais été donnée ou est déjà libre.
    pub fn liberer(&mut self, case: u32) {
        debug_assert!(case < self.suivant, "case jamais attribuée");
        debug_assert!(!self.libres.contains(&case), "case déjà libre");
        self.libres.push(case);
    }

    /// Cases actuellement attribuées.
    pub fn en_usage(&self) -> u32 {
        self.suivant - self.libres.len() as u32
    }

    /// Capacité totale.
    pub fn capacite(&self) -> u32 {
        self.capacite
    }
}

/// Classes de taille du tas de mots, une par nombre de bits par indice (1, 2, 4, 8, 16) : 18, 34, 72, 256, 256 mots.
pub const MOTS_PAR_CLASSE: [u32; 5] = [18, 34, 72, 256, 256];

/// Classe (0 à 4) d'un nombre de bits par indice.
pub fn classe_de_bits(bits: u8) -> usize {
    match bits {
        1 => 0,
        2 => 1,
        4 => 2,
        8 => 3,
        16 => 4,
        autre => panic!("bits par indice invalides : {autre}"),
    }
}

/// Tas de mots (`payload`) : allocation exacte par classe, listes libres par classe, jamais de défragmentation.
#[derive(Debug)]
pub struct PayloadAllocator {
    capacite: u32,
    suivant: u32,
    libres: [Vec<u32>; 5],
}

impl PayloadAllocator {
    /// Tas de `capacite` mots.
    pub fn new(capacite: u32) -> Self {
        Self {
            capacite,
            suivant: 0,
            libres: Default::default(),
        }
    }

    /// Réserve la place d'une brique à `bits` bits par indice ; renvoie le décalage en mots.
    pub fn allouer(&mut self, bits: u8) -> Result<u32, WorldError> {
        let c = classe_de_bits(bits);
        if let Some(o) = self.libres[c].pop() {
            return Ok(o);
        }
        let taille = MOTS_PAR_CLASSE[c];
        if u64::from(self.suivant) + u64::from(taille) > u64::from(self.capacite) {
            return Err(WorldError::Sature {
                ressource: "tas de mots (payload)",
                capacite: u64::from(self.capacite),
            });
        }
        self.suivant += taille;
        Ok(self.suivant - taille)
    }

    /// Rend la place d'une brique.
    pub fn liberer(&mut self, decalage: u32, bits: u8) {
        self.libres[classe_de_bits(bits)].push(decalage);
    }

    /// Mots utilisés (hors cases libres).
    pub fn mots_en_usage(&self) -> u64 {
        let libres: u64 = self
            .libres
            .iter()
            .zip(MOTS_PAR_CLASSE)
            .map(|(l, t)| l.len() as u64 * u64::from(t))
            .sum();
        u64::from(self.suivant) - libres
    }

    /// Capacité en mots.
    pub fn capacite(&self) -> u32 {
        self.capacite
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn les_cases_liberees_sont_reprises_et_la_saturation_est_claire() {
        let mut a = SlotAllocator::new("briques", 2);
        assert_eq!(a.allouer().unwrap(), 0);
        assert_eq!(a.allouer().unwrap(), 1);
        let e = a.allouer().unwrap_err();
        assert!(e.to_string().contains("briques"), "{e}");
        a.liberer(0);
        assert_eq!(a.en_usage(), 1);
        assert_eq!(a.allouer().unwrap(), 0);
    }

    #[test]
    fn le_tas_alloue_a_la_mesure_par_classe() {
        let mut p = PayloadAllocator::new(18 + 34 + 72);
        assert_eq!(p.allouer(1).unwrap(), 0);
        assert_eq!(p.allouer(2).unwrap(), 18);
        assert_eq!(p.allouer(4).unwrap(), 52);
        assert!(p.allouer(8).is_err());
        assert_eq!(p.mots_en_usage(), 124);
        p.liberer(18, 2);
        assert_eq!(p.mots_en_usage(), 90);
        // la place libérée n'est reprise que par la même classe
        assert_eq!(p.allouer(2).unwrap(), 18);
    }
}
