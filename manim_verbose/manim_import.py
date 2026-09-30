"""
Importing manimlib builds its global configuration, and building that reads sys.argv with
manim's own argument parser (see config.initialize_manim_config). Anything which is not the
manimgl command, such as manimgl-scene, manimgl-editor or a test runner, has its own
arguments there, which manim's parser would either misread or exit over.

So import it through here, which hides the command line for the length of the import. What
a render needs configured is set on manim_config afterwards, never through sys.argv.
"""
from __future__ import annotations

import sys
from types import ModuleType


def import_manim() -> ModuleType:
    if "manimlib.config" in sys.modules:
        import manimlib
        return manimlib
    saved = sys.argv
    sys.argv = [saved[0] if saved else "manimgl"]
    try:
        import manimlib
    finally:
        sys.argv = saved
    return manimlib
