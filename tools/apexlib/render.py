from pathlib import Path


def ppm(path: Path):
    with path.open('rb') as stream:
        assert stream.readline().strip() == b'P6'
        width, height = map(int, stream.readline().split())
        assert width > 0 and height > 0
        assert stream.readline().strip() == b'255'
        data = stream.read()
    assert len(data) == width * height * 3
    return width, height, data


def surface_change(before: Path, after: Path) -> dict:
    """Reject an unchanged Shell capture; visual review still identifies the menu."""
    width, height, first = ppm(before)
    other_width, other_height, second = ppm(after)
    assert (width, height) == (other_width, other_height), 'Display size changed during the capture'
    # Ignore the top bar so a clock tick cannot pass this check.
    begin = min(40, height) * width * 3
    changed = sum(max(abs(a-b) for a, b in zip(first[i:i+3], second[i:i+3])) >= 20
                  for i in range(begin, len(first), 3))
    minimum = max(5000, width * height // 100)
    assert changed >= minimum, 'Shell surface did not visibly change after its shortcut'
    return {'changed_pixels': changed, 'minimum_pixels': minimum,
            'visual_identification': 'NOT TESTED'}


def swatches(path: Path) -> dict:
    """Find wide adjacent red, green and blue bars in an unmodified QMP PPM."""
    width, height, data = ppm(path)
    matched = 0
    for y in range(0, height, 4):
        runs = []
        current, start = None, 0
        for x in range(width):
            offset = (y * width + x) * 3
            r, g, b = data[offset:offset + 3]
            color = 'r' if r > 180 and g < 90 and b < 90 else 'g' if g > 140 and r < 100 and b < 120 else 'b' if b > 180 and r < 100 and g < 120 else None
            if color != current:
                if current:
                    runs.append((current, start, x))
                current, start = color, x
        if current:
            runs.append((current, start, width))
        for a, b, c in zip(runs, runs[1:], runs[2:]):
            if (a[0], b[0], c[0]) == ('r', 'g', 'b') and min(end-begin for _, begin, end in (a,b,c)) >= 80 and b[1]-a[2] <= 4 and c[1]-b[2] <= 4:
                matched += 1
                break
    assert matched >= 20, 'The application color bars are not visibly rendered'
    return {'width': width, 'height': height, 'matched_rows_at_stride_four': matched}
