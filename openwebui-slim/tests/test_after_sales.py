"""Verify user-selected appliance binding, scoped persistence and confirmed ticket writes."""
from pathlib import Path
import json
import shutil

import unittest
import test_demo_shop as fixture

module = fixture.module


class AfterSalesTests(unittest.IsolatedAsyncioTestCase):
    confirm = fixture.DemoShopTests.confirm
    tearDown = fixture.DemoShopTests.tearDown
    def setUp(self):
        fixture.DemoShopTests.setUp(self)
        shutil.copyfile(Path(__file__).resolve().parents[1] / 'tools/service_dialog.js',
                        Path(self.temp.name) / 'service_dialog.js')
        self.user = {'id': 'test-user'}
        self.meta = {'session_id': 'test', 'chat_id': 'service-chat', 'message_id': 'service-message'}

    async def select(self, choice):
        async def choose(event):
            self.events.append(event)
            return choice
        return await self.tools.select_service_appliance(
            __user__=self.user, __metadata__=self.meta, __event_call__=choose)

    async def case(self):
        order = (await self.tools.place_demo_order(**self.args, __event_call__=self.confirm))['order']
        result = await self.select({'action': 'select', 'source': 'order',
                                    'order_id': order['order_id'], 'model': 'WRONG-MODEL', 'issue': '显示E4'})
        return result['case']

    async def submit(self, case_id, approved=True, cancel_address=False):
        async def answer(event):
            self.events.append(event)
            if event['type'] == 'confirmation':
                return approved
            if 'const serviceData' in event['data']['code']:
                return {'action': 'appointment', 'issue': '显示E4，按说明书检查后仍未解决',
                        'date': self.tools._schedule()[0], 'slot': '14:00-18:00'}
            return {'action': 'cancel'} if cancel_address else {'action': 'select', 'id': self.address_id}
        return await self.tools.create_demo_service_ticket(case_id, __user__=self.user,
                                                           __metadata__=self.meta, __event_call__=answer)

    async def test_selected_order_not_model_or_memory_controls_case(self):
        case = await self.case()
        self.assertEqual(case['model'], 'XQG100-HL58H1')
        self.assertTrue(case['selection_confirmed_by_user'])
        self.assertNotIn('order_snapshot', case)
        fresh = module.Tools();fresh.valves.DATA_DIR = self.temp.name
        saved = (await fresh.get_after_sales(case['case_id'], __user__=self.user))['cases'][0]
        self.assertEqual(saved['issue'], '显示E4')
        self.assertIsNone(saved['ticket'])
        self.assertEqual((await fresh.get_after_sales(__user__={'id':'other'}))['cases'], [])

    async def test_cancel_or_foreign_order_cannot_create_case(self):
        self.assertEqual((await self.select({'action':'cancel'}))['status'], '已取消')
        foreign = (await self.tools.place_demo_order(**(self.args | {'__user__':{'id':'other'}}),
                    __event_call__=self.confirm))  # No matching address for that user.
        self.assertIn('error', foreign)
        r = await self.select({'action':'select','source':'order','order_id':'DEMO-FOREIGN','issue':'故障'})
        self.assertIn('error', r)
        self.assertEqual((await self.tools.get_after_sales(__user__=self.user))['cases'], [])

    async def test_external_model_is_explicit_and_not_catalog_limited(self):
        r = await self.select({'action':'select','source':'external','model':'external-123','issue':'噪声'})
        self.assertEqual(r['case']['model'], 'EXTERNAL-123')
        self.assertIsNone(r['case']['order_id'])
        bad = await self.select({'action':'select','source':'external','model':' ','issue':'噪声'})
        self.assertIn('error', bad)

    async def test_multiple_orders_follow_explicit_choice_not_latest(self):
        first = (await self.tools.place_demo_order(**self.args, __event_call__=self.confirm))['order']
        await self.tools.place_demo_order(**(self.args | {'model':'XQG100-BEU38A5U1'}),
                                         __event_call__=self.confirm)
        result = await self.select({'action':'select','source':'order',
                                    'order_id':first['order_id'],'issue':'无法进水'})
        self.assertEqual(result['case']['order_id'], first['order_id'])
        self.assertEqual(result['case']['model'], first['model'])

    async def test_cancel_keeps_draft_without_ticket_then_resume_is_idempotent(self):
        case = await self.case()
        cancelled = await self.submit(case['case_id'], cancel_address=True)
        self.assertEqual(cancelled['status'], '已取消')
        persisted = (await self.tools.get_after_sales(case['case_id'], __user__=self.user))['cases'][0]
        self.assertEqual(persisted['stage'], '待确认报修')
        self.assertEqual(persisted['appointment']['slot'], '14:00-18:00')
        self.assertIsNone(persisted['ticket'])
        self.assertEqual((await self.submit(case['case_id'], approved=False))['status'], '已取消')
        created = await self.submit(case['case_id'])
        self.assertEqual(created['ticket']['order_id'], case['order_id'])
        self.assertEqual(created['ticket']['model'], case['model'])
        count = len(self.events)
        repeated = await self.submit(case['case_id'])
        self.assertTrue(repeated['already_created'])
        self.assertEqual(created['ticket']['ticket_id'], repeated['ticket']['ticket_id'])
        self.assertEqual(len(self.events), count)
        self.tools._save_address('test-user', self.address | {'id':self.address_id,'detail':'新地址'})
        stored = (await self.tools.get_after_sales(case['case_id'], __user__=self.user))['cases'][0]
        self.assertEqual(stored['ticket']['address']['detail'], '测试展位')
        self.assertEqual(stored['stage'], '已提交报修')

    async def test_foreign_case_or_no_browser_cannot_submit(self):
        case = await self.case()
        r = await self.tools.create_demo_service_ticket(case['case_id'], __user__={'id':'other'},
                                                       __metadata__=self.meta, __event_call__=self.confirm)
        self.assertIn('error', r)
        r = await self.tools.create_demo_service_ticket(case['case_id'], __user__=self.user)
        self.assertIn('error', r)

    async def test_latest_issue_prefills_form_without_changing_case_on_cancel(self):
        case = await self.case()
        latest = '脱水E4，已摊匀并减量，仍反复出现'
        async def cancel(event):
            prefix = 'const serviceData = '
            payload = json.loads(event['data']['code'].split(';\n', 1)[0][len(prefix):])
            self.assertEqual(payload['issue'], latest)
            self.assertEqual(payload['case_id'], case['case_id'])
            return {'action': 'cancel'}
        result = await self.tools.create_demo_service_ticket(
            case['case_id'], issue=latest, __user__=self.user,
            __metadata__=self.meta, __event_call__=cancel)
        self.assertEqual(result['status'], '已取消')
        persisted = (await self.tools.get_after_sales(case['case_id'], __user__=self.user))['cases'][0]
        self.assertEqual(persisted['issue'], case['issue'])
        self.assertIsNone(persisted['ticket'])

    async def test_ticket_lookup_does_not_mix_other_cases(self):
        first = await self.case()
        ticket = (await self.submit(first['case_id']))['ticket']
        await self.case()
        result = await self.tools.get_after_sales(ticket_id=ticket['ticket_id'], __user__=self.user)
        self.assertEqual([c['case_id'] for c in result['cases']], [first['case_id']])
        self.assertEqual(result['cases'][0]['ticket']['ticket_id'], ticket['ticket_id'])
        for user, number in [({'id': 'other'}, ticket['ticket_id']), (self.user, 'SRV-MISSING')]:
            result = await self.tools.get_after_sales(ticket_id=number, __user__=user)
            self.assertEqual(result['cases'], [])

    async def test_invalid_appointment_cannot_advance_case(self):
        case = await self.case()
        async def invalid(event):
            return {'action':'appointment','issue':'故障','date':'2000-01-01','slot':'14:00-18:00'}
        r = await self.tools.create_demo_service_ticket(case['case_id'], __user__=self.user,
                                                        __metadata__=self.meta, __event_call__=invalid)
        self.assertIn('error', r)
        self.assertEqual(self.tools._service_case('test-user', case['case_id'])['stage'], '待排查')

    async def test_new_catalog_models_keep_order_case_ticket_binding(self):
        catalog = json.loads((fixture.ROOT / 'product-catalog.json').read_text())
        for product in catalog['products']:
            with self.subTest(model=product['model']):
                order = (await self.tools.place_demo_order(
                    **(self.args | {'model': product['model']}), __event_call__=self.confirm))['order']
                result = await self.select({'action': 'select', 'source': 'order',
                    'order_id': order['order_id'], 'model': 'XQG100-HL58H1', 'issue': '显示E4'})
                case = result['case']
                self.assertEqual(case['model'], product['model'])
                self.assertIn('使用说明书', result['next_step'])
                ticket = (await self.submit(case['case_id']))['ticket']
                self.assertEqual(ticket['model'], product['model'])
                self.assertEqual(ticket['order_id'], order['order_id'])
                fresh = module.Tools(); fresh.valves.DATA_DIR = self.temp.name
                saved = (await fresh.get_after_sales(case['case_id'], __user__=self.user))['cases'][0]
                self.assertEqual(saved['ticket']['ticket_id'], ticket['ticket_id'])
                self.assertEqual(saved['stage'], '已提交报修')
