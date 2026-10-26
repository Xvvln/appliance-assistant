"""Schedule suggestions preserve explicit exceptions and never write commerce records."""
import copy
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI, HTTPException, Request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from features import common


async def verified_user(request: Request):
    token = request.headers.get('authorization', '')
    if token not in ('Bearer owner', 'Bearer other'):
        raise HTTPException(401, 'Authentication required')
    return SimpleNamespace(id=token.removeprefix('Bearer '))


auth = ModuleType('open_webui.utils.auth')
auth.get_verified_user = verified_user
spec = importlib.util.spec_from_file_location('features.changes_under_test', ROOT / 'features/changes.py')
changes = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {'open_webui.utils.auth': auth}):
    spec.loader.exec_module(changes)

DATES = ['2026-10-24', '2026-10-25', '2026-10-26']


def record(id='ORDER-WASH', model='JG-F10', category='洗衣机', editable=True):
    return {'id': id, 'kind': 'orders', 'model': model, 'name': model, 'category': category,
            'status': '已确认，待配送' if editable else '已取消', 'editable': editable,
            'date': DATES[0], 'slot': '09:00-12:00', 'service': '送装一体'}


def suggestion(item, date=DATES[1]):
    return {'kind': item['kind'], 'id': item['id'], 'decision': 'change',
            'proposed': {'date': date, 'slot': '14:00-18:00'}, 'reason': '按要求推迟'}


class ChangesTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp_root = ROOT.parent / '临时文件'
        temp_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.addCleanup(self.temp.cleanup)
        self.dbpath = Path(self.temp.name) / 'commerce.sqlite3'
        self.state_patch = patch.object(common, 'STATE_DB', Path(self.temp.name) / 'assistant.sqlite3')
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)
        self.current = [record(), record('ORDER-AC', 'JG-AC35', '空调')]
        self.shop = SimpleNamespace(_schedule=lambda: DATES, _db=self.db,
                                   _product_catalog=lambda: [
                                       {'model': r['model'], 'category': r['category'], 'name': r['name']}
                                       for r in self.current])
        with self.db() as db:
            db.execute('CREATE TABLE orders(id TEXT, user_id TEXT, created_at TEXT, payload TEXT)')
            db.execute('CREATE TABLE service_tickets(id TEXT, user_id TEXT, created_at TEXT, payload TEXT)')
            for item in self.current:
                payload = {'order_id': item['id'], 'model': item['model'], 'status': item['status'],
                           'delivery_date': item['date'], 'delivery_slot': item['slot'],
                           'service': item['service'], 'recipient': '不发送给模型的收货人'}
                db.execute('INSERT INTO orders VALUES(?,?,?,?)',
                           (item['id'], 'owner', DATES[0], json.dumps(payload)))
            db.execute('INSERT INTO orders SELECT ?,?,?,payload FROM orders LIMIT 1',
                       ('FOREIGN', 'other', DATES[0]))
        self.shop_patch = patch.object(changes, 'get_shop', return_value=self.shop)
        self.shop_patch.start()
        self.addCleanup(self.shop_patch.stop)
        app = FastAPI()
        app.include_router(changes.router, prefix='/api/v1/jiadian')
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test')

    def db(self):
        db = sqlite3.connect(self.dbpath)
        db.row_factory = sqlite3.Row
        return db

    async def asyncTearDown(self):
        await self.client.aclose()

    def test_explicit_unchanged_air_conditioner_overrides_broad_generated_changes(self):
        raw = {'items': [suggestion(item) for item in self.current]}
        plan = changes.normalize_plan(raw, self.current, DATES, '配送推迟，但空调安装不变')
        self.assertEqual([i['decision'] for i in plan['items']], ['change', 'keep'])
        self.assertEqual(plan['items'][1]['proposed']['date'], DATES[0])

    def test_closed_records_unknown_ids_and_unavailable_dates_cannot_be_applied(self):
        closed = record('CLOSED', editable=False)
        raw = {'items': [suggestion(self.current[0], '2027-01-01'), suggestion(closed),
                         suggestion(record('UNKNOWN'))]}
        plan = changes.normalize_plan(raw, [self.current[0], closed], DATES, '配送延期')
        self.assertEqual([i['decision'] for i in plan['items']], ['clarify', 'keep'])
        self.assertEqual(len(plan['items']), 2)
        self.assertTrue(plan['questions'])

    def test_compact_model_output_preserves_omitted_records(self):
        closed = record('CLOSED', editable=False)
        records = self.current + [closed]
        raw = {'items': [suggestion(records[0])], 'keep_ids': ['ORDER-AC']}
        plan = changes.normalize_plan(raw, records, DATES, '洗衣机配送推迟一天')
        self.assertEqual([item['id'] for item in plan['items']], [r['id'] for r in records])
        self.assertEqual([item['decision'] for item in plan['items']], ['change', 'keep', 'keep'])
        for item in plan['items'][1:]:
            self.assertEqual(item['proposed'], {'date': item['before']['date'], 'slot': item['before']['slot']})
            self.assertEqual(item['outcome'], '未变更')

    async def test_owner_scoped_inputs_and_missing_auth(self):
        response = await self.client.get('/api/v1/jiadian/assistant/changes/records',
                                         headers={'Authorization': 'Bearer owner'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['records']), 2)
        self.assertNotIn('recipient', json.dumps(response.json()))
        self.assertEqual((await self.client.get('/api/v1/jiadian/assistant/changes/records')).status_code, 401)

    async def make_plan(self):
        raw = {'summary': '只调整洗衣机', 'items': [suggestion(self.current[0])],
               'keep_ids': ['ORDER-AC']}
        with patch.object(changes, 'model_json', new=AsyncMock(return_value=raw)) as model:
            response = await self.client.post('/api/v1/jiadian/assistant/changes/plan',
                headers={'Authorization': 'Bearer owner'}, json={'message': '洗衣机延期，空调不变'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('送装一体', model.call_args.args[0])
        self.assertNotIn('recipient', model.call_args.args[1])
        return response.json()

    async def test_planning_saves_only_suggestion_and_session_is_private(self):
        before = changes.read_records(self.shop, 'owner')
        plan = await self.make_plan()
        self.assertEqual(changes.read_records(self.shop, 'owner'), before)
        foreign = await self.client.get('/api/v1/jiadian/assistant/changes/sessions/' + plan['id'],
                                       headers={'Authorization': 'Bearer other'})
        self.assertEqual(foreign.status_code, 404)

    async def test_dismissing_suggestion_does_not_cancel_real_records(self):
        plan = await self.make_plan()
        before = changes.read_records(self.shop, 'owner')
        response = await self.client.post('/api/v1/jiadian/assistant/changes/sessions/' + plan['id'] + '/dismiss',
                                         headers={'Authorization': 'Bearer owner'})
        self.assertTrue(response.json()['dismissed'])
        self.assertEqual(changes.read_records(self.shop, 'owner'), before)

    def test_outcomes_come_from_saved_records_not_model_claims(self):
        state = changes.normalize_plan({'items': [suggestion(self.current[0])]}, self.current, DATES, '洗衣机延期')
        self.assertEqual(changes.refresh_outcomes(copy.deepcopy(state), self.current)['items'][0]['outcome'], '未变更')
        actual = copy.deepcopy(self.current)
        actual[0].update(date=DATES[1], slot='14:00-18:00')
        self.assertEqual(changes.refresh_outcomes(copy.deepcopy(state), actual)['items'][0]['outcome'], '已应用')
        actual[0]['date'] = DATES[2]
        self.assertEqual(changes.refresh_outcomes(copy.deepcopy(state), actual)['items'][0]['outcome'], '已调整')
        actual[0]['status'] = '已取消'
        self.assertEqual(changes.refresh_outcomes(copy.deepcopy(state), actual)['items'][0]['outcome'], '已取消')


if __name__ == '__main__':
    unittest.main()
