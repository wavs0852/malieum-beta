from typing import Any, Dict
from pydantic import BaseModel, ConfigDict

"""
주로 사용되는 메시지 형식 스키마
프로세스 내부 통신과 API 통신 모두에 사용된다.
"""

class PublishForm(BaseModel):
    """
    type: str ("init" | "next" | "done")
    payload: Dict[str, Any]
    """
    type: str 
    payload: Dict[str, Any] = {}


class MessageForm(BaseModel):
    """
    base class for TranscriptionMessage and TranslationMessage

    type: str ("transcription" | "translation" | "system-message")
    status: str ("success" | "error" | "none") 
    """
    model_config = ConfigDict(extra='allow')
    type: str
    status: str

class SystemMessage(MessageForm):
    """
    type: str
    status: str 
    condition: str ("alive" | "dead")
    detail: str
    """
    condition: str 
    detail: str

class TranscriptionMessage(MessageForm):
    """
    type: str
    status: str
    number: int
    complete: str ("true" or "false")
    language: str
    result: str
    """
    number: int
    complete: str
    language: str
    result: str

class TranslationMessage(MessageForm):
    """ 
    type: str
    status: str
    number: int
    complete: str 
    language: str (comma-separated if multiple)

    ---
    additional fields for translation results (unpacked from translation result)
    translation_lang_1: str 
    translation_lang_2: str 
    ... 
    translation_lang_n: str 
    """
    number: int
    complete: str
    language: str