# napalm.base.validate.compare — the pure spec-vs-data comparator (the only
# napalm surface Twinlab uses). Signature transcribed from napalm 5.2 source:
# a dict spec returns a structured report, a scalar/str spec a bare bool.
# CAUTION (behavior, not typing): compare() MUTATES both arguments — deep-copy
# at the call site.
def compare(
    src: str | dict[str, object] | list[object], dst: object
) -> bool | dict[str, object]: ...
