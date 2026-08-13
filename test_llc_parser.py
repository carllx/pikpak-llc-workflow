import pytest
import tempfile
import json
import os
from llc_parser import parse_llc

def test_parse_llc_success():
    llc_data = {
        "version": 1,
        "mediaFileName": "test.mp4",
        "cutSegments": [
            {"start": 10.5, "end": 20.0, "name": "seg1"},
            {"start": 30.0, "end": 45.1},
            {"end": 60.0},
            {"start": 70.0}
        ]
    }
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.llc', encoding='utf-8') as f:
        json.dump(llc_data, f)
        filepath = f.name

    try:
        segments = parse_llc(filepath)
        assert len(segments) == 4
        assert segments[0] == (10.5, 20.0)
        assert segments[1] == (30.0, 45.1)
        assert segments[2] == (None, 60.0)
        assert segments[3] == (70.0, None)
    finally:
        os.remove(filepath)

def test_parse_llc_missing_cut_segments():
    llc_data = {
        "version": 1,
        "mediaFileName": "test.mp4"
    }
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.llc', encoding='utf-8') as f:
        json.dump(llc_data, f)
        filepath = f.name

    try:
        with pytest.raises(ValueError, match="missing 'cutSegments'"):
            parse_llc(filepath)
    finally:
        os.remove(filepath)

def test_parse_llc_invalid_json():
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.llc', encoding='utf-8') as f:
        f.write("{invalid json")
        filepath = f.name

    try:
        with pytest.raises(ValueError, match="invalid JSON"):
            parse_llc(filepath)
    finally:
        os.remove(filepath)

def test_parse_llc_invalid_segment_format():
    llc_data = {
        "version": 1,
        "cutSegments": [
            {"start": "not-a-number"}
        ]
    }
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.llc', encoding='utf-8') as f:
        json.dump(llc_data, f)
        filepath = f.name

    try:
        with pytest.raises(ValueError, match="must be a number"):
            parse_llc(filepath)
    finally:
        os.remove(filepath)
