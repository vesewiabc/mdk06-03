"""Юнит-тесты чистых утилит: парсинг, пароли, безопасные URL."""
import pytest

from utils import is_safe_url, money, password_ok, safe_float, safe_int


class TestSafeFloat:
    @pytest.mark.parametrize("raw,expected", [
        ("3.14", 3.14),
        ("3,14", 3.14),
        ("  10  ", 10.0),
        ("-0.5", -0.5),
    ])
    def test_ok(self, raw, expected):
        assert safe_float(raw) == expected

    @pytest.mark.parametrize("raw", [
        None, "", "abc", "nan", "inf", "-inf", "1e999", [1], {"a": 1},
    ])
    def test_reject(self, raw):
        assert safe_float(raw) is None

    def test_bounds(self):
        assert safe_float("5", min_=10) is None
        assert safe_float("15", max_=10) is None
        assert safe_float("10", min_=10, max_=10) == 10.0


class TestSafeInt:
    @pytest.mark.parametrize("raw,expected", [("42", 42), (" 7 ", 7), ("-3", -3)])
    def test_ok(self, raw, expected):
        assert safe_int(raw) == expected

    @pytest.mark.parametrize("raw", ["1.5", "1e5", "nan", "", "abc", None, []])
    def test_reject(self, raw):
        assert safe_int(raw) is None

    def test_bounds(self):
        assert safe_int("5", min_=10) is None
        assert safe_int("15", max_=10) is None


class TestMoney:
    def test_rounding_half_up(self):
        assert money("1.005") == 1.01
        assert money(2.344) == 2.34

    @pytest.mark.parametrize("raw", [None, "abc", float("nan"), float("inf")])
    def test_invalid(self, raw):
        assert money(raw) == 0.0


class TestIsSafeUrl:
    @pytest.mark.parametrize("target", [
        "/", "/orders/", "/orders/?x=1",
        "/auth/login?next=/orders/",
    ])
    def test_ok(self, target):
        assert is_safe_url(target) is True

    @pytest.mark.parametrize("target", [
        None, "",  # пустые
        "//evil.com", "http://evil.com", "https://x.io/a",
        "javascript:alert(1)", "data:text/html,x",
        "/\\evil.com",                       # backslash
        "/foo/../etc/passwd",                # traversal
        "/foo//bar",                         # двойной слэш
        "/x\r\nSet-Cookie: a=b",             # CRLF
        "/x%0d%0aInjected: yes",             # url-encoded CRLF
        "x" * 3000,                          # слишком длинный
    ])
    def test_reject(self, target):
        assert is_safe_url(target) is False


class TestPasswordOk:
    def test_strong(self):
        assert password_ok("Sunflower42!Qwe", username="alice") is None

    def test_too_short(self):
        assert password_ok("Aa1") is not None

    def test_no_digit(self):
        assert password_ok("OnlyLettersHere") is not None

    def test_no_letter(self):
        assert password_ok("1234567890123") is not None

    def test_common(self):
        assert password_ok("password123456") is not None

    def test_contains_username(self):
        assert password_ok("alice-pwd-42X", username="alice") is not None

    def test_contains_full_name(self):
        assert password_ok("Ivanov_pwd_42", full_name="Иван Иванов") is not None
        assert password_ok("IvanovX42aa", full_name="Ivanov Ivan") is not None

    def test_sequence(self):
        assert password_ok("Abcdef123456") is not None

    def test_too_uniform(self):
        assert password_ok("aaaaaaaa1111") is not None