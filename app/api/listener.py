"""따라서 클라이언트 프론트엔드 코드(JS/TS)에서 이 메시지를 받았을 때 명시적으로 eventSource.close()를 호출해 주지 않으면, 클라이언트가 주기적으로 다시 접속을 시도하면서 서버 측 유효성 검사 로직을 계속 건드리는 무한 루프에 빠질 수 있습니다."""
import json
from fastapi import APIRouter, Request, Depends, WebSocket, WebSocketDisconnect
from fastapi.sse import EventSourceResponse
import asyncio
import redis.asyncio as redis

from database.redis_manager import SessionKeyMap, ListenerSide
from api.management.message_schema import PublishForm
from api.management.connection_manager import ConnectionManger

async def broadcast_generator(
        session_id: str, 
        redis: redis,
        connection_manager: ConnectionManger,
        ):
    
    def state_handler(condition, data):
        for item in data:
            state["condition"] = item[1]["condition"]
            state["detail"] = item[1]["detail"]
            
    nono = await connection_manager.check_session_id(session_id)

    if not nono:
        message = PublishForm(type="init")
        message.payload["session-state"] = "dead"
        yield f"data: {message.model_dump_json()}\n\n"
        return
        
    try:
        
        state = {"condition": None, "detail": None}
        redis_keymap = SessionKeyMap(session_id)
        redis_manager = ListenerSide(redis, redis_keymap)
        language_group = await redis_manager.read_hash("language_group")

        try: 
            message = PublishForm(type="init")
            message.payload["session-state"] = "alive"
            message.payload["language-group"] = json.loads(language_group)

            bundle = await redis_manager.read_snapshot()
            if data := bundle.get("transcription"): message.payload["transcription"] = [item for item in data if item[1]["complete"] == "true"]
            if data := bundle.get("translation"): message.payload["translation"] = data
            if data := bundle.get("system-message"): state_handler(state, data)

            yield f"data: {message.model_dump_json()}\n\n"

        except Exception as e:
            print("listener init error:", e)
            state["condition"] = "dead"
            state["detail"] = "SSE initializing failed"
            

        
        while state["condition"] == "alive":
            try:
                message = PublishForm(type="next")
                bundle = await redis_manager.read_stream()
                if data := bundle.get("transcription"): message.payload["transcription"] = data[-1]
                if data := bundle.get("translation"): message.payload["translation"] = data[-1]
                if data := bundle.get("system-message"): state_handler(state, data)

                if message.payload: 
                    yield f"data: {message.model_dump_json()}\n\n"

            except Exception as e:
                print("listener while error:", e)
            else:
                pass
            finally:
                pass

    except Exception as e:
        print("listener end error:", e)
    
    finally:
        message = PublishForm(type="done")
        message.payload["detail"] = state["detail"]
        yield f"data: {message.model_dump_json()}\n\n"
