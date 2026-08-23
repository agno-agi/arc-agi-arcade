"""The Fable player: claude-fable-5 at max effort with prompt caching, playing from its own manuals."""

from arcade.player import Player

player = Player(name="claude-fable-5", model="claude-fable-5", jobs=4)

if __name__ == "__main__":
    player.main()
