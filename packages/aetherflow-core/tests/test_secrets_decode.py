from aetherflow.core.runtime.secrets import SecretsProvider


def test_decode_always_called():
    calls = {"n": 0}

    def decode(v: str) -> str:
        calls["n"] += 1
        return "X" + v

    p = SecretsProvider(decode=decode)
    assert p.decode("abc") == "Xabc"
    assert calls["n"] == 1
