import time
import unittest

from tests.support import ROOT  # noqa: F401
from bayyinah.security import RateLimiter, TokenBucket, is_authorized


class TestAuth(unittest.TestCase):
    def test_dev_mode_allows_when_no_key_configured(self):
        self.assertTrue(is_authorized(None, None))
        self.assertTrue(is_authorized("anything", None))

    def test_rejects_missing_key(self):
        self.assertFalse(is_authorized(None, "secret"))

    def test_accepts_matching_key(self):
        self.assertTrue(is_authorized("secret", "secret"))

    def test_rejects_wrong_key(self):
        self.assertFalse(is_authorized("nope", "secret"))

    def test_ignores_surrounding_whitespace(self):
        self.assertTrue(is_authorized("  secret  ", "secret"))


class TestRateLimiter(unittest.TestCase):
    def test_bucket_drains_and_refills(self):
        bucket = TokenBucket(capacity=2, refill_per_second=100)
        self.assertTrue(bucket.allow()[0])
        self.assertTrue(bucket.allow()[0])
        allowed, retry = bucket.allow()
        self.assertFalse(allowed)
        self.assertGreaterEqual(retry, 0)
        time.sleep(0.05)
        self.assertTrue(bucket.allow()[0])

    def test_limiter_is_per_key(self):
        limiter = RateLimiter(per_minute=1)
        self.assertTrue(limiter.check("a")[0])
        self.assertFalse(limiter.check("a")[0])
        self.assertTrue(limiter.check("b")[0])


if __name__ == "__main__":
    unittest.main()
