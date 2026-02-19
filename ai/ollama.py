import json
import os
import urllib.request

from .provider import AIProvider

_SYSTEM = (
    "You are a professional radio music scheduling assistant with deep expertise in "
    "music flow, energy arcs, and rotation theory. "
    "Respond ONLY with valid JSON — no explanation, no markdown fences."
)

_FLOW_SCHEMA = (
    '{"flow_score":<int 1-10>,"energy_arc":"<string describing energy shape>",'
    '"tempo_arc":"<string describing tempo progression>",'
    '"gender_balance":"<observation on gender distribution>",'
    '"issues":["<string>"],"suggestions":["<string>"]}'
)

_ARC_SCHEMA = (
    '{"arc_name":"<string>","description":"<string>",'
    '"targets":[{"position":<int>,"tempo":<1-5 or null>,"energy":<1.0-10.0 or null>,'
    '"gender":<1=male,2=female,3=group,4=instrumental or null>,'
    '"mood":<1=joyful,2=inspirational,3=reflective,4=contemplative,5=somber or null>,'
    '"texture":<1=open,2=medium,3=busy or null>,"notes":"<string>"}]}'
)

_CLOCK_SCHEMA = (
    '{"name":"<string>","slots":[{"type":"<music|spot|liner>","category":"<string>",'
    '"title":"<string>","gender":<1-4 or null>,"tempo":<1-5 or null>,'
    '"texture":<1-3 or null>,"mood":<1-5 or null>,'
    '"nominal_length_s":<int or null>,"notes":"<string>"}]}'
)

_RULES_SCHEMA = (
    '{"artist_separation_songs":<int>,"artist_separation_ms":<int>,'
    '"title_separation_hours":<int>,"title_separation_ms":<int>,'
    '"max_gender_run":<int or -1>,"max_tempo_run":<int or -1>,"max_mood_run":<int or -1>,'
    '"check_prev_day_song":<bool>,'
    '"categories":[{"name":"<string>","rotation_hours":<int>,"weight":<int>,'
    '"force_rank_rotation":<bool>,"min_rotation":<int>}],'
    '"notes":["<string>"]}'
)

_ATTR_GUIDE = (
    "Attribute scales: "
    "tempo 1=slow 2=medium-slow 3=medium 4=medium-fast 5=fast; "
    "energy 1.0=calm to 10.0=intense; "
    "gender 1=male 2=female 3=group 4=instrumental; "
    "mood 1=joyful 2=inspirational 3=reflective 4=contemplative 5=somber; "
    "texture 1=open/sparse 2=medium 3=busy/dense."
)


class OllamaProvider(AIProvider):

    def __init__(self):
        self.host  = os.environ.get("OLLAMA_HOST",  "http://localhost:11434")
        self.model = os.environ.get("OLLAMA_MODEL", "mistral")

    def _ask(self, prompt: str) -> dict:
        payload = json.dumps({
            "model":  self.model,
            "prompt": f"{_SYSTEM}\n\n{prompt}",
            "stream": False,
        }).encode()
        req = urllib.request.Request(
            f"{self.host}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = json.loads(resp.read())["response"]
            return json.loads(raw)

    def analyze_flow(self, tracks: list) -> dict:
        _GENDER = {1: "M", 2: "F", 3: "Grp", 4: "Inst"}
        _MOOD   = {1: "joyful", 2: "inspir", 3: "reflect", 4: "contempl", 5: "somber"}
        lines = "\n".join(
            f"{i+1}. \"{t.get('title','?')}\" – {t.get('artist','?')} | "
            f"BPM:{t.get('bpm') or '?'}  energy:{t.get('energy') or '?'}  "
            f"tempo:{t.get('tempo') or '?'}  texture:{t.get('texture') or '?'}  "
            f"gender:{_GENDER.get(t.get('gender'), '?')}  "
            f"mood:{_MOOD.get(t.get('mood'), t.get('mood') or '?')}  "
            f"SCs:{t.get('sound_codes') or []}"
            for i, t in enumerate(tracks)
        )
        return self._ask(
            f"{_ATTR_GUIDE}\n\n"
            f"Analyze the flow of this scheduled track sequence. Identify separation violations, "
            f"attribute run problems, energy dips, or flow improvements:\n\n"
            f"{lines}\n\n"
            f"Return JSON: {_FLOW_SCHEMA}"
        )

    def plan_arc(self, description: str, num_slots: int) -> dict:
        return self._ask(
            f"{_ATTR_GUIDE}\n\n"
            f"Plan a {num_slots}-position mood/energy arc for this radio scheduling block:\n"
            f"\"{description}\"\n\n"
            f"For each position specify the ideal target attributes. Use null where you have "
            f"no preference. Produce a natural arc — consider energy build/fall, tempo variety, "
            f"gender balance, and mood progression appropriate for the daypart.\n\n"
            f"Return JSON: {_ARC_SCHEMA}"
        )

    def generate_clock(self, description: str, slots: int) -> dict:
        return self._ask(
            f"{_ATTR_GUIDE}\n\n"
            f"Generate a {slots}-slot radio clock template for: \"{description}\"\n\n"
            f"Include slot-level attribute targets where appropriate. "
            f"Use category names like Current, Recurrent, Gold, Power, etc. "
            f"Include spots/liners as needed for a realistic clock.\n\n"
            f"Return JSON: {_CLOCK_SCHEMA}"
        )

    def suggest_rules(self, station_description: str) -> dict:
        return self._ask(
            f"{_ATTR_GUIDE}\n\n"
            f"Suggest music scheduling rules for this station:\n\"{station_description}\"\n\n"
            f"Consider genre, format, daypart, audience, and standard industry practice. "
            f"Use -1 for run limits where unlimited is appropriate.\n\n"
            f"Return JSON: {_RULES_SCHEMA}"
        )
