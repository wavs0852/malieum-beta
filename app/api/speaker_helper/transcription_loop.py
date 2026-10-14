from api.management.message_schema import TranscriptionMessage
import numpy as np
from constant.whisper import LANG_NAMES_TO_IDS
from dataclasses import dataclass, field
from custom.gradual_whisper import GradualWhisper

"""
speaker.stream의 transcription 루프를 책임지는 비동기 핼퍼 함수

주요 기능:
 - context(SpeakerContext)의 오디오 큐로부터 데이터, 혹은 연결 종료 메시지를 받는다.
 - 데이터에 적절한 전처리를 가하고 transcription_handle로 전사를 요청한다.
 - 전사 결과에 적절한 후처리를 가하고 그 결과를 TranscriptionMessage에 담아 최종 결과를 만든다.
 - 최종 결과를 redis stream에 저장하고, 동시에 트랜스 큐에도 삽입하여 번역 요청을 보낸다.

상태 관리:
 - GradualWhisper를 정의하고 Whisper의 실시간 동작 상태를 핸들링한다. 
 - 문장의 상태 (전사중/전사완료)를 구분한다. (현재는 GrudualWhisper에 구현되어 있다.)
 - context(SpeakerContext)를 주입받아 공유된 정보를 활용하고 새로운 정보를 공유한다. 
 - SessionKeyMap과 redis_manager를 주입받아 Redis와 관련한 동작을 수행한다.
"""

# NOTE: 모델을 Whisper에서 Qwen3ASR로 변경할 경우 기존의 Whisper 로직은 필요 없어지게 되므로
      # GradualWhisper를 포함한 기존 코드를 일정 부분 변경해야 한다.
      # 이때 기존의 동작을 훼손하지 않고 모델만 안전하게 교체될 수 있도록 매우 유의해야 한다.


async def whisper_transcription(context, transcription_handle, redis_manager, redis_keymap): 
    custom_whisper = GradualWhisper()
    allowed_language_tokens = [LANG_NAMES_TO_IDS[lang] for lang in context.language_group]

    while True:
        message = None
        data = None
        stop_loop = False
        audio_task_done = False
        end_flag = False
        again = True
        
        try:
            data = await context.audio_queue.get()
            if data is None:
                context.audio_queue.task_done()
                audio_task_done = True
                stop_loop = True
                continue
            
            end_flag = data[0] == 1
            audio_chunk = np.frombuffer(data, dtype=np.float32, offset=1) 

            if len(audio_chunk) > 1:
                custom_whisper.add_audio_chunk(audio_chunk=audio_chunk)
                audio_with_context, frame_size = custom_whisper.get_audio()
                
                output, request_id = await transcription_handle.generate.remote(
                    encoder_input=audio_with_context,
                    decoder_input=custom_whisper.state.prompt, 
                    extra_args={
                        "audio-frame-size": frame_size, 
                        "allowed-languages": allowed_language_tokens,
                        "end": end_flag
                    },
                )

                transcription, language, again = custom_whisper.afterprocessing(output, end=end_flag)
                if again:
                    output, request_id = await transcription_handle.generate.remote(
                        encoder_input=audio_with_context,
                        decoder_input=custom_whisper.state.prompt, 
                        extra_args={
                            "audio-frame-size": frame_size, 
                            "allowed-languages": allowed_language_tokens,
                            "end": end_flag
                        },
                    )
                
            context.audio_queue.task_done()
            audio_task_done = True
        
        except Exception as e:
            message = TranscriptionMessage(
                type="transcription", 
                status="error",
                number=context.transcription_message_number, 
                complete="true" if end_flag else "false",
                language=language if language else "",
                result="Transcription Error",
                )
            print(f"[WARN] Unexpected error occured at transcription_loop: {e}")


        else:
            message = TranscriptionMessage(
                type="transcription", 
                status="success",
                number=context.transcription_message_number, 
                complete="true" if end_flag else "false",
                language=language if language else "",
                result=transcription,
                )
            
        finally:
            print(message)
            if data is not None and not audio_task_done:
                context.audio_queue.task_done()

            if message is not None:
                await redis_manager.update_stream(redis_keymap.stream_transcription, message.model_dump())
                if end_flag: 
                    await context.trans_queue.put(message)
                    context.transcription_message_number += 1
                elif custom_whisper.state.nth > 3 and custom_whisper.state.nth % 2 == 0:
                    print("give data when not finished")
                    await context.trans_queue.put(message)

            if stop_loop:
                break
        

    print("[INFO] Transcription loop ended.")
    await context.trans_queue.put(None)
