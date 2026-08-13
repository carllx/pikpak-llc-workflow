import urllib.request
import re
import json

url = "https://mypikpak.com/s/VOzuCvKmZUsWl46t2khdDdcDo2"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
try:
    with urllib.request.urlopen(req) as response:
        html = response.read().decode('utf-8')
        print("HTML fetched, length:", len(html))
        
        # Look for script tags with JSON data
        match = re.search(r'window\.__STORE__\s*=\s*(\{.*?\});', html, re.DOTALL)
        if match:
            print("Found __STORE__")
            data = json.loads(match.group(1))
            print(json.dumps(data, indent=2)[:500])
        else:
            match = re.search(r'window\.__NEXT_DATA__\s*=\s*(\{.*?\});', html, re.DOTALL)
            if match:
                print("Found __NEXT_DATA__")
            else:
                print("No obvious state found. Snippet:")
                print(html[:1000])
except Exception as e:
    print(f"Error: {e}")
