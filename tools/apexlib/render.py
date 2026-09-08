from pathlib import Path


def swatches(path: Path) -> dict:
    """Find wide adjacent red, green and blue bars in an unmodified QMP PPM."""
    with path.open('rb') as stream:
        assert stream.readline().strip() == b'P6'
        width, height = map(int, stream.readline().split())
        assert stream.readline().strip() == b'255'
        data = stream.read()
    assert len(data) == width * height * 3
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
