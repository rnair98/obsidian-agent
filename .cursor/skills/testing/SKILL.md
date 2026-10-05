---
name: testing
description: Formalize test intent as a semi-formal proof and check it across a seeded multiverse when changing obsidian-agent. Use when adding, editing, deleting, or reviewing tests in this repository.
---

<objective>
Formalize what must stay true, then search a multiverse of worlds for a counterexample. Refuse a test a coding agent can satisfy by editing one expected value.
</objective>

<process>
1. Read `tests/README.md` and ARCHITECTURE.md §§10, 11.1, and 11.2 before writing or deleting a test.
2. Write a `Proof` as specified in §11.1 and check it with `check_always` or `check_sometimes`.
3. Axes are the disturbances. A passing always-property says nothing about worlds you did not generate.
4. Do not add an example assertion that restates the current return value, a mock of the unit under test, a toy-type branch matrix, or an equality check on model prose. Do not delete a failing world. Replay the printed seed.
5. Update the §11 testing map in the same change. Run the focused test, then `just check` when the contract is shared.
</process>

<success_criteria>
The proof names the seam, the fault model, and the axes the test actually varies. An always-property fails on one counterexample and the message includes the seed and the world. A sometimes-property fails when no world witnesses it. Assertions were not weakened to obtain green.
</success_criteria>
