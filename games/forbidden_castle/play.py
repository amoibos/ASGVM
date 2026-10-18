from gameengine.game import module_main, run
from .config import CONFIG

play = lambda root=None: run(CONFIG, root)

if __name__ == "__main__":
    module_main(CONFIG)
