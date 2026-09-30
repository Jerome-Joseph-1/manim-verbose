"""
Importing manimlib reads sys.argv with manim's own parser (see manim_verbose/manim_import.py),
which would choke on pytest's arguments. Import it once here, with the command line hidden,
before any test module gets to it.
"""
from manim_verbose.manim_import import import_manim

import_manim()
