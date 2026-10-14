from dataclasses import dataclass, field
import redis.asyncio as redis
from typing import Any
import functools
from constant.global_vars import SESSION_EXPIRE_SECONDS

@dataclass
class SessionKeyMap:
    session_id: str
    prefix: str = field(init=False)
    hash_info: str = field(init=False)
    stream_system_message: str = field(init=False)
    stream_transcription: str = field(init=False)
    stream_translation: str = field(init=False)
    
    def __post_init__(self):
        self.prefix = f"session:{self.session_id}"
        self.hash_info = f"{self.prefix}:hash:info"
        self.stream_system_message = f"{self.prefix}:stream:system-message"
        self.stream_transcription = f"{self.prefix}:stream:trscrpt"
        self.stream_translation = f"{self.prefix}:stream:trslt"

@dataclass
class ManageKeyMap:
    prefix: str = "manage"
    set_active_session: str = f"{prefix}:set:active-session"
    set_inactive_session: str = f"{prefix}:set:inactive-session"
    set_active_clients: str = "none"
    # client_session_dict



class ManagerSide:
    def __init__(self, redis: redis, keymap: ManageKeyMap):
        self.client = redis
        self.keymap = keymap

    async def get_session_id(self, make_session_id):
        session_id = await self.client.spop(self.keymap.set_inactive_session)
        if not session_id:
            while True:
                session_id = make_session_id()
                if not await self.client.sismember(self.keymap.set_active_session, session_id):
                    break
            
        await self.client.sadd(self.keymap.set_active_session, session_id)
        return session_id
    
    async def return_session_id(self, session_id):
        async with self.client.pipeline(transaction=True) as pipe:
            pipe.srem(self.keymap.set_active_session, session_id)
            pipe.sadd(self.keymap.set_inactive_session, session_id)

            await pipe.execute()

    async def check_session_id(self, session_id):
        is_session = await self.client.sismember(self.keymap.set_active_session, session_id)
        return is_session
        


class SpeakerSide:
    def __init__(self, redis: redis, keymap: SessionKeyMap):
        self.client = redis
        self.keymap = keymap

    async def update_stream(self, key, message):
        await self.client.xadd(key, message)

    async def update_hash(self, message):
        await self.client.hset(self.keymap.hash_info, mapping=message)

    async def set_expire(self, direct=False):
        expire_seconds = 0 if direct else SESSION_EXPIRE_SECONDS
        async with self.client.pipeline(transaction=True) as pipe:
            pipe.expire(self.keymap.hash_info, expire_seconds)
            pipe.expire(self.keymap.stream_system_message, expire_seconds)
            pipe.expire(self.keymap.stream_transcription, expire_seconds)
            pipe.expire(self.keymap.stream_translation, expire_seconds)

            results = await pipe.execute()
        print("expire", results)


class ListenerSide:
    def __init__(self, redis: redis, keymap: SessionKeyMap):
        self.client = redis
        self.keymap = keymap
        self.stream_read_state = {
            keymap.stream_transcription: "0-0",
            keymap.stream_translation:  "0-0",
            keymap.stream_system_message: "0-0"
        }
        
    def set_stream_read_state(self, trscrpt_id, trslt_id):
        self.stream_read_state[self.keymap.stream_transcription] = trscrpt_id
        self.stream_read_state[self.keymap.stream_translation] = trslt_id

    async def read_snapshot(self):
        result = {}
        for key in self.stream_read_state:
            items = await self.client.xrange(key, min="-", max="+")
            if not items:
                continue

            self.stream_read_state[key] = items[-1][0]
            result[items[-1][1]["type"]] = items

        return result
    
    async def read_stream(self):
        streams = await self.client.xread(self.stream_read_state, block=1000)
        result = {}
        for stream in streams:
            key, items = stream
            self.stream_read_state[key] = items[-1][0]
            result[items[-1][1]["type"]] = items
            
        return result
    
    async def read_hash(self, field_name):
        language_group = await self.client.hget(self.keymap.hash_info, field_name)
        return language_group
