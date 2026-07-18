import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from .config import settings

_security = HTTPBasic(auto_error=False)

_UNAUTHORIZED_HEADERS = {"WWW-Authenticate": 'Basic realm="Crime Automation"'}


def require_admin(
    credentials: HTTPBasicCredentials | None = Depends(_security),
) -> str:
    """HTTP-Basic-Auth gegen ADMIN_USERNAME/ADMIN_PASSWORD (.env / Container-Env).

    War zeitweise deaktiviert, als das Dashboard nur lokal (127.0.0.1:8000)
    erreichbar war. Seit dem Docker-Deployment ist das Backend oeffentlich
    via Traefik (crime.bots.sektorrp.eu) erreichbar — hier MUSS geprueft werden.

    Fail-closed: ohne konfiguriertes Passwort (leer oder Default "change-me")
    wird der Zugriff komplett verweigert statt offen durchgelassen.
    """
    if not settings.admin_password or settings.admin_password == "change-me":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin-Passwort nicht konfiguriert (ADMIN_PASSWORD in .env setzen)",
        )
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Login erforderlich",
            headers=_UNAUTHORIZED_HEADERS,
        )
    user_ok = secrets.compare_digest(
        credentials.username.encode("utf-8"),
        settings.admin_username.encode("utf-8"),
    )
    pass_ok = secrets.compare_digest(
        credentials.password.encode("utf-8"),
        settings.admin_password.encode("utf-8"),
    )
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Falsche Zugangsdaten",
            headers=_UNAUTHORIZED_HEADERS,
        )
    return credentials.username
