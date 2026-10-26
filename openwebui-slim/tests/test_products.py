"""Catalog filtering, stock freshness and native embed boundaries."""
import json
from pathlib import Path
import shutil
import unittest

import test_demo_shop as fixtures

ROOT = fixtures.ROOT


class ProductTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.DemoShopTests.setUp
    tearDown = fixtures.DemoShopTests.tearDown

    def prepare(self):
        shutil.copyfile(ROOT / 'product-catalog.json', Path(self.temp.name) / 'product-catalog.json')
        shutil.copyfile(ROOT / 'tools/product_cards.html', Path(self.temp.name) / 'product_cards.html')

    async def test_filters_change_results_and_no_match_is_honest(self):
        self.prepare()
        result = await self.tools.search_demo_products(max_price_yuan=4000, requires_drying=True)
        self.assertEqual({p['model'] for p in result['products']}, {'JG-WD10', 'JG-WD12'})
        result = await self.tools.search_demo_products(max_price_yuan=2000, requires_drying=True)
        self.assertEqual(result['products'], [])
        result = await self.tools.search_demo_products(max_price_yuan=2000, max_depth_mm=500, category='洗衣机')
        self.assertEqual([p['model'] for p in result['products']], ['JG-F8'])
        result = await self.tools.search_demo_products(product_type='波轮洗衣机')
        self.assertEqual([p['model'] for p in result['products']], ['JG-T9'])

    async def test_category_filters_and_comparison_rows(self):
        self.prepare()
        ac = await self.tools.search_demo_products(category='空调', horsepower=1.5, max_price_yuan=3000)
        self.assertEqual([p['model'] for p in ac['products']], ['JG-AC35'])
        fridge = await self.tools.search_demo_products(category='冰箱', min_volume_l=400)
        self.assertEqual([p['model'] for p in fridge['products']], ['JG-R549'])
        self.assertEqual((await self.tools.search_demo_products(category='冰箱', requires_drying=True))['products'], [])
        all_products = (await self.tools.search_demo_products())['products']
        self.assertEqual({category: sum(p['category'] == category for p in all_products)
                          for category in ['洗衣机', '空调', '冰箱']}, {'洗衣机': 6, '空调': 3, '冰箱': 3})
        for p in ac['products'] + fridge['products']:
            self.assertNotIn('洗涤容量', p['comparison_specs'])
            self.assertNotIn('烘干方式', p['comparison_specs'])
        self.assertEqual(ac['products'][0]['comparison_specs']['额定制冷量'], '3510 W')
        self.assertEqual(fridge['products'][0]['comparison_specs']['总容积'], '549 L')

    async def test_air_conditioner_and_fridge_use_existing_order_flow(self):
        async def confirm(event):
            return {'action': 'select', 'id': self.address_id} if event['type'] == 'execute' else True
        for model in ['JG-AC35', 'JG-R549']:
            before = (await self.tools.get_demo_offers(model))['offers'][0]['stock']
            result = await self.tools.place_demo_order(**(self.args | {'model': model}), __event_call__=confirm)
            self.assertEqual(result['order']['model'], model)
            self.assertEqual((await self.tools.get_demo_offers(model))['offers'][0]['stock'], before - 1)

    async def test_new_manuals_are_category_specific_and_traceable(self):
        for p in json.loads((ROOT / 'product-catalog.json').read_text())['products']:
            if p['category'] == '洗衣机':
                continue
            text = (ROOT / 'knowledge' / f'{p["model"]}_说明书.md').read_text()
            for label in ['首次使用', '清洁与保养', '故障排查', '预约报修', p['reference_manual_url']]:
                self.assertIn(label, text)
            self.assertNotIn('### ' + p['model'] + '：E4 衣物偏载', text)
            self.assertIn('没有', text)
            if p['category'] == '冰箱':
                self.assertEqual(p['total_l'], p['fridge_l'] + p['freezer_l'] + p['variable_l'])
                self.assertIn('温控', text)
            else:
                self.assertIn('除湿', text)
                self.assertIn('化霜', text)

    async def test_dynamic_catalog_and_live_offers_not_prompt_constants(self):
        self.prepare()
        products = json.loads((Path(self.temp.name) / 'product-catalog.json').read_text())
        extra = products['products'][0] | {'model': 'JG-NEW', 'name': '新增演示型号'}
        products['products'].append(extra)
        (Path(self.temp.name) / 'product-catalog.json').write_text(json.dumps(products))
        offers = json.loads((Path(self.temp.name) / 'catalog.json').read_text())
        offers['products'].append({'model': 'JG-NEW', 'price_cents': 99900, 'stock': 3})
        (Path(self.temp.name) / 'catalog.json').write_text(json.dumps(offers))
        result = await self.tools.search_demo_products(max_price_yuan=1000)
        self.assertEqual([p['model'] for p in result['products']], ['JG-NEW'])
        with self.tools._db() as db:
            db.execute('UPDATE products SET stock=0,price_cents=199900 WHERE model=?', ('JG-NEW',))
        result = await self.tools.search_demo_products(max_price_yuan=1000)
        self.assertEqual(result['products'], [])
        result = await self.tools.search_demo_products()
        self.assertEqual(next(p['stock'] for p in result['products'] if p['model'] == 'JG-NEW'), 0)

    async def test_embed_validates_models_and_escapes_script_data(self):
        self.prepare()
        self.assertIn('error', await self.tools.show_product_cards(['NOT-A-MODEL']))
        response, context = await self.tools.show_product_cards(['JG-F8'], ['</script><script>alert(1)</script>'])
        content = response.body.decode()
        self.assertEqual(response.headers['content-disposition'], 'inline')
        self.assertNotIn('</script><script>alert(1)', content)
        self.assertIn('JG-F8.png', content)
        self.assertNotIn('base64', content)
        self.assertEqual(context['models'], ['JG-F8'])
        self.assertEqual((await self.tools.get_demo_orders(__user__={'id': 'test-user'}))['orders'], [])

    async def test_old_order_skus_queryable_but_not_default_offers(self):
        result = await self.tools.get_demo_offers()
        self.assertTrue(all(p['model'].startswith('JG-') for p in result['offers']))
        self.assertEqual(len(result['offers']), len(json.loads((ROOT / 'product-catalog.json').read_text())['products']))
        old = await self.tools.get_demo_offers('XQG100-HL58H1')
        self.assertEqual(old['offers'][0]['price_yuan'], 3299)

    async def test_new_product_uses_existing_confirmed_order_flow(self):
        async def confirm(event):
            if event['type'] == 'execute':
                return {'action': 'select', 'id': self.address_id}
            return True
        result = await self.tools.place_demo_order(**(self.args | {'model': 'JG-WD12'}), __event_call__=confirm)
        self.assertEqual(result['order']['total_yuan'], 3999)
        self.assertEqual(result['order']['model'], 'JG-WD12')
        self.assertEqual((await self.tools.get_demo_offers('JG-WD12'))['offers'][0]['stock'], 3)

    async def test_demo_materials_match_catalog_and_have_separate_provenance(self):
        catalog = json.loads((ROOT / 'product-catalog.json').read_text())
        for p in catalog['products']:
            if p['category'] == '洗衣机':
                self.assertLessEqual(p['dry_kg'], p['wash_kg'])
            self.assertTrue((ROOT / 'assets/products' / (p['model'] + '.png')).is_file())
            for kind in ['参数', '说明书']:
                text = (ROOT / 'knowledge' / f'{p["model"]}_{kind}.md').read_text()
                self.assertIn('资料类型：虚构产品资料', text)
                self.assertNotIn('官方说明书：', text)
                self.assertIn(p['model'], text)


if __name__ == '__main__':
    unittest.main()
