## Finish the repair within the remaining budget

You have about five minutes and 60 tool calls. A submitted partial fix can pass the verification tests; an unfinished exploration cannot. Speed is part of correctness here.

1. **Edit before exploring.** If the problem statement contains replacement code, apply it as your first action. Otherwise read only the function you are changing, then edit. By your sixth tool call you must have written a change.
2. **There is no visible test to find.** Graded tests are applied after you submit and are not in the workspace. Do not search `tests/` for issue-specific names; a grep exit status of 1 means no match, not a failure.
3. **If `edit_file` fails, switch immediately.** Escaped backslashes, changed indentation, or a non-unique match mean do not retry the same `old_string`. Use `write_file` on that file with the complete corrected function, preserving the surrounding indentation.
4. **One check, after the edit.** Run at most one targeted pytest command (or a script under `/tmp`). Never run the full suite and never create files in the repository.
5. **Submit before the clock.** With five tool calls left, inspect the diff, remove any scratch files, and call `submit_patch`. Do not wait for perfect confidence. If no justified source change exists, say so; do not fabricate a patch.
