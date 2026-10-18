"""Split a bill in cents among people; the first people absorb the remainder cents."""


def split_bill(total_cents, people):
    if people <= 0:
        raise ValueError("people must be positive")
    share = round(total_cents / people)
    remainder = total_cents - share * people
    shares = [share] * people
    for i in range(remainder):
        shares[i] += 1
    return shares
