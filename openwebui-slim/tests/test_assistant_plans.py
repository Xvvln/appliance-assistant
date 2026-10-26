"""Budget combinations stay grounded in catalog data and preserve explicit constraints."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException, Request
import httpx

import test_demo_shop as fixture


class AssistantPlanTests(unittest.IsolatedAsyncioTestCase):
    tearDown = fixture.DemoShopTests.tearDown

    def setUp(self):
        fixture.DemoShopTests.setUp(self)
        shutil.copyfile(fixture.ROOT / 'product-catalog.json', Path(self.temp.name) / 'product-catalog.json')
        package_name = 'assistant_plans_fixture'
        package = ModuleType(package_name)
        package.__path__ = [str(fixture.ROOT / 'features')]
        auth = ModuleType('open_webui.utils.auth')

        async def verified_user(request: Request):
            header = request.headers.get('authorization', '')
            if header not in ('Bearer alice', 'Bearer bob'):
                raise HTTPException(401, 'Sign in required')
            return SimpleNamespace(id=header.removeprefix('Bearer '))

        auth.get_verified_user = verified_user
        self.common = self._module(package_name + '.common', fixture.ROOT / 'features/common.py')
        self.plans = self._module(package_name + '.plans', fixture.ROOT / 'features/plans.py')
        with patch.dict(sys.modules, {package_name: package,
                package_name + '.common': self.common, 'open_webui.utils.auth': auth,
                'tools.demo_shop': fixture.module}):
            self.common.__spec__.loader.exec_module(self.common)
            self.plans.__spec__.loader.exec_module(self.plans)
        self.common.STATE_DB = Path(self.temp.name) / 'plans.sqlite3'
        self.plans.get_shop = lambda: self.tools
        self.parse_reply = {'patch': {}, 'clarification': ''}
        self.rank_reply = None
        self.fail_parse = False
        self.fail_explanation = False
        self.parse_inputs = []
        self.plans.model_json = self.model
        app = FastAPI()
        app.include_router(self.plans.router, prefix='/api/v1/jiadian')
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://plans.test')

    @staticmethod
    def _module(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        return importlib.util.module_from_spec(spec)

    async def asyncTearDown(self):
        await self.client.aclose()

    async def model(self, system, user_text, images=None):
        if system.startswith('你只负责'):
            self.parse_inputs.append(json.loads(user_text))
            if self.fail_parse:
                raise HTTPException(503, 'Upstream busy')
            return self.parse_reply
        if self.fail_explanation:
            raise HTTPException(503, 'Upstream busy')
        if self.rank_reply is not None:
            return self.rank_reply
        candidates = json.loads(user_text)['组合']
        return {'choices': [{'id': item['id'], 'reason': '在容量与预算之间保留不同选择。'} for item in candidates[:3]]}

    async def post(self, body, user='alice'):
        return await self.client.post('/api/v1/jiadian/assistant/plans', json=body,
                                      headers={'Authorization': f'Bearer {user}'})

    async def create(self, constraints=None):
        response = await self.post({'constraints': constraints or {'budget_yuan': 8000}})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def test_combinations_use_actual_prices_stock_and_each_selected_category(self):
        state = await self.create({'budget_yuan': 10000, 'requirements': {
            '洗衣机': {'requires_drying': True}, '冰箱': {'min_volume_l': 300},
            '空调': {'horsepower': 1.5}}})
        self.assertTrue(state['plans'])
        for plan in state['plans']:
            self.assertEqual({p['category'] for p in plan['products']}, {'洗衣机', '空调', '冰箱'})
            self.assertEqual(plan['total_yuan'], sum(p['price_yuan'] for p in plan['products']))
            self.assertLessEqual(plan['total_yuan'], 10000)
            self.assertTrue(all(p['stock'] > 0 for p in plan['products']))
            self.assertGreater(next(p for p in plan['products'] if p['category'] == '洗衣机')['dry_kg'], 0)
        self.assertFalse((await self.tools.get_demo_orders(__user__={'id': 'alice'}))['orders'])

    async def test_budget_shortfall_does_not_silently_relax_drying_or_volume(self):
        state = await self.create({'budget_yuan': 7000, 'requirements': {
            '洗衣机': {'requires_drying': True}, '冰箱': {'min_volume_l': 300}, '空调': {'horsepower': 1.5}}})
        self.assertEqual(state['plans'], [])
        self.assertEqual(state['no_solution'], {'minimum_total_yuan': 8697.0, 'shortfall_yuan': 1697.0})
        self.assertTrue(state['constraints']['requirements']['洗衣机']['requires_drying'])

    async def test_natural_horsepower_unit_is_accepted_and_form_budget_is_in_context(self):
        self.parse_reply = {'patch': {'requirements': {
            '洗衣机': {'requires_drying': True, 'min_capacity_kg': 10},
            '空调': {'horsepower': '1.5匹'}, '冰箱': {'min_volume_l': 300}}}, 'clarification': ''}
        response = await self.post({'message': '洗衣机要洗烘一体，至少10公斤；空调要1.5匹；冰箱至少300升。',
                                    'constraints': {'budget_yuan': 10000}})
        self.assertEqual(response.status_code, 200, response.text)
        state = response.json()
        self.assertEqual(state['constraints']['requirements']['空调']['horsepower'], 1.5)
        self.assertEqual(self.parse_inputs[0]['已有条件']['budget_yuan'], 10000)
        self.assertEqual(self.parse_inputs[0]['patch_schema']['additionalProperties'], False)
        self.assertIn('horsepower', self.parse_inputs[0]['patch_schema']['$defs']['Requirements']['properties'])
        self.assertTrue(state['plans'])
        self.assertTrue(all(any(p['model'] == 'JG-AC35' for p in plan['products']) for plan in state['plans']))

    async def test_invalid_constraint_shape_logs_exact_location_without_saving(self):
        self.parse_reply = {'patch': {'requirements': {'空调': {'capacity': '1.5匹'}}}, 'clarification': ''}
        with self.assertLogs(self.plans.logger, level='WARNING') as captured:
            response = await self.post({'message': '空调要1.5匹', 'constraints': {'budget_yuan': 10000}})
        self.assertEqual(response.status_code, 422)
        message = ' '.join(captured.output)
        self.assertIn('plan_constraints_validation_failed', message)
        self.assertIn('capacity', message)
        self.assertIn('extra_forbidden', message)
        self.assertEqual(self.common.list_sessions('alice', 'plans'), [])

    async def test_installation_depth_is_not_machine_depth(self):
        state = await self.create({'budget_yuan': 10000, 'categories': ['洗衣机'],
            'requirements': {'洗衣机': {'requires_drying': True, 'max_installation_depth_mm': 650}}})
        models = {p['model'] for plan in state['plans'] for p in plan['products']}
        self.assertIn('JG-WD10', models)
        self.assertNotIn('JG-WD12', models)  # Body 600 mm, required installation depth 660 mm.
        self.assertTrue(all(p['installation_mm'][2] <= 650 for plan in state['plans'] for p in plan['products']))

    async def test_natural_language_change_preserves_other_constraints_and_shows_difference(self):
        original = await self.create({'budget_yuan': 10000, 'categories': ['洗衣机', '冰箱'],
            'requirements': {'洗衣机': {'requires_drying': True, 'max_installation_depth_mm': 650}}})
        self.parse_reply = {'patch': {'budget_yuan': 8000}, 'clarification': ''}
        response = await self.post({'session_id': original['id'], 'message': '预算改成8000，其他不变'})
        updated = response.json()
        self.assertEqual(updated['id'], original['id'])
        self.assertEqual(updated['created_at'], original['created_at'])
        self.assertEqual(updated['constraints']['requirements'], original['constraints']['requirements'])
        self.assertEqual(updated['constraints']['categories'], ['洗衣机', '冰箱'])
        self.assertTrue(any('8000' in item for item in updated['differences']))
        self.assertEqual(self.common.load_session('alice', 'plans', original['id']), updated)

    async def test_locked_model_is_kept_and_out_of_stock_is_not_replaced(self):
        state = await self.create({'budget_yuan': 15000, 'locked_models': {'冰箱': 'JG-R549'}})
        self.assertTrue(all(any(p['model'] == 'JG-R549' for p in plan['products']) for plan in state['plans']))
        with self.tools._db() as db:
            db.execute('UPDATE products SET stock=0 WHERE model=?', ('JG-R549',))
        response = await self.post({'session_id': state['id'], 'constraints': {}})
        changed = response.json()
        self.assertEqual(changed['plans'], [])
        self.assertIn('暂时缺货', ' '.join(changed['problems']))
        self.assertEqual(changed['constraints']['locked_models']['冰箱'], 'JG-R549')

    async def test_room_area_does_not_invent_a_match_or_block_other_planning(self):
        state = await self.create({'budget_yuan': 10000, 'requirements': {'空调': {'room_area_m2': 20}}})
        self.assertTrue(state['plans'])
        self.assertNotIn('horsepower', state['constraints']['requirements']['空调'])
        self.assertIn('不能仅凭面积', state['clarification'])
        self.assertTrue(any('尚未确认' in note for note in state['notes']))

    async def test_model_cannot_invent_combinations_or_prices(self):
        self.rank_reply = {'choices': [{'id': 'INVENTED', 'reason': '优惠只要1元'},
            {'id': 'JG-F8|JG-AC26|JG-R218', 'reason': '价格只有1元，型号JG-FAKE'}]}
        state = await self.create()
        self.assertTrue(state['plans'])
        for plan in state['plans']:
            self.assertNotIn('INVENTED', plan['id'])
            self.assertEqual(plan['total_yuan'], sum(p['price_yuan'] for p in plan['products']))
            self.assertNotIn('1元', plan['reason'])
            self.assertNotIn('FAKE', plan['reason'])

    async def test_explanation_failure_keeps_feasible_options_and_parse_failure_keeps_saved_state(self):
        self.fail_explanation = True
        state = await self.create()
        self.assertTrue(state['plans'])
        self.fail_parse = True
        response = await self.post({'session_id': state['id'], 'message': '预算少一点'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.common.load_session('alice', 'plans', state['id']), state)

    async def test_saved_plans_are_owner_scoped_and_require_sign_in(self):
        state = await self.create()
        path = '/api/v1/jiadian/assistant/plans'
        self.assertEqual((await self.client.get(path)).status_code, 401)
        own = await self.client.get(path, headers={'Authorization': 'Bearer alice'})
        self.assertEqual(own.json()['sessions'][0]['id'], state['id'])
        other = await self.client.get(path, headers={'Authorization': 'Bearer bob'})
        self.assertEqual(other.json()['sessions'], [])
        self.assertEqual((await self.client.get(path + '/' + state['id'], headers={'Authorization': 'Bearer bob'})).status_code, 404)
        self.assertEqual((await self.post({'session_id': state['id'], 'constraints': {'budget_yuan': 20000}}, 'bob')).status_code, 404)


if __name__ == '__main__':
    unittest.main()
