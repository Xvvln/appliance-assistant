"""The records page uses authenticated, owner-scoped calls to the existing tools."""
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Request

import test_after_sales as sales_fixture
import test_manage_records as fixture


class RecordRoutesTests(unittest.IsolatedAsyncioTestCase):
    tearDown = fixture.ManageRecordsTests.tearDown
    confirm = fixture.ManageRecordsTests.confirm
    select = fixture.ManageRecordsTests.select
    case = fixture.ManageRecordsTests.case
    submit = fixture.ManageRecordsTests.submit
    order = fixture.ManageRecordsTests.order
    stock = fixture.ManageRecordsTests.stock
    responder = fixture.ManageRecordsTests.responder

    def setUp(self):
        fixture.ManageRecordsTests.setUp(self)
        app = FastAPI()
        app.mount('', FastAPI())
        self.sessions = {'page-session': {'id': 'test-user'}, 'foreign-session': {'id': 'other'}}
        self.metadata = []
        self.reply = self.responder()

        async def verified_user(request: Request):
            token = request.headers.get('authorization', '')
            if token not in ('Bearer test-user', 'Bearer other'):
                raise HTTPException(401, 'Authentication required')
            return SimpleNamespace(id=token.removeprefix('Bearer '))

        async def get_event_call(metadata):
            self.metadata.append(metadata)
            return self.reply

        main = ModuleType('open_webui.main')
        main.app = app
        socket = ModuleType('open_webui.socket.main')
        socket.SESSION_POOL = self.sessions
        socket.get_event_call = get_event_call
        auth = ModuleType('open_webui.utils.auth')
        auth.get_verified_user = verified_user
        # Import only our thin routes, without starting Open WebUI or accessing its data.
        stubs = {name: ModuleType(name) for name in (
            'open_webui', 'open_webui.socket', 'open_webui.utils', 'tools')}
        stubs.update({'open_webui.main': main, 'open_webui.socket.main': socket,
                      'open_webui.utils.auth': auth, 'tools.demo_shop': sales_fixture.module})
        # Unrelated assistant routers are covered separately; keep this fixture scoped
        # to the existing commerce routes even after project_server mounts new features.
        for feature in ('guidance', 'plans', 'changes', 'preview'):
            module = ModuleType(f'features.{feature}')
            module.router = APIRouter()
            stubs[f'features.{feature}'] = module
        path = Path(__file__).resolve().parents[1] / 'project_server.py'
        spec = importlib.util.spec_from_file_location('record_routes_under_test', path)
        self.routes = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, stubs):
            spec.loader.exec_module(self.routes)
        self.routes.shop = self.tools
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                       base_url='http://records.test')

    async def asyncTearDown(self):
        await self.client.aclose()

    async def records(self, user='test-user'):
        response = await self.client.get('/api/v1/jiadian/records',
                                         headers={'Authorization': f'Bearer {user}'})
        self.assertEqual(response.status_code, 200)
        return response.json()

    async def manage(self, kind, record_id, action='修改', user='test-user', session='page-session',
                     schedule_draft=None):
        body = {'action': action, 'session_id': session, 'operation_id': str(uuid4())}
        if schedule_draft is not None:
            body['schedule_draft'] = schedule_draft
        return await self.client.post(f'/api/v1/jiadian/records/{kind}/{record_id}/manage',
            headers={'Authorization': f'Bearer {user}'}, json=body)

    def use_prefilled_form(self, forms, approve=True, before_confirmation=None):
        async def reply(event):
            self.events.append(event)
            if event['type'] == 'confirmation':
                if before_confirmation is not None:
                    self.assertEqual(await self.records(), before_confirmation)
                return approve
            prefix = 'const serviceData = '
            code = event['data']['code']
            if code.startswith(prefix):
                payload = json.loads(code[len(prefix):].split(';\n', 1)[0])
                forms.append(payload)
                result = {'action': payload['mode'], **payload['draft']}
                if payload['mode'] == 'appointment':
                    result['issue'] = payload['issue']
                return result
            return {'action': 'select', 'id': self.address_id}
        return reply

    async def test_schedule_draft_prefills_order_but_keeps_fields_and_requires_confirmation(self):
        order = await self.order()
        original, original_stock = await self.records(), await self.stock()
        draft = {'date': self.tools._schedule()[2], 'slot': '14:00-18:00',
                 'quantity': '99', 'service': '仅配送', 'model': 'WRONG'}
        for approve in (False, True):
            with self.subTest(approve=approve):
                forms = []
                self.events.clear()
                self.reply = self.use_prefilled_form(forms, approve, original)
                response = await self.manage('orders', order['order_id'], schedule_draft=draft)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(forms[0]['mode'], 'order-edit')
                self.assertEqual(forms[0]['model'], order['model'])
                self.assertEqual(forms[0]['draft'], {
                    'quantity': order['quantity'], 'date': draft['date'],
                    'slot': draft['slot'], 'service': order['service']})
                self.assertEqual([e['type'] for e in self.events], ['execute', 'execute', 'confirmation'])
                if not approve:
                    self.assertEqual(response.json()['status'], '未提交')
                    self.assertEqual(await self.records(), original)
                else:
                    changed = response.json()['order']
                    self.assertEqual(changed['delivery_date'], draft['date'])
                    self.assertEqual(changed['delivery_slot'], draft['slot'])
                    for key in ('quantity', 'service', 'unit_price_yuan', 'total_yuan', 'order_id'):
                        self.assertEqual(changed[key], order[key])
                self.assertEqual(await self.stock(), original_stock)

    async def test_schedule_draft_prefills_appointment_but_keeps_issue_order_and_confirmation(self):
        case = await self.case()
        ticket = (await self.submit(case['case_id']))['ticket']
        original = await self.records()
        draft = {'date': self.tools._schedule()[2], 'slot': '09:00-12:00',
                 'issue': 'WRONG', 'model': 'WRONG'}
        for approve in (False, True):
            with self.subTest(approve=approve):
                forms = []
                self.events.clear()
                self.reply = self.use_prefilled_form(forms, approve, original)
                response = await self.manage('tickets', ticket['ticket_id'], schedule_draft=draft)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(forms[0]['mode'], 'appointment')
                self.assertEqual(forms[0]['model'], ticket['model'])
                self.assertEqual(forms[0]['issue'], ticket['issue'])
                self.assertEqual(forms[0]['draft'], {'date': draft['date'], 'slot': draft['slot']})
                self.assertEqual([e['type'] for e in self.events], ['execute', 'execute', 'confirmation'])
                if not approve:
                    self.assertEqual(response.json()['status'], '未提交')
                    self.assertEqual(await self.records(), original)
                else:
                    changed = response.json()['ticket']
                    self.assertEqual(changed['appointment'], forms[0]['draft'])
                    for key in ('issue', 'order_id', 'ticket_id', 'case_id'):
                        self.assertEqual(changed[key], ticket[key])
                self.assertEqual((await self.records())['orders'], original['orders'])

    async def test_invalid_schedule_draft_returns_400_without_dialogs_or_writes(self):
        case = await self.case()
        ticket = (await self.submit(case['case_id']))['ticket']
        original = await self.records()
        self.events.clear()
        for kind, record_id in [('orders', case['order_id']), ('tickets', ticket['ticket_id'])]:
            for draft in ({'date': '2099-01-01'}, {'slot': '00:00-01:00'}):
                with self.subTest(kind=kind, draft=draft):
                    response = await self.manage(kind, record_id, schedule_draft=draft)
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(self.events, [])
                    self.assertEqual(await self.records(), original)

    async def test_partial_schedule_draft_keeps_original_time_slot(self):
        order = await self.order()
        forms = []
        self.reply = self.use_prefilled_form(forms, approve=False)
        response = await self.manage('orders', order['order_id'],
                                     schedule_draft={'date': self.tools._schedule()[2]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(forms[0]['draft']['slot'], order['delivery_slot'])
        self.assertEqual(forms[0]['draft']['date'], self.tools._schedule()[2])
        self.assertEqual(response.json()['status'], '未提交')
        self.assertEqual((await self.records())['orders'], [order])

    async def test_lists_all_owned_history_and_excludes_other_users(self):
        case = await self.case()
        ticket = (await self.submit(case['case_id']))['ticket']
        order = (await self.tools.get_demo_orders(case['order_id'], __user__=self.user))['orders'][0]
        with self.tools._db() as db:
            for index in range(12):
                oid, tid = f'ORDER-{index:02d}', f'TICKET-{index:02d}'
                db.execute('INSERT INTO orders VALUES (?,?,?,?,?)',
                    (oid, 'test-user', oid, '2026-10-23', json.dumps(order | {'order_id': oid})))
                db.execute('INSERT INTO service_tickets VALUES (?,?,?,?,?)',
                    (tid, f'CASE-{index}', 'test-user', '2026-10-23',
                     json.dumps(ticket | {'ticket_id': tid})))
            db.execute('INSERT INTO orders VALUES (?,?,?,?,?)',
                ('FOREIGN-ORDER', 'other', 'foreign-request', '2099-01-01',
                 json.dumps(order | {'order_id': 'FOREIGN-ORDER'})))
            db.execute('INSERT INTO service_tickets VALUES (?,?,?,?,?)',
                ('FOREIGN-TICKET', 'FOREIGN-CASE', 'other', '2099-01-01',
                 json.dumps(ticket | {'ticket_id': 'FOREIGN-TICKET'})))
        mine = await self.records()
        self.assertEqual(len(mine['orders']), 13)
        self.assertEqual(len(mine['tickets']), 13)
        self.assertNotIn('FOREIGN-ORDER', [o['order_id'] for o in mine['orders']])
        self.assertNotIn('FOREIGN-TICKET', [t['ticket_id'] for t in mine['tickets']])
        other = await self.records('other')
        self.assertEqual([o['order_id'] for o in other['orders']], ['FOREIGN-ORDER'])
        self.assertEqual([t['ticket_id'] for t in other['tickets']], ['FOREIGN-TICKET'])

    async def test_authentication_and_socket_ownership_are_required(self):
        order = await self.order()
        body = {'action': '取消', 'session_id': 'page-session', 'operation_id': str(uuid4())}
        self.assertEqual((await self.client.get('/api/v1/jiadian/records')).status_code, 401)
        response = await self.client.post(
            f"/api/v1/jiadian/records/orders/{order['order_id']}/manage", json=body)
        self.assertEqual(response.status_code, 401)
        for session in ('missing', 'foreign-session'):
            response = await self.manage('orders', order['order_id'], '取消', session=session)
            self.assertEqual(response.status_code, 403)
        self.assertEqual(self.metadata, [])
        self.assertEqual((await self.records())['orders'], [order])
        self.assertEqual(await self.stock(), 7)

    async def test_order_edit_uses_existing_forms_confirmation_and_stock_transaction(self):
        order = await self.order()
        self.events.clear()
        response = await self.manage('orders', order['order_id'])
        self.assertEqual(response.status_code, 200)
        changed = response.json()['order']
        self.assertEqual(changed['order_id'], order['order_id'])
        self.assertEqual(changed['quantity'], 2)
        self.assertEqual(changed['total_yuan'], order['unit_price_yuan'] * 2)
        self.assertEqual(changed['delivery_date'], self.tools._schedule()[1])
        self.assertEqual(await self.stock(), 6)
        self.assertEqual([e['type'] for e in self.events], ['execute', 'execute', 'confirmation'])
        self.assertEqual(self.metadata[0]['user_id'], 'test-user')
        self.assertEqual(self.metadata[0]['session_id'], 'page-session')
        self.assertEqual(self.metadata[0]['chat_id'], f"jiadian-records:{self.metadata[0]['message_id']}")
        self.assertEqual((await self.records())['orders'], [changed])

    async def test_order_cancel_keeps_linked_ticket_and_inventory_rules(self):
        case = await self.case()
        ticket = (await self.submit(case['case_id']))['ticket']
        response = await self.manage('orders', case['order_id'], '取消')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['cancelled_ticket_ids'], [ticket['ticket_id']])
        records = await self.records()
        self.assertEqual(records['orders'][0]['status'], '已取消')
        self.assertEqual(records['tickets'][0]['status'], '已取消')
        self.assertEqual(await self.stock(), 8)
        response = await self.manage('orders', case['order_id'], '取消')
        self.assertTrue(response.json()['already_cancelled'])
        self.assertEqual(await self.stock(), 8)

    async def test_ticket_edit_and_cancel_leave_order_intact(self):
        case = await self.case()
        ticket = (await self.submit(case['case_id']))['ticket']
        original_order = (await self.records())['orders'][0]
        self.events.clear()
        response = await self.manage('tickets', ticket['ticket_id'])
        self.assertEqual(response.status_code, 200)
        changed = response.json()['ticket']
        self.assertEqual(changed['ticket_id'], ticket['ticket_id'])
        self.assertEqual(changed['appointment']['date'], self.tools._schedule()[2])
        self.assertEqual([e['type'] for e in self.events], ['execute', 'execute', 'confirmation'])
        self.assertEqual((await self.records())['tickets'], [changed])
        response = await self.manage('tickets', ticket['ticket_id'], '取消')
        self.assertEqual(response.json()['ticket']['status'], '已取消')
        self.assertEqual((await self.records())['orders'], [original_order])
        self.assertEqual(await self.stock(), 7)

    async def test_declining_confirmation_does_not_write_either_record(self):
        case = await self.case()
        ticket = (await self.submit(case['case_id']))['ticket']
        original = await self.records()
        self.reply = self.responder(approve=False)
        for kind, rid in [('orders', case['order_id']), ('tickets', ticket['ticket_id'])]:
            for action in ('修改', '取消'):
                with self.subTest(kind=kind, action=action):
                    response = await self.manage(kind, rid, action)
                    self.assertEqual(response.json()['status'], '未提交')
                    self.assertEqual(await self.records(), original)
                    self.assertEqual(await self.stock(), 7)

    async def test_callback_error_is_not_treated_as_confirmation(self):
        case = await self.case()
        ticket = (await self.submit(case['case_id']))['ticket']
        original = await self.records()
        respond = self.responder()

        async def failed_confirmation(event):
            if event['type'] == 'confirmation':
                return {'error': 'disconnected'}
            return await respond(event)

        self.reply = failed_confirmation
        for kind, rid in [('orders', case['order_id']), ('tickets', ticket['ticket_id'])]:
            for action in ('修改', '取消'):
                with self.subTest(kind=kind, action=action):
                    response = await self.manage(kind, rid, action)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn('error', response.json())
                    self.assertEqual(await self.records(), original)
                    self.assertEqual(await self.stock(), 7)

    async def test_foreign_records_are_rejected_before_any_dialog(self):
        case = await self.case()
        ticket = (await self.submit(case['case_id']))['ticket']
        original = await self.records()
        self.events.clear()
        for kind, rid in [('orders', case['order_id']), ('tickets', ticket['ticket_id'])]:
            response = await self.manage(kind, rid, '取消', user='other', session='foreign-session')
            self.assertEqual(response.status_code, 200)
            self.assertIn('error', response.json())
        self.assertEqual(self.events, [])
        self.assertEqual(await self.records(), original)
        self.assertEqual(await self.stock(), 7)


if __name__ == '__main__':
    unittest.main()
