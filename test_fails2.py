import pytest

class MockProcess:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode

def test_something(monkeypatch):
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: MockProcess())

    import subprocess
    print(subprocess.run(["gh"]).stdout)

test_something(pytest.MonkeyPatch())
