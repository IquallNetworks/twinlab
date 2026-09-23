"""Sign-in through admin-configured OIDC providers (contract delta 33).

Design record: docs/oidc.md. The backend runs the authorization-code + PKCE
flow itself and ends it by issuing the ORDINARY Twinlab session, so nothing
past `flow` learns OIDC exists.
"""
