import json
from typing import List, Tuple, Optional

def parse_llc(file_path: str) -> List[Tuple[Optional[float], Optional[float]]]:
    """
    Parses a LosslessCut (.llc) project file (v3.69.0) and returns a list of cut segments.
    
    Args:
        file_path: Path to the .llc file.
        
    Returns:
        A list of tuples representing cut segments: (start_time, end_time).
        Times are in seconds. None represents the start or end of the media.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse LLC file '{file_path}': invalid JSON ({e})")
    except Exception as e:
        raise ValueError(f"Failed to read LLC file '{file_path}': {e}")
        
    if not isinstance(data, dict):
        raise ValueError("Invalid LLC format: root must be a JSON object.")
        
    cut_segments_raw = data.get("cutSegments")
    if cut_segments_raw is None:
        raise ValueError("Invalid LLC format: missing 'cutSegments'.")
        
    if not isinstance(cut_segments_raw, list):
        raise ValueError("Invalid LLC format: 'cutSegments' must be a list.")
        
    segments = []
    for i, seg in enumerate(cut_segments_raw):
        if not isinstance(seg, dict):
            raise ValueError(f"Invalid segment at index {i}: must be an object.")
            
        start = seg.get("start")
        end = seg.get("end")
        
        if start is not None and not isinstance(start, (int, float)):
            raise ValueError(f"Invalid start time at index {i}: must be a number.")
        if end is not None and not isinstance(end, (int, float)):
            raise ValueError(f"Invalid end time at index {i}: must be a number.")
            
        if start is not None:
            start = float(start)
        if end is not None:
            end = float(end)
            
        segments.append((start, end))
        
    return segments
