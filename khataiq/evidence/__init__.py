"""The evidence engine's rules. Pure functions over a business's ledger: no DB, no I/O,
deterministic. Each rule has a rule_id and an integer version stored on every link it makes;
changing a rule's behaviour means bumping its version. See docs/specs/evidence-engine.md."""
