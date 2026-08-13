import subprocess

spec_body = """
## Problem Statement
Need a way to extract original high-quality video segments from PikPak without downloading the entire massive file, to save VPN/proxy bandwidth.

## Solution
An Agent-driven toolchain that:
1. Downloads a low-res (480p) proxy of the video.
2. Allows the user to rough-cut it in LosslessCut, producing a `.llc` project file.
3. Parses the `.llc` and performs a precise HTTP Range download of only those segments from the Origin media.

## User Stories
- As a user, I want to download a 480p proxy fast, so I can see what I want to keep without spending GBs of bandwidth.
- As a user, I want to use LosslessCut to pick the best scenes.
- As a user, I want the system to magically download only my selected scenes in Origin quality.

## Implementation Decisions
- Python script collection, not a GUI/EXE app.
- GitHub Issues as the work order system; Agent as the execution operator.
- Prefer anonymous CDN downloads (proved viable for transcoded medias) over Cookie-based API interaction unless strictly necessary.
- Hard guardrail: If Range fetch is unsupported by Origin, ABORT instead of full download.

## Testing Decisions
- Test locally using dummy/sample LLC files.
- Verify Range requests using small 64KB probes before committing to full segment downloads.
- Tests validate external behavior (HTTP calls, file output), not implementation details.

## Out of Scope
- Building a custom video player or GUI.
- Heavy background daemon services.
- Chrome extensions (unless Tampermonkey is added later just for link extraction).

## Further Notes
- Strict 600-line limit per file.
- Unresolved: Pure-python signature acquisition, Origin discovery, and Origin Range behavior.
"""

def run_cmd(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
    if result.returncode != 0:
        print(f"Error running {cmd}: {result.stderr}")
    return result.stdout.strip()

print("Creating Spec Issue...")
spec_url = run_cmd(f'gh issue create --title "Project Spec: PikPak -> LLC -> Origin segments workflow" --body "{spec_body}"')
print(f"Created Spec Issue: {spec_url}")

# Assuming the Spec issue is #6. We can parse the ID.
spec_id = spec_url.split('/')[-1]

issue_updates = {
    1: {
        "title": "A. Share URL -> available media variants -> anonymous 480p Range fetch",
        "body": f"""## Parent
#{spec_id}

## What to build
A pure-Python module that takes a PikPak share URL, extracts the available media variants (Origin, 1080p, 720p, 480p) without browser interception, and successfully fetches a small Range chunk (64KB) from a 480p media anonymously.

## Acceptance criteria
- [ ] Module parses share URL and returns available medias with signed URLs.
- [ ] Script performs a Range request (bytes=0-65535) on the 480p URL.
- [ ] Script successfully receives HTTP 206 and writes exactly 65536 bytes.
- [ ] No silent fallback to full download.
- [ ] Signed URLs/tokens are NOT printed or committed.
- [ ] No Cookie/auth architecture used (unless strictly proven necessary by new evidence).
- [ ] Code is under 600 lines.
- [ ] Tests validate external behavior.

## Blocked by
None
"""
    },
    2: {
        "title": "B. Complete 480p proxy download + connection-count benchmark",
        "body": f"""## Parent
#{spec_id}

## What to build
A script/module to completely download the 480p proxy file, benchmarking single vs multiple connection counts (e.g. via aria2 or Python async) to prove concurrency viability.

## Acceptance criteria
- [ ] Downloads full 480p proxy file.
- [ ] Reports speed difference between 1 and N connections.
- [ ] Code under 600 lines.

## Blocked by
#1
"""
    },
    3: {
        "title": "C. LosslessCut v3.69.0 LLC -> cut segments",
        "body": f"""## Parent
#{spec_id}

## What to build
A parser that takes a valid v3.69.0 `.llc` file and reliably extracts the exact cut segments (start/end times).

## Acceptance criteria
- [ ] Correctly reads `.llc` JSON structure.
- [ ] Returns a list of start and end timestamps.
- [ ] Code under 600 lines.

## Blocked by
None
"""
    },
    4: {
        "title": "D. Origin discovery -> safe Range fetch",
        "body": f"""## Parent
#{spec_id}

## What to build
A module to discover the Origin media URL for a file, and perform a safe Range fetch.

## Acceptance criteria
- [ ] Obtains Origin URL.
- [ ] Performs safe Range fetch.
- [ ] ABORTs immediately if server responds with 200 OK (full file) instead of 206 Partial Content.
- [ ] Code under 600 lines.

## Blocked by
#1
"""
    },
    5: {
        "title": "E. End-to-end PikPak -> proxy -> LLC -> selected Origin segments",
        "body": f"""## Parent
#{spec_id}

## What to build
The integration of the entire flow: Share URL -> download 480p -> read LLC -> discover Origin -> safe Range fetch of only the cut segments.

## Acceptance criteria
- [ ] End-to-end execution of the pipeline.
- [ ] Outputs the correctly extracted Origin segments.
- [ ] Code under 600 lines.

## Blocked by
#2, #3, #4
"""
    }
}

for i in range(1, 6):
    print(f"Updating issue #{i}...")
    # write body to temp file to avoid quoting issues
    with open("temp_body.md", "w", encoding="utf-8") as f:
        f.write(issue_updates[i]["body"])
    
    run_cmd(f'gh issue edit {i} --title "{issue_updates[i]["title"]}" --body-file temp_body.md --add-label "ready-for-agent" --remove-label "needs-triage"')
    print(f"Issue #{i} updated.")

print("Done.")
