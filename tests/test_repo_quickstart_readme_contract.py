from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RepoQuickstartReadmeContractTests(unittest.TestCase):
    def test_chinese_readme_leads_with_windows_setup_and_keeps_zip_fallback(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8-sig")
        self.assertIn('CodexBridge-Setup.exe', text)
        self.assertIn('Windows 10/11：推荐安装包', text)
        self.assertIn('Start CodexBridge.cmd', text)
        self.assertIn('Start CodexBridge.command', text)
        self.assertIn('Windows 源码 ZIP 仍然保留', text)

    def test_english_readme_leads_with_windows_setup_and_keeps_zip_fallback(self):
        text = (ROOT / "README.en.md").read_text(encoding="utf-8-sig")
        self.assertIn('CodexBridge-Setup.exe', text)
        self.assertIn('Windows 10/11: use the installer', text)
        self.assertIn('Start CodexBridge.cmd', text)
        self.assertIn('Start CodexBridge.command', text)
        self.assertIn('Windows repository ZIP is still supported', text)


if __name__ == "__main__":
    unittest.main()
