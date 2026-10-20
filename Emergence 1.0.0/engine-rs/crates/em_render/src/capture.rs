//! Lecture d'une texture et écriture d'un PNG déterministe (docs/19 § 7.2).
//!
//! Les lignes de lecture sont alignées sur 256 o (`COPY_BYTES_PER_ROW_ALIGNMENT`) ; le PNG reçoit les
//! octets sRGB tels que stockés (aucune conversion linéaire), avec un encodeur aux réglages fixes et
//! sans horodatage ni métadonnée variable : deux lectures identiques donnent deux fichiers identiques.

use crate::error::CaptureError;
use crate::gpu::GpuContext;
use std::path::Path;
use std::sync::mpsc;

/// Image RGBA 8 bits lue du GPU (octets sRGB), dimensions et pixels privés.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RgbaImage {
    width: u32,
    height: u32,
    pixels: Vec<u8>,
}

impl RgbaImage {
    /// Largeur en pixels.
    pub fn width(&self) -> u32 {
        self.width
    }

    /// Hauteur en pixels.
    pub fn height(&self) -> u32 {
        self.height
    }

    /// Octets RGBA, ligne par ligne, sans remplissage.
    pub fn pixels(&self) -> &[u8] {
        &self.pixels
    }

    /// Encode en PNG (RGBA 8 bits, marqué sRGB) dans un tampon : octets reproductibles.
    pub fn encoder_png(&self) -> Result<Vec<u8>, CaptureError> {
        let mut sortie = Vec::new();
        {
            let mut enc = png::Encoder::new(&mut sortie, self.width, self.height);
            enc.set_color(png::ColorType::Rgba);
            enc.set_depth(png::BitDepth::Eight);
            enc.set_compression(png::Compression::Default);
            enc.set_filter(png::FilterType::Sub);
            enc.set_source_srgb(png::SrgbRenderingIntent::Perceptual);
            let mut ecrivain = enc.write_header()?;
            ecrivain.write_image_data(&self.pixels)?;
            ecrivain.finish()?;
        }
        Ok(sortie)
    }
}

/// Lit une texture 2D (un seul niveau, une seule couche) en RGBA 8 bits.
///
/// Formats gérés : `Rgba8Unorm[Srgb]` et `Bgra8Unorm[Srgb]` (permutés en RGBA). La texture doit avoir `COPY_SRC`.
pub fn read_texture(gpu: &GpuContext, tex: &wgpu::Texture) -> Result<RgbaImage, CaptureError> {
    if !tex.usage().contains(wgpu::TextureUsages::COPY_SRC) {
        return Err(CaptureError::UsageManquant);
    }
    let permute = match tex.format() {
        wgpu::TextureFormat::Rgba8Unorm | wgpu::TextureFormat::Rgba8UnormSrgb => false,
        wgpu::TextureFormat::Bgra8Unorm | wgpu::TextureFormat::Bgra8UnormSrgb => true,
        autre => return Err(CaptureError::Format(format!("{autre:?}"))),
    };
    let (w, h) = (tex.width(), tex.height());
    let utile = w * 4;
    let aligne = utile.div_ceil(wgpu::COPY_BYTES_PER_ROW_ALIGNMENT) * wgpu::COPY_BYTES_PER_ROW_ALIGNMENT;
    let tampon = gpu.device().create_buffer(&wgpu::BufferDescriptor {
        label: Some("lecture de capture"),
        size: u64::from(aligne) * u64::from(h),
        usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
        mapped_at_creation: false,
    });
    let mut enc = gpu
        .device()
        .create_command_encoder(&wgpu::CommandEncoderDescriptor {
            label: Some("capture"),
        });
    enc.copy_texture_to_buffer(
        tex.as_image_copy(),
        wgpu::TexelCopyBufferInfo {
            buffer: &tampon,
            layout: wgpu::TexelCopyBufferLayout {
                offset: 0,
                bytes_per_row: Some(aligne),
                rows_per_image: Some(h),
            },
        },
        wgpu::Extent3d {
            width: w,
            height: h,
            depth_or_array_layers: 1,
        },
    );
    gpu.queue().submit([enc.finish()]);
    let (tx, rx) = mpsc::channel();
    tampon.slice(..).map_async(wgpu::MapMode::Read, move |r| {
        // Le récepteur vit jusqu'à la fin de la fonction ; un échec d'envoi est impossible ici.
        let _ = tx.send(r);
    });
    gpu.attendre_fin();
    rx.recv()
        .map_err(|e| CaptureError::Lecture(e.to_string()))?
        .map_err(|e| CaptureError::Lecture(e.to_string()))?;
    let mut pixels = Vec::with_capacity((utile * h) as usize);
    {
        let vue = tampon
            .slice(..)
            .get_mapped_range()
            .map_err(|e| CaptureError::Lecture(e.to_string()))?;
        for ligne in 0..h as usize {
            let debut = ligne * aligne as usize;
            pixels.extend_from_slice(&vue[debut..debut + utile as usize]);
        }
    }
    tampon.unmap();
    if permute {
        for px in pixels.as_chunks_mut::<4>().0 {
            px.swap(0, 2);
        }
    }
    Ok(RgbaImage {
        width: w,
        height: h,
        pixels,
    })
}

/// Lit la texture et écrit un PNG sRGB déterministe (crée les dossiers manquants).
pub fn read_texture_png(gpu: &GpuContext, tex: &wgpu::Texture, path: &Path) -> Result<(), CaptureError> {
    let image = read_texture(gpu, tex)?;
    let octets = image.encoder_png()?;
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(path, octets)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::RgbaImage;

    #[test]
    fn le_png_est_reproductible_octet_pour_octet() {
        let pixels: Vec<u8> = (0..(16 * 8 * 4)).map(|i| (i * 7 % 251) as u8).collect();
        let a = RgbaImage {
            width: 16,
            height: 8,
            pixels: pixels.clone(),
        };
        let b = RgbaImage {
            width: 16,
            height: 8,
            pixels,
        };
        assert_eq!(a.encoder_png().unwrap(), b.encoder_png().unwrap());
        assert_eq!(&a.encoder_png().unwrap()[..8], b"\x89PNG\r\n\x1a\n");
    }
}
