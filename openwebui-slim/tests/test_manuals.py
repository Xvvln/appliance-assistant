"""Prevent cross-model capabilities and stale generated manuals in the demo corpus."""
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_product_materials', ROOT / 'build_product_materials.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class ManualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = [p for p in json.loads((ROOT / 'product-catalog.json').read_text())['products'] if p['category'] == '洗衣机']

    def test_every_model_has_daily_use_and_troubleshooting_with_model_headings(self):
        required = ['首次使用', '日常洗衣步骤', '程序选择与装载', '洗涤剂与柔顺剂',
                    '烘干与洗后处理', '暂停、开门与正常现象', '清洁与保养', '故障代码与逐步排查']
        for p in self.products:
            with self.subTest(model=p['model']):
                text = (ROOT / 'knowledge' / f'{p["model"]}_说明书.md').read_text()
                for title in required:
                    self.assertIn(f'## {p["model"]}· {title}', text)
                self.assertIn(f'### {p["model"]}：E4 衣物偏载', text)
                self.assertIn('虚构产品资料', text)
                self.assertIn('不强拉', text)
                self.assertIn('不可用于真实机器安装', text)
                page = (ROOT / 'assets/docs' / f'{p["model"]}-manual.html').read_text()
                self.assertIn('首次使用', page)
                self.assertIn('E4 衣物偏载', page)

    def test_drying_programs_and_capacities_follow_catalog(self):
        for p in self.products:
            with self.subTest(model=p['model']):
                text = builder.build_manual(p, '', '安装条件')
                if p['type'] == '洗烘塔':
                    self.assertIn('没有同筒“洗烘连续”程序', text)
                    self.assertIn('手动从下筒转移', text)
                    self.assertIn('不超过 10kg', text)
                    self.assertNotIn('选择“单烘干', text)
                elif p['dry_kg']:
                    self.assertIn(f'单烘干（≤{p["dry_kg"]}kg）', text)
                    self.assertIn(f'已经按 {p["wash_kg"]}kg洗涤时', text)
                    self.assertIn('先取出一部分衣物分批烘干', text)
                else:
                    self.assertIn('本机不支持热风、冷凝或热泵烘干', text)
                    self.assertNotIn('选择“单烘干', text)

    def test_dosing_networking_and_top_cover_stay_model_specific(self):
        for p in self.products:
            with self.subTest(model=p['model']):
                text = builder.build_manual(p, '', '安装条件')
                self.assertIn('本机支持自动投放' if p['auto_dose'] else '本机不支持自动投放', text)
                self.assertIn('本机支持Wi-Fi是产品规格' if p['wifi'] else '本机不支持Wi-Fi', text)
                for program in p['programs']:
                    self.assertIn(f'**{program}**', text)
                if p['model'] == 'JG-T9':
                    self.assertIn('选中“桶清洁”', text)
                    self.assertNotIn('选中“筒清洁”', text)
                    self.assertIn('没有配网', text)


if __name__ == '__main__':
    unittest.main()
