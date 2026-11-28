# Subscriber-request fixtures

Each row names a pair in [`cases.json`](cases.json). Validate the `valid` and
`broken` members separately against the complete
[`subscriber-requests.v1.schema.json`](../../subscriber-requests.v1.schema.json)
with a Draft 2020-12 validator. The valid member must pass, and the broken
member must fail on the named keyword within its record definition.

The cases use invented logins, text, operations, issue numbers and commit
IDs. They prove record shape. GitHub authorship, actual checks, version
comparison, credit arithmetic, queue sorting and side effects are proved
by the consumers against synthetic inputs.

| Pair | Invalidating schema keyword |
| --- | --- |
| `tier-1` | `const` |
| `tier-10` | `const` |
| `tier-100` | `const` |
| `bank-while-active` | `const` |
| `business-default` | `const` |
| `business-owner-setting` | `minimum` |
| `unquoted-size-cap` | `const` |
| `priority-by-tier` | `const` |
| `oldest-within-tier` | `const` |
| `planned-work-keeps-place` | `const` |
| `local-entitlement` | `const` |
| `entitlement-bank` | `minimum` |
| `business-unlimited-bank` | `type` |
| `entitlement-ban-state` | `type` |
| `ended-bank-frozen` | `type` |
| `no-payment-record` | `additionalProperties` |
| `kernel-scope` | `enum` |
| `skills-scope` | `enum` |
| `driver-scope` | `enum` |
| `market-scope` | `enum` |
| `subscriber-author` | `pattern` |
| `request-bug` | `enum` |
| `request-driver` | `enum` |
| `request-feature` | `enum` |
| `request-docs` | `enum` |
| `closing-marker` | `pattern` |
| `public-default` | `const` |
| `business-private-intake` | `const` |
| `private-needs-business` | `const` |
| `public-admission-separation` | `not` |
| `verdict-approved` | `required` |
| `verdict-market-item` | `enum` |
| `verdict-quote` | `const` |
| `verdict-needs-owner` | `required` |
| `verdict-refused` | `minLength` |
| `verdict-report` | `not` |
| `xl-approval-needs-acceptance` | `required` |
| `cost-s` | `const` |
| `cost-m` | `const` |
| `cost-l` | `const` |
| `xl-charge-needs-acceptance` | `required` |
| `business-use-without-bank` | `type` |
| `approval-only-spend` | `enum` |
| `return-reason` | `required` |
| `stage-submitted` | `required` |
| `stage-triaged` | `required` |
| `stage-building` | `required` |
| `stage-pull-request` | `required` |
| `stage-reviewed` | `required` |
| `stage-merged` | `required` |
| `stage-released` | `required` |
| `stage-working-on-install` | `required` |
| `estimate-not-promise` | `const` |
| `positive-throughput` | `minimum` |
| `unavailable-throughput` | `additionalProperties` |
| `tracker-omits-tier` | `additionalProperties` |
| `credit-pull-request` | `pattern` |
| `credit-changelog` | `pattern` |
| `credit-listing` | `pattern` |
| `no-private-credit` | `const` |
| `veto-comment-form` | `pattern` |
| `veto-before-merge` | `const` |
| `veto-owner-only` | `const` |
| `ban-and-refund-confirmation` | `required` |
| `ban-remains-local` | `const` |

To replay with a Python environment that already has a Draft 2020-12
validator, run from the repository root:

```sh
python3 - <<'PYTHON'
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

root = Path("contracts")
schema = json.loads((root / "subscriber-requests.v1.schema.json").read_text())
cases = json.loads((root / "fixtures/subscriber-requests/cases.json").read_text())
Draft202012Validator.check_schema(schema)
validator = Draft202012Validator(schema, format_checker=FormatChecker())

for case in cases:
    validator.validate(case["valid"])
    if validator.is_valid(case["broken"]):
        raise SystemExit("broken fixture accepted: " + case["rule"])
print(f"{len(cases)} valid/broken pairs passed")
PYTHON
```
