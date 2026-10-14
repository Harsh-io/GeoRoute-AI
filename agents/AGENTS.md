# GeoRoute AI — Mandatory Engineering Rules

You are working on an existing project, not starting a new project from scratch.

1. Inspect the repository, Git status, existing architecture, dependencies, documentation and tests before acting.
2. Never claim a feature exists, works, or has passed testing without inspecting the implementation and obtaining evidence.
3. Follow the Architect's approved task specification and interface contracts.
4. Modify only the files assigned to your task. Never overwrite another agent's work or change unrelated files.
5. Work in your own Git branch or worktree if you need to modify code. Never share a writable working directory with another coding session.
6. Do not replace working code with a new implementation without demonstrating why the change is necessary.
7. Never fabricate satellite data, elevation values, segmentation results, route metrics, test results or API responses.
8. Keep API keys, credentials and private configuration out of source control. Never delete user data or execute destructive commands without approval.
9. Run the relevant tests and report the actual commands, results, failures and limitations.
10. If a dependency, external service, model or dataset is unavailable, report the blocker explicitly. Do not silently substitute mock data.
11. Commit only approved, tested changes. Never merge directly into the integration branch without authorization.
12. Maintain documentation and report changed files, interfaces, dependencies and remaining work.

Every task must end with:
- Task status: PASS, FAIL or BLOCKED.
- Files inspected and changed.
- Tests executed and their actual results.
- Evidence supporting the status.
- Known limitations and unresolved issues.
- Exact next step or handoff required.


13. How agents should work together correctly
Use this workflow for every feature:
Step 1 — Architect approves the task
One specification, one owner, defined files, agreed inputs/outputs and acceptance criteria


Step 2 — Developers work in isolation
Each coding agent uses its own branch or worktree and implements only its assigned module.

Step 3 — QA verifies the output
Run actual tests, reproduce bugs and record evidence before a change is considered complete.

Step 4 — Reviewer independently audits
Check correctness, interfaces, security, geospatial assumptions and whether the evidence supports acceptance.

Step 5 — Integrate and checkpoint
The authorized integrator resolves conflicts, runs end-to-end tests and commits a verified working version.

## 14. Preserve Existing Working Code —Change only when the task assigned is different from the current repository in terms of libraries, framewrok or workflow 

GeoRoute AI is an existing project with implemented geospatial ingestion, raster preprocessing, CRS alignment, COG export and railway routing functionality. Your responsibility is to extend and complete this implementation, not rebuild it from scratch.

1. **Preserve working files:** Never delete, overwrite, replace or rewrite existing working files simply to implement a feature differently. Extend the existing implementation wherever possible.

2. **Inspect before editing:** Read the relevant source files, dependencies, tests and call sites before making changes. Establish the current behavior and identify what is already working.

3. **Minimal changes only:** Make the smallest targeted changes necessary to complete the assigned task. Avoid unrelated refactoring, renaming, restructuring, formatting changes or dependency upgrades.

4. **No unnecessary rewrites:** Do not create duplicate pipelines, routing engines, configuration systems, utilities or API layers when suitable implementations already exist.

5. **Protect verified functionality:** Preserve existing function signatures, configuration formats, output schemas, file paths and interfaces unless a documented requirement makes a change necessary.

6. **Prove the need for modifications:** Before changing working code, explain the specific missing functionality, defect or integration requirement that justifies the change.

7. **Establish a baseline:** Before editing, inspect `git status`, identify the current Git commit and run relevant existing tests when possible. Record existing failures separately from newly introduced failures.

8. **Respect existing changes:** Never discard, reset, revert, stash, overwrite or commit another agent's uncommitted work without explicit authorization. Never assume uncommitted changes are disposable.

9. **Protect data and configuration:** Do not delete or regenerate existing datasets, route outputs, configuration files, environment files, model weights or user-created artifacts unless explicitly authorized.

10. **Extend rather than replace:** When adding functionality, integrate it with existing modules through approved interfaces. Prefer adapters, new isolated modules and backward-compatible extensions over replacing working components.

11. **Verify regressions:** After every change, run the relevant new tests and existing regression tests. Confirm that previously working functionality remains intact. If a regression occurs, investigate and fix your own changes without blindly rewriting the project.

12. **Handle uncertain changes safely:** If a change requires a breaking interface modification, file deletion, major refactor, dependency replacement or migration, stop and request Architect approval before proceeding.

13. **No false completion claims:** A file being created, code compiling or a test passing does not prove that the complete feature works. Verify actual integration and behavior.

14. **Keep changes reviewable:** Report every modified, added and deleted file, explain why each change was necessary, and provide the relevant test evidence. Do not include unrelated modifications in a task's commit.

15. **Preserve rollback capability:** Work on the assigned branch or worktree, create focused commits after verification, and maintain a clear path to restore the previous working state.

### Mandatory pre-edit checklist

Before modifying any file, answer these questions:

- What functionality already exists?
- What exact requirement remains incomplete?
- Which specific files must change, and why?
- Can the feature be implemented without modifying working code?
- Which existing tests could detect regressions?
- Is the change within my assigned scope?

If these questions cannot be answered, continue investigating without editing.

### Mandatory completion checklist

Before reporting a task as complete:

- Confirm that only authorized files were changed.
- Confirm that existing functionality remains intact.
- Run relevant tests and report actual results.
- Verify compatibility with existing module contracts.
- Document any regressions, limitations or unresolved issues.
- Provide a concise change summary and evidence.

**Default decision: Preserve the existing implementation. Modify working code only when necessary, justified, authorized and verified.**

The most important new rule is that agents must never run destructive Git commands or overwrite another agent's uncommitted changes