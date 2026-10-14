#!/usr/bin/env python3
"""utterance_parser.py - prototype of the ENGINE-side language layer (not the AI).

Turns a free English sentence into
  * highlighted tokens: concept (orange), logic (blue), entity/place/person/title (green)
  * a speech-act FRAME that the decision model receives as event scalars:
      act, force 0..3 (question, polite request, plain, command), politeness -2..2,
      modality (want/can/must/will/...), content (predicate + slots)
and suggests known words for unknown or partial words.

The same frame format is used between NPCs, so politics and diplomacy use one language.

  python3 utterance_parser.py        # runs the self-tests and prints examples
"""
import difflib, json, re, sys

CONCEPT_VERBS = ("come go take give bring harvest dig plant build buy sell help follow stop wait tell show "
                 "vote trade fight kill meet see ask promise pay cut mine carry leave stay hide steal "
                 "read write publish elect appoint live have know").split()
CONCEPT_ITEMS = ("carrot bread pickaxe shovel trowel wheat stone coal gold water key flower fruit vegetable "
                 "wood meat apple seed tool letter notice money coin sous rich job work wife husband partner married").split()
ENTITY_WORDS = ("you me i we us him her them farm mine forest square house well river field market "
                "board home village").split()
LOGIC_WORDS = ("with to for and or if then not because before after in at from on of by about "
               "unless else otherwise what who where when why how that").split()
FUNCTION_WORDS = ("the a an do does want would like can could will shall may please lets let's "
                  "must have need should is are was were did does").split()
PLACES = set("farm mine forest square house well river field market board home village".split())
PRONOUNS = {"you": "addressee", "me": "speaker", "i": "speaker", "we": "speaker+addressee",
            "us": "speaker+addressee", "him": "third", "her": "third", "them": "third"}
HARM = set("kill hit hurt burn destroy expose tell fight steal".split())
PAST_WRONG = set("stole lied cheated hit killed betrayed slandered did".split())


class Lexicon:
    def __init__(self):
        self.cat = {}
        for w in CONCEPT_VERBS:
            self.cat[w] = ("concept", "verb")
        for w in CONCEPT_ITEMS:
            self.cat[w] = ("concept", "item")
        for w in ENTITY_WORDS:
            self.cat[w] = ("entity", "place" if w in PLACES else "pronoun")
        for w in LOGIC_WORDS:
            self.cat[w] = ("logic", "logic")
        for w in FUNCTION_WORDS:
            self.cat[w] = ("func", "func")

    def add(self, word, kind):
        """Register a new concept at runtime, e.g. a title the player just created."""
        word = word.lower()
        self.cat[word] = ("entity", kind) if kind in ("title", "person", "place") else ("concept", kind)

    def lookup(self, w):
        w = w.lower()
        if w.endswith("'s") and len(w) > 2:
            w = w[:-2]
        if w in self.cat:
            return self.cat[w]
        if w.endswith("s") and w[:-1] in self.cat:      # carrots -> carrot
            return self.cat[w[:-1]]
        return None

    def stem(self, w):
        w = w.lower()
        return w[:-1] if (w not in self.cat and w.endswith("s") and w[:-1] in self.cat) else w

    def suggest(self, partial, n=5):
        partial = partial.lower()
        pref = sorted(w for w in self.cat if w.startswith(partial) and self.cat[w][0] != "func")
        if pref:
            return pref[:n]
        return difflib.get_close_matches(partial, [w for w in self.cat if self.cat[w][0] != "func"], n=n, cutoff=0.7)


TOKEN_RE = re.compile(r"[A-Za-z']+|[?!.,]")


def tokenize(text, lex):
    toks = []
    for m in TOKEN_RE.finditer(text):
        w = m.group(0)
        if w in "?!.,":
            toks.append({"text": w, "cat": "punct", "start": m.start()})
            continue
        c = lex.lookup(w)
        t = {"text": w, "start": m.start(), "cat": c[0] if c else "unknown", "kind": c[1] if c else None}
        if c is None:
            t["suggest"] = lex.suggest(w)
        toks.append(t)
    return toks


COLORS = {"concept": "#e8890c", "logic": "#2a6fdb", "entity": "#2e9e5b", "unknown": "#c0392b"}


def render_html(toks):
    out = []
    for t in toks:
        col = COLORS.get(t["cat"])
        out.append(f'<span style="color:{col}">{t["text"]}</span>' if col else t["text"])
    return " ".join(out)


def _slots(words, lex):
    """Extract predicate and slots from the words of the content."""
    c = {}
    ws = [w for w in words]
    i = 0
    preds = []
    while i < len(ws):
        w = ws[i]
        info = lex.lookup(w)
        s = lex.stem(w)
        if info and info[1] == "verb":
            preds.append({"predicate": s})
        elif info and info[1] == "item" and preds:
            preds[-1].setdefault("object", s)
        elif info and info[1] == "item":
            preds.append({"object": s})
        elif info and info[0] == "entity" and w in ("me", "us", "you", "him", "her", "them"):
            if i > 0 and ws[i - 1] == "with":
                (preds[-1] if preds else c).setdefault("companion", PRONOUNS[w])
            elif preds and "indirect" not in preds[-1] and i > 0 and ws[i - 1] in ("give", "tell", "show", "bring"):
                preds[-1]["indirect"] = PRONOUNS[w]
        elif info and info[1] == "place" and preds:
            preds[-1].setdefault("place", s)
        elif info and info[1] == "title" and preds:
            preds[-1].setdefault("target_title", s)
        i += 1
    if preds:
        c.update(preds[0])
        if len(preds) > 1:
            c["purpose"] = preds[1]
            if "place" in c and "place" not in preds[1]:
                preds[1]["place"] = c["place"]
    return c


ATTR_PATTERNS = [
    (r"^where (?:does|did|do) (\w+) live", "home_of"), (r"^where (?:is|was) (\w+)(?:'s)? (?:house|home)", "home_of"),
    (r"^where (?:is|was) (\w+)", "where_is"),
    (r"^how (?:much|many) (?:money|coins?|gold|sous) (?:does|do|did) (\w+) have", "wealth_of"),
    (r"^how rich (?:is|was) (\w+)", "wealth_of"),
    (r"^what (?:does|do) (\w+) do", "job_of"), (r"^what (?:is|was) (\w+)(?:'s)? (?:job|work)", "job_of"),
    (r"^who is the (\w+)", "title_holder"), (r"^who is (\w+)(?:'s)? (?:wife|husband|partner)", "partner_of"),
    (r"^is (\w+) married", "partner_of"),
    # embedded word order after "do you know ..."
    (r"^where (\w+) lives", "home_of"), (r"^where (\w+) is\b", "where_is"),
    (r"^how (?:much|many) (?:money|coins?|gold|sous) (\w+) has", "wealth_of"), (r"^what (\w+) does", "job_of"),
]


def extract_query(s, lex):
    for pat, attr in ATTR_PATTERNS:
        m = re.match(pat, s)
        if m:
            subj = m.group(1)
            subj = {"you": "addressee", "i": "speaker", "me": "speaker"}.get(subj, lex.stem(subj))
            return {"attr": attr, "subject": subj}
    return None


def parse(text, lex):
    toks = tokenize(text, lex)
    raw = text.strip()
    s = re.sub(r"[?!.,]", " ", raw.lower().replace("let's", "lets")).strip()
    s = re.sub(r"\s+", " ", s)
    q = raw.endswith("?")
    words = s.split()
    frame = {"act": "inform", "force": 0, "politeness": 0, "modality": None, "negation": bool(re.search(r"\b(not|don't|never|no)\b", s)),
             "content": {}, "text": raw}

    def set_(act, force, pol, modal=None, rest=None):
        frame.update(act=act, force=force, politeness=pol, modality=modal)
        frame["content"] = _slots((rest if rest is not None else s).split(), lex)

    m = re.match(r"^(if|when) (.*?) (i|we) (will|ll|would) (.*)$", s)
    if m:
        cond = _slots(m.group(2).split(), lex)
        cons = m.group(5).split()
        harm = any(lex.stem(w) in HARM for w in cons)
        frame.update(act="threaten_conditional" if harm else "offer_conditional", force=2, politeness=-1 if harm else 1, modality="will")
        frame["content"] = {"if": cond, "then": _slots(cons, lex)}
    elif re.search(r"\b(or) (i will|i ll|else|otherwise)\b", s):
        a, b = re.split(r"\bor (?:i will|i ll|else|otherwise)\b", s, maxsplit=1)
        frame.update(act="threaten", force=3, politeness=-2, modality="will")
        frame["content"] = {"demand": _slots(a.split(), lex), "sanction": _slots(b.split(), lex)}
    elif re.match(r"^(do you want to|do you want|do you wanna|would you like to|would you like)\b", s):
        rest = re.sub(r"^(do you want to|do you want|do you wanna|would you like to|would you like)\s*", "", s)
        set_("invite", 1, 1, "want", rest)
    elif re.match(r"^(can|could|would|will) you\b", s):
        rest = re.sub(r"^(can|could|would|will) you( please)?\s*", "", s)
        set_("request", 2, 2 if "please" in s else 1, "can", rest)
    elif re.match(r"^(may|can) i\b", s):
        set_("ask_permission", 1, 1, "can", re.sub(r"^(may|can) i\s*", "", s))
    elif re.match(r"^(shall we|lets)\b", s):
        set_("propose_joint", 1, 1, None, re.sub(r"^(shall we|lets)\s*", "", s))
    elif re.match(r"^(why|where|who|what|when|how)\b", s) or re.match(r"^do you know (where|who|what|how)\b", s):
        know = re.match(r"^do you know (.*)$", s)
        body = know.group(1) if know else s
        set_("ask_info", 1, 1 if know else 0, "know" if know else None, body)
        frame["content"]["wh"] = body.split()[0]
        qy = extract_query(body, lex)
        if qy:
            frame["content"]["query"] = qy
    elif re.match(r"^i know\b", s) or (len(words) >= 2 and words[0] == "you" and words[1] in PAST_WRONG):
        frame.update(act="accuse", force=2, politeness=-1)
        frame["content"] = {"claim": s}
    elif re.match(r"^please\b", s) or s.endswith(" please"):
        set_("request", 2, 2, None, re.sub(r"\bplease\b", "", s).strip())
    elif re.match(r"^(you must|you have to|you will|you shall|you need to)\b", s):
        set_("order", 3, -1, "must", re.sub(r"^(you must|you have to|you will|you shall|you need to)\s*", "", s))
    elif re.match(r"^i want you to\b", s):
        set_("request", 2, 0, "want", re.sub(r"^i want you to\s*", "", s))
    elif re.match(r"^(i will|i ll|i promise)\b", s):
        set_("promise", 1, 1, "will", re.sub(r"^(i will|i ll|i promise)( to)?\s*", "", s))
    elif words and lex.lookup(words[0]) and lex.lookup(words[0])[1] == "verb":
        set_("order", 3, 0, None, s)
    elif q:
        set_("ask_yesno", 1, 0)
    else:
        set_("inform", 0, 0)
    frame["unknown"] = [t["text"] for t in toks if t["cat"] == "unknown"]
    frame["refusal_cost"] = frame["force"]          # a refused order is a confrontation, a refused invitation is not
    return {"tokens": toks, "frame": frame, "html": render_html(toks)}


# --------------------------------------------------------------------------
def _tests():
    lex = Lexicon()
    n = 0

    def check(cond, msg):
        nonlocal n
        n += 1
        if not cond:
            print("FAIL:", msg)
            sys.exit(1)

    r = parse("Do you want come with me in the farm to harvest the carrots ?", lex)
    f, cats = r["frame"], {t["text"].lower(): t["cat"] for t in r["tokens"]}
    check(f["act"] == "invite" and f["force"] == 1 and f["politeness"] >= 1, "invitation")
    check(f["content"].get("predicate") == "come" and f["content"].get("companion") == "speaker", "come with me")
    check(f["content"].get("purpose", {}).get("predicate") == "harvest" and f["content"]["purpose"].get("object") == "carrot", "purpose harvest carrot")
    check(f["content"]["purpose"].get("place") == "farm", "place inherited")
    check(cats["come"] == cats["harvest"] == cats["carrots"] == "concept", "orange concepts")
    check(cats["with"] == cats["to"] == cats["in"] == "logic", "blue logic words")
    check(cats["you"] == cats["me"] == cats["farm"] == "entity", "green entities")
    o = parse("Come with me", lex)["frame"]
    check(o["act"] == "order" and o["force"] == 3 and o["politeness"] == 0, "order")
    p = parse("Please come with me", lex)["frame"]
    check(p["act"] == "request" and p["force"] == 2 and p["politeness"] == 2, "polite request")
    check(f["refusal_cost"] < o["refusal_cost"], "refusing an order costs more than refusing an invitation")
    t = parse("Give me the key or I will tell the mayor what you did", lex)["frame"]
    check(t["act"] == "threaten" and t["content"]["demand"].get("predicate") == "give" and t["content"]["sanction"].get("predicate") == "tell", "threat with demand")
    b = parse("If you vote for me I will give you bread", lex)["frame"]
    check(b["act"] == "offer_conditional" and b["content"]["then"].get("object") == "bread", "conditional offer (bribe)")
    lex.add("lawyer", "title")
    l = parse("I want to see the lawyer", lex)
    check({t["text"]: t["cat"] for t in l["tokens"]}["lawyer"] == "entity", "user-made title is known")
    u = parse("Do you want to harvset the carrots", lex)
    check(u["frame"]["unknown"] == ["harvset"] and "harvest" in u["tokens"][4]["suggest"], "typo suggestion")
    check(lex.suggest("har")[:1] == ["harvest"], "prefix suggestion")
    print(f"{n} parser tests passed")
    for s in ["Do you want come with me in the farm to harvest the carrots ?", "Come with me", "Please come with me",
              "Give me the key or I will tell the mayor what you did", "If you vote for me I will give you bread"]:
        r = parse(s, lex)
        fr = r["frame"]
        print(f"- {s}\n    act={fr['act']} force={fr['force']} politeness={fr['politeness']} modality={fr['modality']} "
              f"content={json.dumps(fr['content'])}")


if __name__ == "__main__":
    _tests()
