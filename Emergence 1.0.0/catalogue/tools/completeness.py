"""completeness.py - audit de complétude (docs/17) : ce que le catalogue déclare, et ce que le moteur fait VRAIMENT.

    python3 catalogue/tools/completeness.py            # résumé lisible
    python3 catalogue/tools/completeness.py --json     # tout, en JSON (pour docs/17 et pour le test)
    python3 catalogue/tools/completeness.py --list dead # une classe de variables, une par ligne

LECTURE SEULE : n'écrit rien, ne modifie ni le catalogue ni le moteur. Il lit :
  catalogue/data/*.toml (par schema.Catalogue), catalogue/generated/model_interface.json, ai/student2/output_registry.json,
  les en-têtes générés (npc_fields_gen.h, world_gen.h, context_map_gen.h) et le C++ ÉCRIT À LA MAIN de engine/act, engine/social,
  engine/ops (tests, bancs et fichiers générés exclus), plus characters/gen/anim.js (noms de clips) et docs/15 (tâches).

Trois mesures :
  1. gestes x couches  (catalogue, registre de sortie, exécuteur T22, effet moteur, perception par les témoins, gouverneur, clip) ;
  2. processus         (46 : loi C++ présente, ou tâche qui la porte, ou AUCUN porteur) ;
  3. variables         (378 : qui l'ÉCRIT, qui la LIT, et sa classe : vivante, écrite-jamais-lue, lue-jamais-écrite, morte...).

Méthode des variables (heuristique déclarée, pas une preuve formelle) :
  ÉCRIVAIN RÉALISÉ = au moins un de : une [[law]] qui la liste (npc_laws.cpp lit laws_gen.h) ; une règle de perception qui la
  cible (gen_cpp.PERCEPT_RULES) ; une affectation dans le C++ à la main (`.x =`, `->x +=`...) ; une écriture de geste par nom
  (`find("x")` de l'exécuteur, EntityDelta) ; une tête de l'élève qui l'écrit (registre de sortie) ; une source dérivée du
  ContextBuilder (kDerivedSources). `birth` n'est pas réalisé (pas de population, T47) : compté à part.
  LECTEUR RÉALISÉ = au moins un de : un jeton dont le ContextBuilder a la source (context_map_gen.h) ; une loi qui la lit
  (reads, depends_on) ; une règle de perception qui la lit ; un score d'oubli ; une mention en lecture dans le C++ à la main ;
  le gouverneur (governor.py / governor.cpp). La SAUVEGARDE (champ généré d'un état sauvé) est notée mais ne compte pas comme
  lecture : une variable seulement sauvée est « écrite-jamais-lue ».
Les exceptions déclarées (EXCEPTIONS) disent POURQUOI un élément mort l'est encore ; le test échoue si un élément mort
apparaît sans y être (catalogue/tests/test_completeness.py).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "catalogue"))
sys.path.insert(0, str(ROOT / "catalogue" / "tools"))
from schema import Catalogue  # noqa: E402

MI = ROOT / "catalogue/generated/model_interface.json"
REG = ROOT / "ai/student2/output_registry.json"
NPC_FIELDS = ROOT / "engine/social/generated/emergence/social/npc_fields_gen.h"
WORLD_GEN = ROOT / "engine/act/generated/emergence/act/world_gen.h"
CONTEXT_MAP = ROOT / "engine/social/tokenizer/generated/context_map_gen.h"
EXECUTOR = ROOT / "engine/act/gesture_executor.cpp"
TIMING = ROOT / "engine/act/gesture_timing.cpp"
PERCEPTION = ROOT / "engine/act/perception/src/perception_engine.cpp"
LAWS_DIR = ROOT / "engine/act/laws"
ANIM_JS = ROOT / "characters/gen/anim.js"
ROADMAP = ROOT / "docs/15_feuille_de_route_jouable.md"
GOVERNOR_PY = ROOT / "catalogue/tools/governor.py"
CPP_DIRS = ["engine/act", "engine/social/src", "engine/social/include", "engine/social/tokenizer/src",
            "engine/social/tokenizer/include", "engine/ops/src", "engine/ops/include"]
FORBIDDEN_TRUTHS = ("b_truth", "b_origin_fact", "m_fact_ref", "r_true_entity")
MODEL_WRITERS = ("T_jump", "T_step", "T_slow")

# ---------------------------------------------------------------------------------------------------------------------
# Déclarations vérifiées à la main (16 oct. 2026) contre le code ; l'empreinte du code lu est épinglée par le test : si
# gesture_executor.cpp:behavior_of ou gesture_timing.cpp:manner_of changent, le test échoue et la table est à revoir.
# Effet moteur de chaque geste : ce que l'exécuteur émet, et quelle loi peut en faire un changement du monde AUJOURD'HUI.
#   ok      = un effet matériel réel existe (Move, EntityDelta, loi de contact T18) ;
#   partial = effet réel pour une partie des usages seulement (le reste attend une loi) ;
#   act     = seulement une Operation `act` perceptible, aucun changement du monde ;
#   none    = rien (MetaBehavior).
GESTURE_EFFECT = {
    "go": ("ok", "Move de l'acteur sur sa carte mentale (T23b)"),
    "climb": ("ok", "Move ; posture climbing"),
    "swim": ("ok", "Move ; posture swimming"),
    "jump": ("ok", "Move de 0,4 à 2 m"),
    "mount": ("partial", "Move avec holder = monture ; aucune loi ne fait porter l'acteur par la bête qui marche (allure, charge)"),
    "set_posture": ("ok", "EntityDelta posture"),
    "take": ("partial", "Move vers la main si graspable ; `from=growing` (cueillir) et `from=worn_by` ne détachent rien de vivant ni de porté"),
    "put": ("ok", "Move au sol, sur une chose ou un lieu"),
    "give": ("ok", "Move avec holder = receveur (le receveur ne choisit pas : aucun refus physique)"),
    "throw": ("partial", "Move + Contact Strike sur la cible ; un coup sur un corps vivant n'a AUCUN effet (modèle de dommage absent, T34)"),
    "pour": ("partial", "EntityDelta water_volume de -> vers ; ne verse ni grain, ni cire, ni sel (substance sans variable de sorte)"),
    "wear": ("act", "Act seulement : l'habit reste TENU, `worn` n'est jamais écrit (gesture_executor.cpp:322-325)"),
    "operate": ("partial", "Contact Turn -> `till` seulement (outil qui creuse, sans cible) ; ouvrir, fermer, verrouiller : aucun état `open`/`locked` d'instance"),
    "strike": ("partial", "Contact Strike -> split, fracture, crush, disassemble (T18) ; sur une personne ou une bête : aucun effet (T34)"),
    "push": ("partial", "Contact Press -> fracture, crush ; aucun déplacement de la chose poussée ni de la personne"),
    "pull": ("partial", "Contact Press -> fracture, crush ; rien n'est tiré (pas de Move), arracher une plante : rien"),
    "grab": ("partial", "Contact Press ; aucune prise d'autrui (pas d'état `seized`, la cible n'est pas retenue)"),
    "guard": ("act", "Act seulement ; aucune réduction des coups reçus"),
    "scoop": ("partial", "Contact Dig -> extract (outil qui creuse) ; puiser de l'eau avec un seau : rien (`flow`, T20)"),
    "work": ("partial", "rub -> abrade ; saw -> cut ; press/stir/squeeze/twist : mix, press_extract, wash, spin_weave non écrits"),
    "tie": ("partial", "Join/Lash -> assemble, bind ; lier une personne ne la retient pas"),
    "blow": ("act", "Contact Press sans loi (heat/combust non écrits, T19)"),
    "shape": ("partial", "Contact Carve -> carve si l'outil coupe ; modeler l'argile (`shape` sans outil) : rien"),
    "channel": ("partial", "assemble/disassemble/carve ordinaires ; `magic_shape` (charge, magic_stability) non écrit (T20)"),
    "eat": ("ok", "EntityDelta hunger (et thirst), Destroy avec `all`"),
    "drink": ("ok", "EntityDelta thirst, Destroy avec `all`"),
    "sleep": ("ok", "posture lying ; NpcLaws par effort (sleeping)"),
    "rest": ("ok", "posture sitting ; NpcLaws par effort"),
    "touch": ("act", "Contact Press ignoré sur un corps ; seul le témoin « sent » (ev_sense = felt)"),
    "look": ("ok", "orientation (EntityDelta) + Act ; l'attention est écrite par le modèle"),
    "listen": ("ok", "orientation + Act"),
    "search": ("act", "Contact Press sans loi ; ne révèle rien de caché (aucune règle `conceals` dans la perception)"),
    "examine": ("act", "Contact Press sans loi ; aucune finesse de percept gagnée (sense non lu par la perception)"),
    "read": ("act", "Act seulement ; aucune inscription à lire (composant `inscription` sans variable)"),
    "speak": ("ok", "Act + parole -> HeardSpeech -> SpeechRouter (T24)"),
    "sign": ("act", "Act ; le `kind` du signe n'atteint pas le témoin (ev_manner_seen jamais écrit)"),
    "write": ("act", "Act seulement ; rien n'est inscrit sur la chose (composant `inscription` sans variable)"),
    "perform": ("act", "Act bruyant ; `mood` et l'instrument n'atteignent pas le témoin"),
    "wait": ("none", "MetaBehavior : le temps passe, la condition d'arrêt est lue"),
    "stop": ("none", "MetaBehavior : ne lâche aucune prise (`grab` n'a pas d'état)"),
}
# Les tâches qui portent chaque processus non écrit (docs/15, lu automatiquement ; complété ici seulement par ce qu'il ne dit pas).
PLANNED_ELSEWHERE = {"conceive": "T34 (docs/16 § 4.4, P53)", "gestate_birth": "T34 (docs/16 § 4.4, P53)"}

# Exceptions : un élément « mort » qui n'est pas une erreur aujourd'hui, avec sa raison. Une variable morte absente de cette
# table fait échouer le test. Clés = raison (tâche ou décision), valeurs = ids.
EXCEPTIONS = {
    "vue calculée pour la chronique et les mesures, jamais un jeton (docs/14 § 9, T31b/T30)": [
        "recognized_members", "role_holder_support", "legitimacy", "group_cohesion", "recognized_claims",
        "reputation_aggregate", "custom_aggregate", "unrest", "wealth_objective"],
    "vérité du moteur, lue par l'évaluateur d'entraînement seulement (CLAUDE.md, P50)": [
        "b_truth", "b_origin_fact", "m_fact_ref", "b_confirmed", "custody_log", "transactions", "made_by", "a_witnesses",
        "a_obligations", "a_parties", "a_document", "a_kind_label", "trace_fact", "s_introduced_by", "s_introduced_at",
        "biological_parents"],
    "T25 AgreementBook / T35 Referents pas écrits": [
        "a_form", "a_status", "s_scope", "s_last_believed", "s_name"],
    "T26 PlanExecutor / T27 ordonnanceur pas écrits": [
        "i_serves", "i_commitment", "g_has_plan", "g_progress", "think_more", "w_think_budget"],
    "T34 corps : maladies, grossesse, blessures, dommage des coups": [
        "illnesses", "immunities", "symptoms", "pregnancy", "fecundity", "wounds", "permanent_marks", "zones",
        "visible_injury", "sickness_felt", "height", "body_mass"],
    "T19/T20 matière (chaleur, chimie, vivant, eau, magie) pas écrites": [
        "process_progress", "process_started_at", "made_at", "plant_stage", "plant_yield", "plant_health", "plant_species",
        "soil_fertility", "soil_state", "soil_moisture", "deposit", "water_level", "water_flow", "water_quality", "ice",
        "fire_extent", "fire_heat", "fire_fuel", "fire_spread", "smoke", "magic_stability", "magic_attunement",
        "animal_product_ready", "load_margin", "visible_damage"],
    "faune et phénomènes (D29) : lois simples du moteur pas écrites": [
        "animal_species", "animal_fear_humans", "animal_aggression", "animal_attachment", "animal_group",
        "animal_tameness", "phenomenon_kind", "phenomenon_intensity", "phenomenon_effects", "phenomenon_signs",
        "trace_kind", "trace_freshness", "trace_direction", "trace_maker_cue", "hostility_drivers", "frontier_depth",
        "underground_depth"],
    "climat et calendrier : pas de station météo ni d'écriture des percepts de temps (T23 points ouverts)": [
        "wind", "cloud_cover", "precipitation", "fog", "storm", "snow_cover", "moon_phase", "calendar_params",
        "day_of_year", "year", "time_of_day", "game_time", "pp_weather_seen", "pp_sun", "pp_signs", "time_felt",
        "season_felt", "pp_smell_seen"],
    "population initiale et naissance (T47, T34) : écrivain `birth` pas réalisé": [],
    "carte mentale et lieux (T23b partiel) : dossiers LOCUS et lieu reconnu pas écrits": [
        "lc_dir", "lc_dist", "lc_file", "lc_kind", "lc_owner", "place_recognized", "place_bounds", "place_in",
        "inside_of"],
    "perception : champs déclarés que PerceptionEngine n'écrit pas (manque grave, voir docs/17 § 1)": [
        "ev_manner_seen", "pc_owner_believed", "own_held_seen", "posture_felt", "r_reputation_seen", "ep_gaze", "gaze",
        "attire_seen", "held_seen", "look_marks_seen", "look_build_seen", "involuntary_signs", "look_drunk_seen",
        "seen_direction", "seen_distance", "seen_motion", "expression", "look_age_seen", "look_sex_seen", "condition"],
    "tête de l'élève absente ou provisoire (T11, T12)": ["tastes", "attracted_to"],
    "bornes et capacités déclaratives (capacité fixe en v1, docs/14 § 7.5)": [
        "belief_capacity", "memory_store_capacity", "memory_capacity", "relation_capacity", "sim_depth"],
}


# ---------------------------------------------------------------------------------------------------------------------
def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def cpp_sources() -> dict[str, str]:
    """Hand-written C++ only: generated code, tests and benches are left out (they name every field)."""
    out = {}
    for d in CPP_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")):
            if p.suffix not in (".cpp", ".h", ".inc") or not p.is_file():
                continue
            rel = p.relative_to(ROOT).as_posix()
            if "/generated/" in rel or "/tests/" in rel or "/bench/" in rel or p.name.endswith("_gen.h"):
                continue
            out[rel] = _read(p)
    return out


def function_body(text: str, signature_regex: str) -> str:
    m = re.search(signature_regex, text)
    if not m:
        return ""
    i = text.find("{", m.end() - 1)
    depth, j = 0, i
    while j < len(text):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[m.start():j + 1]
        j += 1
    return text[m.start():]


def gen_field_names(path: Path) -> set[str]:
    return set(re.findall(r'^\s*\{"([a-z_0-9]+)",', _read(path), re.M))


def context_sources() -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    text = _read(CONTEXT_MAP)
    def block(name):
        m = re.search(name + r"\[\] = \{(.*?)\};", text, re.S)
        return re.findall(r'SourceDef\{"([^"]*)", "([^"]*)", "([^"]*)"\}', m.group(1)) if m else []
    return block("kSources"), block("kDerivedSources"), block("kListRecords")


def roadmap_tasks() -> dict[str, str]:
    """Process id -> first task of docs/15 whose block names it in backticks."""
    text = _read(ROADMAP)
    blocks = re.split(r"\n\*\*(T\d+[a-z]?) ", text)
    out = {}
    for k in range(1, len(blocks) - 1, 2):
        task, body = blocks[k], blocks[k + 1]
        for word in re.findall(r"`([a-z_]+)`", body):
            out.setdefault(word, task)
    return out


def anim_clips() -> set[str]:
    return set(re.findall(r"(?:clip|gait|strike)\(\s*['\"]([a-z_]+)['\"]", _read(ANIM_JS)))


# ---------------------------------------------------------------------------------------------------------------------
class Audit:
    def __init__(self):
        self.cat = Catalogue.load()
        self.V = self.cat["variable"]
        self.mi = json.loads(_read(MI) or "{}")
        self.reg = json.loads(_read(REG) or "{}")
        self.cpp = cpp_sources()
        self.cpp_all = "\n".join(self.cpp.values())
        self.executor = _read(EXECUTOR)
        self.timing = _read(TIMING)

    # ---- 1. gestures x layers -----------------------------------------------------------------------------------
    def behavior_classes(self) -> dict[str, str]:
        body = function_body(self.executor, r"const Behavior& behavior_of\(Gesture g\)")
        out = {}
        for seg in re.split(r"return (\w+);", body)[:-1:2] if body else []:
            pass
        parts = re.split(r"return (\w+);", body)
        for k in range(0, len(parts) - 1, 2):
            for g in re.findall(r"Gesture::(\w+)", parts[k]):
                out[g.rstrip("_")] = parts[k + 1]
        return out

    def params_read_by_executor(self) -> set[str]:
        names = set(re.findall(r'pv\("(\w+)"\)', self.executor))
        names |= set(re.findall(r'param_index\([^,]+,\s*"(\w+)"\)', self.executor))
        if "discreet()" in self.executor:
            names.add("stealth")
        body = function_body(self.executor, r"static int motion_value\(const Ctx& c\)")
        names |= set(re.findall(r'"(\w+)"', body))
        return names

    def gestures(self) -> dict:
        reg_g = {g["name"] for g in self.reg.get("gestures", [])}
        beh = self.behavior_classes()
        clips = anim_clips()
        read = self.params_read_by_executor()
        manner_seen_written = bool(re.search(r"(?:\.|->)ev_manner_seen\s*=", self.cpp_all))
        rows = {}
        for a in self.cat["action"].values():
            wanted = [c.lstrip("+") for c in a.animation]
            have = [c for c in wanted if c in clips]
            enums = [p for p in a.params if p.type == "enum"]
            manner_values = sum(len(p.values) for p in enums)
            unread = [p.name for p in enums if p.name not in read]
            eff = GESTURE_EFFECT.get(a.id, ("?", "non audité"))
            rows[a.id] = {
                "family": a.family,
                "catalogue": True,
                "registry": a.id in reg_g,
                "executor": beh.get(a.id, "absent"),
                "effect": eff[0], "effect_note": eff[1],
                "perceived_gesture": True,          # ev_gesture : tout geste qui émet une Operation act
                "perceived_manner": manner_seen_written,
                "governor": True,                    # check_gesture sur kGestures (GestureExecutor::begin)
                "minor_ok": a.minor_person_ok, "minor_whitelist": a.minor_whitelist,
                "intimate_values": {p.name: p.intimate_values for p in a.params if p.intimate_values},
                "clips_wanted": wanted, "clips_have": have,
                "animable": bool(have),
                "manner_params": [p.name for p in enums], "manner_values": manner_values,
                "manner_params_unread": unread,
            }
        return rows

    def manner_heads(self) -> list[dict]:
        out = []
        for h in self.reg.get("manner", []):
            out.append({"head": h["name"], "values": len(h["values"]), "capacity": h["capacity"]})
        return out

    # ---- 2. processes --------------------------------------------------------------------------------------------
    def processes(self) -> dict:
        impl = set()
        for p in sorted(LAWS_DIR.glob("*.cpp")) if LAWS_DIR.exists() else []:
            for name in re.findall(r"process\(\) const override \{ return ProcessId::(\w+); \}", _read(p)):
                impl.add(re.sub(r"(?<!^)([A-Z])", r"_\1", name).lower())
        if "collapse_.run" in _read(ROOT / "engine/act/process_engine.cpp"):
            impl.add("collapse")
        tasks = roadmap_tasks()
        rows = {}
        for p in self.cat["process"].values():
            if p.id in impl:
                state = "implemented"
            elif p.id in tasks or p.id in PLANNED_ELSEWHERE:
                state = "planned"
            else:
                state = "no_carrier"
            rows[p.id] = {"file": p.file, "clock": p.clock, "state": state,
                          "task": "T18" if p.id in impl else tasks.get(p.id) or PLANNED_ELSEWHERE.get(p.id, "")}
        return rows

    # ---- 3. variables --------------------------------------------------------------------------------------------
    def variables(self) -> dict:
        V = self.V
        cat = self.cat
        sources, derived_sources, list_records = context_sources()
        ctx_vars = {v for _, _, v in sources if v} | {v for _, _, v in derived_sources if v} | {v for _, _, v in list_records}
        ctx_derived = {v for _, _, v in derived_sources if v}
        reg_w = {w["name"] for w in self.reg.get("write_vars", [])} | {v for vs in self.reg.get("lists", {}).values() for v in vs}
        writable = set(self.mi.get("output", {}).get("writes", {}).get("writable", {}))
        law_w, law_r = defaultdict(list), defaultdict(list)
        for l in cat["law"].values():
            for v in l.variables:
                law_w[v].append(l.id)
            for v in list(l.reads) + list(l.depends_on):
                law_r[v].append(l.id)
        try:
            import gen_cpp
            rules = gen_cpp.PERCEPT_RULES
        except Exception:  # pragma: no cover - the generator is part of the catalogue
            rules = []
        perc_w = {t for t, *_ in rules}
        perc_r = {s for _, src, *_ in rules for s in src.split(",") if not s.startswith("~")}
        forget_r = set()
        for f in cat["forgetting"].values():
            forget_r |= set(f.protect) | {t.get("var") for t in f.score}
        gov = _read(GOVERNOR_PY) + _read(ROOT / "engine/social/src/governor.cpp")
        saved = gen_field_names(NPC_FIELDS) | gen_field_names(WORLD_GEN)
        out = {}
        for vid, v in V.items():
            pat = re.escape(vid)
            assign = re.search(r"(?:\.|->)" + pat + r"\b\s*(?:=(?!=)|\+=|-=|\|=|\+\+|--)", self.cpp_all) is not None
            assign = assign or re.search(r"\b" + pat + r"\s*=\s*find\(", self.cpp_all) is not None
            by_name = re.search(r'"' + pat + r'"', self.cpp_all) is not None
            mention = re.search(r"(?:\.|->|::)" + pat + r"\b", self.cpp_all) is not None
            wr = []
            if law_w.get(vid):
                wr.append("law")
            if vid in perc_w:
                wr.append("perception")
            if assign or by_name:
                wr.append("cpp")
            if vid in reg_w:
                wr.append("student")
            if vid in ctx_derived:
                wr.append("context_derived")
            rd = []
            if v.token and vid in ctx_vars:
                rd.append("token")
            if law_r.get(vid):
                rd.append("law")
            if vid in perc_r:
                rd.append("perception")
            if vid in forget_r:
                rd.append("forgetting")
            if mention or by_name:
                rd.append("cpp")
            if re.search(r"\b" + pat + r"\b", gov):
                rd.append("governor")
            model_w = [w for w in v.writer if w in MODEL_WRITERS]
            if wr and rd:
                cls = "live"
            elif wr:
                cls = "written_never_read"
            elif rd:
                cls = "read_never_written"
            else:
                cls = "dead"
            out[vid] = {
                "holder": v.holder, "scale": v.scale, "writer_declared": list(v.writer), "visibility": v.visibility,
                "token": v.token, "writers_real": wr, "readers_real": rd, "saved": vid in saved, "class": cls,
                "model_writable": bool(model_w), "in_interface_writable": vid in writable, "learnable": vid in reg_w,
                "no_law_reason": bool(v.no_law_reason), "dynamics": bool(v.dynamics),
                "birth_only": set(v.writer) <= {"birth"},
            }
        return out

    def variable_findings(self, vrows: dict) -> dict:
        V = self.V
        sources, derived_sources, list_records = context_sources()
        empty_fields = sorted(f"{t}.{f}" for t, f, v in sources if not v)
        ctx_vars = {v for _, _, v in sources if v}
        token_no_builder = sorted(vid for vid, v in V.items() if v.token and vid not in ctx_vars
                                  and vid not in {x for _, _, x in derived_sources} and vid not in {x for _, _, x in list_records})
        known_comps = {c.id for c in self.cat["component"].values() if c.channel and c.channel != "setting"} | {
            "belief", "relation", "episode", "goal", "intention", "request", "skill", "percept", "event_seen",
            "entity_percept", "place_percept", "locus"}
        no_token = sorted(vid for vid, v in V.items() if not v.token and v.holder in known_comps
                          and v.visibility != "engine" and v.scale != "id" and vid not in FORBIDDEN_TRUTHS)
        model_not_learnable = sorted(vid for vid, r in vrows.items() if r["model_writable"] and not r["learnable"])
        drifting_without_law = sorted(vid for vid, v in V.items() if v.no_law_reason and v.dynamics)
        exc = {v for vs in EXCEPTIONS.values() for v in vs}
        dead_like = {vid for vid, r in vrows.items() if r["class"] != "live"}
        return {
            "token_fields_without_variable": empty_fields,
            "token_variables_without_context_source": token_no_builder,
            "no_token_in_known_component": no_token,
            "model_writable_not_learnable": model_not_learnable,
            "no_law_but_declared_dynamics": drifting_without_law,
            "not_live_undeclared": sorted(dead_like - exc),
            "declared_but_live": sorted(exc & {vid for vid, r in vrows.items() if r["class"] == "live"}),
        }

    # ---- 4. cross checks -----------------------------------------------------------------------------------------
    def components_without_variables(self) -> list[str]:
        cnt = Counter(v.holder for v in self.V.values())
        return sorted(c.id for c in self.cat["component"].values() if cnt.get(c.id, 0) == 0)

    def state_properties_without_storage(self) -> list[str]:
        saved = gen_field_names(WORLD_GEN)
        return sorted(p.id for p in self.cat["property"].values() if p.category == "state" and p.id not in saved)

    def unused_concepts(self) -> list[str]:
        """Grammar concepts never cited by a probe (concepts, utterances, trace), an interpretation, a shape or the sampler."""
        corpus = []
        for s in self.cat["story"].values():
            corpus += s.concepts + s.utterances + s.trace
        for sh in self.cat["shape"].values():
            corpus.append(sh.pattern)
        for i in self.cat["interpretation"].values():
            corpus += i.cues + i.norms + i.facts
        for p in sorted((ROOT / "ai/situations").glob("*.py")):
            corpus.append(_read(p))
        text = "\n".join(corpus)
        return sorted(c for c in self.cat["concept"] if not re.search(r"(?<![a-z_])" + re.escape(c) + r"(?![a-z_])", text))

    def stories(self, grows: dict, vrows: dict) -> dict:
        """Expressible probes whose chain hits a gesture without real effect or a non-live variable."""
        out = {"expressible": 0, "engine_chain_complete": 0, "broken": {}}
        for s in self.cat["story"].values():
            if s.status != "expressible":
                continue
            out["expressible"] += 1
            weak_g = [a for a in s.actions if grows.get(a, {}).get("effect") in ("act", "none", "partial")]
            weak_v = [v for v in s.variables if vrows.get(v, {}).get("class") not in (None, "live")]
            if weak_g or weak_v:
                out["broken"][s.id] = {"gestures": weak_g, "variables": weak_v}
            else:
                out["engine_chain_complete"] += 1
        return out

    def budgets(self, vrows: dict) -> dict:
        import budget
        cap = self.reg.get("capacity", {})
        heads = self.manner_heads()
        return {
            "gestures": [len(self.cat["action"]), budget.MAX_GESTURES],
            "conditions": [len(self.reg.get("conditions", [])), cap.get("conditions", 32)],
            "tokens": [sum(budget.TOKENS.values()), budget.MAX_TOKENS],
            "grammar_words": [len(json.loads(_read(ROOT / "catalogue/generated/vocab_registry.json") or "{}").get("words", [])),
                              budget.GRAMMAR_WORDS_MAX],
            "kinds": [len(json.loads(_read(ROOT / "catalogue/generated/vocab_registry.json") or "{}").get("kinds", [])),
                      budget.KINDS_MAX],
            "writable_interface": [len(self.mi.get("output", {}).get("writes", {}).get("writable", {})), cap.get("write_vars", 128)],
            "writable_registry": [len(self.reg.get("write_vars", [])), cap.get("write_vars", 128)],
            "enum_values": [len(self.reg.get("enum_values", [])), cap.get("enum_values", 128)],
            "manner_heads": [len(heads), cap.get("manner_heads", 64)],
            "manner_heads_full": sorted(h["head"] for h in heads if h["values"] >= h["capacity"]),
            "plan_steps": [self.reg.get("plan_steps_used", 0), cap.get("plan_steps", 8)],
            "writes_per_decision": budget.WRITES_PER_DECISION,
            "intentions": next((c.max_count for c in self.cat["component"].values() if c.id == "intention"), 0),
            "object_vector": [len(self.cat.object_vector()), budget.OBJECT_VECTOR_MAX],
        }

    def code_fingerprint(self) -> str:
        parts = [function_body(self.executor, r"const Behavior& behavior_of\(Gesture g\)"),
                 function_body(self.timing, r"Manner manner_of\(Gesture g, int v\)")]
        return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]

    # ---- all -----------------------------------------------------------------------------------------------------
    def run(self) -> dict:
        g = self.gestures()
        pr = self.processes()
        vr = self.variables()
        cls = Counter(r["class"] for r in vr.values())
        findings = self.variable_findings(vr)
        return {
            "schema": "completeness-1",
            "counts": {
                "gestures": len(g),
                "gestures_registry": sum(r["registry"] for r in g.values()),
                "gestures_executor": sum(r["executor"] not in ("absent", "meta") for r in g.values()),
                "gesture_effect": dict(Counter(r["effect"] for r in g.values())),
                "gestures_animable": sum(r["animable"] for r in g.values()),
                "gestures_all_clips": sum(len(r["clips_have"]) == len(r["clips_wanted"]) for r in g.values()),
                "manner_values": sum(r["manner_values"] for r in g.values()),
                "manner_perceived": g and next(iter(g.values()))["perceived_manner"],
                "processes": len(pr),
                "process_state": dict(Counter(r["state"] for r in pr.values())),
                "variables": len(vr),
                "variable_class": dict(cls),
                "variables_saved": sum(r["saved"] for r in vr.values()),
                "variables_with_token": sum(bool(r["token"]) for r in vr.values()),
                "no_law_reason": sum(r["no_law_reason"] for r in vr.values()),
                "components_without_variables": len(self.components_without_variables()),
                "concepts_never_used": len(self.unused_concepts()),
            },
            "gestures": g,
            "manner_heads": self.manner_heads(),
            "processes": pr,
            "variables": vr,
            "variable_findings": findings,
            "components_without_variables": self.components_without_variables(),
            "state_properties_without_storage": self.state_properties_without_storage(),
            "concepts_never_used": self.unused_concepts(),
            "stories": self.stories(g, vr),
            "budgets": self.budgets(vr),
            "code_fingerprint": self.code_fingerprint(),
            "exceptions": EXCEPTIONS,
        }


def summary(r: dict) -> str:
    c = r["counts"]
    lines = [
        f"gestes {c['gestures']} : registre {c['gestures_registry']}, exécuteur {c['gestures_executor']}, effet {c['gesture_effect']}, "
        f"animables {c['gestures_animable']} (tous leurs clips : {c['gestures_all_clips']}), manière perçue par les témoins : {c['manner_perceived']}",
        f"processus {c['processes']} : {c['process_state']}",
        f"variables {c['variables']} : {c['variable_class']} ; sauvées {c['variables_saved']} ; avec jeton {c['variables_with_token']} ; "
        f"no_law_reason {c['no_law_reason']}",
        f"composants sans variable : {r['components_without_variables']}",
        f"propriétés d'état sans stockage d'instance : {r['state_properties_without_storage']}",
        f"concepts jamais exercés : {c['concepts_never_used']}",
        f"sondes exprimables {r['stories']['expressible']}, chaîne moteur complète {r['stories']['engine_chain_complete']}",
        f"budgets : {r['budgets']}",
        f"non vivantes non déclarées : {r['variable_findings']['not_live_undeclared']}",
        f"déclarées mortes mais vivantes : {r['variable_findings']['declared_but_live']}",
        f"empreinte du code audité : {r['code_fingerprint']}",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--list", choices=["live", "written_never_read", "read_never_written", "dead"])
    a = ap.parse_args(argv)
    r = Audit().run()
    if a.list:
        print("\n".join(sorted(v for v, x in r["variables"].items() if x["class"] == a.list)))
    elif a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1, sort_keys=True, default=list))
    else:
        print(summary(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
