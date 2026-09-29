numbers = {i for i in [1,2,3]}
print(type(numbers))
try:
    print(len(numbers))
except Exception as e:
    print("Error:", e)
