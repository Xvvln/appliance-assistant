"""Room previews using Open WebUI's native Gemini editing and file storage."""
import asyncio
import base64
import io
import json
import logging
import time
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from open_webui.utils.auth import get_verified_user
from PIL import Image, ImageOps
from pydantic import BaseModel, Field

from features.common import ROOT, get_shop, list_sessions, load_session, save_session

router = APIRouter(prefix='/assistant/preview')
_generation_lock = asyncio.Lock()
_next_request_at = 0.0
_jobs: dict[tuple[str, str], asyncio.Task] = {}


def image_settings() -> dict:
    return json.loads((ROOT / 'assistant-images.json').read_text())


def normalize_image(data_uri: str) -> bytes:
    try:
        header, encoded = data_uri.split(',', 1)
        if not header.startswith('data:image/') or len(encoded) > 14_000_000:
            raise ValueError()
        raw = base64.b64decode(encoded, validate=True)
        with Image.open(io.BytesIO(raw)) as source:
            image = ImageOps.exif_transpose(source).convert('RGB')
            image.thumbnail((1536, 1536))
            output = io.BytesIO()
            image.save(output, format='PNG')
        return output.getvalue()
    except (ValueError, OSError) as error:
        raise HTTPException(400, '请选择小于 10 MB 的 JPG、PNG 或 WebP 图片。') from error


def fit_check(product: dict, dimensions: dict | None) -> dict:
    required = product.get('installation_mm')
    if not required or not dimensions or not all(dimensions.get(k) for k in ('width', 'height', 'depth')):
        return {'status': '待测量', 'message': '填写实测宽、高、深后，可核对资料中的预留空间。'}
    names = [('width', '宽'), ('height', '高'), ('depth', '深')]
    checks = [{'label': label, 'measured_mm': dimensions[key], 'required_mm': minimum,
               'difference_mm': round(dimensions[key] - minimum, 1)}
              for (key, label), minimum in zip(names, required)]
    fits = all(item['difference_mm'] >= 0 for item in checks)
    return {'status': '预留尺寸满足' if fits else '预留尺寸不足', 'checks': checks,
            'message': '还需核对开门、搬运、管线及供电条件，安装前由安装人员确认。'}


class PreviewForm(BaseModel):
    model: str
    image: str
    instruction: str = Field(default='', max_length=1500)
    dimensions: dict[str, float] | None = None
    request_id: str = Field(default_factory=lambda: uuid4().hex, max_length=80)


async def generate_preview(request: Request, user, state: dict, product: dict):
    global _next_request_at
    from open_webui.routers.images import image_edits, EditImageForm

    try:
        async with _generation_lock:
            delay = max(0, _next_request_at - time.time())
            state.update(status='queued', available_at=_next_request_at)
            state = save_session(user.id, 'preview', state)
            if delay:
                await asyncio.sleep(delay)
            config = image_settings()
            _next_request_at = time.time() + 60 / max(1, int(config['requests_per_minute']))
            state.update(status='generating', available_at=_next_request_at)
            state = save_session(user.id, 'preview', state)
            product_path = ROOT / 'assets/products' / (product['model'] + '.png')
            product_image = 'data:image/png;base64,' + base64.b64encode(product_path.read_bytes()).decode()
            prompt = (
                '请生成一张真实摄影风格的家电摆放效果图。第一张是用户房间，第二张是待放入的商品参考。'
                '保留第一张的墙面、地板、门窗、光线和视角，把第二张的家电自然放进房间。'
                '保持商品的门数、颜色、面板、轮廓与参考一致，不添加其他商品、不添加文字。'
                '只作外观预览，不要通过改变房间结构或缩小商品来表现它能安装。'
                f'商品：{product["name"]} {product["model"]}；类型：{product["type"]}。'
                f'用户希望：{state["instruction"] or "放在适合的位置，保持整体简洁"}。'
                '请直接输出编辑后的图片。')
            images = await asyncio.wait_for(image_edits(
                request, EditImageForm(image=[state['original']['url'], product_image],
                                       prompt=prompt, model=config['model'], n=1),
                metadata={'activity_id': state['id']}, user=user), timeout=150)
            if not images:
                raise HTTPException(502, '本次没有返回图片，请重试或换一个摆放描述。')
            state.update(status='completed', image=images[0], error='')
            save_session(user.id, 'preview', state)
    except (Exception, asyncio.CancelledError) as error:
        detail = str(error.detail if isinstance(error, HTTPException) else error)
        logging.getLogger(__name__).error('Room preview failed: %s', detail)
        limited = '429' in detail or 'RESOURCE_EXHAUSTED' in detail or 'Too Many Requests' in detail
        if limited:
            _next_request_at = max(_next_request_at, time.time() + 60)
        state.update(status='failed', error=(
            '生图服务暂时达到频率限制，请稍后重试。' if limited else
            '图片暂时未生成，请重试。原图和所选产品已保留。'), available_at=_next_request_at)
        save_session(user.id, 'preview', state)


def recover_job(user_id: str, state: dict) -> dict:
    if state.get('status') in ('queued', 'generating') and (user_id, state['id']) not in _jobs:
        state.update(status='failed', error='上次生成已中断，可以重新生成。')
        return save_session(user_id, 'preview', state)
    return state


@router.get('')
def previews(user=Depends(get_verified_user)):
    return {'sessions': [recover_job(user.id, item) for item in list_sessions(user.id, 'preview')],
            'requests_per_minute': image_settings()['requests_per_minute'],
            'available_at': _next_request_at}


@router.get('/{session_id}')
def preview(session_id: str, user=Depends(get_verified_user)):
    state = load_session(user.id, 'preview', session_id)
    if not state:
        raise HTTPException(404, '预览不存在')
    return recover_job(user.id, state)


@router.post('')
async def create_preview(form: PreviewForm, request: Request, user=Depends(get_verified_user)):
    old = load_session(user.id, 'preview', form.request_id)
    if old:
        return recover_job(user.id, old)
    product = next((p for p in get_shop()._product_catalog() if p['model'] == form.model), None)
    if not product:
        raise HTTPException(400, '请从当前产品中选择型号。')
    from open_webui.routers.images import upload_image
    original_bytes = normalize_image(form.image)
    _, original = await upload_image(request, original_bytes, 'image/png',
                                     {'activity_id': form.request_id}, user)
    state = save_session(user.id, 'preview', {
        'id': form.request_id, 'model': form.model, 'name': product['name'],
        'instruction': form.instruction, 'dimensions': form.dimensions,
        'original': original, 'status': 'queued', 'fit': fit_check(product, form.dimensions),
        'available_at': _next_request_at})
    task = asyncio.create_task(generate_preview(request, user, state, product))
    key = (user.id, state['id'])
    _jobs[key] = task
    task.add_done_callback(lambda _: _jobs.pop(key, None))
    return state
