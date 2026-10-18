"""Session metrics."""


def session_minutes(session):
    return (session[-1]["at"] - session[0]["at"]).total_seconds() / 60


def summarize(sessions):
    if not sessions:
        return {"sessions": 0, "avg_minutes": 0.0}
    total = sum(session_minutes(s) for s in sessions)
    return {"sessions": len(sessions), "avg_minutes": round(total / len(sessions), 1)}
