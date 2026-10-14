import asyncio
import json
import traceback

import redis.asyncio as redis
from fastapi import APIRouter, Request, Depends, WebSocket, WebSocketDisconnect
from ray.serve.handle import DeploymentHandle

from auth.oauth import AuthClaims
from database.redis_manager import SessionKeyMap, SpeakerSide
from api.management.message_schema import SystemMessage
from api.management.connection_manager import ConnectionManger
from api.speaker_helper import websocket_loop, transcription_loop, translation_loop
from api.speaker_helper.context_specs import SpeakerContext

"""
비동기적으로 구현된 Speaker 측의 라우터이자 핸들러

주요 기능:
 - 웹소켓의 핸드쉐이킹 과정과 세션 할당을 책임진다.
 - 코루틴으로 정의된 웹소켓 루프, 전사 루프, 번역 루프의 실행과 종료를 책임진다.
 - 웹소켓의 연결 종료와 이에 따른 세션 만료를 책임진다.

상태 관리:
 - connection_manager를 주입받아 연결/세션 상태 관리를 위임한다.
 - SessionKeyMap과 SpeakerSideRedisManager를 정의하고 Redis와 관련한 동작을 위임한다. 
 - SpeakerContext를 정의하고 Speaker의 동작에 필요한 다양한 자료구조를 위임한다.
 
"""
async def stream(
    websocket: WebSocket,
    redis: redis,
    connection_manager: ConnectionManger,
    transcriptor_handle: DeploymentHandle,
    translator_handle: DeploymentHandle,
    auth_claims: AuthClaims
    ):

    try:
        session_id = await connection_manager.connect(websocket)
        initial_message = await asyncio.wait_for(websocket.receive_json(), timeout=3.0)
        initial_message = initial_message.get("payload", initial_message)

        print(f"[INFO] WebSocket connection accepted: {auth_claims.sub}")
        print(f"[INFO] Session ID: {session_id}")

        await websocket.send_json({
            "type": "session",
            "payload": {
                "pin": session_id,
                "sessionId": session_id,
                "broadcastUrl": f"/api/broadcast/{session_id}",
            }
        })

    except Exception as e:
        print(f"[INFO] Websocket initial/auth connection failed: {e}")
        try:
            await websocket.send_json({
                "type": "auth_error",
                "message": "Authentication failed"
            })
            await websocket.close(code=1008)
        except Exception as e:
            pass
        finally:
            await connection_manager.disconnect(websocket, direct=True)

    try:
        redis_keymap = SessionKeyMap(session_id)
        redis_manager = SpeakerSide(redis, redis_keymap)
        context = SpeakerContext(session_id, redis_keymap)
        context.language_group = initial_message["languages"]
        
        message = SystemMessage(
            type="system-message",
            status="success",
            condition="alive",
            detail="Websocket successfully Connected"
        )
        await redis_manager.update_stream(
            redis_keymap.stream_system_message, 
            message.model_dump()
            )
        await redis_manager.update_hash({
            "pin": session_id,
            "auth_sub": auth_claims.sub,
            "auth_provider": auth_claims.provider,
            "language_group": json.dumps(context.language_group)
        })


        tasks = [
            asyncio.create_task(websocket_loop.socket_loop(context, websocket), name="socket_loop"),
            asyncio.create_task(transcription_loop.whisper_transcription(context, transcriptor_handle, redis_manager, redis_keymap), name="transcription_loop"),
            asyncio.create_task(translation_loop.general_translation(context, translator_handle, redis_manager, redis_keymap), name="translation_loop")
        ]

        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            exc = task.exception()
            if exc:
                print(f"[TASK ERROR] {task.get_name()}: {type(exc).__name__}: {exc}", flush=True)
                traceback.print_exception(type(exc), exc, exc.__traceback__)
                for pending_task in pending:
                    pending_task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                raise exc

        if pending:
            await asyncio.gather(*pending)
        # 비정상 종료상태가 30분이 넘으면 강제종료하기

    except asyncio.TimeoutError as e:
        return
    except (KeyError, json.JSONDecodeError) as e:
        return 
    except Exception as e:
        print(f"Unexpected error in main stream function: {e}")
        traceback.print_exc()

    finally:
        await connection_manager.disconnect(websocket)
        message = SystemMessage(
            type="system-message",
            status="success",
            condition="dead",
            detail="Connection successfully disconnected"
        )
        await redis_manager.update_stream(redis_keymap.stream_system_message, message.model_dump())
        await redis_manager.set_expire()
        