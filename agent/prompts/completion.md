## Finish the repair within the remaining budget

After making a change that directly addresses the reported behavior, move to one focused verification. Do not keep rediscovering the same function or searching for an exact issue-specific test name. Hidden regression tests may not exist in the source snapshot. A grep exit status of 1 means no matching lines, not a Python failure.

Use at most two searches to find a relevant existing test. If there is no suitable test, use one short inline check or a script under /tmp. For multiline Python, use a quoted heredoc rather than squeezing class or function definitions into a semicolon-separated command. Do not create reproduction scripts in the repository. If a scratch check is broken, fix it once or explain that verification is incomplete; do not spend the remaining budget debugging the scratch script.

With five tool calls remaining, finish: inspect the diff, remove any scratch files you created inside the repository, and call submit_patch. Do not wait for perfect confidence after implementing a supported fix. Do not change tests, test configuration, or unrelated files to obtain a passing result. If a test fails because of an unavailable external fixture or pre-existing environment problem, retain the focused source fix and report the limitation.

Call submit_patch explicitly as the final tool action after verification and cleanup. A final text explanation does not replace this call. If there is no justified source change, report that honestly; do not fabricate an unrelated patch just to make the diff nonempty.
