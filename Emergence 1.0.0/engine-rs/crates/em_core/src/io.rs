//! Lecture et écriture petit-boutistes sur des tampons d'octets (formats `.vxm`, `EMBK`, `EMPK`, `EMOPLG`).

use thiserror::Error;

/// Erreur de lecture.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum IoError {
    /// Le tampon se termine avant la fin de la valeur demandée.
    #[error("tampon tronqué : {voulus} octet(s) demandés à la position {position}, {restants} restant(s)")]
    Tronque {
        /// Octets demandés.
        voulus: usize,
        /// Position de lecture au moment de la demande.
        position: usize,
        /// Octets restants.
        restants: usize,
    },
}

/// Écrivain petit-boutiste dans un `Vec<u8>`.
#[derive(Clone, Debug, Default)]
pub struct LeWriter {
    octets: Vec<u8>,
}

impl LeWriter {
    /// Écrivain vide.
    pub fn new() -> Self {
        Self::default()
    }
    /// Écrivain vide avec une capacité réservée.
    pub fn with_capacity(n: usize) -> Self {
        Self {
            octets: Vec::with_capacity(n),
        }
    }
    /// Nombre d'octets écrits.
    pub fn len(&self) -> usize {
        self.octets.len()
    }
    /// Vrai si rien n'a été écrit.
    pub fn is_empty(&self) -> bool {
        self.octets.is_empty()
    }
    /// Octets écrits jusqu'ici.
    pub fn as_bytes(&self) -> &[u8] {
        &self.octets
    }
    /// Consomme l'écrivain et rend les octets.
    pub fn into_bytes(self) -> Vec<u8> {
        self.octets
    }
    pub fn u8(&mut self, v: u8) -> &mut Self {
        self.octets.push(v);
        self
    }
    pub fn u16(&mut self, v: u16) -> &mut Self {
        self.bytes(&v.to_le_bytes())
    }
    pub fn u32(&mut self, v: u32) -> &mut Self {
        self.bytes(&v.to_le_bytes())
    }
    pub fn u64(&mut self, v: u64) -> &mut Self {
        self.bytes(&v.to_le_bytes())
    }
    pub fn i8(&mut self, v: i8) -> &mut Self {
        self.bytes(&v.to_le_bytes())
    }
    pub fn i16(&mut self, v: i16) -> &mut Self {
        self.bytes(&v.to_le_bytes())
    }
    pub fn i32(&mut self, v: i32) -> &mut Self {
        self.bytes(&v.to_le_bytes())
    }
    pub fn i64(&mut self, v: i64) -> &mut Self {
        self.bytes(&v.to_le_bytes())
    }
    /// Ajoute des octets bruts.
    pub fn bytes(&mut self, b: &[u8]) -> &mut Self {
        self.octets.extend_from_slice(b);
        self
    }
}

/// Lecteur petit-boutiste sur une tranche d'octets.
#[derive(Clone, Debug)]
pub struct LeReader<'a> {
    octets: &'a [u8],
    position: usize,
}

impl<'a> LeReader<'a> {
    /// Lecteur positionné au début.
    pub const fn new(octets: &'a [u8]) -> Self {
        Self { octets, position: 0 }
    }
    /// Position de lecture courante.
    pub const fn position(&self) -> usize {
        self.position
    }
    /// Octets restant à lire.
    pub const fn remaining(&self) -> usize {
        self.octets.len() - self.position
    }
    /// Vrai si tout a été lu.
    pub const fn is_finished(&self) -> bool {
        self.remaining() == 0
    }
    /// Lit `n` octets bruts.
    pub fn bytes(&mut self, n: usize) -> Result<&'a [u8], IoError> {
        if n > self.remaining() {
            return Err(IoError::Tronque {
                voulus: n,
                position: self.position,
                restants: self.remaining(),
            });
        }
        let tranche = &self.octets[self.position..self.position + n];
        self.position += n;
        Ok(tranche)
    }
    fn tableau<const N: usize>(&mut self) -> Result<[u8; N], IoError> {
        let mut a = [0_u8; N];
        a.copy_from_slice(self.bytes(N)?);
        Ok(a)
    }
    pub fn u8(&mut self) -> Result<u8, IoError> {
        Ok(self.tableau::<1>()?[0])
    }
    pub fn u16(&mut self) -> Result<u16, IoError> {
        Ok(u16::from_le_bytes(self.tableau()?))
    }
    pub fn u32(&mut self) -> Result<u32, IoError> {
        Ok(u32::from_le_bytes(self.tableau()?))
    }
    pub fn u64(&mut self) -> Result<u64, IoError> {
        Ok(u64::from_le_bytes(self.tableau()?))
    }
    pub fn i8(&mut self) -> Result<i8, IoError> {
        Ok(i8::from_le_bytes(self.tableau()?))
    }
    pub fn i16(&mut self) -> Result<i16, IoError> {
        Ok(i16::from_le_bytes(self.tableau()?))
    }
    pub fn i32(&mut self) -> Result<i32, IoError> {
        Ok(i32::from_le_bytes(self.tableau()?))
    }
    pub fn i64(&mut self) -> Result<i64, IoError> {
        Ok(i64::from_le_bytes(self.tableau()?))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn aller_retour_et_troncature() {
        let mut w = LeWriter::new();
        w.u8(1).u16(0x0203).u32(0x0405_0607).i64(-2).bytes(b"ab");
        let octets = w.into_bytes();
        assert_eq!(&octets[..3], &[1, 3, 2]);
        let mut r = LeReader::new(&octets);
        assert_eq!(r.u8(), Ok(1));
        assert_eq!(r.u16(), Ok(0x0203));
        assert_eq!(r.u32(), Ok(0x0405_0607));
        assert_eq!(r.i64(), Ok(-2));
        assert_eq!(r.bytes(2), Ok(&b"ab"[..]));
        assert!(r.is_finished());
        assert!(matches!(r.u8(), Err(IoError::Tronque { .. })));
    }
}
