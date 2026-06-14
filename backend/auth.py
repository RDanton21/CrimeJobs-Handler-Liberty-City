def require_admin() -> str:
    """Auth deaktiviert — Dashboard ist nur lokal (127.0.0.1:8000) erreichbar.

    Wird weiterhin überall per Depends() eingebunden, prüft aber nichts mehr
    und löst kein HTTP-Basic-Popup aus.
    """
    return "admin"
