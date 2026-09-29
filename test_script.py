sibling_ids = sorted(i for i in [1,2,3])
print(type(sibling_ids))
try:
    print(len(sibling_ids))
except Exception as e:
    print("Error:", e)
