import pathlib
p = pathlib.Path('scripts/ci/opencode_review_surfaces.py')
text = p.read_text()
new_text = text.replace(
    '        return "\\n".join(raw_output.splitlines()).strip()',
    '        return raw_output.replace("\\r\\n", "\\n").replace("\\r", "\\n").strip()'
)
p.write_text(new_text)
