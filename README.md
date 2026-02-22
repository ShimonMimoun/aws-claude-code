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

## Configurer Claude Code avec ce proxy

Pour que **Claude Code** (Cursor, scripts, ou tout code) utilise ce proxy au lieu d’appeler AWS/Bedrock directement, suivre ces étapes.

### Étape 1 : Démarrer le proxy

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

L’URL du proxy est **`http://localhost:8000`** (ou l’URL de votre déploiement).

### Étape 2 : Obtenir un token (une fois)

**Option A – Web**  
Ouvrir **http://localhost:8000/login** dans le navigateur, suivre le device code Entra (ou la page de login), puis récupérer le JWT si besoin (pour le CLI / env, le cookie ne sert que pour le navigateur).

**Option B – CLI (recommandé pour Claude Code)**  
Depuis la racine du projet :

```bash
# Entra ID
python -m src.client login-entra --proxy-url http://localhost:8000

# ou Cognito
python -m src.client login-cognito --proxy-url http://localhost:8000
```

Cela écrit automatiquement **`bedrock-proxy.config.json`** avec l’URL et le token. Aucune variable d’environnement à saisir à la main.

### Étape 3 : Donner l’URL et le token à Claude Code

**Option 1 – Fichier de config (recommandé)**  
Si vous avez fait l’étape 2 avec le CLI, le fichier **`bedrock-proxy.config.json`** est déjà à la racine du projet. Le client Python du projet le lit automatiquement. Rien à faire de plus.

**Option 2 – Variables d’environnement**  
Dans le terminal où vous lancez Cursor / vos scripts, ou dans le fichier d’env de votre OS :

```bash
export BEDROCK_PROXY_URL=http://localhost:8000
export BEDROCK_PROXY_TOKEN=votre_jwt_entra_ou_cognito
```

Les noms **`AWS_PROXY_URL`** et **`AWS_PROXY_TOKEN`** sont aussi reconnus.

**Option 3 – Fichier à la main**  
Créer `bedrock-proxy.config.json` à la racine du projet :

```json
{
  "url": "http://localhost:8000",
  "token": "VOTRE_JWT_ENTRA_OU_COGNITO"
}
```

Ne pas commiter ce fichier (il est dans `.gitignore`).

### Étape 4 : Règle Cursor (déjà dans le projet)

Le fichier **`.cursor/rules/aws-proxy-claude.mdc`** est déjà présent. Il indique à Claude Code de :

- ne **jamais** appeler AWS/Bedrock directement ;
- utiliser le proxy (`POST /api/aws/execute`) avec l’URL et le token (env ou `bedrock-proxy.config.json`) ;
- privilégier le client Python `src.client` (voir ci-dessous).

Aucune config Cursor supplémentaire n’est nécessaire : ouvrir le projet dans Cursor suffit.

### Étape 5 : Utiliser le client dans le code

Dans votre code (ou quand Claude Code génère du code qui appelle Bedrock), utiliser le client du projet :

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
# resp contient la réponse AWS (body éventuellement en base64)
```

Appel générique (n’importe quel service AWS) :

```python
from src.client import execute

result = execute("s3", "list_buckets")
result = execute("bedrock-runtime", "invoke_model", params={"modelId": "...", "body": ...})
```

Le client nécessite **`httpx`** (déjà dans `requirements.txt`).

### Récapitulatif

| Étape | Action |
|-------|--------|
| 1 | Démarrer le proxy : `uvicorn src.main:app --host 0.0.0.0 --port 8000` |
| 2 | Se connecter une fois : `python -m src.client login-entra` (ou `login-cognito`) |
| 3 | Rien à faire si vous utilisez `bedrock-proxy.config.json` (écrit par le CLI) |
| 4 | La règle `.cursor/rules/aws-proxy-claude.mdc` est déjà active dans le projet |
| 5 | Dans le code : `from src.client import get_proxy_client` puis `get_proxy_client().invoke_model(...)` |

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
