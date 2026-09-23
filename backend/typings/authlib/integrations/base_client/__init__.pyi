class OAuthError(Exception):
    error: str
    description: str | None
