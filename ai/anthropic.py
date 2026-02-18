import json
import os

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


class AnthropicProvider(AIProvider):

    def __init__(self):
        try:
            import anthropic
        except ImportError:
            raise ImportError(
                "anthropic package is required for this provider: pip install anthropic"
            )
        self.client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-6")

    def _ask(self, prompt: str) -> dict:
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return json.loads(msg.content[0].text)

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
