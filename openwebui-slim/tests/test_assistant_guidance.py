"""Guide progress follows user feedback and only the selected model's manual."""
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

import httpx
from fastapi import FastAPI, HTTPException, Request

import test_after_sales as fixture


ROOT = Path(__file__).resolve().parents[1]
QUOTE = '本机支持自动投放。面板的“自动投放”选项控制液体洗涤剂投放，不代表所有耗材都会自动投放。'
IMAGE = 'data:image/png;base64,aW1hZ2U='


class GuidanceTests(unittest.IsolatedAsyncioTestCase):
    tearDown = fixture.AfterSalesTests.tearDown
    confirm = fixture.AfterSalesTests.confirm

    def setUp(self):
        fixture.AfterSalesTests.setUp(self)
        package = ModuleType('guidance_test_features')
        package.__path__ = [str(ROOT / 'features')]
        auth = ModuleType('open_webui.utils.auth')

        async def verified_user(request: Request):
            token = request.headers.get('authorization', '')
            if token not in ('Bearer test-user', 'Bearer other'):
                raise HTTPException(401, 'Authentication required')
            return SimpleNamespace(id=token.removeprefix('Bearer '))

        auth.get_verified_user = verified_user
        stubs = {'guidance_test_features': package, 'open_webui.utils.auth': auth,
                 'tools.demo_shop': fixture.module}
        with patch.dict(sys.modules, stubs):
            common_spec = importlib.util.spec_from_file_location('guidance_test_features.common', ROOT / 'features/common.py')
            self.common = importlib.util.module_from_spec(common_spec)
            sys.modules['guidance_test_features.common'] = self.common
            common_spec.loader.exec_module(self.common)
            self.common.STATE_DB = Path(self.temp.name) / 'assistant.sqlite3'
            guide_spec = importlib.util.spec_from_file_location('guidance_test_features.guidance', ROOT / 'features/guidance.py')
            self.guide = importlib.util.module_from_spec(guide_spec)
            guide_spec.loader.exec_module(self.guide)
        self.guide.get_shop = lambda: self.tools
        self.calls = []
        self.answers = []

        async def model_json(system, user_text, images=None):
            self.calls.append({'system': system, 'context': json.loads(user_text), 'images': images})
            return self.answers.pop(0) if self.answers else self.step()

        self.guide.model_json = model_json
        app = FastAPI()
        app.include_router(self.guide.router, prefix='/api/v1/jiadian')
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://guidance.test')

    async def asyncTearDown(self):
        await self.client.aclose()

    def step(self, **changes):
        return {'observation': '依据你描述的需求，先查看机器上的投放标识。', 'title': '确认洗涤剂仓标识',
                'instruction': '请查看可触及的洗涤剂仓标识，告诉我是否写有液体洗涤剂或自动投放。',
                'verification': '确认看见标识后再继续，找不到时可以补拍局部照片。',
                'quote': QUOTE, 'needs_service': False} | changes

    async def start(self, **body):
        return await self.client.post('/api/v1/jiadian/assistant/guidance',
            headers={'Authorization': 'Bearer test-user'},
            json={'model': 'JG-F10', 'task': '第一次使用自动投放'} | body)

    async def reply(self, session_id, action='completed', **body):
        return await self.client.post(f'/api/v1/jiadian/assistant/guidance/{session_id}/step',
            headers={'Authorization': 'Bearer test-user'}, json={'action': action} | body)

    async def test_exact_manual_and_image_reach_model_without_guessing_model(self):
        result = await self.start(images=[IMAGE])
        self.assertEqual(result.status_code, 200)
        state = result.json()
        self.assertEqual(state['model'], 'JG-F10')
        self.assertEqual(state['current_step']['quote'], QUOTE)
        self.assertEqual(self.calls[0]['images'], [IMAGE])
        self.assertIn('JG-F10· 洗涤剂与柔顺剂', self.calls[0]['context']['manual'])
        self.assertEqual(self.calls[0]['context']['selected_model'], 'JG-F10')
        self.assertNotIn('images', state)

    async def test_every_feedback_generates_dynamic_next_step_and_keeps_progress(self):
        first = (await self.start()).json()
        for action, feedback, title in [
            ('not_found', '只看到一个 MAX 标识', '请补拍投放仓附近'),
            ('different', '这里写的是柔顺剂', '先不要添加洗衣液'),
            ('message', '自动投放开关在哪里', '核对面板自动投放选项'),
            ('completed', '看到了，已经确认液体洗涤剂仓', '检查洗衣液适用范围'),
        ]:
            self.answers.append(self.step(title=title))
            response = await self.reply(first['id'], action, feedback=feedback, images=[IMAGE])
            self.assertEqual(response.status_code, 200)
            state = response.json()
            self.assertEqual(state['current_step']['title'], title)
            self.assertEqual(state['history'][-1]['action'], action)
            self.assertEqual(state['history'][-1]['feedback'], feedback)
            self.assertEqual(self.calls[-1]['context']['history'][-1]['feedback'], feedback)
            self.assertEqual(state['status'], 'active')
        stored = self.common.load_session('test-user', 'guidance', first['id'])
        self.assertEqual(len(stored['history']), 4)
        self.assertEqual(stored['history'][0]['step'], first['current_step'])

    async def test_model_cannot_mark_goal_complete_but_user_can(self):
        self.answers.append(self.step(completed=True, status='completed'))
        state = (await self.start()).json()
        self.assertEqual(state['status'], 'active')
        response = await self.reply(state['id'], 'resolved', feedback='现在会使用自动投放了')
        self.assertEqual(response.status_code, 200)
        done = response.json()
        self.assertEqual(done['status'], 'completed')
        self.assertTrue(done['completed_by_user'])
        self.assertEqual(done['history'][-1]['action'], 'resolved')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual((await self.reply(state['id'])).status_code, 409)

    async def test_sessions_restore_and_are_owner_scoped(self):
        state = (await self.start()).json()
        endpoint = '/api/v1/jiadian/assistant/guidance'
        self.assertEqual((await self.client.get(endpoint)).status_code, 401)
        own = await self.client.get(endpoint + '/' + state['id'], headers={'Authorization': 'Bearer test-user'})
        self.assertEqual(own.json(), state)
        other = await self.client.get(endpoint, headers={'Authorization': 'Bearer other'})
        self.assertEqual(other.json()['sessions'], [])
        self.assertEqual((await self.client.get(endpoint + '/' + state['id'],
            headers={'Authorization': 'Bearer other'})).status_code, 404)
        self.assertEqual((await self.client.post(endpoint + '/' + state['id'] + '/step',
            headers={'Authorization': 'Bearer other'}, json={'action': 'resolved'})).status_code, 404)
        self.assertEqual(self.common.load_session('test-user', 'guidance', state['id']), state)

    async def test_unknown_models_and_mismatched_or_foreign_orders_are_rejected(self):
        self.assertEqual((await self.start(model='../other')).status_code, 422)
        order = (await self.tools.place_demo_order(**(self.args | {'model': 'JG-F10'}),
                                                 __event_call__=self.confirm))['order']
        self.assertEqual((await self.start(model='JG-F8', order_id=order['order_id'])).status_code, 422)
        with self.tools._db() as db:
            db.execute('UPDATE orders SET user_id=? WHERE id=?', ('other', order['order_id']))
        self.assertEqual((await self.start(order_id=order['order_id'])).status_code, 422)
        self.assertEqual(self.calls, [])

    async def test_owned_order_keeps_its_explicit_binding(self):
        order = (await self.tools.place_demo_order(**(self.args | {'model': 'JG-F10'}),
                                                 __event_call__=self.confirm))['order']
        response = await self.start(order_id=order['order_id'])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['order_id'], order['order_id'])

    async def test_invalid_quote_or_failed_model_does_not_advance_saved_step(self):
        state = (await self.start()).json()
        self.answers.append(self.step(quote='本型号长按不存在的按键十秒即可修好。'))
        response = await self.reply(state['id'], feedback='我做完了')
        self.assertEqual(response.status_code, 502)
        self.assertEqual(self.common.load_session('test-user', 'guidance', state['id']), state)
        self.answers.append({'title': '缺少其余字段'})
        self.assertEqual((await self.reply(state['id'])).status_code, 502)
        self.assertEqual(self.common.load_session('test-user', 'guidance', state['id']), state)

    async def test_internal_repair_instruction_is_not_returned(self):
        self.answers.append(self.step(instruction='请拆开后盖检查内部电路。'))
        self.assertEqual((await self.start(task='怎么拆机维修')).status_code, 502)
        self.assertEqual(self.common.list_sessions('test-user', 'guidance'), [])

    async def test_empty_message_and_invalid_image_do_not_call_model(self):
        self.assertEqual((await self.start(images=['https://untrusted.invalid/image.png'])).status_code, 422)
        self.assertEqual((await self.start(task='  ')).status_code, 422)
        state = (await self.start()).json()
        self.assertEqual((await self.reply(state['id'], 'message')).status_code, 422)
        self.assertEqual(len(self.calls), 1)


if __name__ == '__main__':
    unittest.main()
