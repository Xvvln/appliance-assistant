"""Exercise the installed LiteLLM router without making upstream API requests.

Run with the jiadian-litellm interpreter (business tests use jiadian-webui).
"""
from copy import deepcopy
from pathlib import Path
import unittest
from importlib.util import find_spec

if find_spec('litellm') is None:
    raise unittest.SkipTest('Routing tests run in the existing jiadian-litellm environment')

import yaml
from litellm import Router
from litellm.router_strategy.complexity_router import ComplexityRouter


class ModelRoutingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        config = yaml.safe_load((Path(__file__).resolve().parents[1] / 'litellm.yaml').read_text())
        self.models = config['model_list']
        deployments = deepcopy(self.models)
        for model in deployments:
            if 'api_key' in model['litellm_params']:
                model['litellm_params']['api_key'] = 'offline-test'
        native = Router(model_list=deployments)
        params = deployments[0]['litellm_params']
        self.router = ComplexityRouter('jiadian-auto', native,
                                       params['complexity_router_config'],
                                       params['complexity_router_default_model'])

    async def route(self, messages):
        result = await self.router.async_pre_routing_hook('jiadian-auto', {}, messages=messages)
        return result.model

    async def test_text_and_tool_continuation_use_deepseek(self):
        messages = [{'role': 'user', 'content': '查我的订单并比较洗衣机规格'}]
        self.assertEqual(await self.route(messages), 'deepseek-text')
        messages += [{'role': 'assistant', 'content': None, 'tool_calls': [
            {'id': 'test', 'type': 'function', 'function': {'name': 'get_demo_orders', 'arguments': '{}'}}]},
            {'role': 'tool', 'tool_call_id': 'test', 'content': '{"orders":[]}'}]
        self.assertEqual(await self.route(messages), 'deepseek-text')

    async def test_image_and_followup_keep_gemini(self):
        messages = [{'role': 'user', 'content': [
            {'type': 'text', 'text': '这是什么洗衣机？'},
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AAAA'}}]}]
        self.assertEqual(await self.route(messages), 'gemini-3.8-flash')
        messages += [{'role': 'assistant', 'content': '这是滚筒洗衣机'},
                     {'role': 'user', 'content': '再看一下门的颜色'}]
        self.assertEqual(await self.route(messages), 'gemini-3.8-flash')

    async def test_no_low_effort_or_remote_classifier(self):
        for model in self.models:
            if model['model_name'] in ('deepseek-text', 'glm-text', 'gemini-3.8-flash'):
                self.assertEqual(model['litellm_params']['reasoning_effort'], 'medium')
        self.assertEqual(self.router.config.classifier_type, 'heuristic')
        self.assertFalse(self.router.config.session_affinity)


if __name__ == '__main__':
    unittest.main()
