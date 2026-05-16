import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

from helpers import REPO_ROOT


class PiInstallerSmokeTests(unittest.TestCase):
    def run_installer(self, args, env):
        result = subprocess.run(
            ["node", "install.js", *args],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        return result

    def test_pi_install_writes_managed_extension_manifest_and_repo_link(self):
        if shutil.which("node") is None:
            self.skipTest("node is not available")

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            home = root / "home"
            pi_agent_dir = root / "pi-agent"
            home.mkdir()

            env = os.environ.copy()
            env.update(
                {
                    "HOME": str(home),
                    "PI_CODING_AGENT_DIR": str(pi_agent_dir),
                }
            )

            extension_dir = pi_agent_dir / "extensions" / "ghostty-peon"
            extension_dir.mkdir(parents=True)
            (extension_dir / "hook-runner.ts").write_text("// Managed by ghostty-peon install.js\nold copied module")

            self.run_installer(["--target", "pi", "--yes", "--force"], env)

            installed_index = extension_dir / "index.ts"
            src_link = extension_dir / "src"
            repo_link = extension_dir / "repo"
            manifest_path = home / ".ghostty-peon" / ".manifest.json"

            self.assertTrue(installed_index.exists())
            installed_source = installed_index.read_text()
            self.assertIn("Managed by ghostty-peon install.js", installed_source)
            self.assertIn('export { default } from "./src/index.js";', installed_source)
            self.assertFalse((extension_dir / "hook-runner.ts").exists())

            self.assertTrue(src_link.is_symlink())
            self.assertEqual(os.path.realpath(src_link), os.path.realpath(REPO_ROOT / "pi-extension"))
            self.assertTrue(repo_link.is_symlink())
            self.assertEqual(os.path.realpath(repo_link), os.path.realpath(REPO_ROOT))

            manifest = json.loads(manifest_path.read_text())
            self.assertIn("pi", manifest["targets"])
            self.assertEqual(manifest["targets"]["pi"]["indexPath"], str(installed_index))
            self.assertEqual(manifest["targets"]["pi"]["srcLink"], str(src_link))
            self.assertEqual(manifest["targets"]["pi"]["repoLink"], str(repo_link))

    def test_pi_uninstall_removes_managed_extension_modules(self):
        if shutil.which("node") is None:
            self.skipTest("node is not available")

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            home = root / "home"
            pi_agent_dir = root / "pi-agent"
            home.mkdir()

            env = os.environ.copy()
            env.update(
                {
                    "HOME": str(home),
                    "PI_CODING_AGENT_DIR": str(pi_agent_dir),
                }
            )

            self.run_installer(["--target", "pi", "--yes", "--force"], env)
            extension_dir = pi_agent_dir / "extensions" / "ghostty-peon"
            self.assertTrue((extension_dir / "src").is_symlink())
            self.assertTrue((extension_dir / "repo").is_symlink())

            self.run_installer(["--uninstall", "--target", "pi", "--yes"], env)

            self.assertFalse(extension_dir.exists())
            manifest_path = home / ".ghostty-peon" / ".manifest.json"
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text())
                self.assertNotIn("pi", manifest.get("targets", {}))


if __name__ == "__main__":
    unittest.main()
