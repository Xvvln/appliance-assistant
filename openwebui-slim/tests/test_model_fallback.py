"""Fault-inject the provider call, exercising the installed native Router end to end."""
from copy import deepcopy
from importlib.util import find_spec
from pathlib import Path
import unittest
from unittest.mock import patch

if find_spec('litellm') is None:
    raise unittest.SkipTest('Fallback tests run in the existing jiadian-litellm environment')

import litellm
import yaml

CONFIG = Path(__file__).resolve().parents[1] / 'litellm.yaml'
TEXT = [{'role': 'user', 'content': '查询我的售后记录'}]
TOOL = {'type': 'function', 'function': {'name': 'get_after_sales',
        'description': '查询已有工单', 'parameters': {'type': 'object', 'properties': {}}}}


class ModelFallbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        config = yaml.safe_load(CONFIG.read_text())
        models = deepcopy(config['model_list'])
        for model in models:
            if 'api_key' in model['litellm_params']:
                model['litellm_params']['api_key'] = 'offline-test'
        self.router = litellm.Router(model_list=models, disable_cooldowns=True,
                                     **config['router_settings'])
        self.calls = []
        self.provider_call = litellm.acompletion
        self.deepseek_fails = True
        self.glm_fails = False
        self.all_fail = False

    async def provider(self, **kwargs):
        self.calls.append(kwargs)
        model = kwargs['model']
        if (self.all_fail or (self.deepseek_fails and 'neice-deepseek-v4' in model)
                or (self.glm_fails and 'GLM-5.2-trial' in model)):
            raise litellm.ServiceUnavailableError('Injected upstream HTTP 503',
                                                  llm_provider='openai', model=model)
        if kwargs.get('stream'):
            return await self.provider_call(**kwargs, mock_response='GLM fallback OK')
        return litellm.ModelResponse(model=model, choices=[{'index': 0,
            'finish_reason': 'tool_calls', 'message': {'role': 'assistant', 'content': None,
            'tool_calls': [{'id': 'read-only-call', 'type': 'function',
                           'function': {'name': 'get_after_sales', 'arguments': '{}'}}]}}])

    async def test_auto_503_keeps_tool_history_and_schema(self):
        messages = TEXT + [
            {'role': 'assistant', 'content': None, 'tool_calls': [
                {'id': 'previous', 'type': 'function',
                 'function': {'name': 'get_demo_orders', 'arguments': '{}'}}]},
            {'role': 'tool', 'tool_call_id': 'previous', 'content': '{"orders":[]}'}]
        with patch('litellm.acompletion', side_effect=self.provider):
            result = await self.router.acompletion(model='jiadian-auto', messages=messages,
                                                   tools=[TOOL], tool_choice='auto')
        self.assertEqual([c['model'] for c in self.calls],
                         ['openai/neice-deepseek-v4', 'openai/GLM-5.2-trial'])
        self.assertEqual(self.calls[-1]['messages'], messages)
        self.assertEqual(self.calls[-1]['tools'], [TOOL])
        self.assertEqual(self.calls[-1]['reasoning_effort'], 'medium')
        self.assertEqual(result.choices[0].message.tool_calls[0].function.name, 'get_after_sales')

    async def test_direct_deepseek_also_falls_back(self):
        with patch('litellm.acompletion', side_effect=self.provider):
            result = await self.router.acompletion(model='deepseek-text', messages=TEXT)
        self.assertIn('GLM-5.2', result.model)
        self.assertEqual(len(self.calls), 2)

    async def test_streaming_503_before_output_falls_back(self):
        with patch('litellm.acompletion', side_effect=self.provider):
            stream = await self.router.acompletion(model='jiadian-auto', messages=TEXT, stream=True)
            chunks = [chunk async for chunk in stream]
        content = ''.join(c.choices[0].delta.content or '' for c in chunks if c.choices)
        self.assertEqual(content, 'GLM fallback OK')
        self.assertEqual(len(self.calls), 2)

    async def test_healthy_deepseek_does_not_call_glm(self):
        self.deepseek_fails = False
        with patch('litellm.acompletion', side_effect=self.provider):
            await self.router.acompletion(model='jiadian-auto', messages=TEXT)
        self.assertEqual([c['model'] for c in self.calls], ['openai/neice-deepseek-v4'])

    async def test_both_text_models_fail_then_gemini_keeps_tools(self):
        self.glm_fails = True
        with patch('litellm.acompletion', side_effect=self.provider):
            result = await self.router.acompletion(model='jiadian-auto', messages=TEXT,
                                                   tools=[TOOL], tool_choice='auto')
        self.assertEqual([c['model'] for c in self.calls],
                         ['openai/neice-deepseek-v4', 'openai/GLM-5.2-trial',
                          'gemini/gemini-3.8-flash'])
        self.assertEqual(self.calls[-1]['messages'], TEXT)
        self.assertEqual(self.calls[-1]['tools'], [TOOL])
        self.assertEqual(self.calls[-1]['reasoning_effort'], 'medium')
        self.assertEqual(result.choices[0].message.tool_calls[0].function.name, 'get_after_sales')

    async def test_all_fail_stops_after_two_fallbacks(self):
        self.all_fail = True
        with patch('litellm.acompletion', side_effect=self.provider):
            with self.assertRaises(litellm.ServiceUnavailableError):
                await self.router.acompletion(model='jiadian-auto', messages=TEXT)
        self.assertEqual([c['model'] for c in self.calls],
                         ['openai/neice-deepseek-v4', 'openai/GLM-5.2-trial',
                          'gemini/gemini-3.8-flash'])

    async def test_image_failure_does_not_fall_back_to_text_model(self):
        self.all_fail = True
        messages = [{'role': 'user', 'content': [
            {'type': 'text', 'text': '看看铭牌'},
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AAAA'}}]}]
        with patch('litellm.acompletion', side_effect=self.provider):
            with self.assertRaises(litellm.ServiceUnavailableError):
                await self.router.acompletion(model='jiadian-auto', messages=messages)
        self.assertEqual([c['model'] for c in self.calls], ['gemini/gemini-3.8-flash'])


if __name__ == '__main__':
    unittest.main()
