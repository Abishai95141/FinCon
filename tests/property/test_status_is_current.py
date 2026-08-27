"""The known-broken table must say what the reproducers say.

`tools/status_table.py` has had a `--check` mode since the table stopped being
hand-written, and nothing ever ran it. So the table rotted exactly the way the
hand-written one did, and in both directions at once: two rows stood **open**
for problems closed on 2026-08-25, and the one genuinely open problem —
`ReconException.leg` cannot name a side a second loop actually has — appeared
nowhere. A reader trusting STATUS.md would have chased two ghosts and missed
the real one.

That is this project's most-repeated defect wearing its newest costume: a
control that exists, is correct, and is reachable by nobody. The generator was
never the weak part. Not running it was.

So the check runs here, in the suite, where a stale table fails rather than
waiting to be noticed. `make status-table` prints the block to paste.
"""

from __future__ import annotations

from tools.status_table import main


def test_the_known_broken_table_matches_its_reproducers():
    assert main(["--check"]) == 0, (
        "STATUS.md's known-broken table disagrees with tests/known_broken.py. "
        "Regenerate it with `make status-table` and paste the block in — do not "
        "hand-edit the rows, which is how the previous table came to carry four "
        "wrong ones."
    )
