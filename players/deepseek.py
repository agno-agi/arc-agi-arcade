"""The DeepSeek player: the open-weight value king, playing on its own manuals."""

from arcade.player import Player

player = Player(
    name="deepseek-v4-flash",
    model="deepseek-v4-flash",
    knowledge="deepseek-v4-flash",
    vision=False,
)

if __name__ == "__main__":
    player.main()
