"""Guard the test environment as well as the application regressions."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TestPipelineConfiguration(unittest.TestCase):
    def test_pytest_is_declared_as_a_test_only_dependency(self):
        requirements = (ROOT / "requirements-test.txt").read_text(encoding="utf-8")
        self.assertIn("-r requirements-build.txt", requirements.splitlines())
        self.assertRegex(requirements, r"(?m)^pytest>=\d+\.\d+\.\d+,<\d+$")
        for filename in ("requirements.txt", "requirements-build.txt"):
            with self.subTest(filename=filename):
                self.assertNotRegex((ROOT / filename).read_text(encoding="utf-8"), r"(?mi)^pytest\b")

    def test_ci_and_release_verification_install_and_run_the_full_suite(self):
        for filename in ("ci.yml", "release.yml"):
            with self.subTest(workflow=filename):
                workflow = (ROOT / ".github" / "workflows" / filename).read_text(encoding="utf-8")
                if filename == "release.yml":
                    workflow = workflow.split("\n  windows:\n", 1)[0]
                self.assertIn("python -m pip install -r requirements-test.txt", workflow)
                self.assertIn("python -m pytest -v tests", workflow)
                self.assertIn("            requirements-test.txt", workflow)
                self.assertIn("pip-audit -r requirements.txt", workflow)

    def test_release_build_jobs_keep_the_build_only_environment(self):
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        for job, following in (("windows", "linux"), ("linux", "publish")):
            with self.subTest(job=job):
                block = workflow.split(f"\n  {job}:\n", 1)[1].split(f"\n  {following}:\n", 1)[0]
                self.assertIn("python -m pip install -r requirements-build.txt", block)
                self.assertNotIn("requirements-test.txt", block)
