# { "Depends": "genlayer-py-std:test" }

import json

import typing
import genlayer.std as gl
from genlayer.py.types import *
from genlayer.py.storage import *


@gl.contract
class PredictionMarket:
    has_resolved: bool
    game_date: str
    team1: str
    team2: str
    resolution_url: str

    def __init__(self, game_date: str, team1: str, team2: str):
        """
        Initializes a new instance of the prediction market with the specified game date and teams.

        Args:
            game_date (str): The date of the game in the format 'YYYY-MM-DD'.
            team1 (str): The name of the first team.
            team2 (str): The name of the second team.

        Attributes:
            has_resolved (bool): Indicates whether the game's resolution has been processed. Default is False.
            game_date (str): The date of the game.
            resolution_url (str): The URL to the game's resolution on BBC Sport.
            team1 (str): The name of the first team.
            team2 (str): The name of the second team.
        """
        self.has_resolved = False
        self.game_date = game_date
        self.resolution_url = (
            "https://www.bbc.com/sport/football/scores-fixtures/" + game_date
        )
        self.team1 = team1
        self.team2 = team2

    @gl.public
    def resolve(self) -> typing.Any:

        if self.has_resolved:
            return "Already resolved"

        def nondet() -> str:
            web_data = gl.get_webpage({"mode": "text"}, self.resolution_url).get()
            print(web_data)

            task = f"""In the following web page, find the winning team in a matchup between the following teams:
            Team 1: {self.team1}
            Team 2: {self.team2}

            Web page content:
            {web_data}
            End of web page data.

            If it says "Kick off [time]" between the names of the two teams, it means the game hasn't started yet.
            If you fail to extract the score, assume the game is not resolved yet.

            Respond with the following JSON format:
            {{
                "score": str, // The score with numbers only, e.g, "1:2", or "-" if the game is not resolved yet
                "winner": int, // The number of the winning team, 0 for draw, or -1 if the game is not yet finished
            }}
            It is mandatory that you respond only using the JSON format above,
            nothing else. Don't include any other words or characters,
            your output must be only JSON without any formatting prefix or suffix.
            This result should be perfectly parsable by a JSON parser without errors.
            """
            result = (
                gl.exec_prompt({}, task).get().replace("```json", "").replace("```", "")
            )
            print(result)
            return json.dumps(json.loads(result), sort_keys=True)

        result_json = json.loads(gl.eq_principle_refl(nondet).get())

        if result_json["winner"] > -1:
            self.has_resolved = True
            self.winner = result_json["winner"]
            self.score = result_json["score"]

        return result_json
