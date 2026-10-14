import asyncio
from functools import partial
import ray
from ray import serve

from fastapi import Depends, FastAPI, WebSocket, Request
from fastapi.sse import EventSourceResponse
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import redis.asyncio as redis_client

from deployment.transcriptor import DeployWhisper
from deployment.translator import DeployMiLMMT
from auth.oauth import AuthClaims, get_current_websocket_user
from api.auth import router as auth_router
from api.management.connection_manager import ConnectionManger
from api import speaker, listener

""" 
Ray의 전역 초기 설정
 - _temp_dir은 반드시 절대 경로로 설정해야 함. 프로젝트 경로에 유의하여 적절히 수정 바람 (malieum-beta 폴더의 경우 수정 필요없음)
 - 아직 세부적인 설정이 정의되지 않음. 공식 문서를 읽고 배포 환경에 적합하게 수정 바람

"""
ray.init(_temp_dir="/data/malieum-beta/temp", ignore_reinit_error=True)


"""
FastAPI 프레임워크 설정
 - Lifespan은 asynccontextmanager로 관리
 - 일반적인 라우터는 include_router 함수를 사용해서 통합함
 - Ray Deployment Handle이 포함된 라우터는 원인을 알 수 없는 메모리 공유 문제로 데코레이터를 사용해서 통합함
 - add_midddleware는 아직 정의가 완료되지 않음. 공식 문서와 예제를 보고 배포 환경에 적합하게 수정 바람

"""
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = redis_client.Redis(
            host='localhost',
            port=6380,
            db=0,
            decode_responses=True
        )
    app.state.connection_manager = ConnectionManger(app.state.redis)
    await app.state.redis.flushdb()
    yield
    await app.state.redis.close()

app = FastAPI(lifespan=lifespan)
app.include_router(auth_router)
app.add_middleware( # 수정 필요
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


""" 
Ingress Deployment
Ray Serve의 진입점이자 API 서버에 기대되는 모든 동작을 수행하는 메인 프로세스

주요 기능:
 - Nginx의 리버스 프록시를 통과해 온 모든 API 요청에 대해 기대되는 동작을 수행한 후 결과값을 반환함.
 - 전사/번역 Deployment의 핸들러를 가지며 이들의 동작을 관리함.
 - 앱의 활동을 제어하고 외부 컨테이너인 Redis나 Nginx와 연결을 수행함. 

Deployment로써의 성질:
 - 전사와 번역 Deployment를 바인딩받아 이를 제어하는 핸들러를 가진다.
 - 핸들러는 Ingress Deployment를 다른 각각의 Deployment와 연결하는 통로이다.
 - 모든 전사/번역 요청은 핸들러를 통해 타 Deployment로 전송되어 해당 Deploy에서 처리된 후 다시 반환된다.

진입점으로써의 성질:
 - FastAPI는 Ingress를 래핑하고 Ingress는 API 서버로 수신되는 요청을 FastAPI에게 위임한다.
 - 모든 통신은 FastAPI를 매개한다.

"""
@serve.deployment
@serve.ingress(app)
class IngressServer:
    def __init__(self, transcriptor_handle, translator_handle):
        self.transcriptor_handle = transcriptor_handle
        self.translator_handle = translator_handle

    @app.websocket("/api/streaming")
    async def websocket_endpoint(
        self, 
        websocket: WebSocket,
        auth_claims: AuthClaims = Depends(get_current_websocket_user), # 먼저 인증(의존성 주입)
    ):
        await speaker.stream(
            websocket,
            app.state.redis,
            app.state.connection_manager,
            self.transcriptor_handle, 
            self.translator_handle,
            auth_claims,
            )

    @app.get("/api/broadcast/{session_id}")
    async def websocket_endpoint(self, request: Request, session_id: str):
        return EventSourceResponse(
            listener.broadcast_generator(
                session_id,
                app.state.redis,
                app.state.connection_manager,
            ))
        

app_transcriptor = DeployWhisper.bind()
app_translator = DeployMiLMMT.bind()
app_ingress = IngressServer.bind(app_transcriptor, app_translator)