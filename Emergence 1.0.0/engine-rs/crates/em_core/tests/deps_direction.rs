//! Sens interdits du graphe de dépendances (docs/19 § 2.3), lus dans `cargo metadata` :
//! `em_render` ne dépend pas de `em_world` ni de `em_ops` ; aucune crate de vérité ne dépend de `wgpu` ;
//! `em_ops` ne dépend pas de `em_voxel`. La fermeture est transitive.

use std::collections::{BTreeMap, BTreeSet};
use std::process::Command;

/// Crates de vérité (docs/19 § 2.4).
const VERITE: [&str; 7] = [
    "em_core",
    "em_voxel",
    "em_ops",
    "em_gen",
    "em_terrain",
    "em_assembly",
    "em_world",
];

/// Graphe des paquets : nom -> noms des dépendances directes (toutes natures confondues).
struct GrapheDependances {
    aretes: BTreeMap<String, BTreeSet<String>>,
}

impl GrapheDependances {
    /// Lit `cargo metadata` pour l'espace de travail courant.
    fn charger() -> Self {
        let cargo = std::env::var("CARGO").unwrap_or_else(|_| "cargo".to_string());
        let sortie = Command::new(cargo)
            .args(["metadata", "--format-version", "1", "--locked"])
            .current_dir(env!("CARGO_MANIFEST_DIR"))
            .output()
            .expect("cargo metadata doit se lancer");
        assert!(
            sortie.status.success(),
            "cargo metadata a échoué : {}",
            String::from_utf8_lossy(&sortie.stderr)
        );
        let json: serde_json::Value = serde_json::from_slice(&sortie.stdout).expect("JSON de cargo metadata");
        let noms: BTreeMap<&str, &str> = json["packages"]
            .as_array()
            .expect("packages")
            .iter()
            .map(|p| (p["id"].as_str().unwrap(), p["name"].as_str().unwrap()))
            .collect();
        let mut aretes: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
        for noeud in json["resolve"]["nodes"].as_array().expect("resolve.nodes") {
            let nom = noms[noeud["id"].as_str().unwrap()].to_string();
            let deps = noeud["dependencies"].as_array().expect("dependencies");
            aretes
                .entry(nom)
                .or_default()
                .extend(deps.iter().map(|d| noms[d.as_str().unwrap()].to_string()));
        }
        Self { aretes }
    }

    /// Toutes les dépendances (transitives) d'un paquet.
    fn fermeture(&self, depart: &str) -> BTreeSet<String> {
        let mut vus = BTreeSet::new();
        let mut pile = vec![depart.to_string()];
        while let Some(courant) = pile.pop() {
            for d in self.aretes.get(&courant).into_iter().flatten() {
                if vus.insert(d.clone()) {
                    pile.push(d.clone());
                }
            }
        }
        vus
    }

    fn depend(&self, de: &str, vers: &str) -> bool {
        self.fermeture(de).contains(vers)
    }
}

#[test]
fn sens_interdits_du_graphe() {
    let g = GrapheDependances::charger();
    assert!(
        g.aretes.contains_key("em_render"),
        "em_render doit exister dans l'espace de travail"
    );
    assert!(
        !g.depend("em_render", "em_world"),
        "em_render ne doit pas dépendre de em_world"
    );
    assert!(
        !g.depend("em_render", "em_ops"),
        "em_render ne doit pas dépendre de em_ops"
    );
    assert!(
        !g.depend("em_ops", "em_voxel"),
        "em_ops ne doit pas dépendre de em_voxel"
    );
    for v in VERITE {
        assert!(g.aretes.contains_key(v), "crate de vérité absente : {v}");
        assert!(
            !g.depend(v, "wgpu"),
            "la crate de vérité {v} ne doit pas dépendre de wgpu"
        );
    }
}

#[test]
fn le_detecteur_detecte() {
    // Garde-fou : em_render dépend bien de wgpu et de em_core, sinon le test ci-dessus ne prouverait rien.
    let g = GrapheDependances::charger();
    assert!(g.depend("em_render", "wgpu"));
    assert!(g.depend("em_lab", "em_world"));
    assert!(g.depend("em_world", "em_core"));
}
