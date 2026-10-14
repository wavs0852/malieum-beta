import numpy as np
from custom import whisper_tokenizer
from dataclasses import dataclass, field
from constant.whisper import LANG_IDS_TO_NAMES_TOKENS


@dataclass
class TranscriptionState:
    nth: int = 1
    prompt: str = "<|startoftranscript|>"
    language_name: str | None = None
    language_token: str | None = None
    word_output: list = field(default_factory=list)
    word_index_minus_half: int = 0

class GradualWhisper:
    def __init__(self):
        self.sampling_rate = 16000
        self.audio_buffer: np.ndarray = np.zeros(self.sampling_rate * 30, dtype=np.float32)
        self.audio_buffer_ptr: int = 0
        self.tokenizer = whisper_tokenizer.get_tokenizer(multilingual=True)
        self.state = TranscriptionState()

    def add_audio_chunk(self, audio_chunk):
        self.audio_chunk_len = len(audio_chunk)

        if self.audio_chunk_len > len(self.audio_buffer):
            audio_chunk = audio_chunk[-len(self.audio_buffer):]
            self.audio_chunk_len = len(audio_chunk)

        overflow = self.audio_buffer_ptr + self.audio_chunk_len - len(self.audio_buffer)
        if overflow > 0:
            keep_size = self.audio_buffer_ptr - overflow
            if keep_size > 0:
                self.audio_buffer[:keep_size] = self.audio_buffer[overflow:self.audio_buffer_ptr]
            self.audio_buffer_ptr = max(0, keep_size)

        self.audio_buffer[self.audio_buffer_ptr:self.audio_buffer_ptr + self.audio_chunk_len] = audio_chunk
        self.audio_buffer_ptr += self.audio_chunk_len

    def get_audio(self):
        audio_with_context = self.audio_buffer[:self.audio_buffer_ptr]
        frame_size = len(audio_with_context) / self.sampling_rate * 100
        return audio_with_context, frame_size

    def afterprocessing(self, output, end):
        output_text = ""
        again = False
        try:
            # process output
            last_attention_token_index = output.custom_output.get("last-attention-token-index", None)
            if last_attention_token_index is not None:
                token_ids = [token for token in output.outputs[0].token_ids[:last_attention_token_index] if token < 50257]
            else:
                token_ids = [token for token in output.outputs[0].token_ids if token < 50257]

            attention_frames = output.custom_output.get("attention-frame-list") or []
            if len(token_ids) != len(attention_frames):
                min_len = min(len(token_ids), len(attention_frames))
                token_ids = token_ids[:min_len]
                attention_frames = attention_frames[:min_len]

            # detokenize
            self.tokenizer.language = whisper_tokenizer.TO_LANGUAGE_CODE[self.state.language_name.lower()] if self.state.language_name else None
            words, word_tokens, word_attention_frames = self.tokenizer.split_to_word_tokens(token_ids, attention_frames)
            words_len = len(words)

            # update state
            word_index_plus_half = words_len // 2
            word_index_minus_half = -(words_len - word_index_plus_half)
            
            if self.state.nth < 3: # do nothing until 3rd chunk
                lang_map = LANG_IDS_TO_NAMES_TOKENS[output.outputs[0].token_ids[0]]
                print("lang_map", lang_map)
                self.state.language_name = lang_map["name"]
                self.state.language_token = lang_map["token"]            
                self.state.word_output = words

            else:
                if words_len == 0:
                    self.state.prompt = f"<|startoftranscript|>{self.state.language_token}<|transcribe|><|notimestamps|>"
                    if end: again = True
                else:
                    frame_half_ptr = max(0, min(word_attention_frames[word_index_plus_half]) - 15)
                    audio_half_ptr = frame_half_ptr * self.sampling_rate // 50
                    audio_last_half_size = self.audio_buffer_ptr - audio_half_ptr 
                    self.audio_buffer[:audio_last_half_size] = self.audio_buffer[audio_half_ptr:self.audio_buffer_ptr] # 다시 전사할 끝부분
                    self.audio_buffer_ptr = audio_last_half_size

                    prev_coupler = self.state.word_output[self.state.word_index_minus_half:][:3]
                    curr_coupler = words[:3]

                    if self.state.nth == 3: 
                        lang_map = LANG_IDS_TO_NAMES_TOKENS[output.outputs[0].token_ids[0]]
                        self.state.language_name = lang_map["name"]
                        self.state.language_token = lang_map["token"]            
                        self.state.word_output = words
                    elif linker := next(((idx, word) for idx, word in enumerate(prev_coupler) if word in curr_coupler), None):
                        prev_end, curr_start = self.state.word_index_minus_half + linker[0], curr_coupler.index(linker[1])
                        self.state.word_output = self.state.word_output[:prev_end] + words[curr_start:]
                    else:
                        prev_end, curr_start = self.state.word_index_minus_half + 1, 1
                        self.state.word_output = self.state.word_output[:prev_end] + words[curr_start:]

                    prev_text = "".join(words[:word_index_plus_half])
                    self.state.prompt = f"<|startofprev|>{prev_text}<|startoftranscript|>{self.state.language_token}<|transcribe|><|notimestamps|>"
                    self.state.word_index_plus_half = word_index_plus_half   
                    self.state.word_index_minus_half = word_index_minus_half 
            
            self.state.nth += 1
            output_text = "".join(self.state.word_output)
            language = self.state.language_name

            if end:
                self.state = TranscriptionState()
                self.audio_buffer_ptr = 0
                
        except Exception as e:
            raise

        
        return output_text, language, again
