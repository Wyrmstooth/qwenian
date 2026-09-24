"""Real Chromium UI check with temporary servers and a fake inference engine."""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright
from studio import create_app
from test_studio import FakeEngine, png


async def main():
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as directory:
        temp = Path(directory)
        engine = FakeEngine(temp/'output')
        async with TestServer(engine.app) as upstream:
            app = create_app(str(upstream.make_url('')).rstrip('/'),temp/'jobs',temp/'input',temp/'output')
            async with TestServer(app) as server, async_playwright() as playwright:
                browser = await playwright.chromium.launch(channel='chrome',headless=True)
                page = await browser.new_page(viewport={'width':1440,'height':1100},device_scale_factor=1,accept_downloads=True)
                errors = []
                page.on('pageerror',lambda error: errors.append(str(error)))
                page.on('response', lambda response: print('HTTP error:',response.status,response.url,flush=True) if response.status >= 400 else None)
                await page.goto(str(server.make_url('/')))
                await page.wait_for_function("document.getElementById('engine').textContent.includes('READY')")
                await page.locator('[data-mode="ui"]').click()
                await page.locator('#example').click()
                await page.locator('#count').select_option('2')
                await page.locator('#seed').fill('400')
                await page.locator('#generate').click()
                await page.wait_for_function("document.querySelectorAll('.job-item').length === 2")
                assert len(engine.prompts) == 2
                for pid in list(engine.pending): engine.finish(pid)
                await page.wait_for_function("document.querySelectorAll('.gallery-card').length === 2")
                assert await page.locator('#collectionBody').is_hidden()
                await page.locator('#collectionToggle').click()
                await page.locator('.gallery-card').first.click()
                await page.locator('#reuse').click()
                assert await page.locator('#count').input_value() == '1'
                await page.locator('#variation').click()
                assert await page.locator('#seed').input_value() == ''
                assert await page.locator('#count').input_value() == '4'
                async with page.expect_download() as download:
                    await page.locator('[data-download]').first.click()
                result = await download.value
                assert result.suggested_filename.endswith('.zip'), result.suggested_filename
                assert await result.failure() is None
                async with page.expect_download() as download:
                    await page.locator('#download').click()
                result = await download.value
                assert result.suggested_filename.endswith('.png')
                assert await result.failure() is None
                await page.locator('#previewOpen').click()
                assert await page.locator('#lightbox').is_visible()
                await page.keyboard.press('Escape')
                await page.reload()
                await page.wait_for_function("document.querySelectorAll('.gallery-card').length === 2")
                assert await page.locator('#prompt').input_value() == ''
                assert 'prompt' not in await page.evaluate("JSON.parse(localStorage.getItem('qwen-studio-draft-v2'))")
                await page.locator('#useReference').click()
                await page.wait_for_function("document.querySelector('[data-mode=edit]').getAttribute('aria-pressed') === 'true'")
                assert await page.locator('[data-mode="edit"]').get_attribute('aria-pressed') == 'true'
                assert await page.locator('.ref-tile').count() == 1
                await page.locator('#prompt').fill('Replace the background with cream.')
                await page.locator('#generate').click()
                await page.wait_for_function("document.querySelector('[data-cancel]') !== null")
                await page.locator('[data-cancel]').first.click()
                await page.wait_for_function("document.getElementById('queueCount').textContent === 'All clear'")
                await page.locator('#clearRefs').click()
                await page.locator('[data-mode="graphics"]').click()
                await page.locator('#prompt').fill('A minimal exhibition poster for a ceramic art show. A terracotta vase on warm cream, generous margins, clean type.')
                await page.locator('#exact_text').fill('FORM & EARTH')
                await page.locator('#palette').fill('Cream, terracotta, charcoal')
                await page.locator('#prompt').blur()
                await page.screenshot(path=str(root/'.studio/browser-desktop.png'),full_page=True)
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                await page.set_viewport_size({'width':390,'height':844})
                await page.screenshot(path=str(root/'.studio/browser-mobile.png'),full_page=True)
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                await page.locator('#collectionToggle').click()
                await page.locator('#clearHistory').click()
                await page.wait_for_function("document.querySelectorAll('.gallery-card').length === 0")
                assert not errors, errors
                print(json.dumps({'browser_errors':errors,'checks':['mode tabs','batch submission','completion','gallery','reuse','variations','zip download','lightbox','reload recovery','prompt privacy','edit reference','scoped cancel','clear history','desktop layout','mobile layout']}))
                await browser.close()


asyncio.run(main())
