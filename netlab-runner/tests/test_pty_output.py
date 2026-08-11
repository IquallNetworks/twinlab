"""PTY transcript cleaning for the interactive docker channel (delta 28).

The fixture is a REAL transcript captured from `docker exec -it clab-…-pe1
su - vyos` on a running VyOS node (2026-08-10): the container TTY echoes what
we type, the login shell frames it with prompts and a farewell, and terminal
escapes ride along.
"""

from netlab_runner.runner import clean_pty_output

_COMMAND = "ping 10.2.0.4 vrf vpn_a count 2"
_PROMPT = "vyos@pe1:~$"
_RAW = (
    "\x1b[?1034h\x1b]0;vyos@pe1: ~\x07vyos@pe1:~$ ping 10.2.0.4 vrf vpn_a count 2\r\n"
    "PING 10.2.0.4 (10.2.0.4) 56(84) bytes of data.\r\n"
    "64 bytes from 10.2.0.4: icmp_seq=1 ttl=63 time=0.050 ms\r\n"
    "\r\n--- 10.2.0.4 ping statistics ---\r\n"
    "2 packets transmitted, 2 received, 0% packet loss, time 1031ms\r\n"
    "\x1b]0;vyos@pe1: ~\x07vyos@pe1:~$ exit\r\nlogout\r\n\x1b[K"
)


def testclean_pty_output_keeps_only_the_command_output() -> None:
    cleaned = clean_pty_output(_RAW, _COMMAND, _PROMPT)
    assert cleaned.splitlines()[0] == "PING 10.2.0.4 (10.2.0.4) 56(84) bytes of data."
    assert "0% packet loss" in cleaned
    # The session's own noise is gone: escapes, the echoed command and exit,
    # the shell's farewell, and every prompt.
    assert "\x1b" not in cleaned
    assert "\r" not in cleaned
    assert _PROMPT not in cleaned
    assert "logout" not in cleaned
    assert _COMMAND not in cleaned


def testclean_pty_output_survives_an_unknown_prompt() -> None:
    # If the banner never yielded a prompt, the transcript still loses its
    # escapes and echoes rather than being passed through raw.
    cleaned = clean_pty_output(_RAW, _COMMAND, "")
    assert "0% packet loss" in cleaned
    assert "\x1b" not in cleaned
    assert "logout" not in cleaned
