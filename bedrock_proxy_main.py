#!/usr/bin/env python3
"""
Point d'entrée unique pour l'exécutable PyInstaller.
Usage:
  bedrock-proxy [serve]        → lance le serveur (port 8000)
  bedrock-proxy login-entra    → login Entra ID, écrit la config
  bedrock-proxy login-cognito → login Cognito, écrit la config
"""
import os
import sys

# Quand on est en exe PyInstaller : .env et config à côté de l'exe
if getattr(sys, "frozen", False):
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    os.chdir(exe_dir)


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] == "serve":
        import uvicorn
        from src.main import app
        host = os.environ.get("BEDROCK_PROXY_HOST", "0.0.0.0")
        port = int(os.environ.get("BEDROCK_PROXY_PORT", "8000"))
        uvicorn.run(app, host=host, port=port)
        return 0
    # Déléguer au CLI (login-entra, login-cognito avec --proxy-url etc.)
    from src.client import main as client_main
    return client_main(argv)


if __name__ == "__main__":
    sys.exit(main())
