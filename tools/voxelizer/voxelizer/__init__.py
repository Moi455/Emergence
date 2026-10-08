"""voxelizer : modèle 3D texturé -> modèle voxel plein, 1 voxel = 1 entité, 2 cm par défaut."""
from .config import ScaleSpec, VoxelizeConfig, UNIT_TO_METERS
from .exporters import GlbExporter, JsonExporter, JsonImporter
from .lattice import VOXEL_SIZE_M
from .loaders import GltfLoader, LfsPointerError, ObjLoader, load_scene
from .model import Voxel, VoxelKind, VoxelModel
from .pipeline import VoxelizationPipeline, VoxelizationResult
from .compact import VoxelPack, pack_model
from .preview import IsoRenderer
from .render import PrettyRenderer
from .style import ColorStyler, OklabQuantizer
from .solid import GridTooLargeError, TooManyVoxelsError, VoxelBudgetError
from .scene import Material, MeshPrimitive, Scene3D, Texture

__all__ = [n for n in dir() if not n.startswith("_")]
