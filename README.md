# Parametric

**Insurance that pays when a public source shows the peril happened in time, with no claim filed.** A parametric-cover primitive for GenLayer, with a live book.

Ordinary insurance pays after a claim, an adjuster, and an argument about whether the thing really happened. Parametric insurance names the trigger up front: a plain-language peril, one public page where its truth will show, a payout, and a window it has to happen in. If the page shows the peril occurred on or before the window closes, the policy pays. Nobody files a claim; nobody argues. The one thing no ordinary contract can do is read that page and decide, honestly, whether the peril happened and whether it happened in time. GenLayer can.

## How it works

1. **`open_policy(peril, source_url, payout, premium, window_end)`** — an underwriter names the trigger, the page it shows on, the payout, the premium, and a window that must close in the future. Bound to `gl.message.sender_address`.
2. **`take(policy_id)`** — someone takes the open policy as the insured, paying the premium to the underwriter. Bound to the caller.
3. **`settle(policy_id)`** — open to anybody, once taken. The contract **fetches the page itself**, tells the round what the window was, and a GenLayer round returns `OCCURRED` / `NOT_OCCURRED` / `UNCLEAR`. Only an occurrence **on or before the window close** pays; the payout moves to the insured. Once the window has closed with no trigger, the policy `EXPIRES`. An unreadable page is `UNCLEAR` and the policy stays active.
4. **`balance(address)`** — units credited to an address: payouts received as the insured, premiums earned as the underwriter.

Reads: `status(id)`, `get(id)`, `size()`, `page(start, count)`.

## The window is part of the settlement

The window is not a formality the contract stores and forgets. It is refused if it is not in the future; it is injected into the round, so validators judge the date the page gives for the event *against that window*; and the mapping from verdict to outcome lives in the contract (`_outcome`), where a policy can only expire once the window has actually closed and only an `OCCURRED` verdict pays. A peril evidenced after the window is `NOT_OCCURRED` for that policy.

## Why it needs GenLayer

Whether a peril happened, and happened in time, is a judgement over real-world text that no ordinary contract can make and no single adjuster should be trusted with. GenLayer validators each fetch the page and reach consensus on one categorical field that already folds in the window; the payout is triggered by evidence, not by a claim.

## What it refuses

- **Refuses a back-dated window.** `open_policy` rejects a window that is not in the future.
- **Cannot pay before it is taken.** `settle` is refused until a policy has an insured.
- **Never pays late.** Only an occurrence on or before the window close is `OCCURRED`; anything after is not covered.
- **Never decides on silence.** An unreadable page is `UNCLEAR`; the policy stays active and can be settled again.
- **Settles for good.** Once a policy has paid or expired it cannot be settled again.
- **Binds each actor to the caller.** The underwriter is the opener, the insured the taker; nobody is paid for a policy they did not take.

## Tests

`python tests/parametric_rules.py` — the payout rules exercised through the real `open_policy()`, `take()` and `settle()` on a Parametric built against a stub of the runtime, with time and the round verdict controlled. It proves back-dated windows are refused, an untaken policy cannot be settled, the premium is credited on take, only an in-window occurrence pays the insured, a peril that never occurs expires after the window, and an unreadable source stays active. 26 checks.

## Live

- **Contract (GenLayer Asimov):** `0x82db4E5e05E7D9060856eFab44e4a75f93F48cF2`
- Explorer: https://explorer-asimov.genlayer.com/address/0x82db4E5e05E7D9060856eFab44e4a75f93F48cF2
- **App:** https://jspiiv.github.io/parametric/ — reads the book from chain without a wallet; opening, taking and settling are transactions on Asimov.

## Proven on Asimov

`scripts/prove.mjs`, `results/proved.json`, against the dated pages in `docs/`:
- a quake policy whose source (`quake-bulletin.txt`) shows a magnitude 6.4 event inside the window → **PAID**, the payout credited to the insured; the premium was credited to the underwriter on take.
- a hurricane policy whose source (`no-landfall.txt`) shows no landfall, settled after its window → **EXPIRED**, paying nothing.
- an untaken policy → `settle` refused, it stays `OPEN`.
- a policy with an unreadable source → `UNCLEAR`, it stays `ACTIVE`.

## Where it stops, plainly

It reads what a public page says, against the window the underwriter set: name a page a third party controls, with the peril and its date visible on it. It judges the trigger, not the loss, which is the point of parametric cover: the payout is fixed in advance, not measured after the fact. On Asimov the payout and premium move as credited balances rather than native value.

## Licence

AGPL-3.0-or-later.
