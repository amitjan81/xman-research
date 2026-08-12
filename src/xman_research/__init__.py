"""xman-research — the options research platform.

This file is deliberately almost empty. Component C4 (hypothesis record and trial log,
PR #8) owns the package's public re-export surface, and C2 (the session store) does not
add to it: the store is imported from its own subpackage,

    from xman_research.session_store import SessionStore

so that when the two branches meet, resolving this file means taking C4's version
verbatim. Nothing of C2's lives here to be lost in that resolution.
"""

__version__ = "0.1.0"
