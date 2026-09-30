"""
The `render` marker, for tests which draw frames or write videos with the real renderer.
They are slower than the rest, and can be left out with -m "not render".
"""


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "render: draws frames or writes videos with the real renderer (slower; deselect with -m 'not render')",
    )
