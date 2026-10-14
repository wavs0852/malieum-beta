from typing import AsyncGenerator
import redis.asyncio as redis
from ray import serve
from vllm.engine.arg_utils import AsyncEngineArgs
from vllm.engine.async_llm_engine import AsyncLLMEngine
from vllm.sampling_params import SamplingParams, BeamSearchParams
from vllm.utils import random_uuid
import yaml

@serve.deployment(
    num_replicas=1,
    max_ongoing_requests=24,
    ray_actor_options={
        "num_gpus": 0.2,
        "runtime_env": {
            "env_vars": {
                "VLLM_WORKER_MULTIPROC_METHOD": "spawn",
            },
        },
    },
)
class DeployWhisper:
    def __init__(self):
        with open('whisper_config.yaml', 'r', encoding='utf-8') as f:
            kwargs = yaml.safe_load(f)

        self.engine = AsyncLLMEngine.from_engine_args(AsyncEngineArgs(**kwargs))
        self.session_pool = {}
        self.r = redis.Redis(host='localhost', port=6380, db=0, decode_responses=True)



    def reconfigure(self, new_config):
        # 새로운 설정으로 엔진을 재구성하는 로직을 구현합니다.
        # 예를 들어, 새로운 모델로 교체하거나, GPU 메모리 활용도를 변경하는 등의 작업이 있을 수 있습니다.
        # new_args = AsyncEngineArgs(**new_config)
        # self.engine = AsyncLLMEngine.from_engine_args(new_args)
        return

    async def generate(
            self, 
            encoder_input, 
            decoder_input, 
            extra_args,
            ) -> AsyncGenerator[str, None]:

        request_id = random_uuid()
        prompt, sampling_params = self.preprocess_request(
            encoder_input, 
            decoder_input, 
            extra_args,
            )
        print(f"[DeployWhisper:generate]\nrequest_id: {request_id}\n")
        results_generator = self.engine.generate(prompt, sampling_params, request_id)

        output = None
        async for request_output in results_generator:
            output = request_output

        return output, request_id

    def preprocess_request(
        self,
        encoder_input, 
        decoder_input, 
        extra_args
        ):

        prompt = {
            "encoder_prompt": {
                "prompt": "",
                "multi_modal_data": {
                    "audio": encoder_input,
                },
            },
            "decoder_prompt": decoder_input,
        }

        sampling_params = SamplingParams(
            temperature=0,
            max_tokens=448,
            # detokenize=False,
            extra_args=extra_args
        )
        
        return prompt, sampling_params
