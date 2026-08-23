"""The GLM player: the open-weight flagship, playing far above its published weight on seeded manuals.

GLM-5.2 is text-only — it plays from the authoritative hex grids alone, seeded with the complete
25-game knowledge the GPT player wrote winning the board.
"""

from arcade.player import Player

player = Player(
    name="glm-5.2",
    model="accounts/fireworks/models/glm-5p2",
    knowledge="glm-5.2",
    seeds=["gpt-5.6"],
    vision=False,
)

if __name__ == "__main__":
    player.main()
