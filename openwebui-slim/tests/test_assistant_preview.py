"""Room-preview references, measured dimensions and native generation scheduling."""
import asyncio
import base64
import importlib.util
import io
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException, Request
import httpx
from PIL import Image
from pydantic import BaseModel

import test_demo_shop as fixture


class EditImageForm(BaseModel):
    image: str | list[str]
    prompt: str
    model: str | None = None
    n: int | None = None


class AssistantPreviewTests(unittest.IsolatedAsyncioTestCase):
    tearDown = fixture.DemoShopTests.tearDown

    def setUp(self):
        fixture.DemoShopTests.setUp(self)
        package = ModuleType('features')
        package.__path__ = [str(fixture.ROOT / 'features')]
        auth = ModuleType('open_webui.utils.auth')

        async def verified_user(request: Request):
            header = request.headers.get('authorization', '')
            if header not in ('Bearer alice', 'Bearer bob'):
                raise HTTPException(401, 'Sign in required')
            return SimpleNamespace(id=header.removeprefix('Bearer '))

        auth.get_verified_user = verified_user
        self.native = ModuleType('open_webui.routers.images')
        self.native.EditImageForm = EditImageForm
        self.native.image_edits = self.image_edits
        self.native.upload_image = self.upload_image
        self.common = self.module('features.common', fixture.ROOT / 'features/common.py')
        self.preview = self.module('preview_under_test', fixture.ROOT / 'features/preview.py')
        self.module_patcher = patch.dict(sys.modules, {
            'features': package, 'features.common': self.common,
            'open_webui.utils.auth': auth, 'open_webui.routers.images': self.native,
            'tools.demo_shop': fixture.module})
        self.module_patcher.start()
        self.addCleanup(self.module_patcher.stop)
        self.common.__spec__.loader.exec_module(self.common)
        self.preview.__spec__.loader.exec_module(self.preview)
        self.common.STATE_DB = Path(self.temp.name) / 'assistant.sqlite3'
        self.preview.ROOT = Path(self.temp.name) / 'preview'
        self.preview.ROOT.mkdir()
        (self.preview.ROOT / 'assistant-images.json').write_text(json.dumps({
            'model': 'gemini-3.1-flash-image', 'requests_per_minute': 1}))
        self.product = {'model': 'JG-F10', 'name': '净洗 10', 'type': '滚筒洗衣机',
                        'installation_mm': [635, 870, 610], 'width_mm': 595,
                        'height_mm': 850, 'depth_mm': 550}
        image_path = self.preview.ROOT / 'assets/products/JG-F10.png'
        image_path.parent.mkdir(parents=True)
        Image.new('RGB', (4, 4), 'white').save(image_path)
        self.reference_bytes = image_path.read_bytes()
        self.photo = 'data:image/png;base64,' + base64.b64encode(self.reference_bytes).decode()
        self.tools._product_catalog = lambda: [self.product]
        self.preview.get_shop = lambda: self.tools
        self.calls = []
        self.uploads = []
        self.fail_native = False
        self.active = 0
        self.peak_active = 0
        self.now = 1000.0
        self.sleeps = []
        self.preview.time = SimpleNamespace(time=lambda: self.now)
        self.preview.asyncio = SimpleNamespace(
            sleep=self.sleep, wait_for=asyncio.wait_for, create_task=asyncio.create_task,
            CancelledError=asyncio.CancelledError)
        app = FastAPI()
        app.include_router(self.preview.router, prefix='/api/v1/jiadian')
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://preview.test')

    @staticmethod
    def module(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        return importlib.util.module_from_spec(spec)

    async def asyncTearDown(self):
        jobs = list(self.preview._jobs.values())
        if jobs:
            await asyncio.gather(*jobs, return_exceptions=True)
        await self.client.aclose()

    async def sleep(self, delay):
        self.sleeps.append(delay)
        self.now += delay
        await asyncio.sleep(0)

    async def image_edits(self, request, form, metadata, user):
        self.active += 1
        self.peak_active = max(self.peak_active, self.active)
        self.calls.append({'form': form, 'metadata': metadata, 'user': user.id, 'at': self.now})
        try:
            await asyncio.sleep(0)
            if self.fail_native:
                raise HTTPException(429, 'RESOURCE_EXHAUSTED')
            return [{'id': 'result-' + metadata['activity_id'],
                     'url': '/api/v1/files/result-' + metadata['activity_id'] + '/content'}]
        finally:
            self.active -= 1

    async def upload_image(self, request, image_data, content_type, metadata, user):
        self.uploads.append({'data': image_data, 'type': content_type, 'user': user.id})
        image_id = 'original-' + metadata['activity_id']
        return None, {'id': image_id, 'url': f'/api/v1/files/{image_id}/content', 'content_type': content_type}

    def state(self, session_id='preview-one', user='alice'):
        return self.common.save_session(user, 'preview', {
            'id': session_id, 'model': self.product['model'], 'name': self.product['name'],
            'instruction': '放在左边靠墙处', 'dimensions': None,
            'original': {'id': 'original-' + session_id, 'url': f'/api/v1/files/original-{session_id}/content'},
            'status': 'queued', 'fit': self.preview.fit_check(self.product, None)})

    async def create(self, request_id, user='alice', **body):
        return await self.client.post('/api/v1/jiadian/assistant/preview',
            headers={'Authorization': f'Bearer {user}'}, json={
                'model': 'JG-F10', 'image': self.photo, 'request_id': request_id,
                'instruction': '放在左边靠墙处'} | body)

    async def settle(self):
        jobs = list(self.preview._jobs.values())
        if jobs:
            await asyncio.gather(*jobs)

    async def test_clearance_uses_supplied_measurements_and_installation_not_body_dimensions(self):
        fit = self.preview.fit_check(self.product, {'width': 640, 'height': 870, 'depth': 600})
        self.assertEqual(fit['status'], '预留尺寸不足')
        self.assertEqual([item['difference_mm'] for item in fit['checks']], [5, 0, -10])
        self.assertEqual([item['required_mm'] for item in fit['checks']], [635, 870, 610])
        exact = self.preview.fit_check(self.product, {'width': 635, 'height': 870, 'depth': 610})
        self.assertEqual(exact['status'], '预留尺寸满足')
        self.assertIn('安装人员确认', exact['message'])

    async def test_photo_without_measured_dimensions_never_asserts_fit(self):
        response = await self.create('no-measurements')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['fit']['status'], '待测量')
        self.assertNotIn('checks', response.json()['fit'])
        await self.settle()
        saved = self.common.load_session('alice', 'preview', 'no-measurements')
        self.assertEqual(saved['status'], 'completed')
        self.assertEqual(saved['fit']['status'], '待测量')
        self.assertIsNone(saved['dimensions'])

    async def test_native_edit_gets_original_and_catalog_reference_with_owner(self):
        state = self.state()
        await self.preview.generate_preview(SimpleNamespace(), SimpleNamespace(id='alice'), state, self.product)
        call = self.calls[0]
        self.assertEqual(call['form'].image[0], state['original']['url'])
        self.assertEqual(base64.b64decode(call['form'].image[1].split(',', 1)[1]), self.reference_bytes)
        self.assertEqual(call['form'].model, 'gemini-3.1-flash-image')
        self.assertEqual(call['form'].n, 1)
        self.assertEqual(call['user'], 'alice')
        self.assertEqual(call['metadata']['activity_id'], state['id'])
        self.assertIn('缩小商品', call['form'].prompt)
        saved = self.common.load_session('alice', 'preview', state['id'])
        self.assertEqual(saved['image']['id'], 'result-' + state['id'])

    async def test_generation_is_serial_and_limited_to_one_start_per_minute(self):
        first, second = self.state('first'), self.state('second', 'bob')
        await asyncio.gather(
            self.preview.generate_preview(SimpleNamespace(), SimpleNamespace(id='alice'), first, self.product),
            self.preview.generate_preview(SimpleNamespace(), SimpleNamespace(id='bob'), second, self.product))
        self.assertEqual(self.peak_active, 1)
        self.assertEqual([call['at'] for call in self.calls], [1000, 1060])
        self.assertEqual(self.sleeps, [60])
        self.assertEqual(self.preview._next_request_at, 1120)

    async def test_history_requires_authentication_and_stays_user_scoped(self):
        alice = self.state('alice-history')
        bob = self.state('bob-history', 'bob')
        for user, state in [('alice', alice), ('bob', bob)]:
            self.common.save_session(user, 'preview', state | {'status': 'completed'})
        endpoint = '/api/v1/jiadian/assistant/preview'
        self.assertEqual((await self.client.get(endpoint)).status_code, 401)
        own = await self.client.get(endpoint, headers={'Authorization': 'Bearer alice'})
        self.assertEqual([state['id'] for state in own.json()['sessions']], ['alice-history'])
        other = await self.client.get(endpoint + '/alice-history', headers={'Authorization': 'Bearer bob'})
        self.assertEqual(other.status_code, 404)
        self.assertEqual((await self.client.get(endpoint + '/bob-history',
            headers={'Authorization': 'Bearer alice'})).status_code, 404)

    async def test_failed_generation_preserves_input_and_new_request_can_retry(self):
        self.fail_native = True
        response = await self.create('failed-request')
        self.assertEqual(response.status_code, 200)
        await self.settle()
        failed = self.common.load_session('alice', 'preview', 'failed-request')
        self.assertEqual(failed['status'], 'failed')
        self.assertEqual(failed['original'], response.json()['original'])
        self.assertEqual(failed['model'], 'JG-F10')
        self.assertIn('频率限制', failed['error'])
        # The UI intentionally uses a fresh request ID when the user clicks regenerate.
        self.fail_native = False
        self.assertEqual((await self.create('retry-request')).status_code, 200)
        await self.settle()
        retried = self.common.load_session('alice', 'preview', 'retry-request')
        self.assertEqual(retried['status'], 'completed')
        self.assertEqual(self.common.load_session('alice', 'preview', 'failed-request')['status'], 'failed')
        self.assertGreaterEqual(self.calls[1]['at'] - self.calls[0]['at'], 60)

    async def test_repeated_request_id_does_not_upload_or_generate_twice(self):
        self.assertEqual((await self.create('same-request')).status_code, 200)
        await self.settle()
        response = await self.create('same-request')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'completed')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(self.uploads), 1)

    async def test_interrupted_saved_job_becomes_retryable_failure(self):
        state = self.state('interrupted')
        response = await self.client.get('/api/v1/jiadian/assistant/preview/' + state['id'],
                                         headers={'Authorization': 'Bearer alice'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'failed')
        self.assertIn('重新生成', response.json()['error'])
        self.assertEqual(response.json()['original'], state['original'])

    async def test_another_users_same_request_id_does_not_mask_an_interrupted_job(self):
        release = asyncio.Event()
        original_edit = self.native.image_edits

        async def paused_edit(*args, **kwargs):
            await release.wait()
            return await original_edit(*args, **kwargs)

        self.native.image_edits = paused_edit
        try:
            self.assertEqual((await self.create('shared-id', user='alice')).status_code, 200)
            self.state('shared-id', user='bob')  # Bob's saved job has no live task.
            response = await self.client.get('/api/v1/jiadian/assistant/preview/shared-id',
                                             headers={'Authorization': 'Bearer bob'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['status'], 'failed')
            self.assertIn('重新生成', response.json()['error'])
        finally:
            release.set()
            await self.settle()


if __name__ == '__main__':
    unittest.main()
