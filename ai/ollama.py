import json
import os
import urllib.request

from .provider import AIProvider

_SYSTEM = (
    "You are a professional radio music scheduling assistant. "
    "Respond ONLY with valid JSON — no explanation, no markdown."
)

_FLOW_SCHEMA = (
    '{"flow_score":<int 1-10>,"energy_arc":"<string>",'
    '"issues":["<string>"],"suggestions":["<string>"]}'
)
_CLOCK_SCHEMA = (
    '{"name":"<string>","slots":[{"position":<int>,"category":"<string>",'
    '"duration_seconds":<int>,"notes":"<string>"}]}'
)
_RULES_SCHEMA = (
    '{"artist_separation_songs":<int>,"title_separation_hours":<int>,'
    '"categories":[{"name":"<string>","rotation_hours":<int>,"weight":<int>}],'
    '"notes":["<string>"]}'
)


class OllamaProvider(AIProvider):

    def __init__(self):
        self.host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        self.model = os.environ.get("OLLAMA_MODEL", "mistral")

    def _ask(self, prompt: str) -> dict:
        payload = json.dumps({
            "model": self.model,
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
        lines = "\n".join(
            f"{i+1}. {t.get('title','?')} - {t.get('artist','?')} "
            f"(BPM:{t.get('bpm','?')} energy:{t.get('energy','?')}/10 mood:{t.get('mood','?')})"
            for i, t in enumerate(tracks)
        )
        return self._ask(
            f"Analyze the flow of this track sequence:\n{lines}\n\nReturn JSON: {_FLOW_SCHEMA}"
        )

    def generate_clock(self, description: str, slots: int) -> dict:
        return self._ask(
            f"Generate a {slots}-slot radio clock template for: {description}\n\n"
            f"Return JSON: {_CLOCK_SCHEMA}"
        )

    def suggest_rules(self, station_description: str) -> dict:
        return self._ask(
            f"Suggest music scheduling rules for this station: {station_description}\n\n"
            f"Return JSON: {_RULES_SCHEMA}"
        )
