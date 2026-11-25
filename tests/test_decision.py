"""Decision expiry validation stays fail-closed before consulting Git."""
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from aak.decision import validate_decision


class DecisionValidationTests(unittest.TestCase):
    repo_root = Path("/local/example-repo")

    def decision(self, expires_at="2999-01-01T00:00:00+00:00"):
        return {"expiresAt": expires_at, "branch": "task/example", "baseSha": "a" * 40}

    def test_malformed_expiry_denied_without_git(self):
        values = ["2999-01-01T00:00:00", "2999-01-01", None, 42, True, [], {}, "invalid"]
        for value in values:
            with self.subTest(expires_at=value), \
                    patch("aak.decision.current_branch") as branch, \
                    patch("aak.decision.subprocess.run") as run:
                valid, reason = validate_decision(self.decision(value), self.repo_root)
                self.assertFalse(valid)
                self.assertTrue(reason.startswith("malformed decision:"), reason)
                branch.assert_not_called()
                run.assert_not_called()

    def test_missing_expiry_denied_without_git(self):
        with patch("aak.decision.current_branch") as branch, \
                patch("aak.decision.subprocess.run") as run:
            valid, reason = validate_decision({}, self.repo_root)
            self.assertFalse(valid)
            self.assertTrue(reason.startswith("malformed decision:"), reason)
            branch.assert_not_called()
            run.assert_not_called()

    def test_aware_future_expiry_checks_branch_and_ancestry(self):
        for expiry in ["2999-01-01T00:00:00+00:00", "2999-01-01T01:00:00+01:00"]:
            with self.subTest(expires_at=expiry), \
                    patch("aak.decision.current_branch", return_value="task/example") as branch, \
                    patch("aak.decision.subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as run:
                self.assertEqual(validate_decision(self.decision(expiry), self.repo_root), (True, "valid"))
                branch.assert_called_once_with(self.repo_root)
                run.assert_called_once_with(
                    ["git", "-C", str(self.repo_root), "merge-base", "--is-ancestor", "a" * 40, "HEAD"],
                    capture_output=True, timeout=10,
                )

    def test_expired_decision_denied_without_git(self):
        with patch("aak.decision.current_branch") as branch, \
                patch("aak.decision.subprocess.run") as run:
            self.assertEqual(
                validate_decision(self.decision("2000-01-01T00:00:00+00:00"), self.repo_root),
                (False, "task decision expired"),
            )
            branch.assert_not_called()
            run.assert_not_called()

    def test_branch_change_denied_without_ancestry_check(self):
        with patch("aak.decision.current_branch", return_value="other"), \
                patch("aak.decision.subprocess.run") as run:
            self.assertEqual(
                validate_decision(self.decision(), self.repo_root),
                (False, "branch changed (task/example -> other)"),
            )
            run.assert_not_called()

    def test_nonancestor_decision_denied(self):
        with patch("aak.decision.current_branch", return_value="task/example"), \
                patch("aak.decision.subprocess.run", return_value=subprocess.CompletedProcess([], 1)):
            self.assertEqual(
                validate_decision(self.decision(), self.repo_root),
                (False, "HEAD is no longer descended from baseSha"),
            )


if __name__ == "__main__":
    unittest.main()
