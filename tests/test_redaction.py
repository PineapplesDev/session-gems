import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import collect


class Redaction(unittest.TestCase):
    def check(self, raw, banned):
        out = collect.redact(raw)
        self.assertNotIn(banned, out, out)
        return out

    def test_secrets(self):
        self.check("key sk-ant-api03-ABCDEFGHIJKLMNOP1234", "ABCDEFGHIJKLMNOP1234")
        self.check("gh token ghp_ABCDEFGHIJKLMNOPQRSTUVWX", "ABCDEFGHIJKLMNOPQRSTUVWX")
        self.check("jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTYifQ.SflKxwRJSMeKKF2QT4fw", "SflKxwRJSMeKKF2QT4fw")
        self.check("Authorization: Bearer abcdefghijklmnop.qrstuv", "abcdefghijklmnop")
        self.check("OPENAI_API_KEY=whatever123", "whatever123")
        self.check('{"password": "hunter2hunter2"}', "hunter2")
        self.check("mail jane.doe@example.com now", "jane.doe@example.com")
        self.check("db postgres://u:p@host:5432/db", "u:p@host")
        self.check("sha 0123456789abcdef0123456789abcdef01234567", "0123456789abcdef0123456789abcdef")
        self.check("blob QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVphYmNkZWZnaGlq", "QUJDREVGR0hJSktMTU5PUFFS")

    def test_paths_survive(self):
        p = "/opt/work/some-very-long-project-directory-name/packages/app-component-library/src/index.ts"
        self.assertIn("packages/app-component-library/src/index.ts", collect.redact(f"edited {p}"))

    def test_never_reads_auth_files(self):
        d = tempfile.mkdtemp()
        for name in ("auth.json", ".env", "token.txt", "credentials.json", "id_rsa"):
            path = os.path.join(d, name)
            open(path, "w").write("x")
            with self.assertRaises(PermissionError):
                collect.safe_open(path)


if __name__ == "__main__":
    unittest.main()
