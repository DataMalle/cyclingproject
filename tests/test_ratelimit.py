from ratelimit import RateLimiter


def test_allows_then_blocks_fast_repeat():
    rl = RateLimiter(min_interval_s=60)
    s = {}
    assert rl.check(s) is None
    assert rl.check(s) is not None


def test_session_cap():
    rl = RateLimiter(per_session_max=2, min_interval_s=0)
    s = {}
    assert rl.check(s) is None
    assert rl.check(s) is None
    assert rl.check(s) is not None


def test_global_daily_cap_across_sessions():
    rl = RateLimiter(global_daily_max=2, min_interval_s=0)
    assert rl.check({}) is None
    assert rl.check({}) is None
    assert rl.check({}) is not None
