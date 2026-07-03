import time
import unittest

from proxyspin import NoHealthyProxies, Proxy, ProxyPool, parse_proxy


class TestParse(unittest.TestCase):
    def test_url_with_auth(self):
        p = parse_proxy("http://user:p%40ss@10.0.0.1:8000")
        self.assertEqual((p.host, p.port, p.username, p.password), ("10.0.0.1", 8000, "user", "p@ss"))
        self.assertEqual(p.url, "http://user:p%40ss@10.0.0.1:8000")

    def test_socks(self):
        p = parse_proxy("socks5://10.0.0.1:1080")
        self.assertEqual(p.scheme, "socks5")

    def test_host_port(self):
        p = parse_proxy("10.0.0.1:8000")
        self.assertEqual(p, Proxy("10.0.0.1", 8000))

    def test_host_port_user_pass(self):
        p = parse_proxy("10.0.0.1:8000:alice:secret")
        self.assertEqual(p.username, "alice")
        self.assertEqual(p.password, "secret")

    def test_user_pass_at_host_port(self):
        p = parse_proxy("alice:secret@10.0.0.1:8000")
        self.assertEqual((p.username, p.password, p.port), ("alice", "secret", 8000))

    def test_invalid(self):
        for bad in ("", "hostonly", "10.0.0.1:notaport", "ftp://10.0.0.1:21", "a:1:b:c:d"):
            with self.assertRaises(ValueError, msg=bad):
                parse_proxy(bad)


class TestPool(unittest.TestCase):
    def proxies(self, n=3):
        return [f"10.0.0.{i}:8000" for i in range(1, n + 1)]

    def test_round_robin_cycles(self):
        pool = ProxyPool(self.proxies())
        seen = {pool.get().address for _ in range(3)}
        self.assertEqual(len(seen), 3)

    def test_dedup(self):
        pool = ProxyPool(["10.0.0.1:8000", "http://10.0.0.1:8000"])
        self.assertEqual(len(pool), 1)

    def test_cooldown_and_recovery(self):
        pool = ProxyPool(self.proxies(2), max_failures=1, cooldown=0.05)
        bad = pool.get()
        pool.mark_failed(bad)
        self.assertEqual(pool.healthy_count, 1)
        for _ in range(5):
            self.assertNotEqual(pool.get(), bad)
        time.sleep(0.06)
        self.assertEqual(pool.healthy_count, 2)

    def test_success_resets_failures(self):
        pool = ProxyPool(self.proxies(1), max_failures=2)
        p = pool.get()
        pool.mark_failed(p)
        pool.mark_ok(p)
        pool.mark_failed(p)
        self.assertEqual(pool.healthy_count, 1)  # streak broken, not banned

    def test_all_banned_raises(self):
        pool = ProxyPool(self.proxies(2), max_failures=1, cooldown=60)
        for _ in range(2):
            pool.mark_failed(pool.get())
        with self.assertRaises(NoHealthyProxies):
            pool.get()

    def test_sticky_keeps_proxy_per_key(self):
        pool = ProxyPool(self.proxies(3), strategy="sticky")
        first = pool.get(key="acct-1")
        for _ in range(5):
            self.assertEqual(pool.get(key="acct-1"), first)

    def test_sticky_reassigns_after_ban(self):
        pool = ProxyPool(self.proxies(2), strategy="sticky", max_failures=1, cooldown=60)
        first = pool.get(key="acct-1")
        pool.mark_failed(first)
        self.assertNotEqual(pool.get(key="acct-1"), first)

    def test_stats(self):
        pool = ProxyPool(self.proxies(1))
        p = pool.get()
        pool.mark_ok(p)
        self.assertEqual(pool.stats()[p.address]["successes"], 1)


class TestPlaywrightHelper(unittest.TestCase):
    def test_settings_with_auth(self):
        from proxyspin.playwright_helper import proxy_settings

        pool = ProxyPool(["http://u:p@10.0.0.1:8000"])
        settings = proxy_settings(pool)
        self.assertEqual(
            settings, {"server": "http://10.0.0.1:8000", "username": "u", "password": "p"}
        )

    def test_settings_bare_proxy(self):
        from proxyspin.playwright_helper import proxy_settings

        self.assertEqual(proxy_settings(Proxy("10.0.0.1", 8000)), {"server": "http://10.0.0.1:8000"})


if __name__ == "__main__":
    unittest.main()
