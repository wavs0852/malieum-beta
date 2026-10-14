import asyncio
from dataclasses import dataclass, field
from database.redis_manager import SessionKeyMap
from typing import Any, Dict, List

@dataclass
class SpeakerContext:
    session_id: str
    redis_keys: SessionKeyMap
    language_group: List[str] = field(default_factory=list)
    audio_queue: asyncio.Queue = field(init=False)
    trans_queue: asyncio.Queue = field(init=False)
    transcription_message_number: int = 0
    translation_message_number: int = 0
    connection_disconnected: bool = False
    connection_error: bool = False 

    def __post_init__(self):
        self.audio_queue = asyncio.Queue()
        self.trans_queue = asyncio.Queue()

    # NOTE (wavs): Simul-Whisper가 통합된 현재 로직으로는 불가능한 일이지만 혹시 로직이 바뀔 경우를 대비해서 메모함.
    # 개별 요청에서 오디오 입력에 대해 순차적인 처리를 하지 않는 경우 입력 순서와 관계없이 상대적으로 짧은 오디오의 전사가 빨리 끝나므로 처리 순서가 역전될 수 있음.
    # 이럴 경우 정렬 리스트를 만들고 순서에 따라 연속해서 처리해야함

