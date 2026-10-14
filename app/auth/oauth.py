import os
import time
from pathlib import Path
from typing import Any, Literal

import jwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, WebSocket, WebSocketException, status
from fastapi.security import OAuth2PasswordBearer
from jwt import InvalidTokenError
from pydantic import BaseModel

# 현재 파일 기준으로 위로 2단계 올라간 위치의 .env를 읽음(설정 완)
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

# 현재 지원하는 OAuth 제공자를 "google" 하나로 제한
Provider = Literal["google"]

# 요청에 이런 헤더에서 토큰부분만 사용
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/exchange", auto_error=False)

# 인증 설정 모델
class AuthSettings(BaseModel):
    # 토큰서명비밀키
    secret: str = os.getenv("KISSOS_AUTH_SECRET", "dev-kissos-auth-secret-change-me")

    issuer: str = os.getenv("KISSOS_AUTH_ISSUER", "kissos")
    audience: str = os.getenv("KISSOS_AUTH_AUDIENCE", "kissos-extension")
    token_ttl_seconds: int = int(os.getenv("KISSOS_AUTH_TOKEN_TTL", "21600"))

# Google OAuth에 필요한 설정 구조
class OAuthProviderConfig(BaseModel):
    client_id: str                      # 클라이언트 ID
    client_secret: str = ""             # 클라이언트 비밀번호
    authorization_url: str              # 로그인 페이지 URL
    token_url: str                      # code to token
    userinfo_url: str                   # 시용자 정보 조회 URL
    scope: str = "openid email profile" # 요청할 권한 범위

# 토큰 교환 요청(OAuth 로그인 후 백엔드로 보내는 요청)
class ExchangeRequest(BaseModel):
    provider: Provider
    code: str
    code_verifier: str
    redirect_uri: str

# Google에서 받아온 사용자를 내부에서 표현
class AuthUser(BaseModel):
    id: str                             # Google의 sub
    email: str | None = None            # 이메일
    name: str | None = None             # 이름

# JWT 클레임(검증 후 꺼내는 사용자 정보)
class AuthClaims(BaseModel):
    sub: str                            # 사용자 식별자
    provider: str                       # 로그인 제공자
    email: str | None = None            # 이메일
    name: str | None = None             # 이름

# .env 값을 읽어서 인증 설정 객체
settings = AuthSettings()

# Google OAuth 설정
PROVIDER_CONFIG: dict[str, OAuthProviderConfig] = {
    "google": OAuthProviderConfig(
        client_id=os.getenv("GOOGLE_CLIENT_ID", ""),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET", ""),
        authorization_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        userinfo_url="https://openidconnect.googleapis.com/v1/userinfo",
    ),
}

# OAuth 설정이 제대로 있는지 확인 -> 안되어있으면 서버에러
def require_provider_config(provider: str) -> OAuthProviderConfig:
    config = PROVIDER_CONFIG[provider]
    if not config.client_id:
        raise HTTPException(status_code=500, detail=f"{provider} client id is not configured")
    return config

# Google userinfo 응답을 내부 AuthUser 형태
def normalize_user(provider: str, userinfo: dict[str, Any]) -> AuthUser:
    return AuthUser(
        id=str(userinfo.get("sub", "")),
        email=userinfo.get("email"),
        name=userinfo.get("name"),
    )

# 내부 JWT 토큰 발급
def issue_kissos_token(provider: str, user: AuthUser) -> tuple[str, int]:
    # 현재 시간과 만료 시간을 계산
    issued_at = int(time.time())
    expires_at = issued_at + settings.token_ttl_seconds
    payload = {
        "iss": settings.issuer,                         # 발금자
        "aud": settings.audience,                       # 대상            
        "sub": f"{provider}:{user.id}",                 #사용자 식별자
        "provider": provider,                           # 구글(고정임)
        "email": user.email,                            # 사용자 정보(이메일)
        "name": user.name,                              # 사용자 정보(이름)
        "iat": issued_at,                               # 발급 시간
        "exp": expires_at,                              # 만료 시간
    }
    token = jwt.encode(payload, settings.secret, algorithm="HS256")
    return token, expires_at

# 내부 JWT 토큰 검증
def verify_kissos_token(token: str) -> AuthClaims:
    try:
        # 검증항목: 서명, 만료 여부, aud(대상)가 맞는지, iss(발급자)가 맞는지, 알고리즘이 HS256인지
        payload = jwt.decode(
            token,
            settings.secret,
            algorithms=["HS256"],
            audience=settings.audience,
            issuer=settings.issuer,
        )
    except InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token") from exc
    # 검증된 payload를 AuthClaims로 변환
    return AuthClaims(
        sub=payload["sub"],
        provider=payload.get("provider", ""),
        email=payload.get("email"),
        name=payload.get("name"),
    )

# FastAPI 라우터에서 의존성으로 사용
async def get_current_user(token: str | None = Depends(oauth2_scheme)) -> AuthClaims:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing access token")
    return verify_kissos_token(token)

# WebSocket 토큰 추출
def get_websocket_bearer_token(websocket: WebSocket) -> str | None:
    authorization = websocket.headers.get("authorization")
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token:
            return token

    return websocket.query_params.get("access_token")

# WebSocket 현재 사용자 가져오기
async def get_current_websocket_user(websocket: WebSocket) -> AuthClaims:
    token = get_websocket_bearer_token(websocket)
    # 토큰이 없으면 연결 거부
    if not token:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Missing access token")

    # 토큰 검증 실패 시 HTTP 예외를 WebSocket 예외로 바꿔 리턴
    try:
        return verify_kissos_token(token)
    except HTTPException as exc:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason=exc.detail) from exc
