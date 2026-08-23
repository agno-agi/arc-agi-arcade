"""The GPT player: gpt-5.6 at max effort on the flex tier, playing from its own manuals."""

from arcade.player import Player

player = Player(name="gpt-5.6", model="gpt-5.6", jobs=5)

if __name__ == "__main__":
    player.main()
