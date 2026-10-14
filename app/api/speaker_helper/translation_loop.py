
from api.management.message_schema import TranslationMessage

"""
speaker.stream의 translation 루프를 책임지는 비동기 핼퍼 함수

주요 기능:
 - context(SpeakerContext)의 트랜스 큐로부터 데이터, 혹은 연결 종료 메시지를 받는다.
 - translation_handle로 번역을 요청한다.
 - 번역 결과에 적절한 후처리(미구현)를 가하고 그 결과를 TranslationMessage에 담아 최종 결과를 만든다.
 - 최종 결과를 redis stream에 저장한다.

상태 관리:
 - 문장의 상태 (전사중/전사완료)를 구분한다. (현재는 GrudualWhisper에 구현되어 있다.)
 - context(SpeakerContext)를 주입받아 공유된 정보를 활용하고 새로운 정보를 공유한다.
 - SessionKeyMap과 redis_manager를 주입받아 Redis와 관련한 동작을 수행한다.
"""
async def general_translation(context, translator_handle, redis_manager, redis_keymap):
    now_language_group = []
    end_flag = False

    if len(context.language_group) < 2:
        print("[INFO] No translation_langs in transcription_loop")
        print("[INFO] Translation loop ended.")
        return

    while True:
        try:
            data = await context.trans_queue.get()
            if data is None and context.trans_queue._unfinished_tasks == 1: 
                context.trans_queue.task_done()
                break
            
            if data.status == "error": 
                raise RuntimeError(f"Transcription Error")
            
            end_flag = data.complete == "true"
            transcription_language, transcription_result = data.language, data.result
            now_language_group = [lang for lang in context.language_group if lang != transcription_language]

            result = await translator_handle.generate.remote(
                cur_lid=transcription_language,
                trans_langs=now_language_group,
                text=transcription_result,
            )
                
            context.trans_queue.task_done()

        except Exception as e:
            message = TranslationMessage(
                type="translation", 
                status="error",
                number=context.translation_message_number,
                complete="true" if end_flag else "false",
                language=", ".join(now_language_group),
                result="Translation Error"
                )
            
            print(f"[ERROR] translation_loop:while \n{e}")
            print(message)
            
        else:
            message = TranslationMessage(
                type="translation", 
                status="success",
                number=context.translation_message_number,
                complete="true" if end_flag else "false",
                language=", ".join(now_language_group),
                **result
                )
            print(message)
        finally:
            if message: await redis_manager.update_stream(redis_keymap.stream_translation, message.model_dump())
            if end_flag: context.translation_message_number += 1

            
            # print(f"[Translation] : {result}", flush=True)

    print("[INFO] Transcription loop ended.")