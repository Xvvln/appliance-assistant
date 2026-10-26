"""Focused order invariants: confirmation, stock, retry, persistence and user scope."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('demo_shop', ROOT / 'tools/demo_shop.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DemoShopTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp_root = ROOT.parent / '临时文件'
        temp_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        shutil.copyfile(ROOT / 'demo-catalog.json', Path(self.temp.name) / 'catalog.json')
        shutil.copyfile(ROOT / 'tools/address_dialog.js', Path(self.temp.name) / 'address_dialog.js')
        self.tools = module.Tools()
        self.tools.valves.DATA_DIR = self.temp.name
        self.events = []
        self.address = {'recipient': '测试客户', 'region': '虚构地区', 'detail': '测试展位',
                        'phone': '', 'label': '家', 'is_default': True}
        self.address_id = self.tools._save_address('test-user', self.address)
        self.args = dict(model='XQG100-HL58H1', quantity=1, delivery_date=self.tools._schedule()[0],
                         delivery_slot='09:00-12:00', service='送装一体',
                         __user__={'id': 'test-user'},
                         __metadata__={'session_id': 'test', 'chat_id': 'chat', 'message_id': 'message'})

    def tearDown(self):
        self.temp.cleanup()

    async def confirm(self, event):
        self.events.append(event)
        if event['type'] == 'execute':
            return {'action': 'select', 'id': self.address_id}
        return True

    async def decline(self, event):
        if event['type'] == 'execute':
            return {'action': 'select', 'id': self.address_id}
        return False

    async def test_confirmation_cancel_does_not_write(self):
        r = await self.tools.place_demo_order(**self.args, __event_call__=self.decline)
        self.assertEqual(r['status'], '已取消')
        self.assertEqual((await self.tools.get_demo_orders(__user__={'id': 'test-user'}))['orders'], [])
        self.assertEqual((await self.tools.get_demo_offers(self.args['model']))['offers'][0]['stock'], 8)

    async def test_confirm_retry_persistence_and_scope(self):
        r = await self.tools.place_demo_order(**self.args, __event_call__=self.confirm)
        self.assertEqual(r['order']['total_yuan'], 3299)
        self.assertIn('3299.00', self.events[1]['data']['message'])
        again = await self.tools.place_demo_order(**self.args, __event_call__=self.confirm)
        self.assertEqual(again['order']['order_id'], r['order']['order_id'])
        self.assertEqual(len(self.events), 2)
        self.assertEqual((await self.tools.get_demo_offers(self.args['model']))['offers'][0]['stock'], 7)
        fresh = module.Tools()
        fresh.valves.DATA_DIR = self.temp.name
        self.assertEqual(len((await fresh.get_demo_orders(__user__={'id': 'test-user'}))['orders']), 1)
        self.assertEqual((await fresh.get_demo_orders(__user__={'id': 'other'}))['orders'], [])

    async def test_no_stock_or_browser_no_order(self):
        args = self.args | {'model': 'EG100PRO89'}
        self.assertIn('库存不足', (await self.tools.place_demo_order(**args, __event_call__=self.confirm))['error'])
        self.assertEqual(self.events, [])
        self.assertIn('页面', (await self.tools.place_demo_order(**self.args))['error'])

    async def test_stock_changed_while_user_confirming(self):
        async def stock_changed(event):
            if event['type'] == 'execute':
                return {'action': 'select', 'id': self.address_id}
            with self.tools._db() as db:
                db.execute('UPDATE products SET stock=0 WHERE model=?', (self.args['model'],))
            return True
        r = await self.tools.place_demo_order(**self.args, __event_call__=stock_changed)
        self.assertIn('发生变化', r['error'])
        self.assertEqual((await self.tools.get_demo_orders(__user__={'id': 'test-user'}))['orders'], [])

    async def test_address_edit_does_not_rewrite_order_and_defaults_are_scoped(self):
        other = self.tools._save_address('other', self.address)
        second = self.tools._save_address('test-user', self.address | {'label': '公司', 'detail': '展位B'})
        self.assertEqual([a['id'] for a in self.tools._addresses('test-user') if a['is_default']], [second])
        self.assertEqual([a['id'] for a in self.tools._addresses('other')], [other])
        order = (await self.tools.place_demo_order(**self.args, __event_call__=self.confirm))['order']
        self.tools._save_address('test-user', self.address | {'id': self.address_id, 'detail': '修改后的地点'})
        stored = (await self.tools.get_demo_orders(order['order_id'], __user__={'id':'test-user'}))['orders'][0]
        self.assertEqual(stored['shipping_address']['detail'], '测试展位')
        with self.assertRaises(ValueError):
            self.tools._save_address('test-user', self.address | {'id': other})

    async def test_address_picker_cancel_and_foreign_selection_do_not_order(self):
        async def cancel(event):
            return {'action': 'cancel'}
        self.assertEqual((await self.tools.place_demo_order(**self.args, __event_call__=cancel))['status'], '已取消')
        foreign = self.tools._save_address('other', self.address)
        async def choose_foreign(event):
            return {'action': 'select', 'id': foreign}
        self.assertIn('未找到', (await self.tools.place_demo_order(**self.args, __event_call__=choose_foreign))['error'])
        self.assertEqual((await self.tools.get_demo_orders(__user__={'id':'test-user'}))['orders'], [])

    async def test_save_multiple_addresses_then_close_preserves_them(self):
        results = iter([{'action':'save','address':self.address | {'label':'父母家','detail':'展位C'}},
                        {'action':'save','address':self.address | {'label':'公司','detail':'展位D'}},
                        {'action':'cancel'}])
        async def fill_forms(event):
            return next(results)
        await self.tools.manage_shipping_addresses(__user__={'id':'test-user'},
                                                  __metadata__={'session_id':'test'}, __event_call__=fill_forms)
        self.assertEqual(len(self.tools._addresses('test-user')),3)
        self.assertEqual(sum(a['is_default'] for a in self.tools._addresses('test-user')),1)


if __name__ == '__main__':
    unittest.main()
