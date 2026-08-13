import sys
import json
import urllib.request
import urllib.error
import urllib.parse
import asyncio

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
REFERER = "https://mypikpak.com/"
RANGE_HEADER = "bytes=0-65535"

URL = "https://dl-z01a-0026.mypikpak.com/download/?fid=DwBODx5FG-5Jlk6DM6I_t088LmqenwzGwvCgUzAJYti9MyACOGYvML-CtaOkuk60pH006DYDbIoRVEsfLTES1WDoZzT-vUu_tJ2oJhKlEDU=&from=5&verno=3&prod=pikpak&expire=1786697999&g=CFF1C0FE0A980331B2A5FEA31362F594C058E06D&ui=888880000000973&t=1&ms=6300000&th=6300000&f=139343156&alt=0&us=0&hspu=&po=0&userid=&category=transcoded&fileid=VOzuAuSrUkan_TaiMNnhSZmro2&pr=XQPkPvr9WWiIuMvELmrVerhQrYKbpARSXHP2jBQKgvDmhkwenAzHDfpc8ZfeM9_g43T_dFWM4KpZuIpz9WtbJbx0hz-I8MEAV-oAty0kPgKFexuSqkvW0_rIZtEwCd4upEAWP9iRSm99DPKjSdKDPO7XfMsn-81SpNGg6doho5sdPvjziwAjdT85yghnad2rLGCo7LKEPYlvIZjXgHNTeuY1PeC8MRHA6p8R97N-abmkUc6cxEqdFQxQANsHjG1aVrE37_vQ010Y6ZmMIshX-DIKkFIfYQCFcJAAhaVwymZnsgsLybW1uXg97wm89xYhNdtVCiuF0S2lgauvo_7VhxKNlY7WWRjH94k5YwWSPd2uhQFCRbD6v1EhmEKn1jYSgjNl_xlKa3CDkwyo7JkO8ezKdjMX_gUoU1K72MbPO-0=&sign=5D8A000E768504220134E451C8E5A994"

def test_request(name, url, headers):
    print(f"\n--- Test {name} ---")
    print(f"Headers: {json.dumps(headers)}")
    req = urllib.request.Request(url, headers=headers)
    
    class RedirectTracer(urllib.request.HTTPRedirectHandler):
        def __init__(self):
            self.redirects = []
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            self.redirects.append((code, newurl))
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    tracer = RedirectTracer()
    opener = urllib.request.build_opener(tracer)
    urllib.request.install_opener(opener)
    
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.getcode()
            content_range = resp.headers.get('Content-Range')
            content_length = resp.headers.get('Content-Length')
            final_url = resp.url
            
            print(f"HTTP status: {status}")
            print(f"Content-Range: {content_range}")
            print(f"Content-Length: {content_length}")
            print(f"Redirect chain: {tracer.redirects}")
            
            final_host = urllib.parse.urlparse(final_url).netloc
            print(f"Final host: {final_host}")
            
            if status != 206:
                print("ABORTED: Server did not return 206 Partial Content")
                return
                
            bytes_read = 0
            chunk_size = 8192
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                bytes_read += len(chunk)
                if bytes_read >= 65536:
                    break
                    
            print(f"Actual bytes read: {bytes_read}")
            
    except urllib.error.HTTPError as e:
        print(f"HTTPError: {e.code} {e.reason}")
        print(f"Redirect chain: {tracer.redirects}")
    except urllib.error.URLError as e:
        print(f"URLError: {e.reason}")
    except Exception as e:
        print(f"Exception type: {type(e).__name__}")
        print(f"Exception message: {str(e)}")

def main():
    print("Using known valid DL URL from previous probe.")
    
    # Run tests A, B, C, D
    test_request("A (Range only)", URL, {"Range": RANGE_HEADER})
    test_request("B (Range + UA)", URL, {"Range": RANGE_HEADER, "User-Agent": USER_AGENT})
    test_request("C (Range + Referer)", URL, {"Range": RANGE_HEADER, "Referer": REFERER})
    test_request("D (Range + UA + Referer)", URL, {"Range": RANGE_HEADER, "User-Agent": USER_AGENT, "Referer": REFERER})

if __name__ == "__main__":
    main()
