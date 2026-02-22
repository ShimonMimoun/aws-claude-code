# AWS Proxy – Authentification SSO + profil forgé

Serveur Python qui assure **l’authentification** (Azure Entra ID ou Cognito) et fait **proxy** de toutes les requêtes AWS avec un **profil forgé** (rôle IAM assumé). Le client ne parle qu’à ce serveur ; aucune requête n’est envoyée directement à AWS par le client.

## Principe

1. **Authentification** : le client s’authentifie en SSO (Azure Entra ID ou Cognito) et envoie un **Bearer JWT** à chaque requête.
2. **Profil forgé** : le serveur utilise un rôle IAM (ou des clés) configurés côté serveur. Tous les appels AWS sont faits avec cette identité.
3. **Proxy** : le client appelle uniquement l’API du serveur (ex. `POST /api/aws/execute`). Le serveur exécute l’action AWS et renvoie le résultat.

## Prérequis

- Python 3.10+
- Compte AWS (rôle IAM à assumer ou clés)
- Azure Entra ID **ou** Cognito configuré (app + audience / User Pool)

## Installation

```bash
cd bedrock
python -m venv .venv
source .venv/bin/activate   # ou .venv\Scripts\activate sur Windows
pip install -r requirements.txt
cp .env.example .env
# Éditer .env (Entra ou Cognito + AWS)
```

## Configuration (.env)

- **Auth** : `AUTH_PROVIDER=entra` ou `cognito`, puis les variables correspondantes (voir `.env.example`).
- **AWS** : `AWS_REGION`, `AWS_ROLE_ARN` pour le rôle à assumer. En dev, `AWS_ACCESS_KEY_ID` et `AWS_SECRET_ACCESS_KEY` peuvent remplacer l’AssumeRole.

## Lancement

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

### Connexion tout automatique (web ou CLI)

- **Web** : ouvrir **`http://localhost:8000/login`** → suivre les instructions (device code Entra) → une fois connecté, un cookie est enregistré : les appels depuis le même navigateur n’ont plus besoin de Bearer.
- **CLI Entra** : `python -m src.client login-entra --proxy-url http://localhost:8000` → saisir le code dans le navigateur → la config `bedrock-proxy.config.json` est écrite automatiquement.
- **CLI Cognito** : `python -m src.client login-cognito --proxy-url http://localhost:8000` → le navigateur s’ouvre sur le Hosted UI Cognito → après login, la config est écrite. Dans Cognito, ajouter l’URL de callback **`http://localhost:8765/callback`** dans l’app client.

- **Health** : `GET http://localhost:8000/health`
- **Infos utilisateur** : `GET http://localhost:8000/me` (header `Authorization: Bearer <token>` ou cookie après `/login`)
- **Proxy AWS** : `POST http://localhost:8000/api/aws/execute` avec body JSON :

```json
{
  "service": "s3",
  "action": "list_buckets",
  "params": {},
  "region": "eu-west-1"
}
```

Actions en **snake_case** boto3 (ex. `list_buckets`, `invoke_model`). Pour Bedrock : `service: "bedrock-runtime"`, `action: "invoke_model"`, `params` selon l’API.

## Exemple d’appel (curl)

```bash
# Avec un JWT Entra ou Cognito
curl -X POST http://localhost:8000/api/aws/execute \
  -H "Authorization: Bearer YOUR_JWT" \
  -H "Content-Type: application/json" \
  -d '{"service":"s3","action":"list_buckets","params":{}}'
```

## Configuration Claude Code / client proxy

Pour que **Claude Code** (ou tout script) utilise ce proxy au lieu d’appeler AWS directement :

### 1. Variables d’environnement

```bash
export BEDROCK_PROXY_URL=http://localhost:8000
export BEDROCK_PROXY_TOKEN=votre_jwt_entra_ou_cognito
```

Les noms `AWS_PROXY_URL` et `AWS_PROXY_TOKEN` sont aussi reconnus.

### 2. Fichier de config (optionnel)

Copier l’exemple et renseigner l’URL et le token :

```bash
cp bedrock-proxy.config.example.json bedrock-proxy.config.json
# Éditer bedrock-proxy.config.json (url + token)
```

Format attendu : `{ "url": "http://...", "token": "..." }`. Ne pas commiter le fichier contenant le token.

### 3. Règle Cursor

Le dossier `.cursor/rules/` contient **aws-proxy-claude.mdc** : dans ce projet, Cursor/Claude est guidé pour utiliser le proxy pour tous les appels AWS/Bedrock (pas d’appels directs, pas de credentials AWS locales).

### 4. Client Python dans le projet

Pour appeler Bedrock (Claude) via le proxy depuis du code Python :

```python
from src.client import get_proxy_client
import json

client = get_proxy_client()  # lit BEDROCK_PROXY_* ou bedrock-proxy.config.json
body = {
    "anthropic_version": "bedrock-2023-05-31",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 1024,
}
resp = client.invoke_model(
    modelId="anthropic.claude-3-5-sonnet-20241022-v2:0",
    body=body,
)
# resp contient la réponse AWS (body éventuellement en base64 dans la réponse)
```

Appel générique (n’importe quel service AWS) :

```python
from src.client import execute

result = execute("s3", "list_buckets")
result = execute("bedrock-runtime", "invoke_model", params={"modelId": "...", "body": ...})
```

Le client nécessite `httpx` (`pip install httpx`).

---

## Structure

- `config.py` : paramètres (auth + AWS).
- `src/auth/` : validation JWT Entra ID et Cognito, dépendance `get_current_user`.
- `src/aws/` : session AWS (AssumeRole ou clés), `execute_aws_api` pour exécuter une action.
- `src/main.py` : FastAPI, routes `/health`, `/login`, `/api/login/*`, `/api/aws/execute`, `/api/usage/*`.
- `src/login_web.py` : flow Entra device code pour la page `/login`.
- `src/client.py` : client Python + CLI (`login-entra`, `login-cognito`) pour config automatique.
- `src/usage/` : suivi d’utilisation (qui a utilisé, combien).
- `.cursor/rules/aws-proxy-claude.mdc` : règle Cursor pour utiliser le proxy avec Claude Code.

Toutes les requêtes AWS passent par le proxy et utilisent le profil forgé configuré sur le serveur.
