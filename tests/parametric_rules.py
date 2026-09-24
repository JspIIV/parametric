"""The payout rules, exercised through the real contract methods.

Testing the helpers alone would not prove that a policy pays only when the peril is
evidenced inside its window, so parametric.py is loaded against a stub of the
runtime, a real Parametric is built, and the assertions go through open_policy(),
take() and settle(). The stub controls the two things the contract cannot: the page
the round fetches and the verdict it returns, plus the clock, so a window can be made
to lie in the future when the policy opens and in the past when it settles.

    python tests/parametric_rules.py
"""

import io
import json
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
CONTRACT = os.path.join(HERE, "..", "contracts", "parametric.py")


class _Store:
    def __init__(self, kind): self.kind = kind
    def __class_getitem__(cls, item): return cls("map" if isinstance(item, tuple) else "list")
    def make(self): return {} if self.kind == "map" else []


class _Address:
    def __init__(self, hex_value): self.as_hex = hex_value
    def __str__(self): return str(self.as_hex)


class _Message:
    def __init__(self):
        self.sender_address = _Address("0x" + "0" * 40)
        self.value = 0


class _Web:
    def __init__(self):
        self.page = "a page"

    def render(self, url):
        if self.page is None:
            raise RuntimeError("could not fetch")
        return self.page


class _Nondet:
    def __init__(self, web):
        self.web = web
        self.last_prompt = None
        self.answer = "{}"

    def exec_prompt(self, task):
        self.last_prompt = task
        return self.answer


class _Write:
    def __call__(self, fn): return fn
    def payable(self, fn): return fn


class _PublicNS:
    def __init__(self):
        self.write = _Write()
        self.view = lambda fn: fn


class _EqPrinciple:
    def prompt_comparative(self, run, principle=None): return run()


class _GL:
    def __init__(self):
        self.Contract = object
        self.public = _PublicNS()
        self.message = _Message()
        self.nondet = _Nondet(_Web())
        self.eq_principle = _EqPrinciple()


def load():
    gl = _GL()
    fake = types.ModuleType("genlayer")
    fake.gl = gl
    fake.DynArray = _Store
    fake.TreeMap = _Store
    fake.u32 = int
    fake.u256 = int
    fake.Address = _Address
    sys.modules["genlayer"] = fake
    module = types.ModuleType("parametric_under_test")
    exec(compile(io.open(CONTRACT, encoding="utf-8").read(), CONTRACT, "exec"), module.__dict__)
    return module, gl


def fresh(module):
    contract = module.Parametric.__new__(module.Parametric)
    for field, declared in module.Parametric.__annotations__.items():
        setattr(contract, field, declared.make())
    contract.__init__()
    return contract


RESULTS = []


def check_(label, condition):
    RESULTS.append((label, bool(condition)))
    print(("  ok  " if condition else " FAIL "), label)


UW = "0x1111111111111111111111111111111111111111"
INSURED = "0x2222222222222222222222222222222222222222"

URL = "https://example.org/bulletin"
NOW = 1_000_000_000
FUTURE = NOW + 3600
PAST = NOW - 3600


def answer(verdict, occurred_on="", reason="r", quote="q"):
    return json.dumps({"verdict": verdict, "occurred_on": occurred_on, "reason": reason, "quote": quote})


def bal(c, who):
    return json.loads(c.balance(who))["balance"]


def main():
    module, gl = load()
    clock = {"now": NOW}
    module._now = lambda: clock["now"]

    def as_(address): gl.message.sender_address = _Address(address)

    print("the pure window and outcome rules")
    check_("a future window is valid", module._valid_window(str(FUTURE), NOW)[0])
    check_("a window already closed is refused", not module._valid_window(str(PAST), NOW)[0])
    check_("a window equal to now is refused", not module._valid_window(str(NOW), NOW)[0])
    check_("OCCURRED pays", module._outcome("OCCURRED", NOW, FUTURE) == ("PAID", True))
    check_("NOT_OCCURRED before the window closes does not pay and stays active",
           module._outcome("NOT_OCCURRED", NOW, FUTURE) == ("ACTIVE", False))
    check_("NOT_OCCURRED after the window closes expires the policy, no pay",
           module._outcome("NOT_OCCURRED", FUTURE + 1, FUTURE) == ("EXPIRED", False))
    check_("UNCLEAR never pays and stays active", module._outcome("UNCLEAR", FUTURE + 1, FUTURE) == ("ACTIVE", False))

    print("\nopening a policy")
    c = fresh(module)
    as_(UW)
    bad = json.loads(c.open_policy("Quake", URL, "0", "5", str(FUTURE)))
    check_("a non-positive payout is refused", not bad["ok"])
    backdated = json.loads(c.open_policy("Quake", URL, "100", "5", str(PAST)))
    check_("a window in the past is refused at open", not backdated["ok"])
    opened = json.loads(c.open_policy("A magnitude 6+ quake hits Region X", URL, "100", "5", str(FUTURE)))
    pid = opened["id"]
    check_("a good policy opens OPEN", opened["ok"] and opened["status"] == "OPEN")

    print("\ntaking a policy pays the premium and cannot be settled before it is taken")
    as_(UW)
    check_("the underwriter cannot take their own policy", not json.loads(c.take(pid))["ok"])
    check_("an untaken policy cannot be settled", not json.loads(c.settle(pid))["ok"])
    as_(INSURED)
    taken = json.loads(c.take(pid))
    check_("the taker becomes the insured and the policy is ACTIVE", taken["ok"] and taken["status"] == "ACTIVE")
    check_("the premium is credited to the underwriter", bal(c, UW) == 5)
    check_("a policy already taken cannot be taken again", not json.loads(c.take(pid))["ok"])

    print("\na peril not yet occurred does not pay while the window is open")
    clock["now"] = NOW + 10
    gl.nondet.answer = answer("NOT_OCCURRED", reason="no quake yet")
    early = json.loads(c.settle(pid))
    check_("settling before the peril occurs leaves the policy active", early["status"] == "ACTIVE" and not early["paid"])
    check_("nothing was paid to the insured yet", bal(c, INSURED) == 0)
    check_("the window was put in front of the round",
           gl.nondet.last_prompt is not None and json.loads(c.get(pid))["window_iso"] in gl.nondet.last_prompt)

    print("\nthe peril occurs in the window: the policy pays the insured")
    clock["now"] = NOW + 20
    gl.nondet.answer = answer("OCCURRED", occurred_on="the 3rd, inside the window", reason="a magnitude 6.4 quake struck")
    paid = json.loads(c.settle(pid))
    check_("an in-window occurrence pays", paid["status"] == "PAID" and paid["paid"])
    check_("the payout is credited to the insured", bal(c, INSURED) == 100)
    check_("a paid policy cannot be settled again", not json.loads(c.settle(pid))["ok"])

    print("\na peril that never occurs expires once the window closes, paying nothing")
    as_(UW)
    p2 = json.loads(c.open_policy("A hurricane makes landfall in Region Y", URL, "200", "7", str(FUTURE)))["id"]
    as_(INSURED)
    c.take(p2)
    clock["now"] = FUTURE + 100  # window has now closed
    gl.nondet.answer = answer("NOT_OCCURRED", reason="the season passed with no landfall")
    expired = json.loads(c.settle(p2))
    check_("after the window closes, no occurrence expires the policy", expired["status"] == "EXPIRED" and not expired["paid"])
    check_("the insured is paid nothing on an expired policy", bal(c, INSURED) == 100)

    print("\nan unreadable source leaves an active policy open")
    clock["now"] = NOW
    as_(UW)
    p3 = json.loads(c.open_policy("A flood crests above 5m at the gauge", URL, "50", "1", str(FUTURE)))["id"]
    as_(INSURED)
    c.take(p3)
    clock["now"] = NOW + 30
    gl.nondet.web.page = None
    unclear = json.loads(c.settle(p3))
    check_("an unreadable page is UNCLEAR and the policy stays active", unclear["verdict"] == "UNCLEAR" and unclear["status"] == "ACTIVE")

    print("\nthe book counts what it paid")
    size = json.loads(c.size())
    check_("one policy paid, one expired, one active", size["paid"] == 1 and size["expired"] == 1 and size["active"] == 1)
    check_("total paid units equals the one payout made", size["paid_units"] == 100)

    failed = [label for label, ok in RESULTS if not ok]
    print()
    if failed:
        print("%d of %d checks failed" % (len(failed), len(RESULTS)))
        return 1
    print("%d checks, all through open_policy(), take() and settle() on a real Parametric, the window enforced"
          % len(RESULTS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
