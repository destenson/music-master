"""Music Master core.

The text tier in this package is pure: JSON in, JSON out, standard library only. That is what
lets the same modules run under CPython (the CLI, the tests, the local backend) and under
Pyodide (the browser SPA) without a second implementation of any check.
``tests/test_text_tier.py`` enforces the standard-library rule; anything that needs a GPU, a
filesystem or a network belongs in the execute tier instead.

The wrappers in ``vocabulary/`` are kept so existing command lines and importers keep working,
and contain no logic of their own.
"""

# The modules that must stay pure. Declared here rather than in the test so the package and
# the guard cannot disagree about what the text tier is; `tests/test_text_tier.py` enforces it.
TEXT_TIER = ("jev", "lyrics", "oracle", "prompt", "radio", "render", "spec", "templates", "timeline", "vocabulary")
