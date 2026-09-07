import unittest

from services.api import get_user_completion_progress


class CompletionProgressClient:
    def __init__(self):
        self.offsets = []

    async def get(self, endpoint, params, *, request_type):
        self.offsets.append(params["o"])
        offset = params["o"]
        count = 500 if offset == 0 else 100
        return {
            "Count": count,
            "Total": 600,
            "Results": [{"GameID": offset + index} for index in range(count)],
        }


class ApiHelperTests(unittest.IsolatedAsyncioTestCase):
    async def test_completion_progress_fetches_all_pages(self):
        client = CompletionProgressClient()

        progress = await get_user_completion_progress(
            client, "player", request_type="achievement"
        )

        self.assertEqual(client.offsets, [0, 500])
        self.assertEqual(progress.total, 600)
        self.assertEqual(len(progress.results), 600)
