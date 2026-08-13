import json5
import os

def parse_llc(file_path):
    """
    Parses a LosslessCut v3.69.0 project file (.llc).
    
    LosslessCut outputs files using a JSON5 / JavaScript Object Literal syntax.
    This parser uses the standard-compliant json5 package.
    
    Returns:
        list[dict]: A list of segments with 'start' and 'end' float values.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"LLC file not found: {file_path}")
        
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
        
    try:
        data = json5.loads(content)
    except Exception as e:
        raise ValueError(f"Failed to parse LLC JSON5 file: {e}")
        
    extracted_segments = []
    
    if "cutSegments" not in data:
        raise ValueError("Missing 'cutSegments' array in LLC file.")
        
    cut_segments = data.get("cutSegments", [])
    if not isinstance(cut_segments, list):
        raise ValueError("'cutSegments' must be an array.")
        
    for seg in cut_segments:
        if not isinstance(seg, dict):
            continue
        if "start" in seg and "end" in seg:
            start_val = float(seg["start"])
            end_val = float(seg["end"])
            if end_val <= start_val:
                raise ValueError(f"Invalid segment: end ({end_val}) is not greater than start ({start_val})")
            
            extracted_segments.append({
                "start": start_val,
                "end": end_val
            })
            
    return extracted_segments

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        segs = parse_llc(sys.argv[1])
        print(f"Parsed {len(segs)} segments:")
        for s in segs:
            print(f"  Start: {s['start']:.3f}, End: {s['end']:.3f}")
    else:
        print("Usage: python llc_parser.py <file.llc>")
