"""PyInstaller entry point."""
import multiprocessing

from geolens.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
