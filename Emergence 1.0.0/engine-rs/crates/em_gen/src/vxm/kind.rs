//! Sorte d'un voxel du fichier `.vxm` (docs/19a § 1.3).

/// Sorte de voxel écrite par l'exporteur Python.
#[derive(Copy, Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum VxmKind {
    /// Écorce (code 1).
    Bark = 1,
    /// Feuille (code 2).
    Leaf = 2,
    /// Rameau (code 3).
    Twig = 3,
    /// Fleur (code 4).
    Flower = 4,
    /// Fruit (code 5).
    Fruit = 5,
}

impl VxmKind {
    /// Toutes les sortes, dans l'ordre de leur code.
    pub const ALL: [VxmKind; 5] = [
        VxmKind::Bark,
        VxmKind::Leaf,
        VxmKind::Twig,
        VxmKind::Flower,
        VxmKind::Fruit,
    ];

    /// Lit un code du fichier.
    pub const fn from_code(code: u8) -> Option<VxmKind> {
        match code {
            1 => Some(VxmKind::Bark),
            2 => Some(VxmKind::Leaf),
            3 => Some(VxmKind::Twig),
            4 => Some(VxmKind::Flower),
            5 => Some(VxmKind::Fruit),
            _ => None,
        }
    }

    /// Code dans le fichier.
    pub const fn code(self) -> u8 {
        self as u8
    }

    /// Rang dans les tables à 5 entrées (code − 1).
    pub const fn index(self) -> usize {
        self as usize - 1
    }

    /// Priorité quand deux sortes tombent dans une même cellule : écorce > rameau > fleur > fruit > feuille
    /// (docs/19a § 1.4). Le plus petit gagne.
    pub const fn priority(self) -> u8 {
        match self {
            VxmKind::Bark => 0,
            VxmKind::Twig => 1,
            VxmKind::Flower => 2,
            VxmKind::Fruit => 3,
            VxmKind::Leaf => 4,
        }
    }
}
