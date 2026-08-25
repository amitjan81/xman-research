"""Guards the CLI applies before anything is computed.

The demotion rule's whole claim is that it was fixed before the first observation. A floor
an operator can lower on the night is that rule being retuned, so the floor is enforced at
the boundary where the number arrives rather than inside the statistics, which still take a
free `min_settled` so tests can drive the rules on small samples.
"""

from __future__ import annotations

import pytest

from xman_research.alpha.cli import main
from xman_research.alpha.tracking import DEFAULT_MIN_SETTLED


def test_min_settled_cannot_be_lowered_below_the_floor() -> None:
    with pytest.raises(SystemExit) as raised:
        main(["track", "report", "--min-settled", "1"])
    assert raised.value.code != 0


def test_min_settled_may_be_raised() -> None:
    """Raising it asks for more evidence before acting, which the rule never forbids."""
    assert DEFAULT_MIN_SETTLED >= 1
    with pytest.raises(SystemExit) as raised:
        main(["track", "report", "--min-settled", str(DEFAULT_MIN_SETTLED + 5), "--help"])
    assert raised.value.code == 0
