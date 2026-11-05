"""S12c-12a protected digest scope: only exact approved before/after units are neutralised.

No product dispatch or runtime data: these hashes bind the public card edits in this slice.
A different value, sibling property, example identity or new card remains visible to S4i.
"""

import hashlib
import json
from typing import Any

# (card, property path, before SHA, approved after SHA); None path is one newly added card.
UNITS = (
    (
        "accidental_death_benefit_rules",
        "includes",
        "99d1fdacfcd15d86f1710a7c5d14c4930d2686c7484bdb4c166d28e0c4904741",
        "747ea3034d15e77352549edf1f5e373ab298d9dbc3c1cac6e772e4809269003c",
    ),
    (
        "additional_benefit_rules",
        "includes",
        "483abcb533176df9762b1d1395331cd34d8eeb55b5ac5f9203edbfb127a22926",
        "2626f18ee25c7d5e93240d56199ddf8ec0610200e49caf15b21facce49df71f8",
    ),
    (
        "benefit_interaction_rules",
        "examples/0/value",
        "550dbfc0a13a3f1ce92c0379a57ad647525a6c70f4e8940094868661eb75d1f5",
        "a28a3139513b6d4cd20670b06681c5b124d5f0b990ff3fbba75c72088a477464",
    ),
    (
        "benefit_interaction_rules",
        "examples/2/value",
        "b820d5fedf6a25742998d0aba123419ec71a94a675f3070b3176c92fafa2bceb",
        "418320e7d7f74432472a26d069a8e0a6b7396f23a995ecd570eda803b6d42d2c",
    ),
    (
        "benefit_interaction_rules",
        "writing_rule",
        "8543a83d570eea1ff3adbaaf4849d29cbb36b9d3cb620a38f19a9cbd83de4cdb",
        "fea8b51487c7c0f75fa075e245db602f23ce08c54b1bbc9bbda3dde808b0caf2",
    ),
    (
        "cash_value_rules",
        "excludes",
        "7ef321a999ecfc5f3491e42657c88664c918f90b860da9675a0d36f1b7ae51ca",
        "bec172f0b1577a0b4626dbf2fd0b4598b5aaf98fd1f216cb64e3027744303549",
    ),
    (
        "cash_value_rules",
        "includes",
        "9050d544c8369d7655b9a4e4cb6e2d208c22937369fafcd6337862679437332a",
        "c1d6476a43b38fba73765942aa0eeceeaac30a23e723230f96ea0f7d41da0b4b",
    ),
    (
        "death_benefit_rules",
        "includes",
        "b24653f9b0887a4995e43caeff4c30545156c663dd1faff4f0058bfdcac4b651",
        "b27a509ff57ac9471e0355dfc05e276c5ceff6b0eacc60a1939d0fe0027ec773",
    ),
    (
        "disability_benefit_rules",
        "includes",
        "287d9ff703cca18cb81b17fb6fbb1394448ec0180531f2966c029811a47a12e3",
        "673200fd3ccbbd10551f8352ba2eb3274c75927d9b61127345a4a042a8626f8a",
    ),
    (
        "exclusions",
        "includes",
        "a1f2b80d1b0bf9b4fa23a1d3d95c2e62f8e8177ada1a547f4e39d49168d405a1",
        "2994d5513c7d3af542c403ec4b0d4db724387662ce00108e081984521705402f",
    ),
    (
        "income_loss_benefit_eligibility_conditions",
        "includes",
        "35d3fd2d094c8d9ea62648863fadd14d2232d088ae11e0be9a1cf6b871725cd8",
        "66d8f4feeaccbc3ddfeb41042e52139d64ba76d565a90997ce1c6846cc9ea672",
    ),
    (
        "income_loss_care_benefit_conditions",
        "includes",
        "9031f95dbd8600b80ebf450b249e247bfa6431a1bc8ec94b2d41dca2770b2f4c",
        "3223b0bf443df8c04d048cdd8afe968cc84504078e412523655bd0f0c5faa1fd",
    ),
    (
        "maturity_benefit_rules",
        "includes",
        "fbc31dc4647d6f464349a1d8c2770d5e03044965fb37396e92f148a8d0ca4661",
        "08bb8e3ff06ce14d88af814a53c9e5ef4fd4c8163286a9608124512496f415cd",
    ),
    (
        "outpatient_inpatient_scope",
        None,
        None,
        "28347ac76833abc942b2f8ca56f4c6d3e7d62c3a486d970593c7912b1e0c9b37",
    ),
    (
        "premium_payment_frequency",
        "excludes",
        "258c5ad107a58b46bb3f28ccb2c6aa265a48e0759051333be7f54f64061d1941",
        "3c4eff9e829c183780bd72ce50d603ac1ba5fa1906f9535fa8000f43dcabcc30",
    ),
    (
        "premium_waiver_rules",
        "includes",
        "556ea983ebe735c045d0600e531e6055079c5209af73bbff331d856dcb8d2e2b",
        "938426fe2c320f6d53b7394f9b042a90103ad8940cb673de190e684b3248bc1b",
    ),
    (
        "reimbursable_expense_scope",
        None,
        None,
        "6ebe231cbbe5c07ce2dc8e8648338b6d4aa48190b0d3f6c153dca85785780b77",
    ),
    (
        "sum_assured_range",
        "definition",
        "40102486b831698614bc61dcc2cc300dfc0cf89325b2d7a4c10bedf0a3e746f1",
        "5b68349f3e356a6c5ae7adf21e0a5cdee771c4704531f1ae12a31b29373bf48a",
    ),
    (
        "sum_assured_range",
        "examples/0/reason",
        "74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b",
        "924b1a2e252ee521575c0e313dd5c584894d61c26ad64576872d5075da19fc70",
    ),
    (
        "sum_assured_range",
        "examples/0/state",
        "94332144d941eb1212c9af7f968e215a7042bf94925c9c10b21de97a2f0cea06",
        "eb8bf0d80db323992f6b634aab492b1e6d9e96a8e87a511c2a0db75ab929452c",
    ),
    (
        "sum_assured_range",
        "examples/0/value",
        "8ddc8b52aeb485c51d32f3e64aa7c3363946cfffdecc6d21e446a5d7d53838cb",
        "74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b",
    ),
    (
        "sum_assured_range",
        "examples/1/reason",
        "74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b",
        "924b1a2e252ee521575c0e313dd5c584894d61c26ad64576872d5075da19fc70",
    ),
    (
        "sum_assured_range",
        "examples/1/state",
        "94332144d941eb1212c9af7f968e215a7042bf94925c9c10b21de97a2f0cea06",
        "eb8bf0d80db323992f6b634aab492b1e6d9e96a8e87a511c2a0db75ab929452c",
    ),
    (
        "sum_assured_range",
        "examples/1/value",
        "8ddc8b52aeb485c51d32f3e64aa7c3363946cfffdecc6d21e446a5d7d53838cb",
        "74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b",
    ),
    (
        "sum_assured_range",
        "examples/2/reason",
        "74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b",
        "924b1a2e252ee521575c0e313dd5c584894d61c26ad64576872d5075da19fc70",
    ),
    (
        "sum_assured_range",
        "examples/2/state",
        "94332144d941eb1212c9af7f968e215a7042bf94925c9c10b21de97a2f0cea06",
        "eb8bf0d80db323992f6b634aab492b1e6d9e96a8e87a511c2a0db75ab929452c",
    ),
    (
        "sum_assured_range",
        "examples/2/value",
        "8ddc8b52aeb485c51d32f3e64aa7c3363946cfffdecc6d21e446a5d7d53838cb",
        "74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b",
    ),
    (
        "sum_assured_range",
        "includes",
        "ae53bca6de56b2e52d4b8900a2b4dac741cbeb995ee15c91ba3e4a430d55af98",
        "c0c6d00a71d1e791b6ea162eb041269c7f0b79eb10e4728dc7495fa0a05456d1",
    ),
    (
        "sum_assured_range",
        "unknown_rule",
        "7318ec0d936f1fafc3705e035c8c6c8449e880c15943c5f7bcf2a0c3dab49b82",
        "9d8ba3c571050169513ea9b9ec08ea1df89ddc45d473e017eed7d5db47995bed",
    ),
    (
        "surrender_and_cancellation_terms",
        "excludes",
        "0e9f9cddcef8d8b7cf6ad9333074539b2bab18d81167d174f501f8e69ea38556",
        "b7aa5bbae0403b6b2ce29a83fa66904dfd7fbd55babde4c82a88b1c8660c2d41",
    ),
    (
        "surrender_and_cancellation_terms",
        "includes",
        "0cd0e4429c015b2c365c919fedc034552b22cc0808e379a6a54f587e0d0c12f4",
        "7212e5194db4399ebdae0ca79e0be2e64bbdcd658d25f7cb5aafdd79654c56bd",
    ),
    (
        "survival_benefit_rules",
        "includes",
        "8f3bd450d1bf1d6094e512d588f43b4a84435e60aeec2490a422bc84fa07f24e",
        "a07823e0b6646756d1b2cf5a0873a744f230c875efc5d96689a731e2b81025ad",
    ),
)


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def neutralize(data: dict[str, Any]) -> None:
    for key, path, before, after in UNITS:
        if path is None:
            if key in data and digest(data[key]) == after:
                data.pop(key)
            continue
        parts = path.split("/")
        parent = data[key]
        for part in parts[:-1]:
            parent = parent[int(part)] if isinstance(parent, list) else parent[part]
        leaf = parts[-1]
        if digest(parent.get(leaf)) in (before, after):
            parent[leaf] = "<S12c-12a approved unit>"
