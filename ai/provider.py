from abc import ABC, abstractmethod


class AIProvider(ABC):

    @abstractmethod
    def analyze_flow(self, tracks: list) -> dict:
        """
        Score the energy/flow of a track sequence and suggest improvements.
        Uses all available attributes: BPM, energy, tempo, texture, gender, mood, sound_codes.

        Returns:
            {
              "flow_score":      int (1-10),
              "energy_arc":      str (description of energy shape),
              "tempo_arc":       str (description of tempo progression),
              "gender_balance":  str (observation on gender distribution),
              "issues":          [str],
              "suggestions":     [str]
            }
        """

    @abstractmethod
    def plan_arc(self, description: str, num_slots: int) -> dict:
        """
        Plan a mood/energy arc for a scheduling block.

        Given a natural-language description (e.g. "Morning Drive — start energetic,
        mid-hour reflective song, finish strong") and a slot count, return a
        position-by-position target attribute sequence that the scheduling engine
        can use to prefer songs that match each position's desired feel.

        Returns:
            {
              "arc_name":    str,
              "description": str,
              "targets": [
                {
                  "position": 1,
                  "tempo":    int|null,   # 1=slow … 5=fast; null = no preference
                  "energy":   float|null, # 1.0-10.0; null = no preference
                  "gender":   int|null,   # 1=male 2=female 3=group 4=instr; null = any
                  "mood":     int|null,   # 1=joyful … 5=somber; null = no preference
                  "texture":  int|null,   # 1=open … 5=busy; null = no preference
                  "notes":    str
                },
                ...
              ]
            }
        """

    @abstractmethod
    def generate_clock(self, description: str, slots: int) -> dict:
        """
        Generate a clock template from a natural language description.

        Returns a dict matching the clock + slot model:
            {
              "name": str,
              "slots": [
                {
                  "type":       str,   # music|spot|liner|link
                  "category":   str,
                  "title":      str,
                  "gender":     int|null,
                  "tempo":      int|null,
                  "texture":    int|null,
                  "mood":       int|null,
                  "nominal_length_s": int|null,
                  "notes":      str
                },
                ...
              ]
            }
        """

    @abstractmethod
    def suggest_rules(self, station_description: str) -> dict:
        """
        Suggest scheduling rules based on a station description.

        Returns a dict matching the rules model:
            {
              "artist_separation_songs": int,
              "artist_separation_ms":    int,
              "title_separation_hours":  int,
              "title_separation_ms":     int,
              "max_gender_run":          int,
              "max_tempo_run":           int,
              "max_mood_run":            int,
              "check_prev_day_song":     bool,
              "categories": [
                {"name": str, "rotation_hours": int, "weight": int,
                 "force_rank_rotation": bool, "min_rotation": int}
              ],
              "notes": [str]
            }
        """
