"""Entry script for PyInstaller: pyinstaller --onefile --name LASTCHANCE run.py"""
import sys

from lastchance.cli import main

sys.exit(main())
