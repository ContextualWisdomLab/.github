from scripts.ci.redact_sensitive_log import redact_text


def test_redact_sensitive_log():
    cases = [
        ("foopassword=supersecret", "foopassword=[REDACTED]"),
        ("xxapi_key=TOPSECRET", "xxapi_key=[REDACTED]"),
        ("123password=abc", "123password=[REDACTED]"),
        ("a123password=abc", "a123password=[REDACTED]"),
        ('""token"=123', '""token"=[REDACTED]'),
        ('password"token"=123', 'password"token"=[REDACTED]'),
        ("password", "password"),
        ("password password=123", "password password=[REDACTED]"),
        ("foobar password=123", "foobar password=[REDACTED]"),
        ("mytokenx=123", "mytokenx=[REDACTED]"),
        ("mytoken=123", "mytoken=[REDACTED]"),
        ("password =123", "password =[REDACTED]"),
        ('"x"token"=123', '"x"token"=[REDACTED]'),
        ("xxpassword", "xxpassword"),
        ("xxpassword xxpassword=123", "xxpassword xxpassword=[REDACTED]"),
        ('"password" = 123', '"password" = [REDACTED]'),
        ("not_asecret=123", "not_asecret=[REDACTED]"),
        ("", ""),
        ('""', '""'),
        ("token", "token"),
        ("token=", "token="),
        ("token={", "token=[REDACTED]"),
        ("token=\\", "token=[REDACTED]"),
        ('token="\\"', "token=[REDACTED]"),
        ('token="\\"abc', "token=[REDACTED]"),
        ('x token="123" y', "x token=[REDACTED] y"),
    ]
    for inp, expected in cases:
        assert redact_text(inp) == expected
