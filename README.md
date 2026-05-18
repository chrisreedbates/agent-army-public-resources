# Agent Army Public Resources

Shareable resources from building an "agent army" — the collection of AI
agents, prompts, and rules I use to run [TheLauncher](https://thelauncher.ai),
a managed digital presence service for French small businesses, as a solo
operator.

Everything here is field-tested in production. If it's in this repo, it's
because it solved a real problem.

## What's here

- **[de-slopping.md](de-slopping.md)** — rules for stripping AI tells out of
  generated copy (French and English). Banned vocabulary, banned structures,
  a 12-point self-check the LLM runs before output. Use this in any pipeline
  or agent that emits human-readable text.

More to come as I extract reusable pieces from the buildout.

## How to use

Drop these files into the system prompts, agent definitions, or rule files
of your own AI pipelines. Most are written as standalone playbooks — copy,
adapt, ship.

## License

MIT License

## About

Built by [Chris Reed-Bates](https://github.com/chrisreedbates) while running
TheLauncher solo. Follow along if you're building AI systems that need to
sound like a human wrote them.
