import os
from passlib.context import CryptContext
from itsdangerous import URLSafeSerializer, BadSignature

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(p: str) -> str:
    return pwd_context.hash(p)

def verify_password(p: str, hashed: str) -> bool:
    return pwd_context.verify(p, hashed)

def _secret() -> str:
    s = os.getenv("SECRET_KEY", "").strip()
    if not s:
        s = "dev-secret-change-me"
    return s

serializer = URLSafeSerializer(_secret(), salt="stefanos-garage-session")

def sign_session(user_id: int) -> str:
    return serializer.dumps({"uid": user_id})

def read_session(token: str):
    try:
        data = serializer.loads(token)
        return int(data.get("uid"))
    except (BadSignature, ValueError, TypeError):
        return None
