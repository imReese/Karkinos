# Karkinos Documentation

This directory contains the maintained product and engineering documentation for
Karkinos.

Start with the document that owns the question you are trying to answer. Do not
treat every document as required context.

## Canonical documents

| Document                           | Owns                                                                              |
| ---------------------------------- | --------------------------------------------------------------------------------- |
| [GOAL.md](GOAL.md)                 | Product purpose, long-term priorities, and hard boundaries                        |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Durable quantitative, financial, and ownership boundaries                         |
| [PLAN.md](PLAN.md)                 | Current development scope, priorities, and frozen areas                           |
| [ENGINEERING.md](ENGINEERING.md)   | Current codebase reality, structural debt, compatibility, and engineering quality |
| [REFERENCES.md](REFERENCES.md)     | Mature external designs used for conceptual comparison                            |

Each subject has one canonical owner.

When documents appear to conflict, prefer the document that owns the subject
rather than copying the same rule into multiple files.

## Guides

Guides describe currently supported behavior or stable financial and operational
semantics. They do not define product direction.

* [Configuration](guides/configuration.md)
* [Return accounting](guides/return-accounting.md)
* [Account Truth import](guides/account-truth-import.md)
* [Legacy Strategy compatibility](guides/strategy-compatibility.md)

Some guides describe compatibility or maintenance-only functionality. Their
existence does not place that functionality in the current development scope;
[PLAN.md](PLAN.md) is authoritative for scope.

## Other repository documentation

* [Root README](../README.md) — product overview, quick start, and user entry point.
* [中文 README](../README.zh.md) — Chinese user-facing README.
* [Product design](../design.md) — durable UI and information-architecture guidance.
* [Scripts](../scripts/README.md) — runtime and maintenance commands.
* [Contributing](../CONTRIBUTING.md) — contribution and branch workflow.
* [Security](../SECURITY.md) — vulnerability reporting and sensitive-data rules.

## Documentation rules

Keep maintained documentation small and purposeful.

* Product intent belongs in `GOAL.md`.
* Durable architecture belongs in `ARCHITECTURE.md`.
* Current work belongs in `PLAN.md`.
* Current repository and engineering reality belongs in `ENGINEERING.md`.
* External design precedent belongs in `REFERENCES.md`.
* Stable usage or operational details belong in a focused guide.
* Implementation history belongs in Git.

Do not create parallel roadmaps, implementation diaries, master architecture
documents, acceptance documents, or duplicate language versions of engineering
documents merely to preserve historical structure.

A new durable document should exist only when its subject has a clear owner that
cannot be represented more simply in an existing canonical document.
