"""Interface renaming: carried config rewritten onto the lab's names.

The map (source interface -> the netlab-assigned NOS-side ifname) comes from
the dry create's expanded topology, joined on the PINNED addresses — the one
transformation carried config undergoes. IOS rewriting is textual (full
names and the canonical show-output abbreviations, single-pass alternation
so chained mappings cannot cascade); VyOS rewriting is structural over the
set-command tokens, including the interface-TYPE change a stub realization
forces (`ethernet ethX` -> `dummy dumN`). Any interface-like token left
unmapped after rewriting is a named note — never silent.
"""

import re
import shlex

from twinlab_backend.services.configimport.model import Note

# IOS interface families and the abbreviations show output / operators use.
# Order within a family is irrelevant — variants are matched longest-first.
_IOS_FAMILIES: dict[str, tuple[str, ...]] = {
    "TwentyFiveGigE": ("TwentyFiveGigE", "Twe"),
    "TenGigabitEthernet": ("TenGigabitEthernet", "TenGigE", "Te"),
    "HundredGigE": ("HundredGigE", "Hu"),
    "FortyGigabitEthernet": ("FortyGigabitEthernet", "Fo"),
    "GigabitEthernet": ("GigabitEthernet", "GigE", "Gig", "Gi"),
    "FastEthernet": ("FastEthernet", "Fas", "Fa"),
    "Ethernet": ("Ethernet", "Eth", "Et"),
    "Serial": ("Serial", "Se"),
    "Loopback": ("Loopback", "Lo"),
    "Port-channel": ("Port-channel", "Po"),
    "Vlan": ("Vlan", "Vl"),
    "Tunnel": ("Tunnel", "Tu"),
}

_IOS_NAME_RE = re.compile(r"^([A-Za-z-]+)([\d][\d/.:]*)$")

# Any interface-looking token (for the unmapped-leftovers scan).
_IOS_TOKEN_RE = re.compile(
    r"\b(?:"
    + "|".join(sorted((a for v in _IOS_FAMILIES.values() for a in v), key=len, reverse=True))
    + r")[\d][\d/.:]*"
)
_VYOS_TOKEN_RE = re.compile(r"^eth\d+$")


def _ios_variants(name: str) -> tuple[str, ...]:
    """Every spelling of an IOS interface name that may appear in config
    (`GigabitEthernet0/0/1` -> also `Gi0/0/1`, `GigE0/0/1`, …)."""
    match = _IOS_NAME_RE.match(name)
    if match is None:
        return (name,)
    family, suffix = match.group(1), match.group(2)
    abbreviations = _IOS_FAMILIES.get(family)
    if abbreviations is None:
        return (name,)
    return tuple(f"{a}{suffix}" for a in abbreviations)


def rewrite_ios(
    lines: tuple[str, ...], mapping: dict[str, str], node: str
) -> tuple[tuple[str, ...], list[Note]]:
    """Rewrite every mapped interface reference in one pass. Single-pass
    alternation: a replacement's OUTPUT can never be re-matched, so shifted
    same-platform maps (Ethernet0/2 -> Ethernet0/1) cannot cascade."""
    replacements: dict[str, str] = {}
    for source, target in mapping.items():
        for variant in _ios_variants(source):
            replacements[variant] = target
    if not replacements:
        combined = None
    else:
        alternation = "|".join(re.escape(v) for v in sorted(replacements, key=len, reverse=True))
        # The lookahead stops `Gi0/1` from matching inside `Gi0/1/1`.
        combined = re.compile(rf"\b(?:{alternation})(?![\w/.:])")

    rewritten: list[str] = []
    for line in lines:
        if combined is None:
            rewritten.append(line)
        else:
            rewritten.append(combined.sub(lambda m: replacements[m.group(0)], line))

    notes: list[Note] = []
    targets = set(mapping.values())
    leftover: set[str] = set()
    for line in rewritten:
        for token in _IOS_TOKEN_RE.findall(line):
            if token not in targets:
                leftover.add(token)
    for token in sorted(leftover):
        notes.append(
            Note(
                node,
                f"carried config references {token}, which maps to no lab interface — "
                "review that config after import",
            )
        )
    return tuple(rewritten), notes


def _vyos_type_for(target: str) -> str:
    """The `interfaces <type>` word a rewritten name lives under: netlab
    realizes stubs as dummies (dumN) and loopbacks as lo."""
    if target.startswith("dum"):
        return "dummy"
    if target == "lo":
        return "loopback"
    return "ethernet"


def rewrite_vyos(
    lines: tuple[str, ...], mapping: dict[str, str], node: str
) -> tuple[tuple[str, ...], list[Note]]:
    """Structural rewrite over set-command tokens: interface-stanza paths get
    both the name and (when a stub realization forces it) the TYPE segment
    replaced; any other token equal to a mapped name is replaced in place."""
    rewritten: list[str] = []
    leftover: set[str] = set()
    targets = set(mapping.values())
    for line in lines:
        try:
            tokens = shlex.split(line, posix=False)
        except ValueError:
            rewritten.append(line)
            continue
        # ONE pass over the original tokens — an emitted replacement is never
        # itself re-examined, so shifted maps (eth1->eth2, eth2->eth3) cannot
        # cascade.
        new_tokens: list[str] = []
        stanza_target: str | None = None
        for index, token in enumerate(tokens):
            quoted = len(token) >= 2 and token[0] in "'\"" and token[-1] == token[0]
            bare = token[1:-1] if quoted else token
            replacement = mapping.get(bare)
            if replacement is None:
                if _VYOS_TOKEN_RE.match(bare) is not None and bare not in targets:
                    leftover.add(bare)
                new_tokens.append(token)
                continue
            new_tokens.append(f"{token[0]}{replacement}{token[0]}" if quoted else replacement)
            if index == 3 and tokens[0] == "set" and tokens[1] == "interfaces":
                stanza_target = replacement
        if stanza_target is not None:
            new_tokens[2] = _vyos_type_for(stanza_target)
        rewritten.append(" ".join(new_tokens))
    notes = [
        Note(
            node,
            f"carried config references {token}, which maps to no lab interface — "
            "review that config after import",
        )
        for token in sorted(leftover)
    ]
    return tuple(rewritten), notes


def wrap_raw(text: str) -> str:
    """Carry files are Jinja templates to netlab; `{% raw %}` keeps device
    config containing brace sequences byte-exact through the render."""
    return "{% raw %}\n" + text + ("\n" if not text.endswith("\n") else "") + "{% endraw %}\n"
