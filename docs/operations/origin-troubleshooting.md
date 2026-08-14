# Origin Troubleshooting Runbook

This guide defines the deterministic diagnostic order for troubleshooting PikPak LLC Origin failures.

## Core Invariants

1. **416 != Expiration Evidence**: An HTTP 416 (Range Not Satisfiable) or CDN rejection on anonymous media links does not indicate token expiration or file corruption.
2. **MEDIA_ORIGIN Failure != Missing File**: Anonymous `MEDIA_ORIGIN` links traverse public CDN edge caches that may behave differently from core storage.
3. **Authenticated Original Finite Range is Authoritative**: Only a finite Range read via authenticated transport (`rclone --pikpak-no-media-link`) serves as definitive diagnostic evidence for file integrity.
4. **File Existence != Successful Extraction**: A 0-byte or corrupt file on disk does not satisfy completion gates.
5. **Exit Code 0 != Completion Gate**: Process termination with returncode 0 is insufficient; all outputs must pass strict media and stream validation.

---

## Diagnostic Decision Tree

Follow this exact diagnostic order. Do not jump directly to infrastructure corruption or network failure theories.

```
[Production Failure Encountered]
               │
               ▼
   1. Operator Preflight Check
      - Is master clean? Is operator preflight PASS?
      - Is origin_segment_extractor.py absent?
      ├─ FAIL ──► Stop; clean worktree or isolate legacy operator files.
      └─ PASS ──► Proceed to Step 2.
               │
               ▼
   2. Profile & Target Resolution
      - Is DPAPI profile provisioned and valid?
      - Does the target media filename resolve to exactly 1 remote file?
      ├─ FAIL ──► Run profile setup (python -m pikpak_llc.profile_setup).
      └─ PASS ──► Proceed to Step 3.
               │
               ▼
   3. Budget & Safety Fuse
      - Is estimated selected duration >= 80% hard cap? (PROJECT_BUDGET_BLOCKED)
      - Did transfer exceed max origin budget during extraction? (HARD_FUSE_HIT)
      ├─ YES ──► Report budget blockage; do not guess corruption.
      └─ NO  ──► Proceed to Step 4.
               │
               ▼
   4. Authenticated Original Finite Range Probe
      - Test 64 KiB slice at target offset via authenticated rclone (--pikpak-no-media-link).
      ├─ FAIL ──► Document actual exit code and bytes; record AUTH_ORIGINAL_BAD_RANGE.
      └─ PASS ──► Disproves file corruption/hole hypotheses; proceed to Step 5.
               │
               ▼
   5. Integration & FFmpeg Execution
      - Did FFmpeg fail to run or terminate abnormally?
      ├─ YES ──► Inspect FFmpeg stderr, process flags (-map 0 -c copy).
      └─ NO  ──► Proceed to Step 6.
               │
               ▼
   6. Output Validation Gate
      - Is output file non-empty and playable (ffprobe duration > 0)?
      - Are all source video/audio streams preserved?
      ├─ FAIL ──► Report OUTPUT_VALIDATION_FAILED.
      └─ PASS ──► Extraction Verified.
```

---

## Incident Response Policy

During active user media operations:
- **Do not modify production source code in the canonical worktree.**
- If unexpected behavior occurs:
  1. Stop media operations.
  2. Preserve safe diagnostic evidence and logs.
  3. File a GitHub Bug Issue.
  4. Reproduce and fix only in an isolated development worktree (`_codex-temp-*`).
  5. Run TDD, test suite, and code review.
  6. Submit a Draft Pull Request for Browser Review Lead approval.
  7. After merge, sync canonical `master` and resume.
