import sys
import os
import traceback
from pikpak_api import get_origin_url, download_range

def run_smoke():
    share_url = os.environ.get("PIKPAK_TEST_SHARE_URL")
    if len(sys.argv) > 1:
        share_url = sys.argv[1]
        
    if not share_url:
        print("Usage: python smoke_origin_test.py <share_url>")
        print("Or set PIKPAK_TEST_SHARE_URL environment variable.")
        return False

    print("Stage: Share URL parsing and Origin URL discovery")
    try:
        origin_url = get_origin_url(share_url)
        print("Successfully obtained Origin URL.")
        print(f"Origin URL format check: {origin_url.startswith('http')}")
        
        print("Stage: Range bytes=0-65535 fetch")
        chunk = download_range(origin_url, "0-65535", 65536)
        
        print(f"Stage: Success! Fetched exactly {len(chunk)} bytes from Origin.")
        if len(chunk) != 65536:
            print("Failed: Length mismatch.")
            return False
            
        return True
    except Exception as e:
        print("Failed with exception:")
        traceback.print_exc()
        return False

if __name__ == '__main__':
    success = run_smoke()
    sys.exit(0 if success else 1)
