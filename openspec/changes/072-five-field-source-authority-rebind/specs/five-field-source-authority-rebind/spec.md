# Five-field source authority rebind specification

## ADDED Requirements

### Requirement: FSR1 exact five-field authority correction

The shared 596-1 task plan SHALL route exactly these fields to the exact terms
material profile and terms source SHA: `zh_0c5a8e59e2`, `zh_14b93ce275`,
`zh_17a83223e4`, `zh_f8cc996739`, and `zh_fd9a0b9fa3`. Each field's approved
049 Golden record SHALL identify `保险条款.pdf` as its Evidence source. The
correction SHALL be code-owned and exact; callers cannot add a sixth field.

#### Scenario: a corrected field remains brochure-bound

- **WHEN** the shared task plan is built from the approved 052 catalog
- **THEN** the field is assigned to a terms task whose source and material
  profile are the approved terms identities

### Requirement: FSR2 unaffected field custody

For every other Schema60 field, the plan SHALL preserve its prior task ID,
material role and source SHA. The plan SHALL remain exactly ten tasks, an exact
Schema60 bijection and identical between weak and strong arms. A model, prompt,
budget, normalizer or output-contract change remains outside this change.

#### Scenario: a sixth field changes authority

- **WHEN** the new plan is compared field-by-field with the merged plan
- **THEN** the changed source-role set is exactly the five approved field IDs

### Requirement: FSR3 no quality-authority substitution

This change SHALL NOT alter the approved Golden bytes, scoring logic or model
execution. It only makes the already-approved Evidence source available to the
five owning tasks. Provider calls remain forbidden in implementation and tests.

#### Scenario: implementation is verified

- **WHEN** focused and static gates run
- **THEN** no provider, Golden write or scorer path is invoked
