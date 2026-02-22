"""
Configuration centralisée : auth (Entra ID, Cognito) et AWS.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Auth : fournisseur actif ("entra" | "cognito")
    auth_provider: str = Field(default="entra", description="entra | cognito")

    # --- Azure Entra ID (OIDC)
    entra_tenant_id: Optional[str] = Field(default=None, description="Tenant ID Azure")
    entra_client_id: Optional[str] = Field(default=None, description="Application (client) ID")
    entra_client_secret: Optional[str] = Field(default=None, description="Client secret (optionnel pour public client)")
    entra_issuer: Optional[str] = Field(default=None, description="Ex: https://login.microsoftonline.com/{tenant}/v2.0")
    entra_audience: Optional[str] = Field(default=None, description="Audience attendue du token")

    # --- Cognito
    cognito_region: Optional[str] = Field(default=None, description="Région du User Pool")
    cognito_user_pool_id: Optional[str] = Field(default=None, description="User Pool ID")
    cognito_app_client_id: Optional[str] = Field(default=None, description="App client ID")
    cognito_jwks_url: Optional[str] = Field(default=None, description="URL JWKS (optionnel, dérivé du pool si absent)")
    cognito_domain_prefix: Optional[str] = Field(default=None, description="Domaine Hosted UI (ex: myapp → myapp.auth.<region>.amazoncognito.com)")

    # --- AWS : rôle à assumer après auth (profil "forgé")
    aws_region: str = Field(default="eu-west-1", description="Région AWS par défaut")
    aws_role_arn: Optional[str] = Field(default=None, description="ARN du rôle à assumer pour les appels proxy")
    aws_role_session_name: str = Field(default="bedrock-proxy-session", description="Nom de session AssumeRole")
    # Optionnel : utiliser des credentials fixes (pour dev) au lieu d'assumer un rôle
    aws_access_key_id: Optional[str] = Field(default=None, description="Access key (dev)")
    aws_secret_access_key: Optional[str] = Field(default=None, description="Secret key (dev)")

    # Suivi d'utilisation : fichier où append les événements (optionnel)
    usage_log_path: Optional[str] = Field(default=None, description="Ex: usage.jsonl")

    def get_entra_issuer(self) -> Optional[str]:
        if self.entra_issuer:
            return self.entra_issuer.rstrip("/")
        if self.entra_tenant_id:
            return f"https://login.microsoftonline.com/{self.entra_tenant_id}/v2.0"
        return None

    def get_cognito_jwks_url(self) -> Optional[str]:
        if self.cognito_jwks_url:
            return self.cognito_jwks_url
        if self.cognito_region and self.cognito_user_pool_id:
            return (
                f"https://cognito-idp.{self.cognito_region}.amazonaws.com/"
                f"{self.cognito_user_pool_id}/.well-known/jwks.json"
            )
        return None


settings = Settings()
