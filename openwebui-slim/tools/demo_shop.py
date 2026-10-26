"""
title: 家电商城
description: 选购下单、用户选机、售后表单与跨对话工单查询；不收款、不实际发货派工。
version: 0.5.0
required_open_webui_version: 0.12.3
license: MIT
"""
from contextlib import closing
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Awaitable, Callable
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from fastapi.responses import HTMLResponse


TZ = ZoneInfo('Asia/Shanghai')
SLOTS = ('09:00-12:00', '14:00-18:00')
SERVICES = ('送装一体', '仅配送')
NOTICE = '当前不收款、不实际发货。'


class Tools:
    class Valves(BaseModel):
        DATA_DIR: str = Field(
            default=str(Path(os.environ.get('DATA_DIR', './data')) / 'commerce'),
            description='商城数据目录，包含catalog.json和shop.sqlite3',
        )

    def __init__(self):
        self.valves = self.Valves()

    def _db(self) -> sqlite3.Connection:
        root = Path(self.valves.DATA_DIR)
        root.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(root / 'shop.sqlite3', timeout=10)
        db.row_factory = sqlite3.Row
        db.executescript('''
            CREATE TABLE IF NOT EXISTS products (
                model TEXT PRIMARY KEY, price_cents INTEGER NOT NULL CHECK(price_cents >= 0),
                stock INTEGER NOT NULL CHECK(stock >= 0));
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL, request_key TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS addresses (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL, recipient TEXT NOT NULL,
                phone TEXT NOT NULL, region TEXT NOT NULL, detail TEXT NOT NULL,
                label TEXT NOT NULL, is_default INTEGER NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS service_cases (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL, created_at TEXT NOT NULL,
                payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS service_tickets (
                id TEXT PRIMARY KEY, case_id TEXT UNIQUE NOT NULL, user_id TEXT NOT NULL,
                created_at TEXT NOT NULL, payload TEXT NOT NULL);
        ''')
        catalog = json.loads((root / 'catalog.json').read_text())
        with db:
            db.executemany('INSERT OR IGNORE INTO products VALUES (:model,:price_cents,:stock)',
                           catalog['products'])
        return db

    def _schedule(self) -> list[str]:
        today = datetime.now(TZ).date()
        return [(today + timedelta(days=n)).isoformat() for n in (1, 2, 3)]

    def _addresses(self, user_id: str) -> list[dict]:
        with closing(self._db()) as db:
            rows = db.execute('SELECT id,recipient,phone,region,detail,label,is_default FROM addresses '
                              'WHERE user_id=? ORDER BY is_default DESC,created_at DESC,id', (user_id,)).fetchall()
        return [dict(row) for row in rows]

    def _save_address(self, user_id: str, draft: dict) -> str:
        fields = {}
        for name, limit in [('recipient', 80), ('phone', 40), ('region', 160), ('detail', 300), ('label', 40)]:
            value = str(draft.get(name) or '').strip()
            if len(value) > limit or (name in ('recipient', 'region', 'detail') and not value):
                raise ValueError('请检查收件人、所在地区和详细地址是否完整，且未超过字数限制。')
            fields[name] = value
        address_id = draft.get('id') or 'ADDR-' + uuid4().hex[:12].upper()
        with closing(self._db()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT * FROM addresses WHERE id=? AND user_id=?', (address_id, user_id)).fetchone()
            if draft.get('id') and not old:
                raise ValueError('该地址不存在，请重新选择。')
            count = db.execute('SELECT count(*) FROM addresses WHERE user_id=?', (user_id,)).fetchone()[0]
            is_default = int(bool(draft.get('is_default')) or count == 0)
            if is_default:
                db.execute('UPDATE addresses SET is_default=0 WHERE user_id=?', (user_id,))
            created = old['created_at'] if old else datetime.now(TZ).isoformat(timespec='microseconds')
            db.execute('INSERT INTO addresses VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                       'recipient=excluded.recipient,phone=excluded.phone,region=excluded.region,'
                       'detail=excluded.detail,label=excluded.label,is_default=excluded.is_default',
                       (address_id, user_id, fields['recipient'], fields['phone'], fields['region'],
                        fields['detail'], fields['label'], is_default, created))
            # Keep a usable default if the only default was unchecked while editing.
            if not db.execute('SELECT 1 FROM addresses WHERE user_id=? AND is_default=1', (user_id,)).fetchone():
                db.execute('UPDATE addresses SET is_default=1 WHERE id=? AND user_id=?', (address_id, user_id))
        return address_id

    def _set_default_address(self, user_id: str, address_id: str) -> None:
        with closing(self._db()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM addresses WHERE id=? AND user_id=?',
                              (address_id, user_id)).fetchone():
                raise ValueError('该地址不存在，请刷新后重试。')
            db.execute('UPDATE addresses SET is_default=(id=?) WHERE user_id=?', (address_id, user_id))

    def _delete_address(self, user_id: str, address_id: str) -> None:
        with closing(self._db()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT is_default FROM addresses WHERE id=? AND user_id=?',
                             (address_id, user_id)).fetchone()
            if not row:
                raise ValueError('该地址不存在，请刷新后重试。')
            db.execute('DELETE FROM addresses WHERE id=? AND user_id=?', (address_id, user_id))
            if row['is_default']:
                replacement = db.execute('SELECT id FROM addresses WHERE user_id=? '
                                         'ORDER BY created_at DESC,id LIMIT 1', (user_id,)).fetchone()
                if replacement:
                    db.execute('UPDATE addresses SET is_default=1 WHERE id=? AND user_id=?',
                               (replacement['id'], user_id))
            # Orders and tickets keep their original address snapshots.

    async def _manage_address(self, action: str, address_id: str, user_id: str,
                              event_call: Callable) -> dict:
        try:
            addresses = self._addresses(user_id)
            address = next((a for a in addresses if a['id'] == address_id), None)
            if action != '新增' and not address:
                raise ValueError('该地址不存在，请刷新后重试。')
            if action == '设为默认':
                self._set_default_address(user_id, address_id)
                return {'status': '已设为默认', 'address_id': address_id}
            if action == '删除':
                message = (f'{address["recipient"]}\n{address["region"]} {address["detail"]}'
                           '\n\n删除后，下单和报修时不再显示此地址。已有订单和预约的地址保持不变。')
                if address['is_default'] and len(addresses) > 1:
                    message += '\n将自动把最近添加的其他地址设为默认。'
                confirmed = await event_call({'type': 'confirmation', 'data': {
                    'title': '删除地址', 'message': message}})
                if confirmed is not True:
                    return {'status': '未提交'}
                self._delete_address(user_id, address_id)
                return {'status': '已删除', 'address_id': address_id}
            if action not in ('新增', '修改'):
                raise ValueError('不支持的地址操作。')
            code = (Path(self.valves.DATA_DIR) / 'address_dialog.js').read_text()
            draft, notice = address or {}, ''
            while True:
                payload = {'addresses': addresses, 'draft': draft, 'editor_only': True, 'notice': notice}
                result = await event_call({'type': 'execute', 'data': {
                    'code': 'const addressData = ' + json.dumps(payload, ensure_ascii=False) + ';\n' + code}})
                if not isinstance(result, dict) or result.get('action') == 'cancel':
                    return {'status': '未提交'}
                if result.get('error'):
                    raise ValueError(str(result['error']))
                if result.get('action') != 'save' or not isinstance(result.get('address'), dict):
                    raise ValueError('地址表单没有返回完整数据，请重新打开。')
                # The clicked row, not a browser-supplied draft ID, determines the edit target.
                draft = result['address'] | {'id': address_id if action == '修改' else None}
                try:
                    saved_id = self._save_address(user_id, draft)
                    return {'status': '已保存', 'address_id': saved_id}
                except ValueError as error:
                    if action == '修改' and not any(a['id'] == address_id for a in self._addresses(user_id)):
                        raise
                    notice = str(error)
        except ValueError as error:
            return {'error': str(error)}

    async def _choose_address(self, user_id: str, event_call: Callable, preferred_id: str = '',
                              title: str = '选择收货地址') -> dict | None:
        notice, selected_id, draft = '', preferred_id, None
        code = (Path(self.valves.DATA_DIR) / 'address_dialog.js').read_text()
        while True:
            addresses = self._addresses(user_id)
            payload = {'addresses': addresses, 'notice': notice, 'selected_id': selected_id, 'draft': draft,
                       'title': title}
            result = await event_call({'type': 'execute', 'data': {
                'code': 'const addressData = ' + json.dumps(payload, ensure_ascii=False) + ';\n' + code,
            }})
            if not isinstance(result, dict) or result.get('action') == 'cancel':
                return None
            if result.get('error'):
                raise ValueError(str(result['error']))
            if result.get('action') == 'save':
                draft = result.get('address')
                if not isinstance(draft, dict):
                    raise ValueError('地址表单没有返回完整数据，请重新打开。')
                try:
                    selected_id = self._save_address(user_id, draft)
                    notice, draft = '地址已保存，请选择本次使用的地址。', None
                except ValueError as error:
                    notice = str(error)
                continue
            if result.get('action') == 'select':
                address = next((a for a in self._addresses(user_id) if a['id'] == result.get('id')), None)
                if address:
                    return address
            raise ValueError('未找到所选地址，请重新选择。')

    async def manage_shipping_addresses(
        self, __user__: dict = None, __metadata__: dict = None,
        __event_call__: Callable[[dict], Awaitable[object]] = None,
    ) -> dict:
        """打开收货地址表单和地址簿，用户可新增多个地址、编辑、设默认和选择。地址由用户在表单填写，无需在聊天里逐项追问。此工具不下单。"""
        if not (__user__ or {}).get('id') or not (__metadata__ or {}).get('session_id') or not __event_call__:
            return {'error': '请在Open WebUI页面打开收货地址表单。'}
        try:
            address = await self._choose_address(__user__['id'], __event_call__)
        except ValueError as error:
            return {'error': str(error)}
        if not address:
            return {'status': '已关闭地址窗口', 'message': '已经点击保存的地址仍会保留，未创建订单。'}
        return {'status': '已选择收货地址', 'address_id': address['id'], 'label': address['label'],
                'saved_address_count': len(self._addresses(__user__['id'])),
                'message': '地址已保存，下单时可再次选择；无需在聊天中重复输入收件信息。'}

    async def get_demo_offers(self, model: str = '') -> dict:
        """查询报价、可售库存、配送日期时段和服务选项。空型号返回全部可报价型号；不提供技术参数，参数须查云知识库。
        :param model: 完整型号，留空列出所有商品。
        """
        with closing(self._db()) as db:
            rows = db.execute('SELECT * FROM products WHERE (? = \'\' OR model = ?) ORDER BY price_cents',
                              (model.strip().upper(), model.strip().upper())).fetchall()
        if not model.strip():
            active = {p['model'] for p in json.loads((Path(self.valves.DATA_DIR) / 'catalog.json').read_text())['products']
                      if p.get('active', True)}
            rows = [r for r in rows if r['model'] in active]
        return {'demo': True, 'notice': NOTICE, 'currency': 'CNY',
                'offers': [{'model': r['model'], 'price_yuan': r['price_cents'] / 100,
                            'stock': r['stock']} for r in rows],
                'delivery_dates': self._schedule(), 'delivery_slots': list(SLOTS),
                'service_options': list(SERVICES), 'delivery_fee_yuan': 0,
                'basic_installation_fee_yuan': 0,
                'installation_note': '基础安装；特殊辅材未报价，安装条件仍须核对说明书。'}

    @staticmethod
    def _comparison_specs(p: dict) -> dict[str, str]:
        """One set of category-specific rows for shop and conversational cards."""
        category = p.get('category', '洗衣机')
        rows = {'产品类型': p['type']}
        if category == '空调':
            rows.update({'匹数': f'{p["horsepower"]:g} 匹',
                         '额定制冷量': f'{p["cooling_w"]} W',
                         '额定制热量': f'{p["heating_w"]} W',
                         '制冷输入功率': f'{p["cooling_input_w"]} W',
                         '循环风量': f'{p["airflow_m3h"]} m³/h'})
        elif category == '冰箱':
            rows.update({'总容积': f'{p["total_l"]} L', '冷藏室': f'{p["fridge_l"]} L',
                         '冷冻室': f'{p["freezer_l"]} L', '变温区': f'{p["variable_l"]} L',
                         '制冷方式': p['cooling_method'], '压缩机': p['compressor']})
        else:
            rows.update({'洗涤容量': f'{p["wash_kg"]} kg',
                         '烘干容量': f'{p["dry_kg"]} kg' if p['dry_kg'] else '不支持',
                         '烘干方式': p['drying'], '自动投放': '支持' if p['auto_dose'] else '不支持'})
        rows['室内机宽×高×深' if category == '空调' else '机身宽×高×深'] = (
            f'{p["width_mm"]} × {p["height_mm"]} × {p["depth_mm"]} mm')
        if category == '空调':
            rows['室外机宽×高×深'] = ' × '.join(map(str, p['outdoor_dimensions_mm'])) + ' mm'
        if 'installation_mm' in p:
            rows['预留空间（宽×高×深）'] = ' × '.join(map(str, p['installation_mm'])) + ' mm'
        if p.get('installation_note'):
            rows['安装条件'] = p['installation_note']
        rows['Wi-Fi'] = '支持' if p['wifi'] else '不支持'
        rows['注意事项'] = p['tradeoff']
        return rows

    def _product_catalog(self) -> list[dict]:
        catalog = json.loads((Path(self.valves.DATA_DIR) / 'product-catalog.json').read_text())
        with closing(self._db()) as db:
            offers = {r['model']: dict(r) for r in db.execute('SELECT * FROM products')}
        return [p | {'comparison_specs': self._comparison_specs(p),
                     'category': p.get('category', '洗衣机'),
                     'price_yuan': offers[p['model']]['price_cents'] / 100,
                     'stock': offers[p['model']]['stock'], 'fictional': True,
                     'spec_url': f'http://127.0.0.1:3000/static/jiadian/docs/{p["model"]}-spec.html',
                     'manual_url': f'http://127.0.0.1:3000/static/jiadian/docs/{p["model"]}-manual.html'}
                for p in catalog['products']]

    async def search_demo_products(
        self, max_price_yuan: float = 0, min_capacity_kg: float = 0,
        requires_drying: bool = False, product_type: str = '', max_depth_mm: int = 0,
        category: str = '', min_volume_l: int = 0, min_cooling_w: int = 0,
        horsepower: float = 0,
    ) -> dict:
        """查询当前虚构产品目录和当前报价，按用户明确的条件筛选，不固定推荐型号。返回完整产品参数和资料链接供推荐与卡片使用。安装、排障仍查对应型号云端说明书。
        :param max_price_yuan: 用户预算上限，0表示不限。
        :param min_capacity_kg: 最小洗涤容量，0表示不限。
        :param requires_drying: 用户明确需要烘干时设为true，否则不按烘干过滤。
        :param product_type: 留空不限；按目录中的产品类型精确筛选，如壁挂式空调、柜式空调、三门冰箱、滚筒洗衣机。
        :param max_depth_mm: 最大机身深度mm，0表示不限。不是柜体深度，不可自动等同安装余量。
        :param category: 洗衣机、空调或冰箱，留空查询全部；用户明确品类时填写。
        :param min_volume_l: 冰箱最小总容积L，0表示不限；不适用于洗涤容量。
        :param min_cooling_w: 空调最小额定制冷量W，0表示不限；不是用电功率。
        :param horsepower: 空调匹数精确筛选，如1、1.5、3，0表示不限；不能单凭面积推断匹数。
        """
        products = self._product_catalog()
        matches = [p for p in products
                   if (max_price_yuan <= 0 or p['price_yuan'] <= max_price_yuan)
                   and (not category or p['category'] == category)
                   and (min_capacity_kg <= 0 or p.get('wash_kg', 0) >= min_capacity_kg)
                   and (not requires_drying or p.get('dry_kg', 0) > 0)
                   and (min_volume_l <= 0 or p.get('total_l', 0) >= min_volume_l)
                   and (min_cooling_w <= 0 or p.get('cooling_w', 0) >= min_cooling_w)
                   and (horsepower <= 0 or p.get('horsepower', 0) == horsepower)
                   and (not product_type or p['type'] == product_type)
                   and (max_depth_mm <= 0 or p['depth_mm'] <= max_depth_mm)]
        return {'demo': True, 'notice': '产品图片由 AI 生成，资料来源见产品说明。',
                'products': matches, 'total_matches': len(matches),
                'next_step': '依据需求和返回参数生成推荐理由，调用show_product_cards展示匹配型号；没有匹配时说明哪些条件需调整，不擅自放宽预算。'}

    async def show_product_cards(
        self, models: list[str], reasons: list[str] = None,
        __metadata__: dict = None,
        __event_call__: Callable[[dict], Awaitable[object]] = None,
    ) -> tuple | dict:
        """在聊天内展示带生成图片的产品卡片，用户可勾选2至3款对比、查看资料、选择型号继续订购。不会创建订单。型号必须先从search_demo_products查询；不要重复渲染同一轮结果。
        :param models: 要展示的准确型号列表，按本次需求排序；不接受不存在的型号。
        :param reasons: 与型号顺序一致的简短推荐理由，基于查询事实和用户本次需求，不可杜撰卖点。
        """
        catalog = {p['model']: p for p in self._product_catalog()}
        selected = list(dict.fromkeys(m.strip().upper() for m in models))
        if not selected or any(m not in catalog for m in selected):
            return {'error': '请先查询产品目录，传入其中存在的型号。'}
        products = [catalog[m] | {'reason': (reasons or [])[i] if i < len(reasons or []) else '',
                                  'image_url': f'http://127.0.0.1:3000/static/jiadian/products/{m}.png'}
                    for i, m in enumerate(selected)]
        theme = {}
        if __event_call__ and (__metadata__ or {}).get('session_id'):
            theme = await __event_call__({'type': 'execute', 'data': {'code': '''
const dark = document.documentElement.classList.contains('dark');
const style = getComputedStyle(document.body);
return {dark, font: style.fontFamily};
'''}})
            if not isinstance(theme, dict):
                theme = {}
        payload = json.dumps({'products': products, 'theme': theme}, ensure_ascii=False).replace('<', '\\u003c')
        template = (Path(self.valves.DATA_DIR) / 'product_cards.html').read_text()
        content = template.replace('/*PRODUCT_DATA*/{}', payload)
        return (HTMLResponse(content=content, headers={'Content-Disposition': 'inline'}),
                {'status': '卡片已展示', 'models': selected, 'demo': True,
                 'message': '图片卡片和勾选对比已显示在聊天内。接下来仅用一至两句提出选择建议或关键追问，不重复Markdown表格、型号参数和价格清单，也不称为右侧卡片。用户选择型号后继续订购；当前未创建订单。'})

    async def place_demo_order(
        self, model: str, quantity: int,
        delivery_date: str, delivery_slot: str, service: str,
        __user__: dict = None, __metadata__: dict = None,
        __event_call__: Callable[[dict], Awaitable[object]] = None,
    ) -> dict:
        """用户明确订购并选好型号、数量、日期时段及服务后调用。自动打开收货地址选择窗口（支持新增表单），再展示订单确认弹窗。不要在聊天中追问地址或姓名。只有点击最终确认才创建订单并扣减库存。取消不下单。不收款、不真实发货。
        :param model: 通过工具查到的完整型号。
        :param quantity: 购买台数，正整数。
        :param delivery_date: get_demo_offers返回的可用日期，YYYY-MM-DD。
        :param delivery_slot: get_demo_offers返回的配送时段。
        :param service: 送装一体或仅配送，必须是用户选择。
        """
        user_id = (__user__ or {}).get('id')
        metadata = __metadata__ or {}
        if not user_id or not metadata.get('session_id') or not __event_call__:
            return {'error': '请在Open WebUI页面下单，需要用户点击订单确认弹窗。', 'demo': True}
        if type(quantity) is not int or quantity < 1:
            return {'error': '购买数量必须是正整数。'}
        if delivery_date not in self._schedule() or delivery_slot not in SLOTS or service not in SERVICES:
            return {'error': '配送日期、时段或服务选项无效，请重新查询报价工具。'}
        model = model.strip().upper()
        request_key = hashlib.sha256(json.dumps([
            user_id, metadata.get('chat_id'), metadata.get('message_id'), model, quantity,
            delivery_date, delivery_slot, service,
        ], ensure_ascii=False).encode()).hexdigest()
        with closing(self._db()) as db:
            old = db.execute('SELECT payload FROM orders WHERE request_key=?', (request_key,)).fetchone()
            if old:
                return {'demo': True, 'already_created': True, 'order': json.loads(old['payload'])}
            product = db.execute('SELECT * FROM products WHERE model=?', (model,)).fetchone()
        if not product:
            return {'error': '此型号尚无报价，不能订购。', 'demo': True}
        if product['stock'] < quantity:
            return {'error': '库存不足，请调整数量或选择其他型号。', 'stock': product['stock'], 'demo': True}
        try:
            address = await self._choose_address(user_id, __event_call__)
        except ValueError as error:
            return {'error': str(error), 'demo': True}
        if not address:
            return {'demo': True, 'status': '已取消', 'message': '未选择收货地址，未创建订单，库存未扣减。'}
        recipient = address['recipient']
        delivery_address = address['region'] + ' ' + address['detail']
        total = product['price_cents'] * quantity
        order = {'model': model, 'quantity': quantity, 'unit_price_yuan': product['price_cents'] / 100,
                 'total_yuan': total / 100, 'currency': 'CNY', 'recipient': recipient.strip(),
                 'delivery_address': delivery_address.strip(), 'delivery_date': delivery_date,
                 'delivery_slot': delivery_slot, 'service': service, 'delivery_fee_yuan': 0,
                 'basic_installation_fee_yuan': 0, 'status': '已确认，待配送',
                 'payment_status': '无需支付', 'notice': NOTICE,
                 'address_id': address['id'], 'shipping_address': address}
        summary = (f'型号：{model}\n数量：{quantity} 台\n单价：¥{product["price_cents"] / 100:.2f}'
                   f'\n合计：¥{total / 100:.2f}\n收件人：{recipient}\n联系电话：{address["phone"] or "未填写"}\n地点：{delivery_address}'
                   f'\n配送：{delivery_date} {delivery_slot}\n服务：{service}'
                   '\n配送及基础安装费：¥0（特殊辅材另议）\n\n' + NOTICE)
        confirmed = await __event_call__({'type': 'confirmation', 'data': {
            'title': '确认订单', 'message': summary,
        }})
        if confirmed is not True:
            return {'demo': True, 'status': '已取消', 'message': '未创建订单，库存未扣减。'}
        with closing(self._db()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT payload FROM orders WHERE request_key=?', (request_key,)).fetchone()
            if old:
                return {'demo': True, 'already_created': True, 'order': json.loads(old['payload'])}
            changed = db.execute('UPDATE products SET stock=stock-? WHERE model=? AND stock>=? AND price_cents=?',
                                 (quantity, model, quantity, product['price_cents'])).rowcount
            if not changed:
                return {'demo': True, 'error': '确认期间库存或报价发生变化，未下单，请重新查询。'}
            order['order_id'] = 'DEMO-' + uuid4().hex[:12].upper()
            order['created_at'] = datetime.now(TZ).isoformat(timespec='seconds')
            db.execute('INSERT INTO orders VALUES (?,?,?,?,?)',
                       (order['order_id'], user_id, request_key, order['created_at'],
                        json.dumps(order, ensure_ascii=False)))
        return {'demo': True, 'order': order}

    async def get_demo_orders(self, order_id: str = '', __user__: dict = None) -> dict:
        """查询当前用户的持久化订单，可跨对话使用。售后识别家电请调用select_service_appliance弹窗由用户选择；不代表真实付款配送。空订单号返回最近10笔。
        :param order_id: 返回工具生成的完整DEMO订单号；不知道时留空。
        """
        user_id = (__user__ or {}).get('id')
        if not user_id:
            return {'error': '缺少当前用户身份。'}
        with closing(self._db()) as db:
            rows = db.execute('SELECT payload FROM orders WHERE user_id=? AND (?=\'\' OR id=?) ORDER BY created_at DESC LIMIT 10',
                              (user_id, order_id.strip().upper(), order_id.strip().upper())).fetchall()
        return {'demo': True, 'notice': NOTICE, 'orders': [json.loads(r['payload']) for r in rows]}

    async def _management_record(self, table: str, user_id: str, record_id: str,
                                 title: str, event_call: Callable) -> dict | None:
        # Table names are internal constants; identifiers and ownership remain bound parameters.
        with closing(self._db()) as db:
            rows = db.execute(f'SELECT id,payload FROM {table} WHERE user_id=? '
                              "AND (?='' OR id=?) ORDER BY created_at DESC",
                              (user_id, record_id, record_id)).fetchall()
        records = {r['id']: json.loads(r['payload']) for r in rows}
        if record_id:
            if record_id not in records:
                raise ValueError('未找到属于当前用户的记录，请重新查询。')
            return records[record_id]
        if not records:
            raise ValueError('当前没有可选择的记录。')
        choices = []
        for key, item in records.items():
            appointment = item.get('appointment', {})
            date = item.get('delivery_date', appointment.get('date', ''))
            slot = item.get('delivery_slot', appointment.get('slot', ''))
            choices.append({'id': key, 'title': item['model'],
                            'lines': [key, item['status'], f'{date} {slot}']})
        result = await self._service_dialog({'mode': 'record-select', 'title': title,
                                             'records': choices}, event_call)
        if result.get('action') != 'record-select':
            return None
        if result.get('id') not in records:
            raise ValueError('所选记录无效，请重新选择。')
        return records[result['id']]

    @staticmethod
    def _linked_tickets(db: sqlite3.Connection, user_id: str, order_id: str) -> list[dict]:
        tickets = [json.loads(r['payload']) for r in db.execute(
            'SELECT payload FROM service_tickets WHERE user_id=? ORDER BY id', (user_id,))]
        return [t for t in tickets if t.get('order_id') == order_id and t['status'] != '已取消']

    async def manage_order(
        self, action: str = '修改', order_id: str = '', __user__: dict = None,
        __metadata__: dict = None, __event_call__: Callable[[dict], Awaitable[object]] = None,
    ) -> dict:
        """修改或取消已创建订单。没有明确订单号时留空，弹出记录选择，不猜最近一单。修改表单支持数量、配送日期时段、服务和地址；型号固定，沿用原单价。取消订单回补库存并在确认中列出一并取消的待受理报修。最终确认后才写入，关闭窗口不改订单。仅办理待配送订单，不退款、不实际发货。
        :param action: 修改或取消，必须来自用户明确意图。
        :param order_id: 用户明确指定或已查询确认的完整订单号；不明确时留空让用户选择。
        """
        user_id = (__user__ or {}).get('id')
        if not user_id or not (__metadata__ or {}).get('session_id') or not __event_call__:
            return {'error': '请在Open WebUI页面办理订单修改或取消。'}
        if action not in ('修改', '取消'):
            return {'error': '请选择修改或取消。'}
        try:
            order = await self._management_record('orders', user_id, order_id.strip().upper(),
                                                   f'选择要{action}的订单', __event_call__)
            if order is None:
                return {'status': '未提交', 'message': '未修改订单。'}
            if order['status'] == '已取消':
                return {'status': '已取消', 'already_cancelled': True, 'order': order,
                        'message': '订单已取消，未再次回补库存。'}
            if order['status'] != '已确认，待配送':
                return {'error': '当前仅支持修改或取消待配送订单。'}
            with closing(self._db()) as db:
                linked = self._linked_tickets(db, user_id, order['order_id'])
            updated = dict(order)
            if action == '修改':
                form = await self._service_dialog({'mode': 'order-edit', 'model': order['model'],
                    'dates': self._schedule(), 'slots': list(SLOTS), 'services': list(SERVICES),
                    'draft': {'quantity': order['quantity'], 'date': order['delivery_date'],
                              'slot': order['delivery_slot'], 'service': order['service']}}, __event_call__)
                if form.get('action') != 'order-edit':
                    return {'status': '未提交', 'message': '未修改订单。'}
                quantity = form.get('quantity')
                if (type(quantity) is not int or quantity < 1 or form.get('date') not in self._schedule()
                        or form.get('slot') not in SLOTS or form.get('service') not in SERVICES):
                    return {'error': '数量、配送日期、时段或服务无效。'}
                address = await self._choose_address(user_id, __event_call__, order.get('address_id', ''))
                if not address:
                    return {'status': '未提交', 'message': '未选择地址，未修改订单。'}
                updated.update(quantity=quantity, total_yuan=round(order['unit_price_yuan'] * quantity, 2),
                    delivery_date=form['date'], delivery_slot=form['slot'], service=form['service'],
                    address_id=address['id'], shipping_address=address, recipient=address['recipient'],
                    delivery_address=address['region'] + ' ' + address['detail'])
                summary = (f'订单：{order["order_id"]}\n型号：{order["model"]}'
                    f'\n数量：{order["quantity"]} → {quantity} 台'
                    f'\n合计：¥{order["total_yuan"]:.2f} → ¥{updated["total_yuan"]:.2f}（沿用原单价）'
                    f'\n配送：{order["delivery_date"]} {order["delivery_slot"]} → {form["date"]} {form["slot"]}'
                    f'\n服务：{order["service"]} → {form["service"]}'
                    f'\n收件人：{updated["recipient"]}\n电话：{address["phone"] or "未填写"}'
                    f'\n原地址：{order["delivery_address"]}\n新地址：{updated["delivery_address"]}'
                    '\n已提交报修的预约时间和地址保持原记录。\n' + NOTICE)
            else:
                if any(t['status'] != '待受理' for t in linked):
                    return {'error': '关联报修已进入处理，请先联系服务方确认，暂不能直接取消订单。'}
                summary = (f'订单：{order["order_id"]}\n型号：{order["model"]}\n数量：{order["quantity"]} 台'
                           f'\n取消后回补库存 {order["quantity"]} 台。')
                if linked:
                    summary += '\n以下待受理报修将一并取消：\n' + '\n'.join(t['ticket_id'] for t in linked)
                summary += '\n订单记录保留。当前没有实际收款，无需退款。'
            confirmed = await __event_call__({'type': 'confirmation', 'data': {
                'title': f'确认{action}订单', 'message': summary}})
            if confirmed is not True:
                return {'status': '未提交', 'message': '订单及报修记录均未改变。'}
            now = datetime.now(TZ).isoformat(timespec='microseconds')
            with closing(self._db()) as db, db:
                db.execute('BEGIN IMMEDIATE')
                current = db.execute('SELECT payload FROM orders WHERE id=? AND user_id=?',
                                     (order['order_id'], user_id)).fetchone()
                if not current or json.loads(current['payload']) != order:
                    return {'error': '订单在确认期间已变化，请重新打开。'}
                updated['updated_at'] = now
                if action == '取消':
                    if self._linked_tickets(db, user_id, order['order_id']) != linked:
                        return {'error': '关联报修在确认期间已变化，请重新确认。'}
                    updated.update(status='已取消', cancelled_at=now)
                    delta = -order['quantity']
                    for ticket in linked:
                        ticket.update(status='已取消', cancelled_at=now, updated_at=now, cancellation_reason='订单取消')
                        db.execute('UPDATE service_tickets SET payload=? WHERE id=? AND user_id=?',
                                   (json.dumps(ticket, ensure_ascii=False), ticket['ticket_id'], user_id))
                    for row in db.execute('SELECT id,payload FROM service_cases WHERE user_id=?', (user_id,)).fetchall():
                        case = json.loads(row['payload'])
                        if case.get('order_id') == order['order_id']:
                            case.update(order_snapshot=updated, stage='订单已取消', updated_at=now)
                            db.execute('UPDATE service_cases SET payload=? WHERE id=? AND user_id=?',
                                       (json.dumps(case, ensure_ascii=False), row['id'], user_id))
                else:
                    delta = updated['quantity'] - order['quantity']
                changed = db.execute('UPDATE products SET stock=stock-? WHERE model=? AND stock>=?',
                                     (delta, order['model'], max(delta, 0))).rowcount
                if not changed:
                    db.rollback()
                    return {'error': '库存不足或商品已变化，订单未修改，请调整数量。'}
                db.execute('UPDATE orders SET payload=? WHERE id=? AND user_id=?',
                           (json.dumps(updated, ensure_ascii=False), order['order_id'], user_id))
            return {'status': '已修改' if action == '修改' else '已取消', 'order': updated,
                    'cancelled_ticket_ids': [t['ticket_id'] for t in linked] if action == '取消' else []}
        except ValueError as error:
            return {'error': str(error)}

    async def manage_service_ticket(
        self, action: str = '修改', ticket_id: str = '', __user__: dict = None,
        __metadata__: dict = None, __event_call__: Callable[[dict], Awaitable[object]] = None,
    ) -> dict:
        """修改或取消待受理报修预约。工单号不明确时留空，弹出记录选择；不猜最新一单。复用预约表单及地址选择，最终确认后更新原工单，保留型号与订单关联。取消保留记录，不改变订单或库存；已取消的预约不能直接恢复，若重新报修须用户明确提出并重新选择机器。
        :param action: 修改或取消，必须来自用户明确意图。
        :param ticket_id: 用户明确指定或已查询确认的SRV工单号；不明确时留空让用户选择。
        """
        user_id = (__user__ or {}).get('id')
        if not user_id or not (__metadata__ or {}).get('session_id') or not __event_call__:
            return {'error': '请在Open WebUI页面办理预约修改或取消。'}
        if action not in ('修改', '取消'):
            return {'error': '请选择修改或取消。'}
        try:
            ticket = await self._management_record('service_tickets', user_id, ticket_id.strip().upper(),
                                                    f'选择要{action}的报修预约', __event_call__)
            if ticket is None:
                return {'status': '未提交', 'message': '未修改报修预约。'}
            if ticket['status'] == '已取消':
                return {'status': '已取消', 'already_cancelled': True, 'ticket': ticket}
            if ticket['status'] != '待受理':
                return {'error': '当前仅支持修改或取消待受理预约，请联系服务方处理。'}
            updated = dict(ticket)
            if action == '修改':
                form = await self._service_dialog({'mode': 'appointment', 'title': '修改报修预约',
                    'model': ticket['model'], 'issue': ticket['issue'], 'draft': ticket['appointment'],
                    'dates': self._schedule(), 'slots': list(SLOTS)}, __event_call__)
                if form.get('action') != 'appointment':
                    return {'status': '未提交', 'message': '未修改报修预约。'}
                issue = str(form.get('issue') or '').strip()
                if not issue or len(issue) > 2000 or form.get('date') not in self._schedule() or form.get('slot') not in SLOTS:
                    return {'error': '故障描述或预约时间无效。'}
                address = await self._choose_address(user_id, __event_call__, ticket['address']['id'], '选择上门地址')
                if not address:
                    return {'status': '未提交', 'message': '未选择地址，报修预约未改变。'}
                updated.update(issue=issue, appointment={'date': form['date'], 'slot': form['slot']}, address=address)
            old_time = ticket['appointment']['date'] + ' ' + ticket['appointment']['slot']
            summary = f'工单：{ticket["ticket_id"]}\n型号：{ticket["model"]}\n原预约：{old_time}'
            if action == '修改':
                address = updated['address']
                summary += (f'\n新预约：{updated["appointment"]["date"]} {updated["appointment"]["slot"]}'
                    f'\n故障描述：{updated["issue"]}\n联系人：{address["recipient"]}\n电话：{address["phone"] or "未填写"}'
                    f'\n原地址：{ticket["address"]["region"]} {ticket["address"]["detail"]}'
                    f'\n新地址：{address["region"]} {address["detail"]}\n修改后仍为待受理，不代表已安排工程师。')
            else:
                summary += '\n取消本次报修预约，保留工单记录。购买订单和库存不变。'
            confirmed = await __event_call__({'type': 'confirmation', 'data': {
                'title': f'确认{action}报修预约', 'message': summary}})
            if confirmed is not True:
                return {'status': '未提交', 'message': '原报修预约未改变。'}
            now = datetime.now(TZ).isoformat(timespec='microseconds')
            with closing(self._db()) as db, db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT payload FROM service_tickets WHERE id=? AND user_id=?',
                                 (ticket['ticket_id'], user_id)).fetchone()
                if not row or json.loads(row['payload']) != ticket:
                    return {'error': '工单在确认期间已变化，请重新打开。'}
                updated['updated_at'] = now
                if action == '取消':
                    updated.update(status='已取消', cancelled_at=now, cancellation_reason='用户取消预约')
                db.execute('UPDATE service_tickets SET payload=? WHERE id=? AND user_id=?',
                           (json.dumps(updated, ensure_ascii=False), ticket['ticket_id'], user_id))
                row = db.execute('SELECT payload FROM service_cases WHERE id=? AND user_id=?',
                                 (ticket['case_id'], user_id)).fetchone()
                case = json.loads(row['payload'])
                case.update(issue=updated['issue'], appointment=updated['appointment'], updated_at=now,
                            stage='已取消报修' if action == '取消' else '已提交报修')
                db.execute('UPDATE service_cases SET payload=? WHERE id=? AND user_id=?',
                           (json.dumps(case, ensure_ascii=False), ticket['case_id'], user_id))
            return {'status': '已修改' if action == '修改' else '已取消', 'ticket': updated}
        except ValueError as error:
            return {'error': str(error)}

    def _service_case(self, user_id: str, case_id: str) -> dict | None:
        with closing(self._db()) as db:
            row = db.execute('SELECT payload FROM service_cases WHERE id=? AND user_id=?',
                             (case_id, user_id)).fetchone()
        return json.loads(row['payload']) if row else None

    async def _service_dialog(self, payload: dict, event_call: Callable) -> dict:
        code = (Path(self.valves.DATA_DIR) / 'service_dialog.js').read_text()
        result = await event_call({'type': 'execute', 'data': {
            'code': 'const serviceData = ' + json.dumps(payload, ensure_ascii=False) + ';\n' + code,
        }})
        if not isinstance(result, dict):
            return {'action': 'cancel'}
        if result.get('error'):
            raise ValueError(str(result['error']))
        return result

    async def select_service_appliance(
        self, issue: str = '', __user__: dict = None, __metadata__: dict = None,
        __event_call__: Callable[[dict], Awaitable[object]] = None,
        __event_emitter__: Callable[[dict], Awaitable[object]] = None,
    ) -> dict:
        """已购家电的首次使用、日常指导或故障咨询都先调用本工具，弹出订单卡片，让用户明确选择机器并确认咨询内容。不能仅查询最新订单代替用户选择，只有一笔订单也必须选择。当前对话已在弹窗确认同一机器后可沿用case_id。支持其他渠道购买手填型号。保存独立售后记录，返回case_id和用户确认的model，随后按此型号查询云端说明书。不创建报修工单。不允许用记忆猜测型号。
        :param issue: 用户已经说出的使用问题或故障描述，可预填；未说明就留空，由用户在弹窗填写。
        """
        user_id = (__user__ or {}).get('id')
        if not user_id or not (__metadata__ or {}).get('session_id') or not __event_call__:
            return {'error': '请在Open WebUI页面选择需要售后的家电。'}
        with closing(self._db()) as db:
            orders = [json.loads(r['payload']) for r in db.execute(
                'SELECT payload FROM orders WHERE user_id=? ORDER BY created_at DESC', (user_id,))]
        orders = [o for o in orders if o['status'] != '已取消']
        cards = [{k: o.get(k, '') for k in ('order_id', 'model', 'quantity', 'created_at',
                                           'delivery_address', 'status')} for o in orders]
        try:
            choice = await self._service_dialog({'mode': 'select', 'orders': cards, 'issue': issue}, __event_call__)
        except ValueError as error:
            return {'error': str(error)}
        if choice.get('action') != 'select':
            return {'status': '已取消', 'message': '没有选择家电，未创建售后记录或报修工单。'}
        selected = next((o for o in orders if o['order_id'] == choice.get('order_id')), None)
        if choice.get('source') == 'order' and selected:
            appliance = {'source': 'order', 'order_id': selected['order_id'], 'model': selected['model'],
                         'order_snapshot': selected}
        elif choice.get('source') == 'external':
            model = str(choice.get('model') or '').strip().upper()
            if not model or len(model) > 100:
                return {'error': '请填写机身铭牌上的完整型号，暂不能确定型号时不要猜测。'}
            appliance = {'source': 'external', 'order_id': None, 'model': model, 'order_snapshot': None}
        else:
            return {'error': '所选订单不存在或不属于当前用户，请重新选择。'}
        fault = str(choice.get('issue') or '').strip()
        if not fault or len(fault) > 2000:
            return {'error': '请填写使用问题或故障现象（最多2000字）。'}
        case = {'case_id': 'CASE-' + uuid4().hex[:12].upper(), **appliance, 'issue': fault,
                'stage': '待排查', 'created_at': datetime.now(TZ).isoformat(timespec='seconds'),
                'selection_confirmed_by_user': True, 'demo': True}
        with closing(self._db()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            if case['order_id']:
                current = db.execute('SELECT payload FROM orders WHERE id=? AND user_id=?',
                                     (case['order_id'], user_id)).fetchone()
                if not current or json.loads(current['payload'])['status'] == '已取消':
                    return {'error': '该订单已取消，请重新选择家电。'}
                case['order_snapshot'] = json.loads(current['payload'])
            db.execute('INSERT INTO service_cases VALUES (?,?,?,?)',
                       (case['case_id'], user_id, case['created_at'], json.dumps(case, ensure_ascii=False)))
        if __event_emitter__:
            await __event_emitter__({'type': 'status', 'data': {
                'description': '已保存用户选择的家电：' + case['model'], 'done': True}})
        # Avoid sending address/recipient to the model when diagnosing a fault.
        return {'case': {k: v for k, v in case.items() if k != 'order_snapshot'},
                'next_step': '按用户确认的model及issue检索对应型号说明书；虚构产品使用使用说明书，不称为品牌官方资料。需要报修时调用create_demo_service_ticket。',
                'notice': '已保存售后咨询记录，尚未提交报修。'}

    async def get_after_sales(self, case_id: str = '', ticket_id: str = '', __user__: dict = None) -> dict:
        """查询当前用户的售后咨询记录与工单，跨对话恢复进度，不能用记忆编造状态。用户提供SRV工单号时必须用ticket_id精确查询，只回答该单；提供CASE编号时用case_id。两者都未指定才返回最近10条，多条待办不明确时让用户选择，不自行猜测。
        :param case_id: select_service_appliance返回的CASE编号，留空列出最近记录。
        :param ticket_id: 用户指定的SRV工单号，精确查询该单；未知则留空。
        """
        user_id = (__user__ or {}).get('id')
        if not user_id:
            return {'error': '缺少当前用户身份。'}
        with closing(self._db()) as db:
            rows = db.execute('SELECT c.payload,t.payload AS ticket FROM service_cases c '
                              'LEFT JOIN service_tickets t ON c.id=t.case_id AND c.user_id=t.user_id '
                              "WHERE c.user_id=? AND (?='' OR c.id=?) AND (?='' OR t.id=?) ORDER BY c.created_at DESC LIMIT 10",
                              (user_id, case_id, case_id, ticket_id, ticket_id)).fetchall()
        cases = []
        for row in rows:
            case = json.loads(row['payload']);case.pop('order_snapshot', None)
            case['ticket'] = json.loads(row['ticket']) if row['ticket'] else None
            cases.append(case)
        return {'demo': True, 'cases': cases, 'notice': '当前不会实际派人或收费。'}

    async def create_demo_service_ticket(
        self, case_id: str, issue: str = '', __user__: dict = None, __metadata__: dict = None,
        __event_call__: Callable[[dict], Awaitable[object]] = None,
    ) -> dict:
        """用户要求报修、预约维修时调用。必须先通过select_service_appliance让用户选机器，取得case_id。工具弹出故障与预约表单、地址选择和最终确认，再创建持久化工单。不能直接传型号替代用户选择。取消保留草稿，重试不会重复提交。
        :param case_id: 用户选定家电后返回的CASE编号；跨对话可用get_after_sales查询。
        :param issue: 用户最新描述的故障和已尝试步骤，原样概括用于表单预填；不编造诊断。留空沿用已有记录，用户仍可编辑确认。
        """
        user_id = (__user__ or {}).get('id')
        if not user_id or not (__metadata__ or {}).get('session_id') or not __event_call__:
            return {'error': '请在Open WebUI页面办理报修，需要用户确认。'}
        case = self._service_case(user_id, case_id)
        if not case:
            return {'error': '未找到当前用户的售后记录，请先打开家电选择窗口。'}
        with closing(self._db()) as db:
            old = db.execute('SELECT payload FROM service_tickets WHERE case_id=? AND user_id=?',
                             (case_id, user_id)).fetchone()
            if case.get('order_id'):
                current = db.execute('SELECT payload FROM orders WHERE id=? AND user_id=?',
                                     (case['order_id'], user_id)).fetchone()
                if not current or json.loads(current['payload'])['status'] == '已取消':
                    return {'error': '关联订单已取消，不能基于该订单继续预约报修。'}
                case['order_snapshot'] = json.loads(current['payload'])
        if old:
            return {'demo': True, 'already_created': True, 'ticket': json.loads(old['payload'])}
        try:
            form = await self._service_dialog({'mode': 'appointment', 'model': case['model'],
                                               'case_id': case_id, 'issue': issue.strip() or case['issue'],
                                               'dates': self._schedule(), 'slots': list(SLOTS),
                                               'draft': case.get('appointment', {})}, __event_call__)
            if form.get('action') != 'appointment':
                return {'status': '已取消', 'case_id': case_id, 'message': '售后记录保留，未创建工单。'}
            fault = str(form.get('issue') or '').strip()
            date, slot = form.get('date'), form.get('slot')
            if not fault or len(fault) > 2000 or date not in self._schedule() or slot not in SLOTS:
                return {'error': '故障或预约日期时段无效，请重新打开表单。', 'case_id': case_id}
            case.update(issue=fault, appointment={'date': date, 'slot': slot}, stage='待确认报修')
            with closing(self._db()) as db, db:
                db.execute('BEGIN IMMEDIATE')
                if case.get('order_id'):
                    current = db.execute('SELECT payload FROM orders WHERE id=? AND user_id=?',
                                         (case['order_id'], user_id)).fetchone()
                    if not current or json.loads(current['payload'])['status'] == '已取消':
                        return {'error': '关联订单已取消，未保存报修预约。'}
                db.execute('UPDATE service_cases SET payload=? WHERE id=? AND user_id=?',
                           (json.dumps(case, ensure_ascii=False), case_id, user_id))
            preferred = (case.get('order_snapshot') or {}).get('address_id', '')
            address = await self._choose_address(user_id, __event_call__, preferred, '选择上门地址')
        except ValueError as error:
            return {'error': str(error), 'case_id': case_id}
        if not address:
            return {'status': '已取消', 'case_id': case_id, 'message': '预约草稿已保存，未提交工单；可以稍后继续。'}
        summary = (f'家电：{case["model"]}\n关联订单：{case["order_id"] or "其他渠道购买（用户填写型号）"}'
                   f'\n故障描述：{fault}\n期望上门：{date} {slot}'
                   f'\n联系人：{address["recipient"]}\n电话：{address["phone"] or "未填写"}'
                   f'\n地址：{address["region"]} {address["detail"]}'
                   '\n\n提交后为待受理，当前不会实际派人或收费，预约时段不代表已安排工程师。')
        confirmed = await __event_call__({'type': 'confirmation', 'data': {
            'title': '确认提交报修', 'message': summary}})
        if confirmed is not True:
            return {'status': '已取消', 'case_id': case_id, 'message': '预约草稿已保存，未提交工单。'}
        ticket = {'ticket_id': 'SRV-' + uuid4().hex[:12].upper(), 'case_id': case_id,
                  'order_id': case['order_id'], 'model': case['model'], 'issue': fault,
                  'appointment': {'date': date, 'slot': slot}, 'address': address,
                  'status': '待受理', 'created_at': datetime.now(TZ).isoformat(timespec='seconds'),
                  'demo': True, 'notice': '未实际派人，无费用；上门时间待受理确认。'}
        with closing(self._db()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            if case.get('order_id'):
                current = db.execute('SELECT payload FROM orders WHERE id=? AND user_id=?',
                                     (case['order_id'], user_id)).fetchone()
                if not current or json.loads(current['payload'])['status'] == '已取消':
                    return {'error': '确认期间关联订单已取消，未创建报修工单。'}
            old = db.execute('SELECT payload FROM service_tickets WHERE case_id=? AND user_id=?',
                             (case_id, user_id)).fetchone()
            if old:
                return {'demo': True, 'already_created': True, 'ticket': json.loads(old['payload'])}
            db.execute('INSERT INTO service_tickets VALUES (?,?,?,?,?)',
                       (ticket['ticket_id'], case_id, user_id, ticket['created_at'], json.dumps(ticket, ensure_ascii=False)))
            case.update(stage='已提交报修', ticket_id=ticket['ticket_id'])
            db.execute('UPDATE service_cases SET payload=? WHERE id=? AND user_id=?',
                       (json.dumps(case, ensure_ascii=False), case_id, user_id))
        return {'demo': True, 'ticket': ticket}
