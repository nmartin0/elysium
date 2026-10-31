# Agentic coding practice

**Bottom line (researched 2026-10-31).** The sources agree on four things: give
the AI a check it can run and make it show evidence; keep its context small;
specify before building anything large; and have a person, or a reviewer in a
fresh context, read the result. We already do the first. We adopted the rest in
[D49](../decisions.md) and [workflow.md](../workflow.md).

## What the sources say

- **A check the agent can run is the biggest lever.** Without one the agent
  stops when the work looks done, and the person becomes the test. Anthropic's
  ladder: ask for the check in the prompt, keep a goal across the session, block
  the end of a turn on a script (a stop hook), have a second model try to refute
  the result. Have the agent show evidence (test output, the command and what it
  returned), not assert success.
- **Context is the scarce resource.** Performance drops as the window fills.
  Keep the smallest set of high-signal tokens; clear between unrelated tasks;
  after two failed corrections of the same thing, restart with a better prompt;
  send research to a sub-agent that returns a short summary; keep notes in a
  file outside the conversation; load detail on demand.
- **Explore, plan, implement, commit.** Skip the plan when the diff is one
  sentence. For a larger feature have the AI interview the owner, write a spec,
  and build it in a fresh session. A good spec names the files and interfaces,
  says what is out of scope and ends with an end-to-end check.
- **Small steps.** One change, test it, commit. Large one-shot output is
  inconsistent and duplicated. Commits are save points; worktrees separate
  experiments.
- **Review in a fresh context.** An agent is biased toward what it just wrote. A
  reviewer that sees only the diff and the criteria does better. Tell it to
  report only gaps in correctness or the stated requirements: a reviewer asked
  for gaps always finds some, and chasing them over-engineers.
- **Keep the instruction file short.** Keep a line only if removing it would
  cause mistakes. Use hooks, not prose, for what must happen every time. A 2026
  study of repository context files found generated ones lowered success slightly
  and raised cost by over 20%, human-written ones helped by about 4% and mostly
  where nothing else documented the repository, and architecture overviews
  distracted the agent (read through a summary, not the paper; mostly Python).
- **The engineer stays accountable.** Treat AI output as an overconfident
  junior's: read it, run it, do not merge what you cannot explain. AI amplifies
  weak fundamentals.
- **Measure, do not feel.** METR's trial (16 experienced developers, 246 tasks,
  large mature codebases, 2025-era tools) found AI users 19% slower while
  believing they were faster. One data point, but a reason to trust checks over
  impressions.

## What we already did

`check.sh` as a gate on every commit; negative controls that prove tests can
fail; one commit per change; a rehearsal of every apply script on a fresh
clone; decisions, lessons and the roadmap kept in `docs/` as notes outside the
conversation.

## Sources

- Anthropic, [Best practices for Claude Code](https://code.claude.com/docs/en/best-practices.md)
- Anthropic, [Effective context engineering for AI agents](https://anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- Addy Osmani, [My LLM coding workflow going into 2026](https://addyosmani.com/blog/ai-coding-workflow/)
- [Evaluating AGENTS.md: are repository-level context files helpful?](https://arxiviq.substack.com/p/evaluating-agentsmd-are-repository) (summary of the paper)
- InfoQ, [METR's productivity study](https://www.infoq.com/news/2025/07/ai-productivity)
