from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RepoQuickstartReadmeContractTests(unittest.TestCase):
    def test_chinese_readme_leads_with_safe_windows_release_zip(self):
        text = (ROOT / "README.md").read_text(encoding="utf-8-sig")
        self.assertIn('CodexBridge-Windows.zip', text)
        self.assertIn('Windows 10/11：推荐 Release ZIP', text)
        self.assertIn('Start CodexBridge.cmd', text)
        self.assertIn('Start CodexBridge.command', text)
        self.assertIn('不再分发预编译 `CodexBridge-Setup.exe`', text)
        self.assertIn('不要为了运行 CodexBridge 关闭 Defender', text)

    def test_english_readme_leads_with_safe_windows_release_zip(self):
        text = (ROOT / "README.en.md").read_text(encoding="utf-8-sig")
        self.assertIn('CodexBridge-Windows.zip', text)
        self.assertIn('Windows 10/11: recommended Release ZIP', text)
        self.assertIn('Start CodexBridge.cmd', text)
        self.assertIn('Start CodexBridge.command', text)
        self.assertIn('does not distribute a prebuilt `CodexBridge-Setup.exe`', text)
        self.assertIn('Do not disable Defender', text)


if __name__ == "__main__":
    unittest.main()
