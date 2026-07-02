from decimal import Decimal


def parse_transfer(allocs) -> dict | None:
    """Parse a transfer income's allocation pair into {from,to,amount}.

    A transfer has one negative allocation (source) and one positive (target).
    Returns None if a valid negative+positive pair is not present.
    """
    source = None
    target = None
    for a in allocs:
        amt = Decimal(str(a.get("amount", "0")))
        if amt < 0 and source is None:
            source = a
        elif amt > 0 and target is None:
            target = a
    if source is None or target is None:
        return None
    amount = abs(Decimal(str(target.get("amount", "0"))))
    return {
        "from": source.get("envelope", ""),
        "from_emoji": source.get("emoji", ""),
        "to": target.get("envelope", ""),
        "to_emoji": target.get("emoji", ""),
        "amount": str(int(amount)) if amount == amount.to_integral_value() else str(amount),
    }
