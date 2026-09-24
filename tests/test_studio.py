"""Run: ComfyUI/.venv/Scripts/python.exe -m unittest discover -s tests -v

All HTTP tests use an isolated fake engine and temporary files; no GPU or app restart.
"""
import asyncio
import io
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

from studio import Studio, create_app, normalize_reference
from studio_core import (CLIP, GGUF, VAE, MAX_SEED, REQUIRED_NODES,
                         build_workflow, dimensions, settings_from)


def png(width=640, height=480, mode='RGB'):
    stream = io.BytesIO()
    Image.new(mode, (width, height), (74, 92, 60, 128) if mode == 'RGBA' else (74, 92, 60)).save(stream, 'PNG')
    return stream.getvalue()


class WorkflowTests(unittest.TestCase):
    def test_production_defaults_and_mode_specific_prompt(self):
        for mode in ['create', 'ui', 'graphics', 'product', 'illustration', 'edit', 'design']:
            s = settings_from({'prompt': 'A clean design', 'mode': mode})
            graph = build_workflow(s, 7, [], Path('.'))['prompt']
            self.assertEqual(graph['6']['inputs']['steps'], 40)
            self.assertEqual(graph['6']['inputs']['cfg'], 1)
            self.assertEqual(graph['9']['inputs']['dtype'], 'default')
            self.assertNotIn('fingers', s['effective_prompt'])
            self.assertNotIn('two legs', s['effective_prompt'])
        self.assertIn('grid', settings_from({'prompt':'Dashboard','mode':'ui'})['effective_prompt'])

    def test_invalid_settings_rejected(self):
        for data in [{'seed': str(MAX_SEED)}, {'seed':'1.5'}, {'count':'9'}, {'count':'0'}, {'mode':'invalid'},
                     {'cfg':'nan'}, {'cfg':'inf'}, {'cfg':'0'}, {'steps':'12'}, {'quality':'ultra'},
                     {'negative_prompt':'blurry'}, {'enhance':'maybe'}, {'prompt':''}]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                settings_from({'prompt':'Test', **data})

    def test_seed_zero_is_reproducible_and_random_is_random(self):
        self.assertEqual(settings_from({'prompt':'Test','seed':'0'})['seed'], 0)
        self.assertNotEqual(settings_from({'prompt':'Test'})['seed'], settings_from({'prompt':'Test'})['seed'])

    def test_guidance_and_prompt_opt_out(self):
        s = settings_from({'prompt':'Keep this exact brief','enhance':'false','negative_prompt':'blur','cfg':'2'})
        self.assertEqual(s['effective_prompt'], s['prompt'])
        self.assertEqual(s['cfg'], 2)
        s = settings_from({'prompt':'A logo','exact_text':'A & B','transparent':'true'})
        self.assertIn('A & B', s['effective_prompt'])
        self.assertIn('alpha channel', s['effective_prompt'])

    def test_reference_alignment_matches_native_encoder(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            reference = normalize_reference(png(1200, 800), directory)
            s = settings_from({'prompt':'Edit it','mode':'edit','shape':'tall'})
            graph = build_workflow(s, 1, [reference], directory)['prompt']
            self.assertEqual(graph['6']['inputs']['latent_image'], ['5', 2])
            self.assertEqual(dimensions(s, [reference], directory), (1248, 832, 1024))
            s['match_size'] = False
            self.assertEqual(build_workflow(s, 1, [reference], directory)['prompt']['6']['inputs']['latent_image'], ['4', 0])

    def test_references_deduplicate_and_keep_alpha(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            first = normalize_reference(png(mode='RGBA'), directory)
            second = normalize_reference(png(mode='RGBA'), directory)
            self.assertEqual(first, second)
            with Image.open(directory / first) as image:
                self.assertEqual(image.mode, 'RGBA')
            self.assertEqual(len(list(directory.glob('*.png'))), 1)
            with self.assertRaises(ValueError):
                normalize_reference(b'not an image', directory)
            with self.assertRaises(ValueError):
                normalize_reference(png(20, 600), directory)


class FakeEngine:
    def __init__(self, output):
        self.output = output
        self.prompts = []
        self.pending = {}
        self.history = {}
        self.cancelled = []
        self.reject_at = None
        self.app = web.Application()
        self.app.add_routes([web.get('/object_info', self.info), web.get('/system_stats', self.stats),
                             web.get('/queue', self.queue), web.post('/prompt', self.submit),
                             web.get('/history/{pid}', self.get_history), web.get('/ws', self.ws),
                             web.post('/api/jobs/{pid}/cancel', self.cancel)])

    async def info(self, request):
        info = {node: {} for node in REQUIRED_NODES}
        for node, field, name in [('UnetLoaderGGUF','unet_name',GGUF),('CLIPLoader','clip_name',CLIP),('VAELoader','vae_name',VAE)]:
            info[node] = {'input':{'required':{field:[[name]]}}}
        return web.json_response(info)

    async def stats(self, request):
        return web.json_response({'devices':[{'name':'Test GPU','vram_total':8*1024**3}]})

    async def queue(self, request):
        return web.json_response({'queue_running':[], 'queue_pending':[[i,pid] for i,pid in enumerate(self.pending)]})

    async def submit(self, request):
        data = await request.json()
        self.prompts.append(data)
        if self.reject_at == len(self.prompts):
            return web.json_response({'error':{'message':'Invalid workflow'}},status=400)
        self.pending[data['prompt_id']] = data
        return web.json_response({'prompt_id':data['prompt_id']})

    async def get_history(self, request):
        pid = request.match_info['pid']
        return web.json_response({pid:self.history[pid]} if pid in self.history else {})

    async def cancel(self, request):
        pid = request.match_info['pid']
        self.cancelled.append(pid)
        existed = self.pending.pop(pid, None) is not None
        return web.json_response({'cancelled':existed})

    async def ws(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for message in ws:
            pass
        return ws

    def finish(self, pid):
        body = self.pending.pop(pid)
        filename = body['prompt']['8']['inputs']['filename_prefix'] + '_00001_.png'
        self.output.mkdir(parents=True, exist_ok=True)
        (self.output / filename).write_bytes(png())
        self.history[pid] = {'status':{'status_str':'success','completed':True,'messages':[
            ['execution_start', {'timestamp':int((time.time()-3)*1000)}], ['execution_success',{'timestamp':int(time.time()*1000)}]]},
            'outputs':{'8':{'images':[{'filename':filename,'subfolder':'','type':'output'}]}}}


class APITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.engine = FakeEngine(self.root / 'output')
        self.server = TestServer(self.engine.app)
        await self.server.start_server()
        self.app = create_app(str(self.server.make_url('')).rstrip('/'), self.root/'jobs', self.root/'input', self.root/'output')
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.studio = self.app['studio']

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()
        self.temp.cleanup()

    async def generate(self, **values):
        response = await self.client.post('/api/generate', data={'prompt':'A UI dashboard','seed':'100','count':'4', **values})
        self.assertEqual(response.status, 202, await response.text())
        return await response.json()

    async def refresh(self):
        async with self.studio.lock:
            await self.studio.refresh()

    async def test_batch_seeds_cache_reuse_and_persistence(self):
        batch = await self.generate()
        self.assertEqual([i['seed'] for i in batch['items']], [100,101,102,103])
        self.assertEqual(len({i['prompt_id'] for i in batch['items']}),4)
        graphs = [body['prompt'] for body in self.engine.prompts]
        for graph in graphs[1:]:
            for node in ['1','2','3','4','5','9']:
                self.assertEqual(graph[node], graphs[0][node])
        restored = Studio('unused', self.root/'jobs',self.root/'input',self.root/'output')
        restored.load()
        self.assertEqual(len(restored.batches[batch['id']]['items']), 4)

    async def test_completion_download_and_partial_cancellation(self):
        batch = await self.generate()
        self.engine.finish(batch['items'][0]['prompt_id'])
        await self.refresh()
        response = await self.client.post(f"/api/job/{batch['id']}/cancel")
        result = await response.json()
        self.assertEqual(result['status'],'partial')
        self.assertEqual(result['completed'],1)
        self.assertEqual(len(self.engine.cancelled),3)
        response = await self.client.get(f"/api/job/{batch['id']}/download")
        self.assertEqual(response.status,200)
        with zipfile.ZipFile(io.BytesIO(await response.read())) as archive:
            self.assertIn('settings.json',archive.namelist())
            self.assertEqual(len(archive.namelist()),2)
        response = await self.client.get(result['images'][0])
        self.assertEqual(response.status,200)

    async def test_rejection_keeps_accepted_images_visible(self):
        self.engine.reject_at = 2
        batch = await self.generate()
        self.assertEqual([i['status'] for i in batch['items']], ['queued','checking','error','error'])
        self.studio.batches[batch['id']]['items'][1]['missing_since'] = time.time()-30
        self.engine.finish(batch['items'][0]['prompt_id'])
        await self.refresh()
        result = self.studio.public(self.studio.batches[batch['id']])
        self.assertEqual(result['status'],'partial')
        self.assertIn('Invalid workflow',result['items'][1]['error'])

    async def test_timeout_recovery_and_progress(self):
        batch = await self.generate(count='1')
        item = self.studio.batches[batch['id']]['items'][0]
        item['status'] = 'checking'
        self.studio.progress({'type':'progress','data':{'prompt_id':item['prompt_id'],'value':12,'max':40}})
        self.assertEqual(item['progress'],0.3)
        self.assertEqual(item['status'],'running')
        self.engine.finish(item['prompt_id'])
        await self.refresh()
        self.assertEqual(item['status'],'done')

    async def test_upload_validation_reference_cache_and_preview(self):
        for raw, expected in [(b'broken',400),(png(),202)]:
            form = FormData(); form.add_field('prompt','Edit the background'); form.add_field('mode','edit')
            form.add_field('references',raw,filename='reference.png',content_type='image/png')
            response = await self.client.post('/api/generate',data=form)
            self.assertEqual(response.status,expected,await response.text())
            if expected == 202:
                batch = await response.json()
        ref = batch['references'][0]
        response = await self.client.post('/api/generate',data={'prompt':'Edit it','mode':'edit','saved_references':ref})
        self.assertEqual(response.status,202)
        response = await self.client.post('/api/preview',data={'prompt':'Dashboard','mode':'ui'})
        self.assertIn('grid',(await response.json())['prompt'])

    async def test_validation_origin_queue_limit_and_path_protection(self):
        for fields in [{'count':'99'},{'mode':'edit'},{'saved_references':'../../secret.png'}]:
            response = await self.client.post('/api/generate',data={'prompt':'Hello',**fields})
            self.assertEqual(response.status,400)
        response = await self.client.post('/api/generate',data={'prompt':'Hello'},headers={'Origin':'https://example.com'})
        self.assertEqual(response.status,403)
        for _ in range(3): await self.generate(count='8')
        response = await self.client.post('/api/generate',data={'prompt':'Too many'})
        self.assertEqual(response.status,400)
        (self.root/'QwenStudio_secret.png').write_bytes(png())
        response = await self.client.get('/api/view',params={'filename':'../QwenStudio_secret.png'})
        self.assertEqual(response.status,404)

    async def test_health_and_missing_history_fail_instead_of_hanging(self):
        response = await self.client.get('/api/health')
        self.assertTrue((await response.json())['online'])
        batch = await self.generate(count='1')
        item = self.studio.batches[batch['id']]['items'][0]
        self.engine.pending.clear()
        item['missing_since'] = time.time()-30
        await self.refresh()
        self.assertEqual(item['status'],'error')


if __name__ == '__main__':
    unittest.main()
