# Methodology: Change Discipline

How to land changes in this repository: issue granularity, PR
sizing, branch naming, anti-patterns. The companion to
[`agent-onboarding.md`](agent-onboarding.md), which covers
*context durability*. This document covers *change discipline* —
the two together form the agentic dev kit for this repo.

This document is **descriptive of how the repo is run**, not a
suggestion. Templates under `.github/ISSUE_TEMPLATE/` and
`.github/PULL_REQUEST_TEMPLATE.md` enforce it for new issues and PRs.

> **Inspired by**
> [`timwukp/Harness-agentic-AI-agent-best-practices-and-use-case/docs/DEVELOPMENT_WORKFLOW.md`](https://github.com/timwukp/Harness-agentic-AI-agent-best-practices-and-use-case/blob/main/docs/DEVELOPMENT_WORKFLOW.md).
> Adapted to use this repo's worked example (the phase 1–6
> install-friction stack) and to align with the existing
> agent-onboarding methodology.

---

## Why this discipline

We use **issue → fix → PR**, one logical change at a time, instead of
monolithic "big bang" PRs.

| Monolithic PR (avoid) | Iterative PRs (this repo) |
|---|---|
| 50 files changed, 30 unrelated concerns | One concern per PR |
| Reviewer must context-switch mid-review | Reviewer focuses on one thing |
| Hard to revert one bad change without losing the rest | Revert = single `git revert` |
| Issue history is implicit ("see commits") | Each fix has an explicit issue with a paper trail |
| Bus factor: only the author knows what's in there | Anyone can pick up any open issue |

**This applies even when you find many problems at once.** Audit
broadly, then file each finding as a separate issue. Don't try to
fix everything in one PR just because you discovered everything in
one read-through.

---

## The 5-step loop

```
┌──────────┐   ┌────────┐   ┌──────┐   ┌─────┐   ┌────────┐
│ DISCOVER │──▶│ TRIAGE │──▶│ GROUP│──▶│ FIX │──▶│ REVIEW │
└──────────┘   └────────┘   └──────┘   └─────┘   └────────┘
     ▲                                                │
     └────────────────── repeat ──────────────────────┘
```

### Step 1: Discover (audit broadly)

Before fixing anything, list **all** problems you can find:

- Read existing docs and code
- Compare claims (README, status tables) against reality (test logs,
  commit history)
- Find inconsistencies between files (doc says X, code does Y)
- Note out-of-date references and stale TODOs

**Output:** A flat list of all findings, no prioritization yet.

### Step 2: Triage

Apply this scale:

| Level | Meaning | Example |
|---|---|---|
| **P0** | Meta — blocks other work | Add CONTRIBUTING.md before doing 6 contribution-style fixes |
| **P1** | Bug or contradiction visible to users | README says X, code does Y |
| **P2** | Drift between code and docs | Architecture doc missing sections for code that exists |
| **P3** | Future improvement, not currently broken | Production hardening design |

This repo currently does **not** use `P0`/`P1`/`P2`/`P3` GitHub
labels. The scale is a triage tool, not a labeling requirement.
Use it in your head; record the priority in the issue body.

Also consider **relevance**: does fixing X unblock Y? If yes, X is
higher priority regardless of severity.

### Step 3: Group findings into issues

**One issue = one logical change with one acceptance criterion.**

Heuristics:

- ✅ Two badges + a paragraph all referencing the same out-of-date
  number → **one issue** (one logical fact)
- ✅ Three missing sections in the same doc → **one issue** (one
  doc, one purpose)
- ❌ "Fix all docs" → split into per-doc or per-concern issues
- ❌ "Add Bedrock collector + fix unrelated typo" → split

**Rule of thumb:** If you can't write a single sentence describing
what "done" looks like, the issue is too big.

### Step 4: Fix one issue at a time

For each issue:

1. **Branch** from `main` using the naming convention below.
2. **Commit** with focused messages. Reference the issue.
3. **Push** the branch.
4. **Open PR** using the PR template. Title mirrors the issue.
5. PR description includes `Closes #N` so GitHub auto-closes the
   issue on merge.

**Don't:**
- Bundle unrelated changes "while you're in there"
- Open a PR before the issue exists (except trivial typos and
  security hotfixes — see "When to deviate" below)
- Reuse a branch for a second issue

### Step 5: Review and iterate

- Wait for review before starting the next issue, *or* push the
  current PR before context-switching so the work is durable.
- Apply review feedback as new commits to the same branch — don't
  force-push during active review.
- Squash on merge if commits are noisy; keep them if each commit
  tells a coherent step.
- After merge, **delete the branch** (the merge commit retains the
  history).

---

## Stacked PRs (the exception, not the default)

When N issues are sequentially dependent and would block each other
if filed as parallel PRs, a **stacked PR** is acceptable:

```
main ◀── PR #N+1: feature A ◀── PR #N+2: feature B (base = #N+1) ◀── PR #N+3 …
```

Each PR's base is the previous PR's branch, not `main`. Merge in
order; retarget downstream PRs to `main` after each merge.

**Use this only when:**
- The work cannot be split into truly independent issues
- Each PR in the stack still passes its own acceptance criteria
- The stack is small (≤ 5 PRs); larger stacks become ungovernable

**Reference:** the phase 1–6 install-friction stack
([`docs/test-reports/phase6-rollup.md`](../test-reports/phase6-rollup.md))
applied this pattern correctly:

| PR | Base | Issues closed |
|---:|---|---|
| #34 | `main` | #23, #24, #27, #28, #33 |
| #35 | #34 branch | #25, #30, #32 |
| #36 | #35 branch | #31 |
| #37 | #36 branch | #26 |
| #38 | #37 branch | #29 |

The split was justified because phase 2 needed the script changes
from phase 1, phase 3 needed the kustomize overlays from phase 2,
etc. Each PR was independently mergeable but logically downstream.

If your work doesn't have this kind of hard sequential dependency,
default to filing parallel issues with one PR each, not a stack.

---

## Templates

The canonical versions live under `.github/`. The structures below
are the contract — the GitHub forms expand to the same shape.

### Issue: discussion (architectural)

```markdown
## Context
What's the situation, in 1–2 paragraphs.

## Working assumptions (read this first)
The maintainer's priors. State preferences explicitly.

## The architectural question
Comparison table if multiple paths.

## Why it's non-trivial for our setup
What's specific about this repo that makes the textbook answer wrong.

## Proposed direction
Best current guess; an anchor for discussion, not a decision.

## Open questions
Numbered list. What the next iteration resolves.

## Non-goals
What this issue is explicitly NOT about.

## Repo context
Links to AGENTS.md, related code paths, prior PRs.
```

Examples in this repo: #39, #41.

### Issue: bug or correctness

```markdown
## Problem
What is wrong, missing, or inconsistent. One paragraph.

## Evidence
- File:line references
- Commit SHAs
- Error logs / screenshots

## Proposed solution
Bullet list of changes intended.

## Acceptance criteria
- [ ] Concrete check 1
- [ ] Concrete check 2

## Priority
P0 / P1 / P2 / P3 — and why.

## Out of scope
What this issue explicitly does NOT cover.
```

### Pull request

```markdown
## Summary
Closes #N

One paragraph: what was wrong, what this PR changes.

## Changes
- `path/to/file1`: did X
- `path/to/file2`: did Y

## Verification
How a reviewer can confirm the change works:
- [ ] Local check: `cmd to run`
- [ ] Screenshot / output
- [ ] Re-run of CI

## Out of scope
What this PR does NOT change, but the issue mentioned.
Link to follow-up issue.

## Risk
Low / Medium / High — what could break if this is wrong.
```

---

## Naming conventions

### Branches

```
<type>/issue-<number>-<kebab-short-desc>
```

| Type | Use for |
|---|---|
| `fix` | Bug or correctness fix |
| `docs` | Documentation only |
| `feat` | New feature or capability |
| `refactor` | Code change with no behaviour change |
| `chore` | Build, dependencies, tooling |
| `test` | Tests only |

Examples:

- `fix/issue-44-otel-receiver-401-on-empty-key`
- `docs/issue-41-change-discipline-methodology`
- `feat/issue-42-bedrock-cloudwatch-collector`

For stacked PRs (the exception above), use a phase-prefixed name:

- `phase1/docs-scripts-fixes`, `phase2/kustomize-overlays`, etc.

### Commits

[Conventional Commits](https://www.conventionalcommits.org/) format
is **recommended**, not enforced. Existing history is mixed; new
work should converge on this format:

```
<type>(<optional scope>): <short summary>

<optional body>

<optional footer with Refs / Closes>
```

Examples:

- `fix(otel): reject 401 when api key header missing (#44)`
- `docs(methodology): add change-discipline doc (#41)`
- `feat(collectors): add Bedrock CloudWatch collector (#42)`

### Pull request titles

Same format as commit messages. The PR title is what shows up in
`git log` after squash-merge, so it matters.

---

## Anti-patterns to avoid

| Anti-pattern | Why it's bad |
|---|---|
| Big-bang PR with 30 unrelated changes | Unreviewable; can't revert one thing |
| Issue with no acceptance criteria | "Done" is a moving target |
| Branch named `update`, `temp`, `wip`, `main2` | Useless in `git log`; conflicts with parallel work |
| PR description "see commits" | Reviewer shouldn't have to reverse-engineer intent |
| Closing an issue without a merged PR | Loses traceability; future-you can't find the fix |
| Force-pushing during active review | Invalidates reviewer's in-progress comments |
| Mixing formatting changes with logic changes | Diff becomes unreadable; do formatting separately |
| Creating issue + PR simultaneously without thinking | Skips triage; you might be solving the wrong problem |
| Using stacked PRs when issues are actually independent | Manufactures sequential dependency; blocks parallel review |
| Ignoring `AGENTS.md` invariants in a PR | Re-litigates settled decisions; wastes reviewer time |

---

## Worked example: the phase 1–6 install-friction stack

This is the canonical worked example for this repo's discipline.
It is intentionally a *stacked* example because of sequential
dependencies — most PRs in this repo will not need this pattern.

**Discover (Step 1):** A fresh-install audit on a new EKS cluster
turned up 11 distinct install-friction problems — broken `envsubst`
flow, missing `--platform linux/amd64` in docs, missing IRSA policy
JSON, port mismatch in NetworkPolicy, missing Helm chart, etc.

**Triage (Step 2):** All 11 were P1 or P2 (visible install
breakage). No P0 meta-work needed — the methodology docs came
later, in a separate PR (#40).

**Group (Step 3):** The 11 were grouped into 5 phases by sequential
dependency:

- Phase 1 (5 issues): doc + script fixes — prerequisite for everything
- Phase 2 (3 issues): kustomize overlays — needed phase 1's variable
  resolution
- Phase 3 (1 issue): Alembic migrations — needed phase 2's Postgres
- Phase 4 (1 issue): Fargate detection — needed phase 3's lifespan
- Phase 5 (1 issue): Helm chart — packaging step on top of phase 4

**Fix (Step 4):** 5 stacked PRs (#34–#38), each with its own test
report under `docs/test-reports/`. A mid-stack regression
(`_check_or_apply_migrations` raising on SQLite tests) was caught
by CI on PRs #36/#37/#38 and fixed by force-pushing the corrected
parent SHA to all three downstream branches via the GitHub Git
Data API — preserving the stack relationship without merging
broken code.

**Review (Step 5):** Each PR merged in sequence after CI went green;
downstream PRs were retargeted to `main` after each merge. After
the final merge, all 5 feature branches were deleted.

**Result:** All 11 issues (#23–#33) closed. Test reports preserved
under [`docs/test-reports/`](../test-reports/). Rollup at
[`phase6-rollup.md`](../test-reports/phase6-rollup.md).

**What we did NOT do:**

- ❌ One PR titled "Fix install"
  - Would be 50+ files unreviewable.
- ❌ 11 parallel PRs
  - Phase 2 depends on phase 1; phase 3 on phase 2; etc. Parallel
    PRs would have constant merge conflicts and couldn't be tested
    independently.
- ✅ 5 stacked PRs with explicit base relationships, each
  independently mergeable in order.

---

## When to deviate

This workflow is the default, not a law. Reasonable exceptions:

- **Trivial typo:** Fix in a small PR without filing an issue.
- **Security hotfix:** Open the PR immediately; file the issue
  afterward for tracking. Do not wait for triage.
- **Cohesive feature with unavoidable cross-cutting changes:** A
  single feature PR can touch multiple files if they form one
  logical unit. The test is whether a reviewer can hold the whole
  change in their head.
- **Mass renames or codebase-wide refactors:** Sometimes one big
  PR is correct (e.g. renaming a class used in 50 files). Make the
  PR description loud about what changed and why a split would be
  worse.

If you deviate, say so in the PR description and explain why.

---

## How this interacts with the rest of the methodology

| Concern | Document |
|---|---|
| Repo invariants and topology that don't change per PR | [`AGENTS.md`](../../AGENTS.md) |
| How to make any repo legible to AI agents | [`agent-onboarding.md`](agent-onboarding.md) |
| **How to land changes in this repo (this doc)** | `change-discipline.md` |
| Security baseline | [`SECURITY.md`](../../SECURITY.md) |

Order of consultation when planning a change:

1. `AGENTS.md` — does my change violate an invariant?
2. Open `discussion` issues — is there an unresolved decision in
   this area? (#39, #41 currently)
3. `change-discipline.md` (this doc) — how do I file the issue
   and structure the PR?
4. The PR template — what does a reviewer need from me to approve?

---

## Maintenance

This document and the templates only work if they stay accurate.

- **Update when reality drifts.** If we adopt P0/P1/P2/P3 labels,
  if we add commitlint, if the stacked-PR pattern stops being an
  exception — update this doc in the same PR that makes the change.
- **Update the worked example when a better one exists.** The
  phase 1–6 stack is a good example *today*; if a future iteration
  produces a cleaner illustration, swap it in.
- **Don't let the templates rot.** Anti-patterns observed in
  practice are signals to update the templates, not nag in PR
  reviews. The template is the cheapest enforcement mechanism.

---

*This document was added in PR #41 alongside `.github/ISSUE_TEMPLATE/`
and `.github/PULL_REQUEST_TEMPLATE.md`. It is itself an example of
the discipline it describes — see issue #41 for the discussion that
preceded the PR.*
