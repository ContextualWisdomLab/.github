with open("scripts/ci/pr_review_merge_scheduler.py", "r") as f:
    lines = f.readlines()

out_lines = []
in_conflict = False
conflict_part = 0 # 0=none, 1=HEAD, 2=origin/main

for line in lines:
    if line.startswith("<<<<<<< HEAD"):
        in_conflict = True
        conflict_part = 1
        continue
    elif line.startswith("======="):
        conflict_part = 2
        continue
    elif line.startswith(">>>>>>> origin/main"):
        in_conflict = False
        conflict_part = 0
        continue

    if in_conflict:
        if conflict_part == 1:
            out_lines.append(line)
        elif conflict_part == 2:
            if "sample =" in line:
                pass # keep the HEAD's `sample: dict[str, Any] = {` which is better for typing
            elif "Exercise scheduler invariants" in line:
                out_lines.insert(len(out_lines)-3, line) # insert docstring before test_fetch
    else:
        out_lines.append(line)

with open("scripts/ci/pr_review_merge_scheduler.py", "w") as f:
    f.writelines(out_lines)
