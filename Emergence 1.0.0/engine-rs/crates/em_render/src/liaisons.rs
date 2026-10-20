//! Petits objets d'aide pour déclarer des mises en page de liaisons EXPLICITES (jamais `auto` : piège de
//! docs/19b L03). Le numéro de liaison est attribué dans l'ordre d'appel, comme dans les shaders.

/// Constructeur de `BindGroupLayout` : une méthode par genre de liaison.
pub(crate) struct MiseEnPage {
    entrees: Vec<wgpu::BindGroupLayoutEntry>,
}

impl MiseEnPage {
    /// Mise en page vide.
    pub(crate) fn new() -> Self {
        Self { entrees: Vec::new() }
    }

    fn ajouter(mut self, visibilite: wgpu::ShaderStages, ty: wgpu::BindingType) -> Self {
        let binding = self.entrees.len() as u32;
        self.entrees.push(wgpu::BindGroupLayoutEntry {
            binding,
            visibility: visibilite,
            ty,
            count: None,
        });
        self
    }

    /// Tampon de stockage en lecture seule.
    pub(crate) fn stockage_tampon_lecture(self, vis: wgpu::ShaderStages) -> Self {
        self.ajouter(
            vis,
            wgpu::BindingType::Buffer {
                ty: wgpu::BufferBindingType::Storage { read_only: true },
                has_dynamic_offset: false,
                min_binding_size: None,
            },
        )
    }

    /// Texture 2D lue par `textureLoad` : entiers non signés.
    pub(crate) fn texture_uint(self, vis: wgpu::ShaderStages) -> Self {
        self.ajouter(
            vis,
            wgpu::BindingType::Texture {
                sample_type: wgpu::TextureSampleType::Uint,
                view_dimension: wgpu::TextureViewDimension::D2,
                multisampled: false,
            },
        )
    }

    /// Texture 2D lue par `textureLoad` : flottants non filtrables (R32Float).
    pub(crate) fn texture_float_brute(self, vis: wgpu::ShaderStages) -> Self {
        self.ajouter(
            vis,
            wgpu::BindingType::Texture {
                sample_type: wgpu::TextureSampleType::Float { filterable: false },
                view_dimension: wgpu::TextureViewDimension::D2,
                multisampled: false,
            },
        )
    }

    /// Tampon uniforme.
    pub(crate) fn uniforme(self, vis: wgpu::ShaderStages) -> Self {
        self.ajouter(
            vis,
            wgpu::BindingType::Buffer {
                ty: wgpu::BufferBindingType::Uniform,
                has_dynamic_offset: false,
                min_binding_size: None,
            },
        )
    }

    /// Texture 2D échantillonnable (flottante filtrable).
    pub(crate) fn texture(self, vis: wgpu::ShaderStages) -> Self {
        self.ajouter(
            vis,
            wgpu::BindingType::Texture {
                sample_type: wgpu::TextureSampleType::Float { filterable: true },
                view_dimension: wgpu::TextureViewDimension::D2,
                multisampled: false,
            },
        )
    }

    /// Texture 2D en écriture seule.
    pub(crate) fn stockage_ecriture(self, vis: wgpu::ShaderStages, format: wgpu::TextureFormat) -> Self {
        self.ajouter(
            vis,
            wgpu::BindingType::StorageTexture {
                access: wgpu::StorageTextureAccess::WriteOnly,
                format,
                view_dimension: wgpu::TextureViewDimension::D2,
            },
        )
    }

    /// Échantillonneur filtrant.
    pub(crate) fn echantillonneur(self, vis: wgpu::ShaderStages) -> Self {
        self.ajouter(
            vis,
            wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
        )
    }

    /// Crée la mise en page sur l'appareil.
    pub(crate) fn creer(self, dev: &wgpu::Device, etiquette: &str) -> wgpu::BindGroupLayout {
        dev.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some(etiquette),
            entries: &self.entrees,
        })
    }
}

/// Échantillonneur linéaire, bords prolongés (LUT, bloom).
pub(crate) fn echantillonneur_lineaire(dev: &wgpu::Device) -> wgpu::Sampler {
    dev.create_sampler(&wgpu::SamplerDescriptor {
        label: Some("échantillonneur linéaire"),
        mag_filter: wgpu::FilterMode::Linear,
        min_filter: wgpu::FilterMode::Linear,
        ..Default::default()
    })
}

/// Texture 2D HDR flottante (ou LUT) avec les usages demandés.
pub(crate) fn texture_2d(
    dev: &wgpu::Device,
    etiquette: &str,
    taille: (u32, u32),
    niveaux: u32,
    usage: wgpu::TextureUsages,
) -> wgpu::Texture {
    dev.create_texture(&wgpu::TextureDescriptor {
        label: Some(etiquette),
        size: wgpu::Extent3d {
            width: taille.0,
            height: taille.1,
            depth_or_array_layers: 1,
        },
        mip_level_count: niveaux,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format: HDR_FORMAT,
        usage,
        view_formats: &[],
    })
}

/// Format de rendu flottant du labo : HDR, LUT et bloom (docs/19b L03).
pub const HDR_FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Rgba16Float;

/// Entrée de groupe : une vue de texture.
pub(crate) fn entree_vue(binding: u32, v: &wgpu::TextureView) -> wgpu::BindGroupEntry<'_> {
    wgpu::BindGroupEntry {
        binding,
        resource: wgpu::BindingResource::TextureView(v),
    }
}

/// Entrée de groupe : un tampon entier.
pub(crate) fn entree_tampon(binding: u32, b: &wgpu::Buffer) -> wgpu::BindGroupEntry<'_> {
    wgpu::BindGroupEntry {
        binding,
        resource: b.as_entire_binding(),
    }
}
