"""Address-book routes reuse checkout addresses without rewriting saved records."""
import json
import unittest
from uuid import uuid4

import test_record_routes as fixture


class AddressRoutesTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixture.RecordRoutesTests.setUp
    tearDown = fixture.RecordRoutesTests.tearDown
    asyncTearDown = fixture.RecordRoutesTests.asyncTearDown
    confirm = fixture.RecordRoutesTests.confirm
    select = fixture.RecordRoutesTests.select
    case = fixture.RecordRoutesTests.case
    submit = fixture.RecordRoutesTests.submit
    order = fixture.RecordRoutesTests.order
    stock = fixture.RecordRoutesTests.stock
    responder = fixture.RecordRoutesTests.responder
    records = fixture.RecordRoutesTests.records

    async def addresses(self, user='test-user'):
        response = await self.client.get('/api/v1/jiadian/addresses',
            headers={'Authorization': f'Bearer {user}'})
        self.assertEqual(response.status_code, 200)
        return response.json()['addresses']

    async def manage_address(self, action, address_id='', user='test-user', session='page-session'):
        response = await self.client.post('/api/v1/jiadian/addresses/manage',
            headers={'Authorization': f'Bearer {user}'}, json={
                'action': action, 'address_id': address_id, 'session_id': session,
                'operation_id': str(uuid4())})
        return response

    def editor(self, draft, approve=True):
        async def answer(event):
            self.events.append(event)
            if event['type'] == 'confirmation':
                return approve
            prefix = 'const addressData = '
            payload = json.loads(event['data']['code'].split(';\n', 1)[0][len(prefix):])
            self.assertTrue(payload['editor_only'])
            return {'action': 'save', 'address': draft}
        return answer

    def assert_success(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('error', response.json())

    async def test_authentication_socket_ownership_and_list_isolation(self):
        foreign = self.tools._save_address('other', self.address | {'detail': '另一位用户'})
        self.assertEqual([a['id'] for a in await self.addresses()], [self.address_id])
        self.assertEqual([a['id'] for a in await self.addresses('other')], [foreign])
        self.assertEqual((await self.client.get('/api/v1/jiadian/addresses')).status_code, 401)
        body = {'action': '删除', 'address_id': self.address_id,
                'session_id': 'page-session', 'operation_id': str(uuid4())}
        self.assertEqual((await self.client.post('/api/v1/jiadian/addresses/manage', json=body)).status_code, 401)
        for session in ('missing', 'foreign-session'):
            response = await self.manage_address('删除', self.address_id, session=session)
            self.assertEqual(response.status_code, 403)
        self.assertEqual(self.metadata, [])
        self.assertEqual([a['id'] for a in await self.addresses()], [self.address_id])

    async def test_first_address_defaults_and_setting_default_keeps_one_per_user(self):
        with self.tools._db() as db:
            db.execute('DELETE FROM addresses WHERE user_id=?', ('test-user',))
        self.reply = self.editor(self.address | {'is_default': False})
        self.assert_success(await self.manage_address('新增'))
        first = (await self.addresses())[0]
        self.assertTrue(first['is_default'])
        self.reply = self.editor(self.address | {'detail': '第二个地点', 'is_default': False})
        self.assert_success(await self.manage_address('新增'))
        saved = await self.addresses()
        second = next(a for a in saved if a['id'] != first['id'])
        self.assertFalse(second['is_default'])
        self.tools._save_address('other', self.address)
        foreign_before = await self.addresses('other')
        self.assert_success(await self.manage_address('设为默认', second['id']))
        self.assertEqual([a['id'] for a in await self.addresses() if a['is_default']], [second['id']])
        self.assertEqual(await self.addresses('other'), foreign_before)

    async def test_saved_edit_is_used_by_both_checkout_and_appointment(self):
        self.reply = self.editor(self.address | {'id': self.address_id, 'detail': '新的收货地点'})
        self.assert_success(await self.manage_address('修改', self.address_id))
        case = await self.case()
        ticket = (await self.submit(case['case_id']))['ticket']
        records = await self.records()
        self.assertEqual(records['orders'][0]['shipping_address']['id'], self.address_id)
        self.assertEqual(records['orders'][0]['shipping_address']['detail'], '新的收货地点')
        self.assertEqual(ticket['address']['id'], self.address_id)
        self.assertEqual(ticket['address']['detail'], '新的收货地点')

    async def test_delete_default_selects_most_recent_remaining_and_last_can_be_empty(self):
        second = self.tools._save_address('test-user', self.address | {'detail': '第二个地点', 'is_default': False})
        third = self.tools._save_address('test-user', self.address | {'detail': '第三个地点', 'is_default': False})
        with self.tools._db() as db:
            db.execute('UPDATE addresses SET created_at=? WHERE id=?', ('2026-10-21', second))
            db.execute('UPDATE addresses SET created_at=? WHERE id=?', ('2026-10-22', third))
        self.events.clear()
        self.reply = self.editor(self.address)
        self.assert_success(await self.manage_address('删除', self.address_id))
        self.assertEqual([e['type'] for e in self.events], ['confirmation'])
        self.assertEqual([a['id'] for a in await self.addresses() if a['is_default']], [third])
        self.assert_success(await self.manage_address('删除', third))
        self.assertEqual([a['id'] for a in await self.addresses() if a['is_default']], [second])
        self.assert_success(await self.manage_address('删除', second))
        self.assertEqual(await self.addresses(), [])

    async def test_declining_delete_or_closing_editor_preserves_addresses(self):
        original = await self.addresses()
        self.reply = self.editor(self.address, approve=False)
        self.assert_success(await self.manage_address('删除', self.address_id))
        self.assertEqual(await self.addresses(), original)

        async def close(event):
            return {'action': 'cancel'}

        self.reply = close
        for action in ('新增', '修改'):
            with self.subTest(action=action):
                self.assert_success(await self.manage_address(action, self.address_id if action == '修改' else ''))
                self.assertEqual(await self.addresses(), original)

    async def test_foreign_address_cannot_be_modified_deleted_or_made_default(self):
        foreign = self.tools._save_address('other', self.address | {'detail': '外人地点'})
        mine, others = await self.addresses(), await self.addresses('other')
        self.events.clear()
        self.reply = self.editor(self.address | {'id': foreign, 'detail': '不应保存'})
        for action in ('修改', '删除', '设为默认'):
            with self.subTest(action=action):
                response = await self.manage_address(action, foreign)
                self.assertEqual(response.status_code, 200)
                self.assertIn('error', response.json())
                self.assertEqual(await self.addresses(), mine)
                self.assertEqual(await self.addresses('other'), others)
        self.assertEqual(self.events, [])

    async def test_requested_address_id_overrides_editor_payload_id(self):
        second = self.tools._save_address('test-user', self.address | {'detail': '第二个地点', 'is_default': False})
        foreign = self.tools._save_address('other', self.address | {'detail': '外人地点'})
        foreign_before = await self.addresses('other')
        self.reply = self.editor(self.address | {'id': second, 'detail': '应写到第一个地址'})
        self.assert_success(await self.manage_address('修改', self.address_id))
        saved = {a['id']: a for a in await self.addresses()}
        self.assertEqual(saved[self.address_id]['detail'], '应写到第一个地址')
        self.assertEqual(saved[second]['detail'], '第二个地点')
        self.reply = self.editor(self.address | {'id': foreign, 'detail': '新增地点'})
        self.assert_success(await self.manage_address('新增'))
        added = next(a for a in await self.addresses() if a['detail'] == '新增地点')
        self.assertNotIn(added['id'], (self.address_id, second, foreign))
        self.assertEqual(await self.addresses('other'), foreign_before)

    async def test_edit_and_delete_never_rewrite_saved_order_or_ticket_addresses(self):
        case = await self.case()
        await self.submit(case['case_id'])
        original_records = await self.records()
        self.reply = self.editor(self.address | {'id': self.address_id, 'detail': '新地点'})
        self.assert_success(await self.manage_address('修改', self.address_id))
        self.assertEqual(await self.records(), original_records)
        self.assert_success(await self.manage_address('删除', self.address_id))
        self.assertEqual(await self.addresses(), [])
        self.assertEqual(await self.records(), original_records)

    async def test_callback_errors_cannot_save_or_confirm_delete(self):
        original = await self.addresses()

        async def failed(event):
            return {'error': 'Client disconnected'}

        self.reply = failed
        for action in ('新增', '修改', '删除'):
            with self.subTest(action=action):
                response = await self.manage_address(action, self.address_id if action != '新增' else '')
                self.assertEqual(response.status_code, 200)
                self.assertIn('error', response.json())
                self.assertEqual(await self.addresses(), original)


if __name__ == '__main__':
    unittest.main()
