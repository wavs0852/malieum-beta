from fastapi import APIRouter, Request, Depends, WebSocket, WebSocketDisconnect
from typing import Any, Dict, List
import traceback


"""
speaker.stream의 websocket 루프를 책임지는 비동기 핼퍼 함수

주요 기능:
 - 웹소켓 연결이 수립된 이후 수신되는 메시지를 핸들링한다.
 - 메시지가 바이트일 경우 오디오 데이터로 간주하고 오디오 큐에 메시지를 삽입한다.
 - 연결 종료 메시지를 받거나 연결 상태에서 오류가 발생할 경우 연결을 종료하고 큐에도 None을 넣어 종료 상태를 알린다.

상태 관리:
 - context(SpeakerContext)를 주입받아 정보를 공유한다.
"""
async def socket_loop(context, websocket):
    while True:
        try:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                print(f"[INFO] Websocket disconnected by user: {message.get('code')}")
                break
            if message["type"] != "websocket.receive":
                continue
            data = message.get("bytes")

            if data is None:
                continue
            
            await context.audio_queue.put(data)
            print(f"[DEBUG] Received audio frame of length {len(data)} bytes")

        except WebSocketDisconnect as e:
            print(f"[WARN] WebSocket Disconnect by unknown error: code={e.code}")
            break

        except Exception as e:
            print(f"[WARN] Unexpected error in socket_loop: type={type(e).__name__}, detail={e!r}")
            traceback.print_exc()
            break

    await context.audio_queue.put(None)