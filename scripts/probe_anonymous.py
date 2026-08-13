import sys
import json
import urllib.request
import asyncio
from playwright.async_api import async_playwright

async def probe():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        file_info = {}
        medias = []
        dl_urls = []
        
        async def handle_response(response):
            # Capture direct download URLs
            if "/download/" in response.url and "fid=" in response.url:
                dl_urls.append(response.url)
                
            if "mypikpak.com" in response.url and response.request.resource_type in ["fetch", "xhr"]:
                try:
                    data = await response.json()
                    def find_medias(obj):
                        if isinstance(obj, dict):
                            if "medias" in obj and isinstance(obj["medias"], list) and len(obj["medias"]) > 0:
                                return obj
                            for v in obj.values():
                                res = find_medias(v)
                                if res: return res
                        elif isinstance(obj, list):
                            for item in obj:
                                res = find_medias(item)
                                if res: return res
                        return None
                    
                    found = find_medias(data)
                    if found:
                        nonlocal file_info, medias
                        file_info = {"name": found.get("name"), "size": found.get("size")}
                        medias = found.get("medias", [])
                except Exception as e:
                    pass

        page.on("response", handle_response)
        
        await page.goto("https://mypikpak.com/s/VOzuCvKmZUsWl46t2khdDdcDo2", wait_until="networkidle")
        await page.wait_for_timeout(2000)
        
        # Click the play button or video thumbnail
        print("Clicking to trigger media load...")
        try:
            await page.click("text='vrkm-962-3.mp4'", timeout=3000)
        except:
            try:
                await page.click(".file-name", timeout=3000)
            except:
                try:
                    await page.click("div[class*='file']", timeout=3000)
                except:
                    pass
        
        await page.wait_for_timeout(5000)
        
        if not file_info and not dl_urls:
            print("Still failed to capture medias or dl_urls.")
        else:
            print(json.dumps({"file_info": file_info, "medias": medias, "dl_urls": dl_urls}, indent=2))
            
            # Test range on the first dl_url if available
            if dl_urls:
                url = dl_urls[0]
                print(f"\nTesting DL URL: {url[:100]}...")
                req = urllib.request.Request(url, headers={
                    'User-Agent': 'Mozilla/5.0',
                    'Range': 'bytes=0-1048575'
                })
                try:
                    with urllib.request.urlopen(req) as resp:
                        status = resp.getcode()
                        print(f"HTTP status: {status}")
                        print(f"Content-Range: {resp.headers.get('Content-Range')}")
                        print(f"Content-Length: {resp.headers.get('Content-Length')}")
                        
                        if status == 206:
                            bytes_read = 0
                            chunk_size = 8192
                            while True:
                                chunk = resp.read(chunk_size)
                                if not chunk:
                                    break
                                bytes_read += len(chunk)
                                if bytes_read >= 1048576:
                                    break
                            print(f"Actual bytes read: {bytes_read}")
                            print(f"Auth required evidence / 2 min limit: {bytes_read < 1048576}")
                        else:
                            print("ABORTED: Server ignored Range.")
                except Exception as e:
                    print(f"Error testing URL: {e}")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(probe())
