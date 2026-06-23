import unittest
import sys
from pathlib import Path

# Add the scripts/ci directory to sys.path so we can import the module
sys.path.insert(0, str(Path(__file__).resolve().parent))

from opencode_review_normalize_output import iter_json_objects

class TestIterJsonObjects(unittest.TestCase):
    def test_pure_json(self):
        text = '{"key": "value"}'
        result = iter_json_objects(text)
        self.assertEqual(result, [{"key": "value"}])

    def test_json_in_prose(self):
        text = 'Here is some prose.\n```json\n{"key": "value"}\n```\nMore prose.'
        result = iter_json_objects(text)
        self.assertEqual(result, [{"key": "value"}])

    def test_multiple_json_objects(self):
        text = 'First object: {"a": 1}. Second object: {"b": 2}.'
        result = iter_json_objects(text)
        self.assertEqual(result, [{"a": 1}, {"b": 2}])

    def test_invalid_json(self):
        text = 'This is not json: {abc}. But this is: {"d": 4}.'
        result = iter_json_objects(text)
        self.assertEqual(result, [{"d": 4}])

    def test_no_json(self):
        text = 'There is no JSON here at all.'
        result = iter_json_objects(text)
        self.assertEqual(result, [])

if __name__ == '__main__':
    unittest.main()
