import pytest

from web_dashboard.supabase_pagination import fetch_all_rows

class MockQuery:
    def __init__(self, data, count=None):
        self._data = data
        self.count = count

    def range(self, start, end):
        self._start = start
        self._end = end
        return self

    def execute(self):
        end = min(self._end + 1, len(self._data))
        return type('Result', (), {'data': self._data[self._start:end]})()

class MockTable:
    def __init__(self, data):
        self.data = data

    def select(self, *args, **kwargs):
        return MockQuery(self.data)

class MockSupabaseClient:
    def __init__(self, data):
        self.data = data

    def table(self, name):
        return MockTable(self.data)

class MockClient:
    def __init__(self, data):
        self.supabase = MockSupabaseClient(data)


def test_fetch_all_rows():
    data = [{'id': i} for i in range(2500)]
    client = MockClient(data)
    rows = fetch_all_rows(client, "dummy_table")
    assert len(rows) == 2500

if __name__ == "__main__":
    pytest.main(["test_fetch_all_rows.py"])
