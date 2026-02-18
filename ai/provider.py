from abc import ABC, abstractmethod


class AIProvider(ABC):

    @abstractmethod
    def analyze_flow(self, tracks: list) -> dict:
        """Score the energy/flow of a track sequence and suggest improvements."""

    @abstractmethod
    def generate_clock(self, description: str, slots: int) -> dict:
        """Generate a clock template from a natural language description."""

    @abstractmethod
    def suggest_rules(self, station_description: str) -> dict:
        """Suggest scheduling rules based on a station description."""
