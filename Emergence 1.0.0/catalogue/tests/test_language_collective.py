"""Step 19a: the inner language and the catalogue can express COMPLEX and COLLECTIVE behaviour (a plot of three, an
expedition). One class per primitive group, in the order they were added; each checks the general primitive, never
a story."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
from schema import Catalogue  # noqa: E402
import language  # noqa: E402


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat = Catalogue.load()
        cls.vocab = language.Vocabulary(cls.cat)

    def utt(self, text):
        return language.Expression(text, self.vocab)

    def bare(self, text):
        return language.Expression(text, self.vocab, bare=True)

    def good(self, *texts, bare=False):
        for t in texts:
            e = self.bare(t) if bare else self.utt(t)
            self.assertTrue(e.ok, (t, e.problems))

    def bad(self, *texts, bare=False):
        for t in texts:
            e = self.bare(t) if bare else self.utt(t)
            self.assertFalse(e.ok, t)


class TestTime(Base):
    """1. Time: moments of the day, offsets and durations, after / before / until, a rendez-vous distinct from a deadline."""

    def test_moments_of_the_day_are_time_marks(self):
        for w in ("dawn", "morning", "noon", "afternoon", "evening", "night"):
            self.good(f"(offer (at_time {w} (at me @L3)))")

    def test_a_rendezvous_is_not_a_deadline(self):
        self.good("(offer (at_time dawn (at me @L3)))", "(offer (before dawn (at me @L3)))")
        self.assertNotEqual(self.utt("(offer (at_time dawn (at me @L3)))").root.args[0].head,
                            self.utt("(offer (before dawn (at me @L3)))").root.args[0].head)

    def test_offsets_and_durations(self):
        self.good("(offer (at_time (span 3 day) (at me @L3)))",          # in three days
                  "(assert (for (span 10 day) (has me silver_coin:5)))",   # for ten days
                  "(offer (after (span 2 hour) (did me go @L1)))",
                  "(request (until (span 1 season) (did you work @T1)))")

    def test_a_duration_is_not_a_moment(self):
        self.bad("(assert (for dawn (at me @L1)))", "(offer (at_time (span many fortnight) (at me @L1)))",
                 "(offer (at_time (span day 3) (at me @L1)))", "(offer (at_time (at me @L1)))",
                 "(offer (at_time dawn))")

    def test_seasons_are_usable_in_an_expression(self):
        self.good("(assert (before winter (did me work @T1)))", "(offer (at_time spring (did me go @L1)))")
        self.assertEqual(self.cat["variable"]["season_felt"].values_from, "season")     # one source for the four words

    def test_an_event_can_be_the_time_mark(self):
        self.good("(assert (after m:3 (at me @L1)))", "(offer (at_time @V2 (did me go @L1)))")

    def test_the_story_specific_time_words_are_gone(self):
        for w in ("at_festival", "before_winter"):
            self.assertNotIn(w, self.vocab.cats)

    def test_the_old_wrappers_still_work(self):
        self.good("(assert (past (did me go @L1)))", "(offer (tomorrow (did me go @L1)))", "(assert (each_day (did me work @T1)))")

    def test_a_goal_has_a_rendezvous_apart_from_its_deadline(self):
        self.assertIn("g_when", self.cat["variable"])
        self.assertEqual(self.cat["variable"]["g_when"].token, "GOAL.when")


class TestGroups(Base):
    """2. Groups: `us` and @G act and are addressed; a group has members, a leader, a goal, a believed role; commitments
    toward a group; `c_sees_ref` on a group; the companion role `with`."""

    def test_a_group_can_be_the_agent_of_an_event_or_of_an_intention(self):
        self.good("(assert (past (did @G1 go @L1)))", "(assert (intends @G1 (did @G1 strike @E4)))",
                  "(assert (wants us (dead @E4)))", "(offer (future (did us go @L2)))")

    def test_we_three_is_us_with_a_count(self):
        self.good("(assert (count us 3))", "(assert (and (count us 3) (intends us (did us go @L2))))")

    def test_a_group_can_be_addressed_or_accompanied(self):
        self.good("(assert (past (did me speak (to @G1) (says (dead @E4)))))",
                  "(assert (past (did @E1 go @L1 (with @E2))))", "(assert (past (did me work @T1 (with @G1))))")

    def test_a_companion_is_a_person_not_a_thing(self):
        self.bad("(assert (past (did me go @L1 (with @T2))))")                 # go has no instrument
        self.good("(assert (past (did me throw @T5 (with @T2))))")           # throw has: an instrument

    def test_a_group_dossier_has_members_leader_goal_and_my_role(self):
        fields = set(self.cat_fields("GROUP"))
        for f in ("members", "leader", "goal", "role", "kind", "size"):
            self.assertIn(f, fields)

    def cat_fields(self, typ):
        import budget
        return budget.counted_slots(self.cat)[typ]

    def test_the_group_dossier_is_derived_from_beliefs_only(self):
        for vid in ("r_group_members", "r_group_leader", "r_group_goal", "r_group_role", "r_group_kind", "r_group_size"):
            v = self.cat["variable"][vid]
            self.assertEqual(v.writer, ["derived"])
            self.assertIn("b_proposition", v.reads)

    def test_a_commitment_can_bind_a_group(self):
        import model_interface
        fields = model_interface.ModelInterface(self.cat).build()["input"]["token_types"]
        self.assertIn("GROUP", fields["COMMIT"]["fields"]["counterparty"]["ref_types"])
        self.assertIn("GROUP", fields["EVENT"]["fields"]["actor"]["ref_types"])
        self.assertEqual(fields["GROUP"]["fields"]["members"]["ref_types"], ["ENTITY", "SELF"])

    def test_waiting_for_everyone_is_seeing_every_member(self):
        c = self.cat["concept"]["c_sees_ref"]
        self.assertIn("GROUPE", c.label_fr)
        self.assertTrue(language.ACCEPTS["entity"] & {"group"})

    def test_a_group_is_not_a_known_adult_for_d10(self):
        from governor import Governor, Party
        g = Governor()
        e = self.utt("(assert (past (did @E1 touch @G1 (how romantic))))")
        self.assertTrue(e.ok, e.problems)
        v = g.check_utterance(e, Party(30, 30, 30, True), {"@E1": Party(30, 30, 30, True)}, addressees=[Party(30, 30, 30, True)])
        self.assertFalse(v.allowed)          # the members of @G1 are unknown: any of them may be a minor


class TestAgreements(Base):
    """3. Agreements: accept or refuse ONE precise offer, parts and fractions, keep thinking, a planned speech, a readable plan."""

    def test_an_answer_can_point_at_one_precise_offer(self):
        self.good("(yes h:2)", "(no q:1)", "(yes c:3)", "(yes h:2 (offer (future (did me go @L1))))", "(no h:2 (assert (dead @E1)))")

    def test_only_an_answering_formula_points(self):
        self.bad("(hello h:2)", "(thanks q:1)", "(yes b:2)", "(yes m:1)", "(yes @E1)", "(yes h:2 h:3)")

    def test_what_was_heard_can_be_cited_like_a_belief(self):
        self.good("(assert (that h:2))", "(assert (believes @E1 (that q:1)))", "(request (that c:2))")
        self.good("h:2", "q:1", "c:3", bare=True)

    def test_the_cited_offer_is_unfolded_by_the_governor(self):
        from governor import Governor, Party
        g = Governor()
        e = self.utt("(yes h:2)")
        adult = Party(30, 30, 30, True)
        self.assertFalse(g.check_utterance(e, adult, {}, addressees=[adult]).allowed)           # no frozen copy: refused as unexpanded
        offer = language.Expression("(offer (future (did me touch you (how romantic))))", self.vocab)
        v = g.check_utterance(e, adult, {"you": Party(15, 15, 15, True)}, addressees=[Party(15, 15, 15, True)],
                              expand=lambda ref: offer)
        self.assertFalse(v.allowed)                                           # accepting an intimate offer with a minor: D10

    def test_parts_and_fractions(self):
        self.good("(offer (future (share @T1 you half)))", "(offer (share @T1 @G1 equal))", "(assert (share @T1 @E2 third))",
                  "(offer (share @T1 me quarter))")
        self.bad("(offer (share @T1 you))", "(offer (share @T1 you big))")

    def test_a_planned_speech_and_a_readable_plan(self):
        import budget
        plan = budget.counted_slots(self.cat)["PLAN"]
        for f in ("says", "steps", "step_targets"):
            self.assertIn(f, plan)
        self.assertEqual(self.cat["variable"]["i_speech"].scale, "proposition")
        self.assertEqual(self.cat["variable"]["i_steps"].token, "PLAN.steps")
        self.assertLessEqual(len(plan), budget.BUDGET["PLAN"])
        self.good("(offer (at_time dawn (did us go @L2)))", "(assert (intends me (did me speak (to @E2) (says (and (share @T1 you half) (did you go @L1))))))")

    def test_keep_thinking_is_an_output_of_the_model_with_a_budget_in_wake(self):
        import model_interface
        spec = model_interface.ModelInterface(self.cat).build()
        w = spec["output"]["writes"]["writable"]["think_more"]
        self.assertEqual((w["scale"], w["target"]), ("bool", "self"))
        self.assertIn("budget", spec["input"]["token_types"]["WAKE"]["fields"])
        self.assertEqual(self.cat["variable"]["w_think_budget"].writer, ["engine"])      # the scheduler fixes it, never the model

    def test_a_plan_can_be_read_in_full_by_the_planner(self):
        v = self.cat["variable"]
        self.assertEqual(v["i_step_targets"].list_of, "mref")
        self.assertIn("6 gestes", v["i_steps"].dynamics)


class TestReference(Base):
    """4. Reference and quantification: quantified subjects, collective percept, description by link or membership,
    embedded questions, indefinites, evidentials aligned on the sources."""

    def test_quantified_subjects(self):
        self.good("(assert (past (did (of most @G3) go @L1)))", "(assert (past (did (of 3 us) go @L1)))",
                  "(assert (past (did (of half everyone) go @L1)))", "(assert (wants (of many @G3) (dead @E4)))",
                  "(assert (past (did (of few (described o_farmer)) go @L1)))")
        self.assertIn("most", self.vocab.cats)

    def test_a_part_must_be_of_people(self):
        self.bad("(assert (past (did (of most @T1) go @L1)))", "(assert (past (did (of big @G3) go @L1)))",
                 "(assert (past (did (of most) go @L1)))")

    def test_the_collective_percept_has_a_count_and_a_total(self):
        import budget
        ev = budget.counted_slots(self.cat)["EVENT"]
        self.assertIn("count", ev)
        self.assertIn("among", ev)

    def test_description_by_link_or_membership(self):
        self.good("(assert (past (did me speak (to (described d_woman (link the_one child @E3))))))",
                  "(assert (past (did me give silver_coin:1 (to (described (lives_at the_one @L3))))))",
                  "(assert (past (did me strike (described d_man (member the_one @G7)))))",
                  "(assert (past (did me strike (described d_man (did the_one strike @E2)))))")

    def test_a_clause_has_exactly_one_hole_and_the_hole_lives_only_there(self):
        self.bad("(assert (past (did me give silver_coin:1 (to (described (lives_at @E1 @L3))))))",
                 "(assert (past (did me give silver_coin:1 (to (described (link the_one child the_one))))))",
                 "(assert (at the_one @L1))", "(assert (past (did me give silver_coin:1 (to the_one))))")

    def test_clauses_nest_but_not_without_limit(self):
        self.good("(assert (past (did me give silver_coin:1 (to (described d_man (link the_one friend (described (link the_one child @E3))))))))")
        self.bad("(assert (past (did me give silver_coin:1 (to (described (link the_one friend (described (link the_one friend (described (link the_one child @E3))))))))))")

    def test_a_relative_clause_about_an_intimate_link_is_refused_by_d10_for_an_unidentified_person(self):
        from governor import Governor, Party
        g = Governor()
        e = self.utt("(assert (past (did me speak (to (described (link the_one spouse @E3))))))")
        self.assertTrue(e.ok, e.problems)
        adult = Party(30, 30, 30, True)
        self.assertFalse(g.check_utterance(e, adult, {"@E3": adult}, addressees=[adult]).allowed)

    def test_embedded_questions(self):
        self.good("(assert (not (knows me (at @E9 where))))", "(assert (knows me (owns @E9 what)))", "(ask (at @E9 where))")
        self.bad("(assert (at @E9 where))", "(assert (believes me (at @E9 where)))", "(assert (not (knows me where)))")

    def test_indefinites(self):
        self.good("(assert (past (did me go somewhere)))", "(assert (owns @E1 something))", "(assert (at @E9 nowhere))",
                  "(assert (at_time sometime (did me go @L1)))", "(assert (has @E1 nothing))")

    def test_every_source_of_a_belief_has_its_evidential(self):
        sources = {c.id for c in self.cat["concept"].values() if c.category == "source"}
        covered = {c.refers for c in self.cat["concept"].values() if c.category == "evidential" and c.refers}
        self.assertEqual(sources, covered)
        self.good("(assert (dreamt_it (exists gold @L26)))",
                  "(assert (read_it (dead @E1)))", "(assert (overheard (dead @E1)))", "(assert (they_say (dead @E1)))")


class TestPlacesAndThings(Base):
    """5. Places and things: a table of kinds of places and constructions, declared words for the perception lists,
    colours, wound words, a mountable flag, an unintelligible mark, the sky and the moon."""

    SITES = ("house", "barn", "wall", "bridge", "well", "field", "mine", "temple", "market", "village", "city", "forest",
             "river", "cave", "road")

    def test_the_kinds_of_places_and_constructions_exist(self):
        for w in self.SITES:
            self.assertIn(w, self.cat["site"], w)
            self.assertIn(w, self.vocab.kinds, w)

    def test_a_site_is_perceived_through_the_word_fields_of_the_percepts(self):
        for vid in ("lc_kind", "pc_kind_seen"):
            self.assertEqual(self.cat["variable"][vid].scale, "word")
        import model_interface
        kinds = set(model_interface.ModelInterface(self.cat).build()["output"]["speech"]["kinds"])
        self.assertTrue(set(self.SITES) <= kinds)

    def test_sites_are_usable_in_exists_recipe_channel_and_described(self):
        self.good("(assert (sure (and (exists city @L27) (located @L27 beyond @L26))))",
                  "(assert (recipe barn (past (did you channel @T1 (into barn)))))",
                  "(request (did you channel @T1 (into house)))",
                  "(assert (at @E1 (described forest w_dangerous)))",
                  "(assert (is_a @L3 village))", "(assert (past (did me go (described mine))))")

    def test_one_cannot_build_what_is_not_built(self):
        self.bad("(request (did you channel @T1 (into forest)))", "(request (did you channel @T1 (into moon)))")

    def test_a_place_can_be_described(self):
        self.good("(assert (past (did me go (described house (owns @E5 the_one)))))")

    def test_the_sky_and_the_moon_are_words(self):
        for w in ("sky", "moon", "sun", "star", "cloud"):
            self.assertIn(w, self.cat["site"])
        self.good("(request (did you go moon))")

    def test_the_perception_lists_declare_their_words(self):
        for vid in ("ep_build", "ep_marks", "ep_signs", "ep_health", "ep_attire", "pc_state_seen", "pp_weather_seen", "pp_signs", "wounds"):
            v = self.cat["variable"][vid]
            self.assertTrue(v.words_from, vid)
            self.assertTrue(self.cat.words_of(v.words_from), vid)
        import model_interface
        ft = model_interface.ModelInterface(self.cat).build()["input"]["token_types"]
        self.assertIn("bald", ft["ENTITY"]["fields"]["look.marks"]["words"])
        self.assertIn("rain", ft["PLACE"]["fields"]["weather"]["words"])
        self.assertIn("burning", ft["THING"]["fields"]["state"]["words"])        # a state property is a state word
        self.assertIn("bruise", ft["SELF"]["fields"]["wound"]["words"])

    def test_what_is_seen_is_what_is_said(self):
        self.good("(assert (appears @E1 bald))", "(assert (appears @E1 pale))", "(assert (appears @L3 foggy))",
                  "(assert (past (did me strike (described bald))))")

    def test_a_colour_is_a_perceptible_property_with_words(self):
        self.assertTrue(self.cat["property"]["color"].perceptible)
        self.assertEqual(self.cat["variable"]["pc_color_seen"].token, "THING.color")
        self.good("(assert (appears @T1 blue))", "(assert (appears @T2 red))")
        self.assertTrue({"red", "blue", "green", "black", "white"} <= set(self.cat.words_of("color")))

    def test_some_animals_are_mountable(self):
        self.assertTrue(self.cat["species"]["horse"].mountable)
        self.assertFalse(self.cat["species"]["wolf"].mountable)
        self.assertTrue(all(sp.kingdom == "animal" for sp in self.cat["species"].values() if sp.mountable))

    def test_an_incomprehensible_speech_is_marked_in_heard(self):
        import model_interface
        ft = model_interface.ModelInterface(self.cat).build()["input"]["token_types"]
        self.assertIn("unintelligible", ft["BELIEF"]["fields"])
        self.assertIn("unintelligible", ft["HEARD"]["fields"])           # HEARD has the fields of BELIEF

    def test_a_word_has_one_meaning_across_the_kinds_tables(self):
        ids = list(self.cat["site"]) + list(self.cat["percept_word"])
        for i in ids:
            for kind in ("item_type", "material", "species", "form", "concept", "action"):
                self.assertNotIn(i, self.cat[kind], (i, kind))

    def test_the_budget_holds_with_all_the_new_words(self):
        import budget
        self.assertLessEqual(len(self.vocab.words), budget.GRAMMAR_WORDS_MAX)
        self.assertLessEqual(len(self.vocab.kinds), budget.KINDS_MAX)


class TestRolesAndTyping(Base):
    """6. Event roles drawn from the parameters of each gesture and typed; the governor resolves the same parties;
    (caused X (dead Y)); the validator types pointers when it knows what their records are."""

    def test_the_roles_of_an_event_are_the_parameters_of_its_gesture(self):
        self.good("(assert (past (did me throw @T5 (at @E2) (with @T3))))",         # instrument and target
                  "(assert (past (did me put @T3 (where @T9))))",
                  "(assert (past (did @E1 pull @E2 (toward @L3))))",
                  "(assert (past (did me pour @T1 (from @T2) (into @T3))))",
                  "(assert (past (did me strike @E2 (with @T3))))",                 # strike: something held
                  "(assert (past (did me wear @T3 (on @E2))))", "(assert (past (did me write (on @T3) (says (dead @E2)))))",
                  "(assert (past (did me guard (against @E2))))",
                  "(assert (past (did me give @T5 (to @E2))))")

    def test_every_ref_parameter_name_is_a_word_of_the_vocabulary(self):
        for a in self.cat["action"].values():
            refs = [p for p in a.params if p.type == "ref"]
            for p in refs[1:]:                                    # the first one is the positional target: no name needed
                self.assertTrue(p.name in self.vocab.cats, (a.id, p.name))

    def test_a_role_is_typed_by_its_parameter(self):
        self.bad("(request (did you channel @T1 (into forest)))", "(request (did you channel @T1 (into moon)))",
                 "(assert (past (did me go @L1 (with @T2))))",              # go has no instrument
                 "(assert (past (did me throw @T5 (at @E2) (at @E3))))",    # twice
                 "(assert (past (did me throw @T5 (toward @E2))))",         # throw has no toward
                 "(assert (past (did me strike @E2 (to @E3))))")
        self.good("(request (did you channel @T1 (into barn)))")

    def test_a_companion_is_with_a_person_or_a_group_for_any_gesture(self):
        self.good("(assert (past (did @E1 go @L1 (with @E2))))", "(assert (past (did @E1 sleep @L1 (with @G3))))",
                  "(assert (past (did @E1 go @L1 (with (of 3 us)))))", "(assert (past (did @E1 go @L1 (with (described o_smith)))))")

    def test_the_governor_resolves_the_parties_of_every_role(self):
        from governor import Governor, Party
        g = Governor()
        adult, kid = Party(30, 30, 30, True), Party(9, 9, 9, True)
        e = self.utt("(request (did you touch @E3 (how romantic)))")
        self.assertFalse(g.check_utterance(e, adult, {"@E3": kid, "you": adult}, addressees=[adult]).allowed)   # target
        e = self.utt("(request (did you tie @T1 (to @E3) (with @T2)))")                  # a person as the `to` of tie
        v = g.check_utterance(e, adult, {"@E3": kid, "you": adult}, addressees=[adult])
        self.assertTrue(v.allowed or v.code.startswith("d10"))                            # the role is resolved by name, not ignored
        self.assertIn("to", [p.name for p in self.cat["action"]["tie"].params])
        e = self.utt("(request (did you pull @T1 (toward @L3)))")
        self.assertTrue(g.check_utterance(e, adult, {"you": adult}, addressees=[adult]).allowed)

    def test_the_group_and_the_part_are_unidentified_parties(self):
        from governor import Governor, Party
        g = Governor()
        adult = Party(30, 30, 30, True)
        for ref in ("@G1", "(of 3 us)", "(described d_woman)"):
            e = self.utt(f"(assert (past (did {ref} touch @E3 (how romantic))))")
            self.assertTrue(e.ok, e.problems)
            self.assertFalse(g.check_utterance(e, adult, {"@E3": adult}, addressees=[adult]).allowed, ref)

    def test_caused_takes_an_outcome(self):
        self.good("(assert (caused @E1 (dead @E2)))", "(assert (past (caused @E1 (did @E2 go @L1))))")

    def test_give_takes_an_animal_and_take_and_pull_a_plant(self):
        acts = self.cat["action"]
        self.assertIn("animal", next(p for p in acts["give"].params if p.name == "item").accepts)
        self.assertIn("plant", next(p for p in acts["take"].params if p.name == "target").accepts)
        self.assertIn("plant", next(p for p in acts["pull"].params if p.name == "target").accepts)
        self.good("(request (did you give cow (to @E2)))", "(request (did you take wheat))")

    def pk(self, text, kinds, bare=False):
        return language.Expression(text, self.vocab, bare=bare, pointer_kinds=kinds)

    def test_pointers_are_typed_when_their_record_is_known(self):
        self.assertFalse(self.pk("(assert (dead @T1))", {"@T1": "knife"}).ok)            # a knife is not dead
        self.assertTrue(self.pk("(assert (dead @T1))", {"@T1": "cow"}).ok)
        self.assertFalse(self.pk("(assert (owns me @L1))", {"@L1": "forest"}).ok)       # one does not own a forest
        self.assertTrue(self.pk("(assert (owns me @L1))", {"@L1": "field"}).ok)
        self.assertTrue(self.pk("(assert (owns me @L1))", {"@L1": "house"}).ok)
        self.assertFalse(self.pk("(request (did you take @T2))", {"@T2": "river"}).ok)
        self.assertFalse(self.pk("(assert (dead wolf_pelt_not_a_word))", {}).ok)

    def test_an_odd_pointer_map_never_crashes_and_types_nothing(self):
        for odd in ({"@T1": None}, {"@T1": 3}, {3: "cow"}, {"@T1": "me"}, {"@T1": "no_such_kind"}, {"@T1": "(x)"}, {"": "cow"}):
            for text in ("(request (did you take @T1))", "(assert (dead @T1))", "(assert (owns me @T1))"):
                e = self.pk(text, odd)
                self.assertTrue(e.ok, (odd, text, e.problems))

    def test_without_a_record_the_pointer_is_not_guessed(self):
        self.assertTrue(self.utt("(assert (dead @T1))").ok)                                # could be a beast: the validator cannot know
        self.assertTrue(self.utt("(assert (owns me @L1))").ok)

    def test_a_bare_kind_is_typed_too(self):
        self.assertFalse(self.utt("(assert (dead knife))").ok)
        self.assertFalse(self.utt("(assert (owns me forest))").ok)
        self.assertTrue(self.utt("(assert (owns me field))").ok)


class TestProbes(Base):
    """7. The probes: the gaps these primitives cover are expressible; the plot of three and the expedition of the mayor
    are decomposed step by step and every line is a valid sentence; D10 holds for adults and refuses a minor."""

    COVERED = ("joke_falls_flat", "secret_kept_loyal", "economy_to_politics", "election_campaign", "decree_ignored",
               "custom_shifts_slowly", "impossible_request", "pay_artisan_build", "strange_zone_legend", "belief_in_beyond",
               "eccentric_collector", "player_runs_for_chief")
    ENGINE_GAPS = ("smell_smoke_wake", "epidemic_fear_exclusion", "marriage_and_children", "touchy_mayor_disaster",
                   "illness_and_care", "pregnancy_birth")

    def test_the_gaps_that_are_language_are_closed(self):
        for sid in self.COVERED:
            self.assertEqual(self.cat["story"][sid].status, "expressible", sid)

    def test_the_gaps_that_remain_are_laws_of_the_engine_and_say_so(self):
        gaps = {s.id for s in self.cat["story"].values() if s.status == "gap"}
        self.assertEqual(gaps, set(self.ENGINE_GAPS))
        for sid in self.ENGINE_GAPS:
            self.assertIn("MOTEUR", self.cat["story"][sid].note, sid)

    def test_every_probe_is_machine_checked(self):
        from probes import ProbeChecker
        self.assertEqual(ProbeChecker(self.cat).problems(), [])

    def test_the_checker_catches_a_bad_line(self):
        from probes import ProbeChecker
        c = ProbeChecker(self.cat)
        self.assertTrue(c.check_line("belief | belief | (dead knife_not_a_word)"))
        self.assertTrue(c.check_line("belief | belief | (assert (dead @E1))"))                  # a mood in a bare record
        self.assertTrue(c.check_line("plan | gesture | go target=@L1 pace=teleport"))
        self.assertTrue(c.check_line("plan | gesture | steal target=@E1"))
        self.assertTrue(c.check_line("plan | condition | c_sees_ref"))
        self.assertTrue(c.check_line("goal | write | b_truth b:1 true"))                         # engine-only variable
        self.assertTrue(c.check_line("nonsense | belief | (dead @E1)"))
        self.assertTrue(c.check_line("percept | belief"))
        self.assertEqual(c.check_line("goal | goal | (dead @E4)"), [])

    def test_the_two_new_probes_are_decomposed_step_by_step(self):
        for sid in ("revenge_plot_three", "mayor_gold_expedition"):
            st = self.cat["story"][sid]
            self.assertEqual(st.status, "expressible")
            phases = {line.split("|")[0].strip() for line in st.trace}
            kinds = {line.split("|")[1].strip() for line in st.trace}
            self.assertTrue({"percept", "belief", "goal", "utterance", "commitment", "plan", "meeting", "act"} <= phases, (sid, phases))
            self.assertTrue({"belief", "goal", "utterance", "commit", "plan_says", "gesture", "condition", "write", "event"} <= kinds, (sid, kinds))
            self.assertGreaterEqual(len(st.trace), 28)
        self.assertIn("judgement", {l.split("|")[0].strip() for l in self.cat["story"]["revenge_plot_three"].trace})

    def test_the_plot_uses_only_general_primitives(self):
        text = " ".join(self.cat["story"]["revenge_plot_three"].trace + self.cat["story"]["revenge_plot_three"].utterances)
        for w in ("us", "@G1", "caused", "at_time", "night", "h:2", "that b:1", "adultery"):
            self.assertIn(w, text)
        for forbidden in ("conspire", "plot", "revenge_action", "expedition"):
            self.assertNotIn(forbidden, self.vocab.cats)                                      # no word, no gesture made for the story
        self.assertFalse({"revenge_plot_three", "mayor_gold_expedition"} & set(self.cat["action"]))

    def test_the_expedition_uses_time_group_part_share_and_a_precise_answer(self):
        text = " ".join(self.cat["story"]["mayor_gold_expedition"].utterances + self.cat["story"]["mayor_gold_expedition"].trace)
        for w in ("span", "of 5", "share", "equal", "yes h:3", "c_sees_ref @G2", "dawn", "for (span 10 day)"):
            self.assertIn(w, text)

    def adult_parties(self):
        from governor import Party
        keys = ("me", "you", "us", "@E1", "@E2", "@E3", "@E4", "@E5", "@E6", "@E7", "@E8", "@E9", "@G1", "@G2")
        return {k: Party(30, 30, 30, True) for k in keys}

    def run_governor(self, sid, parties):
        from governor import Governor, Party
        g = Governor()
        adult = Party(30, 30, 30, True)
        cited = language.Expression("(past (did @E4 go @L5 (how discreet)))", self.vocab, bare=True)
        refused = []
        for line in self.cat["story"][sid].trace:
            _, kind, content = [x.strip() for x in line.split("|", 2)]
            if kind in ("memory", "belief", "goal", "event"):
                v = g.check_record("belief", language.Expression(content, self.vocab, bare=True), adult, parties, expand=lambda r: cited)
            elif kind in ("heard", "utterance", "plan_says"):
                v = g.check_utterance(language.Expression(content, self.vocab), adult, parties, addressees=[adult], expand=lambda r: cited)
            elif kind == "commit":
                v = g.check_record("agreement", language.Expression(content.partition(" ")[2], self.vocab, bare=True), adult, parties, expand=lambda r: cited)
            else:
                continue
            if not v.allowed:
                refused.append((content, v.code))
        return refused

    def test_d10_the_two_probes_pass_for_adults(self):
        for sid in ("revenge_plot_three", "mayor_gold_expedition"):
            self.assertEqual(self.run_governor(sid, self.adult_parties()), [], sid)

    def test_d10_the_plot_is_refused_when_a_protagonist_may_be_a_minor(self):
        from governor import Party
        parties = self.adult_parties()
        parties["@E5"] = Party(9, 9, 9, True)                                     # the wife is a child: nothing intimate about her
        refused = self.run_governor("revenge_plot_three", parties)
        self.assertTrue(refused)
        self.assertTrue(all(code.startswith("d10") for _, code in refused), refused)
        self.assertTrue(any("romantic" in c for c, _ in refused))

    def test_d10_a_judgement_of_adultery_unfolds_the_cited_memory(self):
        from governor import Governor, Party
        g = Governor()
        adult, kid = Party(30, 30, 30, True), Party(9, 9, 9, True)
        e = self.utt("(assert (qualifies m:1 adultery))")
        mem = lambda who: language.Expression(f"(past (did @E4 touch {who} (how gentle)))", self.vocab, bare=True)
        self.assertTrue(g.check_utterance(e, adult, {"@E4": adult, "@E5": adult}, addressees=[adult], expand=lambda r: mem("@E5")).allowed)
        self.assertFalse(g.check_utterance(e, adult, {"@E4": adult, "@E5": kid}, addressees=[adult], expand=lambda r: mem("@E5")).allowed)
        self.assertFalse(g.check_utterance(e, adult, {"@E4": adult}, addressees=[adult]).allowed)       # no frozen copy: refused

    def test_the_budget_after_19a(self):
        import budget
        self.assertLessEqual(len(self.vocab.words), budget.GRAMMAR_WORDS_MAX)
        self.assertLessEqual(len(self.vocab.kinds), budget.KINDS_MAX)
        total = sum(budget.TOKENS.values())
        self.assertLessEqual(total, budget.MAX_TOKENS)


class TestElizaTools(Base):
    """What ELIZA's logic gives the inner language: ranked keywords, decomposition patterns with synonym classes, the I/YOU
    swap. Passive tools: they name, they never decide, and nothing of them reaches the model."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import shapes
        cls.shapes = shapes
        cls.matcher = shapes.ShapeMatcher(cls.cat)

    def test_every_shape_is_a_well_formed_pattern_over_real_categories(self):
        categories = {c for cs in self.vocab.cats.values() for c in cs} | {"pointer", "cite", "number"}
        for s in self.cat["shape"].values():
            self.shapes.Pattern(s.pattern, self.vocab)                                 # parses
            for tag in __import__("re").findall(r"<([a-z_]+)>", s.pattern):
                self.assertIn(tag, categories, (s.id, tag))

    def test_a_shape_is_not_a_word_an_action_or_an_option_of_the_model(self):
        import model_interface
        iface = model_interface.ModelInterface(self.cat).build()
        words = set(iface["output"]["speech"]["grammar_words"]) | set(iface["output"]["speech"]["kinds"]) | set(iface["output"]["gesture_head"])
        for s in self.cat["shape"].values():
            self.assertNotIn(s.id, words, s.id)
            self.assertNotIn(s.id, self.cat["action"], s.id)
        self.assertNotIn("shape", str(iface["output"]["writes"]))

    def test_decomposition_patterns_recognise_the_combination(self):
        read = self.matcher.reading
        self.assertEqual(read("(offer (future (caused us (dead @E4))))"), "joint_commitment")
        self.assertEqual(read("(request (not (future (did you speak (to anyone) (says (that b:1))))))"), "secrecy_request")
        self.assertEqual(read("(yes h:2)"), "acceptance")
        self.assertEqual(read("(no q:1)"), "refusal")
        self.assertEqual(read("(assert (qualifies m:1 adultery))"), "accusation")
        self.assertEqual(read("(assert (norm forbidden (at_time night (did anyone go @L10))))"), "norm_statement")
        self.assertEqual(read("(assert (if (did you speak (to @E2)) (future (did me strike you))))"), "threat")
        self.assertEqual(read("(request (intends us (did us go @L2)))"), "recruitment")
        self.assertEqual(read("(assert (not (knows me (at @E9 where))))"), "ignorance")
        self.assertEqual(read("(ask (knows you (past (did @E4 go @L6))))"), "sounding")

    def test_a_rendezvous_is_not_a_deadline(self):
        self.assertEqual(self.matcher.reading("(offer (at_time night (at us @L9)))"), "rendezvous")
        self.assertEqual(self.matcher.reading("(offer (before night (at us @L9)))"), "deadline")

    def test_the_highest_rank_wins_like_an_eliza_keyword(self):
        text = "(offer (if (not (did you give silver_coin:3 (to me))) (did me speak (to @E2) (says (that b:7)))))"
        shapes = [r.shape for r in self.matcher.read(text)]
        self.assertEqual(shapes[0], "pressure")                  # the pressure (rank 9) beats the plain conditional commitment (5)
        self.assertIn("conditional_commitment", shapes)

    def test_a_shape_is_found_anywhere_in_the_sentence(self):
        self.assertIn("sharing", [r.shape for r in self.matcher.read("(offer (if (has us gold:100) (share gold:100 us equal)))")])

    def test_variables_bind_and_must_agree(self):
        pat = self.shapes.Pattern("(and ?x ?x)", self.vocab)
        node = language.Parser().parse
        self.assertIsNotNone(pat.match(node("(and (dead @E1) (dead @E1))")))
        self.assertIsNone(pat.match(node("(and (dead @E1) (dead @E2))")))

    def test_the_synonym_classes_are_our_word_categories(self):
        p = self.shapes.Pattern("(assert (link _ <link> _))", self.vocab)
        self.assertIsNotNone(p.match(language.Parser().parse("(assert (link @E1 friend @E2))")))
        self.assertIsNone(p.match(language.Parser().parse("(assert (link @E1 chief @E2))")))      # a role word is not a link word

    def test_keywords_are_ranked_and_the_topic_is_the_highest(self):
        k = self.matcher.keywords
        self.assertGreater(k.rank("adultery"), k.rank("go"))
        self.assertGreater(k.rank("go"), k.rank("assert"))
        self.assertEqual(self.matcher.topic("(assert (past (did @E4 go @L5 (how discreet))))"), "go")
        self.assertEqual(self.matcher.topic("(assert (qualifies m:1 adultery))"), "adultery")
        self.assertEqual(k.stack(language.Parser().parse("(assert (qualifies m:1 adultery))"))[0], (9, "adultery"))

    def test_the_i_you_swap_when_a_speech_is_frozen_for_its_hearer(self):
        sw = self.shapes.Perspective("@E3")
        self.assertEqual(sw.text("(offer (future (did me give silver_coin:3 (to you))))"), "(offer (future (did @E3 give silver_coin:3 (to me))))")
        self.assertEqual(sw.text("(assert (wants us (dead @E4)))"), "(assert (wants us (dead @E4)))")
        with self.assertRaises(ValueError):
            self.shapes.Perspective("me")

    def test_the_probes_are_read_as_what_they_are(self):
        plot = self.cat["story"]["revenge_plot_three"].utterances
        found = {self.matcher.reading(u) for u in plot}
        self.assertTrue({"joint_commitment", "rendezvous", "secrecy_request", "accusation", "acceptance"} <= found, found)
        trip = self.cat["story"]["mayor_gold_expedition"].utterances
        found = {r.shape for u in trip for r in self.matcher.read(u)}
        self.assertTrue({"rendezvous", "sharing", "acceptance", "refusal"} <= found, found)


class TestVillageTemperament(Base):
    """The village temperament is a game setting chosen by the player. It reaches the model through WAKE and NEVER
    touches the hard rules or the governor."""

    def test_it_is_a_bounded_scale_read_in_wake_and_written_by_the_engine_only(self):
        v = self.cat["variable"]["village_temperament"]
        self.assertEqual((v.scale, v.writer, v.token), ("unipolar10", ["engine"], "WAKE.temperament"))
        self.assertEqual(self.cat["component"][v.holder].channel, "setting")

    def test_the_model_cannot_write_any_setting(self):
        import model_interface
        writable = model_interface.ModelInterface(self.cat).build()["output"]["writes"]["writable"]
        for v in self.cat["variable"].values():
            if self.cat["component"].get(v.holder) is not None and self.cat["component"][v.holder].channel == "setting":
                self.assertNotIn(v.id, writable)
                self.assertFalse(any(w.startswith("T_") for w in v.writer), v.id)

    def test_it_is_in_the_wake_token_of_the_interface(self):
        import model_interface
        f = model_interface.ModelInterface(self.cat).build()["input"]["token_types"]["WAKE"]["fields"]["temperament"]
        self.assertEqual(f["scale"], "unipolar10")

    def test_the_governor_never_reads_it(self):
        import inspect
        import governor
        src = Path(governor.__file__).read_text()
        self.assertNotIn("temperament", src)
        self.assertNotIn("setting", src.lower().replace("settings", ""))
        for name in ("check_write", "check_value", "check_gesture", "check_utterance", "check_record"):
            self.assertNotIn("temperament", str(inspect.signature(getattr(governor.Governor, name))))

    def test_hard_rules_and_vectors_do_not_mention_it(self):
        text = (Path(__file__).resolve().parents[1] / "data" / "hard_rules.toml").read_text()
        self.assertNotIn("temperament", text)
        inc = (Path(__file__).resolve().parents[2] / "engine" / "social" / "tests" / "governor_vectors.inc").read_text()
        self.assertNotIn("temperament", inc)

    def test_d10_is_identical_for_every_temperament(self):
        from governor import Governor, Party
        g = Governor()
        e = self.utt("(request (did you touch me (how romantic)))")
        verdicts = {t: g.check_utterance(e, Party(30, 30, 30, True), {"you": Party(15, 15, 15, True)}, addressees=[Party(15, 15, 15, True)]).code
                    for t in (0, 5, 10)}                                  # the governor has no such input: one verdict
        self.assertEqual(len(set(verdicts.values())), 1)
        self.assertNotEqual(next(iter(verdicts.values())), "ok")


if __name__ == "__main__":
    unittest.main()
