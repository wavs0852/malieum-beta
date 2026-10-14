import httpx
from fastapi import APIRouter, HTTPException

# auth/oauth.py에서만든 로직 재사용
from auth.oauth import (
    ExchangeRequest,
    PROVIDER_CONFIG,
    issue_kissos_token,
    normalize_user,
    require_provider_config,
)

# API는 /api/auth로 시작
router = APIRouter(prefix="/api/auth")

# OAuth 제공자 목록 조회(지금은 구글 유일)
@router.get("/providers")
async def get_oauth_providers():
    return {
        provider: {
            "label": provider.title(),
            "clientId": config.client_id,
            "authorizationEndpoint": config.authorization_url,
            "scope": config.scope,
        }
        for provider, config in PROVIDER_CONFIG.items()
    }

# OAuth code 교환
@router.post("/exchange")
async def exchange_oauth_code(request: ExchangeRequest):
    config = require_provider_config(request.provider)
    # Google에 보낼 데이터
    token_payload = {
        "grant_type": "authorization_code",
        "client_id": config.client_id,
        "code": request.code,
        "redirect_uri": request.redirect_uri,
        "code_verifier": request.code_verifier,
    }
    if config.client_secret:
        token_payload["client_secret"] = config.client_secret
    # Google에 토큰 요청
    async with httpx.AsyncClient(timeout=10.0) as client:
        token_response = await client.post(config.token_url, data=token_payload)
        if token_response.status_code >= 400:
            raise HTTPException(status_code=401, detail=token_response.text)
        # access_token 추출
        provider_tokens = token_response.json()
        provider_access_token = provider_tokens.get("access_token")
        if not provider_access_token: # access_token 없음 에러
            raise HTTPException(status_code=401, detail="provider access token was missing")
        # 사용자 정보 요청
        user_response = await client.get(
            config.userinfo_url,
            headers={"Authorization": f"Bearer {provider_access_token}"},
        )
        if user_response.status_code >= 400:
            raise HTTPException(status_code=401, detail=user_response.text)

    user = normalize_user(request.provider, user_response.json())
    if not user.id:
        raise HTTPException(status_code=401, detail="provider user id was missing")
    # 내부 JWT 발급
    access_token, expires_at = issue_kissos_token(request.provider, user)
    return {
        "provider": request.provider,
        "accessToken": access_token,
        "user": user.model_dump(),
        "expiresAt": expires_at * 1000,
    }
