"""Opt-in native-engine smoke test. Does not start, stop, or restart any server."""
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aiohttp import ClientSession, ClientTimeout
from studio_core import build_workflow, settings_from
from studio import normalize_reference


async def main():
    if '--run' not in sys.argv:
        raise SystemExit('Pass --run to generate a real 40-step image using the already-running engine.')
    root = Path(__file__).resolve().parents[1]
    s = settings_from({'prompt': 'A clean desktop dashboard for a plant care app. Warm ivory background, dark forest green sidebar, three summary cards, one simple watering schedule. Spacious aligned grid, clear hierarchy, large concise labels, crisp flat UI design. Straight-on interface, no device frame.',
                       'mode': 'ui', 'seed': '824107', 'count': '1', 'shape': 'landscape'})
    refs = []
    if '--edit' in sys.argv:
        refs = [normalize_reference((root/'ComfyUI/output/QwenStudio_SmokeTest_00001_.png').read_bytes(),root/'ComfyUI/input/qwen_studio')]
        s = settings_from({'prompt':'Keep the exact interface layout from image 1. Replace the sidebar labels with simple leaf icons only. Replace all existing text with the short English labels specified below. Keep the ivory and forest green palette.',
                           'exact_text':'PLANTS\nOverview\nMy Plants\nSchedule', 'mode':'edit','seed':'824108','count':'1'})
    body = build_workflow(s, s['seed'], refs, root / 'ComfyUI/input/qwen_studio', prefix='QwenStudio_SmokeTestEdit' if refs else 'QwenStudio_SmokeTest', client_id=str(uuid.uuid4()))
    async with ClientSession(timeout=ClientTimeout(total=30)) as session:
        async with session.get('http://127.0.0.1:8188/queue') as response:
            queue = await response.json()
        if queue['queue_running'] or queue['queue_pending']:
            raise SystemExit('Engine is busy; skipping smoke test.')
        start = time.monotonic()
        async with session.post('http://127.0.0.1:8188/prompt', json=body) as response:
            response.raise_for_status()
            queued = await response.json()
        pid = queued['prompt_id']
        print('Submitted', pid, flush=True)
        while time.monotonic() - start < 1200:
            await asyncio.sleep(5)
            async with session.get(f'http://127.0.0.1:8188/history/{pid}') as response:
                record = (await response.json()).get(pid)
            if record:
                report = {'prompt_id': pid, 'seconds': round(time.monotonic()-start, 1), 'settings': s,
                          'status': record['status'], 'outputs': record.get('outputs')}
                target = root / '.studio' / ('smoke-test-edit.json' if refs else 'smoke-test.json')
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_text(json.dumps(report,indent=2),encoding='utf-8')
                print(json.dumps(report),flush=True)
                if record['status']['status_str'] != 'success':
                    raise SystemExit(1)
                return
        raise SystemExit(f'Test timed out; job {pid} may still be running. No interruption was sent.')

asyncio.run(main())
