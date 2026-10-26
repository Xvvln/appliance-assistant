"""Stock Open WebUI views and direct access to the existing commerce tools."""
from contextlib import closing
import asyncio
import json
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from open_webui.main import app
from open_webui.socket.main import SESSION_POOL, get_event_call
from open_webui.utils.auth import get_verified_user
from tools.demo_shop import Tools

ROOT = Path(__file__).resolve().parent
router = APIRouter(prefix='/api/v1/jiadian', dependencies=[Depends(get_verified_user)])
shop = Tools()
shop.valves.DATA_DIR = str(ROOT / 'data/webui/commerce')


@router.get('/catalog')
async def catalog():
    # Same directory, price and stock lookup used by the conversational shopping tools.
    result = await shop.search_demo_products()
    return {'products': result['products']}


@router.get('/records')
def records(user=Depends(get_verified_user)):
    # Unlike the conversational summary (latest ten), the records page shows all history.
    with closing(shop._db()) as db:
        return {key: [json.loads(row['payload']) for row in db.execute(
            f'SELECT payload FROM {table} WHERE user_id=? ORDER BY created_at DESC, id DESC',
            (user.id,))] for key, table in [('orders', 'orders'), ('tickets', 'service_tickets')]}


class PageInteractionForm(BaseModel):
    session_id: str = Field(min_length=1)
    operation_id: UUID


async def page_interaction(form: PageInteractionForm, user):
    session = SESSION_POOL.get(form.session_id)
    if not session or session.get('id') != user.id:
        raise HTTPException(403, '页面连接已断开，请刷新后重试。')
    metadata = {'user_id': user.id, 'session_id': form.session_id,
                'chat_id': f'jiadian-records:{form.operation_id}',
                'message_id': str(form.operation_id)}
    event_call = await get_event_call(metadata)

    async def interact(event):
        try:
            result = await asyncio.wait_for(event_call(event), timeout=300)
        except TimeoutError:
            raise ValueError('操作已超时，请重新打开并确认。') from None
        if isinstance(result, dict) and result.get('error'):
            raise ValueError('操作未完成，请重新打开；可刷新列表查看最新状态。')
        return result

    return metadata, interact


class ManageRecordForm(PageInteractionForm):
    action: Literal['修改', '取消']
    schedule_draft: dict[str, str] | None = None


@router.post('/records/{kind}/{record_id}/manage')
async def manage_record(kind: Literal['orders', 'tickets'], record_id: str,
                        form: ManageRecordForm, user=Depends(get_verified_user)):
    metadata, interact = await page_interaction(form, user)
    if form.schedule_draft and form.action == '修改':
        original_interact = interact
        draft = {key: value for key, value in form.schedule_draft.items() if key in ('date', 'slot')}
        if (draft.get('date') and draft['date'] not in shop._schedule()) or (
                draft.get('slot') and draft['slot'] not in ('09:00-12:00', '14:00-18:00')):
            raise HTTPException(400, '建议时间不在当前可预约范围，请重新选择。')
        # Prefill the existing form; its validation, address selection and final
        # confirmation still own every write, exactly as in the ordinary record page.
        async def interact(event):
            code = event.get('data', {}).get('code', '')
            prefix = 'const serviceData = '
            if event.get('type') == 'execute' and code.startswith(prefix):
                raw, script = code[len(prefix):].split(';\n', 1)
                payload = json.loads(raw)
                if payload.get('mode') in ('order-edit', 'appointment'):
                    payload['draft'] = payload.get('draft', {}) | draft
                    event = {'type': 'execute', 'data': {'code': prefix +
                             json.dumps(payload, ensure_ascii=False) + ';\n' + script}}
            return await original_interact(event)
    # The same forms, final confirmation, ownership checks and inventory transaction
    # serve both chat and this page. No model request or second write path is needed.
    manage = shop.manage_order if kind == 'orders' else shop.manage_service_ticket
    return await manage(form.action, record_id, __user__={'id': user.id},
                        __metadata__=metadata, __event_call__=interact)


@router.get('/addresses')
def addresses(user=Depends(get_verified_user)):
    return {'addresses': shop._addresses(user.id)}


class ManageAddressForm(PageInteractionForm):
    action: Literal['新增', '修改', '删除', '设为默认']
    address_id: str = ''


@router.post('/addresses/manage')
async def manage_address(form: ManageAddressForm, user=Depends(get_verified_user)):
    _, interact = await page_interaction(form, user)
    return await shop._manage_address(form.action, form.address_id, user.id, interact)


def document_paths() -> dict[str, Path]:
    return {path.stem: path for path in sorted((ROOT / 'knowledge').glob('*.md'))}


@router.get('/knowledge')
def knowledge():
    paths = document_paths()
    return {'id': 'washer-cloud', 'name': '家电产品资料',
            'description': '产品参数与使用说明书', 'file_count': len(paths),
            'updated_at': int(max((p.stat().st_mtime for p in paths.values()), default=0)),
            'documents': [{'id': key, 'model': key.rsplit('_', 1)[0],
                           'kind': key.rsplit('_', 1)[1], 'name': path.name}
                          for key, path in paths.items()]}


@router.get('/knowledge/{document_id}')
def document(document_id: str):
    path = document_paths().get(document_id)
    if path is None:
        raise HTTPException(404, '资料不存在')
    return {'id': document_id, 'content': path.read_text()}


from features.guidance import router as guidance_router
from features.plans import router as plans_router
from features.changes import router as changes_router
from features.preview import router as preview_router

for activity_router in (guidance_router, plans_router, changes_router, preview_router):
    router.include_router(activity_router)

# Keep the stock SPA catch-all last so the narrow authenticated API remains reachable.
position = next(i for i, route in enumerate(app.router.routes) if getattr(route, 'path', None) == '')
previous_length = len(app.router.routes)
app.include_router(router)
added = app.router.routes[previous_length:]
del app.router.routes[previous_length:]
app.router.routes[position:position] = added
