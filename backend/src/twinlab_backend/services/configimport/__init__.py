"""Config import (contract delta 22): dumped running configs → a netlab lab.

The definition factory behind `POST /import/*`: per-platform boundary parsers
normalize source configs into one facts model, link inference recovers the
logical (L3) topology, and every source line lands in exactly one of three
buckets — modeled (the thin skeleton netlab regenerates), carried (verbatim
custom-config), quarantined (kept but unattached). Design record:
docs/config-import.md.
"""
