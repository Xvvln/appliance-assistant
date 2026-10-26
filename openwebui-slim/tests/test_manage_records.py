"""Confirmed edits/cancellations keep inventory, ownership and linked records consistent."""
import json
import unittest
import test_after_sales as fixture


class ManageRecordsTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixture.AfterSalesTests.setUp
    tearDown = fixture.AfterSalesTests.tearDown
    confirm = fixture.AfterSalesTests.confirm
    select = fixture.AfterSalesTests.select
    case = fixture.AfterSalesTests.case
    submit = fixture.AfterSalesTests.submit

    async def order(self):
        return (await self.tools.place_demo_order(**self.args, __event_call__=self.confirm))['order']

    def responder(self, quantity=2, approve=True, choose_id='', address_id=None):
        async def answer(event):
            self.events.append(event)
            if event['type'] == 'confirmation':
                return approve
            if 'const serviceData' in event['data']['code']:
                data = json.loads(event['data']['code'].split('const serviceData = ', 1)[1].split(';\n', 1)[0])
                if data['mode'] == 'record-select':
                    return {'action': 'record-select', 'id': choose_id}
                if data['mode'] == 'order-edit':
                    return {'action': 'order-edit', 'quantity': quantity, 'date': self.tools._schedule()[1],
                            'slot': '14:00-18:00', 'service': '仅配送'}
                return {'action': 'appointment', 'issue': '检查后仍无改善',
                        'date': self.tools._schedule()[2], 'slot': '09:00-12:00'}
            return {'action': 'select', 'id': address_id or self.address_id}
        return answer

    async def manage_order(self, oid='', action='修改', callback=None, user=None):
        return await self.tools.manage_order(action, oid, __user__=user or self.user,
            __metadata__=self.meta, __event_call__=callback or self.responder())

    async def manage_ticket(self, tid='', action='修改', callback=None, user=None):
        return await self.tools.manage_service_ticket(action, tid, __user__=user or self.user,
            __metadata__=self.meta, __event_call__=callback or self.responder())

    async def stock(self):
        return (await self.tools.get_demo_offers(self.args['model']))['offers'][0]['stock']

    async def test_order_edit_preserves_identity_price_and_stock_delta(self):
        o = await self.order()
        new_addr = self.tools._save_address('test-user', self.address | {'detail': '新地点'})
        result = await self.manage_order(o['order_id'], callback=self.responder(address_id=new_addr))
        changed = result['order']
        self.assertEqual(changed['order_id'], o['order_id'])
        self.assertEqual(changed['unit_price_yuan'], o['unit_price_yuan'])
        self.assertEqual(changed['total_yuan'], o['unit_price_yuan'] * 2)
        self.assertEqual(changed['shipping_address']['detail'], '新地点')
        self.assertEqual(changed['service'], '仅配送')
        self.assertEqual(await self.stock(), 6)
        await self.manage_order(o['order_id'], callback=self.responder(quantity=1))
        self.assertEqual(await self.stock(), 7)

    async def test_unconfirmed_edit_and_cancel_preserve_record(self):
        o = await self.order()
        for action in ['修改', '取消']:
            result = await self.manage_order(o['order_id'], action, self.responder(approve=False))
            self.assertEqual(result['status'], '未提交')
            self.assertEqual((await self.tools.get_demo_orders(o['order_id'], __user__=self.user))['orders'][0], o)
            self.assertEqual(await self.stock(), 7)

    async def test_insufficient_stock_and_foreign_record_rejected(self):
        o = await self.order()
        self.assertIn('error', await self.manage_order(o['order_id'], callback=self.responder(quantity=100)))
        self.assertIn('error', await self.manage_order(o['order_id'], user={'id':'other'}))
        self.assertEqual(await self.stock(), 7)

    async def test_record_picker_and_cancel_are_idempotent(self):
        o = await self.order()
        r = await self.manage_order(action='取消', callback=self.responder(choose_id=o['order_id']))
        self.assertEqual(r['order']['status'], '已取消')
        self.assertEqual(await self.stock(), 8)
        self.assertTrue((await self.manage_order(o['order_id'], '取消'))['already_cancelled'])
        self.assertEqual(await self.stock(), 8)
        bad = await self.select({'action':'select','source':'order','order_id':o['order_id'],'issue':'故障'})
        self.assertIn('error', bad)

    async def test_cancel_order_cancels_linked_ticket_and_blocks_stale_case(self):
        case = await self.case(); t = (await self.submit(case['case_id']))['ticket']
        r = await self.manage_order(case['order_id'], '取消')
        self.assertEqual(r['cancelled_ticket_ids'], [t['ticket_id']])
        saved = (await self.tools.get_after_sales(case['case_id'], __user__=self.user))['cases'][0]
        self.assertEqual(saved['ticket']['status'], '已取消')
        self.assertEqual(saved['stage'], '订单已取消')
        self.assertIn('error', await self.submit(case['case_id']))
        self.assertEqual(await self.stock(), 8)

    async def test_ticket_edit_cancel_and_order_independence(self):
        case = await self.case(); t = (await self.submit(case['case_id']))['ticket']
        original = (await self.tools.get_demo_orders(case['order_id'], __user__=self.user))['orders'][0]
        new_addr = self.tools._save_address('test-user', self.address | {'detail':'新上门地点'})
        r = await self.manage_ticket(t['ticket_id'], callback=self.responder(address_id=new_addr))
        self.assertEqual(r['ticket']['ticket_id'], t['ticket_id'])
        self.assertEqual(r['ticket']['appointment']['date'], self.tools._schedule()[2])
        self.assertEqual(r['ticket']['address']['detail'], '新上门地点')
        saved = (await self.tools.get_after_sales(case['case_id'], __user__=self.user))['cases'][0]
        self.assertEqual(saved['appointment'], r['ticket']['appointment'])
        await self.manage_order(case['order_id'], callback=self.responder(quantity=1))
        self.assertEqual((await self.tools.get_after_sales(case['case_id'], __user__=self.user))['cases'][0]['ticket'], r['ticket'])
        r = await self.manage_ticket(t['ticket_id'], '取消')
        self.assertEqual(r['ticket']['status'], '已取消')
        self.assertTrue((await self.manage_ticket(t['ticket_id'], '取消'))['already_cancelled'])
        self.assertEqual(await self.stock(), 7)
        self.assertEqual((await self.tools.get_demo_orders(case['order_id'], __user__=self.user))['orders'][0]['status'], original['status'])

    async def test_ticket_unconfirmed_or_foreign_does_not_change(self):
        case = await self.case(); t = (await self.submit(case['case_id']))['ticket']
        for action in ['修改', '取消']:
            r = await self.manage_ticket(t['ticket_id'], action, self.responder(approve=False))
            self.assertEqual(r['status'], '未提交')
        self.assertIn('error', await self.manage_ticket(t['ticket_id'], user={'id':'other'}))
        saved = (await self.tools.get_after_sales(case['case_id'], __user__=self.user))['cases'][0]['ticket']
        self.assertEqual(saved, t)

    async def test_order_changed_during_confirmation_is_not_overwritten(self):
        o = await self.order(); respond = self.responder()
        async def concurrent(event):
            if event['type'] == 'confirmation':
                await self.manage_order(o['order_id'], '取消')
                return True
            return await respond(event)
        result = await self.manage_order(o['order_id'], callback=concurrent)
        self.assertIn('已变化', result['error'])
        self.assertEqual(await self.stock(), 8)

    async def test_ticket_changed_during_confirmation_is_not_overwritten(self):
        case = await self.case(); t = (await self.submit(case['case_id']))['ticket']; respond = self.responder()
        async def concurrent(event):
            if event['type'] == 'confirmation':
                await self.manage_order(case['order_id'], '取消')
                return True
            return await respond(event)
        result = await self.manage_ticket(t['ticket_id'], callback=concurrent)
        self.assertIn('已变化', result['error'])

    async def test_order_cancelled_during_new_ticket_confirmation_does_not_create_ticket(self):
        case = await self.case(); respond = self.responder()
        async def concurrent(event):
            if event['type'] == 'confirmation':
                await self.manage_order(case['order_id'], '取消')
                return True
            return await respond(event)
        result = await self.tools.create_demo_service_ticket(case['case_id'], __user__=self.user,
            __metadata__=self.meta, __event_call__=concurrent)
        self.assertIn('error', result)
        saved = (await self.tools.get_after_sales(case['case_id'], __user__=self.user))['cases'][0]
        self.assertIsNone(saved['ticket'])
        self.assertEqual(saved['stage'], '订单已取消')
