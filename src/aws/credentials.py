"""
Profil AWS "forgé" : credentials via AssumeRole ou clés fixes (dev).
Toutes les requêtes proxy utilisent ce profil.
"""
import boto3
from config import settings
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from boto3 import Session as Boto3Session


def get_aws_session(
    region_name: Optional[str] = None,
    role_arn: Optional[str] = None,
    session_name: Optional[str] = None,
) -> "Boto3Session":
    """
    Retourne une session boto3 avec le profil forgé :
    - Si aws_role_arn est défini : assume ce rôle (avec clés dev ou instance profile pour l'appel AssumeRole).
    - Sinon si aws_access_key_id/secret : utilise ces clés.
    - Sinon : credentials par défaut (env / instance profile).
    """
    region = region_name or settings.aws_region
    role = role_arn or settings.aws_role_arn
    session_name_val = session_name or settings.aws_role_session_name

    # Session de base (pour assumer le rôle ou appels directs)
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        base_session = boto3.Session(
            region_name=region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )
    else:
        base_session = boto3.Session(region_name=region)

    if not role:
        return base_session

    # Assumer le rôle et retourner une session avec les credentials temporaires
    sts = base_session.client("sts")
    resp = sts.assume_role(
        RoleArn=role,
        RoleSessionName=session_name_val,
    )
    creds = resp["Credentials"]
    return boto3.Session(
        region_name=region,
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )


# Session partagée (évite d'appeler AssumeRole à chaque requête)
_cached_session: Optional["Boto3Session"] = None


def get_cached_aws_session() -> "Boto3Session":
    global _cached_session
    if _cached_session is None:
        _cached_session = get_aws_session()
    return _cached_session
