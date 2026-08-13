import sys
import traceback
from pikpak_api import get_media_variants, download_range

def run_smoke():
    print("Stage: Share URL parsing and variants extraction")
    share_url = "https://mypikpak.com/s/VOzuCvKmZUsWl46t2khdDdcDo2"
    try:
        medias = get_media_variants(share_url)
        print("Successfully obtained media variants.")
        
        target_480p = None
        for m in medias:
            if m.get('resolution_name') == '480P':
                target_480p = m
                break
                
        if not target_480p:
            print("Failed: 480P media not found in variants.")
            print("Available resolutions:", [m.get('resolution_name') for m in medias])
            return False
            
        print("Stage: 480P URL located")
        url_480p = target_480p['link']['url']
        
        print("Stage: Range bytes=0-65535 fetch")
        chunk = download_range(url_480p, "0-65535", 65536)
        
        print(f"Stage: Success! Fetched exactly {len(chunk)} bytes.")
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
