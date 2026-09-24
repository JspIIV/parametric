# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""Parametric: insurance that pays when a public source shows the peril happened in time, with no claim filed.

Ordinary insurance pays after a claim, an adjuster, and an argument about whether
the thing really happened. Parametric insurance names the trigger up front: a
plain-language peril, one public page where its truth will show, a payout, and a
window it has to happen in. If the page shows the peril occurred on or before the
window closes, the policy pays. Nobody files a claim; nobody argues.

The one thing no ordinary contract can do is read that page and decide, honestly,
whether the peril happened and whether it happened in time. GenLayer can. An
underwriter opens a policy; someone takes it and pays the premium; and after that
anyone can settle it. The contract fetches the named page itself, tells the round
what the window was, and a round of GenLayer validators decides whether the peril
occurred within it. Only then does the payout move to the insured. If the window
closes with no trigger, the policy expires and the payout is never owed.

## What it settles

    OCCURRED   the page shows the peril happened on or before the window closes -> the policy PAYS
    NOT_OCCURRED  it did not happen; once the window has closed, the policy EXPIRES
    UNCLEAR    the page could not be read, or does not settle it: the policy stays open

Only OCCURRED ever pays, and it pays only the payout fixed when the policy was
opened. A peril evidenced only after the window closed is not covered.

## What it refuses

The peril and its source page are fixed when the policy is opened and cannot be
edited. A policy cannot be settled before someone has taken it, and it cannot pay
before the peril is evidenced within the window. Once a policy has paid or expired
it is settled for good. The underwriter is bound to the opener, the insured to the
taker, so nobody is paid for a policy they did not take.

## Where it stops, plainly

It reads what a public page says, against the window the underwriter set: name a
page a third party controls, with the peril and its date visible on it. It judges
the trigger, not the loss, which is the point of parametric cover: the payout is
fixed in advance, not measured after the fact.
"""

from genlayer import *
import json

OCCURRED = "OCCURRED"
NOT_OCCURRED = "NOT_OCCURRED"
UNCLEAR = "UNCLEAR"
VERDICTS = (OCCURRED, NOT_OCCURRED, UNCLEAR)

OPEN = "OPEN"
ACTIVE = "ACTIVE"
PAID = "PAID"
EXPIRED = "EXPIRED"

MAX_PERIL = 400
MAX_URL = 300
MAX_PAGE = 6000
MAX_REASON = 300
MAX_QUOTE = 300
MAX_AMOUNT = 10 ** 30

FETCH_FAILED = "__FETCH_FAILED__"


def _now() -> int:
    from datetime import datetime, timezone
    return int(datetime.now(timezone.utc).timestamp())


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _iso(ts: int) -> str:
    from datetime import datetime, timezone
    try:
        return datetime.fromtimestamp(int(ts), timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return str(ts)


def _clip(text: str, limit: int) -> str:
    text = str(text).strip()
    return text if len(text) <= limit else text[:limit] + " [...]"


def _whole(value) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return -1


def _amount(value):
    """A payout or premium: a whole number of units, 0 or more, within a sane bound."""
    n = _whole(value)
    if n < 0 or n > MAX_AMOUNT:
        return None
    return n


def _valid_window(value, now: int):
    """A coverage window must close in the future when the policy is opened."""
    when = _whole(value)
    if when <= 0:
        return False, "give the window close as a unix timestamp in the future"
    if when <= now:
        return False, "the coverage window must close in the future"
    return True, when


def _outcome(verdict: str, now: int, window_end: int):
    """Map a settlement verdict to the policy's next status. The window lives here.

    OCCURRED pays. NOT_OCCURRED expires the policy only once the window has closed;
    before that it is simply not yet triggered and the policy stays ACTIVE. UNCLEAR
    always leaves it ACTIVE. Kept pure so the payout rule can be tested on its own.
    Returns (status, pays: bool).
    """
    if verdict == OCCURRED:
        return PAID, True
    if verdict == NOT_OCCURRED and now >= window_end:
        return EXPIRED, False
    return ACTIVE, False


def _addr(value) -> str:
    text = str(value).strip().lower()
    if not text.startswith("0x") or len(text) != 42:
        return ""
    for character in text[2:]:
        if character not in "0123456789abcdef":
            return ""
    return text


def _url_ok(url: str) -> bool:
    text = str(url).strip()
    if len(text) < 8 or len(text) > MAX_URL or " " in text:
        return False
    return text.startswith("https://") or text.startswith("http://")


def _field(raw: str, name: str, allowed, fallback: str) -> str:
    try:
        text = str(raw).strip()
        obj = json.loads(text[text.index("{"):text.rindex("}") + 1])
        if isinstance(obj, dict):
            said = str(obj.get(name, "")).strip().upper()
            return said if said in allowed else fallback
    except Exception:
        pass
    return fallback


def _text_field(raw: str, name: str, limit: int) -> str:
    try:
        text = str(raw).strip()
        obj = json.loads(text[text.index("{"):text.rindex("}") + 1])
        if isinstance(obj, dict):
            return _clip(str(obj.get(name, "")), limit)
    except Exception:
        pass
    return ""


def _task(peril: str, window: str, page: str) -> str:
    return f"""A parametric insurance policy names a peril and a public page where its truth would
show. Read the page and decide whether the peril occurred, and whether it occurred
in time.

THE PERIL, as the policy states it:
{peril}

THE COVERAGE WINDOW CLOSES AT (an occurrence after this is not covered):
{window}

THE PAGE NAMED AS WHERE ITS TRUTH WOULD SHOW:
{page}

Decide one of:
  {OCCURRED} the page shows the peril happened ON OR BEFORE the window close above
  {NOT_OCCURRED} the page was read and the peril did not happen, or happened only after the window closed
  {UNCLEAR} the page could not be read, or does not settle whether or when the peril happened

Judge from the date the page gives for the event, against the window close above,
not against today. Do not treat an unreachable or unrelated page as an occurrence:
that is {UNCLEAR}. An event the page dates after the window close is {NOT_OCCURRED}
for this policy, not {OCCURRED}.

Reply with bare JSON and nothing else:
{{"verdict": "{OCCURRED}" or "{NOT_OCCURRED}" or "{UNCLEAR}",
  "occurred_on": "the date the page gives for the event, or empty",
  "quote": "the sentence on the page that decided it, or empty",
  "reason": "one sentence naming what decided it, including timing"}}"""


class Parametric(gl.Contract):
    """Parametric policies, each paid from its own public source when the peril is evidenced in its window."""

    # str(id) -> the policy as JSON.
    items: TreeMap[str, str]
    ids: DynArray[str]
    # address -> credited units (payouts received and premiums earned), as a JSON int.
    balances: TreeMap[str, str]

    def __init__(self) -> None:
        pass

    def _credit(self, who: str, amount: int) -> None:
        cur = self.balances.get(who, None)
        base = int(cur) if cur is not None else 0
        self.balances[who] = str(base + int(amount))

    @gl.public.write
    def open_policy(self, peril: str, source_url: str, payout: str, premium: str, window_end: str) -> str:
        """Underwrite a parametric policy: a peril, the page it shows on, a payout, a premium, and a window.

        The underwriter is bound to the caller. The window must close in the future.
        The policy opens waiting for someone to take it.
        """
        underwriter = gl.message.sender_address.as_hex.lower()
        text = _clip(peril, MAX_PERIL)
        link = str(source_url).strip()
        pay = _amount(payout)
        prem = _amount(premium)
        if not text:
            return json.dumps({"ok": False, "error": "state the peril in plain words"})
        if not _url_ok(link):
            return json.dumps({"ok": False, "error": "give an http(s) URL the peril can be checked at"})
        if pay is None or pay <= 0:
            return json.dumps({"ok": False, "error": "give a positive payout as a whole number of units"})
        if prem is None:
            return json.dumps({"ok": False, "error": "give the premium as a whole number of units (0 or more)"})
        ok, when = _valid_window(window_end, _now())
        if not ok:
            return json.dumps({"ok": False, "error": when})

        pid = str(len(self.ids))
        record = {
            "id": pid,
            "underwriter": underwriter,
            "opened_at": _now_iso(),
            "peril": text,
            "source_url": link,
            "payout": pay,
            "premium": prem,
            "window_end": when,
            "window_iso": _iso(when),
            "status": OPEN,
            "insured": "",
            "settlements": 0,
            "verdict": "",
            "occurred_on": "",
            "reason": "",
            "quote": "",
            "settled_at": "",
        }
        self.items[pid] = json.dumps(record)
        self.ids.append(pid)
        return json.dumps({"ok": True, "id": pid, "status": OPEN, "payout": pay, "premium": prem, "window": _iso(when)})

    @gl.public.write
    def take(self, policy_id: str) -> str:
        """Take an open policy as the insured, paying its premium to the underwriter. Bound to the caller.

        The premium is credited to the underwriter now; the payout is credited to the
        insured only if the peril is later settled as having occurred in the window.
        """
        insured = gl.message.sender_address.as_hex.lower()
        pid = str(policy_id).strip()
        stored = self.items.get(pid, None)
        if stored is None:
            return json.dumps({"ok": False, "error": "no policy with that id"})
        record = json.loads(stored)
        if record["status"] != OPEN:
            return json.dumps({"ok": False, "error": "this policy is not open to take", "status": record["status"]})
        if insured == record["underwriter"]:
            return json.dumps({"ok": False, "error": "the underwriter cannot take their own policy"})
        if _now() >= int(record["window_end"]):
            return json.dumps({"ok": False, "error": "the coverage window has already closed"})

        record["insured"] = insured
        record["status"] = ACTIVE
        record["taken_at"] = _now_iso()
        self._credit(record["underwriter"], int(record["premium"]))
        self.items[pid] = json.dumps(record)
        return json.dumps({"ok": True, "id": pid, "status": ACTIVE, "premium_paid": int(record["premium"])})

    @gl.public.write
    def settle(self, policy_id: str) -> str:
        """Fetch the source and settle an active policy: pay if the peril occurred in the window. Open to anybody.

        The page is fetched by the contract inside the round, which is told the window,
        so an occurrence only counts if it is on or before the window close. The payout
        accrues to the insured; nobody passes in the verdict.
        """
        pid = str(policy_id).strip()
        stored = self.items.get(pid, None)
        if stored is None:
            return json.dumps({"ok": False, "error": "no policy with that id"})
        record = json.loads(stored)
        if record["status"] != ACTIVE:
            return json.dumps({"ok": False, "error": "only an active policy can be settled", "status": record["status"]})

        # Copy into locals before the round. Nothing inside the block reads self
        # and nothing inside it raises.
        peril = record["peril"]
        url = record["source_url"]
        window = record["window_iso"]

        def look() -> str:
            page = ""
            try:
                got = gl.nondet.web.render(url)
                page = got if isinstance(got, str) else getattr(got, "body", "")
                if isinstance(page, (bytes, bytearray)):
                    page = page.decode("utf-8", "replace")
                page = _clip(str(page), MAX_PAGE)
            except Exception:
                page = FETCH_FAILED
            if not page or page == FETCH_FAILED:
                return json.dumps({"verdict": UNCLEAR, "occurred_on": "", "quote": "",
                                   "reason": "the source page could not be read"})
            try:
                return str(gl.nondet.exec_prompt(_task(peril, window, page)))
            except Exception as error:
                return json.dumps({"verdict": UNCLEAR, "occurred_on": "", "quote": "",
                                   "reason": _clip("the prompt failed: " + str(error), MAX_REASON)})

        raw = gl.eq_principle.prompt_comparative(
            look,
            principle=(
                f"Both answers must carry the same value in the field named verdict, one of "
                f"{OCCURRED}, {NOT_OCCURRED} or {UNCLEAR}. That single field decides whether an "
                "insurance payout is made, and it already folds in the window: OCCURRED means the "
                "peril happened on or before the window close, NOT_OCCURRED means it did not, or only "
                "after. Two readers differing on it disagree about whether, or when, the peril "
                "happened, not about wording. The other fields are not compared, and the two readers "
                "will not have fetched byte-identical copies of the page."
            ),
        )

        verdict = _field(raw, "verdict", VERDICTS, "")
        if not verdict:
            return json.dumps({"ok": False,
                               "error": "the round produced no verdict this contract recognises",
                               "round_said": _clip(str(raw), 400)})

        status, pays = _outcome(verdict, _now(), int(record["window_end"]))
        record["settlements"] = int(record.get("settlements", 0)) + 1
        record["verdict"] = verdict
        record["occurred_on"] = _text_field(raw, "occurred_on", 80)
        record["reason"] = _text_field(raw, "reason", MAX_REASON)
        record["quote"] = _text_field(raw, "quote", MAX_QUOTE)
        if status == PAID:
            record["status"] = PAID
            record["settled_at"] = _now_iso()
            self._credit(record["insured"], int(record["payout"]))
        elif status == EXPIRED:
            record["status"] = EXPIRED
            record["settled_at"] = _now_iso()
        # ACTIVE: not yet triggered and window still open, or unreadable; can be settled again.
        self.items[pid] = json.dumps(record)
        return json.dumps({"ok": True, "id": pid, "verdict": verdict, "status": record["status"],
                           "paid": status == PAID, "reason": record["reason"]})

    # ------------------------------------------------------------------ reads

    @gl.public.view
    def balance(self, address: str) -> str:
        """Units credited to an address: payouts received as the insured, premiums earned as underwriter."""
        who = _addr(address)
        if not who:
            return json.dumps({"exists": False, "balance": 0})
        cur = self.balances.get(who, None)
        return json.dumps({"exists": cur is not None, "address": who, "balance": int(cur) if cur is not None else 0})

    @gl.public.view
    def status(self, policy_id: str) -> str:
        """A policy's current standing and the reason it was settled."""
        pid = str(policy_id).strip()
        stored = self.items.get(pid, None)
        if stored is None:
            return json.dumps({"exists": False})
        record = json.loads(stored)
        return json.dumps({"exists": True, "id": pid, "status": record["status"],
                           "verdict": record.get("verdict", ""), "settlements": record["settlements"],
                           "reason": record.get("reason", "")})

    @gl.public.view
    def get(self, policy_id: str) -> str:
        """The whole policy, including the deciding verdict, quote and reason once settled."""
        pid = str(policy_id).strip()
        stored = self.items.get(pid, None)
        if stored is None:
            return json.dumps({"exists": False})
        return stored

    @gl.public.view
    def size(self) -> str:
        """How many policies are open, active, paid and expired, and the total paid out."""
        counts = {OPEN: 0, ACTIVE: 0, PAID: 0, EXPIRED: 0}
        paid_units = 0
        for position in range(len(self.ids)):
            record = json.loads(self.items[self.ids[position]])
            state = record["status"]
            if state in counts:
                counts[state] += 1
            if state == PAID:
                paid_units += int(record["payout"])
        return json.dumps({"total": len(self.ids), "open": counts[OPEN], "active": counts[ACTIVE],
                           "paid": counts[PAID], "expired": counts[EXPIRED], "paid_units": paid_units})

    @gl.public.view
    def page(self, start: str, count: str) -> str:
        """A slice of the book, newest first, for a frontend to render."""
        total = len(self.ids)
        begin = _whole(start)
        want = _whole(count)
        if begin < 0:
            begin = 0
        if want < 1:
            want = 20
        if want > 50:
            want = 50
        out = []
        seen = 0
        position = total - 1 - begin
        while position >= 0 and seen < want:
            out.append(json.loads(self.items[self.ids[position]]))
            position -= 1
            seen += 1
        return json.dumps({"total": total, "start": begin, "count": len(out), "items": out})
