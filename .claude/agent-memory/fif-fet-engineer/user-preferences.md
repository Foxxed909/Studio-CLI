---
name: user-preferences
description: How this user works — what they want from fif+fet sessions, communication style
metadata:
  type: user
---

## Session style

User wants full end-to-end execution — read thoroughly, fix everything, then implement real working features. No stubs. No "TODO: implement later" comments in delivered code.

**Why:** They explicitly said "Do not leave stubs" and "Implement real, working code."
**How to apply:** Every feature added must be fully functional. If a feature cannot be fully implemented without installing a new package, note it explicitly rather than leaving a stub.

## Feature scope

When given a feature list to consider, not all items may already be implemented — check first with grep before assuming they exist.

**Why:** The user listed features like /alias, /multiline, /retry that were listed in ALL_COMMANDS but /alias and /multiline had no implementations. /retry was already in the dispatch. Verifying prevented creating duplicate implementations.

## Communication

User works in the StudioCLI / Coderoom ecosystem. GitHub: Foxxed909. Email: applaudeai@gmail.com.

## Project: StudioCLI

This is the user's primary CLI tool project. They care about:
- The version string (bump it when features are added)
- Keeping public.md and private.md updated
- Not breaking existing functionality when adding features
