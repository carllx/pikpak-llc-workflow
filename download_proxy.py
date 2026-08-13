import sys
import os
import requests
from pikpak_api import get_proxy_url

def download_proxy(share_url, output_path):
    print(f"Resolving proxy URL for: {share_url}")
    
    try:
        proxy_url = get_proxy_url(share_url)
    except Exception as e:
        print(f"Error resolving proxy URL: {e}")
        sys.exit(1)
        
    print(f"Target URL resolved. Starting download to: {output_path}")
    
    try:
        with requests.get(proxy_url, stream=True) as r:
            r.raise_for_status()
            
            # Simple progress reporting
            total_size = int(r.headers.get('content-length', 0))
            downloaded = 0
            
            with open(output_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192*4):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            percent = (downloaded / total_size) * 100
                            sys.stdout.write(f"\rDownloaded: {downloaded / (1024*1024):.2f} MB / {total_size / (1024*1024):.2f} MB ({percent:.1f}%)")
                        else:
                            sys.stdout.write(f"\rDownloaded: {downloaded / (1024*1024):.2f} MB")
                        sys.stdout.flush()
                        
            print("\nDownload complete!")
    except Exception as e:
        print(f"\nError during download: {e}")
        sys.exit(1)

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python download_proxy.py <share_url> <output_file.mp4>")
        sys.exit(1)
        
    share_url = sys.argv[1]
    output_path = sys.argv[2]
    
    # If the URL is just an ID, construct the full URL
    if not share_url.startswith("http"):
        share_url = f"https://mypikpak.com/s/{share_url}"
        
    download_proxy(share_url, output_path)
